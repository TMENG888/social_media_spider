"""Explicitly authorized one-off 500-article run. Does not change production gates."""
import argparse,concurrent.futures,datetime,hashlib,json,os,shutil,sys,threading,time
from pathlib import Path
sys.dont_write_bytecode=True;sys.stdout.reconfigure(encoding='utf8')
ROOT=Path(__file__).parent
PROJECT=Path(__file__).resolve().parents[1]/'semantic-r49'
sys.path.insert(0,str(PROJECT));sys.path.insert(0,str(PROJECT/'production_snapshot'))
import delivery_v4 as api
import topic1_semantic_pipeline as pipeline
import topic1_identity as identity
import version_contract
from run_batch300 import validate_result

def read(p):return json.loads(Path(p).read_text(encoding='utf8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(p)

class Runner(api.ApiRunner):
    def call(self,system,payload,doc,phase,response_schema=None):
        limit={'独立专题范围核验':1024,'逐候选决定缺漏裁决':4096,'证据核验协议精简修复':8192}.get(phase,api.MAX_OUTPUT_TOKENS)
        if phase.startswith('紧凑'):limit=8192
        desc={'version':api.VERSION,'base':self.base,'model':self.model,'max_output_tokens':limit,'system':system,'payload':payload}
        if response_schema is not None:desc['response_schema']=response_schema
        key=api.digest(desc);dest=self.output/'calls'/f'{key}.json'
        old=PROJECT/'api_cache/calls'/f'{key}.json'
        if not dest.exists() and old.exists() and read(old).get('metrics',{}).get('status')=='success':
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(old,dest)
        response,metrics=super().call(system,payload,doc,phase,response_schema=response_schema)
        if metrics['status']=='success' and phase in {'专题一分区合同修复','专题一局部切片合同修复'}:
            try:pipeline.resolve_cuts({'text':payload['text']},response)
            except (ValueError,AssertionError,KeyError,TypeError) as error:
                # One extra model repair only after the existing bounded repair
                # fails exact anchors. Never normalise, fuzzy-match or rewrite text.
                schema=pipeline.obj({'cuts':pipeline.arr(pipeline.obj({'quote':{'type':'string','minLength':1,'maxLength':24},'occurrence':{'type':'integer','minimum':1},'theme':pipeline.S}))})
                repaired,repair_metrics=super().call(system+'\n严格定位修复：quote必须逐字复制输入现存的连续原文，不得简繁转换，不得补字漏字；首个quote从原文首字符开始。只修复不合法的定位引用，保留合理语义主题。',
                    {'text':payload['text'],'invalid_draft':response,'exact_validation_error':str(error)},doc,phase+'严格原文定位重试',response_schema=schema)
                accepted=False
                if repair_metrics['status']=='success':
                    try:pipeline.resolve_cuts({'text':payload['text']},repaired);accepted=True
                    except (ValueError,AssertionError,KeyError,TypeError):pass
                audit={'record_id':doc['record_id'],'original_error':str(error),'invalid_draft':response,'repair':repaired,'accepted':accepted}
                if not accepted:
                    text=payload['text']
                    # Different bounded recovery: select source positions instead
                    # of rewriting mixed-script quotes. Grid IDs are not slices.
                    positions=list(range(len(text))) if len(text)<=4096 else [0]+[i for i in range(1,len(text)) if text[i-1] in '。！？；，\n']
                    anchors=[{'id':i,'anchor':text[pos:pos+16]} for i,pos in enumerate(positions)]
                    schema=pipeline.obj({'cuts':pipeline.arr(pipeline.obj({'anchor_id':{'type':'integer','minimum':0,'maximum':len(anchors)-1},'theme':pipeline.S}))})
                    indexed,indexed_metrics=super().call('只做全文语义主题切片，不打标签。通读原文，在独立主题转换处选原文定位网格的anchor_id；相同主题连贯做法保留一起，不按网格逐条切片。网格仅定位，不能改写或翻译原文。必须选择首位置0，按原文顺序给出不重复ID。只输出JSON cuts数组，每项anchor_id和theme。',
                        {'text':text,'anchor_grid':anchors,'prior_topics':response},doc,phase+'原文位置编号恢复',response_schema=schema)
                    audit['position_recovery']=indexed
                    if indexed_metrics['status']=='success':
                        try:
                            indices=[c['anchor_id'] for c in indexed['cuts']]
                            assert indices and indices[0]==0 and indices==sorted(set(indices))
                            assert all(type(i)==int and 0<=i<len(positions) for i in indices)
                            repaired={'cuts':[]}
                            for c in indexed['cuts']:
                                pos=positions[c['anchor_id']];quote=text[pos:pos+16]
                                repaired['cuts'].append({'quote':quote,'occurrence':pipeline.occurrences(text,quote).index(pos)+1,'theme':c['theme']})
                            pipeline.resolve_cuts({'text':text},repaired);accepted=True;repair_metrics=indexed_metrics
                        except (ValueError,AssertionError,KeyError,TypeError):pass
                    audit.update(accepted=accepted,final_repair=repaired)
                save(ROOT/'anchor_recovery'/f'{key}.json',audit)
                if accepted:return repaired,repair_metrics
        return response,metrics

def main():
    p=argparse.ArgumentParser();p.add_argument('--limit',type=int,default=10,choices=[10,500]);args=p.parse_args()
    frozen=version_contract.verify_frozen();assert frozen['version']=='r49'
    manifest=read(ROOT/'input_manifest.json')
    assert sha(Path(manifest['source_workbook']))==manifest['source_workbook_sha256']
    assert sha(ROOT/'documents.json')==manifest['input_sha256']
    docs=read(ROOT/'documents.json');assert len(docs)==500
    tax=read(PROJECT/'inputs/taxonomy.json');business=read(PROJECT/'inputs/brand_dictionary.json')
    runner=Runner(ROOT/'api_cache',concurrency=10)
    seal=api.digest(frozen['files']);lock=ROOT/'run.lock'
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd)
    for name in ['execution.json','status.json','calls.json']:
        if (ROOT/name).exists():
            archive=ROOT/'run_history'/f'{time.time_ns()}_{name}'
            archive.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,archive)
    save(ROOT/'execution.json',{'model':runner.model,'base':runner.base,'pipeline':pipeline.VERSION,
        'frozen_code_sha256':seal,'input_sha256':manifest['input_sha256'],'planned':args.limit,
        'wrapper_sha256':sha(Path(__file__)),'contract_recovery':'仅最终定位合同失败时，Qwen额外一次严格原文定位修复；不改冻结r49语义规则。',
        'max_in_flight_requests':10,'max_source_workers':10,
        'authorization':('用户已确认10篇效果并授权完成剩余490篇；按原顺序处理全部500篇并复用前10篇缓存；未修改旧300篇审批记录。' if args.limit==500 else '先试标10篇；未修改旧300篇审批记录。'),
        'production_default_changed':False,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()})
    done={};errors=[];reused=[];audits={};started=time.monotonic()
    # Prewarm read-only raw-source identity index once; not any reference labels.
    identity.source_index()
    def work(doc):
        sig=api.digest({'frozen_code':seal,'doc':doc,'model':runner.model})
        path=ROOT/'sources'/f'{doc["record_id"]}.json'
        if path.exists():
            cached=read(path)
            if cached['signature']==sig:
                validate_result(cached['result'],tax);return cached['result'],True
        stage=ROOT/'labeled'/f'{doc["record_id"]}.json'
        if stage.exists() and read(stage)['signature']==sig:result=read(stage)['result']
        else:
            result=pipeline.process_document(doc,tax,business,runner)
            validate_result(result,tax);save(stage,{'signature':sig,'result':result})
        result=identity.process(result,business,runner);validate_result(result,tax)
        save(path,{'signature':sig,'result':result});return result,False
    def checkpoint(final=False):
        with runner.lock:calls=list(runner.calls)
        fresh=[x for x in calls if not x.get('cache_hit')]
        status={'planned':args.limit,'completed':len(done),'failed':len(errors),'errors':errors,
            'source_cache_hits':len(reused),'api_calls':len(calls),'fresh_calls':len(fresh),
            'token_usage':sum(x.get('total_tokens') or 0 for x in fresh),
            'estimated_yuan':round(sum(x.get('estimated_yuan') or 0 for x in fresh),4),
            'elapsed_seconds':round(time.monotonic()-started),'auth_stopped':runner.fatal.is_set(),
            'finished':final,'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat()}
        save(ROOT/'status.json',status);save(ROOT/'calls.json',{'model':runner.model,'calls':calls})
        print(json.dumps({k:v for k,v in status.items() if k!='errors'},ensure_ascii=False),flush=True)
    try:
        iterator=iter(docs[:args.limit]);active={}
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            def submit():
                if runner.fatal.is_set():return
                try:d=next(iterator)
                except StopIteration:return
                active[pool.submit(work,d)]=d
            for _ in range(10):submit()
            while active:
                ready,_=concurrent.futures.wait(active,timeout=20,return_when=concurrent.futures.FIRST_COMPLETED)
                for f in ready:
                    d=active.pop(f)
                    try:
                        result,cache_hit=f.result();done[d['record_id']]=result
                        if cache_hit:reused.append(d['record_id'])
                        audits[d['record_id']]=validate_result(result,tax)
                    except Exception as e:
                        errors.append({'record_id':d['record_id'],'error_type':type(e).__name__,'error':str(e)[:350]})
                    submit()
                checkpoint()
        save(ROOT/f'results_{args.limit}.json',[done[d['record_id']] for d in docs[:args.limit] if d['record_id'] in done])
        save(ROOT/f'audit_{args.limit}.json',{'sources':list(audits.values()),'errors':errors})
        checkpoint(True)
        if errors or len(done)!=args.limit:raise RuntimeError('Not all sources succeeded; successful source and API caches retained for exact resume')
    finally:lock.unlink(missing_ok=True)
if __name__=='__main__':main()
