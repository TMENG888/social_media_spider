import {isDeepStrictEqual} from 'node:util';
import {assessAnnualLowVolume,ANNUAL_COMPLETION_POLICY} from './keyword-annual-acceptance.mjs';
import {volumeDecision,validateVolumeSnapshot} from './volume-acceptance.mjs';

// An immutable, task/generation/snapshot-bound annual exception. It must never
// be mistaken for P80 quantity success by a later prepare/confirmation.
export const ANNUAL_COMPLETION_GUARD=`
local function annual_search_closed(id,generation,snapshot_id,status)
 if status~='completed' then return false end
 local raw=redis.call('HGET',KEYS[8],id)
 local ledger=redis.call('HGET',KEYS[12],id..'|'..generation..'|annual-search-completion')
 if not raw or not ledger then return false end
 local aok,a=pcall(cjson.decode,ledger);local rok,r=pcall(cjson.decode,raw)
 if not aok or not rok or type(a)~='table' or type(r)~='table' or type(r.annualAcceptance)~='table' then return false end
 local e=r.annualAcceptance
 return a.completedResult==raw and a.generation==generation and e.taskId==id
  and e.snapshotId==snapshot_id and e.policy=='${ANNUAL_COMPLETION_POLICY}'
  and r.acceptedBy=='verified_low_year_search' and r.accepted==true
  and r.quantityAccepted==false and r.businessCompleted==true
end
`;

const SCRIPT=ANNUAL_COMPLETION_GUARD+`
local id,generation,snapshot_id,token=ARGV[1],ARGV[2],ARGV[3],ARGV[4]
-- Type-probe every key before the first mutation; Redis Lua has no rollback.
for i,key in ipairs(KEYS) do
 if i==6 or i==7 or i==10 then redis.call('ZSCORE',key,'__annual_probe__')
 else redis.call('HGET',key,'__annual_probe__') end
end
local e,d,record=cjson.decode(ARGV[5]),cjson.decode(ARGV[6]),cjson.decode(ARGV[7])
local time=redis.call('TIME');local now=tonumber(time[1])*1000+math.floor(tonumber(time[2])/1000)
if e.policy~='${ANNUAL_COMPLETION_POLICY}' or e.ok~=true or e.taskId~=id or e.snapshotId~=snapshot_id
 or e.keyword~=d.keyword or e.projectName~=d.projectName or e.posts~=d.posts or e.threshold~=d.threshold
 or d.dbReadbackVerified~=true or e.quantityAccepted~=false or e.subtitleQualityRequired~=false
 or e.retryUnit~='original_keyword' or type(e.checkedAtMs)~='number'
 or now-e.checkedAtMs>60000 or e.checkedAtMs>now+1000 then return redis.error_reply('ANNUAL_EVIDENCE_INVALID') end
local status=redis.call('HGET',KEYS[2],id)
if annual_search_closed(id,generation,snapshot_id,status) then
 return cjson.encode({status='completed',changed=false,acceptedByAnnual=true,acceptedByVolume=false})
end
local payload=redis.call('HGET',KEYS[1],id);local task=cjson.decode(payload or '{}')
if not payload or task.keyword~=d.keyword or task.projectName~=d.projectName then return redis.error_reply('ANNUAL_TASK_IDENTITY_MISMATCH') end
local lease=tonumber(redis.call('ZSCORE',KEYS[7],id))
if token=='' or status~='leased' or redis.call('HGET',KEYS[4],id)~=token or not lease or lease<=now then
 return redis.error_reply('ANNUAL_LEASE_LOST') end
local attempts=tonumber(redis.call('HGET',KEYS[3],id))
if not attempts or attempts<1 then return redis.error_reply('ANNUAL_HISTORY_MISSING') end
local field=id..'|'..generation..'|annual-search-completion'
if redis.call('HGET',KEYS[12],field) then return redis.error_reply('ANNUAL_LEDGER_CONFLICT') end
local before={}
for i,key in ipairs(KEYS) do
 if i==6 or i==7 or i==10 then before[i]=redis.call('ZSCORE',key,id) or false
 else before[i]=redis.call('HGET',key,id) or false end
end
local result=cjson.encode({status='completed',accepted=true,businessCompleted=true,quantityAccepted=false,
 acceptedBy='verified_low_year_search',qualityVerified=false,annualAcceptance=e,volumeAcceptance=d,
 missingCandidateIds=e.missingCandidateIds,allItemsCollected=e.allItemsCollected,
 previousEvidenceRetained=true,collectorRecord=record,completedAt=now})
local archive=cjson.encode({generation=generation,before=before,completedResult=result,at=now})
redis.call('HSET',KEYS[12],field,archive)
redis.call('HSET',KEYS[8],id,result);redis.call('HSET',KEYS[2],id,'completed')
redis.call('ZREM',KEYS[6],id);redis.call('ZREM',KEYS[7],id);redis.call('ZREM',KEYS[10],id)
redis.call('HDEL',KEYS[4],id);redis.call('HDEL',KEYS[5],id);redis.call('HDEL',KEYS[9],id)
return cjson.encode({status='completed',changed=true,acceptedByAnnual=true,acceptedByVolume=false,attempts=attempts})
`;

export async function completeAnnualKeyword(queue,snapshot,decision,input,{generation,token,commit=false,record={}}={}){
 validateVolumeSnapshot(snapshot);
 if(!/^[A-Za-z0-9_-]{1,100}$/.test(generation||''))throw new Error('ANNUAL_GENERATION_REQUIRED');
 if(!isDeepStrictEqual(decision,volumeDecision(snapshot,{taskId:decision.taskId,posts:decision.posts,
  readbackVerified:decision.dbReadbackVerified,checkedAt:decision.checkedAt})))throw new Error('ANNUAL_DECISION_INVALID');
 const evidence=assessAnnualLowVolume(decision,input);
 if(!evidence.ok)return {evidence,confirmation:null};
 if(!commit)return {evidence,confirmation:{status:'preview',changed:false}};
 if(typeof token!=='string'||!token)throw new Error('ANNUAL_LEASE_REQUIRED');
 const keys=[...queue.keys,queue.namespace+':volume-policy-history',queue.namespace+':volume-attempt-baseline'];
 const confirmation=JSON.parse(await queue.client.eval(SCRIPT,{keys,arguments:[decision.taskId,generation,
  snapshot.snapshotId,token,JSON.stringify(evidence),JSON.stringify(decision),JSON.stringify(record)]}));
 return {evidence,confirmation};
}
