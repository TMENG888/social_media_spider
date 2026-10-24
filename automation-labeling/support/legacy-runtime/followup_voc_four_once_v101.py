"""One-shot authorized stage chain after exact current owners naturally drain.

Not a recurring automation and not a parallel generator. No requests while the
bound generator/finalizer are alive. Every model stage is an existing script;
the two-source six-branch pilot must independently pass before its shared run.
Even a saved verified workbook remains pending the agent's final visual review.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
import voc_four_projects_v101 as p

WORK=Path(__file__).resolve().parent
CONTROL=p.OUT/'followup_once_v101'
REVISION='natural-drain-single-stage-chain-v101-2'


def processes(pids):
 if not pids or any(type(pid) is not int or pid<=0 for pid in pids):raise ValueError('Exact positive integer PIDs required')
 predicate=' OR '.join('ProcessId='+str(pid) for pid in pids)
 script=("$ErrorActionPreference='Stop'; @(Get-CimInstance Win32_Process -Filter \""+predicate+
  "\" | ForEach-Object { [pscustomobject]@{pid=$_.ProcessId;created=$_.CreationDate.ToString('yyyy-MM-ddTHH:mm:ss.ffffffzzz');command=$_.CommandLine} }) | ConvertTo-Json -Compress")
 result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True,encoding='utf-8',errors='strict',timeout=20)
 if result.returncode:raise RuntimeError('Authoritative local process query failed; no generation launched')
 value=json.loads(result.stdout.strip()) if result.stdout.strip() else []
 if isinstance(value,dict):value=[value]
 return {item['pid']:item for item in value}


def soft_markers():
 return {file.name:p.v.sha(file) for file in (p.OUT/'control').glob('soft_stop*') if file.is_file()}


def save(state,**extra):
 p.atomic_save_json(CONTROL/'status.json',{'at':time.time(),'pid':os.getpid(),'state':state,'revision':REVISION,
  'not_delivered':True,**extra})


def capture_bound():
 launch=p.read(p.OUT/'launcher_identity.json');state=p.read(p.OUT/'run_status.json')
 export=p.read(p.OUT/'finalize_v101/instance.lock')
 if state['state']!='running' or state['pid']!=launch['pid'] or state['started_at']!=launch['started_at']:
  raise RuntimeError('Only a verified currently running launch can be bound')
 live=processes([launch['pid'],export['pid']])
 if set(live)!={launch['pid'],export['pid']}:raise RuntimeError('Both exact owners must be live at registration')
 main_entry=Path(launch.get('adapter_script',launch['script'])).name
 if main_entry not in live[launch['pid']]['command'] or 'finalize_voc_four_projects_v101.py' not in live[export['pid']]['command']:
  raise RuntimeError('Live command does not match the bound launcher')
 if p.STOP.exists():raise RuntimeError('Cannot bind an interrupted launch')
 return {'launch':launch,'owners':live,'soft_markers':soft_markers(),'bound_at':time.time()}


def natural_drain_check(bound,live,state,launch,main_lock,export_lock,markers,stop=False,cancel=False):
 if cancel:return 'cancelled'
 if stop or markers!=bound['soft_markers']:raise RuntimeError('A stop request was observed; natural drain not proven')
 if launch!=bound['launch']:raise RuntimeError('Bound generation identity changed; no implicit follow-on launch')
 for pid,owner in live.items():
  original=bound['owners'].get(str(pid),bound['owners'].get(pid))
  if original is None or owner!=original:raise RuntimeError('PID reuse or another live owner detected')
 if state['pid']!=launch['pid'] or state['started_at']!=launch['started_at']:raise RuntimeError('Run state is not bound to launch')
 if live or main_lock or export_lock or state['state']=='running':return 'wait'
 if state.get('active_sources'):raise RuntimeError('Terminal status still reports in-flight work')
 if state['state'] not in ('generation_incomplete','generation_complete_pending_export'):
  raise RuntimeError('Natural generation completion is not proven by this terminal state')
 return 'drained'


def wait_for_natural_drain(bound):
 missing_since=None
 while True:
  ids=[int(pid) for pid in bound['owners']];live=processes(ids)
  launch=p.read(p.OUT/'launcher_identity.json');state=p.read(p.OUT/'run_status.json')
  verdict=natural_drain_check(bound,live,state,launch,p.LOCK.exists(),(p.OUT/'finalize_v101/instance.lock').exists(),soft_markers(),
   p.STOP.exists(),(CONTROL/'cancel.request').exists())
  save('waiting_for_exact_natural_drain' if verdict=='wait' else verdict,
   current_actual_live_owners=live,accepted_sources=state['accepted_sources'],last_actual_process_check_at=time.time(),new_api_calls_by_controller=0)
  if verdict!='wait':return verdict
  if not live:
   missing_since=missing_since or time.time()
   if time.time()-missing_since>90:raise RuntimeError('Owners missing but terminal drain not proven; no recovery launched')
  else:missing_since=None
  time.sleep(20)


def run_command(name,script,args=()):
 if (CONTROL/'cancel.request').exists() or p.STOP.exists():raise RuntimeError('Follow-on execution cancelled')
 if p.LOCK.exists() or (p.OUT/'finalize_v101/instance.lock').exists():raise RuntimeError('A generation/export owner remains active')
 save('executing_existing_stage',stage=name)
 with (CONTROL/(name+'_stdout.log')).open('x',encoding='utf-8') as out,(CONTROL/(name+'_stderr.log')).open('x',encoding='utf-8') as err:
  result=subprocess.run([sys.executable,str(WORK/script),*args],cwd=WORK.parent,stdout=out,stderr=err)
 if result.returncode:raise RuntimeError(name+' failed; preserved logs; no next stage launched')


def gate_branch_pilot(proof):
 if proof.get('passed') is not True or len(proof.get('pilot_sources',[]))!=2:
  raise RuntimeError('Exactly two independently verified branch sources are required')
 if proof.get('taxonomy_tags')!=580 or proof.get('first_levels')!=6 or not proof.get('original_exclusions_backed_up_exactly') or not proof.get('other_existing_checkpoints_unchanged'):
  raise RuntimeError('Pilot dictionary/provenance/preservation contract incomplete')


def rolling_window(name):
 # Every sequential script owns a fresh limiter. Let the previous owner's last
 # reservation age out before admitting any requests under a new limiter.
 save('waiting_for_rolling_window',previous_stage=name,seconds=65)
 for _ in range(13):
  if (CONTROL/'cancel.request').exists() or p.STOP.exists():raise RuntimeError('Cancelled before next model stage')
  time.sleep(5)


def after_drain():
 completion=p.read(p.OUT/'completion.json')
 # This human-authorized one-tag review changes neither source eligibility nor
 # other labels and is allowed only after natural generation drain.
 rolling_window('natural_generation_drain')
 run_command('targeted_voc0377','voc_four_targeted_tag_review_v101.py',('--run',))
 counts=completion['accepted_sources']
 if any(counts.get(kind,0)<n for kind,n in p.TARGETS.items()):
  rolling_window('targeted_voc0377')
  run_command('branch_pilot_capture','verify_voc_four_branch_pilot_v101.py',('--capture',))
  run_command('branch_pilot','complete_voc_four_branches_v101.py',('--run','--concurrency','2','--limit','2','--recovery-policy'))
  run_command('branch_pilot_verification','verify_voc_four_branch_pilot_v101.py')
  gate_branch_pilot(p.read(p.OUT/'six_branch_pilot_verification.json'))
  # Avoid resetting admission accounting inside the preceding rolling minute.
  rolling_window('branch_pilot')
  run_command('branch_full','complete_voc_four_branches_v101.py',('--run','--concurrency','20','--recovery-policy'))
 completion=p.read(p.OUT/'completion.json')
 if completion['state']!='generation_complete_pending_export' or completion['accepted_sources']!=p.TARGETS or completion['active_sources']:
  save('under_target_after_existing_recall',accepted_sources=completion['accepted_sources'],target=p.TARGETS,
   no_article_substitution_for_missing_comments=True);return
 run_command('final_saved_workbook','finalize_voc_four_projects_v101.py')
 result=p.read(p.OUT/'finalize_v101/status.json')
 if result['state']!='saved_verified_pending_visual_review':raise RuntimeError('Fresh saved workbook not independently verified')
 save('saved_verified_pending_agent_visual_review',book=result['book'],book_sha256=result['book_sha256'],
  all_14_fresh_sheets_must_be_reviewed=True,not_final_delivery=True)


def run():
 if CONTROL.exists():raise RuntimeError('One-shot directory already exists; do not duplicate or overwrite its evidence')
 bound=capture_bound();CONTROL.mkdir()
 p.atomic_save_json(CONTROL/'binding.json',bound)
 p.atomic_save_json(CONTROL/'launcher_identity.json',{'pid':os.getpid(),'started_at':time.time(),'script':str(Path(__file__).resolve()),
  'script_sha256':p.v.sha(__file__),'new_model_provider':False,'one_shot':True})
 try:
  verdict=wait_for_natural_drain(bound)
  if verdict=='cancelled':return
  terminal=p.read(p.OUT/'completion.json')
  if terminal['pid']!=bound['launch']['pid'] or terminal['started_at']!=bound['launch']['started_at'] or terminal['active_sources']:
   raise RuntimeError('Current completion is not the bound drained generation')
  after_drain()
 except Exception as error:
  save('stopped_without_delivery',error_type=type(error).__name__,error=str(error));raise


if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');args=parser.parse_args()
 if args.run:run()
 else:print(json.dumps({'prepared_only':True,'new_api_calls':0,'one_shot':True}))
