"""Add missing subtitle retries without clearing values or resetting streams."""
import argparse, hashlib, json, sys
from collections import Counter
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from redis_task_queue import RedisConnection, fields_to_dict, flatten_queue, safe_token, retry_payload_has_identity
from subtitle_review import has_internal_prompt

def reason(cp):
    row=cp.get('row') or {}
    if cp.get('status')=='running': return None
    if has_internal_prompt(row.get('video_content')): return 'confirmed_internal_context_pollution'
    if cp.get('subtitle_review_required') or cp.get('subtitle_incomplete_confirmed'):
        return 'explicitly_confirmed_subtitle_issue'
    # Do not infer incompleteness from spelling, short length, or model accuracy.
    if not str(row.get('video_content') or '').strip() and row:
        return 'empty_subtitle'
    return None

LUA='''
if redis.call('HGET',KEYS[1],ARGV[1]) ~= ARGV[2] then return 'changed_skip' end
if redis.call('SISMEMBER',KEYS[4],ARGV[3]) == 1 then return 'already_reconciled' end
redis.call('HSET',KEYS[3],ARGV[3],ARGV[2])
redis.call('HSET',KEYS[1],ARGV[1],ARGV[4])
if ARGV[6] == 'existing_live' then return 'existing_live_marked' end
local id=redis.call('XADD',KEYS[2],'*','retry_id',ARGV[3],'payload',ARGV[5])
redis.call('SADD',KEYS[4],ARGV[3])
return id
'''

def main():
    p=argparse.ArgumentParser();p.add_argument('--credentials',type=Path,required=True)
    p.add_argument('--queue',type=Path,required=True);p.add_argument('--apply',action='store_true')
    p.add_argument('--redis-url',default='redis://127.0.0.1:6379/0')
    p.add_argument('--run-id',default='20260926-prod-01');p.add_argument('--report',type=Path,required=True)
    a=p.parse_args();prefix='wechat:channels:'+safe_token(a.run_id)
    tasks=flatten_queue(json.loads(a.queue.read_text(encoding='utf-8-sig')))
    counts=Counter();entries=[];stream=prefix+':video-retry';group='channels-workers-video-retry'
    with RedisConnection(a.redis_url,a.credentials.read_text(encoding='utf-8-sig').strip(),timeout=15) as c:
        groups=[fields_to_dict(x) for x in c.command('XINFO','GROUPS',stream)]
        g=next(x for x in groups if x['name']==group);last=g['last-delivered-id']
        pending=set();start='-'
        while True:
            part=c.command('XPENDING',stream,group,start,'+',1000)
            pending.update(x[0] for x in part)
            if len(part)<1000:break
            start='('+part[-1][0]
        def order(mid): return tuple(map(int,mid.split('-')))
        live=set()
        for mid,f in c.command('XRANGE',stream,'-','+'):
            if mid not in pending and order(mid)<=order(last):continue
            payload=json.loads(fields_to_dict(f)['payload'])
            live.add((payload.get('source_task_id') or payload.get('task_id'),payload.get('fingerprint')))
        stamp=datetime.now().astimezone().isoformat()
        for task in tasks:
            key=prefix+':video-state:'+safe_token(task['task_id'])
            for fp,raw in fields_to_dict(c.command('HGETALL',key) or []).items():
                cp=json.loads(raw);why=reason(cp)
                if not why:continue
                counts['selected_'+why]+=1
                is_live=(task['task_id'],fp) in live
                if is_live:
                    counts['already_live']+=1
                    if cp.get('status')=='retry_pending' and why=='empty_subtitle':continue
                if not retry_payload_has_identity(cp):
                    counts['identity_unrecoverable']+=1
                    entries.append({'task_id':task['task_id'],'fp':fp,'reason':why,'action':'identity_unrecoverable'})
                    continue
                new={**cp,'status':'retry_pending','asr_status':'retry_pending','force_asr':True,
                     'subtitle_review_required':True,'last_error':'Subtitle reconciliation: '+why,
                     'updated_at':stamp}
                token=hashlib.sha256((task['task_id']+'|'+fp+'|subtitle-reconciliation-v1').encode()).hexdigest()
                payload={**task,'source_task_id':task['task_id'],'fingerprint':fp,'checkpoint':new,
                         'force_asr':True,'retry_id':token,'stagedAt':stamp,'repair_reason':why}
                result='would_mark_existing_live' if is_live else 'would_enqueue'
                if a.apply:
                    result=c.command('EVAL',LUA,4,key,stream,prefix+':subtitle-reconcile-backup',
                                     prefix+':subtitle-reconcile-seeded',fp,raw,token,
                                     json.dumps(new,ensure_ascii=False),json.dumps(payload,ensure_ascii=False),
                                     'existing_live' if is_live else 'new')
                counts['result_'+str(result if result in ('would_enqueue','would_mark_existing_live','existing_live_marked','changed_skip','already_reconciled') else 'enqueued')]+=1
                entries.append({'task_id':task['task_id'],'fp':fp,'reason':why,'action':result})
    report={'at':stamp,'applied':a.apply,'scope':'Redis checkpoints only; not a MySQL/CSV reconciliation',
            'counts':dict(counts),'entries':entries,'oldSubtitleCleared':False,'originalStreamsReset':False}
    a.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='entries'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
