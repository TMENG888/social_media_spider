import {configureTiming,timed,timedSync,contentTiming,timingDisposition,timingMarker,timingProgress,timingFailure,timingStop} from './keyword-timing.mjs';
import {waitForPacing} from './collection-pacing.mjs';

export const COMMENT_CLICK_RETRY_DELAYS_MS=Object.freeze([10000,20000,40000]);
export function retryableCommentClick(error){
  return !/STOP_|LOGIN_REQUIRED|SECURITY_CHALLENGE|PLATFORM_RESTRICTION|LEASE_LOST/.test(String(error?.message))
    && (error?.name==='TimeoutError'||/Timeout \d+ms exceeded|element.*detached|Element is not attached/i.test(String(error?.message)));
}

// One initial attempt plus three delayed retries. The caller resolves the
// current post/control anew. A missing control is not proof of comment completion.
export async function clickCommentExpansionWithRetry({findControl,check,flush=async()=>{},onFailure=async()=>{},
  retryDelaysMs=COMMENT_CLICK_RETRY_DELAYS_MS,timeoutMs=10000,
  wait=ms=>waitForPacing(ms,{shouldStop:async()=>{await check();return false;}})}){
  if(!Array.isArray(retryDelaysMs)||retryDelaysMs.length>3||retryDelaysMs.some(ms=>!Number.isFinite(ms)||ms<0||ms>60000))throw new Error('COMMENT_CLICK_RETRY_BUDGET_INVALID');
  const audit={maxRetries:retryDelaysMs.length,attempts:[]};
  for(let attempt=0;attempt<=retryDelaysMs.length;attempt++){
    await check();await flush();
    const control=await timed('comment_control_find',()=>findControl(),{attempt:attempt+1});
    if(!control)return false;
    try{
      await timed('comment_reply_click',()=>control.click({timeout:timeoutMs,noWaitAfter:true}),{attempt:attempt+1});
      return true;
    }catch(error){
      audit.attempts.push({attempt:attempt+1,errorName:error.name||'Error'});timingFailure('comment_click_failure',error,{attempt:attempt+1});
      // Detect a new login/CAPTCHA/stop before considering a UI retry.
      await check();
      const retry=attempt<retryDelaysMs.length&&retryableCommentClick(error);
      audit.exhausted=retryableCommentClick(error)&&!retry;
      try{await onFailure({error,attempt:attempt+1,retrying:retry,delayMs:retry?retryDelaysMs[attempt]:0,audit});}catch{}
      if(!retry)throw Object.assign(error,{commentClickRetry:audit});
      console.warn(`[评论点击重试] 第${attempt+1}次点击未完成，等待${retryDelaysMs[attempt]/1000}秒；重试${attempt+1}/${retryDelaysMs.length}`);
      await timed('comment_retry_wait',()=>wait(retryDelaysMs[attempt]),{attempt:attempt+1,plannedMs:retryDelaysMs[attempt],reason:'comment_click_retry'});
    }
  }
}
