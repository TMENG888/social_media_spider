// Only regenerable monitoring snapshots use this worker. Never use it for
// checkpoint exports, collected data, task acknowledgements or stop requests.
import fs from 'node:fs/promises';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {parentPort,workerData,threadId} from 'node:worker_threads';
const {file,logFile,retryDelaysMs}=workerData;
const version='xhs-background-state-writer-20261110-v1';
const details=e=>({code:e.code||'STATE_WRITE_ERROR',syscall:e.syscall||null,path:e.path||file,dest:e.dest||null,message:e.message,stack:e.stack});
async function log(event){
  try{await fs.appendFile(logFile,JSON.stringify({at:new Date().toISOString(),version,pid:process.pid,threadId,file,...event})+'\n','utf8');return null;}
  catch(e){return details(e);}
}
parentPort.on('message',async({id,value})=>{
  const started=Date.now(),temp=`${file}.tmp-${process.pid}-${threadId}-${randomUUID()}`;
  let retries=0,firstError=null,result;
  try{
    await fs.mkdir(path.dirname(file),{recursive:true});
    await fs.writeFile(temp,JSON.stringify(value,null,2),'utf8');
    while(true){
      try{await fs.rename(temp,file);break;}
      catch(e){
        firstError ||= details(e);
        if(!['EPERM','EBUSY'].includes(e.code)||retries>=retryDelaysMs.length)throw e;
        if(retries===0)await log({event:'replace_retry_started',id,error:firstError});
        await new Promise(r=>setTimeout(r,retryDelaysMs[retries++]));
      }
    }
    result={type:'result',id,ok:true,retries,elapsedMs:Date.now()-started};
    if(retries)result.diagnosticError=await log({...result,event:'replace_recovered',firstError});
  }catch(e){
    result={type:'result',id,ok:false,retries,elapsedMs:Date.now()-started,error:details(e)};
    result.diagnosticError=await log({...result,event:'replace_failed'});
  }finally{
    // Remove only this worker's uniquely named temporary file. The last
    // published snapshot is never deleted to make a replacement succeed.
    await fs.unlink(temp).catch(()=>{});
  }
  parentPort.postMessage(result);
});
