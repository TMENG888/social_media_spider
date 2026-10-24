"""Missing candidate routing, using the unchanged Qwen processor and scheduler.

Short names only admit candidates; they NEVER assign a project or a label.
No requests may run beside the existing recall/controller. Original candidate
file, dictionary, successful checkpoints and core remain unchanged on disk.
"""
import argparse
import copy
import os
import sys
import time
from pathlib import Path
import voc_four_projects_v101 as p
from followup_voc_four_once_v101 import processes

CONTROL='short_name_extension_v101'
REVISION='short-name-routing-existing-qwen-processor-v101-1'
TERMS=('海晏','安澜','熙瑞','臻云')


def routed_extensions(original, inherited):
 known={d['record_id'] for d in original};seen=set(known);items=[]
 for doc in inherited:
  rid=doc['record_id'];score=p.number(doc['row'].get('情绪评分'))
  if rid in seen or doc['kind']!='评论' or not p.metadata_eligible(doc) or score is None or not 0<=score<=100:continue
  if doc.get('topic')!=p.v.b.T2:raise ValueError('Cross-topic candidate')
  clues=[{'field':field,'literal_short_name':term} for field,text in p.context_fields(doc).items() for term in TERMS if term in text]
  if not clues:continue
  items.append({'document':copy.deepcopy(doc),'routing_clues_not_assignments':clues});seen.add(rid)
 return items


def prepare():
 original=p.read(p.OUT/'candidate_documents.json')
 inherited=p.read(p.OUT/'inputs/candidate_documents.json')
 items=routed_extensions(original,inherited)
 value={'revision':REVISION,'new_api_calls':0,'prepared_at':time.time(),
  'original_candidates_sha256':p.v.sha(p.OUT/'candidate_documents.json'),
  'inherited_candidates_sha256':p.v.sha(p.OUT/'inputs/candidate_documents.json'),
  'taxonomy_sha256':p.v.sha(p.OUT/'taxonomy.json'),'main_sha256':p.v.sha(p.__file__),
  'terms':list(TERMS),'candidate_count':len(items),'items':items,
  'project_assignment_by_qwen_only':True,'original_candidates_unchanged':True,
  'requires_existing_recall_and_controller_naturally_finished':True}
 target=p.OUT/CONTROL/'plan.json'
 if target.exists():
  old=p.read(target)
  for key in ('revision','original_candidates_sha256','inherited_candidates_sha256','taxonomy_sha256','main_sha256','items'):
   if old[key]!=value[key]:raise RuntimeError('Prepared source/code scope changed; preserve prior plan')
  return old
 p.save(CONTROL+'/plan.json',value);return value


def assert_drained(allow_complete=False):
 if p.LOCK.exists() or (p.OUT/'finalize_v101/instance.lock').exists() or p.STOP.exists():raise RuntimeError('Existing generation/export/stop owner remains')
 follow=p.read(p.OUT/'followup_once_v101/status.json')
 if follow['state']!='under_target_after_existing_recall':raise RuntimeError('Existing recall must finish naturally and remain under target first')
 state=p.read(p.OUT/'run_status.json');launch=p.read(p.OUT/'launcher_identity.json')
 terminal=('generation_incomplete','pilot_complete','generation_complete_pending_export') if allow_complete else ('generation_incomplete','pilot_complete')
 if state['pid']!=launch['pid'] or state['started_at']!=launch['started_at'] or state['active_sources'] or state['state'] not in terminal:
  raise RuntimeError('Terminal current launch not proven')
 if processes(list({launch['pid'],follow['pid']})):raise RuntimeError('An exact generation/controller owner is still alive')
 comments=state['accepted_sources'].get('评论',0)
 if state['accepted_sources'].get('文章')!=500 or comments>500 or (not allow_complete and comments>=500):raise RuntimeError('This supplement is only for the missing comment quota')
 return state


def documents(plan):
 if p.v.sha(p.OUT/'candidate_documents.json')!=plan['original_candidates_sha256'] or p.v.sha(p.OUT/'inputs/candidate_documents.json')!=plan['inherited_candidates_sha256']:
  raise RuntimeError('Frozen candidate input changed')
 if p.v.sha(p.__file__)!=plan['main_sha256'] or p.v.sha(p.OUT/'taxonomy.json')!=plan['taxonomy_sha256']:raise RuntimeError('Qwen core/dictionary changed')
 original=p.read(p.OUT/'candidate_documents.json')
 return original+[item['document'] for item in plan['items']]


def assert_budget_window():
 finish=p.read(p.OUT/'completion.json');launch=p.read(p.OUT/'launcher_identity.json')
 if finish['pid']!=launch['pid'] or finish['started_at']!=launch['started_at'] or finish['active_sources']:
  raise RuntimeError('Last completed budget owner is not bound to the current launcher')
 elapsed=time.time()-finish['finished_at']
 if not elapsed>=65:raise RuntimeError('Wait for the previous rolling TPM/RPM window to expire before starting a fresh limiter')


def capture_pilot():
 assert_drained();plan=prepare();docs=documents(plan)
 pending=[item['document']['record_id'] for item in plan['items'] if not p.path_for('results',item['document']['record_id']).exists()]
 if len(pending)<2:raise RuntimeError('Need exactly two unprocessed candidate sources')
 path=p.OUT/CONTROL/'pilot_baseline.json'
 if path.exists():raise RuntimeError('Preserve the first pilot baseline')
 files={}
 for folder in ('results','seeds','unit_results','targeted_tag_reviews'):
  for file in (p.OUT/folder).glob('*.json'):files[str(file.relative_to(p.OUT))]=p.v.sha(file)
 value={'at':time.time(),'pilot_record_ids':pending[:2],'preserved_files':files,
  'plan_sha256':p.v.sha(p.OUT/CONTROL/'plan.json'),'adapter_sha256':p.v.sha(__file__),
  'no_api_calls':True,'scope_source_count':len(docs)}
 p.save(CONTROL+'/pilot_baseline.json',value);return value


def run(pilot=False,concurrency=20):
 assert_drained();plan=prepare();docs=documents(plan)
 if not 1<=concurrency<=20:raise ValueError('Maximum authorized concurrency is 20')
 base=p.read(p.OUT/CONTROL/'pilot_baseline.json')
 if p.v.sha(p.OUT/CONTROL/'plan.json')!=base['plan_sha256'] or p.v.sha(__file__)!=base['adapter_sha256']:raise RuntimeError('Pilot scope/code changed')
 if pilot:
  if concurrency!=2:raise ValueError('Pilot must use exactly two concurrent slots')
  if any(p.path_for('results',rid).exists() for rid in base['pilot_record_ids']):raise RuntimeError('Do not repeat a saved pilot source')
 else:
  proof=p.read(p.OUT/CONTROL/'pilot_verification.json')
  if proof.get('passed') is not True or proof.get('pilot_record_ids')!=base['pilot_record_ids'] or proof.get('plan_sha256')!=base['plan_sha256'] or proof.get('adapter_sha256')!=base['adapter_sha256']:
   raise RuntimeError('Independent exact two-source pilot proof required')
 assert_budget_window()
 original_read=p.read;original_save=p.save;docs_path=p.OUT/'candidate_documents.json'
 def reader(path):return copy.deepcopy(docs) if Path(path)==docs_path else original_read(path)
 def saver(name,value):
  if name=='launcher_identity.json':value=dict(value,adapter_script=str(Path(__file__).resolve()),adapter_sha256=p.v.sha(__file__),
   stage='short_name_candidate_supplement',adapter_revision=REVISION,extension_plan_sha256=base['plan_sha256'],
   short_names_are_routing_only=True,original_candidates_unchanged=True)
  return original_save(name,value)
 p.read=reader;p.save=saver
 try:
  return p.run(concurrency,2 if pilot else 0,recovery_policy=True,pilot_record_ids=base['pilot_record_ids'] if pilot else None)
 finally:p.read=original_read;p.save=original_save


if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');a=argparse.ArgumentParser()
 a.add_argument('--run',action='store_true');a.add_argument('--pilot',action='store_true');a.add_argument('--capture-pilot',action='store_true');a.add_argument('--concurrency',type=int,default=20)
 args=a.parse_args()
 if args.capture_pilot:result=capture_pilot()
 elif args.run:result=run(args.pilot,args.concurrency)
 else:
  plan=prepare();result={k:v for k,v in plan.items() if k!='items'}
 print(p.json.dumps(result,ensure_ascii=False))
