// Observe fatal exits without intercepting them or converting them to success.
import fs from 'node:fs';
import path from 'node:path';
const safeCode=error=>/^[A-Z][A-Z0-9_]{0,63}$/.test(error?.code||'')?error.code:'UNCLASSIFIED';
export function installWorkerDiagnostics(worker,{processObject=process}={}) {
  const directory=path.join(path.resolve(worker),'runs');
  const file=path.join(directory,'worker-process-'+processObject.pid+'.jsonl');
  const record=(reason,details={})=>{
    const event={schemaVersion:1,at:new Date().toISOString(),pid:processObject.pid,reason,...details};
    try{fs.mkdirSync(directory,{recursive:true});fs.appendFileSync(file,JSON.stringify(event)+'\n');}
    catch{console.warn('[Worker diagnostic] persistence_unavailable');}
  };
  record('started');
  processObject.on('uncaughtExceptionMonitor',(error,origin)=>{
    // No raw error message, credentials, signed URLs or arbitrary argument dumps.
    const frames=String(error?.stack||'').split('\n').filter(line=>/^\s+at /.test(line))
      .slice(0,8).map(line=>line.replace(/https?:\/\/[^\s)]+/g,'[remote-url]').slice(0,500));
    record('uncaught_exception',{origin,code:safeCode(error),frames});
  });
  processObject.on('exit',exitCode=>record('exited',{exitCode}));
  return {file,record};
}
