// Shared by collection, login recovery and local end-to-end checks.
export async function inspectPlatformAccess(page,platform,{retryNavigation=true}={}){
 if(page.isClosed())throw new Error('STOP_BROWSER_CLOSED');
 const inspect=()=>page.evaluate(platform=>{
  const visible=n=>{
   const r=n.getBoundingClientRect();if(r.width<=0||r.height<=0)return false;
   for(let p=n;p;p=p.parentElement){const s=getComputedStyle(p);
    if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)<0.05||p.getAttribute('aria-hidden')==='true')return false;}
   return true;
  };
  const content='section.note-item,.note-item,[data-note-id],.search-result-card,[data-e2e="search-result"],.note-container,#noteContainer,[data-e2e="feed-active-video"],[data-e2e="feed-video"],[data-e2e="video-desc"],[data-e2e="comment-list"]';
  const shown=selector=>[...document.querySelectorAll(selector)].some(visible);
  // Keep the same challenge guard during recovery, including the transition
  // document before the verification iframe becomes visible.
  if(platform==='抖音'&&/(^|\.)douyin\.com$/.test(location.hostname)
   &&document.title.trim()==='验证码中间页'
   &&(!shown(content)||shown('.middle_page_loading')))
   return {kind:'captcha',evidence:'verification_interstitial_document'};
  if(shown('#captcha_container,iframe[src*="rmc.bytedance.com"],iframe#nocaptcha-container,iframe[src*="rc-verifycenter"]'))return {kind:'captcha',evidence:'visible_verification_frame'};
  const labels=[...document.querySelectorAll('body,main,div,p,span,button,h1,h2,a')]
   .filter(n=>visible(n)&&!n.closest(content)&&n.childElementCount===0)
   .map(n=>(n.textContent||'').trim());
  if(labels.some(t=>/请完成.*验证|拖动.*滑块|安全验证|验证码验证/.test(t)))return {kind:'captcha',evidence:'visible_verification_prompt'};
  if(labels.some(t=>/操作频繁|访问频繁|访问过于频繁|暂时无法浏览|安全限制|网络环境存在风险|300013/.test(t)))return {kind:'security',evidence:'visible_security_prompt'};
  if(shown('[id^="login-full-panel-"],.login-container,.login-modal,.login-mask,[role="dialog"][aria-label*="登录"]'))return {kind:'login',evidence:'visible_login_panel'};
  if(labels.some(t=>/^登录$|登录后推荐更懂你的笔记|登录后查看搜索结果|登录后即可搜索|登录后查看更多|登录后查看评论|扫码登录|请先登录/.test(t)))return {kind:'login',evidence:'visible_login_prompt'};
  const unwrap=x=>x&&typeof x==='object'?('value' in x?x.value:('_value' in x?x._value:x)):x;
  const user=unwrap(window.__INITIAL_STATE__?.user),flag=unwrap(user?.isLogin)??unwrap(user?.isLoggedIn);
  if(flag===false)return {kind:'login',evidence:'rendered_app_logged_out'};
  if(labels.some(t=>/(?:502\s+Bad Gateway|503\s+Service Unavailable|504\s+Gateway Time-out)/i.test(t)))return {kind:'gateway',evidence:'visible_gateway_document'};
  return {kind:null,evidence:'no_visible_restriction'};
 },platform);
 // A normal full-document search navigation can replace the JS context
 // between two checks. Retry observations only; never resubmit an action.
 for(let attempt=0;attempt<3;attempt++){
  try{
   const main=await inspect();
   if(['security','gateway'].includes(main.kind)||main.kind==='captcha'&&main.evidence!=='visible_verification_prompt')return main;
   if(platform==='抖音')for(const frame of page.frames()){
    let u;try{u=new URL(frame.url());}catch{continue;}
    if(u.protocol!=='https:'||!/(^|\.)douyin\.com$/i.test(u.hostname))continue;
    const sms=await frame.evaluate(()=>{
     const shown=n=>{const r=n.getBoundingClientRect();if(!r.width||!r.height)return false;for(let p=n;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)<.05)return false;}return true;};
     const labels=[...document.querySelectorAll('h1,h2,h3,div,span,p,button')].filter(n=>n.childElementCount===0&&shown(n)).map(n=>n.textContent.trim());
     return !labels.some(t=>/拖动.*滑块|拖动.*拼图|旋转.*图片|完成.*滑块/.test(t))&&labels.some(t=>/^(身份验证|短信验证|短信验证码验证|接收短信验证码|手机验证)$/.test(t));
    });
    if(sms)return {kind:'captcha',evidence:'sms_identity_verification'};
   }
   return main;
  }
  catch(error){
   if(page.isClosed())throw new Error('STOP_BROWSER_CLOSED');
   if(!retryNavigation||attempt===2||!/Execution context was destroyed|Cannot find context|most likely because of a navigation/.test(String(error.message)))throw error;
   await page.waitForLoadState?.('domcontentloaded',{timeout:3000}).catch(()=>{});
  }
 }
}
export function platformAccessError(state,platform){
 if(!state?.kind)return null;
 const messages={
  login:'STOP_LOGIN_REQUIRED：请在本机完成人工登录',
  captcha:platform==='小红书'?'STOP_SECURITY_CHALLENGE：出现验证码或安全验证，请人工处理':'STOP_PLATFORM_RESTRICTION：出现验证码或安全验证，请人工处理',
  security:platform==='小红书'?'STOP_SECURITY_CHALLENGE：安全限制，自动冷却等待':'STOP_PLATFORM_RESTRICTION：访问频繁，自动冷却等待',
  gateway:'STOP_SEARCH_GATEWAY_ERROR：网站网关暂时不可用'
 };
 return Object.assign(new Error(messages[state.kind]),{accessEvidence:state.evidence});
}
export async function assertPlatformAccess(page,platform,{report}={}){
 const state=await inspectPlatformAccess(page,platform),error=platformAccessError(state,platform);
 if(error){if(report&&state.kind!=='gateway')await report(error.message);throw error;}
 return state;
}
export async function guardedPlatformAction(page,platform,action,options={}){
 await assertPlatformAccess(page,platform,options);
 try{return await action();}
 catch(error){await assertPlatformAccess(page,platform,options);throw error;}
}
