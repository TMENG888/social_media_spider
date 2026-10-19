import {randomUUID} from 'node:crypto';

export const CORRECTION_POLICY='20261015-usable-db-80-v1';
export const RESUME_CORRECTION_POLICY='20261015-approved-resume-after-fixes-v2';
export const supportedCorrectionPolicy=policy=>[CORRECTION_POLICY,RESUME_CORRECTION_POLICY].includes(policy);
const CLAIM=`
local id,owner,token,policy=ARGV[1],ARGV[2],ARGV[3],ARGV[4]
local expected={'hash','hash','hash','hash','hash','zset','zset','hash','hash','zset','hash','hash'}
for i,want in ipairs(expected) do
 -- Read probes fail on a wrong type before the first write, without TYPE
 -- permission (production worker ACL intentionally does not grant it).
 if want=='hash' then redis.call('HGET',KEYS[i],'__correction_type_probe__')
 else redis.call('ZSCORE',KEYS[i],'__correction_type_probe__') end
end
local t=redis.call('TIME');local now=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
if KEYS[13] then
 local encoded=redis.call('HGET',KEYS[13],'state')
 if encoded then
  local s=cjson.decode(encoded)
  if s.manualRequired or (s.untilMs or 0)>now then return redis.error_reply('RATE_LIMIT_COOLDOWN_ACTIVE') end
 end
end
local field=id..'|'..policy
if redis.call('HEXISTS',KEYS[12],field)==1 then return redis.error_reply('CORRECTION_ALREADY_ATTEMPTED') end
local status=redis.call('HGET',KEYS[2],id)
if status~='skipped_unresolved' and status~='failed' and status~='completed_with_skips' and status~='completed' then
 return redis.error_reply('CORRECTION_REQUIRES_TERMINAL_ORIGINAL_TASK')
end
if redis.call('ZSCORE',KEYS[7],id) or redis.call('HGET',KEYS[4],id) or redis.call('HGET',KEYS[5],id) then
 return redis.error_reply('CORRECTION_ACTIVE_LEASE')
end
local payload=redis.call('HGET',KEYS[1],id)
local attempts=tonumber(redis.call('HGET',KEYS[3],id))
if not payload or not attempts or attempts<0 or attempts~=math.floor(attempts) then
 return redis.error_reply('CORRECTION_ORIGINAL_HISTORY_MISSING')
end
local ledger={policy=policy,taskId=id,originalStatus=status,originalAttempts=attempts,
 originalPayload=payload,originalResult=redis.call('HGET',KEYS[8],id) or cjson.null,
 originalError=redis.call('HGET',KEYS[9],id) or cjson.null,
 originalDeferrals=redis.call('HGET',KEYS[11],id) or cjson.null,
 correctionAttempt=attempts+1,claimedAt=now,owner=owner}
local encodedLedger=cjson.encode(ledger)
local expiry=now+tonumber(ARGV[5])
redis.call('HSET',KEYS[12],field,encodedLedger)
redis.call('HSET',KEYS[3],id,attempts+1)
redis.call('ZREM',KEYS[6],id);redis.call('ZREM',KEYS[10],id)
redis.call('HSET',KEYS[2],id,'leased');redis.call('HSET',KEYS[4],id,token)
redis.call('HSET',KEYS[5],id,owner);redis.call('ZADD',KEYS[7],expiry,id)
return cjson.encode({taskId=id,payload=payload,token=token,leaseMs=tonumber(ARGV[5]),
 leaseUntil=expiry,attempt=attempts+1,correctionPolicy=policy})
`;
const PAUSE=`
local id,token=ARGV[1],ARGV[2]
local t=redis.call('TIME');local now=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
local expiry=tonumber(redis.call('ZSCORE',KEYS[7],id))
if redis.call('HGET',KEYS[2],id)~='leased' or redis.call('HGET',KEYS[4],id)~=token
 or not expiry or expiry<=now then return redis.error_reply('LEASE_LOST') end
redis.call('HDEL',KEYS[4],id);redis.call('HDEL',KEYS[5],id);redis.call('ZREM',KEYS[7],id)
redis.call('ZREM',KEYS[6],id);redis.call('ZADD',KEYS[10],now,id)
redis.call('HSET',KEYS[2],id,'failed')
redis.call('HSET',KEYS[8],id,ARGV[3])
redis.call('HSET',KEYS[9],id,cjson.encode({code='CORRECTION_INTERRUPTED',
 message='Single correction stopped; cumulative attempts and original evidence retained',at=now}))
return cjson.encode({taskId=id,status='failed',correctionInterrupted=true,
 attempt=tonumber(redis.call('HGET',KEYS[3],id))})
`;
export async function claimCorrection(queue,owner,taskId,policy){
 if(!supportedCorrectionPolicy(policy))throw new Error('CORRECTION_POLICY_NOT_SUPPORTED');
 if(!taskId||!owner)throw new Error('CORRECTION_EXACT_TASK_REQUIRED');
 // Ledger is KEYS[12], never KEYS[11] (the existing deferral counter).
 const keys=[...queue.keys,queue.namespace+':correction-history'];
 if(queue.cooldownKey)keys.push(queue.cooldownKey);
 const raw=await queue.client.eval(CLAIM,{keys,arguments:[taskId,owner,randomUUID(),policy,String(queue.leaseMs)]});
 const {payload,...lease}=JSON.parse(raw);return {...lease,task:JSON.parse(payload)};
}
export async function pauseCorrection(queue,taskId,token,result){
 return JSON.parse(await queue.client.eval(PAUSE,{keys:queue.keys,arguments:[taskId,token,JSON.stringify(result??{})]}));
}
