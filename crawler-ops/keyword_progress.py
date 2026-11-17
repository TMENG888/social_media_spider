"""Read-only, manifest-scoped keyword progress. Never claims or repairs leases."""
import json,time
from collections import Counter
from settings import PACKAGE,PLATFORMS,read_json

DONE={'completed','completed_with_skips','skipped_unresolved'}
LABELS={'pending':'待领取','retry':'待重试','collecting':'采集中','background':'后台处理中','resting':'休息中','cooldown':'安全冷却','verification':'等待验证','leased':'任务执行中','expired':'租约过期待核实','completed':'已结案','pending_import':'已结案待补库','failed':'异常待处理','unknown':'状态待核实','updating':'状态更新中','excluded':'已排除'}
ERRORS={'STOP_SORT_NOT_CONFIRMED':'未能确认最新排序，已保留断点','LEASE_EXPIRED':'租约到期，等待重新领取','STOP_BROWSER_CLOSED':'浏览器关闭，已保留断点','STOP_SEARCH_CONTEXT_LOST':'搜索页面位置异常，已保留断点','LOGIN_REQUIRED':'等待登录处理','RATE_LIMIT':'平台安全限制','STOP_VIEWPORT_UNUSABLE':'页面可用区域过小，已保留断点'}
REASONS={'keyword_post_count_p80':'数量达到平台P80','verified_search_exhaustion':'搜索结果结束','verified_low_year_search':'已到年度边界','local_post_p80_exception':'异常时本地数量达到P80','quantity_threshold':'数量达标','volume_threshold':'数量达标','search_exhausted':'搜索结果结束','retry_exhausted_completion':'重试额度耗尽','verified_annual_range_boundary':'已到年度边界','annual_range_boundary':'已到年度边界','risk_quantity_threshold':'异常时数量达标'}

def decode(raw):
 try:
  v=json.loads(raw);return v if isinstance(v,dict) else {}
 except (ValueError,TypeError):return {}

def hgets(c,namespace,field,ids):
 """Batch only HGET; HMGET is not permitted by the production ACL."""
 out=[]
 for start in range(0,len(ids),80):
  batch=ids[start:start+80]
  c.sock.sendall(b''.join(c._encode(('HGET',namespace+':'+field,i)) for i in batch))
  out.extend(c._read() for _ in batch)
 return out

def observe(c,namespace,platform,now):
 common=PACKAGE/platform/'common'
 manifest=read_json(common/'tasks/redis-tasks.json',{})
 tasks=[t for t in manifest.get('tasks',[]) if t.get('topic')=='专题一']
 catalog=read_json(common/'tasks/keyword-catalog.json',{})
 meta={r['keyword']:r for r in catalog.get('tasks',[])}
 tasks.sort(key=lambda t:meta.get(t['keyword'],{}).get('order',t.get('sequence',0)))
 ids=[t['redisTaskId'] for t in tasks]
 fields={f:hgets(c,namespace,f,ids) for f in ['statuses','attempts','owners','results','errors']}
 statuses=hgets(c,namespace,'statuses',ids)
 lease_values=c.command('ZRANGE',namespace+':leases',0,-1,'WITHSCORES') or []
 leases={lease_values[i]:float(lease_values[i+1]) for i in range(0,len(lease_values),2)}
 rows=[]
 for i,t in enumerate(tasks):
  raw=statuses[i];result=decode(fields['results'][i]);m=meta.get(t['keyword'],{})
  try:attempt=int(fields['attempts'][i])
  except (ValueError,TypeError):attempt=None
  status=('updating' if raw!=fields['statuses'][i] else 'pending_import' if raw in DONE and result.get('pendingImport') is True else 'completed' if raw in DONE else 'retry' if raw=='pending' and attempt and attempt>0 else 'expired' if raw=='leased' and leases.get(t['redisTaskId'],0)<=now*1000 else raw if raw in LABELS else 'unknown')
  owner=fields['owners'][i] or ''
  error=decode(fields['errors'][i]);error_text=str(error.get('code',''))+' '+str(error.get('message',''))
  failure_reason=next((label for code,label in ERRORS.items() if code in error_text),'上轮未完成，等待重试' if status=='retry' else '')
  rows.append(dict(keyword=t['keyword'],order=m.get('order',i+1),brand=m.get('brand',''),sourceId=m.get('sourceId',''),status=status,statusLabel=LABELS[status],attempts=attempt,taskId=t['redisTaskId'],
   # Owner is used only internally for matching; never sent in the public snapshot.
   _owner=owner,reason=REASONS.get(result.get('acceptedBy'), '结案规则已确认' if raw in DONE else failure_reason),
   completedAt=result.get('completedAt') or result.get('confirmedAt'),machine=None))
 return dict(source='ok',sampledAt=now,total=len(tasks),catalogFile=catalog.get('file'),manifestHash=manifest.get('manifestHash'),rows=rows)

def unavailable(platform):
 catalog=read_json(PACKAGE/platform/'common/tasks/keyword-catalog.json',{})
 rows=[dict(keyword=t['keyword'],order=t['order'],brand=t.get('brand',''),sourceId=t.get('sourceId',''),status='unknown',statusLabel=LABELS['unknown'],attempts=None,machine=None,reason='') for t in catalog.get('tasks',[])]
 return dict(source='unavailable',total=len(rows),rows=rows)

def enrich(progress,machines):
 for r in progress['rows']:
  owner=r.pop('_owner','')
  matches=[m for m in machines if m.get('keyword')==r['keyword'] and not m.get('finishedAt') and m.get('status') in ('collecting','background','resting','cooldown','verification','waiting')]
  # Several computers use worker-01. Require computer identity, or a unique live
  # same-word match, rather than assigning solely by worker name.
  explicit=[m for m in matches if m['computer'].lower() in owner.lower()]
  match=explicit[0] if len(explicit)==1 else matches[0] if len(matches)==1 else None
  if r['status']=='leased' and match:
   r['machine']=match['machine'];r['status']=match['status'] if match['status'] in LABELS else 'leased';r['statusLabel']=LABELS[r['status']]
  elif r['status']=='expired':r['reason']='任务租约未确认续期'
 counts=Counter(r['status'] for r in progress['rows']);done=sum(counts[s] for s in ('completed','pending_import'))
 progress.update(counts=dict(counts),completed=done,percent=round(done/progress['total']*100,1) if progress['total'] else 0)
 return progress
