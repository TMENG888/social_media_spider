const RESULT_SELECTOR = 'section.note-item,.note-item,[data-note-id]';
const DETAIL_SELECTOR = '#noteContainer,.note-container,#detail-title,#detail-desc';
const FILTER_CONTROL = 'div.filter,button.filter,[class~="filter"]';

export async function renderedControl(locator) {
  const index = await locator.evaluateAll(nodes => nodes.findIndex(node => {
    const box = node.getBoundingClientRect();
    if (box.width <= 0 || box.height <= 0) return false;
    for (let ancestor = node; ancestor; ancestor = ancestor.parentElement) {
      const style = getComputedStyle(ancestor);
      if (ancestor.getAttribute('aria-hidden') === 'true' || style.display === 'none'
        || style.visibility === 'hidden' || Number(style.opacity) < 0.05) return false;
    }
    return true;
  }));
  return index < 0 ? null : locator.nth(index);
}

function filterControls(page) {
  // A panel can be nested inside the control. Match its direct label, not the
  // entire textContent, which then contains every filter option as well.
  return page.locator(FILTER_CONTROL).filter({ has: page.locator(':scope > span').filter({ hasText: /^(筛选|已筛选)$/ }) })
    .or(page.locator(FILTER_CONTROL).filter({ hasText: /^(筛选|已筛选)$/ }));
}

export function isKeywordSearchUrl(value, keyword) {
  try {
    const url = new URL(value);
    return /(^|\.)xiaohongshu\.com$/i.test(url.hostname) && /^\/search_result\/?$/.test(url.pathname)
      && url.searchParams.get('keyword') === keyword;
  } catch { return false; }
}

export async function visibleAny(page, selector) {
  if (page.isClosed()) throw new Error('STOP_BROWSER_CLOSED：浏览器页签已关闭，保留断点后停止本节点');
  return page.locator(selector).evaluateAll(nodes => nodes.some(node => {
    const box = node.getBoundingClientRect(), style = getComputedStyle(node);
    return box.width > 0 && box.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  }));
}

export async function searchEndpointSnapshot(page,keyword,count) {
  const contextValid=isKeywordSearchUrl(page.url(),keyword);
  const state=await page.evaluate(selector=>{
    const visible=node=>{
      const r=node.getBoundingClientRect();if(!(r.width>0&&r.height>0))return false;
      for(let parent=node;parent;parent=parent.parentElement){
        const s=getComputedStyle(parent);
        if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)<0.05||parent.getAttribute('aria-hidden')==='true')return false;
      }
      return true;
    };
    const cards=[...document.querySelectorAll(selector)].filter(node=>node.querySelector('a[href*="/search_result/"],a[href*="/explore/"]'));
    const last=cards.at(-1); let scroller=document.scrollingElement;
    for(let parent=last?.parentElement;parent&&parent!==document.body;parent=parent.parentElement){
      if(/auto|scroll/.test(getComputedStyle(parent).overflowY)&&parent.scrollHeight>parent.clientHeight+8){scroller=parent;break;}
    }
    const height=scroller?.scrollHeight||0,top=scroller?.scrollTop||0,viewport=scroller?.clientHeight||0;
    const labels=[...document.querySelectorAll('div,p,span')].filter(node=>!node.closest(selector)&&visible(node)).map(node=>node.textContent?.trim()||'');
    const terminal=labels.some(t=>/^(没有更多了?|暂无更多(内容|笔记|结果)?|已显示全部(结果)?|到底了|没有更多(内容|笔记|结果)了?)$/.test(t));
    const loading=labels.some(t=>/^(正在)?加载中[.。…]*$/.test(t))||[...document.querySelectorAll('[aria-busy="true"]')].some(visible);
    const loadFailed=labels.some(t=>/^(加载失败|网络异常|网络错误|点击重试)[，,。 .]*(请稍后重试|点击重试)?$/.test(t));
    const href=last?.querySelector('a[href*="/search_result/"],a[href*="/explore/"]')?.getAttribute('href')||'';
    const lastId=last?.getAttribute('data-note-id')||href.match(/\/(?:search_result|explore)\/([a-zA-Z0-9]+)/)?.[1]||null;
    return {rendered:cards.some(visible),height,top,viewport,atBottom:Boolean(height&&viewport&&top+viewport>=height-8),terminal,loading,loadFailed,lastId};
  },RESULT_SELECTOR);
  return {...state,count,contextValid};
}

export async function advanceSearchScroll(page) {
  await page.evaluate(selector=>{
    const last=[...document.querySelectorAll(selector)].at(-1); let scroller=document.scrollingElement;
    for(let parent=last?.parentElement;parent&&parent!==document.body;parent=parent.parentElement){
      if(/auto|scroll/.test(getComputedStyle(parent).overflowY)&&parent.scrollHeight>parent.clientHeight+8){scroller=parent;break;}
    }
    scroller?.scrollBy({top:Math.max((scroller.clientHeight||innerHeight)*1.6,1400),behavior:'instant'});
  },RESULT_SELECTOR);
}

export async function latestSortSnapshot(page) {
  // Read one current DOM snapshot. Clicks may destroy the whole panel, so a
  // locator captured before the click must never be awaited for attributes.
  return page.locator('.filter-panel').evaluateAll(panels => {
    const visible = node => {
      const box = node.getBoundingClientRect(), style = getComputedStyle(node);
      if (!(box.width > 0 && box.height > 0 && style.display !== 'none' && style.visibility !== 'hidden')) return false;
      for (let ancestor = node; ancestor; ancestor = ancestor.parentElement) {
        if (ancestor.getAttribute('aria-hidden') === 'true' || Number(getComputedStyle(ancestor).opacity) < 0.05) return false;
      }
      return true;
    };
    for (const panel of panels.filter(visible)) {
      const group = [...panel.querySelectorAll('.filters')].find(node => /排序依据/.test(node.textContent || ''));
      if (!group) continue;
      const latest = [...group.querySelectorAll('.tags')].find(node => node.textContent?.trim() === '最新' && visible(node));
      if (!latest) continue;
      const selected = latest.matches('.active,.selected,.checked') || latest.getAttribute('aria-selected') === 'true'
        || latest.getAttribute('aria-checked') === 'true';
      return { panelVisible: true, latestVisible: visible(latest), selected, className: latest.className };
    }
    return { panelVisible: false, latestVisible: false, selected: false, className: null };
  });
}

async function openFilterPanel(page) {
  if ((await latestSortSnapshot(page)).latestVisible) return true;
  const controls = filterControls(page);
  const count = await controls.count();
  for (let index = 0; index < count; index += 1) {
    const control = controls.nth(index);
    if (!await renderedControl(control)) continue;
    await control.hover({ timeout: 2000 }).catch(() => {});
    await page.waitForTimeout(200);
    if ((await latestSortSnapshot(page)).latestVisible) return true;
    await control.click({ timeout: 2500 }).catch(() => {});
    for (let attempt = 0; attempt < 5; attempt += 1) {
      await page.waitForTimeout(150);
      if ((await latestSortSnapshot(page)).latestVisible) return true;
    }
  }
  return false;
}

export async function ensureLatestSort(page, keyword, { assertSafe = async () => {}, attempts = 3, log = console.log } = {}) {
  let snapshot = null;
  await assertSafe(page);
  await page.locator('div.filter:visible,button.filter:visible,[class~="filter"]:visible').first()
    .waitFor({state:'visible',timeout:12000}).catch(() => {});
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    if (page.isClosed()) throw new Error('STOP_BROWSER_CLOSED：确认排序时浏览器已关闭');
    await assertSafe(page);
    if (!isKeywordSearchUrl(page.url(), keyword)) throw new Error(`STOP_SEARCH_CONTEXT_LOST：排序时页面不属于关键词“${keyword}”`);
    if (!await openFilterPanel(page)) {
      log(`[筛选核验] ${keyword}：第${attempt}/${attempts}次未发现可见“排序依据/最新”控件`);
      await page.waitForTimeout(400); continue;
    }
    snapshot = await latestSortSnapshot(page);
    if (!snapshot.selected) {
      const latest = await renderedControl(page.locator('.filter-panel .filters').filter({ hasText: /排序依据/ }).locator('.tags')
        .filter({ hasText: /^最新$/ }));
      await latest?.click({ timeout: 3000 }).catch(error => {
        if (page.isClosed()) throw new Error('STOP_BROWSER_CLOSED：点击最新排序时浏览器已关闭', { cause: error });
      });
      await page.waitForTimeout(700);
      // XHS closes/unmounts the panel after choosing a tag. Reopen it and
      // inspect the newly mounted tag, including when the previous tag vanished.
      await openFilterPanel(page);
      snapshot = await latestSortSnapshot(page);
    }
    if (snapshot.selected) {
      await page.keyboard.press('Escape').catch(() => {});
      await page.mouse.move(500, 400).catch(() => {});
      if (await visibleAny(page, '.filter-panel')) {
        const collapse = await renderedControl(page.locator('.filter-panel .operation').filter({ hasText: /^收起$/ }));
        const control = collapse || await renderedControl(filterControls(page));
        await control?.click({ timeout: 2000 }).catch(() => {});
        await page.mouse.move(500, 400).catch(() => {});
      }
      await assertSafe(page);
      if (!isKeywordSearchUrl(page.url(), keyword)) throw new Error('STOP_SEARCH_CONTEXT_LOST：确认排序后离开当前关键词搜索页');
      log(`[筛选] ${keyword}：重新读取当前DOM，最新选中状态已确认（第${attempt}次核验）`);
      return { keyword, selected: true, verifiedAt: Date.now(), searchUrl: page.url(), className: snapshot.className };
    }
    log(`[筛选核验] ${keyword}：第${attempt}/${attempts}次，面板=${snapshot.panelVisible}，最新可见=${snapshot.latestVisible}，class=${snapshot.className || '无'}`);
  }
  await assertSafe(page);
  throw new Error(`STOP_SORT_NOT_CONFIRMED：${attempts}次有限核验后仍未确认最新选中；停止本节点，保留断点`);
}

export async function captureSearchState(page, keyword) {
  if (!isKeywordSearchUrl(page.url(), keyword)) throw new Error('STOP_SEARCH_CONTEXT_LOST：打开帖子前不在当前关键词搜索页');
  return { keyword, searchUrl: page.url(), scrollY: await page.evaluate(() => window.scrollY) };
}

export async function closeDetailToSearch(page, state, { timeout = 45000, assertSafe = async () => {}, log = console.log } = {}) {
  if (page.isClosed()) throw new Error('STOP_BROWSER_CLOSED：关闭帖子时浏览器已关闭');
  await assertSafe(page);
  await page.locator('video').evaluateAll(videos => videos.forEach(video => { try { video.pause(); } catch {} })).catch(() => {});
  const previewSelector = '.preview-modal,[class*="preview-modal"],[class*="image-preview"]';
  const recovered = async () => isKeywordSearchUrl(page.url(), state.keyword)
    && !await visibleAny(page, DETAIL_SELECTOR) && !await visibleAny(page, previewSelector)
    && await visibleAny(page, RESULT_SELECTOR);
  const finish = async (method, waitMs = 0) => {
    const deadline = Date.now() + waitMs;
    do {
      await assertSafe(page);
      if (await recovered()) {
        // A normal detail overlay close does not rebuild the search route.
        // Keep the one sort selection made when the keyword search opened;
        // reopening the filter for every note adds unnecessary interactions.
        await page.evaluate(position => window.scrollTo({ top: position, behavior: 'instant' }), state.scrollY).catch(() => {});
        log(`[详情关闭] ${method}，沿用检索开始时已确认的最新排序，保留“${state.keyword}”搜索结果页`);
        return true;
      }
      if (Date.now() >= deadline) break;
      await page.waitForTimeout(200);
    } while (true);
    return false;
  };
  if (await finish('页面已自行恢复')) return { method: 'already_closed' };
  if (await visibleAny(page, previewSelector)) {
    await page.keyboard.press('Escape').catch(() => {});
    if (await finish('图片预览层已关闭', 1200)) return { method: 'preview_closed' };
  }
  const closeSelectors = ['.note-detail-mask .close.close-mask-dark:visible', '.note-detail-mask .close:visible', '.close.close-mask-dark:visible'];
  for (let pass = 0; pass < 2; pass += 1) {
    for (const selector of closeSelectors) {
      const close = page.locator(selector).first();
      if (!await close.isVisible().catch(() => false)) continue;
      await close.click({ timeout: 3000 }).catch(() => {});
      if (await finish('已点击帖子关闭按钮', 1600)) return { method: 'close_control' };
    }
    if (await visibleAny(page, previewSelector)) await page.keyboard.press('Escape').catch(() => {});
  }
  const containers = page.locator('#noteContainer:visible,.note-container:visible,[class*="note-container"]:visible');
  let box = null;
  for (let index = 0; index < await containers.count(); index += 1) {
    const candidate = await containers.nth(index).boundingBox();
    if (candidate && candidate.width >= 300 && candidate.height >= 200) { box = candidate; break; }
  }
  const viewport = page.viewportSize() || await page.evaluate(() => ({width:innerWidth,height:innerHeight}));
  if (box) {
    const points = [
      {x:Math.max(8,box.x/2),y:Math.min(viewport.height-8,Math.max(8,box.y+120))},
      {x:Math.min(viewport.width-8,box.x+box.width+16),y:Math.min(viewport.height-8,Math.max(8,box.y+120))}
    ].filter(p=>p.x<box.x||p.x>box.x+box.width||p.y<box.y||p.y>box.y+box.height);
    for (const point of points) {
      // Do not click a search card behind the mask: only a genuine overlay
      // background is a safe outside-click target.
      const mask = await page.evaluate(({x,y}) => {
        const node = document.elementFromPoint(x,y);
        return Boolean(node?.matches('.note-detail-mask,.note-detail-mask > .mask,[class~="note-detail-mask"]'));
      },point);
      if (!mask) continue;
      await page.mouse.click(point.x,point.y);
      if (await finish('已点击详情遮罩空白区域', 1200)) return { method: 'outside_mask' };
    }
  }
  for (let attempt = 0; attempt < 2; attempt += 1) {
    await page.keyboard.press('Escape').catch(() => {});
    if (await finish('已通过Escape关闭详情', 1000)) return { method: 'escape' };
  }
  // Only a real route reload invalidates the original sort selection. In that
  // exceptional recovery path, select/verify Latest once again before resuming.
  if (!isKeywordSearchUrl(state.searchUrl,state.keyword)) throw new Error('STOP_SEARCH_CONTEXT_LOST：原搜索地址无效');
  log(`[搜索恢复] ${state.keyword}：关闭控件未恢复列表，当前页签重载原搜索地址并重新确认排序`);
  await page.goto(state.searchUrl,{waitUntil:'domcontentloaded',timeout});
  await ensureLatestSort(page,state.keyword,{assertSafe,log});
  if (await finish('搜索地址恢复且最新排序已重新核验',Math.min(timeout,15000))) return { method: 'reload_verified' };
  throw new Error('STOP_SEARCH_CONTEXT_LOST：详情关闭及有限恢复失败，停止本节点');
}
