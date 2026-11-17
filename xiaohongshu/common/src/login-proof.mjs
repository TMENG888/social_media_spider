// Read credentials only inside the owner's browser context. Never export values.
export const LOGIN_PROOF_VERSION='login-proof-20261111-v1';
export async function inspectBrowserCredential(context,platform,{now=Date.now,timeoutMs=2500}={}){
 const domain=platform==='小红书'?'xiaohongshu.com':platform==='抖音'?'douyin.com':null;
 if(!domain)return {credentialPresent:false,reason:'UNSUPPORTED_PLATFORM'};
 let timer;
 try{
  const cookies=await Promise.race([context.cookies(['https://www.'+domain+'/']),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('CREDENTIAL_CHECK_TIMEOUT')),timeoutMs);})]);
  const accepted=platform==='小红书'?['web_session']:['sessionid','sessionid_ss'];
  const names=cookies.filter(c=>accepted.includes(c.name)&&typeof c.value==='string'&&c.value.trim().length>0
   &&(c.domain.replace(/^\./,'')===domain||c.domain.replace(/^\./,'').endsWith('.'+domain))
   &&(c.expires===-1||Number.isFinite(c.expires)&&c.expires>now()/1000)).map(c=>c.name);
  return {version:LOGIN_PROOF_VERSION,credentialPresent:names.length>0,names:[...new Set(names)],checkedAt:now(),reason:names.length?'BROWSER_SESSION_PRESENT':'LOGIN_CREDENTIAL_MISSING'};
 }catch{return {version:LOGIN_PROOF_VERSION,credentialPresent:false,checkedAt:now(),reason:'LOGIN_CREDENTIAL_UNCONFIRMED'};}
 finally{clearTimeout(timer);}
}
