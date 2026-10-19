// Business closure is deliberately distinct from quantity/quality acceptance.
export function operationalFailure(record) {
 const text=String(record?.error||record?.status||'');
 return /LOGIN_REQUIRED|SECURITY_CHALLENGE|PLATFORM_RESTRICTION|STOP_REQUESTED|LEASE_LOST|IMPORT|MYSQL|DATABASE|CONNECTION|CONTEXT_LOST|BROWSER|RATE_LIMIT|COOLDOWN|CONFIRMATION_FAILED/i.test(text);
}
export const EXHAUSTION_COMPLETION=`
local exhausted_field=field..'|retry-exhausted-completion'
local exhausted_raw=redis.call('HGET',KEYS[12],exhausted_field)
local current_result=redis.call('HGET',KEYS[8],id)
if exhausted_raw and current_result then
 local a=cjson.decode(exhausted_raw);local r=cjson.decode(current_result)
 if a.completedResult==current_result and a.generation==generation and a.snapshotId==snapshot_id
  and status=='completed' and r.acceptedBy=='retry_exhausted_completion' and r.quantityAccepted==false then
  return cjson.encode({status='completed',taskId=id,changed=false,acceptedByExhaustion=true,acceptedByVolume=false}) end
end
local baseline=tonumber(redis.call('HGET',KEYS[13],id))
if d.posts<d.threshold and old_ledger and baseline and attempts-baseline>=tonumber(ARGV[6]) then
 local blocked=false
 if token=='' then
  local previous=string.upper((redis.call('HGET',KEYS[9],id) or '')..(current_result or ''))
  for _,p in ipairs({'LOGIN_REQUIRED','SECURITY_CHALLENGE','PLATFORM_RESTRICTION','STOP_REQUESTED','LEASE_LOST','IMPORT_FAILED','MYSQL','DATABASE','CONNECTION_ERROR','CONTEXT_LOST','RATE_LIMIT','COOLDOWN','CONFIRMATION_FAILED'}) do
   if string.find(previous,p,1,true) then blocked=true end
  end
 end
 if blocked then return cjson.encode({status='retry_exhausted_action_required',taskId=id,changed=false}) end
 local result={status='completed',accepted=true,businessCompleted=true,acceptedBy='retry_exhausted_completion',
  quantityAccepted=false,qualityVerified=false,volumeAcceptance=d,completedAt=now,
  attempts=attempts,retryBudget=tonumber(ARGV[6]),generationAttempts=attempts-baseline,
  missingPosts=math.max(0,d.threshold-d.posts),previousEvidenceRetained=true,
  finalAttemptEvidence=ARGV[8]~='' and cjson.decode(ARGV[8]) or cjson.null}
 local value=cjson.encode(result)
 local ledger=cjson.encode({generation=generation,snapshotId=snapshot_id,completedResult=value,archive=archive,at=now})
 redis.call('HSET',KEYS[12],exhausted_field,ledger)
 redis.call('HSET',KEYS[8],id,value);redis.call('HSET',KEYS[2],id,'completed')
 redis.call('ZREM',KEYS[6],id);redis.call('ZREM',KEYS[7],id);redis.call('ZREM',KEYS[10],id)
 redis.call('HDEL',KEYS[4],id);redis.call('HDEL',KEYS[5],id);redis.call('HDEL',KEYS[9],id)
 return cjson.encode({status='completed',taskId=id,changed=true,acceptedByExhaustion=true,acceptedByVolume=false,attempts=attempts})
end
if d.action=='reset_existing' and token~='' and ARGV[7]=='finish' then
 return cjson.encode({status='retry_pending',taskId=id,changed=false})
end
`;
