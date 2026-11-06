import fs from 'node:fs/promises';
import path from 'node:path';
import {spawn} from 'node:child_process';

export function humanRecoveryCandidate(state){
 return state?.requiresHuman===true && ['login','captcha'].includes(state.kind)
  && !['ready','resolved'].includes(state.status) && Boolean(state.incidentId);
}

// Called only by the original supervisor's idle wait entry. Never claims tasks.
export function automaticRecoveryWait({gate,root,workerRoot,shouldStop,runRecovery,readKeyword,readFailure,now=Date.now}){
 const attempted=new Map();let lastCheck=-Infinity;
 return async()=>{
  if(await shouldStop())return true;
  if(now()-lastCheck<1500)return false;
  lastCheck=now();
  const state=await gate.read();
  if(!humanRecoveryCandidate(state))return false;
  const previous=attempted.get(state.incidentId);if(previous&&(previous.done||now()<previous.nextAt))return false;
  const attempt=(previous?.attempt||0)+1,startedAt=now();
  attempted.set(state.incidentId,{attempt,done:true});
  const keyword=readKeyword?await readKeyword():await fs.readFile(path.join(workerRoot,'runs','worker_status.json'),'utf8').then(text=>{
   const status=JSON.parse(text.replace(/^\uFEFF/,''));return status.currentKeyword||status.tasks?.at(-1)?.keyword||'';
  });
  if(await shouldStop())return true;
  console.log('[自动恢复等待] '+state.platform+' / '+state.machine+' / '+state.workerId+'；请在浏览器完成人工登录或验证码，核验后自动续采，无需回车或CONFIRM。');
  const args=[path.join(root,'src','login-auto-recovery.mjs'),'--worker-root',workerRoot];
  if(keyword)args.push('--verification-keyword',keyword);
  const code=runRecovery?await runRecovery(args):await new Promise((resolve,reject)=>{
   const child=spawn(process.execPath,args,{stdio:'inherit',windowsHide:false});
   child.once('error',reject);child.once('exit',code=>resolve(code??1));
  });
  if(code!==0&&attempt<3){
   const failure=await (readFailure?readFailure():fs.readFile(path.join(workerRoot,'.state','login-auto-recovery-error.json'),'utf8').then(JSON.parse)).catch(()=>null);
   if(failure?.retryable===true&&failure.at>=startedAt&&failure.at<=now()+5000)attempted.set(state.incidentId,{attempt,done:false,nextAt:now()+60000*attempt});
  }
  if(code!==0)console.warn('[自动恢复等待] 本次页面恢复未确认，原保护保留；请检查当前窗口诊断。');
  return shouldStop();
 };
}
