// Bounded delayed refresh of an XHS challenge. Never operates a captcha control.
import fs from 'node:fs/promises';
import {performance} from 'node:perf_hooks';
import {atomicLoginState} from './login-state-io.mjs';
import {inspectPlatformAccess} from './recovery-platform-access.mjs';
import {timingMarker} from './keyword-timing.mjs';
export const CAPTCHA_REFRESH_DELAYS=Object.freeze([15*60000,30*60000,60*60000]);
export function createCaptchaRefresh({page,platform,session,file,assertAllowed,now=Date.now,mono=()=>performance.now(),read=async()=>JSON.parse(await fs.readFile(file,'utf8')),write=v=>atomicLoginState(file,v),inspect=()=>inspectPlatformAccess(page,platform,{retryNavigation:false}),marker=timingMarker}){
 let state=null,loaded=false,busy=false,dueMono=null;
 const key=session.incidentId||session.sessionId;
 const snapshot=()=>state?{...state}:null;
 const allowed=()=>{try{const u=new URL(page.url());return !page.isClosed()&&u.protocol==='https:'&&/(^|\.)xiaohongshu\.com$/i.test(u.hostname);}catch{return false;}};
 async function phonePending(){
  for(const frame of page.frames()){
   let u;try{u=new URL(frame.url());}catch{continue;}
   if(u.protocol!=='https:'||!/(^|\.)xiaohongshu\.com$/i.test(u.hostname))continue;
   const labels=frame.getByText(/手机刷脸|人脸识别|请在手机(?:上|端)?(?:进行)?确认|手机确认|短信验证码|请输入验证码/);
   for(let i=0;i<Math.min(await labels.count(),30);i++)if(await labels.nth(i).isVisible().catch(()=>false))return true;
  }
  return false;
 }
 async function eligible(access){return platform==='小红书'&&allowed()&&access?.kind==='captcha'&&access.evidence!=='sms_identity_verification'&&!await phonePending();}
 async function load(){
  if(loaded)return;
  let saved;try{saved=await read();}catch(e){if(e.code!=='ENOENT')throw e;}
  if(saved?.incidentKey===key){
   if(saved.schema!==1||!Number.isInteger(saved.attempt)||saved.attempt<0||saved.attempt>3||saved.platform!==platform||saved.workerId!==session.workerId||saved.machine!==session.machine)throw Error('CAPTCHA_TIMER_STATE_INVALID');
   if(saved.nextAt!==null&&!Number.isFinite(saved.nextAt))throw Error('CAPTCHA_TIMER_STATE_INVALID');
   state=saved;
   if(saved.nextAt!==null&&saved.attempt<3)dueMono=mono()+Math.min(CAPTCHA_REFRESH_DELAYS[saved.attempt],Math.max(0,saved.nextAt-now()));
  }
  loaded=true;
 }
 async function persist(){state.updatedAt=now();await write(state);}
 function schedule(){const delay=CAPTCHA_REFRESH_DELAYS[state.attempt];state.status='waiting';state.plannedMs=delay;state.nextAt=now()+delay;dueMono=mono()+delay;}
 async function observe(access){
  if(platform!=='小红书')return null;if(busy)return snapshot();busy=true;
  try{
   await assertAllowed();await load();
   if(!await eligible(access)){
    if(state&&['waiting','refreshing'].includes(state.status)){state.status='suspended';state.nextAt=null;dueMono=null;await persist();marker('captcha_refresh_suspended',{lane:'hold',attempt:state.attempt});}
    return snapshot();
   }
   if(!state){state={schema:1,incidentKey:key,platform,machine:session.machine,workerId:session.workerId,firstSeenAt:now(),attempt:0,lastAttemptAt:null,nextAt:null};schedule();await persist();marker('captcha_refresh_wait',{lane:'hold',attempt:1,plannedMs:state.plannedMs,resumeAtMs:state.nextAt});return snapshot();}
   if(state.attempt>=3){if(state.status!=='manual_wait'){state.status='manual_wait';state.nextAt=null;dueMono=null;await persist();}return snapshot();}
   if(state.status==='suspended'||state.nextAt===null){schedule();await persist();marker('captcha_refresh_wait',{lane:'hold',attempt:state.attempt+1,plannedMs:state.plannedMs,resumeAtMs:state.nextAt});return snapshot();}
   if(dueMono===null)dueMono=mono()+Math.min(CAPTCHA_REFRESH_DELAYS[state.attempt],Math.max(0,state.nextAt-now()));
   if(mono()<dueMono)return snapshot();
   // Recheck after waiting: human completion or a stop cancels this refresh.
   await assertAllowed();if(!await eligible(await inspect())){state.status='suspended';state.nextAt=null;dueMono=null;await persist();return snapshot();}
   await assertAllowed();
   state.attempt++;state.lastAttemptAt=now();state.status='refreshing';state.nextAt=null;dueMono=null;
   // Persist consumption before navigation. Restart must not duplicate a refresh.
   await persist();marker('captcha_refresh_attempt',{lane:'hold',attempt:state.attempt,action:'reload'});
   try{await page.reload({waitUntil:'domcontentloaded',timeout:30000});state.lastResult='navigation_returned';}
   catch{state.lastResult='navigation_unconfirmed';}
   await assertAllowed();
   if(state.attempt<3)schedule();else{state.status='manual_wait';state.nextAt=null;state.plannedMs=0;}
   await persist();marker('captcha_refresh_result',{lane:'hold',attempt:state.attempt,outcome:state.lastResult,resumeAtMs:state.nextAt??0});return snapshot();
  }finally{busy=false;}
 }
 return {observe,snapshot};
}
