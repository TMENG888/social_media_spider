import sys,os,json,hashlib,argparse,traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
sys.dont_write_bytecode=True;sys.stdout.reconfigure(encoding='utf8')
R=Path(__file__).parent
sys.path.insert(0,str(R/'production_snapshot'))
import delivery_v4 as api
import topic1_semantic_pipeline as pipeline
import topic1_identity as identity
import exhaustive_labels as labeler
import label_candidates as recall
import summary_evidence
import version_contract
def read(p):return json.loads(Path(p).read_text(encoding='utf8'))
def save(p,x):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(p)
def main():
 p=argparse.ArgumentParser();p.add_argument('--batch',choices=['A','B','C'],required=True);p.add_argument('--limit',type=int);p.add_argument('--version',default='r1');args=p.parse_args()
 if args.batch=='C' and not (R/'frozen_version.json').exists():raise RuntimeError('C is sealed until A/B frozen')
 if args.batch=='C':
  frozen=version_contract.verify_frozen()
  if args.version!=frozen['version']:raise RuntimeError('C must use the exact frozen version')
 docs=read(R/'inputs'/f'{args.batch}_documents.json')
 # B/C frozen raw inputs predate the API wrapper's envelope fields. Add only
 # source metadata here; never alter raw text, reference annotations or hashes.
 for d in docs:
  if d['row'].get('项目')!='全国地产设计产品力监测':raise ValueError('Input is not topic1')
  d.setdefault('topic',d['row']['项目']);d.setdefault('kind','文章')
 if args.limit:docs=docs[:args.limit]
 tax=read(R/'inputs/taxonomy.json');business=read(R/'inputs/brand_dictionary.json')
 out=R/('run_'+args.version);out.mkdir(exist_ok=True);lock=out/(args.batch+'.lock')
 fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd)
 runner=api.ApiRunner(R/'api_cache',concurrency=6)
 signature=api.digest({'code':Path(pipeline.__file__).read_text(encoding='utf8'),'labeler':Path(labeler.__file__).read_text(encoding='utf8'),'recall':Path(recall.__file__).read_text(encoding='utf8'),'identity':Path(identity.__file__).read_text(encoding='utf8'),'summary':Path(summary_evidence.__file__).read_text(encoding='utf8'),'raw_identity_sha':hashlib.sha256(identity.RAW.read_bytes()).hexdigest(),'api_dependencies':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (R/'production_snapshot').glob('*.py')},'model':runner.model,'tax':tax,'dictionary':business})
 done={};errors=[]
 def work(d):
  f=out/'sources'/(d['record_id']+'.json');sig=api.digest({'pipeline':signature,'doc':d})
  if f.exists():
   x=read(f)
   if x['signature']==sig:return x['result']
  result=pipeline.process_document(d,tax,business,runner);result=identity.process(result,business,runner);save(f,{'signature':sig,'result':result});return result
 try:
  with ThreadPoolExecutor(max_workers=3) as pool:
   futures={pool.submit(work,d):d for d in docs}
   for f in as_completed(futures):
    d=futures[f]
    try:done[d['record_id']]=f.result()
    except Exception as e:errors.append({'record_id':d['record_id'],'error_type':type(e).__name__,'error':str(e)[:500]})
    status={'batch':args.batch,'version':args.version,'completed':len(done),'planned':len(docs),'errors':errors,'last_source':d['record_id']}
    save(out/(args.batch+'_status.json'),status);print(json.dumps(status,ensure_ascii=False),flush=True)
  save(out/(args.batch+'_results.json'),[done[d['record_id']] for d in docs if d['record_id'] in done])
  save(out/(args.batch+'_run.json'),{'signature':signature,'model':runner.model,'calls':runner.calls,'errors':errors,'pipeline':pipeline.VERSION})
  if errors:raise RuntimeError('Some sources failed; preserved successful caches')
 finally:lock.unlink(missing_ok=True)
if __name__=='__main__':main()
