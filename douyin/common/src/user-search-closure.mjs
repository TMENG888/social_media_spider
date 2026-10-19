import {isDeepStrictEqual} from 'node:util';
import {volumeDecision,validateVolumeSnapshot} from './volume-acceptance.mjs';
import {verifiedAnnualSearchEnd} from './collection-policy.mjs';

// An explicit, task-bound human disposition, never an automatic P80 success.
// The immutable ledger must match the current result byte-for-byte before a
// later prepare is permitted to honor the exception.
export const USER_SEARCH_CLOSURE_GUARD=`
local function user_search_closed(id,generation,snapshot_id,status)
 if status~='completed_with_skips' then return false end
 local raw=redis.call('HGET',KEYS[8],id)
 local ledger=redis.call('HGET',KEYS[12],id..'|'..generation..'|user-search-closure')
 if not raw or not ledger then return false end
 local aok,a=pcall(cjson.decode,ledger);local rok,r=pcall(cjson.decode,raw)
 if not aok or not rok or type(a)~='table' or type(r)~='table' or type(a.approval)~='table' then return false end
 return a.completedResult==raw and a.approval.taskId==id and a.approval.generation==generation
  and a.approval.snapshotId==snapshot_id and r.acceptedBy=='user_approved_search_exhaustion'
  and r.accepted==false and r.quantityAccepted==false and r.businessCompleted==true
end
`;

const stateScript=`
local out={}
for i,key in ipairs(KEYS) do
 local value
 if i==6 or i==7 or i==10 then value=redis.call('ZSCORE',key,ARGV[1])
 elseif i==12 then value=redis.call('HGET',key,ARGV[2])
 else value=redis.call('HGET',key,ARGV[1]) end
 out[i]=value or false
end
return cjson.encode(out)
`;
const closureKeys=q=>[...q.keys,q.namespace+':volume-policy-history',q.namespace+':volume-attempt-baseline'];
const field=(id,g)=>id+'|'+g+'|user-search-closure';

export async function readUserClosureState(queue,taskId,generation){
 return JSON.parse(await queue.client.eval(stateScript,{keys:closureKeys(queue),arguments:[taskId,field(taskId,generation)]}));
}

export function validateUserSearchClosure(snapshot,decision,{approval,summary,expected}={}){
 validateVolumeSnapshot(snapshot);
 const rebuilt=volumeDecision(snapshot,{taskId:decision.taskId,posts:decision.posts,readbackVerified:decision.dbReadbackVerified,checkedAt:decision.checkedAt});
 if(!isDeepStrictEqual(rebuilt,decision)||decision.ok!==false||decision.posts<1||decision.threshold<1)throw new Error('USER_CLOSURE_VOLUME_INVALID');
 if(!approval||approval.source!=='explicit_user_instruction'||!/^[-a-zA-Z0-9_]{1,100}$/.test(approval.id||'')
  ||!/^[-a-zA-Z0-9_]{1,100}$/.test(approval.generation||'')||!approval.text?.trim()
  ||!Number.isFinite(Date.parse(approval.approvedAt))||approval.taskId!==decision.taskId
  ||approval.keyword!==decision.keyword||approval.projectName!==decision.projectName
  ||approval.snapshotId!==snapshot.snapshotId)throw new Error('USER_CLOSURE_EXPLICIT_APPROVAL_REQUIRED');
 if(!verifiedAnnualSearchEnd(summary)||summary.keyword!==decision.keyword||summary.savedPosts!==decision.posts
  ||!Array.isArray(summary.knownIncomplete)||summary.knownIncomplete.some(x=>typeof x!=='string')
  ||new Set(summary.knownIncomplete).size!==summary.knownIncomplete.length
  ||!isDeepStrictEqual(summary.searchExhaustion.gaps.slice().sort(),summary.knownIncomplete.slice().sort()))throw new Error('USER_CLOSURE_SEARCH_PROOF_INVALID');
 if(!Array.isArray(expected)||expected.length!==13||expected.some(x=>x!==false&&typeof x!=='string'))throw new Error('USER_CLOSURE_CAS_REQUIRED');
 return true;
}

const closeScript=USER_SEARCH_CLOSURE_GUARD+`
local id,generation=ARGV[1],ARGV[2]
local d,approval,summary,expected=cjson.decode(ARGV[3]),cjson.decode(ARGV[4]),cjson.decode(ARGV[5]),cjson.decode(ARGV[6])
local current={}
for i,key in ipairs(KEYS) do
 local value
 if i==6 or i==7 or i==10 then value=redis.call('ZSCORE',key,id)
 elseif i==12 then value=redis.call('HGET',key,id..'|'..generation..'|user-search-closure')
 else value=redis.call('HGET',key,id) end
 current[i]=value or false
end
local now_parts=redis.call('TIME');local now=tonumber(now_parts[1])*1000+math.floor(tonumber(now_parts[2])/1000)
if now-d.checkedAtMs>60000 or d.checkedAtMs>now+1000 then return redis.error_reply('USER_CLOSURE_STALE_SQL') end
if user_search_closed(id,generation,d.snapshotId,current[2]) then
 if cjson.decode(current[12]).approval.id~=approval.id then return redis.error_reply('USER_CLOSURE_APPROVAL_CONFLICT') end
 return cjson.encode({status='completed_with_skips',changed=false,acceptedByVolume=false})
end
for i=1,13 do if current[i]~=expected[i] then return redis.error_reply('USER_CLOSURE_STATE_CHANGED') end end
if current[4] or current[5] or current[7] or current[2]=='leased' then return redis.error_reply('USER_CLOSURE_LEASE_PRESENT') end
if current[2]~='failed' and current[2]~='pending' then return redis.error_reply('USER_CLOSURE_STATUS_INVALID') end
if current[12] then return redis.error_reply('USER_CLOSURE_LEDGER_CONFLICT') end
local task=cjson.decode(current[1])
if task.keyword~=d.keyword or task.projectName~=d.projectName or approval.taskId~=id or approval.snapshotId~=d.snapshotId
 or approval.generation~=generation then return redis.error_reply('USER_CLOSURE_IDENTITY_MISMATCH') end
local attempts,baseline=tonumber(current[3]),tonumber(current[13])
if not attempts or not baseline or attempts<baseline then return redis.error_reply('USER_CLOSURE_HISTORY_INVALID') end
local result={status='completed_with_skips',businessCompleted=true,accepted=false,quantityAccepted=false,
 acceptedBy='user_approved_search_exhaustion',qualityVerified=false,volumeAcceptance=d,
 userClosure=approval,searchSummary=summary,completedAt=now,previousEvidenceRetained=true,
 missingCandidateIds=summary.knownIncomplete,skipReason='verified_search_exhausted_user_approved',deletedConfirmed=false}
local encoded=cjson.encode(result)
local archive=cjson.encode({before=current,approval=approval,completedResult=encoded,at=now,
 previousPolicyHistory=redis.call('HGET',KEYS[12],id..'|'..generation) or false})
-- All potentially failing reads/JSON validation precede the first mutation.
redis.call('HSET',KEYS[12],id..'|'..generation..'|user-search-closure',archive)
redis.call('HSET',KEYS[8],id,encoded);redis.call('HSET',KEYS[2],id,'completed_with_skips')
redis.call('ZREM',KEYS[6],id);redis.call('ZREM',KEYS[10],id);redis.call('HDEL',KEYS[9],id)
return cjson.encode({status='completed_with_skips',changed=true,acceptedByVolume=false,attempts=attempts})
`;

export async function closeUserApprovedSearch(queue,snapshot,decision,options={}){
 validateUserSearchClosure(snapshot,decision,options);
 if(options.commit!==true)return {status:'preview',changed:false,acceptedByVolume:false};
 return JSON.parse(await queue.client.eval(closeScript,{keys:closureKeys(queue),arguments:[decision.taskId,
  options.approval.generation,JSON.stringify({...decision,checkedAtMs:Date.parse(decision.checkedAt)}),
  JSON.stringify(options.approval),JSON.stringify(options.summary),JSON.stringify(options.expected)]}));
}
