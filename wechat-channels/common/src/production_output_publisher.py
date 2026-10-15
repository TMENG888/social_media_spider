"""Durable telemetry replay only. Never claim/ACK/reset collection tasks."""
import argparse, json, os, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from redis_task_queue import RedisConnection, safe_token
LUA='''
if redis.call('HEXISTS',KEYS[1],ARGV[1])==1 then return 0 end
local fresh=cjson.decode(ARGV[4])
local old=redis.call('HGET',KEYS[3],ARGV[3])
if old then
  local previous=cjson.decode(old)
  for _,field in ipairs({'lastEffectiveOutputAt','lastMetadataAt','lastSubtitleAt','lastCommentAt'}) do
    if previous[field] and (not fresh[field] or previous[field]>fresh[field]) then fresh[field]=previous[field] end
  end
end
local id=redis.call('XADD',KEYS[2],'*','eventId',ARGV[1],'record',ARGV[2])
redis.call('HSET',KEYS[1],ARGV[1],id)
redis.call('HSET',KEYS[3],ARGV[3],cjson.encode(fresh))
return 1
'''

def event_summary(record):
    kinds={kind for item in record['items'] for kind in item.get('types',[])}
    stamp=record['committedAt']
    result={k:record.get(k) for k in ('computer','worker','consumer','generation','runId','taskId','keyword')}
    result['lastEffectiveOutputAt']=stamp
    for kind,field in [('metadata','lastMetadataAt'),('subtitle','lastSubtitleAt'),('comment','lastCommentAt')]:
        if kind in kinds:result[field]=stamp
    return result

def flush(outbox,url,password,connection_factory=RedisConnection):
    pending=Path(outbox)/'pending';sent=Path(outbox)/'sent'
    files=sorted(pending.glob('*.json'))[:100] if pending.exists() else []
    result={'event':'production_output_upload_result','sent':0,'deduplicated':0,'remainingLocal':len(list(pending.glob('*.json'))) if pending.exists() else 0}
    if not files:return result
    if not url:return {**result,'deferred':True,'reason':'redis_configuration_absent'}
    try:
        with connection_factory(url,password,timeout=5) as c:
            for file in files:
                record=json.loads(file.read_text(encoding='utf-8'))
                if not record.get('readbackVerified') or not record.get('committedAt') or not record.get('runId'):
                    continue
                # Never attach a saved event to a different run on restart.
                prefix='wechat:channels:'+safe_token(record['runId'])
                wire={k:v for k,v in record.items() if k!='verification'}
                latest=event_summary(record)
                identity=str(record.get('generation') or 'unknown')+'|'+str(record.get('computer'))+'/'+str(record.get('worker'))
                inserted=c.command('EVAL',LUA,3,prefix+':production-output-dedupe',prefix+':production-output',prefix+':production-output-latest',record['eventId'],json.dumps(wire,ensure_ascii=False,separators=(',',':')),identity,json.dumps(latest,ensure_ascii=False,separators=(',',':')))
                result['sent' if inserted else 'deduplicated']+=1
                sent.mkdir(parents=True,exist_ok=True)
                os.replace(file,sent/file.name)
        result['remainingLocal']=len(list(pending.glob('*.json')))
    except Exception as e:
        result.update(deferred=True,errorType=type(e).__name__)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--outbox',type=Path,required=True);a=p.parse_args()
    print(json.dumps(flush(a.outbox,os.environ.get('REDIS_URL',''),os.environ.get('REDIS_PASSWORD')),ensure_ascii=False),flush=True)
