import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import {existsSync,readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {navigateSearch,searchPageKeyword,assertSearchContext,searchEndUi,scrollSearchResults,waitForInitialSearch} from './douyin-browser.mjs';
import {DouyinResponseObserver} from './douyin-data.mjs';

// Real Chromium, completely routed offline. No production browser profile,
// Redis, MySQL, platform requests, or task/stop-marker mutations.
let browser;
before(async()=>{
 const bundled=fileURLToPath(new URL('../runtime/browsers/chrome-win64/chrome.exe',import.meta.url));
 browser=await chromium.launch({headless:true,executablePath:process.env.DY_TEST_BROWSER||(existsSync(bundled)?bundled:undefined),args:['--disable-background-networking']});
});
after(async()=>{await browser?.close();});
const fast={settleMs:0,typingDelayMs:0,timeoutMs:1800,retryDelaysMs:[]};
async function fixture(options={}){
 const context=await browser.newContext({serviceWorkers:'block'}),page=await context.newPage();
 const documents=[],api=[],unexpected=[];let oldReply;
 await context.route('**/*',async route=>{
  const request=route.request(),url=new URL(request.url());
  if(url.hostname!=='www.douyin.com'){unexpected.push(request.url());await route.abort();return;}
  if(url.pathname.includes('/general/search/')){
   api.push(url.searchParams.get('keyword'));
   if(url.searchParams.has('old'))await new Promise(resolve=>{oldReply=resolve;});
   const status=(options.statuses||[200])[Math.min(api.length-1,(options.statuses||[200]).length-1)];
   await route.fulfill({status,contentType:'application/json',body:JSON.stringify({status_code:options.businessCode||0,data:[],keyword:url.searchParams.get('keyword')})});return;
  }
  if(!request.isNavigationRequest()){await route.abort();return;}
  documents.push(url.pathname);
  // Any accidental page.goto(searchUrl(...)) fails this fixture.
  if(/\/(?:jingxuan\/)?search\//.test(url.pathname)&&!options.fullNavigation){await route.fulfill({status:502,contentType:'text/html',body:'502 Bad Gateway: direct links forbidden by fixture'});return;}
  const initial=searchPageKeyword(url.href)||options.initial||'';
  await route.fulfill({status:200,contentType:'text/html; charset=utf-8',body:options.body??`<!doctype html><html><body>
   ${options.hiddenInput?'<input data-e2e="searchbar-input" style="display:none">':''}
   <input data-e2e="searchbar-input"><button data-e2e="searchbar-button">搜索</button>
   <main>old cards</main>
   ${options.rememberPrompt?'<div id="trust-logout-dialog" style="position:fixed;inset:0;z-index:100;background:white">是否保存登录信息？<button onclick="window.cancelled=true;this.parentElement.remove()">取消</button><button onclick="window.saved=true">保存</button></div>':''}
   ${options.opaqueOverlay?'<div id="unknown-overlay" style="position:fixed;inset:0;z-index:101;background:white">加载中</div>':''}
   <script>
    const options=${JSON.stringify({...options,body:undefined})};
    const input=document.querySelector('input:not([style])');input.value=${JSON.stringify(initial)};
    window.events=[];window.submissions=[];
    input.addEventListener('input',()=>{
     events.push(input.value);
     if(input.value&&(options.resetEveryInput||options.resetFirstInput&&!window.resetDone)){window.resetDone=true;input.value='';}
    });
    const searchPrefix=options.routePrefix||'/search/';
    if(${JSON.stringify(initial)})history.replaceState({},'', searchPrefix+encodeURIComponent(input.value));
    document.querySelector('[data-e2e="searchbar-button"]').onclick=async()=>{
     const keyword=input.value;submissions.push(keyword);
     if(options.inert)return;
     if(options.fullNavigation){location.href=searchPrefix+encodeURIComponent(keyword);return;}
     history.pushState({},'',searchPrefix+encodeURIComponent(options.wrongKeyword||keyword));
     if(options.noFreshResponse)return;
     const response=await fetch('/aweme/v1/web/general/search/single/?keyword='+encodeURIComponent(keyword));
     if(!response.ok||options.gatewayBodyOnOk){document.querySelector('main').textContent='502 Bad Gateway';return;}
     document.querySelector('main').textContent='results: '+keyword;
    };
   </script></body></html>`});
 });
 return {page,context,documents,api,unexpected,releaseOld:()=>oldReply?.(),close:()=>context.close()};
}

test('blank page bootstraps HOME only, clears/types the exact keyword and clicks search',async()=>{
 const f=await fixture();try{
  const keyword='金茂 住宅 + A/B';
  const audit=await navigateSearch(f.page,keyword,fast);
  assert.equal(audit.method,'search_box');assert.equal(audit.attempts[0].inputCleared,true);
  assert.equal(audit.attempts[0].stage,'verified');assert.equal(audit.attempts[0].response.kind,'search_api');
  assert.deepEqual(f.documents,['/']);assert.deepEqual(f.api,[keyword]);assert.deepEqual(f.unexpected,[]);
  assert.deepEqual(await f.page.evaluate(()=>submissions),[keyword]);
  assert.equal(await f.page.locator('main').innerText(),'results: '+keyword);
 }finally{await f.close();}
});

test('optional remember-login prompt is cancelled normally, never saved',async()=>{
 const f=await fixture({rememberPrompt:true});try{
  const audit=await navigateSearch(f.page,'保利 神盘',fast);
  assert.equal(audit.attempts[0].optionalLoginPromptCancelled,true);
  assert.deepEqual(f.api,['保利 神盘']);
  assert.equal(await f.page.evaluate(()=>window.cancelled),true);
  assert.equal(await f.page.evaluate(()=>window.saved),undefined);
 }finally{await f.close();}
});

test('unknown input obstruction gets at most the configured retries, never force-clicks or submits',async()=>{
 const f=await fixture({opaqueOverlay:true});try{
  await assert.rejects(navigateSearch(f.page,'same',{...fast,timeoutMs:450,retryDelaysMs:[0,0]}),e=>{
   assert.equal(e.searchNavigation.attempts.length,3);
   assert.ok(e.searchNavigation.attempts.every(a=>a.status==='ui_timeout'));return true;
  });
  assert.deepEqual(f.api,[]);assert.equal(await f.page.locator('#unknown-overlay').count(),1);
 }finally{await f.close();}
});

test('HTTP200 business failure has a distinct readiness diagnostic, never empty-result acceptance',async()=>{
 const f=await fixture({businessCode:500}),observer=new DouyinResponseObserver(f.page);try{
  await navigateSearch(f.page,'same',fast);
  await assert.rejects(waitForInitialSearch(f.page,observer,{timeoutMs:1000,pollMs:20}),e=>{
   assert.match(e.message,/SEARCH_INITIAL_RESPONSE_FAILED/);
   assert.equal(e.searchReadiness.responseFailures.at(-1).statusCode,500);return true;
  });
 }finally{observer.detach();await f.close();}
});

test('temporary obstruction can recover within the bounded UI retry budget',async()=>{
 const f=await fixture({opaqueOverlay:true});let observationJob=Promise.resolve();try{
  await f.page.goto('https://www.douyin.com/');
  // The fixture simulates a loading overlay naturally ending after timeout;
  // production never removes unknown overlays.
  const audit=await navigateSearch(f.page,'same',{...fast,timeoutMs:450,retryDelaysMs:[600,0],
   onObservation:a=>{if(a.attempts.at(-1).status==='ui_timeout')observationJob=f.page.evaluate(()=>{
    setTimeout(()=>document.querySelector('#unknown-overlay')?.remove(),100);
   });}});
  await observationJob;
  assert.deepEqual(audit.attempts.map(a=>a.status),['ui_timeout','ready']);
  assert.deepEqual(f.api,['same']);assert.equal(audit.attempts.at(-1).readiness,'transport_only');
 }finally{await f.close();}
});

test('switching keywords reuses the current UI and never opens a search URL',async()=>{
 const f=await fixture({initial:'招商蛇口 好房子'});try{
  await f.page.goto('https://www.douyin.com/');
  await navigateSearch(f.page,'金茂府',fast);
  assert.deepEqual(f.documents,['/']);assert.deepEqual(f.api,['金茂府']);
  const events=await f.page.evaluate(()=>events);assert.equal(events[0],'');assert.equal(events.at(-1),'金茂府');
  assert.equal(await f.page.locator('main').innerText(),'results: 金茂府');
 }finally{await f.close();}
});

test('restarting the SAME keyword still requires a fresh UI-triggered response',async()=>{
 const f=await fixture({initial:'金茂府'});try{
  await f.page.goto('https://www.douyin.com/');
  await navigateSearch(f.page,'金茂府',fast);await navigateSearch(f.page,'金茂府',fast);
  assert.deepEqual(f.api,['金茂府','金茂府']);assert.deepEqual(f.documents,['/']);
 }finally{await f.close();}
});

test('normal search button full-document navigation also verifies the new keyword',async()=>{
 const f=await fixture({initial:'old',fullNavigation:true});try{
  await f.page.goto('https://www.douyin.com/');
  const audit=await navigateSearch(f.page,'新词',fast);
  assert.equal(audit.attempts[0].response.kind,'search_document');
  assert.deepEqual(f.documents,['/','/search/'+encodeURIComponent('新词')]);assert.deepEqual(f.api,[]);
 }finally{await f.close();}
});

test('hidden duplicate search input cannot steal the interaction',async()=>{
 const f=await fixture({hiddenInput:true});try{
  await navigateSearch(f.page,'new word',fast);assert.deepEqual(f.api,['new word']);
 }finally{await f.close();}
});

test('real-site /jingxuan/search route supports UI keyword switching and full navigation',async()=>{
 for(const fullNavigation of [false,true]){
  const f=await fixture({initial:'old',routePrefix:'/jingxuan/search/',fullNavigation});try{
   await f.page.goto('https://www.douyin.com/');
   const audit=await navigateSearch(f.page,'金茂 住宅',fast);
   assert.equal(audit.attempts[0].status,'ready');assert.equal(searchPageKeyword(f.page.url()),'金茂 住宅');
   assert.equal(audit.attempts[0].response.kind,fullNavigation?'search_document':'search_api');
  }finally{await f.close();}
 }
});

test('old and jingxuan search routes retain strict keyword, domain and modal guards',()=>{
 for(const prefix of ['/search/','/jingxuan/search/'])assert.equal(searchPageKeyword('https://www.douyin.com'+prefix+encodeURIComponent('金茂 住宅 + A/B')),'金茂 住宅 + A/B');
 for(const url of ['https://evil.example/search/new','https://douyin.com.evil.example/jingxuan/search/new','https://www.douyin.com/user/search/new','https://www.douyin.com/search/new?modal_id=123','https://www.douyin.com/jingxuan/search/new?modal_id=123','https://www.douyin.com/jingxuan','https://www.douyin.com/jingxuan/search/%ZZ'])assert.equal(searchPageKeyword(url),null);
});

test('home hydration dropping characters retypes once, and persistent mismatch never submits',async()=>{
 for(const options of [{resetFirstInput:true},{resetEveryInput:true}]){
  const f=await fixture(options);try{
   if(options.resetEveryInput){await assert.rejects(navigateSearch(f.page,'金茂 住宅',fast),/STOP_SEARCH_INPUT_MISMATCH/);assert.deepEqual(f.api,[]);}
   else{const audit=await navigateSearch(f.page,'金茂 住宅',fast);assert.deepEqual(audit.attempts[0].inputAttempts.map(a=>a.matched),[false,true]);assert.deepEqual(f.api,['金茂 住宅']);}
  }finally{await f.close();}
 }
});

test('jingxuan result restoration, scroll and explicit empty endpoint use the same keyword context',async()=>{
 const f=await fixture({initial:'金茂府',routePrefix:'/jingxuan/search/'});try{
  await f.page.goto('https://www.douyin.com/');
  await f.page.locator('main').evaluate(el=>{el.innerHTML='<article class="search-result-card" data-e2e-vid="7690238024572292003" style="height:3000px">fixture</article>';});
  await assertSearchContext(f.page,'金茂府');
  await assert.rejects(assertSearchContext(f.page,'wrong'),/STOP_SEARCH_CONTEXT_LOST/);
  assert.equal((await scrollSearchResults(f.page,{keyword:'金茂府'})).available,true);
  await f.page.locator('main').evaluate(el=>{el.innerHTML='<div>暂无搜索结果</div>';window.scrollTo(0,0);});
  assert.equal((await searchEndUi(f.page,'金茂府')).visible,true);
  assert.equal((await searchEndUi(f.page,'wrong')).visible,false);
  await waitForInitialSearch(f.page,{flush:async()=>{},awemes:new Map(),searchPages:[{keyword:'金茂府',hasMore:false,noteIds:[]}]},{timeoutMs:100,pollMs:1});
  await assert.rejects(waitForInitialSearch(f.page,{flush:async()=>{},awemes:new Map(),searchPages:[{keyword:'wrong',hasMore:false,noteIds:[]}]},{timeoutMs:50,pollMs:1}),/SEARCH_INITIAL_RESULTS_NOT_READY/);
 }finally{await f.close();}
});

test('a button click alone, a changed URL alone and a wrong-keyword page are not success',async()=>{
 for(const options of [{initial:'old',inert:true},{initial:'new',noFreshResponse:true},{wrongKeyword:'old'}]){
  const f=await fixture(options);try{
   await assert.rejects(navigateSearch(f.page,'new',{...fast,timeoutMs:500}),/STOP_SEARCH_SUBMIT_UNCONFIRMED/);
  }finally{await f.close();}
 }
});

test('late response from a SAME-keyword request created before submission cannot certify search',async()=>{
 const f=await fixture({initial:'new',noFreshResponse:true});try{
  await f.page.goto('https://www.douyin.com/');
  const started=f.page.waitForRequest(r=>r.url().includes('old=1'));
  await f.page.evaluate(()=>{void fetch('/aweme/v1/web/general/search/single/?keyword=new&old=1');});await started;
  const navigation=navigateSearch(f.page,'new',{...fast,timeoutMs:700});
  // Release the old response after the search button really was clicked.
  await f.page.waitForFunction(()=>submissions.length===1);f.releaseOld();
  await assert.rejects(navigation,/STOP_SEARCH_SUBMIT_UNCONFIRMED/);
 }finally{f.releaseOld();await f.close();}
});

test('gateway response retries only the original keyword via UI with a fixed budget',async()=>{
 const f=await fixture({statuses:[502,503,200]});try{
  const audit=await navigateSearch(f.page,'金茂府',{...fast,retryDelaysMs:[0,0]});
  assert.deepEqual(audit.attempts.map(a=>a.status),['gateway_error','gateway_error','ready']);
  assert.deepEqual(f.api,['金茂府','金茂府','金茂府']);assert.ok(f.documents.every(p=>p==='/'));
 }finally{await f.close();}
});

test('persistent gateway stops after 3 searches and retains attempts; HTTP200 gateway body is not success',async()=>{
 for(const options of [{statuses:[502]},{gatewayBodyOnOk:true}]){
  const f=await fixture(options);try{
   await assert.rejects(navigateSearch(f.page,'same',{...fast,retryDelaysMs:[0,0]}),e=>{
    assert.match(e.message,/STOP_SEARCH_GATEWAY_ERROR/);assert.equal(e.searchNavigation.attempts.length,3);return true;
   });assert.deepEqual(f.api,['same','same','same']);assert.ok(f.documents.every(p=>p==='/'));
  }finally{await f.close();}
 }
});

test('login, visible CAPTCHA and security restriction never trigger automatic search retries',async()=>{
 for(const body of ['登录后即可搜索','安全验证 拖动滑块','<iframe id="nocaptcha-container" style="width:300px;height:100px"></iframe>','操作频繁']){
  const f=await fixture({body});try{
   await assert.rejects(navigateSearch(f.page,'same',{...fast,retryDelaysMs:[0,0]}),/STOP_(?:LOGIN_REQUIRED|PLATFORM_RESTRICTION)/);
   assert.deepEqual(f.api,[]);assert.equal(f.documents.length,1);
  }finally{await f.close();}
 }
});

test('manual-login mode signals unfinished search and collector explicitly re-submits after human login',async()=>{
 const f=await fixture({body:'登录后即可搜索'});try{
  const audit=await navigateSearch(f.page,'same',{...fast,allowManualLogin:true});
  assert.equal(audit.awaitingManualLogin,true);assert.equal(audit.attempts[0].status,'awaiting_manual_login');assert.deepEqual(f.api,[]);
  const source=readFileSync(new URL('./collector.mjs',import.meta.url),'utf8');
  assert.match(source,/if\(initialSearch\.awaitingManualLogin\)activeSearch=await navigateSearch\(page,task.keyword/);
  assert.match(source,/let prepared=await prepareSearch\(activeSearch\)/);
 }finally{await f.close();}
});

test('missing/ambiguous input or search buttons fail closed instead of guessing or direct-link fallback',async()=>{
 for(const body of [
  '<main>no search input</main>',
  '<input data-e2e="searchbar-input"><input data-e2e="searchbar-input">',
  '<input data-e2e="searchbar-input">',
  '<input data-e2e="searchbar-input"><button>搜索</button><button>搜索</button>',
 ]){
  const f=await fixture({body});try{
   await assert.rejects(navigateSearch(f.page,'same',{...fast,timeoutMs:450}),/STOP_SEARCH_(?:INPUT|SUBMIT)_UNAVAILABLE/);
   assert.deepEqual(f.api,[]);assert.ok(f.documents.every(p=>p==='/'));
  }finally{await f.close();}
 }
});

test('stop during gateway backoff prevents a new submission',async()=>{
 const f=await fixture({statuses:[502]});let stopped=false;try{
  await assert.rejects(navigateSearch(f.page,'same',{...fast,retryDelaysMs:[1000,1000],shouldStop:async()=>stopped,
   onObservation:()=>{stopped=true;}}),/STOP_REQUESTED/);
  assert.deepEqual(f.api,['same']);
 }finally{await f.close();}
});

test('stop before navigation or after typing prevents search submission',async()=>{
 const f=await fixture();try{
  await assert.rejects(navigateSearch(f.page,'same',{...fast,shouldStop:async()=>true}),/STOP_REQUESTED/);
  assert.deepEqual(f.documents,[]);
  await f.page.goto('https://www.douyin.com/');
  await assert.rejects(navigateSearch(f.page,'same',{...fast,shouldStop:async()=>f.page.evaluate(()=>document.querySelector('input').value==='same')}),/STOP_REQUESTED/);
  assert.deepEqual(f.api,[]);assert.deepEqual(await f.page.evaluate(()=>submissions),[]);
 }finally{await f.close();}
});

test('invalid input/budgets fail before any browser action; search navigation contains no direct search goto',async()=>{
 for(const retryDelaysMs of [[0,0,0],[Infinity],[-1]])await assert.rejects(navigateSearch({},'same',{retryDelaysMs}),/BUDGET_INVALID/);
 await assert.rejects(navigateSearch({},' '),/KEYWORD_INVALID/);
 await assert.rejects(navigateSearch({},'same',{typingDelayMs:-1}),/OPTIONS_INVALID/);
 const source=readFileSync(new URL('./douyin-browser.mjs',import.meta.url),'utf8');
 assert.doesNotMatch(source,/page\.goto\(searchUrl/);
 assert.match(source,/page\.goto\('https:\/\/www\.douyin\.com\/'/);
});
