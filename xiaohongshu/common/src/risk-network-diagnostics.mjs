// Passive observations only. Never fetch, replay, intercept or alter a request.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash,randomUUID} from 'node:crypto';

export const RISK_DIAGNOSTIC_VERSION='xhs-risk-network-20261113-v1';
const MAX_BODY=64*1024, MAX_EVENTS=240;
const sessions=new Map();
const stamp=()=>({at:new Date().toISOString(),beijingTime:new Intl.DateTimeFormat('sv-SE',
  {timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'medium',hourCycle:'h23'}).format(new Date())});
const timeout=async(promise,ms)=>{
  let timer;try{return await Promise.race([promise,new Promise(resolve=>{timer=setTimeout(()=>resolve(null),ms);})]);}
  finally{clearTimeout(timer);}
};
export function riskUrl(value){
  try{
    const u=new URL(String(value));
    if(!['http:','https:','about:'].includes(u.protocol))return {url:'[non-web-url]'};
    const parameterNames=[...new Set([...u.searchParams.keys()].filter(k=>/^[a-zA-Z0-9_-]{1,40}$/.test(k)))].slice(0,30);
    // Keep no query values, including search words, verification messages or links.
    const errorCode=/^-?\d{1,10}$/.test(u.searchParams.get('error_code')||'')?Number(u.searchParams.get('error_code')):null;
    return {url:u.origin==='null'?u.protocol+u.pathname:u.origin+u.pathname,parameterNames,
      hasXsecToken:u.searchParams.has('xsec_token'),hasXsecSource:u.searchParams.has('xsec_source'),
      ...(errorCode===null?{}:{errorCode})};
  }catch{return {url:'[invalid-url]'};}
}
function riskMessage(value){
  const s=String(value??'');
  for(const [pattern,label]of [[/访问频次异常|访问频繁|操作频繁|请勿频繁/,'访问频次异常'],
    [/检测到异常访问|本次访问已被限制|安全限制/,'异常访问限制'],[/网络连接异常/,'网络连接异常'],
    [/帐号异常|账号异常/,'账号异常'],[/浏览器异常/,'浏览器异常'],[/验证码|安全验证|滑块/,'需要验证'],
    [/登录|登陆/,'需要登录']])if(pattern.test(s))return label;
  return s?'[message omitted]':null;
}
function code(value){return /^-?\d{1,10}$/.test(String(value??''))?Number(value):null;}
export function riskBodySummary(body){
  const result={};
  for(const [name,o]of [['root',body],['data',body?.data]]){
    if(!o||typeof o!=='object'||Array.isArray(o))continue;
    const item={};
    for(const key of ['code','result','error_code','errorCode','errno']){const n=code(o[key]);if(n!==null)item[key]=n;}
    if(typeof o.success==='boolean')item.success=o.success;
    const message=riskMessage(o.msg??o.message??o.error_msg);if(message)item.messageCategory=message;
    if(Object.keys(item).length)result[name]=item;
  }
  return result;
}
function selectedHeaders(headers,salt){
  const out={};
  for(const [raw,value]of Object.entries(headers||{})){
    const key=raw.toLowerCase();
    if(['resultpolicy','verifytype','verifybiz','x-ratelimit-limit','x-ratelimit-remaining'].includes(key)){
      const n=code(value);if(n!==null)out[key]=n;
    }else if(['riskuuid','verifyuuid','x-request-id','x-trace-id','x-b3-traceid'].includes(key)){
      out[key+'Hash']=createHash('sha256').update(salt+String(value)).digest('hex').slice(0,20);
    }else if(key==='verifymsg')out.verifyMessagePresent=Boolean(value);
    else if(key==='retry-after'){
      if(/^\d{1,10}$/.test(String(value)))out.retryAfterSeconds=Number(value);
      else if(Number.isFinite(Date.parse(value)))out.retryAfterAt=new Date(value).toISOString();
    }
  }
  return out;
}
function isRisk(event){
  return event.headers?.resultpolicy===400||[403,429,461,471].includes(event.httpStatus)
    ||event.path?.errorCode===300013||/\/website-login\/(?:error|captcha|native)/.test(event.path?.url||'')
    ||Object.values(event.business||{}).some(o=>Object.entries(o).some(([k,v])=>
      (/code|errno|result/i.test(k)&&Number(v)>=300000&&Number(v)<400000)||(/Category$/.test(k)&&v!=='[message omitted]')));
}
function sessionFor(file){
  if(sessions.has(file))return sessions.get(file);
  const s={salt:randomUUID(),recent:[],requests:[],tail:Promise.resolve(),queued:0,dropped:0,writeErrors:0,sequence:0};
  s.write=event=>{
    if(s.queued>=64){s.dropped++;return;}
    s.queued++;
    s.tail=s.tail.then(async()=>{
      await fs.mkdir(path.dirname(file),{recursive:true});
      const size=await fs.stat(file).then(o=>o.size).catch(()=>0);
      if(size>=4*1024*1024){
        await fs.rm(file+'.2',{force:true});
        await fs.rename(file+'.1',file+'.2').catch(e=>{if(e.code!=='ENOENT')throw e;});
        await fs.rename(file,file+'.1');
      }
      await fs.appendFile(file,JSON.stringify({version:RISK_DIAGNOSTIC_VERSION,...event})+'\n','utf8');
    }).catch(()=>{s.writeErrors++;if(s.writeErrors===1)console.warn('[Risk diagnostics] Journal unavailable; collection continues.');})
      .finally(()=>{s.queued--;});
  };
  sessions.set(file,s);
  // Bounded cache; a recorder retains its own session even after eviction.
  if(sessions.size>16)sessions.delete(sessions.keys().next().value);
  return s;
}
export function createRiskNetworkDiagnostics({page,platform,keyword,outputDir,workerId='',runId='',pageRole=''}){
  if(platform!=='小红书')return null;
  const file=path.join(outputDir,'page-diagnostics',`risk-network-${process.pid}.jsonl`),s=sessionFor(file);
  const pageId=randomUUID().slice(0,12),listeners=[],pending=new Set(),requests=new WeakMap();
  let stage='diagnostics_attached',disposed=false,activeReads=0;
  const base=()=>({...stamp(),sequence:++s.sequence,pid:process.pid,pageId,pageRole,keyword,workerId,runId,stage});
  const counts=()=>{const now=Date.now();s.requests=s.requests.filter(t=>t>now-300000);return {
    pageScope:'attached pages in this collector/output directory',last60s:s.requests.filter(t=>t>now-60000).length,last300s:s.requests.length};};
  const record=(event,{persist=true}={})=>{
    const e={...base(),...event};s.recent.push(e);if(s.recent.length>MAX_EVENTS)s.recent.shift();
    if(persist)s.write(e);
    if(isRisk(e))s.write({...base(),event:'risk_detected',triggerSequence:e.sequence,requestCounts:counts(),recent:s.recent.slice(-80)});
    return e;
  };
  const on=(event,handler)=>{page.on(event,handler);listeners.push([event,handler]);};
  const observe=request=>{
    try{
      const u=new URL(request.url()),type=request.resourceType();
      if(!/(^|\.)xiaohongshu\.com$/i.test(u.hostname)||!['document','xhr','fetch'].includes(type))return null;
      const old=requests.get(request);if(old)return old;
      const prev=request.redirectedFrom?.();const prior=prev?observe(prev):null;
      const h=request.headers?.()||{};
      const e={requestId:randomUUID().slice(0,12),path:riskUrl(request.url()),method:request.method(),resourceType:type,
        startedMs:Date.now(),startedStage:stage,referer:h.referer?riskUrl(h.referer):null,
        redirectedFromRequestId:prior?.requestId||null,redirectedFrom:prev?riskUrl(prev.url()):null};
      requests.set(request,e);s.requests.push(e.startedMs);if(s.requests.length>20000)s.requests.splice(0,10000);
      record({...e,event:'request_started'});return e;
    }catch{return null;}
  };
  on('request',observe);
  on('response',response=>{
    try{
      const r=observe(response.request());if(!r)return;
      const h=response.headers(),headers=selectedHeaders(h,s.salt),httpStatus=response.status();
      const event=record({...r,event:'response',elapsedMs:Date.now()-r.startedMs,httpStatus,headers,
        location:h.location?riskUrl(new URL(h.location,response.url()).href):null,
        contentType:(h['content-type']||'').split(';')[0].slice(0,80),requestCounts:counts()});
      const length=Number(h['content-length']);
      // Never consume unbounded/unknown-size payloads or ordinary HTML/content bodies.
      const json=/json/i.test(h['content-type']||'');
      if(!json||!Number.isFinite(length)||length<=0||length>MAX_BODY){
        if(json||isRisk(event))record({event:'body_observation_skipped',requestId:r.requestId,
          reason:!json?'non_json':length>MAX_BODY?'declared_body_too_large':'unknown_or_empty_declared_length'});
        return;
      }
      if(activeReads>=4||pending.size>=8){record({event:'body_observation_skipped',requestId:r.requestId,reason:'observer_busy'});return;}
      activeReads++;
      const work=(async()=>{
        try{
          const body=await response.body();
          if(body.length>MAX_BODY){record({event:'body_observation_skipped',requestId:r.requestId,reason:'decoded_body_too_large'});return;}
          const business=riskBodySummary(JSON.parse(body.toString('utf8')));
          if(Object.keys(business).length)record({...r,event:'business_response',httpStatus,headers,business,elapsedMs:Date.now()-r.startedMs});
        }catch{record({event:'body_observation_unavailable',requestId:r.requestId});}
        finally{activeReads--;}
      })();pending.add(work);work.finally(()=>pending.delete(work));
    }catch{/* A diagnostic failure must never escape into collection. */}
  });
  on('requestfailed',request=>{try{const r=observe(request);if(r){const raw=String(request.failure()?.errorText||'');
    record({...r,event:'request_failed',failureCode:raw.match(/net::[A-Z0-9_]+/)?.[0]||'[unclassified]',elapsedMs:Date.now()-r.startedMs});}}catch{}});
  on('framenavigated',frame=>{try{if(frame===page.mainFrame())record({event:'main_frame_navigated',path:riskUrl(frame.url())});}catch{}});
  const snapshot=()=>({version:RISK_DIAGNOSTIC_VERSION,journal:file,pageId,requestCounts:counts(),
    lastRisk:s.recent.findLast(e=>isRisk(e))||null,
    recent:s.recent.slice(-100),activeBodyReads:activeReads,queuedWrites:s.queued,droppedWrites:s.dropped,writeErrors:s.writeErrors,
    bodyPolicy:'Only declared JSON <=64KiB; top-level/nested status codes and categorical messages. No raw bodies, headers, cookies or query values.',
    scope:'Counts cover observed document/xhr/fetch requests on attached pages, not account-wide or IP-wide traffic.'});
  return {setStage(value){stage=String(value).slice(0,100);},snapshot,
    async flush(ms=700){await timeout(Promise.allSettled([...pending]),Math.min(ms,500));await timeout(s.tail,Math.min(ms,500));return snapshot();},
    dispose(){if(disposed)return;disposed=true;for(const [event,handler]of listeners){try{page.off(event,handler);}catch{}}}
  };
}
