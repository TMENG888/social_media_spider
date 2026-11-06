import {configureTiming,timed,timedSync,contentTiming,timingDisposition,timingMarker,timingProgress,timingFailure,timingStop} from './keyword-timing.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';

export const CONTROL_RETRY_VERSION='control-backoff-20261105-v2';
export const CONTROL_RETRY_DELAYS_MS=Object.freeze([5000,10000,20000]);
export const CONTROL_RETRY_TIMEOUT_MS=90000;
export function transientControlError(error){
  if(['ECONNRESET','ECONNREFUSED','EPIPE','ETIMEDOUT','ENETUNREACH','EHOSTUNREACH','REDIS_TIMEOUT'].includes(error?.code))return true;
  if(['ClientClosedError','SocketClosedUnexpectedlyError','ConnectionTimeoutError','DisconnectsClientError','ClientOfflineError'].includes(error?.constructor?.name))return true;
  return ['The client is closed','Socket closed unexpectedly','CONTROL_TIMEOUT','CONTROL_CONNECT_TIMEOUT'].includes(error?.message);
}
const close=client=>{try{if(client?.isOpen)client.destroy();}catch{}};
function errorFields(error){
  return {errorClass:/^[A-Za-z]{1,64}$/.test(error?.constructor?.name||'')?error.constructor.name:'Error',
    errorCode:/^[A-Z_0-9]{1,64}$/.test(error?.code||'')?error.code:null};
}
async function record(owner,event){
  if(!owner.ctx?.workerRoot)return;
  try{await fs.appendFile(path.join(owner.ctx.workerRoot,'.state','control-read-diagnostics.jsonl'),
    JSON.stringify({at:new Date().toISOString(),version:CONTROL_RETRY_VERSION,...event})+'\n');}catch{}
}

// Only idempotent reads are retried. No stop flags, ACKs, task writes or
// assumed success. A null client covers the initial authenticated connection.
export async function readControlWithReconnect(...args){return timed('control_channel_read',()=>readControlWithReconnectDetailedImpl(...args),{});}
async function readControlWithReconnectDetailedImpl(owner,read,connect,options={}){
  const {retryDelaysMs=CONTROL_RETRY_DELAYS_MS,timeoutMs=CONTROL_RETRY_TIMEOUT_MS,
    sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms)),now=Date.now,onDiagnostic=event=>record(owner,event)}=options;
  if(!Array.isArray(retryDelaysMs)||retryDelaysMs.length>3||retryDelaysMs.some(ms=>!Number.isFinite(ms)||ms<0||ms>30000)
    ||!Number.isFinite(timeoutMs)||timeoutMs<=0||timeoutMs>90000)throw new Error('CONTROL_RETRY_BUDGET_INVALID');
  const started=now(),until=started+timeoutMs;let expired=false,timer,pendingClient=null;
  const timeout=()=>Object.assign(new Error('CONTROL_TIMEOUT'),{code:'ETIMEDOUT'});
  const check=()=>{
    if(expired||now()>=until)throw timeout();
    if(owner.closed)throw new Error('CONTROL_CLOSED_DURING_RECONNECT');
  };
  const emit=async(stage,error=null,details={})=>{
    try{await onDiagnostic({stage,elapsedMs:Math.max(0,now()-started),...details,...(error?errorFields(error):{})});}catch{}
  };
  const wait=async ms=>{
    const end=now()+ms;
    while(now()<end){check();await sleep(Math.min(250,end-now(),Math.max(1,until-now())));}
    check();
  };
  const deadline=new Promise((_,reject)=>{timer=setTimeout(()=>{
    expired=true;close(owner.client);close(pendingClient);reject(timeout());
  },timeoutMs);});
  const operation=async()=>{
    let failure;
    for(let attempt=0;attempt<=retryDelaysMs.length;attempt++){
      check();
      if(attempt){
        await emit('retry_scheduled',failure,{attempt,delayMs:retryDelaysMs[attempt-1]});
        close(owner.client);
        await timed('control_retry_wait',()=>wait(retryDelaysMs[attempt-1]),{attempt,plannedMs:retryDelaysMs[attempt-1],reason:'control_reconnect'});
      }
      try{
        if(attempt||!owner.client){
          pendingClient=await timed('control_connect',()=>connect(owner.ctx),{attempt});
          try{check();}catch(error){close(pendingClient);throw error;}
          owner.client=pendingClient;pendingClient=null;
        }
        const value=await timed('control_read',()=>read(owner.client),{attempt});
        check();
        if(attempt){owner.reconnectedReads=(owner.reconnectedReads||0)+1;await emit('fresh_read_verified',null,{attempt});}
        return value;
      }catch(error){
        timingFailure('control_read_failure',error,{attempt});close(pendingClient);pendingClient=null;close(owner.client);failure=error;
        await emit(attempt?'reconnect_failed':'first_read_failed',error,{attempt});
        check();
        if(!transientControlError(error)||attempt===retryDelaysMs.length){
          await emit('retry_stopped',error,{attempt,exhausted:transientControlError(error)});
          throw error;
        }
      }
    }
  };
  try{return await Promise.race([operation(),deadline]);}
  catch(error){
    if(expired)await emit('total_deadline_exceeded',error,{timeoutMs});
    if(owner.closed)await emit('reconnect_cancelled',error);
    throw error;
  }finally{clearTimeout(timer);}
}
