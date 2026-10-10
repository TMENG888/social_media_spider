import {extractId} from './schema.mjs';
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
export async function commentScope(page,id) {
 // A search card remains in the DOM behind a modal. Never collect or scroll
 // its hidden/background comments when the site's click opened a modal.
 const modal=page.locator('[data-e2e="modal-video-container"]');
 for(let i=0;i<await modal.count();i++)if(await modal.nth(i).isVisible()){
  const modalId=new URL(page.url()).searchParams.get('modal_id');
  if(modalId&&modalId!==id)throw new Error('COMMENTS_POST_CONTEXT_MISMATCH');
  return modal.nth(i);
 }
 return page.locator('.search-result-card').filter({has:page.locator(`[data-e2e-vid="${id}"]`)});
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
export async function assertAccess(page) {
 if(page.isClosed())throw new Error('STOP_BROWSER_CLOSED');
 const text=await page.locator('body').innerText({timeout:5000});
 if(/请完成.*验证|拖动.*滑块|安全验证|验证码验证|操作频繁|访问过于频繁|暂时无法浏览/.test(text))throw new Error('STOP_PLATFORM_RESTRICTION：需要人工处理，不自动重试');
 if(/登录后即可搜索|登录后查看更多|登录后查看评论/.test(text))throw new Error('STOP_LOGIN_REQUIRED：请人工登录');
}
export async function selectLatest(page,observer,keyword) {
 const start=Date.now();
 await assertAccess(page);
 const single=page.getByText('单列',{exact:true});
 await single.last().click({timeout:10000});
 const filter=page.getByText('筛选',{exact:true});
 await filter.last().hover({timeout:10000});
 const latest=page.getByText('最新发布',{exact:true});
 await latest.last().click({timeout:10000});
 // Confirm the actual UI-triggered request, not just a successful click.
 for(let i=0;i<20;i++){
  await assertAccess(page);await observer.flush();
  if(observer.searchRequests.some(r=>r.at>=start&&r.latest&&(!r.keyword||r.keyword===keyword)))return {at:start,confirmed:true};
  await pause(500);
 }
 throw new Error('STOP_LATEST_SORT_UNCONFIRMED：未观察到最新排序请求，保留断点');
}
export async function visibleCards(page) {
 const singles=await page.locator('.search-result-card').evaluateAll(cards=>cards.filter(c=>c.getClientRects().length).map(c=>({noteId:c.querySelector('[data-e2e-vid]')?.getAttribute('data-e2e-vid'),text:c.innerText})).filter(c=>/^\d{15,22}$/.test(c.noteId||'')));
 if(singles.length)return singles.map(c=>({...c,url:`https://www.douyin.com/video/${c.noteId}`}));
 return page.locator('a[href*="/video/"],a[href*="/note/"],a[href*="modal_id="]').evaluateAll(anchors=>anchors.filter(a=>a.getClientRects().length).map(a=>({url:a.href,text:a.innerText})) ).then(rows=>{
  const seen=new Set();return rows.map(r=>({...r,noteId:extractId(r.url)})).filter(r=>r.noteId&&!seen.has(r.noteId)&&seen.add(r.noteId));
 });
}
export async function openCard(page,note) {
 const single=page.locator(`.search-result-card [data-e2e-vid="${note.noteId}"]`);
 if(await single.count()){
  const player=single.first();
  await player.evaluate(el=>el.scrollIntoView({block:'center',inline:'nearest'}));
  const box=await player.boundingBox();if(box)await page.mouse.move(box.x+box.width/2,box.y+box.height/2);
  await pause(1200);await assertAccess(page);
  const card=page.locator('.search-result-card').filter({has:page.locator(`[data-e2e-vid="${note.noteId}"]`)});
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
 const links=page.locator(`a[href*="${note.noteId}"]`);
 for(let i=0;i<await links.count();i++)if(await links.nth(i).isVisible()){
  await links.nth(i).click({timeout:10000});await pause(1500);await assertAccess(page);return;
 }
 throw new Error('SEARCH_CARD_NOT_VISIBLE：重新扫描当前搜索结果，不直接打开详情地址');
}
export async function restoreSearch(page,keyword,noteId=null) {
 // Normal details close in place. Never visit an author or reload search here.
 if(noteId&&!new URL(page.url()).searchParams.has('modal_id')){
  const card=page.locator('.search-result-card').filter({has:page.locator(`[data-e2e-vid="${noteId}"]`)});
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
 const url=new URL(page.url());
 if(!url.pathname.startsWith('/search/')||decodeURIComponent(url.pathname.slice('/search/'.length))!==keyword||url.searchParams.has('modal_id'))throw new Error('STOP_SEARCH_CONTEXT_LOST：详情关闭未恢复原检索页');
 if(!(await visibleCards(page)).length)throw new Error('STOP_SEARCH_CONTEXT_LOST：原检索列表不可见');
}
export function commentRepairPlan(prior,post){
 const audit=prior?.audit?.comments,rows=prior?.comments;
 if(prior?.post?.文章id!==post.文章id||Number(prior.post.文章评论数)!==Number(post.文章评论数)||audit?.rootEnd!==true||!(audit.pages>0)||!Array.isArray(rows)||rows.length<Number(audit.collected)||!audit.missingReplyRoots?.length)return null;
 const roots=[...new Set(audit.missingReplyRoots.map(String))];
 if(roots.some(id=>!rows.some(c=>c.评论id===id&&c.文章id===post.文章id&&Number(c.评论回复数)>0)))return null;
 return {rootIds:roots,rows,audits:prior.commentAudits||[],pages:audit.pages};
}
export async function collectComments(page,observer,post,{shouldStop,maxRounds=0,priorResult=null}={}) {
 const id=post.文章id;
 if(post.文章评论数!=null&&Number(post.文章评论数)===0)return {rows:[],audit:{status:'reported_zero',complete:true,reported:0}};
 const start=Date.now();
 const repair=commentRepairPlan(priorResult,post);
 if(repair)console.log(`[评论精准恢复] ${id}：保留${repair.rows.length}条及${repair.pages}页主分页结束证据，仅补验${repair.rootIds.length}个缺口回复线程`);
 let zeroGrowth=0,lastCount=-1,lastScroll=null,round=0,lastProgressAt=0;
 const scope=await commentScope(page,id);
 const existingPanel=scope.locator('[data-e2e="comment-list"],[data-e2e="comment-list-container"]');
 let panelOpen=false;for(let i=0;i<await existingPanel.count();i++)if(await existingPanel.nth(i).isVisible()){panelOpen=true;break;}
 const {commentFromRaw,commentAuditFromRaw}=await import('./douyin-data.mjs');
 try{
 if(!panelOpen)await clickCommentControl(page,scope);
 while(true){
  if(await shouldStop?.())throw new Error('STOP_REQUESTED：评论分页断点保留');
  await assertAccess(page);await pause(1200);await observer.flush();
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
  const repliesComplete=replyRoots.every(replyComplete);
  if(Date.now()-lastProgressAt>=30000){console.log(`[评论进度] ${id}：已取得${raw.length}条，页面统计${post.文章评论数}；主分页${roots.length}页，主分页结束=${rootEnd}，回复结束=${repliesComplete}`);lastProgressAt=Date.now();}
  if(rootEnd&&repliesComplete&&!expanded){
   const rows=new Map((repair?.rows||[]).map(c=>[c.评论id,c]));for(const c of raw)rows.set(String(c.cid),commentFromRaw(c,post,c.reply_id&&String(c.reply_id)!=='0'?String(c.reply_id):null));
   const audits=new Map((repair?.audits||[]).map(c=>[c.comment_id,c]));for(const c of raw)audits.set(String(c.cid),commentAuditFromRaw(c,c.reply_id&&String(c.reply_id)!=='0'?String(c.reply_id):null));
   return {rows:[...rows.values()],commentAudits:[...audits.values()],audit:{status:'browser_pages_exhausted',complete:true,reported:post.文章评论数,collected:rows.size,pages:repair?.pages||roots.length,rootEnd:true,resumedRootEnd:!!repair,repairRootIds:repair?.rootIds||[],collectionStartedAt:start}};
  }
  const panel=scope.locator('[data-e2e="comment-list"],[data-e2e="comment-list-container"]');
  let target=null;for(let i=0;i<await panel.count();i++)if(await panel.nth(i).isVisible()){target=panel.nth(i);break;}
  if(!target)throw Object.assign(new Error('COMMENTS_PANEL_NOT_VISIBLE：禁止滚动整个搜索页冒充评论分页'),{partialComments:raw.map(c=>commentFromRaw(c,post)),partialCommentAudits:raw.map(c=>commentAuditFromRaw(c,c.reply_id&&String(c.reply_id)!=='0'?String(c.reply_id):null))});
  const position=await target.evaluate(el=>({top:el.scrollTop,height:el.scrollHeight,viewport:el.clientHeight}));
  // Long comments/reply blocks can require many scrolls before the next page
  // loads. Moving through existing content is real progress, not stagnation.
  const moved=lastScroll&&(Math.abs(position.top-lastScroll.top)>1||position.height!==lastScroll.height);
  zeroGrowth=raw.length===lastCount&&!moved&&!expanded?zeroGrowth+1:0;
  lastCount=raw.length;lastScroll=position;round++;
  if(zeroGrowth>=8||(maxRounds>0&&round>=maxRounds))throw Object.assign(new Error(`COMMENTS_INCOMPLETE：页面声明${post.文章评论数}条，已获取${raw.length}条，分页尚未确认结束`),{partialComments:raw.map(c=>commentFromRaw(c,post)),partialCommentAudits:raw.map(c=>commentAuditFromRaw(c,c.reply_id&&String(c.reply_id)!=='0'?String(c.reply_id):null)),commentAudit:{status:'incomplete',complete:false,reported:post.文章评论数,collected:raw.length,rootEnd,pages:repair?.pages||roots.length,missingReplyRoots:replyRoots.filter(c=>!replyComplete(c)).map(c=>String(c.cid)),scroll:position}});
  // A large wheel delta chains from a short sidebar into the search list,
  // activating the next video. Native element scrolling confines movement
  // to this post's comment scrollport and emits its normal scroll events.
  await target.evaluate(el=>el.scrollBy({top:Math.max(80,Math.min(400,el.clientHeight*.8)),behavior:'smooth'}));
 }
 }catch(error){
  // All failures, including an ordinary locator timeout, retain observations
  // already obtained. Never replace a partially collected thread with [].
  const raw=[...observer.comments.values()].filter(c=>String(c.aweme_id)===id);
  error.partialComments??=raw.map(c=>commentFromRaw(c,post,c.reply_id&&String(c.reply_id)!=='0'?String(c.reply_id):null));
  error.partialCommentAudits??=raw.map(c=>commentAuditFromRaw(c,c.reply_id&&String(c.reply_id)!=='0'?String(c.reply_id):null));
  error.commentAudit??={status:'incomplete',complete:false,reported:post.文章评论数,collected:raw.length};
  throw error;
 }
}
