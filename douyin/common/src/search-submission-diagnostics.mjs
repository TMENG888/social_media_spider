// Passive evidence only. Does not submit, retry, or change search acceptance.
import {safeUrl,safeText} from './page-diagnostics.mjs';
export const SEARCH_TRACE_VERSION='douyin-search-submit-evidence-20261114-v1';
export function createSearchSubmissionTrace(page,observation,{now=Date.now,limit=60}={}){
 const started=now(),events=[],listeners=[];
 observation.diagnosticVersion=SEARCH_TRACE_VERSION;observation.events=events;
 const mark=(event,details={})=>{try{
  events.push({at:new Date(now()).toISOString(),elapsedMs:Math.max(0,now()-started),event,...details});
  if(events.length>limit){events.shift();observation.droppedEvents=(observation.droppedEvents||0)+1;}
 }catch{}};
 const listen=(name,handler)=>{page.on(name,handler);listeners.push([name,handler]);};
 const relevant=request=>request.isNavigationRequest()||/\/general\/search(?:\/|$)/.test(new URL(request.url()).pathname);
 listen('request',request=>{try{if(relevant(request))mark('request',{url:safeUrl(request.url()),method:request.method(),navigation:request.isNavigationRequest()});}catch{}});
 listen('response',response=>{try{if(relevant(response.request()))mark('response',{url:safeUrl(response.url()),httpStatus:response.status()});}catch{}});
 listen('requestfailed',request=>{try{if(relevant(request))mark('request_failed',{url:safeUrl(request.url()),error:safeText(request.failure()?.errorText)});}catch{}});
 listen('framenavigated',frame=>{try{if(frame===page.mainFrame())mark('main_frame_navigated',{url:safeUrl(frame.url())});}catch{}});
 mark('before_submit',{url:safeUrl(page.url()),inputMatched:observation.inputAttempts?.at(-1)?.matched??null});
 return {mark,close({responseConfirmed=false,urlMatched=false}={}){
  for(const [name,handler]of listeners){try{page.off(name,handler);}catch{}}
  observation.finalUrl=safeUrl(page.url());observation.elapsedMs=Math.max(0,now()-started);
  observation.confirmation={responseConfirmed,urlMatched,inputMatched:observation.currentInputMatched??null};
  observation.missingConfirmation=Object.entries(observation.confirmation).filter(([,v])=>v!==true).map(([k])=>k);
  mark('finished',{stage:observation.stage,url:observation.finalUrl,...observation.confirmation});
 }};
}
