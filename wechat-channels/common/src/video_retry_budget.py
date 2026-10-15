"""Shared, lease-fenced attempts. Review is NOT completion; never XACK here."""
import hashlib
import json
import re
import uuid


def is_content_failure(guard):
    """Fail closed: unhealthy nodes and unknown outcomes are not missing content."""
    if guard.get('ok') or guard.get('deferred'):
        return False
    reason = str(guard.get('reason') or guard.get('error') or '')
    if re.search(r'LEASE|LOGIN|SECURITY|CAPTCHA|COOLDOWN|MYSQL|IMPORT|MEMORY|RESOURCE|ECONN|ETIMEDOUT|LOCK.*TIMEOUT|DATABASE OR DISK IS FULL|MODEL.*(?:LOAD|INIT)|STOP_|登录|验证码|风控|冷却|租约|内存|资源|入库|模型初始化|模型加载', reason, re.I):
        return False
    return guard.get('status') in {'retry_pending','partial_review','dead_letter','completed_metadata','pending','failed'} and bool(
        re.search(r'ASR_QUALITY|quality rejected|transcript.*(?:short|coverage|reject)|hallucination|字幕.*(?:不完整|质量|拒绝)|详情.*(?:缺失|不可访问|无法浏览)|DETAIL.*(?:NOT_RENDERED|INCOMPLETE|UNAVAILABLE)|identity_recovery_required', reason, re.I)
    )

BEGIN = """
local p=redis.call('XPENDING',KEYS[2],ARGV[1],ARGV[2],ARGV[2],1)
if #p~=1 or p[1][2]~=ARGV[3] then return redis.error_reply('RETRY_LEASE_LOST') end
local old=redis.call('HGET',KEYS[1],ARGV[4])
local s=old and cjson.decode(old) or {attempts=0}
s.maxAttempts=s.maxAttempts or tonumber(ARGV[5])
if s.state=='blocked' then
 return cjson.encode({allowed=false,state='blocked',attempts=s.attempts or 0,deferrals=s.deferrals or 0,reason=s.reason,requiresAction=true})
end
if s.state=='skipped' then
 return cjson.encode({allowed=false,state='skipped',attempts=s.attempts or 0,reason=s.reason})
end
if s.state=='exhausted' or (s.attempts or 0)>=s.maxAttempts then
 s.state='exhausted'; s.reason=s.reason or 'RETRY_BUDGET_EXHAUSTED'
 redis.call('HSET',KEYS[1],ARGV[4],cjson.encode(s))
 return cjson.encode({allowed=false,state='exhausted',attempts=s.attempts or 0,reason=s.reason or 'RETRY_BUDGET_EXHAUSTED'})
end
local t=redis.call('TIME')
s.attempts=(s.attempts or 0)+1
s.state='running'; s.token=ARGV[6]; s.owner=ARGV[3]; s.messageId=ARGV[2]
s.startedAt=tonumber(t[1]); s.strategy=ARGV[7]
redis.call('HSET',KEYS[1],ARGV[4],cjson.encode(s))
return cjson.encode({allowed=true,attempts=s.attempts,token=s.token})
"""

FINISH = """
local p=redis.call('XPENDING',KEYS[2],ARGV[1],ARGV[2],ARGV[2],1)
if #p~=1 or p[1][2]~=ARGV[3] then return redis.error_reply('RETRY_LEASE_LOST') end
local old=redis.call('HGET',KEYS[1],ARGV[4])
if not old then return redis.error_reply('RETRY_ATTEMPT_MISSING') end
local s=cjson.decode(old)
if s.token~=ARGV[5] or s.owner~=ARGV[3] then return redis.error_reply('RETRY_ATTEMPT_REPLACED') end
if s.state~='running' then return redis.error_reply('RETRY_ATTEMPT_ALREADY_FINISHED') end
local g=cjson.decode(ARGV[6]); s.outcome=g
local t=redis.call('TIME'); s.finishedAt=tonumber(t[1])
if not g.ok and g.deferred then
 s.attempts=math.max(0,s.attempts-1); s.state='pending'; s.reason=g.deferReason or 'NODE_UNAVAILABLE'
 -- Intentional user stop is not a defect. Other no-evidence retries cannot loop forever.
 if not g.cooperativeStop then
  s.deferrals=(s.deferrals or 0)+1
  if s.deferrals>=3 then s.state='blocked'; s.requiresAction=true end
 end
elseif g.ok and g.skipped then
 s.state='skipped'
elseif g.ok then
 s.state='accepted'
elseif s.attempts>=(s.maxAttempts or tonumber(ARGV[7])) then
 s.state='exhausted'; s.reason='RETRY_BUDGET_EXHAUSTED'
else s.state='pending' end
redis.call('HSET',KEYS[1],ARGV[4],cjson.encode(s))
return cjson.encode(s)
"""

def identity(item):
    parent=item.get('source_task_id') or item.get('task_id')
    fingerprint=item.get('fingerprint')
    if not parent or not fingerprint:
        raise ValueError('RETRY_IDENTITY_MISSING')
    return hashlib.sha256(f'{parent}|{fingerprint}'.encode()).hexdigest()

RESTORE_IDENTITY = """
local p=redis.call('XPENDING',KEYS[1],ARGV[1],ARGV[2],ARGV[2],1)
if #p~=1 or p[1][2]~=ARGV[3] then return redis.error_reply('RETRY_LEASE_LOST') end
local raw=redis.call('HGET',KEYS[2],ARGV[4])
if not raw then return redis.error_reply('RETRY_CHECKPOINT_MISSING') end
local cp=cjson.decode(raw); local source=cjson.decode(ARGV[5])
local function filled(v) return type(v)=='string' and v:match('%S')~=nil end
if type(cp)~='table' or type(source)~='table' or source.fingerprint~=ARGV[4] then
 return redis.error_reply('RETRY_IDENTITY_SOURCE_INVALID')
end
local row=type(cp.row)=='table' and cp.row or {}
local sr=type(source.row)=='table' and source.row or {}
if not filled(sr.url) or not filled(sr.title) then return raw end
if (filled(cp.article_key) and filled(source.article_key) and cp.article_key~=source.article_key)
 or (filled(row.url) and row.url~=sr.url)
 or (filled(cp.fingerprint) and cp.fingerprint~=ARGV[4]) then
 return redis.error_reply('RETRY_IDENTITY_CONFLICT')
end
local changed=false
for _,field in ipairs({'url','title','author_name'}) do
 if not filled(row[field]) and filled(sr[field]) then row[field]=sr[field]; changed=true end
end
if not filled(cp.article_key) and filled(source.article_key) then cp.article_key=source.article_key; changed=true end
if changed then
 cp.row=row; cp.identityRecovery={source='original_stream_checkpoint',messageId=ARGV[2],fingerprint=ARGV[4]}
 raw=cjson.encode(cp); redis.call('HSET',KEYS[2],ARGV[4],raw)
end
return raw
"""


def restore_retry_identity(q,args,stream,group,message_id,item):
    """Fill identity only from the leased original payload; never copy old outcome."""
    source=item.get('checkpoint') or {}
    if not isinstance(source,dict) or not isinstance(source.get('row'),dict):
        return None
    row=source['row']
    if not str(row.get('url') or '').strip() or not str(row.get('title') or '').strip():
        return None
    parent=q.safe_token(item.get('source_task_id') or item['task_id'])
    raw=q.redis_command(args.redis_url,args.redis_password,'EVAL',RESTORE_IDENTITY,2,
        stream,args.prefix+':video-state:'+parent,group,message_id,args.consumer,
        item['fingerprint'],json.dumps(source,ensure_ascii=False))
    current=json.loads(raw)
    item['checkpoint']=current
    return current


def begin(q, args, stream, group, message_id, item):
    token=uuid.uuid4().hex
    raw=q.redis_command(args.redis_url,args.redis_password,'EVAL',BEGIN,2,
        args.prefix+':video-retry-budget',stream,group,message_id,args.consumer,
        identity(item),int(getattr(args,'video_retry_max_attempts',3)),token,'20261013-evidence-v1')
    return json.loads(raw)

def finish(q,args,stream,group,message_id,item,attempt,guard):
    guard=dict(guard)
    if guard.get('status')=='dead_letter':
        guard.update(ok=False,accepted=False)
    if not guard.get('ok') and not guard.get('deferred') and not is_content_failure(guard):
        guard.update(deferred=True,deferReason='NON_CONTENT_OR_UNKNOWN_FAILURE')
    raw=q.redis_command(args.redis_url,args.redis_password,'EVAL',FINISH,2,
        args.prefix+':video-retry-budget',stream,group,message_id,args.consumer,
        identity(item),attempt['token'],json.dumps(guard,ensure_ascii=False),
        int(getattr(args,'video_retry_max_attempts',3)))
    return json.loads(raw)

SKIP = """
local p=redis.call('XPENDING',KEYS[2],ARGV[1],ARGV[2],ARGV[2],1)
if #p~=1 or p[1][2]~=ARGV[3] then return redis.error_reply('RETRY_LEASE_LOST') end
local old=redis.call('HGET',KEYS[1],ARGV[4])
if not old then return redis.error_reply('RETRY_ATTEMPT_MISSING') end
local s=cjson.decode(old)
if (s.state~='exhausted' and s.state~='skipped') or s.attempts<(s.maxAttempts or tonumber(ARGV[6])) then return redis.error_reply('RETRY_NOT_EXHAUSTED') end
local encoded=redis.call('HGET',KEYS[3],ARGV[5])
if not encoded then return redis.error_reply('RETRY_CHECKPOINT_MISSING') end
if encoded~=ARGV[7] then return redis.error_reply('RETRY_CHECKPOINT_CHANGED') end
local cp=cjson.decode(encoded)
if type(cp)~='table' then return redis.error_reply('RETRY_CHECKPOINT_INVALID') end
local row=type(cp.row)=='table' and cp.row or {}
local function nonempty(value) return type(value)=='string' and value:match('%S')~=nil end
if not nonempty(cp.article_key) and not (nonempty(row.url) or nonempty(row.title) or nonempty(cp.title)) then
 return redis.error_reply('RETRY_IDENTITY_MISSING')
end
if cp.status=='completed' or cp.status=='no_content' or cp.status=='not_applicable' then
 return cjson.encode({skipped=false,status=cp.status})
end
if cp.status=='skipped_unresolved' and redis.call('HEXISTS',KEYS[4],ARGV[5])==1 then
 return cjson.encode({skipped=true,status='skipped_unresolved',accepted=false,attempts=s.attempts})
end
if s.state~='exhausted' then return redis.error_reply('RETRY_NOT_EXHAUSTED') end
local t=redis.call('TIME')
local decision={status='skipped_unresolved',reason=cp.last_error or s.reason,
 attempts=s.attempts,dispositionAt=tonumber(t[1]),policy='20261013-user-authorized-finite-skip',
 previousCheckpoint=cp,budget=s}
redis.call('HSET',KEYS[4],ARGV[5],cjson.encode(decision))
cp.status='skipped_unresolved'; cp.asr_status='skipped_unresolved'; cp.skip_reason=decision.reason
cp.skip_attempts=s.attempts; cp.skip_evidence_key=KEYS[4]
cp.retry_count=math.max(tonumber(cp.retry_count) or 0,s.attempts)
redis.call('HSET',KEYS[3],ARGV[5],cjson.encode(cp))
s.state='skipped'; s.outcome={ok=true,skipped=true,accepted=false,status='skipped_unresolved'}
redis.call('HSET',KEYS[1],ARGV[4],cjson.encode(s))
return cjson.encode({skipped=true,status='skipped_unresolved',accepted=false,attempts=s.attempts})
"""

def skip_exhausted(q,args,stream,group,message_id,item):
    # Original data stays intact; this function NEVER acknowledges a message.
    parent=q.safe_token(item.get('source_task_id') or item['task_id'])
    state_key=args.prefix+':video-state:'+parent
    encoded=q.redis_command(args.redis_url,args.redis_password,'HGET',state_key,item['fingerprint'])
    try:
        cp=json.loads(encoded)
    except (TypeError,ValueError):
        raise q.RedisError('RETRY_CHECKPOINT_INVALID')
    if cp.get('status') not in {'completed','no_content','not_applicable','skipped_unresolved'} and not is_content_failure(
        {'status':cp.get('status'),'reason':cp.get('last_error')}
    ):
        raise q.RedisError('RETRY_NON_CONTENT_FAILURE_CANNOT_SKIP')
    raw=q.redis_command(args.redis_url,args.redis_password,'EVAL',SKIP,4,
        args.prefix+':video-retry-budget',stream,state_key,
        args.prefix+':video-skips:'+parent,group,message_id,args.consumer,
        identity(item),item['fingerprint'],int(getattr(args,'video_retry_max_attempts',3)),encoded)
    return json.loads(raw)

ACK_TERMINAL = """
local p=redis.call('XPENDING',KEYS[1],ARGV[1],ARGV[2],ARGV[2],1)
if #p~=1 or p[1][2]~=ARGV[3] then return redis.error_reply('RETRY_LEASE_LOST') end
local raw=redis.call('HGET',KEYS[2],ARGV[4])
if not raw then return redis.error_reply('RETRY_CHECKPOINT_MISSING') end
local cp=cjson.decode(raw)
if type(cp)~='table' or (cp.status~='completed' and cp.status~='no_content' and
 cp.status~='not_applicable' and cp.status~='skipped_unresolved') then
 return redis.error_reply('RETRY_NOT_TERMINAL')
end
return redis.call('XACK',KEYS[1],ARGV[1],ARGV[2])
"""

def acknowledge_terminal(q,args,stream,group,message_id,item):
    """Owner and exact checkpoint are checked atomically with XACK."""
    parent=q.safe_token(item.get('source_task_id') or item['task_id'])
    return q.redis_command(args.redis_url,args.redis_password,'EVAL',ACK_TERMINAL,2,
        stream,args.prefix+':video-state:'+parent,group,message_id,args.consumer,item['fingerprint'])


# One-time repair for the old FINISH bug: a real exhausted content failure
# was recorded as accepted and ACKed. No claim, task creation or extra ACK.
SEAL_ACKED_FAILURE = """
if #redis.call('XPENDING',KEYS[1],ARGV[1],ARGV[2],ARGV[2],1)~=0 then
 return redis.error_reply('RETRY_STILL_PENDING')
end
if #redis.call('XRANGE',KEYS[1],ARGV[2],ARGV[2])~=1 then return redis.error_reply('RETRY_MESSAGE_MISSING') end
local encoded=redis.call('HGET',KEYS[2],ARGV[3])
local raw=redis.call('HGET',KEYS[3],ARGV[4])
if encoded~=ARGV[5] or raw~=ARGV[6] then return redis.error_reply('RETRY_REPAIR_SNAPSHOT_CHANGED') end
local cp=cjson.decode(encoded); local s=cjson.decode(raw)
if cp.status=='skipped_unresolved' and s.state=='skipped' and redis.call('HEXISTS',KEYS[4],ARGV[3])==1 then
 return cjson.encode({skipped=true,accepted=false,idempotent=true,attempts=s.attempts})
end
if cp.status~='dead_letter' or cp.asr_status~='dead_letter' or cp.article_key~=ARGV[7] or
 s.state~='accepted' or s.messageId~=ARGV[2] or s.attempts<(s.maxAttempts or 3) or
 not s.outcome or s.outcome.skipped~=true or s.outcome.accepted~=false or s.outcome.status~='dead_letter' then
 return redis.error_reply('RETRY_REPAIR_NOT_PROVEN')
end
local t=redis.call('TIME')
local decision={status='skipped_unresolved',accepted=false,reason=cp.last_error,
 attempts=s.attempts,dispositionAt=tonumber(t[1]),policy='20261013-acked-terminal-correction',
 previousCheckpoint=cp,budget=s,messageId=ARGV[2],noAdditionalAck=true}
redis.call('HSET',KEYS[4],ARGV[3],cjson.encode(decision))
cp.status='skipped_unresolved'; cp.asr_status='skipped_unresolved'
cp.retry_count=math.max(tonumber(cp.retry_count) or 0,s.attempts)
cp.skip_reason=decision.reason; cp.skip_attempts=s.attempts; cp.skip_evidence_key=KEYS[4]
s.state='skipped'; s.correctedAt=tonumber(t[1]); s.outcome={ok=true,skipped=true,accepted=false,status='skipped_unresolved'}
redis.call('HSET',KEYS[2],ARGV[3],cjson.encode(cp))
redis.call('HSET',KEYS[3],ARGV[4],cjson.encode(s))
return cjson.encode({skipped=true,accepted=false,attempts=s.attempts,noAdditionalAck=true})
"""


def seal_acked_content_failure(q,args,stream,group,message_id,item,expected_checkpoint,expected_budget,article_key):
    """Exact snapshot repair only; fail closed on ownership/content changes."""
    cp=json.loads(expected_checkpoint)
    if cp.get('status')!='skipped_unresolved' and not is_content_failure(
        {'status':cp.get('status'),'reason':cp.get('last_error')}
    ):
        raise q.RedisError('RETRY_NON_CONTENT_FAILURE_CANNOT_SKIP')
    if cp.get('article_key')!=article_key or cp.get('fingerprint')!=item.get('fingerprint'):
        raise q.RedisError('RETRY_IDENTITY_CHANGED')
    parent=q.safe_token(item.get('source_task_id') or item['task_id'])
    return json.loads(q.redis_command(args.redis_url,args.redis_password,'EVAL',SEAL_ACKED_FAILURE,4,
        stream,args.prefix+':video-state:'+parent,args.prefix+':video-retry-budget',
        args.prefix+':video-skips:'+parent,group,message_id,item['fingerprint'],identity(item),
        expected_checkpoint,expected_budget,article_key))
