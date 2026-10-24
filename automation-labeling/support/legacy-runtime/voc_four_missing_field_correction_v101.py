"""Prepared missing-stage pilot; NEVER imported by the live generator.

Adds the last unsuccessful formal response and exact mechanical errors to a
new request. Does not normalize quotes, drop labels, or change acceptance rules.
Execution must wait for both owners to drain; successful units remain reusable.
"""
import argparse
import copy
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor,as_completed
import voc_four_projects_v101 as p
from voc_four_single_truth_v101 import PHASE, derive_unit, repair_feedback

REVISION='missing-field-explicit-formal-feedback-v101-2'
CONTROL='missing_field_correction_pilot_v2'


def corrected_request(original,system,payload,schema,doc,phase,runner,tax):
 """Promote precise errors; do not feed an entire invalid answer back as a template."""
 detail=context_for(doc,payload['requested_units'],tax)
 detail=copy.deepcopy(detail);detail.pop('earlier_response',None)
 exact=detail.get('exact_field_feedback')
 if isinstance(exact,dict):exact.pop('previous_response_to_repair',None)
 enriched=copy.deepcopy(payload);enriched['saved_unsuccessful_response_correction']=detail
 instruction=('\n本次为未保存字段纠错。以下机械错误必须逐项解决，不能复制旧错误。'
  '同项目同tag_id只能有一条，多个对象或证据须由你合并在这一条的object、reason、attribute_keys中，不能再输出第二条。'
  'project_identity.quote必须是对应字段连续原文，不允许用...、…或省略号拼接两段。'
  '若一段话太长可选其中连续短句；不要把概括写成原文引文。'
  '项目归属仍由你按实际原文判断，不能把不同楼盘当四项目的别名。'
  '保持完整目录和逐事实自检，不为通过字段检查虚构标签。当前精确纠错：'+p.json.dumps(detail,ensure_ascii=False))
 return original(system+instruction,enriched,schema,doc,phase+'-精确字段纠错2',runner)


def assert_drained():
 if p.LOCK.exists() or (p.OUT/'finalize_v101/instance.lock').exists():
  raise RuntimeError('Both owners must drain before missing-field correction')
 if p.STOP.exists():raise RuntimeError('Soft-stop request remains active')


def context_for(doc,requested,tax):
 rid=doc['record_id'];file=p.path_for('results',rid)
 if not file.exists():raise ValueError('Correction requires an existing unfinished source')
 record=p.read(file)
 if record['state']!='retry_required':raise ValueError('Never rerun a successful terminal source')
 if record['signature']!=p.signature(doc,tax):raise ValueError('Source signature changed')
 ids=[u['unit_id'] for u in requested]
 if len(ids)!=1 or ids[0] not in record['unfinished_units']:
  raise ValueError('Only one explicitly unfinished unit may be corrected')
 if p.path_for('unit_results',rid+'|'+ids[0]).exists():
  raise ValueError('Successful unit checkpoint cannot be corrected')
 history=next((h for h in reversed(record['request_history']) if ids[0] in h['unit_ids'] and h.get('calls')),None)
 if history is None:
  return {'revision':REVISION,'unit_id':ids[0],'earlier_response':None,
   'mechanical_errors':['尚无该缺失单元的正式响应；按完整原文和完整目录处理，不沿用其他片答案。']}
 metric=history['calls'][-1];formal=p.OUT/'calls'/(metric['request_key']+'.json');call=p.read(formal)
 if call['metrics']['record_id']!=rid:raise ValueError('Formal response source mismatch')
 raw=call.get('response');catalog=p.v.supplement.evidence_catalog(record['units'])
 index={t['tag_id']:t for t in tax};errors=list(history.get('protocol_errors') or []);feedback=None
 if isinstance(raw,dict):
  candidates=[u for u in raw.get('units',[]) if u.get('unit_id')==ids[0]]
  if len(candidates)==1:
   try:
    unit=derive_unit(candidates[0]);errors+=p.validate_unit(unit,requested[0],catalog,doc,index)
    feedback=repair_feedback(unit,candidates[0],requested[0],catalog,errors,[],p.context_fields(doc))
   except (ValueError,KeyError,TypeError):errors.append('旧正式响应结构尚未闭环；由Qwen完整纠正当前单元。')
  else:errors.append('旧正式响应中当前单元遗漏或重复')
  if not record.get('publisher'):
   _,role_errors,_=_role(record,raw,doc)
   errors+=role_errors
 return {'revision':REVISION,'unit_id':ids[0],
  'previous_formal_response_sha256':p.v.sha(formal),'earlier_response':copy.deepcopy(raw),
  'mechanical_errors':list(dict.fromkeys(errors)), 'exact_field_feedback':feedback,
  'instruction':'这是未成功保存字段的新修复请求。依据原文自行纠正，不机械复制旧答案；'
   '不为补字段制造标签，也不得丢掉有据标签。项目引文逐字复制对应原文字段；同项目同标签只输出一次。'}


def _role(record,raw,doc):
 from voc_four_literal_recovery_v101 import choose_publisher
 return choose_publisher(record.get('publisher'),raw.get('publisher') or {},p.own_fields(doc))


def run_exact_sources(record_ids,docs,tax):
 """Two explicit corrections even if the general article quota is already full.

 Keep the main completion/selection unchanged. A later cohort reconciliation
 selects the final 500+500; correcting a missing source never pads that count.
 """
 assert_drained()
 if len(record_ids)!=2 or len(set(record_ids))!=2:raise ValueError('Exactly two distinct sources required')
 p.pilot_selection(record_ids,2)
 origins=p.read(p.OUT/'partition_index.json');projects=p.read(p.OUT/'projects.json')
 prior={r['record_id']:r for r in p.read(p.OUT/'inputs/selected_sources.json')}
 started=time.time();owner={'pid':os.getpid(),'started_at':started,'script':__file__}
 fd=os.open(p.LOCK,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
 os.write(fd,p.json.dumps(owner).encode());os.close(fd)
 results=[]
 try:
  runner=p.configure_runner(2,recovery_policy=True)
  p.save(CONTROL+'/launcher_identity.json',dict(owner,script_sha256=p.v.sha(__file__),
   main_script_sha256=p.v.sha(p.__file__),record_ids=record_ids,concurrency_ceiling=2,
   governor_policy='RecoveryPolicyCandidate',credentials_saved=False))
  p.save(CONTROL+'/status.json',dict(owner,state='running',record_ids=record_ids))
  with ThreadPoolExecutor(max_workers=2) as pool:
   futures={pool.submit(p.process,docs[rid],tax,projects,origins,prior,runner):rid for rid in record_ids}
   for future in as_completed(futures):
    rid=futures[future]
    try:
     result=future.result();results.append({'record_id':rid,'state':result['state'],
      'unfinished_units':result['unfinished_units']})
    except Exception as error:results.append({'record_id':rid,'state':'error','error_type':type(error).__name__})
  proof=dict(owner,finished_at=time.time(),state='pilot_complete',record_ids=record_ids,
   processed_sources=len(results),results=results,main_selection_and_completion_unchanged=True,
   not_final_delivery=True)
  p.save(CONTROL+'/completion.json',proof);p.save(CONTROL+'/status.json',proof)
  return proof
 finally:
  if p.LOCK.exists() and p.read(p.LOCK)['pid']==owner['pid']:p.LOCK.unlink()


def pilot(record_ids):
 assert_drained();p.pilot_selection(record_ids,2)
 tax=p.read(p.OUT/'taxonomy.json');docs={d['record_id']:d for d in p.read(p.OUT/'candidate_documents.json')}
 original=p.v.review
 def review(system,payload,schema,doc,phase,runner):
  if phase!=PHASE:return original(system,payload,schema,doc,phase,runner)
  return corrected_request(original,system,payload,schema,doc,phase,runner,tax)
 for rid in record_ids:
  record=p.read(p.path_for('results',rid))
  context_for(docs[rid],[next(u for u in record['units'] if u['unit_id']==record['unfinished_units'][0])],tax)
 p.v.review=review
 try:return run_exact_sources(record_ids,docs,tax)
 finally:p.v.review=original


if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8')
 parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');parser.add_argument('--record-id',action='append',default=[])
 args=parser.parse_args()
 if args.run:print(p.json.dumps(pilot(args.record_id),ensure_ascii=False))
 else:print(p.json.dumps({'prepared_only':True,'new_api_calls':0,'requires_both_owners_drained':True,'revision':REVISION}))
