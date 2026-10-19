import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import {existsSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {searchScrollDom,searchScrollProgress} from './search-scroll.mjs';
import {scrollSearchResults} from './douyin-browser.mjs';
let browser;
before(async()=>{
 const bundled=fileURLToPath(new URL('../runtime/browsers/chrome-win64/chrome.exe',import.meta.url));
 const executablePath=process.env.DY_TEST_BROWSER||process.env.XHS_TEST_BROWSER||(existsSync(bundled)?bundled:undefined);
 browser=await chromium.launch({headless:true,...(executablePath?{executablePath}:{})});
});
after(async()=>{await browser?.close();});
const keyword='保利地产 住宅';
const proxy=page=>({url:()=>`https://www.douyin.com/search/${encodeURIComponent(keyword)}`,
 evaluate:(fn,arg)=>page.evaluate(fn,arg),locator:(...args)=>page.locator(...args),
 isClosed:()=>page.isClosed(),mouse:page.mouse,keyboard:page.keyboard});
const card='<article class="search-result-card" style="height:10000px"><div data-e2e-vid="7690238024572292003">fixture video</div><div data-e2e="comment-list" style="height:100px;overflow-y:auto"><p style="height:1500px">comments</p></div></article>';

test('real DOM missing scroll-list selector, search suggestions and comment sidebar cannot steal search scrolling',async()=>{
 const page=await browser.newPage();
 try{
  await page.setContent(`<style>body{margin:0;overflow:hidden}#feed{position:absolute;top:100px;left:100px;width:800px;height:500px;overflow:auto}#suggest{position:fixed;top:80px;left:100px;width:800px;height:500px;background:white;overflow:auto;z-index:20}</style>
   <input data-e2e="searchbar-input"><div id="feed">${card}</div><div id="suggest"><p style="height:3000px">search suggestions</p></div>`);
  await page.locator('input').focus();
  await page.evaluate(()=>document.addEventListener('keydown',e=>{if(e.key==='Escape')document.querySelector('#suggest').style.display='none';}));
  let progress={};let state;
  // More than fifteen mounted-card-only passes must advance to the actual end.
  for(let i=0;i<30;i++){state=await scrollSearchResults(proxy(page),{keyword});progress=searchScrollProgress(progress,state);if(state.atBottom)break;assert.equal(progress.progressed,true);}
  assert.equal(state.scrollport.id,'feed');assert.equal(state.atBottom,true);assert.ok(state.afterTop>9000);
  assert.equal(await page.locator('#suggest').evaluate(el=>el.scrollTop),0);
  assert.equal(await page.locator('[data-e2e="comment-list"]').evaluate(el=>el.scrollTop),0);
  assert.equal(await page.evaluate(()=>document.activeElement.tagName),'BODY');
  const stopped=await scrollSearchResults(proxy(page),{keyword});assert.equal(stopped.movedForward,false);
  assert.equal(searchScrollProgress(progress,stopped).progressed,false);
 }finally{await page.close();}
});

test('real DOM scrolls nearest results ancestor rather than root or unrelated scroll-list',async()=>{
 const page=await browser.newPage();
 try{
  await page.setContent(`<div style="height:1800px"><div data-e2e="scroll-list" style="height:100px;overflow:auto"><p style="height:2000px">unrelated</p></div><div id="feed" style="height:400px;overflow:auto">${card}</div></div>`);
  const state=await scrollSearchResults(proxy(page),{keyword});
  assert.equal(state.scrollport.id,'feed');assert.equal(state.movedForward,true);
  assert.equal(await page.evaluate(()=>document.scrollingElement.scrollTop),0);
  assert.equal(await page.locator('[data-e2e="scroll-list"]').evaluate(el=>el.scrollTop),0);
 }finally{await page.close();}
});

test('real DOM root scroll fallback works and non-search/modal/empty contexts never scroll',async()=>{
 const page=await browser.newPage();
 try{
  await page.setContent(card);
  assert.equal((await scrollSearchResults(proxy(page),{keyword})).scrollport.root,true);
  await assert.rejects(scrollSearchResults(page,{keyword}),/CONTEXT_LOST/);
  const before=await page.evaluate(()=>document.scrollingElement.scrollTop);
  await page.evaluate(()=>{const modal=document.createElement('div');modal.dataset.e2e='modal-video-container';modal.style='position:fixed;inset:0';modal.textContent='detail';document.body.append(modal);});
  await assert.rejects(scrollSearchResults(proxy(page),{keyword}),/MODAL_OPEN/);
  assert.equal(await page.evaluate(()=>document.scrollingElement.scrollTop),before);
  await page.setContent('<input data-e2e="searchbar-input"><div>loading search</div>');
  assert.deepEqual(await page.evaluate(searchScrollDom,{advance:true}),{available:false,reason:'no_search_cards'});
 }finally{await page.close();}
});

test('bounce, missing ports and bottom alone are not progress or endpoint proof',()=>{
 const s={available:true,scrollport:{id:'feed'},beforeTop:0,afterTop:400,movedForward:true,atBottom:false};
 const p=searchScrollProgress({},s);assert.equal(p.progressed,true);
 assert.equal(searchScrollProgress(p,s).progressed,false);
 const other=searchScrollProgress(p,{...s,scrollport:{id:'other'}});
 assert.equal(searchScrollProgress(other,s).progressed,false);
 assert.equal(searchScrollProgress(p,{...s,beforeTop:400,afterTop:400,movedForward:false,atBottom:true}).progressed,false);
 assert.equal(searchScrollProgress(p,{available:false}).progressed,false);
 assert.equal(Object.hasOwn(s,'confirmed'),false);
});
