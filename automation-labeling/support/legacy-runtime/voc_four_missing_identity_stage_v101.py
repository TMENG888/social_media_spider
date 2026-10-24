"""Qwen-only identity-field completion, with a reproducible two-formal-response chain.

Only unsuccessful units whose sole mechanical error is a nonliteral project
identity quote qualify. The old full response, tag decisions and summaries are
immutable. The model supplies supported/unsupported and exact identity fields.
"""
import argparse
import copy
import os
import sys
import time
from pathlib import Path
import voc_four_projects_v101 as p
from voc_four_single_truth_v101 import PHASE as UNIT_PHASE,derive_unit
from voc_four_identity_citation_v101 import schema as identity_schema,errors as identity_errors,SYSTEM
import voc_four_missing_field_correction_v101 as c

PHASE='专题二未成功单元仅补项目引文-v101'
REVISION='missing-unit-identity-only-formal-chain-v101-1'
CONTROL='missing_identity_stage'


def rejection_path(rid,uid):return p.OUT/'unit_identity_rejections'/(p.digest([rid,uid])+'.json')


def save_rejection(doc,uid,repairs,calls,basefile):
 if not any(entry.get('supported') is False for entry in repairs.get('identity_repairs',{}).values()):return None
 for metric in reversed(calls):
  file=p.OUT/'calls'/(metric['request_key']+'.json')
  if file.exists() and p.read(file).get('response')==repairs:
   value={'record_id':doc['record_id'],'unit_id':uid,'source_signature':p.signature(doc,p.read(p.OUT/'taxonomy.json')),
    'base_formal':{'file':str(basefile),'sha256':p.v.sha(basefile)},
    'repair_formal':{'file':str(file),'sha256':p.v.sha(file)},'at':time.time()}
   p.atomic_save_json(rejection_path(doc['record_id'],uid),value);return value
 raise ValueError('Cannot store an unsupported-project verdict without formal model evidence')


def load_rejection(doc,uid,tax):
 file=rejection_path(doc['record_id'],uid)
 if not file.exists():return None
 proof=p.read(file)
 if proof['record_id']!=doc['record_id'] or proof['unit_id']!=uid or proof['source_signature']!=p.signature(doc,tax):raise ValueError('Identity rejection source changed')
 raw=formal(proof['repair_formal']['file'],proof['repair_formal']['sha256'],doc['record_id'],PHASE)
 base=formal(proof['base_formal']['file'],proof['base_formal']['sha256'],doc['record_id'])
 if not any(u.get('unit_id')==uid for u in base.get('units',[])):raise ValueError('Rejection has no original unit')
 if not any(entry.get('supported') is False for entry in raw.get('identity_repairs',{}).values()):raise ValueError('No unsupported Qwen identity verdict')
 return {'unit_id':uid,'formal_response_sha256':proof['repair_formal']['sha256'],
  'qwen_identity_reassessment':raw,'instruction':'这是Qwen自身独立补证后给出的不能支持归属结论，不是Codex语义意见。'
   '按实际原文重新检查当前未成功单元全部标签的项目归属；确无对应项目时据实留空并给逐事实排除理由，不能仅更换引文继续保留错配。'
   '也不要因此删除其他真实有据项目标签。'}


def prepare_existing_rejection(rid):
 """Recover the just-completed one-unit pilot's explicit model rejection, no API."""
 c.assert_drained();launch=p.read(p.OUT/CONTROL/'launcher_identity.json')
 if launch['record_id']!=rid:raise ValueError('Not the existing identity-only pilot')
 record=p.read(p.path_for('results',rid))
 if record['state']!='retry_required' or len(record['unfinished_units'])!=1:raise ValueError('Explicit single unfinished pilot unit required')
 uid=record['unfinished_units'][0];base=[];repairs=[]
 for file in (p.OUT/'calls').glob('*.json'):
  call=p.read(file);m=call['metrics'];raw=call.get('response')
  if m['record_id']!=rid or m['status']!='success' or not isinstance(raw,dict):continue
  if any(u.get('unit_id')==uid for u in raw.get('units',[])):base.append((file.stat().st_mtime_ns,file))
  if m['phase']==PHASE and any(x.get('supported') is False for x in raw.get('identity_repairs',{}).values()):repairs.append((file.stat().st_mtime_ns,file,call))
 if not base or not repairs:raise ValueError('Missing exact full-unit and explicit identity-only formal evidence')
 _,basefile=max(base,key=lambda x:x[0]);_,file,call=max(repairs,key=lambda x:x[0])
 return save_rejection(record['document'],uid,call['response'],[call['metrics']],basefile)


def slots_for(raw_unit,contexts):
 slots={}
 views=raw_unit['views'].values() if isinstance(raw_unit['views'],dict) else raw_unit['views']
 seen=set()
 for view in views:
  for label in view['labels']:
   key=view['project_id']+'|'+label['tag_id']
   if key in seen:raise ValueError('Duplicate labels need Qwen merge, not identity-only repair')
   seen.add(key);identity=label['project_identity'];field=identity['context_source'];quote=identity['quote']
   if field not in contexts or not quote or quote not in contexts[field]:
    slots[key]={'project_id':view['project_id'],**copy.deepcopy(label)}
 if not slots:raise ValueError('No invalid literal identity field to repair')
 return slots


def reconstruct(raw,unit_id,repairs,contexts):
 """Join only fields explicitly supplied by Qwen, with no quote normalization."""
 out=copy.deepcopy(raw);units=[u for u in out['units'] if u['unit_id']==unit_id]
 if len(units)!=1:raise ValueError('Exactly one matching model unit required')
 unit=units[0];slots=slots_for(unit,contexts);bad=identity_errors(repairs,slots,contexts)
 if bad:raise ValueError('; '.join(bad))
 views=unit['views'].values() if isinstance(unit['views'],dict) else unit['views']
 for view in views:
  for label in view['labels']:
   key=view['project_id']+'|'+label['tag_id']
   if key in slots:label['project_identity']=copy.deepcopy(repairs['identity_repairs'][key]['project_identity'])
 return out


def formal(file,sha,rid,phase=None):
 file=Path(file).resolve()
 if file.parent not in {(p.OUT/'calls').resolve(),(p.OUT/'call_attempt_history').resolve()}:
  raise ValueError('Only local formal ledger evidence is allowed')
 if p.v.sha(file)!=sha:raise ValueError('Formal response file changed')
 call=p.read(file);m=call['metrics']
 if m['record_id']!=rid or m['status']!='success' or (phase and m['phase']!=phase):
  raise ValueError('Formal response identity/status mismatch')
 return call['response']


def validated_chain(stored,doc,tax):
 rid=doc['record_id'];uid=stored['unit_id']
 if stored['record_id']!=rid or stored['source_signature']!=p.signature(doc,tax):raise ValueError('Source signature changed')
 base=stored['base_formal'];patch=stored['repair_formal']
 raw=formal(base['file'],base['sha256'],rid)
 repairs=formal(patch['file'],patch['sha256'],rid,PHASE)
 if stored['base_response_digest']!=p.digest(raw) or stored['repair_response_digest']!=p.digest(repairs):raise ValueError('Response chain changed')
 combined=reconstruct(raw,uid,repairs,p.context_fields(doc))
 units=[u for u in combined['units'] if u['unit_id']==uid]
 unit=derive_unit(units[0])
 seed=p.read(p.path_for('seeds',rid))['seed'];items=p.v.supplement.audit_units(seed)
 item=next(u for u in items if u['unit_id']==uid);cat=p.v.supplement.evidence_catalog(items)
 if p.validate_unit(unit,item,cat,doc,{t['tag_id']:t for t in tax}):raise ValueError('Identity-only completion still fails the mechanical contract')
 if p.digest(unit)!=stored['derived_unit_digest']:raise ValueError('Derived unit chain mismatch')
 return unit,combined


def proof_path(rid,uid):return p.OUT/'unit_field_corrections'/(p.digest([rid,uid])+'.json')


def try_identity_only(original,system,payload,schema,doc,phase,runner,tax):
 """Return None if this is not a strictly identity-only failed stage."""
 rid=doc['record_id'];requested=payload['requested_units']
 detail=c.context_for(doc,requested,tax)
 if set(detail.get('mechanical_errors') or [])!={'项目身份引文不可定位'}:return None
 record=p.read(p.path_for('results',rid));uid=requested[0]['unit_id']
 if not record.get('publisher'):return None
 old=detail.get('earlier_response')
 if not isinstance(old,dict):return None
 raw_unit=next((u for u in old.get('units',[]) if u['unit_id']==uid),None)
 if raw_unit is None:return None
 contexts=p.context_fields(doc);slots=slots_for(raw_unit,contexts)
 history=next(h for h in reversed(record['request_history']) if uid in h['unit_ids'] and h.get('calls'))
 basefile=p.OUT/'calls'/(history['calls'][-1]['request_key']+'.json')
 if p.read(basefile).get('response')!=old:raise RuntimeError('Original unsuccessful response changed')
 compact={'projects':p.read(p.OUT/'projects.json'),'source_kind':doc['kind'],
  'declared_identity_contexts':contexts,'unit_id':uid,'original_slice':requested[0],
  'supplied_labels':slots,'previous_errors':payload.get('failed_fields_only') or {},
  'attempt':payload.get('field_repair_attempt'),'base_formal_sha256':p.v.sha(basefile),
  'instruction':'只修复列出的项目身份引用。原标签、对象、理由、摘要不重打。不能支持既有项目时明确supported=false，不借用另一个楼盘作证。'}
 repairs,calls,audit,bad=original(SYSTEM,compact,identity_schema(slots,contexts),doc,PHASE,runner)
 if not repairs or bad:return None,calls,audit,bad or ['项目身份补证未返回']
 bad=identity_errors(repairs,slots,contexts)
 if bad:
  save_rejection(doc,uid,repairs,calls,basefile)
  return None,calls,audit,bad
 combined=reconstruct(old,uid,repairs,contexts)
 unit=derive_unit(next(u for u in combined['units'] if u['unit_id']==uid))
 catalogue=p.v.supplement.evidence_catalog(record['units'])
 bad=p.validate_unit(unit,requested[0],catalogue,doc,{t['tag_id']:t for t in tax})
 if bad:return None,calls,audit,bad
 repairfile=None
 for metric in calls:
  candidate=p.OUT/'calls'/(metric['request_key']+'.json')
  if candidate.exists() and p.read(candidate).get('response')==repairs:repairfile=candidate
 if repairfile is None:raise RuntimeError('Identity fields lack formal Qwen response')
 proof={'revision':REVISION,'at':time.time(),'record_id':rid,'unit_id':uid,'source_signature':record['signature'],
  'base_formal':{'file':str(basefile),'sha256':p.v.sha(basefile)},
  'repair_formal':{'file':str(repairfile),'sha256':p.v.sha(repairfile)},
  'base_response_digest':p.digest(old),'repair_response_digest':p.digest(repairs),
  'derived_unit_digest':p.digest(unit),'target_keys':list(slots),'label_summary_and_other_fields_unchanged':True}
 validated_chain(proof,doc,tax)
 target=proof_path(rid,uid)
 if target.exists() and p.read(target)!=proof:raise RuntimeError('Do not overwrite an existing successful field proof')
 p.atomic_save_json(target,proof)
 return combined,calls,audit,[]


def adapter(original,record_ids,tax):
 allowed=frozenset(record_ids)
 def review(system,payload,schema,doc,phase,runner):
  if phase==UNIT_PHASE and doc['record_id'] in allowed:
   rejection=load_rejection(doc,payload['requested_units'][0]['unit_id'],tax)
   if rejection:
    from voc_four_feedback_payload_v101 import without_rejected_answer_templates
    enriched=without_rejected_answer_templates(payload);enriched['formal_qwen_project_identity_reassessment']=rejection
    return c.corrected_request(original,system+'\n必须处理Qwen自身补证发现的项目不支持结论：'+p.json.dumps(rejection,ensure_ascii=False),enriched,schema,doc,phase+'-不沿用旧错配模板3',runner,tax)
   corrected=try_identity_only(original,system,payload,schema,doc,phase,runner,tax)
   if corrected is not None:return corrected
  return c.corrected_request(original,system,payload,schema,doc,phase,runner,tax) if phase==UNIT_PHASE and doc['record_id'] in allowed else original(system,payload,schema,doc,phase,runner)
 return review


def run_one(rid):
 c.assert_drained();baseline=p.read(p.OUT/c.CONTROL/'preservation_baseline.json')
 if rid not in baseline['record_ids']:raise ValueError('Only the same authorized two-source pilot may be continued')
 doc=next(d for d in p.read(p.OUT/'candidate_documents.json') if d['record_id']==rid)
 record=p.read(p.path_for('results',rid))
 if record['state']!='retry_required':raise ValueError('Never rerun a successful source')
 tax=p.read(p.OUT/'taxonomy.json');started=time.time();owner={'pid':os.getpid(),'started_at':started,'script':__file__}
 fd=os.open(p.LOCK,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,p.json.dumps(owner).encode());os.close(fd)
 original=p.v.review
 try:
  runner=p.configure_runner(2,recovery_policy=True)
  p.save(CONTROL+'/launcher_identity.json',dict(owner,record_id=rid,script_sha256=p.v.sha(__file__),main_sha256=p.v.sha(p.__file__),concurrency_ceiling=2))
  p.save(CONTROL+'/status.json',dict(owner,state='running',record_id=rid))
  p.v.review=adapter(original,{rid},tax)
  result=p.process(doc,tax,p.read(p.OUT/'projects.json'),p.read(p.OUT/'partition_index.json'),
   {r['record_id']:r for r in p.read(p.OUT/'inputs/selected_sources.json')},runner)
  finish=dict(owner,state='completed',record_id=rid,result_state=result['state'],unfinished_units=result['unfinished_units'],finished_at=time.time())
  p.save(CONTROL+'/completion.json',finish);p.save(CONTROL+'/status.json',finish);return finish
 finally:
  p.v.review=original
  if p.LOCK.exists() and p.read(p.LOCK)['pid']==os.getpid():p.LOCK.unlink()


if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');parser.add_argument('--record-id');args=parser.parse_args()
 print(p.json.dumps(run_one(args.record_id) if args.run else {'prepared_only':True,'new_api_calls':0},ensure_ascii=False))
