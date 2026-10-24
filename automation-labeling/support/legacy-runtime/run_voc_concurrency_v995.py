"""Concurrency-only scheduler. Annotation core, signatures and success cache unchanged.

First supported profile: at most20 actual HTTP attempts including retries,
3.5m conservative rolling TPM and300RPM. No extra API/service or acceptance
threshold change. A bounded throughput benchmark precedes continued processing.
"""
import argparse,copy,json,os,sys,time,threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from pathlib import Path
import voc_batch_v99 as base
import voc_repair_overlay_v994 as overlay
from run_voc_batch_driver_v994 import require_independent_pilot_review
from prepare_stage_reuse_v994 import old_pid_live,source_signature

class AdaptiveGovernor(base.Governor):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.operating_cap=self.maximum
    def finish(self,attempt_id,usage=None,status=None,seconds=0,network_error=False):
        # Condition's default RLock keeps reduction atomic with admission.
        with self.cv:
            prior=self.target
            super().finish(attempt_id,usage,status,seconds,network_error)
            if network_error or status in {408,409,429} or (status or 0)>=500 or seconds>=60:
                self.target=min(self.target,max(1,prior//2))
            self.target=min(self.target,self.operating_cap);self.cv.notify_all()
    def cap(self,value):
        if type(value) is not int or not 1<=value<=self.maximum:raise ValueError('Invalid operating cap')
        with self.cv:
            self.operating_cap=value;self.target=min(self.target,value);self.cv.notify_all()

def validate_profile(concurrency,tpm,rpm,seconds):
    if type(concurrency) is not int or not 1<=concurrency<=20:raise ValueError('First benchmark permits at most20')
    if type(tpm) is not int or not 1<=tpm<=3500000:raise ValueError('TPM above tested conservative profile')
    if type(rpm) is not int or not 1<=rpm<=300:raise ValueError('RPM above tested profile')
    if not 60<=seconds<=900:raise ValueError('Benchmark must be60-900seconds')

def make_runner(factory,output,concurrency,key):
    # Legacy constructor permits at most10, solely to initialize its semaphore.
    # No requests run in the constructor. Replace that one scheduler primitive
    # before any work is submitted; the shared HTTP governor remains authoritative.
    runner=factory(output,min(concurrency,10),key=key)
    runner.gate=threading.BoundedSemaphore(concurrency)
    return runner

def audit_saved(v,docs,reuse,tax):
    issues=[];sources=0;repairs=0
    signatures={};by_source={d['record_id']:d for d in docs};annotation_sha=v.sha(overlay.__file__)
    def signature(rid):
        if rid not in signatures:signatures[rid]=source_signature(by_source[rid],reuse[rid],tax,overlay.VERSION,annotation_sha)
        return signatures[rid]
    for doc in docs:
        rid=doc['record_id']
        path=v.result_path(rid)
        if not path.exists():continue
        record=v.read(path);sources+=1
        if record['signature']!=signature(rid) or v.stable_source(record['document'])!=v.stable_source(doc):
            issues.append({'record_id':rid,'issue':'Saved source signature/context mismatch'})
    for path in (v.OUT/'revisions'/v.VERSION/'repairs').glob('*.json'):
        record=v.read(path);item=record['outcome']['unit'];rid=item['unit_id'].rsplit('-V',1)[0];repairs+=1
        if rid not in by_source or record['signature']!=v.b.digest({'source_signature':signature(rid),'item':item}):
            issues.append({'unit_id':item['unit_id'],'issue':'Saved unit signature mismatch'})
    return {'passed':not issues,'sources':sources,'repairs':repairs,'issues':issues,'network_calls':0}

def attempt_snapshot(directory,started):
    rows=[]
    for p in directory.glob('*.json'):
        if p.stat().st_mtime<started:continue
        r=base.read(p)
        if r.get('started_at',0)>=started:rows.append(r)
    finished=[r for r in rows if r.get('finished_at')]
    lat=sorted(r['seconds'] for r in finished)
    return {'attempts':len(rows),'finished':len(finished),'http429':sum(r.get('http_status')==429 for r in finished),
        'unhealthy':sum(r.get('state')=='transport_error_usage_unknown' or r.get('http_status',0) in {408,409,429}
            or (r.get('http_status') or 0)>=500 for r in finished),
        'seconds_p50':lat[len(lat)//2] if lat else None,
        'seconds_p95':lat[min(len(lat)-1,int(len(lat)*.95))] if lat else None,
        'diagnostic_not_cost_ledger':True}

def benchmark_decision(baseline,elapsed,initial,current,http):
    added=sum(r['state'] in {'accepted','excluded','pending','pending_score'} for k,r in current.items() if k not in initial)
    valid=sum(r['state']=='accepted' for k,r in current.items() if k not in initial)
    rate=added/max(elapsed/60,1e-9);valid_rate=valid/max(elapsed/60,1e-9)
    old_rate=baseline['new_sources']/max(baseline['elapsed_seconds']/60,1e-9)
    errors=http['unhealthy']/max(http['finished'],1)
    old_valid_rate=baseline['new_accepted_sources']/max(baseline['elapsed_seconds']/60,1e-9)
    passed=(http['finished']>=20 and errors<=.05 and http['http429']/max(http['finished'],1)<=.01
        and rate>old_rate*1.2 and valid_rate>=old_valid_rate)
    return {'passed_operational_benchmark':passed,'not_semantic_quality_acceptance':True,
        'elapsed_seconds':elapsed,'new_sources':added,'new_machine_accepted_sources':valid,
        'sources_per_minute':rate,'machine_accepted_per_minute':valid_rate,
        'baseline_sources_per_minute':old_rate,'source_throughput_multiple':rate/old_rate if old_rate else None,
        'baseline_machine_accepted_per_minute':old_valid_rate,
        'http':http,'quality_thresholds_unchanged':True,'pending_not_valid':True,
        'decision':'continue20_ceiling_with_adaptive_HTTP_limits' if passed else 'reduce_to4_and_preserve_results',
        'valid_yield_requires_later_independent_review':True}

def main():
    p=argparse.ArgumentParser();p.add_argument('--concurrency',type=int,default=20);p.add_argument('--tpm',type=int,default=3500000)
    p.add_argument('--rpm',type=int,default=300);p.add_argument('--benchmark-seconds',type=int,default=300)
    p.add_argument('--preflight',action='store_true');a=p.parse_args();validate_profile(a.concurrency,a.tpm,a.rpm,a.benchmark_seconds)
    v=overlay.activate();control=v.OUT/'control';approval=v.read(control/'approval_concurrency20_v995.json')
    assert approval['approved'] and approval['annotation_sha256']==v.sha(overlay.__file__)
    assert v.sha(Path(__file__).with_name('voc_batch_v99.py'))==overlay.BASE_SHA256
    assert v.read(v.OUT/'smoke_gate_v994.json')['passed'];require_independent_pilot_review(v)
    for f in v.read(v.OUT/'manifest.json')['frozen_inputs']:
        if v.sha(f['snapshot'])!=f['sha256']:raise RuntimeError('Frozen input changed')
    if (control/'instance.lock').exists() or old_pid_live(approval['old_pid']):raise RuntimeError('Old driver not drained')
    docs=v.read(v.OUT/'candidate_documents.json');reuse={r['record_id']:r for r in v.read(v.OUT/'reuse_manifest.json')}
    tax=v.read(v.OUT/'taxonomy.json');business=v.read(v.OUT/'business.json')
    audit=audit_saved(v,docs,reuse,tax);v.save('concurrency20_saved_stage_audit.json',audit)
    if not audit['passed']:raise RuntimeError('Saved stage signature audit failed')
    if a.preflight:print(v.b.dumps(audit));return
    key=os.getenv('YS_LLM_API_KEY')
    if not key:raise RuntimeError('Existing gateway credential unavailable')
    baseline=v.read(control/'concurrency4_baseline_v995.json')
    runner=make_runner(v.ClosedLoopRunner,v.OUT,a.concurrency,key)
    fd=os.open(control/'instance.lock',os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.write(fd,v.b.dumps({'pid':os.getpid(),'script':__file__,'created_at':time.time()}).encode());os.close(fd)
    started=time.time();results=v.known_results(docs);initial=copy.deepcopy(results);failures=[];active={};cursors={k:0 for k in v.KINDS}
    pools={k:[d for d in docs if d['kind']==k] for k in v.KINDS}
    ceiling=a.concurrency;bench=None
    governor=AdaptiveGovernor(a.concurrency,tpm=a.tpm,rpm=a.rpm,stop=lambda:(control/'soft_stop.request').exists() or runner.fatal.is_set())
    v.b.post_json=v.ControlledPost(v.b.post_json,governor,control,v.b.save_json)
    def state(status):
        counts=v.selected_results(docs,results)[1]
        payload={'state':status,'pid':os.getpid(),'version':v.VERSION,'started_at':started,'updated_at':time.time(),
            'processed_sources':len(results),'initial_reused_sources':len(initial),'targets':v.TARGETS,
            'selected_valid_sources':dict(counts),'outcomes':dict(Counter(r['state'] for r in results.values())),
            'failures':failures,'active_sources':[d['record_id'] for d in active.values()],
            'elapsed_seconds':time.time()-started,'concurrency_ceiling':ceiling,'credentials_saved':False,
            'benchmark_completed':bench is not None,'annotation_implementation_unchanged':True}
        v.save('run_status.json',payload);print(v.b.dumps(payload),flush=True)
    def next_doc(kind):
        while cursors[kind]<len(pools[kind]):
            doc=pools[kind][cursors[kind]];cursors[kind]+=1
            if doc['record_id'] not in results:return doc
        return None
    try:
        v.save('launcher_identity.json',{'pid':os.getpid(),'script':__file__,'driver_sha256':v.sha(__file__),
            'annotation_script':str(v.__file__),'annotation_script_sha256':v.sha(overlay.__file__),'started_at':started,
            'model':runner.model,'concurrency':a.concurrency,'tpm':a.tpm,'rpm':a.rpm,'credentials_saved':False})
        state('running')
        with ThreadPoolExecutor(max_workers=a.concurrency) as pool:
            while True:
                elapsed=time.time()-started
                if bench is None and elapsed>=a.benchmark_seconds:
                    bench=benchmark_decision(baseline,elapsed,initial,results,attempt_snapshot(control/'http_attempts',started))
                    if not bench['passed_operational_benchmark']:ceiling=4;governor.cap(4)
                    v.save('concurrency20_benchmark.json',bench)
                counts=v.selected_results(docs,results)[1]
                if not runner.fatal.is_set() and not (control/'soft_stop.request').exists():
                    active_counts=Counter(d['kind'] for d in active.values())
                    for kind in v.KINDS:
                        other=next(k for k in v.KINDS if k!=kind)
                        limit=ceiling if counts[other]>=v.TARGETS[other] or cursors[other]>=len(pools[other]) else max(1,ceiling//2)
                        while len(active)<ceiling and active_counts[kind]<limit and counts[kind]+active_counts[kind]<v.TARGETS[kind]:
                            doc=next_doc(kind)
                            if doc is None:break
                            f=pool.submit(v.process_source,doc,reuse[doc['record_id']],tax,business,runner)
                            active[f]=doc;active_counts[kind]+=1
                if not active:break
                done,_=wait(active,timeout=15,return_when=FIRST_COMPLETED)
                for f in done:
                    doc=active.pop(f)
                    try:results[doc['record_id']]=f.result()
                    except Exception as e:
                        failures.append({'record_id':doc['record_id'],'error_type':type(e).__name__})
                        sig=source_signature(doc,reuse[doc['record_id']],tax,v.VERSION,v.sha(overlay.__file__))
                        record={'signature':sig,'record_id':doc['record_id'],'kind':doc['kind'],'state':'pending_exception',
                            'document':doc,'rows':[],'traces':[],'score':v.b.numeric_score(doc['row'].get('情绪评分')),
                            'pending':[{'reason':'未完成来源：'+type(e).__name__+'；保存阶段与请求，不计有效来源'}],
                            'excluded':[],'error_type':type(e).__name__,'human_gold':False}
                        v.b.save_json(v.result_path(doc['record_id']),record);results[doc['record_id']]=record
                state('running')
        counts=v.selected_results(docs,results)[1];success=all(counts[k]>=v.TARGETS[k] for k in v.KINDS)
        if results and any(r['state']=='accepted' for r in results.values()):v.analyze(require_target=success)
        state('generation_completed_pending_workbook_verification' if success else 'generation_incomplete')
        v.save('driver_completion.json',{'target_reached':success,'counts':dict(counts),'failures':failures,
            'workbooks_created':False,'requires_independent_verification_and_visual_review':True})
        v.save('token_cost_summary.json',v.cost_report(v.OUT))
    finally:
        lock=control/'instance.lock'
        if lock.exists() and v.read(lock).get('pid')==os.getpid():lock.unlink()

if __name__=='__main__':sys.stdout.reconfigure(encoding='utf-8');main()
