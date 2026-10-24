"""Missing recall stage for excluded records, only if the first batch is deficient.

Reuses Qwen transport/evidence contracts. Never runs beside the current generator,
never revisits an accepted source, never adds a tag by a Codex/keyword verdict.
"""
import argparse
import copy
import json
import os
import sys
import time
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor,FIRST_COMPLETED,wait
import voc_four_projects_v101 as p
from voc_four_literal_recovery_v101 import literal_project_references
from voc_four_single_truth_v101 import response_schema,derive_unit,request_system as single_system,repair_feedback,INSTRUCTION

LEVELS=['客户','市场','品牌','土地','产品','服务']
PHASE='专题二分支补漏复核-v101-完整输出'
SYSTEM=p.SYSTEM+'''
本次是排除结果的缺漏复查，只检查this_first_level指定分支，不是重新打已有成功标签。
专题二有客户、市场、品牌、土地、产品、服务六个一级分支。不是客户画像也可能适用其他分支。不能用“不是客户画像/动机/关注点”作为排除产品、土地、品牌、服务或市场事实的理由。
该分支每个标签均要核查，checked_tag_ids必须恰好列出本次branch_catalogue中每个编号一次。
units保持原切片不变，只返回本次requested_units。catalogue_checked表示已查本次完整分支；程序合并六分支后才算全目录完成。
历史无标签原因只是待复查资料，不能作为答案。有匹配理由即输出；无适用项给本分支具体原因，不强行打标，不制造客户身份、对象或数值口径。
旧排除裁决与错误响应原样留在检查点供追溯，不作为本次输出模板发送；以原文、本分支完整目录及精确字段错误独立完成复查。
每个views标签只来自本次branch_catalogue；其它分支会单独处理。publisher已由原程序完成，本阶段不重判、不返回发布者角色。
'''

def source_snapshot():
 return {r['record_id']:r for f in (p.OUT/'results').glob('*.json') if (r:=p.read(f))}

def selected(docs,records=None):
 if records is None:records=source_snapshot()
 counts=Counter();chosen=[]
 for d in docs:
  r=records.get(d['record_id'])
  if r is None or not p.metadata_eligible(d):continue
  if r['state']=='accepted' and counts[d['kind']]<p.TARGETS[d['kind']]:chosen.append(r);counts[d['kind']]+=1
 return chosen,counts

def prepare():
 docs=p.read(p.OUT/'candidate_documents.json');chosen,counts=selected(docs);available=Counter()
 for d in docs:
  file=p.path_for('results',d['record_id'])
  if file.exists() and p.metadata_eligible(d):
   r=p.read(file)
   if r['state']=='excluded' and not r.get('six_branch_recall_complete'):available[d['kind']]+=1
 result={'new_api_calls':0,'already_valid':dict(counts),'target':p.TARGETS,'eligible_exclusions_for_missing_stage':dict(available),
  'per_first_level_dictionary':dict(Counter(t['l1'] for t in p.read(p.OUT/'taxonomy.json'))),
  'not_a_parallel_generator':True,'accepted_sources_are_not_reprocessed':True,
  'run_only_if_deficient_and_after_generation_and_export_helpers_exit':True}
 p.save('branch_completion_plan.json',result);return result

def scan_schema(item,catalogue,branch,fields=None,references=None,project_slots=False,contexts=None):
 unit_schema=response_schema([item],catalogue,fields or {},references or [],branch,contexts)['properties']['units']
 return p.v.obj({'checked_tag_ids':{'type':'array','items':{'type':'string','enum':[t['tag_id'] for t in branch]}},'units':unit_schema})

def checked_keys_errors(raw,branch):
 keys=raw.get('checked_tag_ids') or [];expected={t['tag_id'] for t in branch}
 return [] if len(keys)==len(expected) and set(keys)==expected else ['未恰好逐一检查当前完整分支：需全部编号、不重复、不遗漏']


def feedback_without_answer_template(feedback):
 result=copy.deepcopy(feedback)
 if isinstance(result,dict):result.pop('previous_response_to_repair',None)
 return result

def merge_outcomes(uid,parts):
 if len(parts)!=len(LEVELS) or {level for level,unit in parts}!=set(LEVELS):raise RuntimeError('All six first-level branches must be completed')
 if any(unit['unit_id']!=uid for level,unit in parts):raise RuntimeError('Cross-unit branch merge forbidden')
 views={};facts=[];coverage=[]
 for level,unit in parts:
  coverage.append(level+'：'+unit['coverage_reason'])
  for fact in unit['facts']:facts.append(dict(copy.deepcopy(fact),reviewed_first_level=level))
  for view in unit['views']:
   pid=view['project_id']
   if pid not in views:views[pid]=copy.deepcopy(view)
   else:
    target=views[pid]
    target['summary']+='；'+view['summary']
    for key in ['expressions','emotions']:target[key]=list(dict.fromkeys(target[key]+view[key]))
    existing={t['tag_id'] for t in target['labels']}
    if existing&{t['tag_id'] for t in view['labels']}:raise RuntimeError('Cross-branch dictionary id duplicate')
    target['labels']+=copy.deepcopy(view['labels'])
 return {'unit_id':uid,'reason':'Qwen按六个专题二分支补漏复核；保留其有据标签理由，不设Codex语义阈值',
  'catalogue_checked':True,'coverage_reason':'；'.join(coverage),'facts':facts,'views':list(views.values())}

def process(record,tax,projects,runner):
 rid=record['record_id'];doc=record['document'];sig=p.signature(doc,tax)
 if record['signature']!=sig or record['state']!='excluded':raise RuntimeError('Only exact excluded source can enter new recall stage')
 if any(o['views'] for o in record['outcomes'].values()):raise RuntimeError('Never replace previously accepted labels')
 if p.product.role_errors(record['publisher'],p.own_fields(doc)):raise RuntimeError('Original publisher stage incomplete')
 catalog=p.v.supplement.evidence_catalog(record['units']);combined={};proof=[]
 references=literal_project_references(p.context_fields(doc),projects)
 for item in record['units']:
  parts=[]
  for level in LEVELS:
   branch=[t for t in tax if t['l1']==level];scope=p.digest([sig,item,branch,SYSTEM])
   target=p.OUT/'branch_recall'/level/(p.digest([rid,item['unit_id']])+'.json')
   if target.exists():
    stored=p.read(target)
    if stored['signature']!=scope:raise RuntimeError('Saved branch scope signature differs')
    raw=stored['response'];calls=stored['calls']
   else:
    raw=None;calls=[];feedback=[]
    for attempt in range(4):
     if p.STOP.exists() or runner.fatal.is_set():return {'record_id':rid,'state':'recall_incomplete'}
     clean_feedback=feedback_without_answer_template(feedback)
     payload={'topic':p.v.b.T2,'this_first_level':level,'all_first_levels':LEVELS,'projects':projects,
      'branch_catalogue':[{'tag_id':t['tag_id'],'path':[t.get('l'+str(i)) for i in range(1,6)],'emphasis':t['emphasis'],'definition':t['instruction']} for t in branch],
      'source_kind':doc['kind'],'source_title':doc.get('title'),'source_text':doc['text'],
      'parent_identity_context':p.context_fields(doc) if doc['kind']=='评论' else None,
      'source_evidence':catalog,'requested_units':[item],'original_exclusion_verdict_digest':p.digest(record['outcomes'][item['unit_id']]),
      'literal_project_reference_options':references,'declared_identity_contexts':p.context_fields(doc),
      'failed_fields_only':clean_feedback,'field_repair_attempt':attempt+1,'output_contract':INSTRUCTION}
     retry_fields={item['unit_id']:clean_feedback} if clean_feedback else {}
     request_system=single_system(SYSTEM,retry_fields)
     response,metrics,audit,errors=p.v.review(request_system,payload,scan_schema(item,catalog,branch,p.own_fields(doc),references,contexts=p.context_fields(doc)),doc,PHASE+'-'+level,runner)
     calls.append({'attempt':attempt+1,'calls':metrics,'protocol_errors':errors})
     if not response or errors:
      feedback=['当前分支响应协议未完成，仅重试未保存分支；已保存分支不重跑']+list(errors or [])
      if any(m.get('http_status') in (400,404,405,413,422) for m in metrics):break
      continue
     feedback=checked_keys_errors(response,branch)
     if len(response['units'])!=1 or response['units'][0]['unit_id']!=item['unit_id']:feedback.append('返回单元遗漏或重复')
     else:
      raw_unit=copy.deepcopy(response['units'][0])
      try:unit=derive_unit(raw_unit)
      except (ValueError,KeyError,TypeError) as e:
       feedback={'errors':['单一裁决证据字段未完成：'+str(e)],'repair_contract':INSTRUCTION};continue
      response['units']=[unit]
      feedback+=p.validate_unit(unit,item,catalog,doc,{t['tag_id']:t for t in branch})
     if not feedback:raw=response;break
     if len(response['units'])==1 and response['units'][0]['unit_id']==item['unit_id']:
      feedback=repair_feedback(response['units'][0],raw_unit,item,catalog,feedback,references,p.context_fields(doc))
    if raw is None:
     p.save('branch_recall_failures/'+p.digest([rid,item['unit_id'],level])+'.json',{'record_id':rid,'unit_id':item['unit_id'],'level':level,'calls':calls,'feedback':feedback})
     return {'record_id':rid,'state':'recall_incomplete'}
    p.atomic_save_json(target,{'signature':scope,'response':raw,'calls':calls,'original_source_signature':sig})
   if checked_keys_errors(raw,branch):raise RuntimeError('Cached branch incomplete')
   unit=raw['units'][0]
   if p.validate_unit(unit,item,catalog,doc,{t['tag_id']:t for t in branch}):raise RuntimeError('Cached branch evidence contract invalid')
   parts.append((level,unit));proof.append({'unit_id':item['unit_id'],'level':level,'branch_file':str(target),'sha256':p.v.sha(target),'checked_tag_ids':raw['checked_tag_ids']})
  outcome=merge_outcomes(item['unit_id'],parts)
  if p.validate_unit(outcome,item,catalog,doc,{t['tag_id']:t for t in tax}):raise RuntimeError('Combined branch evidence contract invalid')
  combined[item['unit_id']]=outcome
 # Preserve the prior successful exclusion result and original unit cache.
 file=p.path_for('results',rid);current=p.read(file)
 if current['state']!='excluded' or current['signature']!=sig:raise RuntimeError('Source changed during recall')
 backup=p.OUT/'branch_original_exclusions'/(p.digest(rid)+'.json')
 if not backup.exists():p.atomic_save_json(backup,current)
 result=copy.deepcopy(current);result['outcomes']=combined;result['six_branch_recall_complete']=True;result['branch_recall_proof']=proof
 result['state']='accepted' if any(u['views'] for u in combined.values()) else 'excluded'
 p.atomic_save_json(file,result)
 return {'record_id':rid,'state':result['state']}

def run(concurrency,limit=0,recovery_policy=False):
 if not 1<=concurrency<=20 or limit<0:raise ValueError('Concurrency 1..20; nonnegative pilot limit')
 if p.LOCK.exists() or (p.OUT/'finalize_v101/instance.lock').exists():raise RuntimeError('Current generation/export helper must drain first; no parallel launch')
 if p.STOP.exists():raise RuntimeError('Soft-stop flag present; do not implicitly restart')
 docs=p.read(p.OUT/'candidate_documents.json');records=source_snapshot();chosen,counts=selected(docs,records)
 if all(counts[k]>=n for k,n in p.TARGETS.items()):return {'state':'not_needed','counts':dict(counts)}
 tax=p.read(p.OUT/'taxonomy.json');projects=p.read(p.OUT/'projects.json')
 runner=p.configure_runner(concurrency,recovery_policy=True) if recovery_policy else p.configure_runner(concurrency)
 started=time.time()
 fd=os.open(p.LOCK,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,json.dumps({'pid':os.getpid(),'started_at':started,'script':__file__}).encode());os.close(fd)
 p.save('pre_branch_generation_status.json',p.read(p.OUT/'run_status.json'));p.save('pre_branch_launcher_identity.json',p.read(p.OUT/'launcher_identity.json'))
 p.save('launcher_identity.json',{'pid':os.getpid(),'started_at':started,'script':__file__,'script_sha256':p.v.sha(__file__),
  'version':p.VERSION,'model':runner.model,'base':runner.base,'concurrency_ceiling':concurrency,'credentials_saved':False,'stage':'six_branch_exclusion_completion',
  'governor_policy':'RecoveryPolicyCandidate' if recovery_policy else 'AdaptiveGovernor'})
 active={};errors=[];processed=0
 candidates=[]
 for d in docs:
  file=p.path_for('results',d['record_id'])
  if not file.exists() or not p.metadata_eligible(d):continue
  r=p.read(file)
  if r['state']=='excluded' and not r.get('six_branch_recall_complete'):candidates.append(r)
 def status(state):
  chosen,nums=selected(docs,records)
  result={'version':p.VERSION,'pid':os.getpid(),'started_at':started,'updated_at':time.time(),'state':state,'accepted_sources':dict(nums),
   'target':p.TARGETS,'active_sources':[r['record_id'] for r in active.values()],'processed_this_run':processed,'errors':errors,
   'elapsed_seconds':time.time()-started,'concurrency_ceiling':concurrency,'partial_not_delivery':True,'stage':'six_branch_exclusion_completion'}
  p.save('run_status.json',result);return result
 try:
  status('running')
  with ThreadPoolExecutor(max_workers=concurrency) as pool:
   while True:
    _,counts=selected(docs,records)
    for record in list(candidates):
     kind=record['kind'];busy=sum(r['kind']==kind for r in active.values())
     if len(active)>=concurrency or counts[kind]+busy>=p.TARGETS[kind]:continue
     if limit and processed+len(active)>=limit:continue
     if p.STOP.exists() or runner.fatal.is_set():break
     active[pool.submit(process,record,tax,projects,runner)]=record;candidates.remove(record)
    if not active:break
    done,_=wait(active,timeout=15,return_when=FIRST_COMPLETED)
    for future in done:
     record=active.pop(future);processed+=1
     try:
      r=future.result()
      if r['state']=='recall_incomplete':errors.append({'record_id':r['record_id'],'reason':'branch_recall_incomplete'})
      else:records[r['record_id']]=p.read(p.path_for('results',r['record_id']))
     except Exception as e:errors.append({'record_id':record['record_id'],'error_type':type(e).__name__})
    status('running')
  chosen,counts=selected(docs,records);p.save('selected_results.json',chosen)
  final=status('generation_complete_pending_export' if all(counts[k]>=n for k,n in p.TARGETS.items()) else 'pilot_complete' if limit else 'generation_incomplete')
  p.save('completion.json',dict(final,finished_at=time.time(),active_sources=[]));return final
 finally:
  if p.LOCK.exists() and p.read(p.LOCK)['pid']==os.getpid():p.LOCK.unlink()

if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');a=argparse.ArgumentParser();a.add_argument('--run',action='store_true');a.add_argument('--concurrency',type=int,default=20);a.add_argument('--limit',type=int,default=0);a.add_argument('--recovery-policy',action='store_true');args=a.parse_args();print(json.dumps(run(args.concurrency,args.limit,args.recovery_policy) if args.run else prepare(),ensure_ascii=False))
