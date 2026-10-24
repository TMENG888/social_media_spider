"""Bounded fresh HTTP benchmark; never changes production core or baseline labels."""
import ast,json,sys,time,threading,random,urllib.error,math,os,datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from collections import deque
sys.path.insert(0,r'C:/Users/YS-Insight/Desktop/陈晓锋/地产专题混合切片打标自动化程序/hybrid_slicing_pipeline')
from delivery_v4 import post_json,parse_json,cached_tokens,calculate_cost
src=Path(r'D:/Codex/outputs/01a1349d-c76e-7b63-be36-3c8e0766deef/20261013_各平台广告盲测50条')
out=src/'pressure_10_16_20'
out.mkdir(exist_ok=True)
if (out/'started.json').exists():raise RuntimeError('Existing benchmark: do not duplicate requests')
key=os.environ.get('YS_LLM_API_KEY','')
if not key:raise RuntimeError('Missing dedicated Qwen key')
system=next(ast.literal_eval(n.value) for n in ast.parse(Path(__file__).with_name('qwen_test.py').read_text(encoding='utf-8')).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='system' for t in n.targets))
packets=json.loads((src/'blind_packets.json').read_text(encoding='utf-8'))
refs={r['sample_id']:r for r in json.loads((src/'codex_reference_frozen.json').read_text(encoding='utf-8'))}
baseline={r['sample_id']:r['response']['label'] for r in json.loads((src/'qwen_results.json').read_text(encoding='utf-8'))}
lock=threading.Lock();window=deque();attempt_count=0;active=0;peak=0;fatal=threading.Event()
def save(name,value):
 (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
save('started.json',{'time':datetime.datetime.now(datetime.timezone.utc).isoformat(),'pid':os.getpid(),'model':'qwen3.7-flash','base':'http://127.0.0.1:3000','tiers':[10,16,20],'rounds_per_tier':2,'rows_per_round':50,'max_attempts':500,'rpm_cap':300,'estimated_tpm_cap':3500000,'fresh_HTTP':True,'note':'Same blind payload and prompt as baseline; no local response cache. Provider prefix caching may occur.'})
def reserve(estimate):
 global attempt_count,active,peak
 while not fatal.is_set():
  with lock:
   now=time.monotonic()
   while window and now-window[0][0]>=60:window.popleft()
   if attempt_count>=500:fatal.set();return False
   if len(window)<300 and sum(x[1] for x in window)+estimate<=3500000:
    window.append((now,estimate));attempt_count+=1;active+=1;peak=max(peak,active);return True
  time.sleep(.1)
 return False
def classify(p,tier,round_no):
 global active
 started=time.perf_counter();attempts=[];result=None;error='';valid=False
 body={'model':'qwen3.7-flash','messages':[{'role':'system','content':system},{'role':'user','content':json.dumps(p,ensure_ascii=False,separators=(',',':'))}],'temperature':.1,'enable_thinking':False,'max_tokens':8192,'response_format':{'type':'json_object'}}
 estimate=len(json.dumps(body,ensure_ascii=False))+8192
 for no in range(2):
  if not reserve(estimate):error='Auth failure or request budget stop';break
  a={'attempt':no+1};ts=time.perf_counter()
  try:
   response=post_json('http://127.0.0.1:3000/v1/chat/completions',body,key,timeout=90)
   a['http_status']=response.status_code
   if response.status_code in [401,403]:fatal.set();error='Authentication failure'
   elif response.status_code==200:
    payload=response.json();a['usage']=payload.get('usage') or {}
    try:
     c=payload['choices'][0]
     if c.get('finish_reason') in ['length','content_filter']:raise ValueError('Incomplete output')
     result=parse_json(c['message']['content'])
     valid=isinstance(result,dict) and result.get('label') in ['广告','非广告','待判断'] and isinstance(result.get('reason'),str)
     if not valid:error='Invalid label JSON'
    except (ValueError,TypeError,KeyError):error='Invalid/truncated JSON'
   else:error=f'HTTP {response.status_code}'
  except (urllib.error.URLError,TimeoutError,OSError):a['network_error']='Network/timeout';error='Network/timeout'
  except (ValueError,TypeError,KeyError):error='Invalid gateway JSON'
  finally:
   a['seconds']=time.perf_counter()-ts;attempts.append(a)
   with lock:
    active-=1
    with (out/'http_attempts.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(dict(a,sample_id=p['sample_id'],tier=tier,round=round_no),ensure_ascii=False)+'\n')
  if valid or fatal.is_set():break
  retry=a.get('http_status') in [408,409,429] or a.get('http_status',0)>=500 or 'network_error' in a
  if not retry:break
  time.sleep(2+random.random())
 evidence=result.get('evidence',[]) if isinstance(result,dict) else []
 exact=bool(evidence) and isinstance(evidence,list) and all(isinstance(e,dict) and bool(e.get('quote')) and e.get('field') in p['fields'] and e['quote'] in p['fields'][e['field']] for e in evidence)
 r={'sample_id':p['sample_id'],'tier':tier,'round':round_no,'response':result,'label_valid':valid,'evidence_exact':exact,'attempts':attempts,'seconds':time.perf_counter()-started,'error':error if not valid else ''}
 save(f'{tier}_{round_no}_{p["sample_id"]}.json',r)
 return r
def percentile(xs,q):
 xs=sorted(xs);return xs[max(0,math.ceil(q*len(xs))-1)] if xs else None
stages=[];all_results=[];bench_start=time.perf_counter()
for tier in [10,16,20]:
 tier_results=[];rounds=[];peak=0
 for round_no in [1,2]:
  start=time.perf_counter()
  with ThreadPoolExecutor(max_workers=tier) as pool:
   for future in as_completed([pool.submit(classify,p,tier,round_no) for p in packets]):tier_results.append(future.result())
  rr=[r for r in tier_results if r['round']==round_no];wall=time.perf_counter()-start
  rounds.append({'round':round_no,'wall_seconds':wall,'throughput_rows_per_min':len(rr)/wall*60,'success':sum(r['label_valid'] for r in rr),'p95_seconds':percentile([r['seconds'] for r in rr],.95)})
  print('ROUND',tier,round_no,json.dumps(rounds[-1]),flush=True)
  if fatal.is_set():break
 all_results+=tier_results
 attempts=[a for r in tier_results for a in r['attempts']]
 definite=[r for r in tier_results if refs[r['sample_id']]['label']!='待判断']
 labels=lambda r:(r['response'] or {}).get('label')
 wall=sum(r['wall_seconds'] for r in rounds)
 summary={'tier':tier,'rounds':rounds,'rows':len(tier_results),'success':sum(r['label_valid'] for r in tier_results),'first_attempt_success':sum(r['label_valid'] and len(r['attempts'])==1 for r in tier_results),'HTTP_attempts':len(attempts),'rate_limits':sum(a.get('http_status')==429 for a in attempts),'network_timeouts':sum('network_error' in a for a in attempts),'HTTP_5xx':sum(a.get('http_status',0)>=500 for a in attempts),'p50_seconds':percentile([r['seconds'] for r in tier_results],.5),'p95_seconds':percentile([r['seconds'] for r in tier_results],.95),'max_seconds':max(r['seconds'] for r in tier_results),'wall_seconds':wall,'throughput_rows_per_min':len(tier_results)/wall*60,'peak_actual_HTTP':peak,'reference_definite_n':len(definite),'reference_agree':sum(labels(r)==refs[r['sample_id']]['label'] for r in definite),'baseline_agree':sum(labels(r)==baseline[r['sample_id']] for r in tier_results),'evidence_exact_rows':sum(r['evidence_exact'] for r in tier_results),'unknown_usage_attempts':sum(not a.get('usage') for a in attempts)}
 for name in ['prompt_tokens','completion_tokens','total_tokens']:summary[name]=sum(a.get('usage',{}).get(name,0) or 0 for a in attempts)
 summary['estimated_yuan']=sum(calculate_cost(a['usage'].get('prompt_tokens'),cached_tokens(a['usage']),a['usage'].get('completion_tokens')) or 0 for a in attempts if a.get('usage'))
 summary['stop_escalation']=fatal.is_set() or summary['success']<.98*len(tier_results) or summary['rate_limits']>0 or summary['network_timeouts']>0 or summary['p95_seconds']>60
 stages.append(summary);save('pressure_results.json',{'stages':stages,'total_attempts':attempt_count,'elapsed_seconds':time.perf_counter()-bench_start,'complete':False});print('TIER',json.dumps(summary,ensure_ascii=False),flush=True)
 if summary['stop_escalation']:break
save('pressure_results.json',{'stages':stages,'total_attempts':attempt_count,'elapsed_seconds':time.perf_counter()-bench_start,'complete':True,'maximum_tested':stages[-1]['tier'],'global_maximum_proven':False})
save('all_results.json',all_results)
print('BENCHMARK COMPLETE',flush=True)
