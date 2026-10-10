import {renderedControl, ensureLatestSort, closeDetailToSearch, isKeywordSearchUrl} from './xhs-browser-state.mjs';

export class WebUnavailableStreak {
  constructor(){this.count=0;}
  observe(error){this.count=String(error?.message||error||'').startsWith('STOP_WEB_NOTE_UNAVAILABLE')?this.count+1:0;return this.count;}
  get reached(){return this.count>=3;}
}

export async function dismissWebNoteUnavailable(page,{assertSafe=async()=>{}}={}){
  await assertSafe(page);
  if(!await webNoteUnavailableMessage(page))return true;
  const heading=await renderedControl(page.getByText('当前笔记暂时无法浏览',{exact:true}));
  const dialog=heading?.locator('xpath=ancestor::*[.//*[normalize-space(.)="关闭"]][1]');
  const close=dialog?await renderedControl(dialog.getByText('关闭',{exact:true})):null;
  // A visible button can be stale or covered after returning from the author.
  // A failed click is not proof that the original search page is lost.
  if(close)await close.click({timeout:3000}).catch(()=>{});
  await page.waitForTimeout(300);
  await assertSafe(page);
  return !await webNoteUnavailableMessage(page);
}

export async function recoverWebUnavailableToSearch(page,state,{assertSafe=async()=>{},assertStrict=assertSafe,timeout=45000,log=console.log}={}){
  const dismissed=await dismissWebNoteUnavailable(page,{assertSafe});
  if(!dismissed){
    await assertSafe(page);
    if(!isKeywordSearchUrl(state.searchUrl,state.keyword))throw new Error('STOP_SEARCH_CONTEXT_LOST：原搜索地址无效');
    log(`[死信恢复] ${state.keyword}：提示关闭控件不可用，同页恢复原搜索地址；不重新访问死信帖子`);
    await page.goto(state.searchUrl,{waitUntil:'domcontentloaded',timeout});
    await assertStrict(page);
    await ensureLatestSort(page,state.keyword,{assertSafe:assertStrict,log});
  }
  return closeDetailToSearch(page,state,{timeout,assertSafe:assertStrict,log});
}

export const WEB_NOTE_UNAVAILABLE_PATTERN = /当前笔记暂时无法浏览/;

export async function webNoteUnavailableMessage(page) {
  // A quotation in a post/comment must not be mistaken for a platform dialog.
  const visible = await page.getByText('当前笔记暂时无法浏览', {exact:true}).evaluateAll(nodes => nodes.some(node => {
    if (node.closest('#detail-title,#detail-desc,.note-item,.comment-item')) return false;
    const box = node.getBoundingClientRect();
    if (box.width <= 0 || box.height <= 0) return false;
    for (let ancestor = node; ancestor; ancestor = ancestor.parentElement) {
      const style = getComputedStyle(ancestor);
      if (ancestor.getAttribute('aria-hidden') === 'true' || style.display === 'none'
        || style.visibility === 'hidden' || Number(style.opacity) < 0.05) return false;
    }
    return true;
  }));
  return visible ? '当前笔记暂时无法浏览；平台要求使用小红书App查看，保留断点并停止本节点' : null;
}

export async function assertWebNoteAccessible(page) {
  const message = await webNoteUnavailableMessage(page);
  if (message) throw Object.assign(new Error(`STOP_WEB_NOTE_UNAVAILABLE：${message}`), {code:'WEB_NOTE_UNAVAILABLE'});
}
