import {ANNUAL_RESUME_VERSION} from './annual-resume.mjs';

export const CONTEXT_DATE_RECOVERY_VERSION='xhs-context-date-recovery-20261109-v1';
export const CONTEXT_RECOVERY_DELAYS_MS=Object.freeze([30000,60000,120000]);
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));

export function dateRecoveryEligible(collector,{annual=false,ownedBrowser=false}={}){
  if(!annual||!ownedBrowser||collector?.annualResumePolicy!==ANNUAL_RESUME_VERSION)return false;
  const code=String(collector.collectionError||collector.error||'').split(/[：:\s]/,1)[0];
  return ['STOP_SEARCH_CONTEXT_LOST','STOP_DETAIL_CONTEXT_LOST','STOP_BROWSER_CLOSED'].includes(code)
    && ['context_lost','browser_closed'].includes(collector.collectionStatus||collector.status);
}

// Keep the exact task, checkpoint and live fenced lease. A retry starts a new
// collector (and run ID), which reuses the existing date-window/dedup policy.
// This gate never clears a stop, CAPTCHA, cooldown or lost-lease marker.
export async function collectWithDateRecovery({run,annual=false,ownedBrowser=false,
  assertAllowed,restartBrowser,acceptFailure=async()=>null,onEvent=async()=>{},
  delays=CONTEXT_RECOVERY_DELAYS_MS,wait=sleep}){
  const history=[];
  let attempt=0;
  const finish=(value,extra={})=>({...value,...extra,recovery:{
    version:CONTEXT_DATE_RECOVERY_VERSION,restarts:attempt,history,...extra.recovery}});
  while(true){
    const value=await run(attempt);
    if(!dateRecoveryEligible(value.collector,{annual,ownedBrowser})){
      if(attempt)await onEvent('finished',{attempt,collectorRunId:value.collector.runId,status:value.collector.status});
      return finish(value);
    }
    const failure={attempt,error:value.collector.error,status:value.collector.status,
      collectorRunId:value.collector.runId,firstFailureAt:value.collector.firstFailureAt||null};
    history.push(failure);
    // Quantity-based exception closure takes precedence over another browser launch.
    const acceptedRecord=await acceptFailure(value);
    if(acceptedRecord)return finish(value,{acceptedRecord});
    if(attempt>=delays.length){
      await onEvent('exhausted',{...failure,restarts:attempt});
      return finish(value,{recovery:{exhausted:true}});
    }
    try{
      await assertAllowed();
      const delayMs=delays[attempt];
      await onEvent('waiting',{...failure,nextAttempt:attempt+1,delayMs});
      // Recheck stop/lease/protection during the backoff, not only afterwards.
      let remaining=delayMs;
      while(remaining>0){
        const chunk=Math.min(1000,remaining);await wait(chunk);remaining-=chunk;
        await assertAllowed();
      }
      await assertAllowed();
      await restartBrowser();
      await assertAllowed();
    }catch(error){
      const blockedBy=String(error?.code||error?.message||error).split('\n')[0];
      await onEvent('blocked',{...failure,blockedBy});
      return finish(value,{recovery:{blockedBy}});
    }
    attempt++;
    await onEvent('resuming',{previousCollectorRunId:failure.collectorRunId,attempt});
  }
}

// Close only the browser process owned by this worker. Do not touch an external
// CDP session or an unrelated process that happens to listen on the same port.
export async function stopOwnedBrowser(child,cdpUrl,{timeoutMs=15000,wait=sleep,
  requestClose=async()=>{
    const {chromium}=await import('playwright');
    const browser=await chromium.connectOverCDP(cdpUrl,{timeout:5000});
    let timer;
    try{
      const session=await browser.newBrowserCDPSession();
      await Promise.race([session.send('Browser.close'),new Promise((_,reject)=>{
        timer=setTimeout(()=>reject(new Error('BROWSER_RECOVERY_GRACEFUL_CLOSE_TIMEOUT')),5000);
      })]);
    }finally{clearTimeout(timer);await browser.close().catch(()=>{});}
  },
  now=Date.now,probe=async()=>{
    try{return (await fetch(cdpUrl+'/json/version',{signal:AbortSignal.timeout(1000)})).ok;}
    catch{return false;}
  }}={}){
  if(!child)throw new Error('BROWSER_RECOVERY_NOT_OWNED');
  if(child.exitCode===null&&child.signalCode===null){
    // Browser.close flushes profile storage. Killing a healthy Chrome immediately
    // can discard recent login cookies. Fall back only when CDP is unavailable.
    if(await probe())await requestClose();
    else if(!child.kill())throw new Error('BROWSER_RECOVERY_STOP_FAILED');
    const deadline=now()+timeoutMs;
    while(child.exitCode===null&&child.signalCode===null){
      if(now()>=deadline)throw new Error('BROWSER_RECOVERY_STOP_TIMEOUT');
      await wait(100);
    }
  }
  const deadline=now()+timeoutMs;
  while(await probe()){
    if(now()>=deadline)throw new Error('BROWSER_RECOVERY_PORT_STILL_BUSY');
    await wait(100);
  }
}
