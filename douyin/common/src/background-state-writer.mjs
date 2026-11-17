import {Worker} from 'node:worker_threads';
import path from 'node:path';
import fs from 'node:fs/promises';
export const STATE_WRITER_VERSION='xhs-background-state-writer-20261110-v1';
export const STATE_RETRY_DELAYS_MS=Object.freeze([50,100,200,400,800,1000,1000,1000]);
export class BackgroundStateWriter{
  constructor({file,logFile=path.join(path.dirname(file),'state-write-diagnostics.jsonl'),retryDelaysMs=STATE_RETRY_DELAYS_MS,jobTimeoutMs=8000,onWarning=e=>console.warn('[状态文件后台保存] '+JSON.stringify(e))}){
    if(!retryDelaysMs.every(n=>Number.isSafeInteger(n)&&n>=0)||retryDelaysMs.reduce((a,b)=>a+b,0)>=jobTimeoutMs)throw new Error('Invalid state write retry budget');
    Object.assign(this,{file,logFile,retryDelaysMs:[...retryDelaysMs],jobTimeoutMs,onWarning});
    this.sequence=0;this.pending=null;this.inFlight=null;this.worker=null;this.waiters=new Set();this.closing=false;this.closed=false;this.lastResult=null;this.timer=null;
  }
  enqueue(value){
    if(this.closing||this.closed)return false;
    // Bound the queue to the active write plus the newest pending snapshot.
    this.pending={id:++this.sequence,value};
    this.pump();return true;
  }
  warn(error){try{this.onWarning(error);}catch{}}
  wake(){if(!this.inFlight&&!this.pending)for(const f of [...this.waiters])f();}
  failed(worker,error){
    if(this.worker!==worker)return;
    clearTimeout(this.timer);this.timer=null;this.worker=null;
    this.lastResult={ok:false,id:this.inFlight?.id,error};this.inFlight=null;
    this.warn(error);
    void fs.appendFile(this.logFile,JSON.stringify({at:new Date().toISOString(),version:STATE_WRITER_VERSION,event:'worker_failed',file:this.file,error})+'\n','utf8').catch(()=>{});
    // Wait for the old worker to exit before another writer can publish a
    // newer snapshot; an outstanding old rename must not race its successor.
    this.restarting=true;
    void worker.terminate().catch(()=>{}).finally(()=>{this.restarting=false;this.pump();this.wake();});
    this.wake();
  }
  pump(){
    if(this.closed||this.restarting||this.inFlight||!this.pending)return;
    if(!this.worker){
      let worker;
      try{
        worker=new Worker(new URL('./state-write-worker.mjs',import.meta.url),{workerData:{file:this.file,logFile:this.logFile,retryDelaysMs:this.retryDelaysMs}});
        this.worker=worker;
        worker.on('error',e=>this.failed(worker,{code:e.code||'STATE_WRITER_THREAD_ERROR',message:e.message,stack:e.stack}));
        worker.on('exit',code=>{if(this.worker===worker)this.failed(worker,{code:'STATE_WRITER_THREAD_EXIT',exitCode:code});});
        worker.on('message',result=>{
          if(this.worker!==worker||result.type!=='result'||result.id!==this.inFlight?.id)return;
          clearTimeout(this.timer);this.timer=null;this.lastResult=result;this.inFlight=null;
          if(!result.ok)this.warn(result.error);
          if(result.diagnosticError)this.warn({code:'STATE_WRITE_DIAGNOSTIC_FAILED',error:result.diagnosticError});
          worker.unref();this.pump();this.wake();
        });
      }catch(e){
        this.pending=null;this.lastResult={ok:false,error:{code:e.code||'STATE_WRITER_THREAD_START_FAILED',message:e.message}};
        this.warn(this.lastResult.error);this.wake();return;
      }
    }
    const job=this.pending;this.pending=null;this.inFlight=job;
    this.worker.ref();
    const active=this.worker;
    this.timer=setTimeout(()=>this.failed(active,{code:'STATE_WRITER_TIMEOUT',timeoutMs:this.jobTimeoutMs,file:this.file}),this.jobTimeoutMs);
    try{active.postMessage(job);}catch(e){this.failed(active,{code:e.code||'STATE_WRITER_POST_FAILED',message:e.message});}
  }
  async flush(timeoutMs=6000){
    if(!this.inFlight&&!this.pending)return !this.lastResult||this.lastResult.ok;
    return new Promise(resolve=>{
      let timer;
      const done=()=>{clearTimeout(timer);this.waiters.delete(done);resolve(!this.lastResult||this.lastResult.ok);};
      timer=setTimeout(()=>{this.waiters.delete(done);resolve(false);},timeoutMs);
      this.waiters.add(done);
    });
  }
  async close({timeoutMs=6000}={}){
    if(this.closed)return this.lastResult?.ok!==false;
    this.closing=true;
    const flushed=await this.flush(timeoutMs);
    if(!flushed&&this.inFlight)this.warn({code:'STATE_WRITER_CLOSE_TIMEOUT',timeoutMs,file:this.file});
    this.closed=true;clearTimeout(this.timer);this.timer=null;this.pending=null;this.inFlight=null;
    const worker=this.worker;this.worker=null;
    if(worker)await worker.terminate();
    this.wake();return flushed;
  }
}
