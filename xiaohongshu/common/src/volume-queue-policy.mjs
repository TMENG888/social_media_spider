import {volumeDecision,validateVolumeSnapshot,VOLUME_POLICY} from './volume-acceptance.mjs';
import {isDeepStrictEqual} from 'node:util';
import {EXHAUSTION_COMPLETION} from './retry-exhaustion.mjs';
import {ANNUAL_COMPLETION_GUARD} from './annual-queue-policy.mjs';

const SCRIPT=`
${ANNUAL_COMPLETION_GUARD}
local id,encoded,snapshot_id,generation,token=ARGV[1],ARGV[2],ARGV[3],ARGV[4],ARGV[5]
local types={'hash','hash','hash','hash','hash','zset','zset','hash','hash','zset','hash','hash','hash'}
for i,want in ipairs(types) do
 if want=='hash' then redis.call('HGET',KEYS[i],'__volume_probe__') else redis.call('ZSCORE',KEYS[i],'__volume_probe__') end
end
local d=cjson.decode(encoded)
local now_parts=redis.call('TIME');local now=tonumber(now_parts[1])*1000+math.floor(tonumber(now_parts[2])/1000)
if d.policy~='${VOLUME_POLICY}' or d.snapshotId~=snapshot_id or d.taskId~=id
 or d.dbReadbackVerified~=true or d.subtitleQualityRequired~=false or d.qualityVerified~=false
 or type(d.posts)~='number' or d.posts<0 or d.posts~=math.floor(d.posts)
 or type(d.threshold)~='number' or d.threshold<1 or d.threshold~=math.floor(d.threshold)
 or type(d.checkedAtMs)~='number' or now-d.checkedAtMs>60000 or d.checkedAtMs>now+1000 then
 return redis.error_reply('VOLUME_EVIDENCE_INVALID')
end
local payload=redis.call('HGET',KEYS[1],id)
local status=redis.call('HGET',KEYS[2],id)
if not payload or not status then return redis.error_reply('VOLUME_ORIGINAL_TASK_MISSING') end
local task=cjson.decode(payload)
if task.keyword~=d.keyword or task.projectName~=d.projectName then return redis.error_reply('VOLUME_TASK_IDENTITY_MISMATCH') end
local attempts=tonumber(redis.call('HGET',KEYS[3],id))
if not attempts or attempts<0 or attempts~=math.floor(attempts) then return redis.error_reply('VOLUME_HISTORY_MISSING') end
local lease=tonumber(redis.call('ZSCORE',KEYS[7],id))
if token~='' then
 if status~='leased' or redis.call('HGET',KEYS[4],id)~=token or not lease or lease<=now then return redis.error_reply('LEASE_LOST') end
elseif (lease and lease>now) or (not lease and (status=='leased' or redis.call('HGET',KEYS[4],id) or redis.call('HGET',KEYS[5],id))) then
 return cjson.encode({status='busy',taskId=id,changed=false})
end
if d.action~='complete_by_volume' and d.action~='reset_existing' then return redis.error_reply('VOLUME_ACTION_INVALID') end
if (d.action=='complete_by_volume')~=(d.posts>=d.threshold) then return redis.error_reply('VOLUME_DECISION_MISMATCH') end
local field=id..'|'..generation
local old_ledger=redis.call('HGET',KEYS[12],field)
local archive={policy=d.policy,generation=generation,snapshotId=snapshot_id,taskId=id,at=now,
 originalStatus=status,originalAttempts=attempts,originalPayload=payload,
 originalLease=lease or cjson.null,originalToken=redis.call('HGET',KEYS[4],id) or cjson.null,
 originalOwner=redis.call('HGET',KEYS[5],id) or cjson.null,
 originalResult=redis.call('HGET',KEYS[8],id) or cjson.null,
 originalError=redis.call('HGET',KEYS[9],id) or cjson.null,
 originalDeferrals=redis.call('HGET',KEYS[11],id) or cjson.null,
 originalPending=redis.call('ZSCORE',KEYS[6],id) or cjson.null,
 originalFailed=redis.call('ZSCORE',KEYS[10],id) or cjson.null}
local encoded_archive=cjson.encode(archive)
if annual_search_closed(id,generation,snapshot_id,status) then
 return cjson.encode({status='completed',taskId=id,changed=false,acceptedByVolume=false,acceptedByAnnual=true})
end
${EXHAUSTION_COMPLETION}
if d.action=='reset_existing' then
 if token~='' then return redis.error_reply('VOLUME_RESET_REQUIRES_IDLE_TASK') end
 if annual_search_closed(id,generation,snapshot_id,status) then
  return cjson.encode({status='completed',taskId=id,changed=false,acceptedByVolume=false,acceptedByAnnual=true})
 end
 local baseline=tonumber(redis.call('HGET',KEYS[13],id))
 if not old_ledger then
  redis.call('HSET',KEYS[12],field,encoded_archive)
 end
 if not old_ledger or not baseline then redis.call('HSET',KEYS[13],id,attempts) end
 redis.call('HDEL',KEYS[4],id);redis.call('HDEL',KEYS[5],id);redis.call('ZREM',KEYS[7],id)
 redis.call('HSET',KEYS[2],id,'pending');redis.call('ZREM',KEYS[10],id)
 redis.call('ZADD',KEYS[6],now,id)
 return cjson.encode({status='pending',taskId=id,changed=true,attempts=attempts,resetExisting=true})
end
local previous_result=redis.call('HGET',KEYS[8],id)
if status=='completed' and previous_result then
 local old=cjson.decode(previous_result)
 if old.acceptedBy=='keyword_post_count_p80' and type(old.volumeAcceptance)=='table' and old.volumeAcceptance.snapshotId==snapshot_id then
  return cjson.encode({status='completed',taskId=id,changed=false,acceptedByVolume=true})
 end
end
local result={status='completed',accepted=true,acceptedBy='keyword_post_count_p80',qualityVerified=false,
 volumeAcceptance=d,completedAt=now,previousEvidenceRetained=true}
local encoded_result=cjson.encode(result)
if not old_ledger then redis.call('HSET',KEYS[12],field,encoded_archive) end
redis.call('HSET',KEYS[12],field..'|completion',encoded_archive)
redis.call('HSET',KEYS[8],id,encoded_result);redis.call('HSET',KEYS[2],id,'completed')
redis.call('ZREM',KEYS[6],id);redis.call('ZREM',KEYS[10],id);redis.call('ZREM',KEYS[7],id)
redis.call('HDEL',KEYS[4],id);redis.call('HDEL',KEYS[5],id);redis.call('HDEL',KEYS[9],id)
return cjson.encode({status='completed',taskId=id,changed=true,acceptedByVolume=true,attempts=attempts})
`;

export async function applyVolumeDecision(queue,snapshot,decision,{generation,token=null,commit=false,finishBelow=false,record=null}={}){
 validateVolumeSnapshot(snapshot);
 if(!/^[A-Za-z0-9_-]{1,100}$/.test(generation||''))throw new Error('VOLUME_GENERATION_REQUIRED');
 const {checkedAt,...expected}=volumeDecision(snapshot,{taskId:decision.taskId,posts:decision.posts,readbackVerified:decision.dbReadbackVerified,checkedAt:decision.checkedAt});
 const {checkedAt:ignored,...actual}=decision;
 if(!isDeepStrictEqual(actual,expected))throw new Error('VOLUME_DECISION_INVALID');
 if(decision.action==='requires_policy_choice')return {status:'requires_policy_choice',changed:false};
 if(!commit)return {status:'preview',changed:false,decision};
 const keys=[...queue.keys,queue.namespace+':volume-policy-history',queue.namespace+':volume-attempt-baseline'];
 const evidence={...decision,checkedAtMs:Date.parse(checkedAt)};
 return JSON.parse(await queue.client.eval(SCRIPT,{keys,arguments:[decision.taskId,JSON.stringify(evidence),snapshot.snapshotId,generation,token||'',String(queue.maxAttempts),finishBelow?'finish':'prepare',record?JSON.stringify(record):'']}));
}
