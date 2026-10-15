import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import {fileURLToPath} from 'node:url';
import {existsSync} from 'node:fs';
import {searchEndpointSnapshot,advanceSearchScroll} from './xhs-browser-state.mjs';
let browser;
before(async()=>{
  const bundled=fileURLToPath(new URL('../runtime/browsers/chrome-win64/chrome.exe',import.meta.url));
  const executablePath=process.env.XHS_TEST_BROWSER || (existsSync(bundled)?bundled:undefined);
  browser=await chromium.launch({headless:true,...(executablePath?{executablePath}:{})});
});
after(async()=>{await browser?.close();});

test('real DOM fixture observes and advances the actual inner search scroller',async()=>{
  const page=await browser.newPage();
  try{
    await page.setContent(`<div id="feed" style="height:200px;overflow-y:auto">
      <section class="note-item" data-note-id="n1" style="height:600px"><a href="/explore/n1">fixture 1</a></section>
      <section class="note-item" data-note-id="n2" style="height:600px"><a href="/explore/n2">fixture 2</a></section>
      <p id="end">没有更多了</p><span id="busy" style="display:none">加载中</span></div>`);
    const proxy={url:()=> 'https://www.xiaohongshu.com/search_result?keyword='+encodeURIComponent('保利熙瑞 看房'),
      evaluate:(fn,arg)=>page.evaluate(fn,arg)};
    const first=await searchEndpointSnapshot(proxy,'保利熙瑞 看房',2);
    assert.equal(first.contextValid,true);assert.equal(first.atBottom,false);assert.equal(first.viewport,200);
    await advanceSearchScroll(proxy);
    const end=await searchEndpointSnapshot(proxy,'保利熙瑞 看房',2);
    assert.equal(end.atBottom,true);assert.equal(end.terminal,true);assert.equal(end.loading,false);assert.equal(end.lastId,'n2');
    await page.locator('#busy').evaluate(node=>node.style.display='inline');
    assert.equal((await searchEndpointSnapshot(proxy,'保利熙瑞 看房',2)).loading,true);
    assert.equal((await searchEndpointSnapshot(page,'保利熙瑞 看房',2)).contextValid,false);
    await page.locator('#feed').evaluate(node=>node.style.opacity='0');
    const hidden=await searchEndpointSnapshot(proxy,'保利熙瑞 看房',2);
    assert.equal(hidden.rendered,false);assert.equal(hidden.terminal,false);
  }finally{await page.close();}
});
