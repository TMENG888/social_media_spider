import {timed} from './keyword-timing.mjs';
import {waitForPacing} from './collection-pacing.mjs';

export const COMMENT_LOAD_RETRY_DELAYS_MS=Object.freeze([30000,60000,120000]);

// One bounded budget per post/pass, even if an earlier retry briefly helped.
// Only the caller's proven no-progress condition enters this recovery path.
export function createCommentLoadRetries({check,flush,scroll,onAttempt=async()=>{},
 wait=ms=>waitForPacing(ms,{reason:'comment_load_retry',shouldStop:async()=>{await check();return false;}})}){
 const attempts=[];let exhausted=false;
 return {
  audit:()=>({maxRetries:COMMENT_LOAD_RETRY_DELAYS_MS.length,exhausted,attempts:attempts.map(a=>({...a}))}),
  observe(count){
   const last=attempts.at(-1);
   if(last&&last.status==='scrolled'&&count>last.beforeCount){last.status='progress_observed';last.afterCount=count;last.progressAt=new Date().toISOString();}
  },
  async retry(details){
   await check();
   if(attempts.length>=COMMENT_LOAD_RETRY_DELAYS_MS.length){exhausted=true;return false;}
   const attempt={attempt:attempts.length+1,delayMs:COMMENT_LOAD_RETRY_DELAYS_MS[attempts.length],
    beforeCount:details.collected,pagesBefore:details.pages,status:'waiting',at:new Date().toISOString()};
   attempts.push(attempt);
   try{await onAttempt({...attempt,...details});}catch{/* Diagnostic storage must not change recovery policy. */}
   try{
    await timed('comment_retry_wait',()=>wait(attempt.delayMs),{reason:'comment_load_stalled',attempt:attempt.attempt,plannedMs:attempt.delayMs});
    await check();await flush();await scroll();await check();await flush();
    attempt.status='scrolled';attempt.scrolledAt=new Date().toISOString();return true;
   }catch(error){
    attempt.status='interrupted';attempt.errorCode=String(error?.code||error?.message||error).split(/[：:]/)[0].slice(0,100);
    throw error;
   }
  }
 };
}
