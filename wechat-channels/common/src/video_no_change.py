"""End a proven unchanged retry, without claiming that empty content is complete."""
import hashlib
import json
import re
from pathlib import Path
from video_retry_budget import identity, is_content_failure

def read_checkpoint(q,args,item):
    parent=q.safe_token(item.get('source_task_id') or item['task_id'])
    return q.redis_command(args.redis_url,args.redis_password,'HGET',
                           args.prefix+':video-state:'+parent,item['fingerprint'])

def content_digest(cp):
    row=dict(cp.get('row') or {})
    for field in ('captured_at','updated_at','文章获取时间'):
        row.pop(field,None)
    def clean(v):
        if isinstance(v,list):
            return sorted([clean(x) for x in v],key=lambda x:json.dumps(x,sort_keys=True,ensure_ascii=False))
        if isinstance(v,dict):
            return {k:clean(x) for k,x in v.items() if k not in {'captured_at','updated_at','评论获取时间'}}
        return v
    value={'fingerprint':cp.get('fingerprint'),'article_key':cp.get('article_key'),
           'row':row,'comments':clean(cp.get('comments') or [])}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def failure_kind(cp):
    guard={'status':cp.get('status'),'reason':cp.get('last_error')}
    if not is_content_failure(guard):return None
    reason=str(cp.get('last_error') or '')
    if re.search(r'ASR|quality|transcript|hallucination|字幕',reason,re.I):return 'subtitle'
    if re.search(r'DETAIL|详情',reason,re.I):return 'detail'
    return None

def no_change_evidence(before,after,*,import_ok=False,stopped=False):
    if stopped or not import_ok or not isinstance(before,dict) or not isinstance(after,dict):return None
    row=before.get('row') or {}
    if not all(str(row.get(k) or '').strip() for k in ('url','title')) or not before.get('article_key'):return None
    if not failure_kind(before) or failure_kind(before)!=failure_kind(after):return None
    # A timestamp refresh or cached export is insufficient. The actual detail /
    # audio attempt must have advanced its durable counter.
    if int(before.get('retry_count') or 0)<1 or int(after.get('retry_count') or 0)<=int(before.get('retry_count') or 0):return None
    first,second=content_digest(before),content_digest(after)
    if first!=second:return None
    return {'policy':'20261014-user-authorized-no-change-v1','disposition':'no_change',
            'accepted':False,'beforeDigest':first,'afterDigest':second,
            'emptySubtitle':not bool(str((after.get('row') or {}).get('video_content') or '').strip()),
            'previousRetryCount':before['retry_count'],'currentRetryCount':after['retry_count'],
            'importOk':True,'failureKind':failure_kind(after)}

def import_confirmed(worker_root,item):
    try:
        report=json.loads((Path(worker_root)/'.state'/'asr_backfill_status.json').read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):return False
    if not item.get('retryObservationRunId') or report.get('retryRunId')!=item['retryObservationRunId'] or not report.get('finishedAt'):return False
    rows=[r for r in report.get('keywords',[]) if r.get('keyword')==item.get('keyword') and r.get('exactFingerprint')==item['fingerprint']]
    return len(rows)==1 and rows[0].get('databaseImported') is True and rows[0].get('status') in {'partial','completed'} and bool(rows[0].get('finishedAt'))

SEAL = """
local p=redis.call('XPENDING',KEYS[1],ARGV[1],ARGV[2],ARGV[2],1)
if #p~=1 or p[1][2]~=ARGV[3] then return redis.error_reply('RETRY_LEASE_LOST') end
local raw=redis.call('HGET',KEYS[3],ARGV[4])
local s=raw and cjson.decode(raw) or {}
if s.state~='running' or s.token~=ARGV[5] or s.owner~=ARGV[3] then return redis.error_reply('RETRY_ATTEMPT_REPLACED') end
local encoded=redis.call('HGET',KEYS[2],ARGV[6])
if encoded~=ARGV[7] then return redis.error_reply('RETRY_CHECKPOINT_CHANGED') end
local cp=cjson.decode(encoded);local evidence=cjson.decode(ARGV[8]);local previous=cjson.decode(ARGV[9])
if type(cp)~='table' or type(evidence)~='table' or evidence.disposition~='no_change'
 or type(evidence.beforeDigest)~='string' or #evidence.beforeDigest~=64
 or evidence.beforeDigest~=evidence.afterDigest or evidence.importOk~=true or evidence.accepted~=false then
 return redis.error_reply('RETRY_NO_CHANGE_INVALID_EVIDENCE')
end
local decision={status='skipped_unresolved',disposition='no_change',accepted=false,
 previousCheckpoint=previous,recollectedCheckpoint=cp,noChangeEvidence=evidence,attempts=s.attempts,messageId=ARGV[2]}
redis.call('HSET',KEYS[4],ARGV[6],cjson.encode(decision))
cp.status='skipped_unresolved';cp.disposition='no_change';cp.noChangeEvidence=evidence
cp.skip_reason='Verified recollection unchanged';cp.skip_evidence_key=KEYS[4]
redis.call('HSET',KEYS[2],ARGV[6],cjson.encode(cp))
return cjson.encode({ok=true,skipped=true,accepted=false,status='skipped_unresolved',disposition='no_change'})
"""

def seal_no_change(q,args,stream,group,message_id,item,attempt,before_encoded,*,import_ok=False,stopped=False):
    after_encoded=read_checkpoint(q,args,item)
    try:
        evidence=no_change_evidence(json.loads(before_encoded),json.loads(after_encoded),import_ok=import_ok,stopped=stopped)
    except (TypeError,ValueError):return None
    if not evidence:return None
    parent=q.safe_token(item.get('source_task_id') or item['task_id'])
    return json.loads(q.redis_command(args.redis_url,args.redis_password,'EVAL',SEAL,4,
        stream,args.prefix+':video-state:'+parent,args.prefix+':video-retry-budget',args.prefix+':video-skips:'+parent,
        group,message_id,args.consumer,identity(item),attempt['token'],item['fingerprint'],
        after_encoded,json.dumps(evidence,ensure_ascii=False),before_encoded))
