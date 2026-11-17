// Strict state persistence: transient sharing errors get bounded retries.
// Evidence failures must never replace the original file error.
import fs from 'node:fs/promises';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
export const CYCLE_WRITE_VERSION='douyin-cycle-write-retry-20261114-v2';
export const CYCLE_WRITE_RETRY_DELAYS_MS=Object.freeze([50,100,200,400,800,1000,1000,1000]);
const transient=new Set(['EPERM','EACCES','EBUSY']);
const queues=new Map();
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const errorInfo=e=>({name:e?.name,code:e?.code,errno:e?.errno,syscall:e?.syscall,message:String(e?.message||e).slice(0,1800),stack:String(e?.stack||'').slice(0,4000)});
async function stat(io,file){try{const s=await io.stat(file);return {exists:true,size:s.size,mode:s.mode,mtime:s.mtime.toISOString(),isFile:s.isFile()};}catch(e){return {exists:e.code==='ENOENT'?false:null,error:errorInfo(e)};}}

// Snapshot at submission, and preserve publication order within this process.
// A delayed collecting write must not overwrite a later stopped/resting write.
export function writeCycleState(file,state,options={}){
 const snapshot=JSON.stringify(state),key=path.resolve(file);
 const previous=queues.get(key)||Promise.resolve();
 const work=previous.then(()=>writeSnapshot(file,JSON.parse(snapshot),options));
 const tail=work.catch(()=>{});queues.set(key,tail);
 void tail.then(()=>{if(queues.get(key)===tail)queues.delete(key);});
 return work;
}

async function writeSnapshot(file,state,{io=fs,now=Date.now,sleep=delay,
 retryDelaysMs=CYCLE_WRITE_RETRY_DELAYS_MS,logFailure}={}){
 if(!Array.isArray(retryDelaysMs)||retryDelaysMs.length>8||retryDelaysMs.some(ms=>!Number.isFinite(ms)||ms<0||ms>1000))throw new Error('CYCLE_STATE_RETRY_BUDGET_INVALID');
 const started=now(),tmp=file+'.tmp-'+process.pid+'-'+randomUUID(),steps=[];
 let stage='mkdir',retries=0,waitedMs=0,firstError=null,lastError=null;
 async function record(event,error,nextDelayMs=null){
  const value={version:CYCLE_WRITE_VERSION,at:new Date(now()).toISOString(),event,pid:process.pid,parentPid:process.ppid,node:process.version,
   stage,elapsedMs:Math.max(0,now()-started),steps:[...steps],file,tmp,phase:state.phase,round:state.round,workerId:state.workerId,
   cycleId:state.cycleId,retries,maxRetries:retryDelaysMs.length,waitedMs,nextDelayMs,error:error?errorInfo(error):null,
   firstError:firstError?errorInfo(firstError):null,target:await stat(io,file),temporary:await stat(io,tmp),
   memory:process.memoryUsage(),uptimeSeconds:process.uptime(),lockOwner:'not_observed'};
  try{
   if(logFailure)await logFailure(value);
   else{
    const log=path.join(path.dirname(file),'cycle-state-write-diagnostics.jsonl');
    try{if((await io.stat(log)).size>1024*1024){await io.rm(log+'.1',{force:true});await io.rename(log,log+'.1');}}catch{}
    await io.appendFile(log,JSON.stringify(value)+'\n','utf8');
   }
  }catch{console.warn('[轮次状态诊断] 日志写入失败；保留原始文件操作结果');}
  if(event==='retry_exhausted'||event==='write_failed')console.error('[轮次状态写入失败] '+JSON.stringify(value));
  else console.warn('[轮次状态保存] '+JSON.stringify({version:CYCLE_WRITE_VERSION,event,stage,retries,waitedMs,nextDelayMs,code:error?.code,elapsedMs:value.elapsedMs}));
 }
 async function operation(name,work){
  stage=name;
  while(true){
   try{await work();steps.push({stage,elapsedMs:now()-started});return;}
   catch(error){
    firstError ||= error;lastError=error;
    if(!transient.has(error.code)||retries>=retryDelaysMs.length){
     await record(transient.has(error.code)?'retry_exhausted':'write_failed',error);throw error;
    }
    const ms=retryDelaysMs[retries++];await record('retry_scheduled',error,ms);
    await sleep(ms);waitedMs+=ms;
   }
  }
 }
 await operation('mkdir',()=>io.mkdir(path.dirname(file),{recursive:true}));
 await operation('write_tmp',()=>io.writeFile(tmp,JSON.stringify(state)+'\n','utf8'));
 await operation('rename',()=>io.rename(tmp,file));
 if(retries)await record('write_recovered',lastError);
 return {version:CYCLE_WRITE_VERSION,elapsedMs:Math.max(0,now()-started),retries,waitedMs};
}
