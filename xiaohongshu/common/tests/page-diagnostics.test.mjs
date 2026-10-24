import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {existsSync} from 'node:fs';
import {createRequire} from 'node:module';
import {pathToFileURL,fileURLToPath} from 'node:url';
import vm from 'node:vm';
const base=process.env.PAGE_DIAG_PACKAGE||fileURLToPath(new URL('../../../',import.meta.url));
const root=await fs.mkdtemp(path.join(os.tmpdir(),'page-diagnostics-'));
const platformDirectory=p=>({'小红书':'xiaohongshu','抖音':'douyin'})[p]||p;
const require=createRequire(pathToFileURL(path.join(base,'douyin/common/src/collector.mjs')));
const {chromium}=require('playwright');
const load=(platform,file)=>import(pathToFileURL(path.join(base,platformDirectory(platform),'common/src',file)));
const {createPageDiagnostics,safeUrl,safeText,appendDiagnosticEvent}=await load('抖音','page-diagnostics.mjs');
const xhs=await load('小红书','xhs-browser-state.mjs');
const {ensureSingleColumn}=await load('抖音','douyin-browser.mjs');
let browser;
before(async()=>{
  const bundled=path.join(base,'douyin/common/runtime/browsers/chrome-win64/chrome.exe');
  const executablePath=process.env.DY_TEST_BROWSER||process.env.XHS_TEST_BROWSER||(existsSync(bundled)?bundled:undefined);
  browser=await chromium.launch({headless:true,...(executablePath?{executablePath}:{}),
    downloadsPath:root+'/downloads',tracesDir:root+'/traces',args:['--disk-cache-dir='+path.join(root,'browser-cache')]});
});
after(async()=>{await browser?.close();});
async function fixture(name,html,{platform='抖音',keyword='测试 住宅'}={}){
  const context=await browser.newContext({viewport:{width:1100,height:800}});
  // Every HTTP request is fulfilled in memory: never contact the platform.
  await context.route('**/*',route=>route.fulfill({status:200,contentType:'text/html; charset=utf-8',body:html}));
  const page=await context.newPage();
  const url=platform==='抖音'?'https://www.douyin.com/search/'+encodeURIComponent(keyword):'https://www.xiaohongshu.com/search_result?keyword='+encodeURIComponent(keyword);
  await page.goto(url);
  const outputDir=root+'/evidence/'+name;
  const diag=createPageDiagnostics({page,platform,keyword,outputDir,workerId:'fixture-worker',runId:name});
  return {page,context,diag,outputDir,keyword,url,async close(){diag.dispose();await context.close();}};
}
async function recordedLayout(f){
  const captures=[];
  let error;
  try{await ensureSingleColumn(f.page,{timeoutMs:90,pollMs:10,onDiagnostic:async event=>{
    f.diag.mark(event.stage,event.details);
    if(event.error)captures.push(await f.diag.capture(event.stage,event.error,event.details));
  }});}catch(e){error=e;}
  return {error,captures,async last(){return JSON.parse(await fs.readFile(captures.at(-1).jsonFile,'utf8'));}};
}
test('XHS close can be verified, then a later SPA navigation independently loses the keyword context',async()=>{
  const f=await fixture('xhs-late-route','<section class="note-item"><a href="/explore/n1">result</a></section><div id="noteContainer">detail</div><div class="note-detail-mask"><button class="close" onclick="document.querySelector(\'#noteContainer\').remove();this.parentElement.remove()">close</button></div>',{platform:'小红书',keyword:'中海宏洋 住宅'});
  try{
    const result=await xhs.closeDetailToSearch(f.page,{keyword:f.keyword,searchUrl:f.url,scrollY:0},{timeout:1000,log:()=>{}});
    assert.equal(result.method,'close_control');assert.equal(xhs.isKeywordSearchUrl(f.page.url(),f.keyword),true);
    f.diag.mark('detail_close_verified',{method:result.method});
    await f.page.evaluate(()=>history.pushState({},'','/explore/fixture?xsec_token=PRIVATE_URL_TOKEN'));
    assert.equal(xhs.isKeywordSearchUrl(f.page.url(),f.keyword),false);
    const saved=await f.diag.capture('search_context_lost',new Error('STOP_SEARCH_CONTEXT_LOST'));
    const text=await fs.readFile(saved.jsonFile,'utf8'),data=JSON.parse(text);
    assert.ok(data.reasons.includes('search_url_keyword_mismatch'));
    assert.ok(data.timeline.some(e=>e.stage==='detail_close_verified'));
    assert.ok(data.timeline.some(e=>e.stage==='main_frame_navigated'));
    assert.ok(!data.reasons.includes('single_column_control_not_found'));
    assert.ok(!text.includes('PRIVATE_URL_TOKEN'));
    assert.ok(data.screenshot);assert.equal(data.platform,'小红书');
  }finally{await f.close();}
});
test('hidden duplicate last matching single-column control reproduces the exact click failure',async()=>{
  const f=await fixture('dy-hidden-last','<button>单列</button><button style="display:none">单列</button>');
  try{
    const result=await recordedLayout(f);
    assert.match(result.error.message,/STOP_SEARCH_LAYOUT_UNCONFIRMED：单列控件无法正常点击/);
    const data=await result.last();
    assert.equal(data.dom.singleColumnControls.length,2);
    assert.equal(data.dom.singleColumnControls[0].visible,true);
    assert.ok(data.reasons.includes('last_matching_control_hidden'));
    assert.ok(data.errors.some(e=>e.message.includes('visible')));
  }finally{await f.close();}
});
test('overlay interception is distinguished from a hidden control',async()=>{
  const f=await fixture('dy-overlay','<button>单列</button><div class="blocking-overlay" style="position:fixed;inset:0;z-index:999;background:#eee"></div>');
  try{const result=await recordedLayout(f);assert.match(result.error.message,/单列控件无法正常点击/);
    const data=await result.last();assert.ok(data.reasons.includes('last_matching_control_obscured'));
    assert.match(data.dom.singleColumnControls[0].hit.classes,/blocking-overlay/);
  }finally{await f.close();}
});
test('disabled control is distinguished from an overlay',async()=>{
  const f=await fixture('dy-disabled','<button disabled>单列</button>');
  try{const result=await recordedLayout(f);assert.match(result.error.message,/单列控件无法正常点击/);
    assert.ok((await result.last()).reasons.includes('last_matching_control_disabled'));
  }finally{await f.close();}
});
test('missing control records zero matching elements',async()=>{
  const f=await fixture('dy-missing','<h1>search content</h1>');
  try{const result=await recordedLayout(f);assert.match(result.error.message,/单列控件无法正常点击/);
    assert.ok((await result.last()).reasons.includes('single_column_control_not_found'));
  }finally{await f.close();}
});
test('successful click without recognized post cards records a separate layout-not-applied failure',async()=>{
  const f=await fixture('dy-unrecognized-cards','<button>单列</button><div class="search-result-card">card without unique ID</div>');
  try{const result=await recordedLayout(f);assert.match(result.error.message,/单列切换未生效/);
    const data=await result.last();assert.equal(data.dom.cards.mounted,1);
    assert.ok(data.reasons.includes('mounted_cards_without_unique_post_id'));
    assert.equal(data.stage,'layout_not_confirmed');
  }finally{await f.close();}
});
test('healthy mounted card remains accepted with no extra UI clicks or failure artifacts',async()=>{
  const f=await fixture('dy-healthy','<div class="search-result-card" data-e2e-vid="1234567890123456789">post</div>');
  try{const result=await recordedLayout(f);assert.equal(result.error,undefined);assert.equal(result.captures.length,0);
    const saved=await f.diag.capture('healthy_fixture',null);assert.equal((JSON.parse(await fs.readFile(saved.jsonFile,'utf8'))).dom.cards.uniqueIdCards,1);
  }finally{await f.close();}
});
test('login requirement is still stopped before layout clicking, never bypassed by diagnostics',async()=>{
  const f=await fixture('dy-login','<p>登录后即可搜索</p><button>单列</button>');
  try{const result=await recordedLayout(f);assert.match(result.error.message,/STOP_LOGIN_REQUIRED/);assert.equal(result.captures.length,0);
  }finally{await f.close();}
});
test('a broken diagnostics callback cannot replace the original collection failure',async()=>{
  const f=await fixture('dy-callback-failure','<p>fixture</p>');
  try{await assert.rejects(()=>ensureSingleColumn(f.page,{timeoutMs:40,pollMs:5,onDiagnostic:()=>{throw new Error('broken logger');}}),/STOP_SEARCH_LAYOUT_UNCONFIRMED：单列控件无法正常点击/);
  }finally{await f.close();}
});
test('closed browser page still produces JSON without attempting screenshots',async()=>{
  const f=await fixture('closed-page','<p>fixture</p>');
  try{await f.page.close();const saved=await f.diag.capture('closed',new Error('STOP_BROWSER_CLOSED'));
    const data=JSON.parse(await fs.readFile(saved.jsonFile,'utf8'));assert.equal(data.closed,true);assert.ok(data.reasons.includes('browser_page_closed'));assert.equal(saved.screenshot,null);
  }finally{await f.close();}
});
test('diagnostic write failure is nonfatal and does not overwrite the original error',async()=>{
  const f=await fixture('write-failure','<p>fixture</p>');
  try{
    const file=root+'/not-a-directory';await fs.writeFile(file,'fixture');
    const diag=createPageDiagnostics({page:f.page,platform:'抖音',keyword:f.keyword,outputDir:file});
    const original=new Error('original failure');const result=await diag.capture('failure',original);
    assert.ok(result.captureError);assert.equal(original.message,'original failure');diag.dispose();
  }finally{await f.close();}
});
test('redaction strips credentials, URL credentials, signed query values and error causes',async()=>{
  assert.equal(safeUrl('https://user:PRIVATE@www.douyin.com/search/test?keyword=test&access_token=PRIVATE&xsec_token=PRIVATE#PRIVATE'),'https://www.douyin.com/search/test?keyword=test');
  assert.ok(!safeText('password=PRIVATE cookie=PRIVATE https://x.test/?token=PRIVATE').includes('PRIVATE'));
  assert.ok(!safeText('Authorization: Bearer PRIVATE_BEARER').includes('PRIVATE_BEARER'));
  assert.ok(!safeText('Cookie: first=PRIVATE_FIRST; second=PRIVATE_SECOND').includes('PRIVATE_'));
  const file=root+'/redacted-lifecycle.jsonl';
  await appendDiagnosticEvent(file,{stage:'fixture',password:'PRIVATE_PASSWORD',nested:{cookie:'PRIVATE_COOKIE'},error:'token=PRIVATE_TOKEN'});
  assert.ok(!(await fs.readFile(file,'utf8')).includes('PRIVATE_'));
});
test('timeline is bounded and event handlers are detached',async()=>{
  const f=await fixture('bounded-timeline','<p>fixture</p>');
  try{for(let i=0;i<100;i++)f.diag.mark('fixture_'+i);
    const saved=await f.diag.capture('final',null),data=JSON.parse(await fs.readFile(saved.jsonFile,'utf8'));
    assert.equal(data.timeline.length,60);const count=f.page.listenerCount('framenavigated');f.diag.dispose();assert.equal(f.page.listenerCount('framenavigated'),count-1);
  }finally{await f.close();}
});
test('worker lifecycle queues preserve the original keyword, phase and occurrence order',async()=>{
  const code=await fs.readFile(path.join(base,'xiaohongshu/common/src/run-worker.mjs'),'utf8');
  const fn=code.match(/function markLifecycle\(stage,details=\{\}\) \{[\s\S]*?\r?\n\}/)?.[0];
  assert.ok(fn);const events=[];
  const context=vm.createContext({diagnosticPhase:'collecting',diagnosticKeyword:'original-keyword',lifecycleQueue:Promise.resolve(),
    workerId:'fixture-worker',cycleId:'fixture-cycle',lifecycleFile:'fixture.jsonl',appendDiagnosticEvent:async(file,event)=>{events.push(event);}});
  vm.runInContext(fn,context);
  const first=context.markLifecycle('collector_finished',{collectorStatus:'context_lost'});
  context.diagnosticKeyword='next-keyword';
  const second=context.markLifecycle('preservation_import_started');
  const third=context.markLifecycle('runtime_limit_reached',{phaseAtDeadline:context.diagnosticPhase});
  await Promise.all([first,second,third]);
  assert.equal(events[0].keyword,'original-keyword');assert.equal(events[1].keyword,'next-keyword');
  assert.equal(events[2].phaseAtDeadline,'preservation_import_started');
  assert.deepEqual(events.map(e=>e.stage),['collector_finished','preservation_import_started','runtime_limit_reached']);
  assert.ok(events.every(e=>e.at));
});
test('context failure plus later runtime timeout remains distinct from an ordinary timeout-only exit',async()=>{
  const {cooldownWorkerExit}=await load('小红书','rate-limit-cooldown.mjs');
  const {summarizeWorkerTasks}=await load('小红书','worker-status.mjs');
  const tasks=[{status:'context_lost',importExitCode:0,redisReleased:true}];
  const summary=summarizeWorkerTasks(tasks);
  assert.equal(summary.failedCount,0);
  assert.equal(cooldownWorkerExit({status:{tasks,...summary},fatalError:null}),1);
  assert.equal(cooldownWorkerExit({status:{tasks:[{status:'partial_stopped',importExitCode:0,redisReleased:true}],failedCount:0},fatalError:null}),0);
});
test('both platform deployments expose the same safe standalone diagnostic interface',async()=>{
  const modules=await Promise.all(['小红书','抖音'].map(p=>load(p,'page-diagnostics.mjs')));
  assert.deepEqual(Object.keys(modules[0]).sort(),Object.keys(modules[1]).sort());
  for(const module of modules){
    assert.equal(typeof module.createPageDiagnostics,'function');
    assert.equal(typeof module.appendDiagnosticEvent,'function');
    assert.ok(module.DIAGNOSTIC_VERSION.startsWith('page-diagnostics-'));
    assert.equal(module.safeUrl('https://example.com/?token=fixture-secret'),modules[0].safeUrl('https://example.com/?token=fixture-secret'));
  }
});
