// Diagnostic observations only: no navigation, task mutation, cookies or request bodies.
import fs from 'node:fs/promises';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import os from 'node:os';
import {inspectPlatformAccess} from './platform-access.mjs';
export const DIAGNOSTIC_VERSION='page-diagnostics-20261021-search-v2';

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
export function createPageDiagnostics({page,platform,keyword,outputDir,workerId='',runId='',limit=60}){
  const timeline=[],listeners=[];let sequence=0,lastCapture=null;
  const mark=(stage,details={})=>{
    const event={sequence:++sequence,...stamp(),stage,url:safeUrl(page?.url?.()),details:safeValue(details)};
    timeline.push(event);if(timeline.length>limit)timeline.shift();return event;
  };
  const listen=(event,handler)=>{try{page.on(event,handler);listeners.push([event,handler]);}catch{}};
  listen('framenavigated',frame=>{try{if(frame===page.mainFrame())mark('main_frame_navigated',{url:safeUrl(frame.url())});}catch{}});
  listen('popup',popup=>{try{mark('popup_opened',{url:safeUrl(popup.url())});}catch{}});
  listen('close',()=>mark('page_closed'));
  listen('crash',()=>mark('page_crashed'));
  listen('pageerror',error=>mark('page_javascript_error',{errors:diagnosticError(error)}));
  listen('requestfailed',request=>{try{if(request.isNavigationRequest())mark('navigation_request_failed',
    {url:safeUrl(request.url()),failure:safeText(request.failure()?.errorText)});}catch{}});
  mark('diagnostics_attached');
  const capture=async(stage,error,details={})=>{
    try {
      mark(stage,{...details,errors:diagnosticError(error)});
      const rawUrl=page?.url?.()||'';
      const evidence={schemaVersion:1,diagnosticVersion:DIAGNOSTIC_VERSION,nodeVersion:process.version,...stamp(),platform,keyword:safeText(keyword),workerId,runId,
        computer:os.hostname(),pid:process.pid,stage,url:safeUrl(rawUrl),closed:!page||page.isClosed(),
        context:contextFor(rawUrl,platform,keyword),errors:diagnosticError(error),details:safeValue(details)};
      if(!evidence.closed){
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
      evidence.timeline=[...timeline];
      const directory=path.join(outputDir,'page-diagnostics');
      await fs.mkdir(directory,{recursive:true});
      const id=Date.now()+'-'+randomUUID().slice(0,8);
      const jsonFile=path.join(directory,id+'.json'),imageFile=path.join(directory,id+'.png');
      if(!evidence.closed){
        try{await bounded(()=>page.screenshot({path:imageFile,timeout:3000,fullPage:false,
          mask:[page.locator('input,canvas,iframe,[class*="qr"],[class*="QR"],[data-e2e*="qr"]')]}),3500);evidence.screenshot=path.basename(imageFile);}
        catch(e){evidence.screenshotError=safeText(e.message);}
      }
      await fs.writeFile(jsonFile,JSON.stringify(safeValue(evidence),null,2),{encoding:'utf8',flag:'wx'});
      lastCapture={jsonFile,screenshot:evidence.screenshot?imageFile:null,at:evidence.at,stage,reasons:evidence.reasons};
      console.warn('[Page diagnostics] '+DIAGNOSTIC_VERSION+' '+platform+' '+stage+' / '+evidence.reasons.join(',')+' / '+jsonFile);
      return lastCapture;
    }catch(e){console.warn('[Page diagnostics] Capture unavailable; original collection error retained.');return {stage,captureError:safeText(e.message)};}
  };
  return {mark,capture,get lastCapture(){return lastCapture;},dispose(){for(const [event,handler]of listeners){try{page.off(event,handler);}catch{}}}};
}
