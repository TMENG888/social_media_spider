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
  if(shown('iframe#nocaptcha-container,iframe[src*="rc-verifycenter"]'))return {kind:'captcha',evidence:'visible_verification_frame'};
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
  try{return await inspect();}
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
