import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
import {performance} from 'node:perf_hooks';
export const isTransient = text => /ENOTFOUND|ECONNRESET|ECONNREFUSED|ETIMEDOUT|EHOSTUNREACH|ENETUNREACH|EAI_AGAIN|EPIPE|PROTOCOL_CONNECTION_LOST|PROTOCOL_SEQUENCE_TIMEOUT|ER_CON_COUNT_ERROR|socket hang up|read ECONNRESET|MYSQL_IMPORT_LOCK_TIMEOUT|ER_LOCK_WAIT_TIMEOUT|ER_LOCK_DEADLOCK|Lock wait timeout exceeded|Deadlock found when trying to get lock/i.test(text);
const networkErrors=new Set(['ENOTFOUND','EAI_AGAIN','ECONNRESET','ECONNREFUSED','ETIMEDOUT',
  'EHOSTUNREACH','ENETUNREACH','EPIPE','PROTOCOL_CONNECTION_LOST','PROTOCOL_SEQUENCE_TIMEOUT']);
const replaySafe=result=>result.retrySafe===true&&result.commitState==='not_attempted';
const retained={localDataRetained:true,taskConfirmed:false,scope:'import_only_no_video_replay'};
export function importReceipt(stdout,stderr){
  let receipt=null;
  for(const line of (stdout+'\n'+stderr).split(/\r?\n/)){
    try{const parsed=JSON.parse(line);if(parsed?.status==='failed'&&parsed.errorCode)receipt=parsed;}catch{}
  }
  return receipt;
}
export async function retryImport(run, pause, attempts=3, {
  standbyMs=0, now=()=>performance.now(), shouldStop=null,
  log=entry=>console.log(JSON.stringify(entry)),
}={}) {
  if(!Number.isSafeInteger(attempts)||attempts<1||attempts>5)throw new Error('IMPORT_RETRY_POLICY_INVALID');
  if(!Number.isFinite(standbyMs)||standbyMs<0||standbyMs>120*60000)throw new Error('IMPORT_STANDBY_POLICY_INVALID');
  // Poll only between imports. Never kill an in-flight COMMIT to honour a stop:
  // its receipt must establish the transaction outcome before we return.
  const stopped=()=>Boolean(shouldStop?.());
  const stop=()=>{log({event:'mysql_import_wait_cancelled',reason:'stop_requested',...retained});return 75;};
  const wait=async ms=>{
    if(!shouldStop){await pause(ms);return true;}
    const until=now()+ms;
    for(let left=until-now();left>0;left=until-now()){
      if(stopped())return false;
      await pause(Math.min(1000,left));
    }
    return !stopped();
  };
  let deadline=null,standbyAttempt=0;
  for (let attempt=1;;attempt++) {
    if(stopped())return stop();
    const result=await run();
    if(result.code===0){
      if(attempt>1)log({event:deadline===null?'mysql_import_retry_recovered':'mysql_import_standby_recovered',attempt,standbyAttempt});
      return 0;
    }
    // The driver receipt, not an error message or an exit code, authorises replay.
    const transient=isTransient(result.error)&&replaySafe(result);
    if(!transient){
      log({event:'mysql_import_failure_not_retried',attempt,commitState:result.commitState||'unverified',...retained});
      return result.code ?? 2;
    }
    if(stopped())return stop();
    if(attempt<attempts){
      const seconds=5 * 2**(attempt-1);
      log({event:'mysql_import_transient_retry',attempt,nextAttempt:attempt+1,seconds,...retained});
      if(!await wait(seconds*1000))return stop();
      continue;
    }
    if(standbyMs>0&&networkErrors.has(result.error)){
      if(deadline===null){
        deadline=now()+standbyMs;
        log({event:'mysql_import_standby_started',version:'channels-mysql-standby-20261023-v1',
          maxStandbySeconds:standbyMs/1000,errorCode:result.error,...retained});
      }
      const remaining=Math.max(0,deadline-now());
      if(remaining>0){
        const delay=Math.min(30000*2**Math.min(standbyAttempt,2),remaining);
        log({event:'mysql_import_standby_wait',standbyAttempt:++standbyAttempt,
          seconds:delay/1000,remainingSeconds:Math.ceil(remaining/1000),errorCode:result.error,...retained});
        // Each importer has exited and closed its connections before this wait.
        if(!await wait(delay))return stop();
        if(now()<deadline)continue;
      }
      log({event:'mysql_import_standby_exhausted',attempt,maxStandbySeconds:standbyMs/1000,...retained});
    }
    log({event:'mysql_import_circuit_open',attempt,maxAttempts:attempts,
      commitState:result.commitState,...retained});
    return result.code ?? 2;
  }
}
if (process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
 try {
  const option=name=>{const i=process.argv.indexOf(name);return i>=0?process.argv[i+1]:null;};
  const standbyMinutes=Number(option('--standby-minutes')??process.env.CHANNELS_MYSQL_STANDBY_MINUTES??'30');
  if(!Number.isFinite(standbyMinutes)||standbyMinutes<0||standbyMinutes>120)throw new Error('IMPORT_STANDBY_POLICY_INVALID');
  const stopFile=option('--stop-file')||(process.env.WECHAT_WORKER_ROOT?path.join(process.env.WECHAT_WORKER_ROOT,'.state','stop.requested'):null);
  let signalStop=false;
  process.on('SIGINT',()=>{signalStop=true;});process.on('SIGTERM',()=>{signalStop=true;});
  const shouldStop=()=>{
    if(signalStop)return true;
    if(!stopFile)return false;
    try{fs.statSync(stopFile);return true;}catch(error){if(error.code==='ENOENT')return false;throw Error('IMPORT_STOP_STATE_UNREADABLE');}
  };
  const importerArgs=[];
  for(let i=2;i<process.argv.length;i++){
    if(['--stop-file','--standby-minutes'].includes(process.argv[i])){
      if(!process.argv[i+1]||process.argv[i+1].startsWith('--'))throw Error('IMPORT_RETRY_POLICY_INVALID');
      i++;
    }else importerArgs.push(process.argv[i]);
  }
  const receiptPath=option('--status')||path.join(path.dirname(path.resolve(option('--posts')||'')),'mysql_import_status.json');
  let prior=null;
  try{prior=JSON.parse(fs.readFileSync(receiptPath,'utf8').replace(/^\uFEFF/,''));}
  catch(error){if(error.code!=='ENOENT')throw new Error('MYSQL_IMPORT_RECEIPT_UNREADABLE');}
  const replayBlocked=prior?.status==='failed'&&['unknown','committed'].includes(prior.commitState);
  const importer=fileURLToPath(new URL('./mysql-import.mjs',import.meta.url));
  const run=()=>new Promise(resolve=>{
    const child=spawn(process.execPath,[importer,...importerArgs],{stdio:['ignore','pipe','pipe'],windowsHide:true});
    let error='',output='';
    child.stdout.on('data',data=>{output=(output+data).slice(-16384);process.stdout.write(data);});
    child.stderr.on('data',data=>{error=(error+data).slice(-16384);process.stderr.write(data);});
    child.on('error',e=>resolve({code:2,error:e.code || ''}));
    child.on('close',code=>{
      const receipt=importReceipt(output,error);
      resolve({code:code ?? 2,error:receipt?.errorCode||'',retrySafe:receipt?.retrySafe===true,
        commitState:receipt?.commitState||'unverified'});
    });
  });
  if(replayBlocked){
    console.error(JSON.stringify({event:'mysql_import_commit_reconciliation_required',status:'failed',commitState:prior.commitState,
      retrySafe:false,localDataRetained:true,taskConfirmed:false}));process.exitCode=2;
  }else process.exitCode=await retryImport(run,ms=>new Promise(resolve=>setTimeout(resolve,ms)),3,
    {standbyMs:standbyMinutes*60000,shouldStop});
 } catch {
  console.error(JSON.stringify({event:'mysql_import_retry_guard_failed',...retained}));process.exitCode=2;
 }
}
