import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {verifyCheckpointCoverage} from './coverage-gate.mjs';
import {COVERAGE_REDIS_GUARD} from './coverage-redis-guard.mjs';
import {SearchExhaustion,assessSearchAcceptance} from './search-acceptance.mjs';
import {ACCEPTANCE_VERSION} from './collection-policy.mjs';
import {assessAsrAcceptance} from './acceptance-gate.mjs';
import {asrJobStats} from './checkpoint.mjs';
import {CORRECTION_POLICY} from './correction-lease.mjs';

export const TERMINAL_RECHECK_POLICY='20261015-terminal-scope-recheck-v1';
const digest=value=>createHash('sha256').update(typeof value==='string'?value:JSON.stringify(value)).digest('hex');
const beijingTime=value=>Date.parse(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(value||'')?value.replace(' ','T')+'+08:00':value);
const samePath=(a,b)=>typeof a==='string'&&typeof b==='string'&&path.resolve(a).toLowerCase()===path.resolve(b).toLowerCase();
const READ=`
local expected={'hash','hash','hash','hash','hash','zset','zset','hash','hash','zset','hash','hash','hash'}
for i,want in ipairs(expected) do
 if want=='hash' then redis.call('HGET',KEYS[i],'__terminal_recheck_probe__')
 else redis.call('ZSCORE',KEYS[i],'__terminal_recheck_probe__') end
end
local function read_state(id,field)
 return {taskId=id,status=redis.call('HGET',KEYS[2],id) or cjson.null,
  payload=redis.call('HGET',KEYS[1],id) or cjson.null,attempts=redis.call('HGET',KEYS[3],id) or cjson.null,
  result=redis.call('HGET',KEYS[8],id) or cjson.null,error=redis.call('HGET',KEYS[9],id) or cjson.null,
  deferrals=redis.call('HGET',KEYS[11],id) or cjson.null,pending=redis.call('ZSCORE',KEYS[6],id) or cjson.null,
  lease=redis.call('ZSCORE',KEYS[7],id) or cjson.null,token=redis.call('HGET',KEYS[4],id) or cjson.null,
  owner=redis.call('HGET',KEYS[5],id) or cjson.null,failed=redis.call('ZSCORE',KEYS[10],id) or cjson.null,
  correction=redis.call('HGET',KEYS[13],id..'|'..ARGV[2]) or cjson.null,
  recheck=redis.call('HGET',KEYS[12],field) or cjson.null}
end
local id=ARGV[1];local field=id..'|${TERMINAL_RECHECK_POLICY}'
local current=read_state(id,field)
`;
const COMMIT=READ+`
local before=cjson.decode(ARGV[3])
for key,value in pairs(current) do
 if before[key]~=value then return redis.error_reply('TERMINAL_RECHECK_CONCURRENT_CHANGE') end
end
if current.status~='failed' and current.status~='skipped_unresolved' and current.status~='completed' and current.status~='completed_with_skips' then
 return redis.error_reply('TERMINAL_RECHECK_REQUIRES_TERMINAL_TASK')
end
if current.lease~=cjson.null or current.token~=cjson.null or current.owner~=cjson.null or current.pending~=cjson.null then
 return redis.error_reply('TERMINAL_RECHECK_ACTIVE_OR_QUEUED')
end
if current.recheck~=cjson.null then return redis.error_reply('TERMINAL_RECHECK_ALREADY_COMMITTED') end
if current.correction==cjson.null then return redis.error_reply('TERMINAL_RECHECK_CORRECTION_MISSING') end
local correction=cjson.decode(current.correction)
if correction.policy~=ARGV[2] or correction.taskId~=id or correction.originalPayload~=current.payload
 or correction.correctionAttempt~=tonumber(current.attempts) then return redis.error_reply('TERMINAL_RECHECK_HISTORY_MISMATCH') end
local result=cjson.decode(ARGV[4])
${COVERAGE_REDIS_GUARD}
local t=redis.call('TIME');local now=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
local proof=result.acceptanceRecheck
if type(proof)~='table' or proof.policy~='${TERMINAL_RECHECK_POLICY}'
 or type(proof.checkedAtMs)~='number' or proof.checkedAtMs>now+1000 or now-proof.checkedAtMs>60000
 or type(proof.checkpointDigest)~='string' or #proof.checkpointDigest~=64
 or type(proof.sourceDigest)~='string' or #proof.sourceDigest~=64 then return redis.error_reply('TERMINAL_RECHECK_STALE_OR_MISSING_EVIDENCE') end
local status=(c.denominator-c.numerator)>0 and 'completed_with_skips' or 'completed'
result.status=status;result.accepted=true;result.redisConfirmed=true;result.redisDisposition=status
result.redisFailedHandled=false;result.redisReleased=false
local ledger=cjson.encode({policy=proof.policy,taskId=id,committedAt=now,originalState=current,
 originalLocalRecord=ARGV[5],checkpointDigest=proof.checkpointDigest,sourceDigest=proof.sourceDigest,
 coverage=result.coverage})
local encoded=cjson.encode(result)
-- Everything, including key types and JSON encodings, is checked before writes.
-- This changes neither attempts, deferrals, payloads, nor correction history.
redis.call('HSET',KEYS[12],field,ledger)
redis.call('HSET',KEYS[8],id,encoded);redis.call('HSET',KEYS[2],id,status)
redis.call('HDEL',KEYS[9],id);redis.call('ZREM',KEYS[10],id)
return cjson.encode({taskId=id,status=status,committedAt=now,acceptanceOnly=true,attempts=tonumber(current.attempts)})
`;

function checkpointState(checkpointDb){
 const db=new DatabaseSync(checkpointDb,{readOnly:true}),hash=createHash('sha256');
 try{
  db.exec('BEGIN');
  const tables=db.prepare("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").all();
  for(const table of tables){
   // Names are read from the schema, never pasted from an external argument.
   const quoted='"'+table.name.replaceAll('"','""')+'"';
   hash.update(JSON.stringify(table));
   for(const row of db.prepare(`SELECT * FROM ${quoted} ORDER BY rowid`).all())hash.update(JSON.stringify(row));
  }
  const stats=asrJobStats(db);
  db.exec('COMMIT');return {digest:hash.digest('hex'),stats};
 }finally{db.close();}
}

function terminalStateReason(snapshot){
 if(!['failed','skipped_unresolved','completed','completed_with_skips'].includes(snapshot.status))return 'TERMINAL_RECHECK_REQUIRES_TERMINAL_TASK';
 if(['lease','token','owner','pending'].some(k=>snapshot[k]!=null))return 'TERMINAL_RECHECK_ACTIVE_OR_QUEUED';
 if(snapshot.recheck!=null)return 'TERMINAL_RECHECK_ALREADY_COMMITTED';
 return null;
}

export function terminalEvidenceReason({snapshot,task,record,collector,checkpointDb,now=Date.now()}){
 const stateReason=terminalStateReason(snapshot);if(stateReason)return stateReason;
 let stored,correction;try{stored=JSON.parse(snapshot.payload);correction=JSON.parse(snapshot.correction);}catch{return 'TERMINAL_RECHECK_HISTORY_MISSING';}
 if(!correction||correction.policy!==CORRECTION_POLICY||correction.taskId!==task.redisTaskId||snapshot.taskId!==task.redisTaskId
  ||correction.originalPayload!==snapshot.payload||correction.correctionAttempt!==Number(snapshot.attempts)
  ||stored.redisTaskId!==task.redisTaskId||stored.keyword!==task.keyword||stored.topic!==task.topic)return 'TERMINAL_RECHECK_HISTORY_MISMATCH';
 if(record?.keyword!==task.keyword||record.topic!==task.topic||record.taskId!==task.id
  ||!samePath(record.checkpointDb,checkpointDb)||!samePath(collector?.checkpointDb,checkpointDb)
  ||!samePath(path.dirname(checkpointDb),record.stateDir)||!record.workerId||!correction.owner?.startsWith(record.workerId+'-')
  ||!record.runId||record.runId!==collector.runId)return 'TERMINAL_RECHECK_SOURCE_MISMATCH';
 const runStarted=Number(record.runId.split('-')[0]),finished=beijingTime(record.finishedAt),collected=beijingTime(collector.finishedAt);
 if(!Number.isFinite(runStarted)||runStarted<correction.claimedAt||!Number.isFinite(finished)||!Number.isFinite(collected)
  ||collected+1000<runStarted||finished+1000<collected||finished>now+1000)return 'TERMINAL_RECHECK_STALE_RUN';
 if(record.exitCode!==0||record.importExitCode!==0||!['completed','completed_with_skips','incomplete'].includes(record.status)
  ||!['completed','completed_with_skips'].includes(collector.status)||collector.error
  ||(record.error&&!['USABLE_DB_COVERAGE_BELOW_80','SEARCH_END_UNVERIFIED'].includes(record.error))
  ||collector.scopeAcceptance?.acceptanceVersion!==ACCEPTANCE_VERSION||collector.scopeAcceptance?.ok!==true)return 'TERMINAL_RECHECK_RUN_NOT_HEALTHY';
 if(!assessAsrAcceptance(collector.asrJobs,{required:task.collectorConfig?.asrEnabled!==false||Boolean(collector.asrJobs),allowExhaustedSkip:true}).ok)return 'TERMINAL_RECHECK_ASR_UNFINISHED';
 if(!assessSearchAcceptance(collector.searchSummaries,{annual:true}).ok)return 'SEARCH_END_UNVERIFIED';
 for(const summary of collector.searchSummaries){
  if(summary.keyword!==task.keyword||summary.exhaustion?.policy!=='20261014-verified-search-end-v1'||!Array.isArray(summary.exhaustion.observations))return 'SEARCH_END_UNVERIFIED';
  const endpoint=new SearchExhaustion({stableRounds:task.collectorConfig?.maxStagnantRounds??15});let verified;
  for(const observation of summary.exhaustion.observations)verified=endpoint.observe(observation);
  if(verified?.ok!==true)return 'SEARCH_END_UNVERIFIED';
 }
 return null;
}

// Explicit one-task scope recheck, not another collection attempt. Preview is
// the default. Caller supplies an exact existing manifest task and its paths.
export async function recheckTerminalAcceptance({queue,task,checkpointDb,outputDir,commit=false,connect}){
 await queue.verifyExisting(task);
 const keys=[...queue.keys,queue.namespace+':acceptance-recheck-history',queue.namespace+':correction-history'];
 const args=[task.redisTaskId,CORRECTION_POLICY];
 const snapshot=JSON.parse(await queue.client.eval(READ+'return cjson.encode(current)',{keys,arguments:args}));
 const stateReason=terminalStateReason(snapshot);if(stateReason)return {ok:false,committed:false,reason:stateReason};
 const recordFile=path.join(outputDir,'task_status.json'),collectorFile=path.join(outputDir,'collector_status.json');
 const [recordText,collectorText]=await Promise.all([fs.readFile(recordFile,'utf8'),fs.readFile(collectorFile,'utf8')]);
 const record=JSON.parse(recordText),collector=JSON.parse(collectorText);
 const reason=terminalEvidenceReason({snapshot,task,record,collector,checkpointDb});
 if(reason)return {ok:false,committed:false,reason};
 if(!samePath(record.outputDir,outputDir))return {ok:false,committed:false,reason:'TERMINAL_RECHECK_SOURCE_MISMATCH'};
 const before=checkpointState(checkpointDb);
 if(!assessAsrAcceptance(before.stats,{required:true,allowExhaustedSkip:true}).ok)return {ok:false,committed:false,reason:'TERMINAL_RECHECK_ASR_UNFINISHED'};
 const cutoff=task.cutoff||'2026-01-01';
 const coverage=await verifyCheckpointCoverage({checkpointDb,keyword:task.keyword,scanComplete:true,year:Number(cutoff.slice(0,4)),cutoff,strictMedia:true,connect});
 const after=checkpointState(checkpointDb);
 const [newRecord,newCollector]=await Promise.all([fs.readFile(recordFile,'utf8'),fs.readFile(collectorFile,'utf8')]);
 if(before.digest!==after.digest||newRecord!==recordText||newCollector!==collectorText)return {ok:false,committed:false,reason:'TERMINAL_RECHECK_LOCAL_EVIDENCE_CHANGED'};
 if(!coverage.ok||!commit)return {ok:coverage.ok,committed:false,previewOnly:!commit,coverage,checkpointDigest:after.digest};
 const result={...record,error:null,accepted:true,coverage,acceptanceRecheck:{policy:TERMINAL_RECHECK_POLICY,checkedAtMs:Date.now(),
  checkpointDigest:after.digest,sourceDigest:digest([recordText,collectorText])}};
 const confirmation=JSON.parse(await queue.client.eval(COMMIT,{keys,arguments:[...args,JSON.stringify(snapshot),JSON.stringify(result),recordText]}));
 return {ok:true,committed:true,confirmation,coverage,checkpointDigest:after.digest};
}
