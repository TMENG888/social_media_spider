import {OperationalGate} from './operational-gate.mjs';
import path from 'node:path';
import fs from 'node:fs/promises';
import {inspectPlatformAccess} from './platform-access.mjs';
import {COOLDOWN_SCOPE_LUA} from './cooldown-scope.mjs';

export function workerStatePath(worker,queue,platform){
 if(queue.workerId&&queue.workerId!==path.basename(worker))throw new Error('WORKER_ID_MISMATCH：任务清单不属于此节点。');
 const state=platform==='小红书'?path.resolve(worker,'tasks',queue.stateRoot||path.join(worker,'.state')):path.join(worker,'.state');
 const relative=path.relative(worker,state);
 if(!relative||relative==='..'||relative.startsWith('..'+path.sep)||path.isAbsolute(relative))
  throw new Error('STATE_PATH_OUTSIDE_WORKER：状态目录不在此节点内，禁止误用其他节点登录资料。');
 return state;
}
export async function assertWorkerIdle(state,{readText=file=>fs.readFile(file,'utf8'),probe=pid=>process.kill(pid,0)}={}){
 let lock;
 try{lock=JSON.parse(await readText(path.join(state,'worker.lock')));}
 catch(error){if(error.code==='ENOENT')return;throw new Error('WORKER_STATE_UNCONFIRMED：不能确认采集进程状态，请先安全停止并检查锁文件；不会删除锁。');}
 if(!Number.isInteger(lock.pid)||lock.pid<=0)throw new Error('WORKER_STATE_UNCONFIRMED：采集锁文件无有效PID；不会删除锁。');
 try{probe(lock.pid);}
 catch(error){if(error.code==='ESRCH')return;throw new Error('WORKER_STATE_UNCONFIRMED：无权确认采集进程，请先安全停止。');}
 throw new Error('WORKER_STILL_RUNNING：此节点采集进程尚未退出，请先安全停止或等待收尾；不会干扰正在采集的浏览器。');
}

// Monitoring-only recovery; never changes tasks, leases, SQL or stop flags.
export const SNAPSHOT_LUA = COOLDOWN_SCOPE_LUA + `
local ir=redis.call('HGET',KEYS[1],ARGV[1]) or ''
local t=redis.call('TIME');local now=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
local sr=''
local shared_hold=false;local tr=''
if #KEYS==3 then
 sr=redis.call('HGET',KEYS[3],'state') or ''
 tr=redis.call('HGET',KEYS[3],'timedState') or ''
 shared_hold=cooldown_scope(sr~='' and sr or nil,KEYS[1],ARGV[1],now,KEYS[3]).sharedManualRequired
end
return cjson.encode({incidentRaw=ir,sharedRaw=sr,timedRaw=tr,serverTime=now,sharedHoldPreserved=shared_hold})
`;
export const RECOVER_LUA = `
local ir=redis.call('HGET',KEYS[1],ARGV[1]) or ''
local sr='';local tr=''
if #KEYS==3 then sr=redis.call('HGET',KEYS[3],'state') or '';tr=redis.call('HGET',KEYS[3],'timedState') or '' end
if ir~=ARGV[2] or sr~=ARGV[3] or tr~=(ARGV[6] or '') then return cjson.encode({ok=false,reason='INCIDENT_CHANGED'}) end
local i=ir~='' and cjson.decode(ir) or nil
local s=sr~='' and cjson.decode(sr) or nil
local t=redis.call('TIME');local now=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
if i and i.status~='resolved' and i.status~='ready' and i.kind~='login' and i.kind~='captcha' then
 return cjson.encode({ok=false,reason='NOT_LOGIN_OR_CAPTCHA'})
end
if s and not s.manualRequired and (s.untilMs or 0)>now then
 return cjson.encode({ok=false,reason='TIMED_COOLDOWN_PRESERVED'})
end
local timed=tr~='' and cjson.decode(tr) or nil
if timed and (timed.untilMs or 0)>now then return cjson.encode({ok=false,reason='TIMED_COOLDOWN_PRESERVED'}) end
if ARGV[4]~='local_confirmed' then
 return cjson.encode({ok=false,reason='NODE_ONLY_RECOVERY_REQUIRED'})
end
-- Type-check every write target before writing: Lua errors do not roll back.
redis.call('HGET',KEYS[2],'__recovery_probe__')
if i and i.status~='resolved' and i.status~='ready' then
 i.status='resolved';i.requiresHuman=false;i.resolvedAt=now;i.resolution='verified_manual_login'
 local encoded=cjson.encode(i);redis.call('HSET',KEYS[1],ARGV[1],encoded)
 if i.notifyHuman==true then redis.call('HSET',KEYS[2],i.incidentId..'|resolved',encoded) end
end
return cjson.encode({ok=true,status='resolved',sharedReset=false})
`;

export function recoveryState(snapshot) {
 const incident=snapshot.incidentRaw?JSON.parse(snapshot.incidentRaw):null;
 const shared=snapshot.sharedRaw?JSON.parse(snapshot.sharedRaw):null;
 const timed=snapshot.timedRaw?JSON.parse(snapshot.timedRaw):null;
 if(incident&&!['resolved','ready'].includes(incident.status)&&!['login','captcha'].includes(incident.kind))
  throw new Error('NOT_LOGIN_OR_CAPTCHA：安全限流事件不通过登录工具解除，请保留冷却。');
 if(shared&&!shared.manualRequired&&shared.untilMs>snapshot.serverTime||timed&&timed.untilMs>snapshot.serverTime)
  throw new Error('TIMED_COOLDOWN_PRESERVED：定时冷却由原启动脚本等待，不在登录工具中重置。');
 // A browser login confirms only this node, never all nodes in the group.
 return {incident,shared,needsShared:false,sharedHoldPreserved:snapshot.sharedHoldPreserved===true};
}
export async function openRecovery(common,workerId,platform,{onStage=()=>{}}={}) {
 let owner,gate,keys;
 if(platform==='小红书'){
  const {RateLimitCooldown}=await import('./rate-limit-cooldown.mjs');
  owner=await RateLimitCooldown.open({root:common,stateRoot:null,workerId,onStage});
  gate=owner.operations;keys=[...gate.keys,owner.key];
 }else{
  owner=gate=await OperationalGate.open({root:common,workerId,platform,onStage});keys=gate.keys;
 }
 return {
  async snapshot(){return JSON.parse(await gate.client.eval(SNAPSHOT_LUA,{keys,arguments:[gate.field]}));},
  async resolve(snapshot,sharedConfirmed){
   return JSON.parse(await gate.client.eval(RECOVER_LUA,{keys,arguments:[
    gate.field,snapshot.incidentRaw,snapshot.sharedRaw,sharedConfirmed?'shared_confirmed':'local_confirmed',workerId,snapshot.timedRaw||'']}));
  },
  close:()=>owner.close()
 };
}
function supportedHost(url,platform) {
 return platform==='抖音'?/(^|\.)douyin\.com$/i.test(url.hostname):/(^|\.)xiaohongshu\.com$/i.test(url.hostname);
}
export function searchKeyword(value,platform){
 try{
  const url=new URL(value);if(!supportedHost(url,platform)||url.searchParams.has('modal_id'))return null;
  if(platform==='小红书')return /^\/search_result\/?$/.test(url.pathname)?url.searchParams.get('keyword'):null;
  const match=url.pathname.match(/^\/(?:jingxuan\/)?search\/(.+)$/);
  return match?decodeURIComponent(match[1]):null;
 }catch{return null;}
}
export function requestKeyword(request,platform){
 try{
  const url=new URL(request.url());if(!supportedHost(url,platform))return null;
  const valid=platform==='小红书'?/\/api\/sns\/web\/v\d+\/search\/notes\/?$/.test(url.pathname):/\/general\/search(?:\/|$)/.test(url.pathname);
  if(!valid)return null;
  let keyword=url.searchParams.get('keyword');
  if(!keyword){const body=request.postData()||'';try{keyword=JSON.parse(body).keyword;}catch{keyword=new URLSearchParams(body).get('keyword');}}
  return keyword||null;
 }catch{return null;}
}
export function successfulSearchData(data,platform){
 if(!data||typeof data!=='object')return false;
 return platform==='小红书'?data.success!==false&&(data.success===true||data.code===0)&&(data.code==null||data.code===0):data.status_code===0;
}
export function watchManualSearch(context,platform,keyword){
 let evidence=null,closed=false;const requests=new WeakSet();
 const onRequest=request=>{if(requestKeyword(request,platform)===keyword)requests.add(request);};
 const onResponse=response=>{
  if(closed||!requests.has(response.request())||response.status()!==200)return;
  void (async()=>{
   try{
    const data=await response.json();
    if(!closed&&successfulSearchData(data,platform))
     evidence={page:response.frame().page(),at:Date.now(),keyword};
   }catch{}
  })();
 };
 context.on('request',onRequest);context.on('response',onResponse);
 return {get:()=>evidence,close:()=>{closed=true;context.off('request',onRequest);context.off('response',onResponse);}};
}
export async function inspectSearchPage(page,platform,keyword){
 if(page.isClosed()||searchKeyword(page.url(),platform)!==keyword)return {ok:false,reason:'SEARCH_URL_MISMATCH'};
 const snapshot=await page.evaluate(({platform,keyword})=>{
  const visible=node=>{
   const rect=node.getBoundingClientRect();if(rect.width<=0||rect.height<=0)return false;
   for(let p=node;p;p=p.parentElement){const s=getComputedStyle(p);
    if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)<0.05||p.getAttribute('aria-hidden')==='true')return false;}
   return true;
  };
  const cards=platform==='小红书'?'section.note-item,.note-item,[data-note-id]':'.search-result-card,[data-e2e="search-result"]';
  const labels=[...document.querySelectorAll('div,p,span,button,h1,h2')]
   .filter(n=>visible(n)&&!n.closest(cards)&&n.childElementCount===0)
   .map(n=>(n.textContent||'').trim());
  const blocked=labels.some(t=>/登录后推荐更懂你的笔记|登录后查看搜索结果|登录后即可搜索|登录后查看更多|登录后查看评论|扫码登录|请先登录|安全验证|请完成.*验证|拖动.*滑块|访问频繁|操作频繁|访问过于频繁|暂时无法浏览|网络环境存在风险|300013|Bad Gateway|Service Unavailable|Gateway Time-out/i.test(t))
   ||[...document.querySelectorAll('iframe#nocaptcha-container,iframe[src*="rc-verifycenter"],.login-container,.login-mask')].some(visible);
  const inputs=[...document.querySelectorAll('input[data-e2e="searchbar-input"],input[name="keyword"],input[placeholder*="搜索"],input#search-input')].filter(visible);
  const inputMatches=inputs.some(n=>n.value===keyword);
  const results=[...document.querySelectorAll(cards)].some(visible);
  const empty=labels.some(t=>/^(暂无搜索结果|没有找到相关(内容|结果)|暂无相关(内容|结果)|暂时没有更多了|没有更多了|暂无笔记|没有找到你想要的结果)[。！!]?$/u.test(t));
  return {blocked,inputMatches,results,empty};
 },{platform,keyword});
 return {...snapshot,ok:!snapshot.blocked&&snapshot.inputMatches&&(snapshot.results||snapshot.empty)};
}
export async function verifyManualSearch(context,watch,platform,keyword,{settleMs=1000}={}){
 const evidence=watch.get();if(!evidence)return {ok:false,reason:'NO_FRESH_SUCCESSFUL_SEARCH'};
 const page=evidence.page;
 const first=await inspectSearchPage(page,platform,keyword);
 if(!first.ok)return {ok:false,reason:first.blocked?'LOGIN_OR_SECURITY_STILL_VISIBLE':'SEARCH_PAGE_NOT_VERIFIED'};
 await page.waitForTimeout(settleMs);
 const second=await inspectSearchPage(page,platform,keyword);
 return second.ok?{ok:true,keyword,verifiedAt:new Date().toISOString()}:{
  ok:false,reason:second.blocked?'LOGIN_OR_SECURITY_STILL_VISIBLE':'SEARCH_PAGE_CHANGED'};
}
export function recoveryConfirmation(answer,needsShared){
 const value=String(answer).trim();
 return needsShared?['CONFIRM LOCAL','CONFIRM SHARED'].includes(value):value==='CONFIRM';
}

export async function inspectLoginPage(page,platform){
 if(page.isClosed())return {ok:false,reason:'BROWSER_CLOSED'};
 let url;
 try{url=new URL(page.url());}catch{return {ok:false,reason:'PLATFORM_PAGE_REQUIRED'};}
 if(!['http:','https:'].includes(url.protocol)||!supportedHost(url,platform))
  return {ok:false,reason:'PLATFORM_PAGE_REQUIRED'};
 const access=await inspectPlatformAccess(page,platform,{retryNavigation:false});
 if(access.kind)return {ok:false,reason:access.evidence==='rendered_app_logged_out'?'APP_REPORTS_LOGGED_OUT':'LOGIN_OR_SECURITY_STILL_VISIBLE',access};
 const state=await page.evaluate(platform=>{
  const visible=node=>{
   const r=node.getBoundingClientRect();if(r.width<=0||r.height<=0)return false;
   for(let p=node;p;p=p.parentElement){const s=getComputedStyle(p);
    if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)<0.05||p.getAttribute('aria-hidden')==='true')return false;}
   return true;
  };
  const content='section.note-item,.note-item,[data-note-id],.search-result-card,[data-e2e="search-result"],.note-container,#noteContainer,[data-e2e="feed-active-video"],[data-e2e="feed-video"],[data-e2e="video-desc"],[data-e2e="comment-list"]';
  const labels=[...document.querySelectorAll('div,p,span,button,h1,h2,a')]
   .filter(n=>visible(n)&&!n.closest(content)&&n.childElementCount===0)
   .map(n=>(n.textContent||'').trim());
  const blocked=labels.some(t=>/^登录$|登录后推荐更懂你的笔记|登录后查看搜索结果|登录后即可搜索|登录后查看更多|登录后查看评论|扫码登录|请先登录|安全验证|请完成.*验证|拖动.*滑块|访问频繁|操作频繁|访问过于频繁|暂时无法浏览|网络环境存在风险|300013|Bad Gateway|Service Unavailable|Gateway Time-out/i.test(t))
   ||[...document.querySelectorAll('iframe#nocaptcha-container,iframe[src*="rc-verifycenter"],.login-container,.login-mask,[role="dialog"][aria-label*="登录"]')].some(visible);
  const unwrap=value=>{
   if(value&&typeof value==='object'&&'value' in value)return value.value;
   if(value&&typeof value==='object'&&'_value' in value)return value._value;
   return value;
  };
  // Read rendered application login flags only. Never read cookies, storage,
  // account IDs, tokens, credentials or request headers.
  const user=unwrap(window.__INITIAL_STATE__?.user);
  const explicit=unwrap(user?.isLogin)??unwrap(user?.isLoggedIn);
  const appLoggedIn=typeof explicit==='boolean'?explicit:null;
  const defaultAvatar=/default[_/-]?(avatar|user)|guest|anonymous/i;
  const avatar=node=>[node,...node.querySelectorAll('img,[role="img"],[data-e2e="user-avatar"]')].some(img=>{
   if(!visible(img))return false;
   const image=img.matches('img')?(img.currentSrc||img.getAttribute('src')||''):getComputedStyle(img).backgroundImage;
   return Boolean(image&&image!=='none'&&!defaultAvatar.test(image));
  });
  const navRoots=[...document.querySelectorAll('header,[role="banner"],aside,nav,.side-bar,.sidebar,[data-e2e="sidebar"]')];
  const selfLink=node=>{try{const target=new URL(node.getAttribute('href')||'',location.href);
   return node.matches('a[href]')&&/(^|\.)douyin\.com$/i.test(target.hostname)&&/^\/user\/self\/?$/.test(target.pathname);
  }catch{return false;}};
  const ownNavigation=navRoots.some(root=>[...root.querySelectorAll('a,li,button,.user,.side-bar-component')].some(node=>{
   if(node.closest(content)||!visible(node)||!avatar(node))return false;
   return /^(我|我的|个人主页|我的主页)$/.test((node.textContent||'').trim())
    ||node.matches('.user.side-bar-component,.user')
    ||(platform==='抖音'&&(selfLink(node)||[...node.querySelectorAll('a[href]')].some(selfLink)));
  }));
  const xhsOwn=[...document.querySelectorAll('.user.side-bar-component')].some(n=>visible(n)&&avatar(n)&&/^(我|我的|个人主页|我的主页)$/.test((n.textContent||'').trim()));
  const dyOwn=[...document.querySelectorAll('[data-e2e="user-info"],[data-e2e="user-avatar"],[data-e2e="sidebar-user"]')]
   .some(n=>!n.closest(content)&&visible(n)&&avatar(n));
  // Alternate header layouts use a self link or an accessible account-menu
  // button rather than the old data-e2e nodes. Never accept arbitrary authors.
  const dyHeaderOwn=platform==='抖音'&&navRoots.some(root=>
   [...root.querySelectorAll('a[href],button,[role="button"]')].some(node=>{
    if(node.closest(content)||!visible(node)||!avatar(node))return false;
    const label=(node.getAttribute('aria-label')||node.textContent||'').trim();
    return selfLink(node)||/^(个人中心|我的账号|个人主页|我的主页|用户菜单)$/.test(label);
   }));
  const ownAccount=ownNavigation||(platform==='小红书'?xhsOwn:(dyOwn||dyHeaderOwn));
  const ready=document.readyState!=='loading'&&(document.body?.innerText.trim().length||0)>0;
  return {ready,blocked,appLoggedIn,ownAccount};
 },platform);
 if(state.blocked)return {ok:false,reason:'LOGIN_OR_SECURITY_STILL_VISIBLE',signals:state};
 if(!state.ready)return {ok:false,reason:'PAGE_NOT_READY',signals:state};
 if(state.appLoggedIn===false)return {ok:false,reason:'APP_REPORTS_LOGGED_OUT',signals:state};
 if(state.appLoggedIn!==true&&!state.ownAccount)return {ok:false,reason:'LOGIN_STATE_UNCONFIRMED',signals:state};
 return {ok:true,evidence:state.appLoggedIn===true?'rendered_app_login_flag':'own_account_navigation'};
}
export async function verifyManualLogin(context,platform,{settleMs=800}={}){
 let page=null,first=null,last=null;
 for(const candidate of [...context.pages()].reverse()){
  const check=await inspectLoginPage(candidate,platform);
  if(check.reason!=='PLATFORM_PAGE_REQUIRED')last=check;
  if(check.ok){page=candidate;first=check;break;}
  // Do not select a healthy tab while another platform tab shows a challenge.
  if(check.reason==='LOGIN_OR_SECURITY_STILL_VISIBLE'||check.reason==='APP_REPORTS_LOGGED_OUT')
   return check;
 }
 if(!page)return last||{ok:false,reason:'LOGIN_STATE_UNCONFIRMED'};
 await page.waitForTimeout(settleMs);
 // Recheck all tabs; a new login or CAPTCHA page must not be ignored.
 for(const candidate of context.pages()){
  const check=await inspectLoginPage(candidate,platform);
  if(check.reason==='LOGIN_OR_SECURITY_STILL_VISIBLE'||check.reason==='APP_REPORTS_LOGGED_OUT')return check;
 }
 const second=await inspectLoginPage(page,platform);
 return second.ok?{ok:true,evidence:first.evidence,verifiedAt:new Date().toISOString()}:second;
}
export async function waitForManualLogin(context,platform,{timeoutMs=15000,pollMs=750,settleMs=800,onCheck=()=>{}}={}){
 const deadline=Date.now()+Math.max(0,timeoutMs);let last;
 do{
  if(!context.pages().some(page=>!page.isClosed()))return {ok:false,reason:'BROWSER_CLOSED'};
  try{last=await verifyManualLogin(context,platform,{settleMs});}
  catch(error){
   if(!/Execution context was destroyed|Cannot find context|Frame was detached|page has been closed|Target page.*closed/i.test(String(error.message||'')))throw error;
   last={ok:false,reason:'PAGE_CHANGED_DURING_CHECK'};
  }
  onCheck(last);
  if(last.ok||Date.now()>=deadline)return last;
  await new Promise(resolve=>setTimeout(resolve,Math.min(pollMs,Math.max(0,deadline-Date.now()))));
 }while(true);
}
