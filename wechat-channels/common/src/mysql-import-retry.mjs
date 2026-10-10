import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
export const isTransient = text => /ECONNRESET|ECONNREFUSED|ETIMEDOUT|EHOSTUNREACH|ENETUNREACH|EAI_AGAIN|PROTOCOL_CONNECTION_LOST|socket hang up|read ECONNRESET/i.test(text);
export async function retryImport(run, pause, attempts=3) {
  for (let attempt=1; attempt<=attempts; attempt++) {
    const result=await run();
    if (result.code===0 || !isTransient(result.error) || attempt===attempts) return result.code ?? 2;
    const seconds=5 * 2**(attempt-1);
    console.log(JSON.stringify({event:'mysql_import_transient_retry',attempt,nextAttempt:attempt+1,seconds,scope:'import_only_no_video_replay'}));
    await pause(seconds*1000);
  }
}
if (process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  const importer=fileURLToPath(new URL('./mysql-import.mjs',import.meta.url));
  const run=()=>new Promise(resolve=>{
    const child=spawn(process.execPath,[importer,...process.argv.slice(2)],{stdio:['ignore','pipe','pipe'],windowsHide:true});
    let error='';
    child.stdout.on('data',data=>process.stdout.write(data));
    child.stderr.on('data',data=>{error=(error+data).slice(-16384);process.stderr.write(data);});
    child.on('error',e=>resolve({code:2,error:e.code || ''}));
    child.on('close',code=>resolve({code:code ?? 2,error}));
  });
  process.exitCode=await retryImport(run,ms=>new Promise(resolve=>setTimeout(resolve,ms)));
}
