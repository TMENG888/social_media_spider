"""Streaming four-source driver; never changes the validated annotation implementation."""
import os,sys,time,json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from pathlib import Path
import voc_batch_v99 as v

def main():
    manifest=v.read(v.OUT/'manifest.json');gate=v.read(v.OUT/'smoke_gate.json')
    if not gate['passed']:raise RuntimeError('Real API smoke gate has not passed')
    docs=v.read(v.OUT/'candidate_documents.json');reuse={r['record_id']:r for r in v.read(v.OUT/'reuse_manifest.json')}
    taxonomy=v.read(v.OUT/'taxonomy.json');business=v.read(v.OUT/'business.json')
    for f in manifest['frozen_inputs']:
        if v.sha(f['snapshot'])!=f['sha256']:raise RuntimeError('Frozen inputs changed')
    key=os.getenv('YS_LLM_API_KEY')
    if not key:raise RuntimeError('No configured existing-gateway credential; no request sent')
    control=v.OUT/'control';lock=control/'instance.lock'
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.write(fd,v.b.dumps({'pid':os.getpid(),'script':str(Path(__file__)),'created_at':time.time()}).encode());os.close(fd)
    started=time.time();results=v.known_results(docs);failures=[];active={};cursors={k:0 for k in v.KINDS}
    pools={k:[d for d in docs if d['kind']==k] for k in v.KINDS}
    runner=v.ClosedLoopRunner(v.OUT,4,key=key)
    governor=v.Governor(4,tpm=1500000,rpm=120,stop=lambda:(control/'soft_stop.request').exists() or runner.fatal.is_set())
    v.b.post_json=v.ControlledPost(v.b.post_json,governor,control,v.b.save_json)
    def state(status):
        selected,counts=v.selected_results(docs,results)
        payload={'state':status,'pid':os.getpid(),'version':v.VERSION,'updated_at':time.time(),'started_at':started,
            'processed_sources':len(results),'targets':v.TARGETS,'selected_valid_sources':dict(counts),
            'outcomes':dict(Counter(r['state'] for r in results.values())),'failures':failures,
            'active_sources':[d['record_id'] for d in active.values()],
            'elapsed_seconds':time.time()-started,'concurrency_ceiling':4,'credentials_saved':False}
        v.save('run_status.json',payload);print(v.b.dumps(payload),flush=True)
    def next_doc(kind):
        while cursors[kind]<len(pools[kind]):
            d=pools[kind][cursors[kind]];cursors[kind]+=1
            if d['record_id'] not in results:return d
        return None
    def source_failure(d,e):
        signature=v.b.digest({'version':v.VERSION,'source':v.stable_source(d),'score':d['row'].get('情绪评分'),
            'taxonomy':taxonomy,'script_sha256':v.sha(v.__file__),'reuse':reuse[d['record_id']]})
        record={'signature':signature,'record_id':d['record_id'],'kind':d['kind'],'state':'pending_exception',
            'document':d,'rows':[],'traces':[],'score':v.b.numeric_score(d['row'].get('情绪评分')),
            'pending':[{'reason':'来源处理未完成：'+type(e).__name__+'；保留请求账本和已保存阶段，不计入有效来源'}],
            'excluded':[],'error_type':type(e).__name__,'human_gold':False}
        v.b.save_json(v.result_path(d['record_id']),record);return record
    try:
        v.save('launcher_identity.json',{'pid':os.getpid(),'script':str(Path(__file__)),'driver_sha256':v.sha(__file__),
            'annotation_script':str(Path(v.__file__)),'annotation_script_sha256':v.sha(v.__file__),'started_at':started,
            'model':runner.model,'concurrency':4,'source_scheduler':'streaming; no whole-batch barrier'})
        state('running')
        with ThreadPoolExecutor(max_workers=4) as pool:
            while True:
                _,counts=v.selected_results(docs,results)
                if runner.fatal.is_set() or (control/'soft_stop.request').exists():
                    # In-flight calls/checkpoint writes finish; no second generation process is launched.
                    if not active:break
                else:
                    active_counts=Counter(d['kind'] for d in active.values())
                    for kind in v.KINDS:
                        other=next(k for k in v.KINDS if k!=kind)
                        limit=4 if counts[other]>=v.TARGETS[other] or cursors[other]>=len(pools[other]) else 2
                        while len(active)<4 and active_counts[kind]<limit and counts[kind]+active_counts[kind]<v.TARGETS[kind]:
                            d=next_doc(kind)
                            if d is None:break
                            f=pool.submit(v.process_source,d,reuse[d['record_id']],taxonomy,business,runner)
                            active[f]=d;active_counts[kind]+=1
                if not active:break
                finished,_=wait(active,timeout=30,return_when=FIRST_COMPLETED)
                if not finished:
                    state('running');continue
                for f in finished:
                    d=active.pop(f)
                    try:results[d['record_id']]=f.result()
                    except Exception as e:
                        failures.append({'record_id':d['record_id'],'error_type':type(e).__name__})
                        results[d['record_id']]=source_failure(d,e)
                state('running')
                if len(results)%10==0:
                    v.save('token_cost_summary.json',v.cost_report(v.OUT))
        metrics=v.analyze()
        _,counts=v.selected_results(docs,results)
        success=all(counts[k]>=v.TARGETS[k] for k in v.KINDS)
        if success:
            v.analyze(require_target=True);state('generation_completed_pending_workbook_verification')
        else:state('generation_incomplete')
        v.save('token_cost_summary.json',v.cost_report(v.OUT))
        v.save('driver_completion.json',{'target_reached':success,'counts':dict(counts),'failures':failures,
            'workbooks_created':False,'requires_independent_verification_and_visual_review':True})
    finally:
        if lock.exists() and v.read(lock).get('pid')==os.getpid():lock.unlink()

if __name__=='__main__':sys.stdout.reconfigure(encoding='utf-8');main()
