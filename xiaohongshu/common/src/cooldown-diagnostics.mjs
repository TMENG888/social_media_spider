// Diagnostics only. No Redis writes, navigation, retries or task-state changes.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createHash,randomUUID} from 'node:crypto';
export const COOLDOWN_DIAGNOSTIC_VERSION='xhs-cooldown-diagnostics-20261111-v1';
const beijing=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'});
const atom=v=>/^[A-Za-z0-9_.:-]{1,120}$/.test(String(v||''))?String(v):'UNCLASSIFIED';
const known=/\b(?:REDIS_TIMEOUT|REDIS_CLIENT_CLOSED|ECONNRESET|ECONNREFUSED|ETIMEDOUT|EHOSTUNREACH|ENETUNREACH|EAI_AGAIN|ENOTFOUND|WRONGPASS|NOAUTH|NOPERM|WRONGTYPE|MISCONF|READONLY|LOADING|BUSY|OOM|CROSSSLOT|CLUSTERDOWN|MASTERDOWN|NOSCRIPT|LEGACY_COOLDOWN_INVALID|LEGACY_COOLDOWN_OWNER_UNCONFIRMED|NODE_INCIDENT_INVALID|TIMED_COOLDOWN_INVALID|MACHINE_COOLDOWN_STATE_INVALID|COOLDOWN_STATE_INVALID|COOLDOWN_STATE_UNAVAILABLE|RATE_LIMIT_COOLDOWN_ACTIVE|COOLDOWN_MANUAL_REQUIRED|ENOSPC|EACCES|EPERM)\b/g;
export function cooldownErrorChain(error){
 const seen=new Set(),rows=[];
 for(let e=error;e&&rows.length<5&&!seen.has(e);e=e.cause){
  seen.add(e);const message=String(e.message||e),tokens=[...new Set(message.match(known)||[])];
  const name=atom(e.name||'Error'),code=atom(e.code),syntax=name==='SyntaxError';
  const category=syntax?'response_parse':tokens.some(t=>/OWNER|INVALID/.test(t))?'state_validation':tokens.some(t=>/AUTH|PASS|NOPERM/.test(t))?'authentication_or_permission':tokens.some(t=>/^E(?:CONN|TIME|HOST|NET|AI_|NOTFOUND)|REDIS_TIMEOUT/.test(t))||/Socket|Connection/.test(name)?'connection':tokens.length?'redis_or_system':'unclassified';
  // Never retain arbitrary server replies or error strings that could embed data.
  const frames=[...String(e.stack||'').matchAll(/[/\\]([a-z][a-z0-9-]*\.mjs):(\d+):(\d+)/gi)].slice(0,5).map(m=>({file:m[1],line:Number(m[2]),column:Number(m[3])}));
  rows.push({name,code,category,reasonCodes:tokens,messageSha256:createHash('sha256').update(message).digest('hex'),frames,...(e.syscall?{syscall:atom(e.syscall)}:{})});
 }
 return rows;
}
export class CooldownDiagnostics {
 constructor({stateRoot,workerId,machine=os.hostname(),context=()=>({}),clock=()=>Date.now(),writer=null}={}){
  this.directory=stateRoot?path.join(path.dirname(stateRoot),'runs'):null;
  this.workerId=workerId;this.machine=machine;this.context=context;this.clock=clock;this.writer=writer;
  this.sessionId=randomUUID();this.queue=Promise.resolve();this.pending=0;this.dropped=0;this.operations=new Map();this.metadata={};this.initialized=false;
 }
 configure({campaign,scope,group,redisUrl,commandTimeoutMs}={}){
  this.metadata={...this.metadata,...(campaign?{campaign}:{}),...(scope?{scope}:{}),...(group?{group}:{}),...(commandTimeoutMs?{commandTimeoutMs}:{})};
  if(redisUrl)try{const u=new URL(redisUrl);this.metadata.redis={host:u.hostname,port:Number(u.port||6379),database:u.pathname};}catch{}
 }
 event(event,details={}){
  try{
   let context={};try{context=this.context()||{};}catch{}
   const now=this.clock(),record={at:new Date(now).toISOString(),beijingTime:beijing.format(new Date(now)),version:COOLDOWN_DIAGNOSTIC_VERSION,event,machine:this.machine,workerId:this.workerId,pid:process.pid,sessionId:this.sessionId,...this.metadata,
    keyword:String(context.keyword||'').slice(0,160),cycleId:String(context.cycleId||'').slice(0,80),...details};
   if(this.pending>=128){this.dropped++;return;}
   if(this.dropped){record.droppedEvents=this.dropped;this.dropped=0;}
   this.pending++;
   this.queue=this.queue.then(async()=>{
    if(this.writer){await this.writer(record);return;}
    if(!this.directory)return;
    await fs.mkdir(this.directory,{recursive:true});
    if(!this.initialized){
     this.initialized=true;
     for(const name of await fs.readdir(this.directory)){
      const match=/^cooldown-diagnostics-(\d{4}-\d{2}-\d{2})\.jsonl(?:\.1)?$/.exec(name);
      if(match&&Date.parse(match[1]+'T00:00:00+08:00')<now-8*86400000)await fs.unlink(path.join(this.directory,name)).catch(()=>{});
     }
    }
    const file=path.join(this.directory,'cooldown-diagnostics-'+record.beijingTime.slice(0,10)+'.jsonl');
    try{if((await fs.stat(file)).size>2*1024*1024){await fs.unlink(file+'.1').catch(()=>{});await fs.rename(file,file+'.1');}}catch{}
    await fs.appendFile(file,JSON.stringify(record)+'\n','utf8');
   }).catch(()=>{}).finally(()=>{this.pending--;});
  }catch{}
 }
 success(stage,elapsedMs,state=null){
  const now=this.clock(),previous=this.operations.get(stage)||{},changed=state?JSON.stringify([state.active,state.manualRequired,state.untilMs,state.scope]):'';
  if(previous.failed||!previous.loggedAt||now-previous.loggedAt>=60000||changed!==previous.signature){
   this.event(previous.failed?'operation_recovered':'operation_ok',{stage,elapsedMs:Math.round(elapsedMs),...(previous.failed?{sinceFailureMs:now-previous.failedAt}:{}),...(state?{protection:{active:state.active,manualRequired:state.manualRequired,untilMs:state.untilMs,scope:state.scope,serverTime:state.serverTime}}:{})});
   previous.loggedAt=now;
  }
  this.operations.set(stage,{...previous,failed:false,signature:changed,lastSuccessAt:now});
 }
 failure(stage,phase,error,elapsedMs){
  const previous=this.operations.get(stage)||{},now=this.clock();
  this.event('operation_failed',{stage,phase,elapsedMs:Math.round(elapsedMs),lastSuccessAt:previous.lastSuccessAt?new Date(previous.lastSuccessAt).toISOString():null,errors:cooldownErrorChain(error)});
  this.operations.set(stage,{...previous,failed:true,failedAt:previous.failedAt||now});
 }
 async flush(timeoutMs=1000){
  let timer;try{await Promise.race([this.queue,new Promise(resolve=>{timer=setTimeout(resolve,timeoutMs);})]);}finally{clearTimeout(timer);}
 }
}
