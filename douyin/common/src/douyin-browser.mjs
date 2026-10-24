import {extractId} from './schema.mjs';
import {commentPause,waitForPacing} from './collection-pacing.mjs';
import {aggregateCommentThreads,commentNodesFromResult} from './comment-threads.mjs';
import {searchScrollDom} from './search-scroll.mjs';
import {assertPlatformAccess,guardedPlatformAction} from './platform-access.mjs';
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function searchCard(page,id){
 if(!/^\d{15,22}$/.test(id||''))throw new Error('SEARCH_CARD_ID_INVALID');
 // Locators must keep resolving the ID when a virtual list inserts/reorders
 // cards during scroll/hover. A snapshot's numeric cardIndex is diagnostics only.
 const blocked='[data-e2e="comment-list"],[data-e2e="comment-list-container"],[data-e2e="modal-video-container"],nav,aside';
 const cards=page.locator(`.search-result-card:visible:not(:is(${blocked}) *)`);
 const players=page.locator(`[data-e2e-vid="${id}"]:not(:is(${blocked}) *)`);
 const media=page.locator(`.search-result-card[data-e2e-vid="${id}"]:visible:not(:is(${blocked}) *)`).or(cards.filter({has:players,hasNot:page.locator('.search-result-card')}));
 if(await media.count())return media.first();
 const links=[];
 for(const origin of ['', 'https://www.douyin.com','https://douyin.com','http://www.douyin.com','http://douyin.com']){
  for(const kind of ['video','note']){
   const url=`${origin}/${kind}/${id}`;
   links.push(`a[href="${url}"]`,`a[href="${url}/"]`,`a[href^="${url}?"]`,`a[href^="${url}/?"]`,`a[href^="${url}#"]`);
  }
  const prefix=origin?`[href^="${origin}/"]`:'[href^="/"]:not([href^="//"])';
  for(const query of [`[href$="?modal_id=${id}"]`,`[href$="&modal_id=${id}"]`,`[href*="?modal_id=${id}&"]`,`[href*="&modal_id=${id}&"]`])links.push(`a${prefix}${query}`);
 }
 // Other players and comment references cannot identify a link-only card.
 return page.locator(`.search-result-card:not([data-e2e-vid]):visible:not(:is(${blocked}) *)`).filter({has:page.locator(`:is(${links.join(',')}):not(:is(${blocked}) *)`),hasNot:page.locator('[data-e2e-vid]')}).filter({hasNot:page.locator('.search-result-card')}).first();
}
export async function commentScope(page,id) {
 // A search card remains in the DOM behind a modal. Never collect or scroll
 // its hidden/background comments when the site's click opened a modal.
 const modal=page.locator('[data-e2e="modal-video-container"]');
 for(let i=0;i<await modal.count();i++)if(await modal.nth(i).isVisible()){
  const modalId=new URL(page.url()).searchParams.get('modal_id');
  if(modalId&&modalId!==id)throw new Error('COMMENTS_POST_CONTEXT_MISMATCH');
  return modal.nth(i);
 }
 return searchCard(page,id);
}
export async function clickCommentControl(page,scope,{timeoutMs=4000}={}) {
 const controls=scope.locator('[data-e2e="feed-comment-icon"],[data-e2e="video-comment-icon"],[data-e2e="comment-icon"]');
 let lastError;
 for(let attempt=0;attempt<2;attempt++){
  for(let i=0;i<await controls.count();i++){
   const control=controls.nth(i);if(!await control.isVisible())continue;
   try{
    // Single-column players can overlap a scrolled action rail. Bring the
    // actual control to the viewport centre, reveal hover controls, and retain
    // normal hit testing. Never force-click through an overlay/video.
    await control.evaluate(el=>el.scrollIntoView({block:'center',inline:'nearest'}));
    const box=await control.boundingBox();
    if(box)await page.mouse.move(box.x+box.width/2,box.y+box.height/2);
    await control.click({timeout:timeoutMs,noWaitAfter:true});return;
   }catch(e){lastError=e;await assertAccess(page);}
  }
  if(attempt===0)await pause(800); // Allow the active player's action rail to mount.
 }
 if(lastError)throw Object.assign(new Error(`COMMENTS_CONTROL_OBSCURED：当前帖子的评论按钮无法正常点击：${lastError.message}`),{cause:lastError});
 throw new Error('COMMENTS_CONTROL_NOT_FOUND：未定位当前帖子的评论入口，不等待错误面板');
}
export const searchUrl=keyword=>`https://www.douyin.com/search/${encodeURIComponent(keyword)}`;
export function searchPageKeyword(url){
 try{
  const u=new URL(url),route=u.pathname.match(/^\/(?:jingxuan\/)?search\/(.+)$/);
  return /(^|\.)douyin\.com$/.test(u.hostname)&&route&&!u.searchParams.has('modal_id')?decodeURIComponent(route[1]):null;
 }catch{return null;}
}
function searchPageMatches(url,keyword){
 return searchPageKeyword(url)===keyword;
}
function searchRequestKind(request,keyword){
 try{
  const u=new URL(request.url());if(!/(^|\.)douyin\.com$/.test(u.hostname))return null;
  if(request.isNavigationRequest()&&searchPageMatches(u.href,keyword))return 'search_document';
  if(!/\/general\/search(?:\/|$)/.test(u.pathname))return null;
  let value=u.searchParams.get('keyword');
  if(value==null){const body=request.postData()||'';try{value=JSON.parse(body).keyword;}catch{value=new URLSearchParams(body).get('keyword');}}
  return value===keyword?'search_api':null;
 }catch{return null;}
}
async function visibleSearchControl(groups,{shouldStop,timeoutMs,errorCode}){
 const deadline=Date.now()+timeoutMs;
 do{
  await waitForPacing(0,{shouldStop});
  for(const group of groups){
   const visible=[];
   for(let i=0;i<await group.count();i++){const control=group.nth(i);if(await control.isVisible()&&await control.isEnabled())visible.push(control);}
   if(visible.length===1)return visible[0];
   if(visible.length>1)throw new Error(`${errorCode}：存在多个可见控件，禁止猜测点击`);
  }
  await waitForPacing(Math.min(200,Math.max(0,deadline-Date.now())),{shouldStop});
 }while(Date.now()<deadline);
 throw new Error(`${errorCode}：未找到唯一可见的搜索控件，保留断点`);
}
export async function dismissRememberLoginPrompt(page,{shouldStop,observation}={}){
 await waitForPacing(0,{shouldStop});await assertAccess(page);
 // This optional site prompt is not a login/CAPTCHA gate. Only cancel the
 // specifically observed prompt; never save credentials or remove a mask.
 const dialog=page.locator('#trust-logout-dialog');
 if(await dialog.count()!==1||!await dialog.isVisible())return false;
 if(!/是否保存登录信息/.test(await dialog.innerText()))return false;
 const cancel=dialog.getByText('取消',{exact:true});
 if(await cancel.count()!==1||!await cancel.isVisible()||!await cancel.isEnabled())return false;
 await cancel.click({timeout:4000,noWaitAfter:true});
 await dialog.waitFor({state:'hidden',timeout:4000});
 await waitForPacing(0,{shouldStop});await assertAccess(page);
 if(observation)observation.optionalLoginPromptCancelled=true;
 console.log('[搜索弹窗] 已正常点击“取消”关闭保存登录信息提示；未操作登录或安全验证');
 return true;
}
async function searchUiAction(page,action,options){
 await dismissRememberLoginPrompt(page,options);
 try{return await guardedPlatformAction(page,'抖音',action,{report:accessIncidentReporter});}
 catch(error){
  // Handle a prompt mounted between the precheck and the ordinary click.
  // Unknown overlays and genuine security gates remain intact.
  if(await dismissRememberLoginPrompt(page,options))return guardedPlatformAction(page,'抖音',action,{report:accessIncidentReporter});
  throw error;
 }
}
async function searchFromInput(page,keyword,{shouldStop,timeoutMs,settleMs,typingDelayMs,observation}){
 await waitForPacing(0,{shouldStop});
 if(page.isClosed())throw new Error('STOP_BROWSER_CLOSED');
 let bootstrap=false;
 try{bootstrap=!/(^|\.)douyin\.com$/.test(new URL(page.url()).hostname);}catch{bootstrap=true;}
 if(!bootstrap){
  try{await assertAccess(page);}catch(error){
   if(!/^STOP_SEARCH_GATEWAY_ERROR/.test(error.message))throw error;
   bootstrap=true;observation.bootstrapReason='gateway_document';
  }
 }
 if(bootstrap){
  // Only bootstrap the normal site home. Search URLs are NEVER opened here,
  // including gateway recovery. Login/verification protections stay intact.
  observation.stage='home';
  const response=await page.goto('https://www.douyin.com/',{waitUntil:'domcontentloaded',timeout:timeoutMs});
  observation.homeHttpStatus=response?.status()??null;
  await waitForPacing(settleMs,{shouldStop});
  await assertAccess(page);
  if([502,503,504].includes(observation.homeHttpStatus))throw new Error('STOP_SEARCH_GATEWAY_ERROR：网站首页网关响应异常');
 }
 await assertAccess(page);observation.stage='search_input';
 let inputVerified=false;observation.inputAttempts=[];
 // The real home page can hydrate/remount after its input becomes visible.
 // Re-resolve and retype at most once if hydration dropped characters. Never
 // click search with a truncated word, and never turn this into submit retries.
 for(let attempt=0;attempt<2;attempt++){
  const input=await visibleSearchControl([
   page.locator('[data-e2e="searchbar-input"]'),
   page.locator('input[name="keyword"],input[placeholder*="搜索"]'),
  ],{shouldStop,timeoutMs,errorCode:'STOP_SEARCH_INPUT_UNAVAILABLE'});
  await searchUiAction(page,async()=>{
   await input.click({timeout:Math.min(timeoutMs,4000)});await input.fill('',{timeout:Math.min(timeoutMs,4000)});
  },{shouldStop,observation});
  if(await input.inputValue()!=='')throw new Error('STOP_SEARCH_INPUT_NOT_CLEARED');
  observation.inputCleared=true;
  await waitForPacing(120,{shouldStop});
  await input.pressSequentially(keyword,{delay:typingDelayMs,timeout:timeoutMs});
  await waitForPacing(250,{shouldStop});await assertAccess(page);
  inputVerified=await input.inputValue()===keyword;
  observation.inputAttempts.push({attempt:attempt+1,matched:inputVerified});
  if(inputVerified)break;
  if(attempt===0)await waitForPacing(500,{shouldStop});
 }
 if(!inputVerified)throw new Error('STOP_SEARCH_INPUT_MISMATCH');
 const button=await visibleSearchControl([
  page.locator('[data-e2e="searchbar-button"]'),
  page.getByRole('button',{name:'搜索',exact:true}),
  page.getByText('搜索',{exact:true}),
 ],{shouldStop,timeoutMs,errorCode:'STOP_SEARCH_SUBMIT_UNAVAILABLE'});
 const requests=new Map();let responseEvidence=null,gatewayStatus=null;
 // Track requests created AFTER input and before the normal search click.
 // A late response from a previous keyword (even the same word) is not proof.
 const onRequest=request=>{const kind=searchRequestKind(request,keyword);if(kind)requests.set(request,kind);};
 const onResponse=response=>{
  const kind=requests.get(response.request());if(!kind)return;
  const status=response.status();observation.httpStatus=status;
  if([502,503,504].includes(status))gatewayStatus=status;
  if(status>=200&&status<300)responseEvidence={kind,httpStatus:status};
 };
 page.on('request',onRequest);page.on('response',onResponse);
 try{
  observation.stage='search_submit';observation.submittedAt=new Date().toISOString();
  await waitForPacing(0,{shouldStop});
  await searchUiAction(page,()=>button.click({timeout:Math.min(timeoutMs,4000),noWaitAfter:true}),{shouldStop,observation});
  const deadline=Date.now()+timeoutMs;
  do{
   await waitForPacing(0,{shouldStop});await assertAccess(page);
   if(gatewayStatus){observation.httpStatus=gatewayStatus;throw new Error('STOP_SEARCH_GATEWAY_ERROR：本次搜索响应网关异常');}
   if(responseEvidence&&searchPageMatches(page.url(),keyword)){
    // Re-resolve the input: a normal full document navigation may remount it.
    const current=page.locator('[data-e2e="searchbar-input"],input[name="keyword"],input[placeholder*="搜索"]').filter({visible:true});
    if(await current.count()===1&&await current.inputValue()===keyword){
     await waitForPacing(settleMs,{shouldStop});await assertAccess(page);
     if(gatewayStatus)throw new Error('STOP_SEARCH_GATEWAY_ERROR：本次搜索响应网关异常');
     if(!searchPageMatches(page.url(),keyword))throw new Error('STOP_SEARCH_CONTEXT_LOST');
     observation.response=responseEvidence;observation.httpStatus=responseEvidence.httpStatus;observation.stage='verified';return;
    }
   }
   await waitForPacing(Math.min(200,Math.max(0,deadline-Date.now())),{shouldStop});
  }while(Date.now()<deadline);
  throw new Error('STOP_SEARCH_SUBMIT_UNCONFIRMED：未确认新词搜索框、结果页和本次搜索响应，禁止沿用旧结果');
 }finally{page.off('request',onRequest);page.off('response',onResponse);}
}
export async function navigateSearch(page,keyword,{shouldStop,timeoutMs=45000,settleMs=2500,typingDelayMs=65,retryDelaysMs=[15000,30000],allowManualLogin=false,onObservation=()=>{}}={}) {
 // Ordinary UI search only, within the existing lease and bounded retry budget.
 // No direct search/article requests, proxy changes or CAPTCHA retries.
 if(!Array.isArray(retryDelaysMs)||retryDelaysMs.length>2||retryDelaysMs.some(ms=>!Number.isFinite(ms)||ms<0||ms>60000))throw new Error('SEARCH_GATEWAY_RETRY_BUDGET_INVALID');
 if(typeof keyword!=='string'||!keyword.trim())throw new Error('SEARCH_KEYWORD_INVALID');
 if(!Number.isFinite(timeoutMs)||timeoutMs<=0||!Number.isFinite(typingDelayMs)||typingDelayMs<0||typingDelayMs>1000)throw new Error('SEARCH_UI_OPTIONS_INVALID');
 const audit={keyword,method:'search_box',attempts:[],maxRetries:retryDelaysMs.length};
 for(let attempt=0;attempt<=retryDelaysMs.length;attempt++){
  await waitForPacing(0,{shouldStop});
  const observation={attempt:attempt+1,at:new Date().toISOString(),httpStatus:null,method:'search_box'};
  try{
   await searchFromInput(page,keyword,{shouldStop,timeoutMs,settleMs,typingDelayMs,observation});
   console.log(`[搜索框检索] ${keyword}：已清空输入并点击搜索，结果页与本次HTTP响应已确认；数据和排序另行核验`);
   observation.status='ready';observation.readiness='transport_only';audit.attempts.push(observation);onObservation(audit);return audit;
  }catch(error){
   if(allowManualLogin&&/^STOP_LOGIN_REQUIRED(?:：|:|$)/.test(String(error.message))){
    observation.status='awaiting_manual_login';audit.awaitingManualLogin=true;audit.attempts.push(observation);onObservation(audit);return audit;
   }
   const gateway=/^STOP_SEARCH_GATEWAY_ERROR(?:：|:|$)/.test(String(error.message));
   const uiTimeout=error.name==='TimeoutError'&&['search_input','search_submit'].includes(observation.stage);
   observation.status=gateway?'gateway_error':uiTimeout?'ui_timeout':'stopped';observation.error=String(error.message);
   audit.attempts.push(observation);onObservation(audit);
   if((!gateway&&!uiTimeout)||attempt===retryDelaysMs.length)throw Object.assign(error,{searchNavigation:audit});
   console.warn(`[搜索有限退避] ${keyword}：第${attempt+1}次${gateway?'网关错误':'控件超时'}，等待${retryDelaysMs[attempt]/1000}秒后通过搜索框重试原词；最多${retryDelaysMs.length}次，不强制穿透遮挡`);
   await waitForPacing(retryDelaysMs[attempt],{shouldStop});
  }
 }
}
let accessIncidentReporter=null;
export function setAccessIncidentReporter(reporter){accessIncidentReporter=reporter;}
export async function assertAccess(page) {
 await assertPlatformAccess(page,'抖音',{report:accessIncidentReporter});
}
async function searchCheck(page,shouldStop){
 if(await shouldStop?.())throw new Error('STOP_REQUESTED：搜索列表准备期间已安全停止');
 await assertAccess(page);
}
export async function searchEndUi(page,keyword){
 if(!searchPageMatches(page.url(),keyword))return {visible:false};
 const markers=page.getByText(/^(?:暂时没有更多了|没有更多了|暂无搜索结果|没有找到相关结果)$/,{exact:true});
 for(let i=0;i<await markers.count();i++){
  const marker=markers.nth(i);if(!await marker.isVisible())continue;
  const evidence=await marker.evaluate(el=>{
   // A comment-thread end or a caption quoting the words is not a search end.
   if(el.closest('.search-result-card,[data-e2e="modal-video-container"],[data-e2e="comment-list"],[data-e2e="comment-list-container"]'))return {visible:false};
   const r=el.getBoundingClientRect();
   return {visible:r.width>0&&r.height>0&&r.bottom>0&&r.top<window.innerHeight,text:el.innerText.trim()};
  });
  if(evidence.visible)return evidence;
 }
 return {visible:false};
}
export async function scrollSearchResults(page,{keyword}={}){
 const current=searchPageKeyword(page.url());
 if(current===null||(keyword!=null&&current!==keyword))throw new Error('STOP_SEARCH_SCROLL_CONTEXT_LOST');
 await assertAccess(page);
 let state=await page.evaluate(searchScrollDom);
 if(state.reason==='detail_modal_open')throw new Error('STOP_SEARCH_SCROLL_MODAL_OPEN');
 if(!state.available)return state;
 // Sorting used to leave the pointer on the search input. A wheel there can
 // scroll suggestions instead of results. Escape/blur never submits a search.
 await page.mouse.move(state.point.x,state.point.y);
 await page.keyboard.press('Escape');
 await page.evaluate(()=>{
  const active=document.activeElement;
  if(active?.matches('[data-e2e="searchbar-input"],input,textarea,[contenteditable="true"]'))active.blur();
 });
 state=await page.evaluate(searchScrollDom,{advance:true});
 // These are movement diagnostics, never independent search-end evidence.
 return state;
}
export async function waitForInitialSearch(page,observer,{shouldStop,timeoutMs=45000,pollMs=500,after=0,keyword:expectedKeyword,documentVerified=false}={}){
 // During hydration the layout controls can accept a click yet do nothing.
 // Observe actual search data before attempting the layout switch.
 const started=Date.now(),deadline=started+timeoutMs;let waitingLogged=false;
 const current=p=>p.keyword===searchPageKeyword(page.url())&&(!after||p.requestStartedAt>=after);
 const diagnostic=async()=>({keyword:searchPageKeyword(page.url()),elapsedMs:Date.now()-started,
  timeoutMs,parsedPosts:observer.awemes.size,
  matchingSearchPages:(observer.searchPages||[]).filter(current).length,
  matchingSearchItems:(observer.searchPages||[]).filter(current).reduce((n,p)=>n+p.noteIds.length,0),
  observerErrorCodes:(observer.failures||[]).slice(-3).map(e=>/^[A-Z_]{3,80}$/.test(e)?e:'OBSERVER_ERROR_REDACTED'),
  responseFailures:(observer.searchFailures||[]).filter(current).map(p=>({
   http:p.http??null,statusCode:p.statusCode??null,error:p.error??null,
  })).slice(-3),
  // Counts and iframe origins only: no cookies, body text, query or QR data.
  dom:await page.evaluate(()=>{
   const shown=el=>{const b=el.getBoundingClientRect();return b.width>0&&b.height>0&&getComputedStyle(el).visibility!=='hidden'&&getComputedStyle(el).display!=='none';};
   const cards=[...document.querySelectorAll('.search-result-card')];
   return {readyState:document.readyState,mountedCards:cards.length,visibleCards:cards.filter(shown).length,
    visibleFrames:[...document.querySelectorAll('iframe')].filter(shown).slice(0,8).map(el=>{
     const b=el.getBoundingClientRect();let origin='unknown';try{origin=new URL(el.getAttribute('src')||'about:blank',location.href).origin;}catch{}
     return {origin,width:Math.round(b.width),height:Math.round(b.height)};
    })};
  }).catch(()=>({unavailable:true}))});
 do{
  await searchCheck(page,shouldStop);await observer.flush();
  const keyword=searchPageKeyword(page.url());
  if(expectedKeyword!=null&&keyword!==expectedKeyword)throw new Error('STOP_SEARCH_CONTEXT_LOST：搜索准备期间关键词改变');
  const failure=(observer.searchFailures||[]).filter(current).at(-1);
  const pages=(observer.searchPages||[]).filter(current),success=pages.at(-1);
  if(failure&&(!success||failure.at>success.at)){
   const details=await diagnostic();
   console.warn('[搜索响应失败] '+JSON.stringify(details));
   throw Object.assign(new Error('SEARCH_INITIAL_RESPONSE_FAILED：搜索响应失败，非空结果结束；保留断点'),{searchReadiness:details});
  }
  const hasPosts=after?pages.some(p=>p.noteIds.length>0):observer.awemes.size>0;
  const cards=(await visibleCards(page)).length;
  if((hasPosts||cards)&&(!after||success||(documentVerified&&cards)))return {hasPosts:true};
  if(keyword!==null&&pages.some(p=>p.hasMore===false&&p.noteIds.length===0)&&(await searchEndUi(page,keyword)).visible)return {hasPosts:false};
  if(!waitingLogged&&Date.now()-started>=20000){
   waitingLogged=true;console.log('[搜索加载等待] '+JSON.stringify(await diagnostic()));
  }
  await pause(pollMs);
 }while(Date.now()<deadline);
 const details=await diagnostic();console.warn('[搜索加载超时] '+JSON.stringify(details));
 throw Object.assign(new Error('SEARCH_INITIAL_RESULTS_NOT_READY：搜索内容尚未加载，禁止把空DOM当年度完成'),{searchReadiness:details});
}
export async function ensureSingleColumn(page,{shouldStop,timeoutMs=10000,pollMs=500,onDiagnostic}={}){
 const observe=async(stage,details={},error=null)=>{try{await onDiagnostic?.({stage,details,error});}catch{/* Diagnostics never change the collection decision. */}};
 // The same mounted, unambiguous cards we can collect must establish layout
 // readiness. Image-only results and root-level player IDs have no descendant
 // player. Grid fallback anchors alone still cannot certify single-column UI.
 const ready=async()=>(await visibleCards(page)).some(row=>Number.isInteger(row.cardIndex));
 await searchCheck(page,shouldStop);
 if(await ready()){await observe('layout_already_ready');return;}
 // At most two normal UI clicks, never force-click a loading/verification
 // overlay, never change the search tab to "video" and drop image posts.
 for(let attempt=0;attempt<2;attempt++){
  await searchCheck(page,shouldStop);
  await observe('layout_click_started',{attempt:attempt+1,selector:'getByText(单列,exact).last'});
  try{await page.getByText('单列',{exact:true}).last().click({timeout:Math.min(10000,timeoutMs)});}
  catch(error){
   await observe('layout_click_failed',{attempt:attempt+1},error);
   await searchCheck(page,shouldStop);if(await ready())return;
   if(attempt===1)throw Object.assign(new Error('STOP_SEARCH_LAYOUT_UNCONFIRMED：单列控件无法正常点击，保留断点'),{cause:error});
  }
  const deadline=Date.now()+timeoutMs;
  do{
   await searchCheck(page,shouldStop);
   if(await ready()){await observe('layout_verified',{attempt:attempt+1});return;}
   await pause(pollMs);
  }while(Date.now()<deadline);
 }
 const error=new Error('STOP_SEARCH_LAYOUT_UNCONFIRMED：单列切换未生效，未发现可读取的帖子卡片；保留断点');
 await observe('layout_not_confirmed',{},error);
 throw error;
}
export async function selectLatest(page,observer,keyword,options={}) {
 const readiness=await waitForInitialSearch(page,observer,{...options,keyword});
 if(!(await searchEndUi(page,keyword)).visible||readiness.hasPosts)await ensureSingleColumn(page,options);
 const start=Date.now();
 const filter=page.getByText('筛选',{exact:true});
 await filter.last().hover({timeout:10000});
 const latest=page.getByText('最新发布',{exact:true});
 await latest.last().click({timeout:10000});
 // Confirm the actual UI-triggered request, not just a successful click.
 for(let i=0;i<20;i++){
  await searchCheck(page,options.shouldStop);await observer.flush();
  if(observer.searchRequests.some(r=>r.at>=start&&r.latest&&(!r.keyword||r.keyword===keyword))){
   // Sorting remounts the list. Do not acknowledge the layout from an old
   // click before the new search has rendered its actual single-column rows.
   // Do not hover the search input: that opens suggestions over the feed and
   // leaves subsequent wheel events targeting the wrong scrollport.
   await page.keyboard.press('Escape');
   await pause(800);
   const empty=observer.searchPages?.some(p=>p.at>=start&&p.keyword===keyword&&p.latest&&p.hasMore===false&&p.noteIds.length===0)&&(await searchEndUi(page,keyword)).visible;
   if(!empty)await ensureSingleColumn(page,options);
   const cards=await visibleCards(page);
   return {at:start,confirmed:true,layout:empty?'empty':'single',cards:cards.length};
  }
  await pause(500);
 }
 throw new Error('STOP_LATEST_SORT_UNCONFIRMED：未观察到最新排序请求，保留断点');
}

export const SEARCH_PREPARATION_VERSION='douyin-search-readiness-20261021-v1';
function retryableInitialSearch(error){
 if(/^SEARCH_INITIAL_RESULTS_NOT_READY(?:：|:|$)/.test(error.message))return true;
 if(!/^SEARCH_INITIAL_RESPONSE_FAILED(?:：|:|$)/.test(error.message))return false;
 const failure=error.searchReadiness?.responseFailures?.at(-1);
 // HTTP200 with a nonzero application code may be a platform restriction.
 // Never repeatedly submit it as an ordinary loading/transport failure.
 return failure?.statusCode==null&&([502,503,504].includes(failure?.http)||['DOUYIN_RESPONSE_BODY_TIMEOUT'].includes(failure?.error));
}
export async function selectLatestWithRecovery(page,observer,keyword,{after=0,documentVerified=false,shouldStop,
 timeoutMs=45000,pollMs=500,navigationOptions={},retryDelaysMs=[15000,30000],onRecovery=()=>{},onDiagnostic}={}){
 if(!Array.isArray(retryDelaysMs)||retryDelaysMs.length>2||retryDelaysMs.some(ms=>!Number.isFinite(ms)||ms<0||ms>60000))throw new Error('SEARCH_READINESS_RETRY_BUDGET_INVALID');
 const audit={version:SEARCH_PREPARATION_VERSION,keyword,maxRetries:retryDelaysMs.length,attempts:[]};
 for(let attempt=0;attempt<=retryDelaysMs.length;attempt++){
  await searchCheck(page,shouldStop);
  const row={attempt:attempt+1,startedAt:new Date().toISOString()};
  try{
   if(attempt){
    // Start a fresh UI submission of this same word. No direct URL, forced
    // click, cookie clearing, profile restart or task reset.
    const navigation=await navigateSearch(page,keyword,{...navigationOptions,shouldStop,retryDelaysMs:[]});
    after=Date.parse(navigation.attempts.at(-1).submittedAt);row.navigation=navigation;
    documentVerified=navigation.attempts.at(-1).response?.kind==='search_document';
   }
   const prepared=await selectLatest(page,observer,keyword,{after,documentVerified,shouldStop,timeoutMs,pollMs,onDiagnostic});
   row.status='ready';audit.attempts.push(row);audit.exhausted=false;onRecovery(audit);return prepared;
  }catch(error){
   row.status='failed';row.errorCode=String(error.message).split(/[：:]/)[0];
   if(error.searchReadiness)row.readiness=error.searchReadiness;
   audit.attempts.push(row);
   const retry=retryableInitialSearch(error)&&attempt<retryDelaysMs.length;
   audit.exhausted=retryableInitialSearch(error)&&!retry;onRecovery(audit);
   try{await onDiagnostic?.({stage:retry?'search_readiness_retry':'search_preparation_failed',
    details:{version:SEARCH_PREPARATION_VERSION,attempt:attempt+1,retrying:retry,readiness:error.searchReadiness},error});}catch{}
   if(!retry)throw Object.assign(error,{searchPreparationRecovery:audit});
   console.warn(`[搜索加载重试] ${keyword}：第${attempt+1}次未就绪，等待${retryDelaysMs[attempt]/1000}秒后清空搜索框重搜原词；最多${retryDelaysMs.length}次，不把空DOM当完成`);
   await waitForPacing(retryDelaysMs[attempt],{shouldStop});
  }
 }
}
export async function visibleCards(page) {
 const snapshot=await page.locator('.search-result-card').evaluateAll(cards=>{
  const blocked='[data-e2e="comment-list"],[data-e2e="comment-list-container"],[data-e2e="modal-video-container"],nav,aside';
  const valid=id=>/^\d{15,22}$/.test(id||'');
  const visible=el=>{const style=getComputedStyle(el);return el.getClientRects().length>0&&style.display!=='none'&&style.visibility!=='hidden'&&Number(style.opacity)!==0;};
  const linkedId=a=>{
   if(a.closest(blocked)||!visible(a))return null;
   try{const u=new URL(a.href);if(!['www.douyin.com','douyin.com'].includes(u.hostname))return null;
    const id=u.pathname.match(/^\/(?:video|note)\/(\d{15,22})\/?$/)?.[1]||u.searchParams.get('modal_id');return valid(id)?id:null;
   }catch{return null;}
  };
  const rows=[];
  cards.forEach((card,cardIndex)=>{
   if(!visible(card)||card.closest(blocked))return;
   const own=node=>node.closest('.search-result-card')===card&&!node.closest(blocked);
   const players=[card,...card.querySelectorAll('[data-e2e-vid]')].filter(own);
   const ids=[...new Set(players.map(n=>n.getAttribute('data-e2e-vid')).filter(valid))];
   if(!ids.length)ids.push(...new Set([...card.querySelectorAll('a[href]')].filter(own).map(linkedId).filter(Boolean)));
   // One search card must identify one post. Never guess among multiple IDs.
   if(ids.length===1)rows.push({noteId:ids[0],cardIndex,text:card.innerText});
  });
  return {mountedCards:cards.length,rows};
 });
 if(snapshot.mountedCards){const seen=new Set();return snapshot.rows.filter(c=>!seen.has(c.noteId)&&seen.add(c.noteId)).map(c=>({...c,url:`https://www.douyin.com/video/${c.noteId}`}));}
 return page.locator('a[href*="/video/"],a[href*="/note/"],a[href*="modal_id="]').evaluateAll(anchors=>anchors.filter(a=>a.getClientRects().length&&!a.closest('[data-e2e="comment-list"],[data-e2e="comment-list-container"],[data-e2e="modal-video-container"],nav,aside')).map(a=>({url:a.href,text:a.innerText})) ).then(rows=>{
  const seen=new Set();return rows.map(r=>({...r,noteId:extractId(r.url)})).filter(r=>{
   try{return ['www.douyin.com','douyin.com'].includes(new URL(r.url).hostname)&&r.noteId&&!seen.has(r.noteId)&&seen.add(r.noteId);}catch{return false;}
  });
 });
}
export async function openCard(page,note) {
 if(!/^\d{15,22}$/.test(note.noteId||''))throw new Error('SEARCH_CARD_ID_INVALID');
 if(!(await visibleCards(page)).some(row=>row.noteId===note.noteId))throw new Error('SEARCH_CARD_NOT_VISIBLE：重新扫描当前搜索结果，不直接打开详情地址');
 const card=await searchCard(page,note.noteId);
 const single=await card.count()===1&&await card.getAttribute('data-e2e-vid')===note.noteId?card:card.locator(`[data-e2e-vid="${note.noteId}"]`);
 if(await single.count()){
  const player=single.first();
  await player.evaluate(el=>el.scrollIntoView({block:'center',inline:'nearest'}));
  const box=await player.boundingBox();if(box)await page.mouse.move(box.x+box.width/2,box.y+box.height/2);
  await pause(1200);await assertAccess(page);
  // Centre/hover normally activates the inline player. Clicking an already
  // active player opens a modal and leaves the background card mounted.
  const active=card.locator('[data-e2e="feed-active-video"]');
  if(!await active.count()||!await active.first().isVisible()){
   await player.click({timeout:10000});await pause(1500);await assertAccess(page);
  }
  const guide=page.getByText('我知道了',{exact:true});
  if(await guide.count()&&await guide.last().isVisible())await guide.last().click({timeout:3000});
  return;
 }
 const links=(await card.count()?card:page).locator(`a[href*="${note.noteId}"]`);
 for(let i=0;i<await links.count();i++)if(await links.nth(i).isVisible()){
  const eligible=await links.nth(i).evaluate((a,id)=>{
   if(a.closest('[data-e2e="comment-list"],[data-e2e="comment-list-container"],[data-e2e="modal-video-container"],nav,aside'))return false;
   try{const u=new URL(a.href);return ['www.douyin.com','douyin.com'].includes(u.hostname)
    &&(u.pathname.match(/^\/(?:video|note)\/(\d{15,22})\/?$/)?.[1]||u.searchParams.get('modal_id'))===id;}catch{return false;}
  },note.noteId);
  if(!eligible)continue;
  await links.nth(i).click({timeout:10000});await pause(1500);await assertAccess(page);return;
 }
 throw new Error('SEARCH_CARD_NOT_VISIBLE：重新扫描当前搜索结果，不直接打开详情地址');
}
export async function restoreSearch(page,keyword,noteId=null) {
 // Normal details close in place. Never visit an author or reload search here.
 if(noteId&&!new URL(page.url()).searchParams.has('modal_id')){
  const card=await searchCard(page,noteId);
  const comments=card.locator('[data-e2e="comment-list"],[data-e2e="comment-list-container"]');
  let panelOpen=false;for(let i=0;i<await comments.count();i++)if(await comments.nth(i).isVisible()){panelOpen=true;break;}
  if(panelOpen){
   try{
    // Prefer the panel's own close control observed in the real single-column
    // UI, not the video's comment toggle after hundreds of DOM rows mount.
    const closes=card.locator('.comment-header-close-btn');let clicked=false;
    for(let i=0;i<await closes.count();i++)if(await closes.nth(i).isVisible()){
     await closes.nth(i).click({timeout:10000,noWaitAfter:true});clicked=true;break;
    }
    if(!clicked)await clickCommentControl(page,card,{timeoutMs:10000});
   }catch(e){
    await assertAccess(page);await assertSearchContext(page,keyword);
    // An inline comment panel is not a detail navigation. Its optional toggle
    // timing out must not discard a fully collected post or reload the search.
    console.warn('[评论关闭] 控件未完成关闭，但原关键词搜索列表仍可见；保留排序，继续下一张卡片');
   }
  }
  await assertAccess(page);await assertSearchContext(page,keyword);return;
 }
 const close=page.locator('[data-e2e="video-detail-close"],[data-e2e="close-icon"],button[aria-label="关闭"]');
 let clicked=false;
 for(let i=0;i<await close.count();i++)if(await close.nth(i).isVisible()){await close.nth(i).click({timeout:3000});clicked=true;break;}
 if(!clicked)await page.keyboard.press('Escape');
 await pause(800);await assertAccess(page);
 await assertSearchContext(page,keyword);
}
export async function assertSearchContext(page,keyword){
 if(!searchPageMatches(page.url(),keyword))throw new Error('STOP_SEARCH_CONTEXT_LOST：详情关闭未恢复原检索页');
 if(!(await visibleCards(page)).length)throw new Error('STOP_SEARCH_CONTEXT_LOST：原检索列表不可见');
}
export function commentRepairPlan(prior,post){
 const audit=prior?.audit?.comments,rows=prior?.comments;
 if(prior?.post?.文章id!==post.文章id||Number(prior.post.文章评论数)!==Number(post.文章评论数)||audit?.rootEnd!==true||!(audit.pages>0)||!Array.isArray(rows)||commentNodesFromResult(prior).size<Number(audit.raw_comment_count??audit.collected)||!audit.missingReplyRoots?.length)return null;
 const roots=[...new Set(audit.missingReplyRoots.map(String))];
 if(roots.some(id=>!rows.some(c=>c.评论id===id&&c.文章id===post.文章id&&Number(c.评论回复数)>0)))return null;
 return {rootIds:roots,rows,audits:prior.commentAudits||[],pages:audit.pages};
}
export async function collectComments(page,observer,post,{shouldStop,maxRounds=0,priorResult=null,pacingConfig=null}={}) {
 const id=post.文章id;
 if(post.文章评论数!=null&&Number(post.文章评论数)===0)return {rows:[],audit:{status:'reported_zero',complete:true,reported:0}};
 const start=Date.now();
 const repair=commentRepairPlan(priorResult,post);
 if(repair)console.log(`[评论精准恢复] ${id}：保留${repair.rows.length}条及${repair.pages}页主分页结束证据，仅补验${repair.rootIds.length}个缺口回复线程`);
 let zeroGrowth=0,lastCount=-1,lastScroll=null,round=0,lastProgressAt=0;
 const scope=await commentScope(page,id);
 const existingPanel=scope.locator('[data-e2e="comment-list"],[data-e2e="comment-list-container"]');
 let panelOpen=false;for(let i=0;i<await existingPanel.count();i++)if(await existingPanel.nth(i).isVisible()){panelOpen=true;break;}
 const snapshot=(rootComplete=null)=>aggregateCommentThreads([...observer.comments.values()].filter(c=>String(c.aweme_id)===id),post,{priorResult,rootComplete});
 try{
 if(!panelOpen)await clickCommentControl(page,scope);
 while(true){
  if(await shouldStop?.())throw new Error('STOP_REQUESTED：评论分页断点保留');
  await assertAccess(page);
  if(pacingConfig){
   const delay=commentPause(pacingConfig,round);
   if(delay.kind==='comment_batch')console.log(`[评论休息] ${id}：完成${round}轮分页，休息${Math.round(delay.ms/1000)}秒`);
   await waitForPacing(delay.ms,{shouldStop});await assertAccess(page);
  }else await pause(1200);
  await observer.flush();
  // The observer is keyword-scoped. Opening a card may preload its comment
  // page before this function starts; do not discard that real end-page proof.
  const roots=observer.commentPages.filter(p=>p.awemeId===id&&!p.rootId);
  const raw=[...observer.comments.values()].filter(c=>String(c.aweme_id)===id);
  const rootEnd=roots.some(p=>Number(p.hasMore)===0)||!!repair;
  const replyRoots=repair?repair.rootIds.map(cid=>({cid})):raw.filter(c=>Number(c.reply_comment_total)>0&&(!c.reply_id||String(c.reply_id)==='0'));
  // Expand every visible reply control through the site's UI.
  const expand=scope.getByText(/^(?:展开\s*\d+\s*(?:条|个)?\s*回复|展开更多(?:回复)?|查看更多回复)$/,{exact:true});
  let expanded=false;
  // Reply expansion is an in-place action. Do not wait for unrelated scheduled
  // navigation after the click already finished; validate access/context in
  // the following iteration and confirm the actual reply response instead.
  for(let i=0;i<Math.min(await expand.count(),20);i++)if(await expand.nth(i).isVisible()){await expand.nth(i).click({timeout:10000,noWaitAfter:true});expanded=true;await pause(800);break;}
  const replyEnds=observer.commentPages.filter(p=>p.awemeId===id&&p.rootId&&Number(p.hasMore)===0);
  const replyComplete=c=>replyEnds.some(p=>p.rootId===String(c.cid))||observer.embeddedReplyCoverage?.get(`${id}/${c.cid}`)?.complete===true;
  const merged=snapshot(cid=>replyRoots.some(c=>String(c.cid)===cid)?replyComplete({cid}):null);
  const repliesComplete=replyRoots.every(replyComplete)&&merged.orphanCommentIds.length===0&&merged.commentAudits.every(a=>a.thread_complete!==false);
  if(Date.now()-lastProgressAt>=30000){console.log(`[评论进度] ${id}：已取得${raw.length}条，页面统计${post.文章评论数}；主分页${roots.length}页，主分页结束=${rootEnd}，回复结束=${repliesComplete}`);lastProgressAt=Date.now();}
  if(rootEnd&&repliesComplete&&!expanded){
   return {rows:merged.rows,commentAudits:merged.commentAudits,audit:{status:'browser_pages_exhausted',complete:true,aggregation_mode:'comment_thread',aggregation_version:1,reported:post.文章评论数,collected:merged.rawCommentCount,raw_comment_count:merged.rawCommentCount,thread_count:merged.threadCount,pages:repair?.pages||roots.length,rootEnd:true,resumedRootEnd:!!repair,repairRootIds:repair?.rootIds||[],collectionStartedAt:start}};
  }
  const panel=scope.locator('[data-e2e="comment-list"],[data-e2e="comment-list-container"]');
  let target=null;for(let i=0;i<await panel.count();i++)if(await panel.nth(i).isVisible()){target=panel.nth(i);break;}
  if(!target)throw new Error('COMMENTS_PANEL_NOT_VISIBLE：禁止滚动整个搜索页冒充评论分页');
  const position=await target.evaluate(el=>({top:el.scrollTop,height:el.scrollHeight,viewport:el.clientHeight}));
  // Long comments/reply blocks can require many scrolls before the next page
  // loads. Moving through existing content is real progress, not stagnation.
  const moved=lastScroll&&(Math.abs(position.top-lastScroll.top)>1||position.height!==lastScroll.height);
  zeroGrowth=raw.length===lastCount&&!moved&&!expanded?zeroGrowth+1:0;
  lastCount=raw.length;lastScroll=position;round++;
  if(zeroGrowth>=8||(maxRounds>0&&round>=maxRounds))throw Object.assign(new Error(`COMMENTS_INCOMPLETE：页面声明${post.文章评论数}条，已获取${raw.length}条，分页尚未确认结束`),{commentAudit:{status:'incomplete',complete:false,reported:post.文章评论数,rootEnd,pages:repair?.pages||roots.length,missingReplyRoots:[...new Set([...replyRoots.filter(c=>!replyComplete(c)).map(c=>String(c.cid)),...merged.commentAudits.filter(a=>a.thread_complete===false).map(a=>a.comment_id)])],scroll:position}});
  // A large wheel delta chains from a short sidebar into the search list,
  // activating the next video. Native element scrolling confines movement
  // to this post's comment scrollport and emits its normal scroll events.
  await target.evaluate(el=>el.scrollBy({top:Math.max(80,Math.min(400,el.clientHeight*.8)),behavior:'smooth'}));
 }
 }catch(error){
  // All failures, including an ordinary locator timeout, retain observations
  // already obtained. Never replace a partially collected thread with [].
  const partial=snapshot();
  error.partialComments=partial.rows;error.partialCommentAudits=partial.commentAudits;
  error.commentAudit={...error.commentAudit,status:'incomplete',complete:false,reported:post.文章评论数,collected:partial.rawCommentCount,raw_comment_count:partial.rawCommentCount,thread_count:partial.threadCount,aggregation_mode:'comment_thread',aggregation_version:1,orphan_comment_ids:partial.orphanCommentIds,unattached_comments:partial.unattachedComments};
  throw error;
 }
}
