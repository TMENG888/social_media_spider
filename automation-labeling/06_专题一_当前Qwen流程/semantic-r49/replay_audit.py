"""Exact request-key cache replay, no key/network and no new API requests."""
import json,sys
from pathlib import Path
sys.dont_write_bytecode=True;sys.stdout.reconfigure(encoding='utf8')
R=Path(__file__).parent;sys.path.insert(0,str(R/'production_snapshot'))
import delivery_v4 as api
import topic1_semantic_pipeline as pipe
def read(p):return json.loads(Path(p).read_text(encoding='utf8'))
class CacheOnlyRunner:
 def __init__(self):self.base='http://127.0.0.1:3000';self.model='qwen3.7-flash';self.requests=[]
 def call(self,system,payload,doc,phase,response_schema=None):
  limit={'独立专题范围核验':1024,'逐候选决定缺漏裁决':4096,'证据核验协议精简修复':8192}.get(phase,api.MAX_OUTPUT_TOKENS)
  if phase.startswith('紧凑'):limit=8192
  desc={'version':api.VERSION,'base':self.base,'model':self.model,'max_output_tokens':limit,'system':system,'payload':payload}
  if response_schema is not None:desc['response_schema']=response_schema
  key=api.digest(desc);path=R/'api_cache/calls'/(key+'.json')
  if not path.exists():raise RuntimeError('Cache miss, network forbidden: '+phase+' '+doc['record_id'])
  x=read(path);assert x['metrics']['status']=='success'
  self.requests.append({'source':doc['source_id'],'phase':phase,'payload':payload,'response':x['response'],'request_key':key})
  return x['response'],dict(x['metrics'],cache_hit=True)
def main():
 docs=read(R/'inputs/A_documents.json');tax=read(R/'inputs/taxonomy.json');biz=read(R/'inputs/brand_dictionary.json')
 runner=CacheOnlyRunner();out=R/'r8_audit';out.mkdir(exist_ok=True);results=[]
 for d in docs:
  x=pipe.process_document(d,tax,biz,runner,label_engine='legacy');results.append(x)
  (out/(d['record_id']+'.json')).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
 (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
 (out/'requests.json').write_text(json.dumps(runner.requests,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps({'sources':len(results),'calls_replayed':len(runner.requests),'paid_calls':0},ensure_ascii=False))
if __name__=='__main__':main()
