// Freshness of SQL evidence uses Redis TIME at query start and at acceptance.
// Never re-stamp an old SQL count, and never fall back to a worker's clock.
export const REDIS_EVIDENCE_CLOCK_VERSION='redis-sql-evidence-clock-20261105-v1';
export const SQL_EVIDENCE_MAX_AGE_MS=60000;
const TIME_SCRIPT="local t=redis.call('TIME');return tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)";
export async function readRedisTimeMs(client){
 if(!client?.eval)throw new Error('VOLUME_REDIS_TIME_REQUIRED');
 const value=await client.eval(TIME_SCRIPT,{keys:[],arguments:[]});
 const ms=Number(value);
 if(!Number.isSafeInteger(ms)||ms<=0)throw new Error('VOLUME_REDIS_TIME_INVALID');
 return ms;
}
export function assertFreshSqlTime(checkedAtMs,serverNowMs){
 if(!Number.isSafeInteger(checkedAtMs)||!Number.isSafeInteger(serverNowMs))throw new Error('VOLUME_EVIDENCE_TIME_INVALID');
 const ageMs=serverNowMs-checkedAtMs;
 if(ageMs>SQL_EVIDENCE_MAX_AGE_MS||ageMs < -1000){
  const code=ageMs<0?'VOLUME_EVIDENCE_TIME_FUTURE':'VOLUME_EVIDENCE_EXPIRED';
  throw Object.assign(new Error(code),{code,checkedAtMs,serverNowMs,ageMs});
 }
}
export function evidenceTimeGuardLua(prefix,expression){
 if(!/^[A-Z_]+$/.test(prefix)||!/^\w+\.checkedAtMs$/.test(expression))throw new Error('EVIDENCE_GUARD_SCOPE_INVALID');
 return `
if type(${expression})~='number' or ${expression}~=math.floor(${expression}) then return redis.error_reply('${prefix}_EVIDENCE_TIME_INVALID') end
if now-${expression}>60000 then return redis.error_reply('${prefix}_EVIDENCE_EXPIRED ageMs='..tostring(now-${expression})..' checkedAtMs='..tostring(${expression})..' serverNowMs='..tostring(now)) end
-- Both stamps come from Redis. This checks a server-clock rollback, not worker skew.
if ${expression}>now+1000 then return redis.error_reply('${prefix}_EVIDENCE_TIME_FUTURE ageMs='..tostring(now-${expression})..' checkedAtMs='..tostring(${expression})..' serverNowMs='..tostring(now)) end
`;
}
export function evidenceFreshnessCode(error){
 return String(error?.code||error?.message||'').match(/\b(?:VOLUME|ANNUAL|SEARCH_CLOSURE)_EVIDENCE_(?:EXPIRED|TIME_FUTURE)\b/)?.[0]||null;
}
export async function retryFreshSqlEvidence(operation,{attempts=3,sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms)),onDiagnostic=()=>{}}={}){
 if(!Number.isInteger(attempts)||attempts<1||attempts>3)throw new Error('EVIDENCE_RETRY_LIMIT_INVALID');
 for(let attempt=1;attempt<=attempts;attempt++){
  try{return await operation();}
  catch(error){
   const reason=evidenceFreshnessCode(error);if(!reason)throw error;
   const details={};
   for(const key of ['checkedAtMs','serverNowMs','ageMs']){
    const raw=Number.isFinite(error[key])?error[key]:String(error.message||'').match(new RegExp('\\b'+key+'=(-?\\d+)'))?.[1];
    if(raw!==undefined&&Number.isFinite(Number(raw)))details[key]=Number(raw);
   }
   const diagnostic={version:REDIS_EVIDENCE_CLOCK_VERSION,reason,attempt,maxAttempts:attempts,
    result:attempt===attempts?'recheck_exhausted':'requery_required',...details};
   await onDiagnostic(diagnostic);
   if(attempt===attempts){error.evidenceRecheckAttempts=attempt;throw error;}
   // The callback must query SQL again; reusing/re-dating a prior decision is forbidden.
   await sleep(attempt*1000);
  }
 }
}
