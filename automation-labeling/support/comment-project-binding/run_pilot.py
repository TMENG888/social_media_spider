import argparse, copy, json, os, sys, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
sys.dont_write_bytecode=True
import project_priority as q

PILOT=[('T2-C-1237992','评论点名安澜但旧结果另含臻澐'),
 ('T2-C-7963753211120752231','相似项目名海晏天珺'),
 ('T2-C-7963753211120754293','相似项目名海晏府'),
 ('T2-C-7963753211120747929','评论点名建发海晏，父文主要介绍臻澐'),
 ('T2-C-7963753211120747868','只用邻盘位置指代项目'),
 ('T2-C-7963753211120747254','评论明确谈四项目外楼盘'),
 ('T2-C-7963753211120752205','只提品牌，需要父文消歧'),
 ('T2-C-7963753211120747239','无项目名，父文唯一楼盘'),
 ('T2-C-1237966','这俩指代多项目'),
 ('T2-C-7963753211120747210','合并评论同时谈多个楼盘')]

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--run',action='store_true');ap.add_argument('--limit',type=int,default=10)
    ap.add_argument('--repair-record-id',action='append',default=[]);a=ap.parse_args()
    assert 1<=a.limit<=10
    q.WORK.mkdir(parents=True,exist_ok=True);q.OUT.mkdir(parents=True,exist_ok=True)
    inventory=q.p.read(q.BASE);by={s['record_id']:s for s in inventory['sources']}
    records=[by[rid] for rid,_ in PILOT[:a.limit]]
    initial_sha=q.sha(q.BASE)
    plan={'version':q.VERSION,'input_inventory':q.reference(q.BASE),'source_counts':inventory['source_counts'],
        'sample_count':len(records),'selection':'purposive_risk_stratified_not_random','items':[{'record_id':rid,'stratum':st} for rid,st in PILOT[:a.limit]],
        'scope':'project_fields_only_reuse_slices_and_tag_decisions','future_rule':'5-10 source pilot, reuse successes in cohort, targeted field repairs, never rerun successful labels',
        'quota_change_authority':'User confirmed existing Qwen quota restored 2026-10-20; no restart of the old 1000-source generation chain'}
    q.save(q.WORK/'pilot_plan.json',plan)
    if not a.run:print(json.dumps(plan,ensure_ascii=False));return
    lock=q.WORK/'instance.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd)
    q.p.OUT=q.OUT;q.p.STOP=q.WORK/'soft_stop.request'
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'legacy-runtime'))
    import gateway_error_observer_v104 as observer
    q.p.v.b.post_json=observer.observe(q.p.v.b.post_json,lambda x:q.save(q.OUT/'gateway_errors'/(str(time.time_ns())+'.json'),x))
    runner=q.p.configure_runner(4,True)
    events=[];failures=[];started=time.time()
    def status(state,pending):
        q.save(q.WORK/'run_status.json',{'state':state,'pid':os.getpid(),'started_at':started,'updated_at':time.time(),
            'sample_target':len(records),'completed':len(events),'pending':pending,'failures':failures,'events':events,'model':runner.model,'old_chain_not_resumed':True})
    q.save(q.WORK/'launcher_identity.json',{'pid':os.getpid(),'script':__file__,'script_sha256':q.sha(__file__),
        'policy_script_sha256':q.sha(q.__file__),'started_at':started,'model':runner.model,'concurrency_ceiling':4,'credential_saved':False})
    def worker(source):
        file=q.OUT/'overlays'/q.VERSION/(q.digest(source['record_id'])+'.json')
        initial=q.OUT/'overlays'/(q.digest(source['record_id'])+'.json')
        if not file.exists() and initial.exists() and source['record_id'] not in a.repair_record_id:file=initial
        if file.exists():
            overlay=q.p.read(file);assert overlay['source_digest']==q.digest(source)
        else:
            overlay=q.resolve(source,runner);overlay['overlay_file']=str(file);q.save(file,overlay)
        revised_file=q.OUT/'revised_sources'/overlay['version']/(q.digest(source['record_id'])+'.json')
        initial_revised=q.OUT/'revised_sources'/(q.digest(source['record_id'])+'.json')
        if revised_file.exists():revised=q.p.read(revised_file)
        elif file==initial and initial_revised.exists():revised=q.p.read(initial_revised)
        else:
            revised=q.apply_overlay(source,dict(overlay,overlay_file=str(file)))
            revised=q.repair_summaries(source,revised,runner)
        q.save(revised_file,revised)
        return {'record_id':source['record_id'],'state':revised['state'],'methods':dict(Counter(x['method'] for x in overlay['bindings'])),
            'parked_labels':len(revised['project_attribution_parked_labels']),'overlay':q.reference(file),'revised_source':q.reference(revised_file)}
    try:
        status('running_project_only_pilot',len(records))
        with ThreadPoolExecutor(max_workers=4) as pool:
            tasks={pool.submit(worker,s):s for s in records}
            for future in as_completed(tasks):
                source=tasks[future]
                try:events.append(future.result())
                except Exception as e:failures.append({'record_id':source['record_id'],'type':type(e).__name__,'error':str(e)})
                status('running_project_only_pilot',len(records)-len(events)-len(failures))
        assert q.sha(q.BASE)==initial_sha,'Original inventory changed during pilot'
        status('pilot_stages_saved' if not failures else 'pilot_incomplete_preserved',0)
        print(json.dumps({'completed':len(events),'failures':failures,'elapsed_seconds':time.time()-started},ensure_ascii=False))
    finally:
        lock.unlink()

if __name__=='__main__':main()
