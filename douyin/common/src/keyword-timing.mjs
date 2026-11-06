// Diagnostics only: bounded metadata, monotonic spans, no page bodies/credentials.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {AsyncLocalStorage} from 'node:async_hooks';
import {randomUUID} from 'node:crypto';
import {performance} from 'node:perf_hooks';
export const TIMING_VERSION='keyword-timing-20261106-v1';
export const DETAIL_VERSION='keyword-timing-detail-20261106-v2';
const storage=new AsyncLocalStorage(),session=randomUUID(),active=new Map(),stops=new Set();
let config=null,sequence=0,disabled=false,pulse=null;
const strings=['platform','workerId','keyword','topic','runId','articleId','lane','kind','sample','disposition','action','reason','errorCode','errorKind','stopOrigin','priorStatus','outcome'];
const numbers=['attempt','round','pages','replyPages','comments','threads','missingReplies','beforeCount','afterCount','deltaCount','newToLocal','rootEnd','repliesComplete','expanded','availableControls','zeroGrowth','scrollTop','scrollHeight','pending','completed','failed','inserted','updated','posts','cached','plannedMs','deadlineAtMs','resumeAtMs','priorRetained','elapsedMs'];
function safe(meta={}){const r={};for(const k of strings)if(meta[k]!=null)r[k]=String(meta[k]).replace(/[\x00-\x1f]/g,' ').slice(0,160);for(const k of numbers)if(Number.isFinite(meta[k])||typeof meta[k]==='boolean')r[k]=meta[k];return r;}
function emit(value){
 if(!config||disabled)return;
 try{
  const file=path.join(config.directory,`${new Date().toISOString().slice(0,10)}-${process.pid}-${session}.jsonl`);
  const base={version:TIMING_VERSION,detailVersion:DETAIL_VERSION,session,pid:process.pid,machine:os.hostname(),at:new Date().toISOString(),monoMs:performance.now(),...safe(config)};
  if(fs.existsSync(file)&&fs.statSync(file).size>32*1024*1024){fs.appendFileSync(file,JSON.stringify({...base,event:'marker',stage:'telemetry_limit',reason:'file_size_limit'})+'\n');disabled=true;return;}
  fs.appendFileSync(file,JSON.stringify({...base,...value})+'\n','utf8');
 }catch{disabled=true;}
}
function errorFacts(error){
 try{
  const text=String(error?.code||error?.message||''),code=text.match(/^([A-Z][A-Z0-9_]{2,80})(?:[：:\s]|$)/)?.[1];
  const kind=/Timeout|timed out/i.test(String(error?.name)+' '+text)?'timeout':code?.startsWith('STOP_')?'protected_stop':code==='LEASE_LOST'?'lease_lost':'operation_error';
  const origin=/LOGIN_REQUIRED/.test(code)?'login_required':/SECURITY_CHALLENGE|PLATFORM_RESTRICTION/.test(code)?'platform_protection':/LEASE_LOST/.test(code)?'lease_lost':/REDIS|CONTROL/.test(code)?'control_channel':'unspecified';
  return {errorCode:code||'UNCLASSIFIED_ERROR',errorKind:kind,stopOrigin:origin};
 }catch{return {errorCode:'UNCLASSIFIED_ERROR'};}
}
export function configureTiming(value){
 try{if(!value?.directory)return;fs.mkdirSync(value.directory,{recursive:true});config={...value};disabled=false;emit({event:'configured',clock:'host_utc_duration_monotonic'});
  if(!pulse){pulse=setInterval(()=>{try{for(const entry of [...active.values()].sort((a,b)=>a.start-b.start).slice(0,32))emit({event:'heartbeat',...entry.context,elapsedMs:performance.now()-entry.start});}catch{}},30000);pulse.unref?.();}
 }catch{}
}
export function timingContext(){return storage.getStore()||{};}
function begin(stage,meta){const parent=storage.getStore()||{},id=`${session}-${++sequence}`,context={...safe(config),...safe(parent),...safe(meta),id,parentId:parent.id||null,stage};const start=performance.now();emit({event:'begin',...context});active.set(id,{context,start});return {context,start};}
function finish(context,start,status,error){active.delete(context.id);emit({event:'end',...context,status,durationMs:Math.max(0,performance.now()-start),...(error?errorFacts(error):{})});}
export async function timed(stage,fn,meta={}){
 if(!config||disabled)return fn();
 const {context,start}=begin(stage,meta);return storage.run(context,async()=>{let error;try{return await fn();}catch(e){error=e;throw e;}finally{finish(context,start,error?'failed':'ok',error);}});
}
export function timedSync(stage,fn,meta={}){
 if(!config||disabled)return fn();
 const {context,start}=begin(stage,meta);return storage.run(context,()=>{let error;try{return fn();}catch(e){error=e;throw e;}finally{finish(context,start,error?'failed':'ok',error);}});
}
export const contentTiming=(meta,fn)=>timed('content',fn,{lane:'foreground',sample:'visited',...meta});
export function timingDisposition(value){try{const state=storage.getStore();if(state){state.disposition=String(value);emit({event:'disposition',id:state.id,...safe(state)});}}catch{}}
export function timingMarker(stage,meta={}){try{emit({event:'marker',...safe(storage.getStore()),...safe(meta),stage,parentId:storage.getStore()?.id||null});}catch{}}
export function timingProgress(stage,meta={}){timingMarker(stage,meta);}
export function timingFailure(stage,error,meta={}){timingMarker(stage,{...meta,...errorFacts(error)});}
export function timingStop(stopOrigin,meta={}){try{const c=storage.getStore()||config||{},key=[c.runId,c.keyword,stopOrigin].join('|');if(stops.has(key))return;if(stops.size>256)stops.clear();stops.add(key);timingMarker('stop_requested',{...meta,stopOrigin});}catch{}}
