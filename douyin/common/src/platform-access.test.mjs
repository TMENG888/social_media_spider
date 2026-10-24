import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import {fileURLToPath} from 'node:url';
import {inspectPlatformAccess,assertPlatformAccess,guardedPlatformAction} from './platform-access.mjs';
let browser;
before(async()=>{browser=await chromium.launch({headless:true,executablePath:process.env.DY_TEST_BROWSER||process.env.XHS_TEST_BROWSER||fileURLToPath(new URL('../runtime/browsers/chrome-win64/chrome.exe',import.meta.url)),args:['--disable-background-networking']});});
after(async()=>{await browser?.close();});
for(const platform of ['抖音','小红书']){
 async function fixture(html){
  const context=await browser.newContext({serviceWorkers:'block'}),page=await context.newPage();
  await context.route('**/*',r=>r.request().isNavigationRequest()?r.fulfill({contentType:'text/html; charset=utf-8',body:'<!doctype html><body>'+html+'</body>'}):r.abort());
  await page.goto(platform==='抖音'?'https://www.douyin.com/':'https://www.xiaohongshu.com/explore');
  return {context,page};
 }
 for(const html of [
  '<div id="login-full-panel-100fd4uqu98g0" style="width:400px;height:300px"></div>',
  '<div class="login-container" style="display:none">扫码登录</div><div class="login-container">请先登录</div>',
  '登录后即可搜索',
 ]){
  test(platform+' visible login blocks: '+html.slice(0,40),async()=>{
   const f=await fixture(html);let called=0,reported=0;
   try{await assert.rejects(guardedPlatformAction(f.page,platform,()=>{called++;},{report:()=>reported++}),/^Error: STOP_LOGIN_REQUIRED/);assert.equal(called,0);assert.equal(reported,1);}
   finally{await f.context.close();}
  });
 }
 test(platform+' hidden/preloaded panel and content quotes are ignored',async()=>{
  const f=await fixture('<div style="display:none"><div id="login-full-panel-a" style="width:100px;height:100px">扫码登录</div></div><section class="note-item"><span>安全验证 操作频繁 扫码登录</span></section><article class="search-result-card"><span>安全验证 登录后即可搜索</span></article>');
  try{assert.equal((await inspectPlatformAccess(f.page,platform)).kind,null);}finally{await f.context.close();}
 });
 test(platform+' panel appearing during a click is reclassified, not force-clicked',async()=>{
  const f=await fixture('<input placeholder="搜索">');let reported=0;
  try{await assert.rejects(guardedPlatformAction(f.page,platform,async()=>{await f.page.evaluate(()=>{document.body.insertAdjacentHTML('beforeend','<div id="login-full-panel-race" style="width:100px;height:100px"></div>');});throw new Error('locator.click: timeout');},{report:()=>reported++}),/STOP_LOGIN_REQUIRED/);assert.equal(reported,1);}
  finally{await f.context.close();}
 });
 test(platform+' unrelated action errors remain fatal',async()=>{
  const f=await fixture('<p>推荐内容</p>');
  try{await assert.rejects(guardedPlatformAction(f.page,platform,()=>{throw new Error('UNRELATED_DISK_FAILURE');}),/UNRELATED_DISK_FAILURE/);}finally{await f.context.close();}
 });
 test(platform+' captcha has priority over login and rate limits stay timed',async()=>{
  for(const [html,kind] of [['<div>请完成安全验证</div><div>扫码登录</div>','captcha'],['<div>操作频繁</div>','security'],['502 Bad Gateway','gateway']]){
   const f=await fixture(html);try{assert.equal((await inspectPlatformAccess(f.page,platform)).kind,kind);}finally{await f.context.close();}
  }
 });
 test(platform+' rendered application false login flag never passes',async()=>{
  const f=await fixture('<p>推荐内容</p>');
  try{await f.page.evaluate(()=>window.__INITIAL_STATE__={user:{isLogin:false}});assert.equal((await inspectPlatformAccess(f.page,platform)).kind,'login');}finally{await f.context.close();}
 });
}
