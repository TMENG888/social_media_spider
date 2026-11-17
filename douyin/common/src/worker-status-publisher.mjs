// Regenerable worker progress only. Durable collection data, task acknowledgements
// and protection markers must continue using their existing strict write paths.
import {BackgroundStateWriter} from './background-state-writer.mjs';
import {publishOpsState,flushOpsState} from './ops-state.mjs';
export const WORKER_STATUS_WRITE_VERSION='douyin-worker-status-retry-20261113-v1';
export class WorkerStatusPublisher{
  constructor({file,writerOptions={},publish=publishOpsState,flushPublished=flushOpsState,
    onWarning=e=>console.warn('[工作进度后台保存] '+JSON.stringify(e))}){
    Object.assign(this,{file,publish,flushPublished,onWarning});
    this.writer=new BackgroundStateWriter({...writerOptions,file,onWarning});
  }
  warn(error){try{this.onWarning(error);}catch{}}
  async write(value){
    try{
      // Freeze each observation before the caller mutates its in-memory status.
      const snapshot=structuredClone(value);
      const queued=this.writer.enqueue(snapshot);
      if(!queued){this.warn({code:'WORKER_STATUS_WRITER_CLOSED',file:this.file});return false;}
      // The dashboard remains an independent best-effort projection even while
      // the internal progress file is busy. Neither is task-completion evidence.
      try{this.publish(this.file,snapshot);}catch(error){this.warn({code:error.code||'OPS_PUBLISH_FAILED',message:error.message});}
      return true;
    }catch(error){this.warn({code:error.code||'WORKER_STATUS_QUEUE_FAILED',message:error.message});return false;}
  }
  async close(){
    let saved=false;
    try{saved=await this.writer.close({timeoutMs:8000});}
    catch(error){this.warn({code:error.code||'WORKER_STATUS_CLOSE_FAILED',message:error.message});}
    try{await this.flushPublished(this.file);}catch(error){this.warn({code:error.code||'OPS_FLUSH_FAILED',message:error.message});}
    if(!saved)this.warn({code:'WORKER_STATUS_LAST_SNAPSHOT_NOT_SAVED',file:this.file});
    return saved;
  }
}
