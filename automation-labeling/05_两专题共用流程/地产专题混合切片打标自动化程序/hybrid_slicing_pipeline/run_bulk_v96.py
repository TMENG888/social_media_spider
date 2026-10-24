"""Full-source MapReduce/H -> single-unit dictionary recall -> local fallback.

One shared HTTP semaphore (10), per-source/stage checkpoints, real ODS comments,
exact dictionary identity, and all-attempt costs. No source or old output writes.
"""
import argparse,copy,json,os,time,threading
from pathlib import Path
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
import delivery_v4 as b
import delivery_v76 as mr
import delivery_v82 as h
import full_dictionary_supplement_v92 as s
from full_dictionary_supplement_v93 import ScopedApiRunner
import project_context_v90 as projects
import joint_keyword_supplement_v95 as joint
from final_definition_guard_v92 import final_scope_risks
from token_cost_report_v93 import report
from gym_policy_v96 import VERSION as POLICY_VERSION

VERSION='v96-500-per-topic-club-gym-policy'

class BulkRunner(ScopedApiRunner):
 def __init__(self,*args,**kwargs):
  super().__init__(*args,**kwargs);self.progress_lock=threading.Lock();self.counter=0
 def call(self,system,payload,doc,phase,response_schema=None):
  if payload.get('request_scope')=='single_unit':
   raw,metric=super().call(system,payload,doc,phase,response_schema)
  else:
   raw,metric=b.ApiRunner.call(self,system,payload,doc,phase,response_schema)
  with self.progress_lock:
   self.counter+=1
   if self.counter%100==0:
    costs=report(self.output)
    b.save_json(self.output/'api_progress.json',{'calls_seen':self.counter,'latest_source':doc['record_id'],
       'latest_phase':phase,'latest_status':metric['status'],'cost':costs['total']})
    print(b.dumps({'api_calls_seen':self.counter,'latest_phase':phase,'cost':costs['total']}),flush=True)
  return raw,metric

def h_context(base,taxonomy,runner):
 candidate=h.candidate_from_maps(base)
 d=h.supplement.run(base,candidate,taxonomy,runner)
 d['unrouted_map_proposals']=candidate['unrouted_map_proposals']
 index={t['tag_id']:t for t in taxonomy};checks=[]
 for row in d['rows']:
  for tag in row['标签明细']:
   tid=tag['标签路径ID']
   if tid in h.RISKY:
    decision=h.review_one(d,row,index[tid],runner,'context')
    checks.append({'unit_id':row['unit_id'],'tag_id':tid,'context':decision})
 return h.reconcile(d,checks,'Hflex')

def guard_new(result,prior,taxonomy):
 index=s.index_for(taxonomy,result['document']['topic']);old={(r['unit_id'],t['标签路径ID']) for r in prior['rows'] for t in r['标签明细']}
 for row,trace in zip(result['rows'],result['traces']):
  for proof in list(trace.get('全字典补选证据',[])):
   tid='VOC-'+proof['key'][1:]
   if (row['unit_id'],tid) in old:continue
   risks=final_scope_risks(proof,index,result['document'])
   if not risks:continue
   row['标签明细']=[t for t in row['标签明细'] if t['标签路径ID']!=tid]
   row['打标说明']='\n'.join(line for line in row['打标说明'].splitlines() if tid not in line)
   event={**proof,'处理':'新增标签必要证据不足转待核','原因':'；'.join(risks)}
   result['label_supplement_events'].append(event);result['label_supplement_deferred'].append(event)
   trace.setdefault('补选必要证据待核',[]).append(proof);trace['全字典补选证据'].remove(proof)
 result['label_supplement_deferred']=s.unique_deferred(result['label_supplement_deferred'])
 return result

def repair_content_fields(result,taxonomy,business,runner):
 """Only incomplete content is regenerated, one unit at a time; old tags stay."""
 index=s.index_for(taxonomy,result['document']['topic']);doc=result['document']
 for row,trace in zip(result['rows'],result['traces']):
  problems=s.fields.problems(row,doc)
  if not any(x in problems for x in ['无做法/摘要','无打标说明','文案复制原文','摘要过长','文章错误评论语体']):continue
  unit={'unit_id':row['unit_id'],'start':trace['起点'],'end':trace['终点'],'text':row.get('原文摘录',row.get('原始摘录')),
    'old_labels':[t['标签路径ID'] for t in row['标签明细']],'old_rewrite':row.get('具体产品做法',row.get('观点摘要')),'problems':problems}
  raw,check,cc,aa,ee=s.fields.run_group(result,[unit],index,business,runner)
  result['calls']+=cc;result['audit']+=aa
  draft=next((u for u in (raw or {}).get('units',[]) if u['unit_id']==row['unit_id']),None)
  ck=next((u for u in (check or {}).get('units',[]) if u['unit_id']==row['unit_id']),None)
  if draft and ck and ck['rewrite_ok'] and ck['confidence']>=.9 and draft['rewrite'] and not s.fields.validate_units({'units':[draft]},[unit],doc,index):
   row['具体产品做法' if doc['topic']==b.T1 else '观点摘要']=draft['rewrite']
   if not row['打标说明']:
    by={x['key']:x for x in draft['labels']}
    row['打标说明']='\n'.join(t['标签路径ID']+'｜'+by['D'+t['标签路径ID'][4:]]['reason']
      for t in row['标签明细'] if 'D'+t['标签路径ID'][4:] in by)
   trace['单片字段修复-v96']={'draft':draft,'check':ck,'issues':ee}
  else:
   row['备注']+='；文案字段补全未确认，保留原证据待核'
 return result

def validate_final(result,taxonomy):
 doc=result['document'];index={t['tag_id']:b.label_json(t) for t in taxonomy if doc['topic'] in t['topics']}
 assert len(result['rows'])==len(result['traces'])
 for row,trace in zip(result['rows'],result['traces']):
  assert row.get('原文摘录',row.get('原始摘录'))==doc['text'][trace['起点']:trace['终点']]
  ids=[t['标签路径ID'] for t in row['标签明细']];assert len(ids)==len(set(ids))
  for tag in row['标签明细']:assert tag==index[tag['标签路径ID']]
  if doc['kind']=='评论':
   assert len(result['rows'])<=1 and row['原始摘录']==doc['text']
   assert row['映射文章id']==(doc['row'].get('文章id') or None)
  row['验收状态']='需人工审核'
 return result

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--sample',type=Path,required=True);ap.add_argument('--taxonomy',type=Path,required=True)
 ap.add_argument('--output-dir',type=Path,required=True);ap.add_argument('--smoke-only',action='store_true');ap.add_argument('--finalize-only',action='store_true');a=ap.parse_args()
 sample=json.loads(a.sample.read_text(encoding='utf-8'));docs=sample['documents'];taxonomy=b.load_taxonomy(a.taxonomy);business=b.load_business()
 assert next(t for t in taxonomy if t['tag_id']=='VOC-0377')['instruction'].find('无需具体器械')>=0
 mr.activate();runner=BulkRunner(a.output_dir,10,key=os.getenv('YS_LLM_API_KEY'))
 implementation={n:Path(__file__).with_name(n).read_text(encoding='utf-8') for n in ['run_bulk_v96.py','gym_policy_v96.py','keyword_supplement_v94.py','joint_keyword_supplement_v95.py','full_dictionary_supplement_v92.py','label_definition_precision.py']}
 sig=b.digest({'version':VERSION,'policy':POLICY_VERSION,'code':implementation,'taxonomy':taxonomy,'business':business})
 lock=threading.Lock();done={};cores={};start=time.time()
 def checkpoint(stage,doc,fn,prior=None):
  dest=a.output_dir/'stages'/stage/(b.digest(doc['record_id'])+'.json');signature=b.digest({'code':sig,'document':doc,'input':prior})
  if dest.exists():
   old=json.loads(dest.read_text(encoding='utf-8'))
   if old.get('bulk_signature')==signature:return old['result']
  out=fn();b.save_json(dest,{'bulk_signature':signature,'result':out});return out
 def work(doc):
  if runner.fatal.is_set():raise RuntimeError('API authentication failed')
  core=checkpoint('01_mapreduce',doc,lambda:mr.process_document(doc,taxonomy,business,runner))
  with lock:cores[doc['record_id']]=core
  refined=checkpoint('02_D_H',doc,lambda:h_context(core,taxonomy,runner),core)
  recalled=checkpoint('03_single_unit',doc,lambda:s.process(refined,taxonomy,business,runner,a.output_dir,48,'single_unit'),refined)
  def finish():
   r=guard_new(copy.deepcopy(recalled),refined,taxonomy)
   r=joint.process(r,taxonomy);r=repair_content_fields(r,taxonomy,business,runner)
   r=projects.process(r,business,runner)
   r['bulk_policy_version']=POLICY_VERSION
   return validate_final(r,taxonomy)
  return checkpoint('04_final',doc,finish,recalled)
 # Real source smoke: one article per topic and one real complete comment.
 smoke=[next(d for d in docs if d['topic']==topic and d['kind']==kind) for topic,kind in [(b.T1,'文章'),(b.T2,'文章'),(b.T2,'评论')]]
 def consume(targets):
  with ThreadPoolExecutor(max_workers=10) as pool:
   for f in as_completed([pool.submit(work,d) for d in targets]):
    r=f.result()
    with lock:
     done[r['document']['record_id']]=r
     stats={'processed_sources':len(done),'planned_sources':len(docs),'processed_articles':Counter(x['document']['topic'] for x in done.values() if x['document']['kind']=='文章'),
       'processed_comments':sum(x['document']['kind']=='评论' for x in done.values()),'elapsed_seconds':round(time.time()-start),
       'latest_record_id':r['document']['record_id']}
     b.save_json(a.output_dir/'bulk_progress.json',stats);print(b.dumps(stats),flush=True)
 if not a.finalize_only:
  consume(smoke)
  gate={'passed':not runner.fatal.is_set() and all(r.get('label_supplement_coverage',{}).get('all_branches_checked') for r in done.values()),
    'source_ids':list(done),'note':'真实请求和全字典遍历合同测试，不是语义准确率'}
  b.save_json(a.output_dir/'bulk_smoke_gate.json',gate)
  if not gate['passed']:raise RuntimeError('Real-source smoke did not fully traverse dictionary; inspect checkpoints')
  if a.smoke_only:return
  consume([d for d in docs if d['record_id'] not in done])
 else:
  for doc in docs:
   file=a.output_dir/'stages'/'04_final'/(b.digest(doc['record_id'])+'.json')
   if not file.exists():raise RuntimeError('Missing final source: '+doc['record_id'])
   done[doc['record_id']]=json.loads(file.read_text(encoding='utf-8'))['result']
   cores[doc['record_id']]=json.loads((a.output_dir/'stages'/'01_mapreduce'/(b.digest(doc['record_id'])+'.json')).read_text(encoding='utf-8'))['result']
 results=[done[d['record_id']] for d in docs]
 assert len(results)==1956
 prior=b.export(a.output_dir/'core_baseline',[cores[d['record_id']] for d in docs],sample['sampling'],taxonomy,business,None,'api',True)
 data=b.export(a.output_dir,results,sample['sampling'],taxonomy,business,runner,'api',True)
 data['summary'].update(version=VERSION,planned_articles=1000,requested_articles_per_topic=500,bulk_source_complete=True,
     note='两专题各500篇真实来源，附带专题二所选文章956条真实去重评论；有据标签主表，未确认事实保留审核，不声称零漏标。')
 data['execution_manifest']={'requested_record_ids':[d['record_id'] for d in docs],'scope':'各专题500文章加全量关联评论','seed':20261008}
 data['supplement_status']={'sources':len(results),'fully_scanned_sources':sum(r['label_supplement_coverage']['all_branches_checked'] for r in results),
     'new_tags':sum(r['label_supplement_coverage']['new_confirmed_tags'] for r in results),'zero_miss_guarantee':False}
 data['delivery_changes']=[e for r in results for e in r.get('repair_changes',[])]
 data['current_run_token_cost']=report(a.output_dir)
 data['gym_policy']={'version':POLICY_VERSION,'label_id':'VOC-0377','instruction':next(t['instruction'] for t in taxonomy if t['tag_id']=='VOC-0377')}
 b.save_json(a.output_dir/'delivery_results.json',data);print(b.dumps({'finished':True,'summary':data['summary'],'cost':data['current_run_token_cost']['total']}),flush=True)

if __name__=='__main__':main()
