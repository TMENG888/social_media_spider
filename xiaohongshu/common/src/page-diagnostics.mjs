// Diagnostic observations only: no navigation, task mutation, cookies or request bodies.
import fs from 'node:fs/promises';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import os from 'node:os';
import {monitorEventLoopDelay} from 'node:perf_hooks';
import {inspectClickPage, traceDetailClick} from './detail-click-diagnostics.mjs';
export {traceDetailClick};
import {inspectPlatformAccess} from './platform-access.mjs';
import {createRiskNetworkDiagnostics} from './risk-network-diagnostics.mjs';
export const DIAGNOSTIC_VERSION='page-diagnostics-20261113-risk-network-v6';

export function safeUrl(value) {
  try {
    const u=new URL(String(value));
    if(!['http:','https:','about:'].includes(u.protocol))return '[non-web-url]';
    u.username='';u.password='';u.hash='';
    for(const key of [...u.searchParams.keys()]){
      if(!['keyword','source','type','modal_id','sort_type','publish_time'].includes(key))u.searchParams.delete(key);
    }
    return u.toString();
  }catch{return '[invalid-url]';}
}
export function safeText(value) {
  return String(value??'').replace(/https?:\/\/[^\s"'<>]+/g,safeUrl)
    .replace(/\bauthorization\s*[:=]\s*(?:bearer\s+|basic\s+)?[^\s,;]+/gi,'authorization=[redacted]')
    .replace(/\b(?:set-cookie|cookie)\s*[:=]\s*[^\r\n]*/gi,'cookie=[redacted]')
    .replace(/\b(password|passwd|authorization|cookie|xsec_token|access_token|refresh_token|secret|token)\s*[:=]\s*[^\s,;]+/gi,'$1=[redacted]')
    .slice(0,1800);
}
function safeValue(value,depth=0) {
  if(depth>5)return '[truncated]';
  if(typeof value==='string')return safeText(value);
  if(value==null||typeof value==='number'||typeof value==='boolean')return value;
  if(Array.isArray(value))return value.slice(-60).map(v=>safeValue(v,depth+1));
  if(typeof value==='object')return Object.fromEntries(Object.entries(value).slice(0,60).map(([key,v])=>
    [key,/password|passwd|authorization|cookie|token|secret|storageState/i.test(key)?'[redacted]':safeValue(v,depth+1)]));
  return safeText(value);
}
export function diagnosticError(error) {
  const errors=[];const seen=new Set();
  for(let e=error;e&&errors.length<3&&!seen.has(e);e=e.cause){
    seen.add(e);errors.push({name:safeText(e.name||'Error'),message:safeText(e.message||e)});
  }
  return errors;
}
const stamp=()=>({at:new Date().toISOString(),beijingTime:new Intl.DateTimeFormat('sv-SE',
  {timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'medium',hourCycle:'h23'}).format(new Date())});
export async function appendDiagnosticEvent(file,event) {
  try {await fs.mkdir(path.dirname(file),{recursive:true});await fs.appendFile(file,JSON.stringify(safeValue({...stamp(),diagnosticVersion:DIAGNOSTIC_VERSION,...event}))+'\n','utf8');return true;}
  catch{return false;}
}
async function bounded(work,ms=2500) {
  let timer;
  try{return await Promise.race([Promise.resolve().then(work),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('DIAGNOSTIC_TIMEOUT')),ms);})]);}
  finally{clearTimeout(timer);}
}
// Snapshot only the already loaded DOM. Never reload a failed URL or save
// cookies/storage/scripts. A failed download navigation may leave about:blank.
export async function captureDiagnosticHtml(page) {
  return page.evaluate(()=>{
    const clone=document.documentElement.cloneNode(true);
    clone.querySelectorAll('script,template,base,iframe,object,embed').forEach(el=>el.remove());
    const redact=value=>String(value).replace(/(["']?(?:password|passwd|authorization|cookie|access_token|refresh_token|xsec_token|secret|token)["']?\s*[:=]\s*)[^\s,;<>]+/gi,'$1[redacted]');
    const url=value=>{
      try{
        const u=new URL(value,location.href);
        if(!['http:','https:','about:'].includes(u.protocol))return '[removed]';
        u.username='';u.password='';u.hash='';
        for(const key of [...u.searchParams.keys()])if(!['keyword','source','type','modal_id','sort_type','publish_time'].includes(key))u.searchParams.delete(key);
        return u.href;
      }catch{return '[removed]';}
    };
    for(const el of [clone,...clone.querySelectorAll('*')]){
      for(const attr of [...el.attributes]){
        if(/^on/i.test(attr.name)||/password|passwd|authorization|cookie|token|secret|nonce|srcdoc|srcset|action|formaction/i.test(attr.name))el.removeAttribute(attr.name);
        else if(['href','src','poster','data'].includes(attr.name))el.setAttribute(attr.name,url(attr.value));
        else el.setAttribute(attr.name,redact(attr.value));
      }
      if(el.matches('input,textarea,select')){
        el.removeAttribute('value');el.removeAttribute('checked');
        if(el.tagName!=='INPUT')el.textContent='[form value removed]';
      }
      if(el.matches('meta[http-equiv],meta[name]'))el.remove();
    }
    const walker=document.createTreeWalker(clone,NodeFilter.SHOW_TEXT|NodeFilter.SHOW_COMMENT);
    const remove=[];while(walker.nextNode()){
      const node=walker.currentNode;
      if(node.nodeType===Node.COMMENT_NODE)remove.push(node);else node.textContent=redact(node.textContent);
    }
    remove.forEach(node=>node.remove());
    let head=clone.querySelector('head');if(!head){head=document.createElement('head');clone.prepend(head);}
    const charset=document.createElement('meta');charset.setAttribute('charset','utf-8');head.prepend(charset);
    const csp=document.createElement('meta');csp.setAttribute('http-equiv','Content-Security-Policy');
    csp.setAttribute('content',"default-src 'none'; style-src 'unsafe-inline'; img-src data:; form-action 'none'; base-uri 'none'");head.prepend(csp);
    return '<!DOCTYPE html>\n'+clone.outerHTML;
  });
}
export function diagnosticReasons(evidence) {
  const reasons=[];
  const layoutFailure=/^layout_(?:click_failed|not_confirmed)$/.test(evidence.stage||'')
    || evidence.errors?.some(error=>/STOP_SEARCH_LAYOUT_UNCONFIRMED/.test(error.message||''));
  if(evidence.closed)reasons.push('browser_page_closed');
  if(evidence.access?.kind)reasons.push('platform_'+evidence.access.kind+'_required');
  if(evidence.context?.matches===false)reasons.push('search_url_keyword_mismatch');
  if(evidence.errors?.some(error=>/SEARCH_INITIAL_RESULTS_NOT_READY/.test(error.message||'')))reasons.push('search_initial_results_not_ready');
  if(evidence.errors?.some(error=>/SEARCH_INITIAL_RESPONSE_FAILED/.test(error.message||'')))reasons.push('search_initial_response_failed');
  if(evidence.details?.searchReadiness?.dom?.visibleFrames?.length)reasons.push('visible_frame_present_not_classified');
  const controls=evidence.dom?.singleColumnControls;
  if(evidence.platform==='抖音'&&layoutFailure&&Array.isArray(controls)){
    if(!controls.length)reasons.push('single_column_control_not_found');
    else {
      const target=controls.at(-1);
      if(!target.visible)reasons.push('last_matching_control_hidden');
      else if(target.disabled)reasons.push('last_matching_control_disabled');
      else if(!target.inViewport)reasons.push('last_matching_control_outside_viewport');
      else if(target.obscured)reasons.push('last_matching_control_obscured');
    }
  }
  if(layoutFailure&&evidence.dom?.cards?.mounted>0&&evidence.dom.cards.uniqueIdCards===0)reasons.push('mounted_cards_without_unique_post_id');
  return reasons;
}
function contextFor(url,platform,keyword) {
  try{
    const u=new URL(url);
    const douyinRoute=u.pathname.match(/^\/(?:jingxuan\/)?search\/(.+)$/);
    const current=platform==='小红书'?u.searchParams.get('keyword'):
      douyinRoute?decodeURIComponent(douyinRoute[1]):null;
    const route=platform==='小红书'?/(^|\.)xiaohongshu\.com$/i.test(u.hostname)&&/^\/search_result\/?$/.test(u.pathname):
      /(^|\.)douyin\.com$/i.test(u.hostname)&&Boolean(douyinRoute)&&!u.searchParams.has('modal_id');
    return {matches:Boolean(route&&current===keyword),observedKeyword:safeText(current),expectedKeyword:safeText(keyword)};
  }catch{return {matches:false,observedKeyword:null,expectedKeyword:safeText(keyword)};}
}
export function createPageDiagnostics({page,platform,keyword,outputDir,workerId='',runId='',pageRole='collection',limit=60}){
  const timeline=[],listeners=[],network=[],pending=new Map(),requests=new WeakMap();
  let riskDiagnostics=null;
  try{riskDiagnostics=createRiskNetworkDiagnostics({page,platform,keyword,outputDir,workerId,runId,pageRole});}catch{}
  let sequence=0,lastCapture=null,requestSequence=0;
  const loopDelay=monitorEventLoopDelay({resolution:50});loopDelay.enable();
  const runtime=()=>({rssBytes:process.memoryUsage().rss,uptimeSeconds:Math.round(process.uptime()),
    eventLoopDelayMs:{max:Math.round(loopDelay.max/1e6),mean:Number.isFinite(loopDelay.mean)?Math.round(loopDelay.mean/1e6):null}});
  const networkState=()=>({recent:network.slice(-60),pending:[...pending.values()].slice(-30).map(r=>({...r,elapsedMs:Date.now()-r.startedMs}))});
  const networkEvent=event=>{network.push({...stamp(),...event});if(network.length>120)network.shift();};
  const journal=path.join(outputDir,'page-diagnostics',`detail-actions-${process.pid}-${pageRole.replace(/[^a-z0-9_-]/gi,'_')}.jsonl`);
  const persist=async event=>{
    try{await bounded(async()=>{
      await fs.mkdir(path.dirname(journal),{recursive:true});
      const size=await fs.stat(journal).then(s=>s.size).catch(()=>0);
      if(size>8*1024*1024)await fs.rename(journal,journal+'.previous');
      if(!await appendDiagnosticEvent(journal,{platform,keyword,workerId,runId,...event}))throw new Error('DIAGNOSTIC_JOURNAL_WRITE_FAILED');
    },1500);}catch{console.warn('[Page diagnostics] Action journal unavailable; collection continues.');}
  };
  const mark=(stage,details={})=>{
    riskDiagnostics?.setStage(stage);
    const event={sequence:++sequence,...stamp(),stage,url:safeUrl(page?.url?.()),details:safeValue(details)};
    timeline.push(event);if(timeline.length>limit)timeline.shift();return event;
  };
  const listenOn=(target,event,handler)=>{try{target?.on(event,handler);listeners.push([target,event,handler]);}catch{}};
  const listen=(event,handler)=>listenOn(page,event,handler);
  const observeDetail=async(stage,details={})=>{
    try{
      const started=Date.now();mark(stage,details);
      const event={...stamp(),stage,details:safeValue(details),url:safeUrl(page?.url?.()),closed:!page||page.isClosed()};
      if(!event.closed){
        try{event.observation=await bounded(()=>page.evaluate(inspectClickPage,{noteId:details.noteId||''}),800);}
        catch(e){event.observationError=safeText(e.message);}
      }
      event.probeElapsedMs=Date.now()-started;event.runtime=runtime();event.network=networkState();
      mark(stage+'_observed',{...details,...event});
      await persist(event);
      console.log('[Detail action] '+stage+' / '+safeText(details.noteId||'')+' / '+(event.observation?.state||event.observationError||'page_closed')+' / '+Math.round(details.elapsedMs||0)+'ms');
      return event;
    }catch(e){return {stage,observationError:safeText(e.message)};}
  };
  try{
    listenOn(page.context(),'close',()=>mark('browser_context_closed'));
    listenOn(page.context().browser(),'disconnected',()=>mark('browser_control_disconnected'));
  }catch{}
  listen('request',request=>{try{
    const u=new URL(request.url()),type=request.resourceType();
    if(!/(^|\.)(xiaohongshu\.com|xhscdn\.com)$/i.test(u.hostname)||!['document','xhr','fetch','image','script'].includes(type))return;
    const entry={requestId:++requestSequence,url:safeUrl(request.url()),method:request.method(),resourceType:type,startedMs:Date.now()};
    requests.set(request,entry);pending.set(entry.requestId,entry);
    if(pending.size>200)pending.delete(pending.keys().next().value);
  }catch{}});
  const finish=(request,failed=false)=>{try{
    const entry=requests.get(request);if(!entry)return;
    pending.delete(entry.requestId);
    if(failed||['document','xhr','fetch'].includes(entry.resourceType))networkEvent({...entry,event:failed?'request_failed':'request_finished',elapsedMs:Date.now()-entry.startedMs,
      ...(failed?{failure:safeText(request.failure()?.errorText)}:{})});
  }catch{}};
  listen('requestfinished',request=>finish(request));
  listen('requestfailed',request=>finish(request,true));
  listen('response',response=>{try{
    const entry=requests.get(response.request());if(!entry)return;
    entry.httpStatus=response.status();
    if(['document','xhr','fetch'].includes(entry.resourceType)||entry.httpStatus>=400)networkEvent({...entry,event:'response',elapsedMs:Date.now()-entry.startedMs});
  }catch{}});
  listen('framenavigated',frame=>{try{if(frame===page.mainFrame())mark('main_frame_navigated',{url:safeUrl(frame.url())});}catch{}});
  listen('popup',popup=>{try{mark('popup_opened',{url:safeUrl(popup.url())});}catch{}});
  listen('close',()=>mark('page_closed'));
  listen('crash',()=>mark('page_crashed'));
  listen('pageerror',error=>mark('page_javascript_error',{errors:diagnosticError(error)}));
  listen('requestfailed',request=>{try{if(request.isNavigationRequest())mark('navigation_request_failed',
    {url:safeUrl(request.url()),failure:safeText(request.failure()?.errorText)});}catch{}});
  listen('response',response=>{try{
    const request=response.request();
    if(!request.isNavigationRequest()||request.frame()!==page.mainFrame())return;
    const headers=response.headers();
    mark('navigation_response',{url:safeUrl(response.url()),httpStatus:response.status(),
      contentType:safeText(headers['content-type']||''),contentDisposition:safeText(headers['content-disposition']||''),
      contentLength:safeText(headers['content-length']||''),location:headers.location?safeUrl(new URL(headers.location,response.url()).href):null});
  }catch{}});
  listen('download',download=>{try{mark('navigation_download_started',{
    url:safeUrl(download.url()),suggestedFilename:safeText(path.basename(download.suggestedFilename()))});}catch{}});
  mark('diagnostics_attached',{pageRole});
  console.log('[Page diagnostics ready] '+DIAGNOSTIC_VERSION+' '+platform+' / '+pageRole);
  const capture=async(stage,error,details={})=>{
    try {
      mark(stage,{...details,errors:diagnosticError(error)});
      const rawUrl=page?.url?.()||'';
      const evidence={schemaVersion:1,diagnosticVersion:DIAGNOSTIC_VERSION,nodeVersion:process.version,...stamp(),platform,keyword:safeText(keyword),workerId,runId,
        computer:os.hostname(),pid:process.pid,stage,pageRole,url:safeUrl(rawUrl),closed:!page||page.isClosed(),
        captureSource:'bound_playwright_page',
        context:(pageRole.includes('detail')||details.noteId)?{matches:null,kind:'detail',expectedKeyword:safeText(keyword)}:contextFor(rawUrl,platform,keyword),errors:diagnosticError(error),details:safeValue(details)};
      evidence.runtime=runtime();evidence.network=networkState();evidence.actionJournal=path.basename(journal);
      if(!evidence.closed&&details.noteId){
        try{evidence.clickObservation=await bounded(()=>page.evaluate(inspectClickPage,{noteId:details.noteId}),800);}
        catch(e){evidence.clickObservationError=safeText(e.message);}
      }
      if(!evidence.closed){
        evidence.activation={attempted:true,succeeded:false};
        try{await bounded(()=>page.bringToFront(),1500);evidence.activation.succeeded=true;}
        catch(e){evidence.activation.error=safeText(e.message);}
        const host=(()=>{try{return new URL(rawUrl).hostname;}catch{return '';}})();
        evidence.pageIdentity={expectedPlatform:platform,
          platformHostMatches:platform==='小红书'?/(^|\.)xiaohongshu\.com$/i.test(host):/(^|\.)douyin\.com$/i.test(host),
          role:pageRole,actualUrl:safeUrl(rawUrl)};
        try{evidence.access=await bounded(()=>inspectPlatformAccess(page,platform));}catch{}
        try{
          evidence.dom=await bounded(()=>page.evaluate(()=>{
            const visible=el=>{
              const b=el.getBoundingClientRect();if(b.width<=0||b.height<=0)return false;
              for(let n=el;n;n=n.parentElement){const s=getComputedStyle(n);
                if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0||n.getAttribute('aria-hidden')==='true')return false;}
              return true;
            };
            const cards=[...document.querySelectorAll('.search-result-card')];
            const xhs=[...document.querySelectorAll('section.note-item,.note-item,[data-note-id]')];
            const uniqueIdCards=cards.filter(card=>{
              const own=n=>n.closest('.search-result-card')===card;
              const ids=[...new Set([card,...card.querySelectorAll('[data-e2e-vid]')].filter(own).map(n=>n.getAttribute('data-e2e-vid')).filter(id=>/^\d{15,22}$/.test(id||'')))];
              if(!ids.length)for(const a of card.querySelectorAll('a[href]')){try{const u=new URL(a.href);if(!['www.douyin.com','douyin.com'].includes(u.hostname))continue;const id=u.pathname.match(/^\/(?:video|note)\/(\d{15,22})\/?$/)?.[1]||u.searchParams.get('modal_id');if(own(a)&&/^\d{15,22}$/.test(id||'')&&!ids.includes(id))ids.push(id);}catch{}}
              return ids.length===1;
            }).length;
            const summary=el=>({tag:el?.tagName||null,role:el?.getAttribute('role')||null,
              classes:typeof el?.className==='string'?el.className.slice(0,180):null});
            return {readyState:document.readyState,viewport:{width:innerWidth,height:innerHeight,dpr:devicePixelRatio},
              cards:{mounted:cards.length,visible:cards.filter(visible).length,uniqueIdCards,xhsMounted:xhs.length,xhsVisible:xhs.filter(visible).length},
              detailVisible:[...document.querySelectorAll('#noteContainer,.note-container,[data-e2e="modal-video-container"]')].some(visible),
              verificationFrameVisible:[...document.querySelectorAll('iframe#nocaptcha-container,iframe[src*="rc-verifycenter"]')].some(visible),
              visibleFrames:[...document.querySelectorAll('iframe')].filter(visible).slice(0,8).map(el=>{
                const b=el.getBoundingClientRect();let origin='unknown';try{origin=new URL(el.getAttribute('src')||'about:blank',location.href).origin;}catch{}
                return {origin,width:Math.round(b.width),height:Math.round(b.height)};
              }),
              visibleDialogs:[...document.querySelectorAll('[role="dialog"]')].filter(visible).slice(0,8).map(summary)};
          }));
          evidence.dom.singleColumnControls=await bounded(()=>page.getByText('单列',{exact:true}).evaluateAll(nodes=>nodes.slice(-30).map((el,index)=>{
            const b=el.getBoundingClientRect();let visible=b.width>0&&b.height>0;
            for(let n=el;n;n=n.parentElement){const s=getComputedStyle(n);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0||n.getAttribute('aria-hidden')==='true')visible=false;}
            const x=b.x+b.width/2,y=b.y+b.height/2,inViewport=x>=0&&x<innerWidth&&y>=0&&y<innerHeight;
            const hit=inViewport?document.elementFromPoint(x,y):null;
            return {index:Math.max(0,nodes.length-30)+index,visible,disabled:!!el.disabled||el.getAttribute('aria-disabled')==='true'||!!el.closest('[inert]'),
              inViewport,obscured:!!hit&&hit!==el&&!el.contains(hit),rect:{x:b.x,y:b.y,width:b.width,height:b.height},
              hit:hit?{tag:hit.tagName,classes:typeof hit.className==='string'?hit.className.slice(0,180):null}:null};
          })));
        }catch(e){evidence.domError=safeText(e.message);}
        try{evidence.tabs=page.context().pages().slice(0,12).map(p=>({url:safeUrl(p.url()),closed:p.isClosed(),current:p===page}));}catch{}
      }
      evidence.reasons=diagnosticReasons(evidence);
      if(evidence.errors?.some(e=>/locator\.click.*Timeout/s.test(e.message||''))&&evidence.clickObservation?.state==='target_url_detail_present')evidence.reasons.push('click_timeout_but_target_detail_present');
      if(evidence.clickObservationError)evidence.reasons.push('detail_observation_unavailable');
      if(evidence.pageIdentity?.platformHostMatches===false)evidence.reasons.push('bound_page_outside_platform_or_browser_error');
      evidence.timeline=[...timeline];
      await persist({stage:'failure_capture_started',details:safeValue(details),errors:evidence.errors,runtime:evidence.runtime,network:evidence.network});
      const directory=path.join(outputDir,'page-diagnostics');
      await fs.mkdir(directory,{recursive:true});
      const id=Date.now()+'-'+randomUUID().slice(0,8);
      const jsonFile=path.join(directory,id+'.json'),imageFile=path.join(directory,id+'.png'),htmlFile=path.join(directory,id+'.html');
      evidence.htmlSnapshotKind='current_rendered_dom_redacted';
      if(!evidence.closed){
        try{
          const html=await bounded(()=>captureDiagnosticHtml(page),3000);
          await fs.writeFile(htmlFile,html,{encoding:'utf8',flag:'wx'});evidence.html=path.basename(htmlFile);
        }catch(e){evidence.htmlError=safeText(e.message);}
        try{await bounded(()=>page.screenshot({path:imageFile,timeout:3000,fullPage:false,
          mask:[page.locator('input,canvas,iframe,[class*="qr"],[class*="QR"],[data-e2e*="qr"]')]}),3500);evidence.screenshot=path.basename(imageFile);}
        catch(e){evidence.screenshotError=safeText(e.message);}
      }
      evidence.network=networkState();evidence.timeline=[...timeline];
      if(riskDiagnostics)evidence.riskNetwork=await riskDiagnostics.flush();
      await fs.writeFile(jsonFile,JSON.stringify(safeValue(evidence),null,2),{encoding:'utf8',flag:'wx'});
      lastCapture={jsonFile,htmlFile:evidence.html?htmlFile:null,screenshot:evidence.screenshot?imageFile:null,at:evidence.at,stage,reasons:evidence.reasons};
      console.warn('[Page diagnostics] '+DIAGNOSTIC_VERSION+' '+platform+' '+stage+' / '+evidence.reasons.join(',')+' / '+jsonFile);
      return lastCapture;
    }catch(e){console.warn('[Page diagnostics] Capture unavailable; original collection error retained.');return {stage,captureError:safeText(e.message)};}
  };
  return {mark,capture,observeDetail,get lastCapture(){return lastCapture;},dispose(){riskDiagnostics?.dispose();loopDelay.disable();for(const [target,event,handler]of listeners){try{target.off(event,handler);}catch{}}}};
}
