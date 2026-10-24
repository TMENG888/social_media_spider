"""Staged replacement entry. Requires human switch approval, drained PID, and real smoke.

Not launched while v99.3 is running. Same Qwen gateway, formal concurrency four;
pilot concurrency one. Successful signed sources/units are reused, not rerun.
"""
import argparse,os,sys,time
from pathlib import Path
import voc_batch_v99 as original
import voc_repair_overlay_v994 as overlay
from prepare_stage_reuse_v994 import old_pid_live

BASE_DRIVER_SHA='f3122d09d93617c6c2ace0ce0623de4178815d74f32ed705c45b53dd073847ef'
PILOT_IDS=['T2-8000912876517502691','T2-C-6923440650351499790','T2-C-1237984','T2-8000912876517503293','T2-C-2682002808526990393','T2-243441354646023807']
PRIOR_PENDING_PILOT_IDS=['T2-8000912876517502691','T2-8000912876517503293','T2-243441354646023807']

def prelaunch_guard():
    approval=original.read(original.OUT/'control'/'approval_to_switch_v994.json')
    if not approval.get('approved'):raise RuntimeError('Explicit user switch approval missing')
    reused=original.read(original.OUT/'stage_reuse_v994_applied.json')
    if not reused.get('passed') or reused.get('mode')!='applied':raise RuntimeError('Applied stage signature verification missing')
    if reused['new_overlay_sha256']!=original.sha(overlay.__file__):raise RuntimeError('Overlay changed after stage reuse')
    if (original.OUT/'control'/'instance.lock').exists() or old_pid_live(reused['old_primary_pid']):
        raise RuntimeError('Old generator still live/locked; do not start a second process')
    for frozen in original.read(original.OUT/'manifest.json')['frozen_inputs']:
        if original.sha(frozen['snapshot'])!=frozen['sha256']:raise RuntimeError('Frozen source changed')
    if original.sha(Path(__file__).with_name('run_voc_batch_driver_v99.py'))!=BASE_DRIVER_SHA:
        raise RuntimeError('Validated original driver changed')
    return reused

def pilot_gate(results,seeds,paths):
    def has_area(rid):
        return results[rid]['state']=='accepted' and any(t['标签路径ID']=='VOC-0186'
            for row in results[rid]['rows'] for t in row['标签明细'])
    clear_area_evidence=any(p.get('key')=='D0186' and any('建面约187-275㎡' in q for q in p.get('quotes',[]))
        for trace in results['T2-8000912876517502691'].get('traces',[]) for p in trace.get('标签证据与归属',[]))
    checks={
        'at_least_one_previously_pending_source_now_complete':any(results[rid]['state']=='accepted' and results[rid]['rows'] for rid in PRIOR_PENDING_PILOT_IDS),
        'known_missing_data_comment_not_price_tag':all(t['标签路径ID']!='VOC-0087' for row in results['T2-C-1237984']['rows'] for t in row['标签明细']),
        'known_missing_data_comment_closed':results['T2-C-1237984']['state']=='excluded',
        'named_facility_not_guessed_as_metro':all(t['标签路径ID']!='VOC-0142' for row in results['T2-C-2682002808526990393']['rows'] for t in row['标签明细']),
        'named_facility_summary_no_added_station_or_line':all(not any(term in row['观点摘要'] for term in ['地铁站','12号线']) for row in results['T2-C-2682002808526990393']['rows']),
        'long_anchor_source_boundary_review_saved_without_erasing_uncertainty':bool(
            seeds.get('T2-8000912876517503293',{}).get('v994_recovered_anchor_boundary_review',{}).get('passed')
            or (results['T2-8000912876517503293']['state']=='pending'
                and results['T2-8000912876517503293'].get('boundary_review_pending',{}).get('uncertainty_preserved'))),
        'all_pilot_results_saved':all(path.exists() for path in paths),
        # Ambiguous source evidence must remain pending, not be forced into a
        # false exclusion/label just to pass the pilot. Formal launch additionally
        # requires a separate saved full-text review bound to every result hash.
        'all_pilot_sources_saved_without_runtime_exception':all(r['state'] in {'accepted','excluded','pending'} for r in results.values()),
        'explicit_building_area_positive_control_completed':has_area('T2-243441354646023807'),
        'clear_area_fact_retained_even_if_other_facts_pending':clear_area_evidence,
        'missing_area_basis_comment_honestly_pending':results['T2-C-6923440650351499790']['state']=='pending',
        'unknown_facility_category_remains_pending_not_false_excluded':results['T2-C-2682002808526990393']['state']=='pending',
        'accepted_pilot_sources_have_labeled_rows':all(r['state']!='accepted' or (r['rows'] and all(row['标签明细'] for row in r['rows'])) for r in results.values()),
    }
    return checks

def require_independent_pilot_review(v):
    review=v.read(v.OUT/'independent_pilot_review_v994.json')
    if not review.get('passed') or review.get('overlay_sha256')!=v.sha(overlay.__file__):
        raise RuntimeError('Current independent semantic pilot review not passed')
    bound=review.get('reviewed_results_sha256',{})
    if set(bound)!=set(PILOT_IDS):raise RuntimeError('Independent review must cover every pilot source including the positive control')
    for rid in PILOT_IDS:
        if v.sha(v.result_path(rid))!=bound[rid]:raise RuntimeError('Pilot result changed after semantic review')
    if not review.get('pending_sources_excluded_from_valid_denominator'):
        raise RuntimeError('Pending pilot sources cannot be counted as valid sources')
    return review

def smoke(v):
    key=os.getenv('YS_LLM_API_KEY')
    if not key:raise RuntimeError('Existing-gateway credential missing; no API called')
    control=v.OUT/'control';lock=control/'instance.lock'
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.write(fd,v.b.dumps({'pid':os.getpid(),'script':__file__,'created_at':time.time(),'role':'v994-real-smoke'}).encode());os.close(fd)
    docs={d['record_id']:d for d in v.read(v.OUT/'candidate_documents.json')}
    reuse={r['record_id']:r for r in v.read(v.OUT/'reuse_manifest.json')}
    tax=v.read(v.OUT/'taxonomy.json');business=v.read(v.OUT/'business.json');results={};errors=[]
    runner=v.ClosedLoopRunner(v.OUT,1,key=key)
    governor=v.Governor(1,tpm=1500000,rpm=120,stop=lambda:(control/'soft_stop.request').exists() or runner.fatal.is_set())
    v.b.post_json=v.ControlledPost(v.b.post_json,governor,control,v.b.save_json)
    v.save('pilot_launcher_v994.json',{'pid':os.getpid(),'script':__file__,'version':v.VERSION,'script_sha256':v.sha(__file__),
        'overlay_sha256':v.sha(overlay.__file__),'model':runner.model,'concurrency':1,'credentials_saved':False})
    try:
        for rid in PILOT_IDS:
            if (control/'soft_stop.request').exists() or runner.fatal.is_set():break
            try:results[rid]=v.process_source(docs[rid],reuse[rid],tax,business,runner)
            except Exception as e:errors.append({'record_id':rid,'error_type':type(e).__name__})
            v.save('pilot_progress_v994.json',{'pid':os.getpid(),'version':v.VERSION,'finished':{k:r['state'] for k,r in results.items()},
                'errors':errors,'updated_at':time.time()})
            print(v.b.dumps({'pilot_source':rid,'state':results.get(rid,{}).get('state','incomplete'),'errors':errors}),flush=True)
        paths=[v.result_path(rid) for rid in PILOT_IDS]
        seeds={}
        for rid in PILOT_IDS:
            path=v.OUT/'revisions'/v.VERSION/'seeds'/(v.b.digest(rid)+'.json')
            if path.exists():seeds[rid]=v.read(path)
        checks=pilot_gate(results,seeds,paths) if len(results)==len(PILOT_IDS) else {'all_pilot_sources_returned':False}
        from voc_metadata_completion_v99 import current_audit
        metadata_audit=current_audit(results)
        checks['accepted_pilot_metadata_evidence_complete']=metadata_audit['passed']
        gate={'passed':not errors and all(checks.values()),'checks':checks,'errors':errors,'version':v.VERSION,
            'overlay_sha256':v.sha(overlay.__file__),'pilot_states':{k:r['state'] for k,r in results.items()},
            'not_human_semantic_gold':True,'updated_at':time.time()}
        v.save('smoke_gate_v994.json',gate);v.save('token_cost_summary.json',v.cost_report(v.OUT));print(v.b.dumps(gate),flush=True)
    finally:
        if lock.exists() and v.read(lock).get('pid')==os.getpid():lock.unlink()

def main():
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--smoke',action='store_true');group.add_argument('--run',action='store_true');args=parser.parse_args()
    prelaunch_guard();v=overlay.activate()
    if args.smoke:smoke(v);return
    gate=v.read(v.OUT/'smoke_gate_v994.json')
    if not gate['passed'] or gate['overlay_sha256']!=v.sha(overlay.__file__):raise RuntimeError('Current real smoke gate not passed')
    if old_pid_live(v.read(v.OUT/'pilot_launcher_v994.json')['pid']):raise RuntimeError('Pilot process not fully exited; no second generator')
    require_independent_pilot_review(v)
    import run_voc_batch_driver_v99 as driver
    driver.__file__=__file__
    driver.main()

if __name__=='__main__':sys.stdout.reconfigure(encoding='utf-8');main()
