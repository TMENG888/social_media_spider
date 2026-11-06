import {waitForManualLogin,verifyManualSearch} from './recovery-login-check.mjs';
import {inspectPlatformAccess} from './recovery-platform-access.mjs';
const navigationRace=error=>/Execution context was destroyed|Cannot find context|Frame was detached|Target page.*closed|page has been closed/i.test(String(error?.message||''));
async function clearPages(context,platform){
 for(const page of context.pages()){
  if(page.isClosed())continue;
  let u;try{u=new URL(page.url());}catch{continue;}
  const domain=platform==='抖音'?'douyin.com':'xiaohongshu.com';
  if(u.hostname!==domain&&!u.hostname.endsWith('.'+domain))continue;
  if((await inspectPlatformAccess(page,platform)).kind)return false;
 }
 return true;
}
export async function automaticRecoveryCheck(context,platform,{keyword='',watch,settleMs=800}={}){
 try{
  if(!await clearPages(context,platform))return {ok:false,reason:'LOGIN_OR_SECURITY_STILL_VISIBLE'};
  const login=await waitForManualLogin(context,platform,{timeoutMs:2000,pollMs:500,settleMs});
  if(!login.ok)return login;
  if(keyword){const search=await verifyManualSearch(context,watch,platform,keyword,{settleMs});if(!search.ok)return {...search,loginVerified:true,searchDiagnostics:watch.diagnostics?.()};}
  if(!await clearPages(context,platform))return {ok:false,reason:'LOGIN_OR_SECURITY_STILL_VISIBLE'};
  return {ok:true,loginVerified:true,reason:keyword?'LOGIN_AND_SEARCH_VERIFIED':'LOGIN_VERIFIED'};
 }catch(error){if(navigationRace(error))return {ok:false,reason:'PAGE_CHANGED_DURING_CHECK'};throw error;}
}
export async function waitForAutomaticRecovery(context,platform,{assertNoNewStop=async()=>{},onState=()=>{},pollMs=1500,searchProbeIntervalMs=30000,maxSearchProbes=2,navigateRecoverySearch,...options}={}){
 let consecutive=0,loginConsecutive=0,previous='',searchProbes=0,lastSearchProbe=-Infinity;
 while(true){
  await assertNoNewStop();
  if(!context.pages().some(page=>!page.isClosed()))throw new Error('OPERATOR_CANCELLED：浏览器已关闭，保留保护。');
  const check=await automaticRecoveryCheck(context,platform,options);
  if(check.reason!==previous){await onState(check);previous=check.reason;}
  loginConsecutive=check.loginVerified?loginConsecutive+1:0;
  // Logging in can return to the homepage without retrying the blocked search.
  // After stable login and no challenge, open this node's approved search once.
  if(!check.ok&&loginConsecutive>=2&&options.keyword&&check.reason==='NO_FRESH_SUCCESSFUL_SEARCH'
   &&searchProbes<maxSearchProbes&&Date.now()-lastSearchProbe>=searchProbeIntervalMs){
   await assertNoNewStop();
   const domain=platform==='抖音'?'douyin.com':'xiaohongshu.com';
   const page=[...context.pages()].reverse().find(p=>{try{const host=new URL(p.url()).hostname;return !p.isClosed()&&(host===domain||host.endsWith('.'+domain));}catch{return false;}});
   if(page){
    searchProbes++;lastSearchProbe=Date.now();
    await onState({ok:false,loginVerified:true,reason:'VERIFYING_CURRENT_SEARCH',attempt:searchProbes});
    try{
     if(platform==='抖音'){
      const navigate=navigateRecoverySearch||(await import('./douyin-browser.mjs')).navigateSearch;
      await navigate(page,options.keyword,{shouldStop:async()=>{await assertNoNewStop();return false;},timeoutMs:15000,retryDelaysMs:[]});
     }else{
      await page.goto('https://www.xiaohongshu.com/search_result?keyword='+encodeURIComponent(options.keyword),{waitUntil:'domcontentloaded',timeout:15000});
     }
    }catch(error){
     await assertNoNewStop();
     if(page.isClosed())throw error;
     await onState({ok:false,reason:'SEARCH_NAVIGATION_NOT_CONFIRMED'});
    }
    previous='';
   }
  }
  consecutive=check.ok?consecutive+1:0;
  if(consecutive>=2){await assertNoNewStop();return check;}
  await new Promise(resolve=>setTimeout(resolve,pollMs));
 }
}
