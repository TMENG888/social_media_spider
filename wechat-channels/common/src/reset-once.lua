-- One original keyword, one fresh recollection. Never flush data or reset history.
-- KEYS ledger,archive,status,attempts,tokens,owners,pending/stream,leases,results,errors,failed,baseline,payload
local mode,id,engine,token,owner,mid,group,field=ARGV[1],ARGV[2],ARGV[3],ARGV[4],ARGV[5],ARGV[6],ARGV[7],ARGV[8]
local evidence=cjson.decode(ARGV[9] or '{}')
local expected=ARGV[10]
local idle=tonumber(ARGV[11]) or 300000
local t=redis.call('TIME');local now=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
local raw=redis.call('HGET',KEYS[1],id)
local s=raw and cjson.decode(raw) or nil
local old=redis.call('HGET',KEYS[3],id)
local function out(v) return cjson.encode(v) end
local function completed()
 local result=cjson.decode(s.result or '{}')
 return out({status='completed',changed=false,acceptedByResetOnce=true,businessCompleted=true,quantityAccepted=false,
  pendingImport=result.pendingImport==true,collectionSucceeded=result.collectionSucceeded==true,
  dataImported=result.dataImported==true})
end
if mode=='read' then return raw or '{}' end
if s and s.state=='completed' then return completed() end
if mode~='arm' and not s then return out({status='absent'}) end
-- Type probes before any writes: Redis Lua is atomic, not rollback capable.
redis.call('HGET',KEYS[2],'__probe__');redis.call('HGET',KEYS[4],'__probe__')
redis.call('HGET',KEYS[5],'__probe__');redis.call('HGET',KEYS[9],'__probe__')
redis.call('HGET',KEYS[10],'__probe__');redis.call('HGET',KEYS[12],'__probe__')
if engine=='hash' then
 redis.call('HGET',KEYS[6],'__probe__');redis.call('ZSCORE',KEYS[7],'__probe__')
 redis.call('ZSCORE',KEYS[8],'__probe__');redis.call('ZSCORE',KEYS[11],'__probe__')
 redis.call('HGET',KEYS[13],id)
elseif engine~='stream' then return redis.error_reply('RESET_ENGINE_INVALID') end
local pending={}
if engine=='stream' then
 local rows=redis.call('XRANGE',KEYS[7],mid,mid)
 if #rows~=1 then return redis.error_reply('RESET_ORIGINAL_MESSAGE_MISSING') end
 local payload=nil
 for i=1,#rows[1][2],2 do if rows[1][2][i]=='payload' then payload=rows[1][2][i+1] end end
 local p=cjson.decode(payload or '{}')
 if p.task_id~=id then return redis.error_reply('RESET_ORIGINAL_IDENTITY_MISMATCH') end
 pending=redis.call('XPENDING',KEYS[7],group,mid,mid,1)
end
local lease=engine=='hash' and tonumber(redis.call('ZSCORE',KEYS[8],id)) or nil
local current_token=redis.call('HGET',KEYS[5],id)
local function hot()
 if engine=='hash' then return (lease and lease>now) or (current_token and not lease) end
 return current_token or (#pending>0 and tonumber(pending[1][3])<idle)
end
local function validate_owner()
 if engine=='hash' then
  if old~='leased' or current_token~=token or not lease or lease<=now then return false end
 else
  if current_token~=token or #pending~=1 or pending[1][2]~=owner then return false end
 end
 return true
end
local function archive(tag,details)
 redis.call('HSET',KEYS[2],id..'|'..tag,cjson.encode(details))
end
local function finish(record,stale)
 local import_ok=record.importOk==true
 local result={status='completed',accepted=true,businessCompleted=true,acceptedBy='reset_once_recollection',
  taskId=id,keyword=s.preservation.keyword,topic=s.preservation.topic,messageId=mid,
  quantityAccepted=false,qualityVerified=false,collectionSucceeded=record.collectionSucceeded==true,
  dataImported=import_ok,pendingImport=not import_ok,completedAt=now,
  policy=s.policy,previousDataPreserved=true,attemptHistoryPreserved=true,
  preservation=s.preservation,lastVerifiedPosts=s.preservation.posts,
  outcome=record,staleLeaseClosed=stale or false}
 local encoded=cjson.encode(result)
 s.state='completed';s.finishedAt=now;s.result=encoded
 archive('final', {previousStatus=old,previousResult=redis.call('HGET',KEYS[9],id),result=encoded,policy=s.policy})
 redis.call('HSET',KEYS[1],id,cjson.encode(s))
 redis.call('HSET',KEYS[3],id,engine=='hash' and 'completed' or encoded)
 if engine=='hash' then
  redis.call('HSET',KEYS[9],id,encoded)
  redis.call('ZREM',KEYS[7],id);redis.call('ZREM',KEYS[8],id);redis.call('ZREM',KEYS[11],id)
  redis.call('HDEL',KEYS[6],id)
 else redis.call('XACK',KEYS[7],group,mid) end
 redis.call('HDEL',KEYS[5],id)
 return out({status='completed',changed=true,acceptedByResetOnce=true,businessCompleted=true,
  quantityAccepted=false,pendingImport=not import_ok,dataImported=import_ok,collectionSucceeded=result.collectionSucceeded})
end
if mode=='arm' then
 if s then return out({status=s.state,changed=false,alreadyArmed=true}) end
 if old~=expected then return out({status='changed_since_preview',changed=false}) end
 if hot() then return out({status='busy',changed=false}) end
 if not old then return redis.error_reply('RESET_ORIGINAL_MISSING') end
 local previous=engine=='hash' and old or cjson.decode(old).status
 if not ({pending=true,failed=true,retry_pending=true,completed_with_deferred_retries=true,completed_with_dead_letters=true,safety_hold=true})[previous] then
  return out({status='not_abnormal',changed=false}) end
 if evidence.dbReadbackVerified~=true or evidence.localExportsChecked~=true or evidence.localImportConfirmed~=true
  or type(evidence.posts)~='number' or evidence.posts<0
  or type(evidence.checkedAtMs)~='number' or now-evidence.checkedAtMs>60000 or evidence.checkedAtMs>now+1000 then
  return redis.error_reply('RESET_PRESERVATION_PROOF_REQUIRED') end
 local attempt=redis.call('HGET',KEYS[4],field)
 local backup={originalStatus=old,originalAttempts=attempt,originalResult=redis.call('HGET',KEYS[9],id),
  originalError=redis.call('HGET',KEYS[10],id),originalToken=current_token,originalDelivery=pending,
  originalPayload=engine=='hash' and redis.call('HGET',KEYS[13],id) or mid,at=now,preservation=evidence}
 s={policy='reset-once-20261016-v1',state='armed',armedAt=now,starts=0,pauses=0,
  preservation=evidence,attemptBaseline=tonumber(attempt) or 0,originalMessageId=mid}
 local value=engine=='hash' and 'pending' or cjson.encode({status='recollect_pending',accepted=false,businessCompleted=false,
  taskId=id,messageId=mid,policy=s.policy,previousDataPreserved=true})
 archive('original',backup)
 redis.call('HSET',KEYS[1],id,cjson.encode(s))
 redis.call('HSET',KEYS[3],id,value)
 if engine=='hash' then
  redis.call('HSET',KEYS[12],id,tonumber(attempt) or 0)
  redis.call('ZADD',KEYS[7],now,id);redis.call('ZREM',KEYS[11],id)
  redis.call('ZREM',KEYS[8],id);redis.call('HDEL',KEYS[5],id);redis.call('HDEL',KEYS[6],id)
 end
 return out({status='armed',changed=true,policy=s.policy})
end
if mode=='prepare' then
 if s.state=='running' then
  local still_live=engine=='hash' and hot() or engine=='stream' and
   ((current_token and current_token~=s.token) or (#pending>0 and tonumber(pending[1][3])<idle))
  if still_live then return out({status='busy',changed=false}) end
  -- An expired hash lease or idle original stream delivery is a failed replay.
  -- Do not call this an import success: retained artifacts remain pending.
  return finish({error='RECOLLECTION_LEASE_EXPIRED',importOk=false,collectionSucceeded=false},true)
 end
  if engine=='hash' then
   if hot() then return out({status='busy',changed=false}) end
   redis.call('HSET',KEYS[12],id,tonumber(redis.call('HGET',KEYS[4],id)) or 0)
   return out({status='pending',recollection=true,policy=s.policy}) end
 if hot() then return out({status='busy',changed=false}) end
 local claimed=redis.call('XCLAIM',KEYS[7],group,owner,idle,mid,'FORCE')
 if #claimed~=1 then return out({status='busy',changed=false}) end
 s.state='running';s.starts=s.starts+1;s.startedAt=now;s.token=token;s.owner=owner
 redis.call('HSET',KEYS[1],id,cjson.encode(s));redis.call('HSET',KEYS[5],id,token)
 redis.call('HINCRBY',KEYS[4],field,1)
 redis.call('HSET',KEYS[3],id,cjson.encode({status='running',taskId=id,messageId=mid,worker=owner,policy=s.policy}))
 return out({status='claimed',recollection=true,policy=s.policy})
end
if mode=='start' then
 if engine~='hash' or s.state~='armed' or not validate_owner() then return redis.error_reply('RESET_LEASE_LOST') end
 s.state='running';s.startedAt=now;s.starts=s.starts+1;s.token=token;s.owner=owner
 redis.call('HSET',KEYS[1],id,cjson.encode(s))
 return out({status='running',policy=s.policy})
end
if mode=='finish' or mode=='pause' then
 if s.state~='running' or s.token~=token or not validate_owner() then return redis.error_reply('RESET_LEASE_LOST') end
 if mode=='finish' then return finish(evidence,false) end
 s.state='armed';s.pauses=s.pauses+1
 archive('pause-'..s.pauses,{outcome=evidence,at=now,attempts=redis.call('HGET',KEYS[4],field)})
 s.token=nil;s.owner=nil
 redis.call('HSET',KEYS[1],id,cjson.encode(s))
 if engine=='stream' then
  redis.call('HDEL',KEYS[5],id)
  redis.call('XCLAIM',KEYS[7],group,owner,0,mid,'IDLE',idle,'JUSTID')
  redis.call('HSET',KEYS[3],id,cjson.encode({status='recollect_pending',policy=s.policy,paused=true}))
 end
 return out({status='paused',changed=true})
end
return redis.error_reply('RESET_MODE_INVALID')
