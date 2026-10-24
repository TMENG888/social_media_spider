// Retry transient transport/lock failures only. Never log driver messages,
// SQL, URLs, credentials or parameters. The caller owns transaction safety.
const transient=new Set(['ENOTFOUND','EAI_AGAIN','ETIMEDOUT','ECONNRESET','ECONNREFUSED',
 'EHOSTUNREACH','ENETUNREACH','EPIPE','PROTOCOL_CONNECTION_LOST','PROTOCOL_SEQUENCE_TIMEOUT',
 'ER_LOCK_WAIT_TIMEOUT','ER_LOCK_DEADLOCK','MYSQL_IMPORT_LOCK_TIMEOUT','ER_CON_COUNT_ERROR']);
export const safeInfrastructureCode=error=>{
 const value=String(error?.code||error?.errorCode||'INFRASTRUCTURE_OPERATION_FAILED');
 return /^[A-Z][A-Z0-9_]{1,79}$/.test(value)?value:'INFRASTRUCTURE_OPERATION_FAILED';
};
export const transientInfrastructureError=error=>transient.has(safeInfrastructureCode(error));
export async function retryInfrastructure(run,{operation='database',delaysMs=[5000,10000],
 pause=ms=>new Promise(resolve=>setTimeout(resolve,ms)),
 log=entry=>console.error(JSON.stringify(entry))}={}){
 if(!Array.isArray(delaysMs)||delaysMs.length>4||delaysMs.some(ms=>!Number.isFinite(ms)||ms<0||ms>60000))throw new Error('INFRASTRUCTURE_RETRY_POLICY_INVALID');
 for(let attempt=1;;attempt++){
  try{const result=await run(attempt);
   if(attempt>1)log({event:'infrastructure_retry_recovered',operation,attempt});
   return result;
  }catch(error){
   const errorCode=safeInfrastructureCode(error),retryable=error?.retrySafe!==false&&transientInfrastructureError(error);
   if(!retryable||attempt>delaysMs.length){
    log({event:retryable?'infrastructure_circuit_open':'infrastructure_failure_not_retried',operation,errorCode,
     attempt,maxAttempts:delaysMs.length+1,localDataRetained:true,taskConfirmed:false});
    throw error;
   }
   log({event:'infrastructure_retry_wait',operation,errorCode,attempt,nextAttempt:attempt+1,
    maxAttempts:delaysMs.length+1,waitSeconds:delaysMs[attempt-1]/1000});
   await pause(delaysMs[attempt-1]);
  }
 }
}
