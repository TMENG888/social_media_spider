import {createHash} from 'node:crypto';
import {isDeepStrictEqual} from 'node:util';
import {collectorAnnualScan} from './annual-scan-adapter.mjs';
import {volumeDecision,validateVolumeSnapshot} from './volume-acceptance.mjs';

// User-approved business closure, including zero SQL rows. Never a claim of
// quantity/quality success or proof that unresolved content has been deleted.
export const SEARCH_EXHAUSTION_POLICY='20261019-douyin-verified-search-business-completion-v1';
const contentErrors=new Set(['VOLUME_BELOW_THRESHOLD','KNOWN_CANDIDATES_INCOMPLETE']);
const digest=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const reject=reason=>({ok:false,policy:SEARCH_EXHAUSTION_POLICY,reason});

export function assessSearchExhaustion(decision,task,record,{now=Date.now()}={}){
 if(decision?.platform!=='抖音'||decision.dbReadbackVerified!==true||decision.ok!==false
  ||decision.reason!=='VOLUME_BELOW_THRESHOLD'||!Number.isSafeInteger(decision.posts)||decision.posts<0
  ||!Number.isSafeInteger(decision.threshold)||decision.threshold<1||decision.posts>=decision.threshold)
  return reject('SEARCH_CLOSURE_SQL_INVALID');
 const checkedAtMs=Date.parse(decision.checkedAt);
 if(!Number.isFinite(checkedAtMs)||now-checkedAtMs>60000||checkedAtMs>now+1000)return reject('SEARCH_CLOSURE_SQL_STALE');
 if(!task||(task.redisTaskId||task.id)!==decision.taskId||task.keyword!==decision.keyword
  ||task.projectName!==decision.projectName||record?.taskId!==decision.taskId
  ||record.keyword!==decision.keyword||record.projectName!==decision.projectName)
  return reject('SEARCH_CLOSURE_IDENTITY_MISMATCH');
 if(!['completed','completed_with_skips','incomplete'].includes(record.status)||record.stopped||record.mustStopNode
  ||record.importOk!==true||record.importError||record.importExitCode!=null&&record.importExitCode!==0
  ||record.asr?.runtimeUnavailable||record.asrError
  ||[record.error,record.previousCollectionError,record.collectionError].some(e=>e!=null&&e!==''&&!contentErrors.has(e)))
  return reject('SEARCH_CLOSURE_OPERATIONAL_FAILURE');
 const year=Number(String(task.cutoff||task.minPublishedDate||'2026-01-01').slice(0,4));
 const scan=collectorAnnualScan(record,{taskId:decision.taskId,keyword:decision.keyword,projectName:decision.projectName,year});
 const started=Date.parse(scan.startedAt),finished=Date.parse(scan.finishedAt);
 if(!scan.ok||!Number.isFinite(started)||!Number.isFinite(finished)||finished<started
  ||finished>now+1000||now-finished>1800000)return reject('SEARCH_CLOSURE_END_UNVERIFIED');
 const validIds=ids=>Array.isArray(ids)&&ids.every(id=>typeof id==='string'&&id.trim())&&new Set(ids).size===ids.length;
 if(!validIds(record.knownIncomplete)||!validIds(record.searchExhaustion.gaps))return reject('SEARCH_CLOSURE_GAPS_INVALID');
 const missingCandidateIds=[...new Set([...record.knownIncomplete,...record.searchExhaustion.gaps])].sort();
 const body={policy:SEARCH_EXHAUSTION_POLICY,taskId:decision.taskId,snapshotId:decision.snapshotId,
  keyword:decision.keyword,projectName:decision.projectName,platform:decision.platform,posts:decision.posts,
  threshold:decision.threshold,checkedAtMs,searchEvidence:scan,missingCandidateIds,
  allItemsCollected:missingCandidateIds.length===0,quantityAccepted:false,qualityVerified:false,
  acceptanceMeaning:'business_completion_after_verified_search_exhaustion_not_full_collection',deletedConfirmed:false};
 return {ok:true,...body,evidenceDigest:digest(body)};
}

export const SEARCH_EXHAUSTION_GUARD=`
local function exhausted_search_closed(id,generation,snapshot_id,status)
 if status~='completed' then return false end
 local raw=redis.call('HGET',KEYS[8],id)
 local ledger=redis.call('HGET',KEYS[12],id..'|'..generation..'|verified-search-completion')
 if not raw or not ledger then return false end
 local aok,a=pcall(cjson.decode,ledger);local rok,r=pcall(cjson.decode,raw)
 if not aok or not rok or type(a)~='table' or type(r)~='table' or type(r.searchExhaustionAcceptance)~='table' then return false end
 local e=r.searchExhaustionAcceptance
 return a.completedResult==raw and a.generation==generation and e.taskId==id
  and e.snapshotId==snapshot_id and e.policy=='${SEARCH_EXHAUSTION_POLICY}'
  and r.acceptedBy=='verified_search_exhaustion' and r.accepted==true
  and r.quantityAccepted==false and r.businessCompleted==true
end
`;

const SCRIPT=SEARCH_EXHAUSTION_GUARD+`
local id,generation,snapshot_id,token=ARGV[1],ARGV[2],ARGV[3],ARGV[4]
-- Redis Lua does not roll back: finish all type probes, validation and encoding
-- before the first mutation. Only the live original lease can close this task.
for i,key in ipairs(KEYS) do
 if i==6 or i==7 or i==10 then redis.call('ZSCORE',key,'__search_closure_probe__')
 else redis.call('HGET',key,'__search_closure_probe__') end
end
local e,d,record=cjson.decode(ARGV[5]),cjson.decode(ARGV[6]),cjson.decode(ARGV[7])
local time=redis.call('TIME');local now=tonumber(time[1])*1000+math.floor(tonumber(time[2])/1000)
if e.policy~='${SEARCH_EXHAUSTION_POLICY}' or e.ok~=true or e.taskId~=id or e.snapshotId~=snapshot_id
 or e.keyword~=d.keyword or e.projectName~=d.projectName or e.posts~=d.posts or e.threshold~=d.threshold
 or d.dbReadbackVerified~=true or d.posts>=d.threshold or e.quantityAccepted~=false
 or type(e.checkedAtMs)~='number' or now-e.checkedAtMs>60000 or e.checkedAtMs>now+1000 then
 return redis.error_reply('SEARCH_CLOSURE_EVIDENCE_INVALID') end
local status=redis.call('HGET',KEYS[2],id)
if exhausted_search_closed(id,generation,snapshot_id,status) then
 return cjson.encode({status='completed',changed=false,acceptedBySearchExhaustion=true,acceptedByVolume=false}) end
local payload=redis.call('HGET',KEYS[1],id);local task=cjson.decode(payload or '{}')
if not payload or task.keyword~=d.keyword or task.projectName~=d.projectName then return redis.error_reply('SEARCH_CLOSURE_TASK_MISMATCH') end
local lease=tonumber(redis.call('ZSCORE',KEYS[7],id))
if token=='' or status~='leased' or redis.call('HGET',KEYS[4],id)~=token or not lease or lease<=now then
 return redis.error_reply('SEARCH_CLOSURE_LEASE_LOST') end
local attempts=tonumber(redis.call('HGET',KEYS[3],id))
if not attempts or attempts<1 or attempts~=math.floor(attempts) then return redis.error_reply('SEARCH_CLOSURE_HISTORY_MISSING') end
local field=id..'|'..generation..'|verified-search-completion'
if redis.call('HGET',KEYS[12],field) then return redis.error_reply('SEARCH_CLOSURE_LEDGER_CONFLICT') end
local before={}
for i,key in ipairs(KEYS) do
 if i==6 or i==7 or i==10 then before[i]=redis.call('ZSCORE',key,id) or false
 else before[i]=redis.call('HGET',key,id) or false end
end
local result=cjson.encode({status='completed',accepted=true,businessCompleted=true,quantityAccepted=false,
 acceptedBy='verified_search_exhaustion',qualityVerified=false,searchExhaustionAcceptance=e,volumeAcceptance=d,
 missingCandidateIds=e.missingCandidateIds,allItemsCollected=e.allItemsCollected,deletedConfirmed=false,
 previousEvidenceRetained=true,collectorRecord=record,completedAt=now,attempts=attempts})
local archive=cjson.encode({generation=generation,before=before,completedResult=result,at=now,
 previousPolicyHistory=redis.call('HGET',KEYS[12],id..'|'..generation) or false})
redis.call('HSET',KEYS[12],field,archive)
redis.call('HSET',KEYS[8],id,result);redis.call('HSET',KEYS[2],id,'completed')
redis.call('ZREM',KEYS[6],id);redis.call('ZREM',KEYS[7],id);redis.call('ZREM',KEYS[10],id)
redis.call('HDEL',KEYS[4],id);redis.call('HDEL',KEYS[5],id);redis.call('HDEL',KEYS[9],id)
return cjson.encode({status='completed',changed=true,acceptedBySearchExhaustion=true,acceptedByVolume=false,attempts=attempts})
`;

export async function completeExhaustedSearch(queue,snapshot,decision,task,record,{generation,token,commit=false,now}={}){
 validateVolumeSnapshot(snapshot);
 if(!/^[A-Za-z0-9_-]{1,100}$/.test(generation||''))throw new Error('SEARCH_CLOSURE_GENERATION_REQUIRED');
 if(!isDeepStrictEqual(decision,volumeDecision(snapshot,{taskId:decision.taskId,posts:decision.posts,
  readbackVerified:decision.dbReadbackVerified,checkedAt:decision.checkedAt})))throw new Error('SEARCH_CLOSURE_DECISION_INVALID');
 const evidence=assessSearchExhaustion(decision,task,record,{now});
 if(!evidence.ok)return {evidence,confirmation:null};
 if(!commit)return {evidence,confirmation:{status:'preview',changed:false}};
 if(typeof token!=='string'||!token)throw new Error('SEARCH_CLOSURE_LEASE_REQUIRED');
 const keys=[...queue.keys,queue.namespace+':volume-policy-history',queue.namespace+':volume-attempt-baseline'];
 const confirmation=JSON.parse(await queue.client.eval(SCRIPT,{keys,arguments:[decision.taskId,generation,
  snapshot.snapshotId,token,JSON.stringify(evidence),JSON.stringify(decision),JSON.stringify(record)]}));
 return {evidence,confirmation};
}
