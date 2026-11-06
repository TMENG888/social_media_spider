import {configureTiming,timed,timedSync,contentTiming,timingDisposition,timingMarker,timingProgress,timingFailure,timingStop} from './keyword-timing.mjs';
import path from 'node:path';
import {openRecoveryPage} from './recovery-navigation.mjs';
import {startLoginBridge} from './login-bridge.mjs';
import os from 'node:os';
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';
import {waitForAutomaticRecovery} from './recovery-auto-check.mjs';
import {loginFailure,LOGIN_RECOVERY_VERSION} from './login-diagnostics.mjs';
import {openRecovery,recoveryState,workerStatePath,assertWorkerIdle,watchManualSearch} from './recovery-login-check.mjs';
const common=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const platform=path.basename(path.dirname(common));
const index=process.argv.indexOf('--worker-root');
if(index<0||!process.argv[index+1])throw new Error('worker-root is required');
const worker=path.resolve(process.argv[index+1]),workerId=path.basename(worker);
if(!['抖音','小红书'].includes(platform)||!/^worker-\d+$/.test(workerId)||path.dirname(worker)!==path.dirname(common))
 throw new Error('工作节点必须是当前平台目录下的 worker-*，禁止跨平台解除。');
configureTiming({directory:path.join(worker,'runs','timing'),platform,workerId,lane:'hold'});
const stopFiles=['supervisor.stop','stop.requested'];
let initialStops=null,stateRootForStop=null;
async function stopSnapshot(){return Promise.all(stopFiles.map(name=>fs.readFile(path.join(stateRootForStop,name),'utf8').catch(error=>{if(error.code==='ENOENT')return null;throw error;})));}
async function assertNoNewStop(){if(initialStops&&JSON.stringify(await stopSnapshot())!==JSON.stringify(initialStops))throw new Error('OPERATOR_CANCELLED：收到新的人工停止请求，自动恢复已取消。');}
let bridge=null;
let context,recovery,searchWatch,verificationKeyword='',stage='READ_QUEUE';
const onStage=value=>{stage=value;console.log('[登录恢复阶段] '+value);};
async function requireVerifiedLogin(...args){return timed('login_verification',()=>requireVerifiedLoginTimingImpl(...args),{keyword:verificationKeyword,lane:'hold'});}
async function requireVerifiedLoginTimingImpl(){
 return waitForAutomaticRecovery(context,platform,{keyword:verificationKeyword,watch:searchWatch,assertNoNewStop,
  onState:async check=>{
   timingProgress('login_poll',{outcome:check.ok?'ready':'waiting'});
   bridge?.verification(check);
   console.log('[自动恢复核验] '+JSON.stringify(check));if(!check.ok)onStage('WAITING_AUTO_VERIFICATION');
   const diagnostic={platform,machine:os.hostname(),worker:workerId,at:new Date().toISOString(),...check};
   const target=path.join(stateRootForStop,'login-auto-recovery-status.json'),temporary=target+'.tmp-'+process.pid;
   await fs.writeFile(temporary,JSON.stringify(diagnostic));await fs.rename(temporary,target);
  }});
}
try{
 console.log('[登录恢复] '+platform+' / '+os.hostname()+' / '+workerId);
 console.log('[登录恢复版本] '+LOGIN_RECOVERY_VERSION);
 console.log('只操作此节点的浏览器登录资料和监控事件，不领取任务、不入库、不清除人工停止标记。');
 onStage('READ_QUEUE');
 const queue=JSON.parse((await fs.readFile(path.join(worker,'tasks','task-queue.json'),'utf8')).replace(/^\uFEFF/,''));
 onStage('VALIDATE_WORKER');
 const stateRoot=workerStatePath(worker,queue,platform);
 stateRootForStop=stateRoot;initialStops=await stopSnapshot();
 onStage('CHECK_IDLE');
 await assertWorkerIdle(stateRoot);
 const keywordIndex=process.argv.indexOf('--verification-keyword');
 if(keywordIndex>=0){
  const keyword=process.argv[keywordIndex+1];
  const last=JSON.parse((await fs.readFile(path.join(worker,'runs','worker_status.json'),'utf8')).replace(/^\uFEFF/,''));
  if(typeof keyword!=='string'||!keyword.trim()||keyword.length>100||/[\x00-\x1f]/.test(keyword)||keyword!==(last.currentKeyword||last.tasks?.at(-1)?.keyword))
   throw new Error('VERIFICATION_KEYWORD_MISMATCH：只允许核验此节点刚刚受阻的检索词。');
  verificationKeyword=keyword;
 }
 if(platform==='小红书'&&process.env.XHS_CDP_URL)
  throw new Error('CUSTOM_CDP_CONFIGURED：此终端配置了外部采集浏览器，不能用默认节点资料代替；请先核对实际浏览器配置，事件保留。');
 onStage('OPEN_MONITOR');
 recovery=await openRecovery(common,workerId,platform,{onStage});
 onStage('READ_MONITOR_SNAPSHOT');
 const snapshot=await recovery.snapshot();
 onStage('VALIDATE_MONITOR_STATE');
 const state=recoveryState(snapshot);
 if(!verificationKeyword&&state.incident?.requiresHuman&&['login','captcha'].includes(state.incident.kind)){
  const last=JSON.parse((await fs.readFile(path.join(worker,'runs','worker_status.json'),'utf8')).replace(/^\uFEFF/,''));
  const lastKeyword=last.currentKeyword||last.tasks?.at(-1)?.keyword;
  if(typeof lastKeyword==='string'&&lastKeyword.trim()&&lastKeyword.length<=100&&!/[\x00-\x1f]/.test(lastKeyword))verificationKeyword=lastKeyword;
 }
 const profile=path.join(stateRoot,'browser-profile');
 onStage('PREPARE_PROFILE');
 await fs.mkdir(profile,{recursive:true});
 onStage('LAUNCH_BROWSER');
 try{
  context=await chromium.launchPersistentContext(profile,{
   executablePath:path.join(common,'runtime','browsers','chrome-win64','chrome.exe'),
   headless:false,viewport:null
  });
 }catch{
  throw new Error('BROWSER_PROFILE_UNAVAILABLE：浏览器登录资料可能正在被采集进程占用；请先安全停止采集，勿删除锁文件或强杀浏览器。事件未解除。');
 }
 if(verificationKeyword)searchWatch=watchManualSearch(context,platform,verificationKeyword);
 onStage(verificationKeyword?'OPEN_VERIFICATION_SEARCH':'OPEN_HOMEPAGE');
 const page=context.pages()[0]||await context.newPage();
 await openRecoveryPage(page,platform==='抖音'?'https://www.douyin.com/':verificationKeyword?'https://www.xiaohongshu.com/search_result?keyword='+encodeURIComponent(verificationKeyword):'https://www.xiaohongshu.com/explore',{assertAllowed:async()=>{await assertNoNewStop();const current=await recovery.snapshot();recoveryState(current);if(current.incidentRaw!==snapshot.incidentRaw||current.sharedRaw!==snapshot.sharedRaw)throw Error('INCIDENT_CHANGED');}});
 console.log(verificationKeyword?'无需输入或搜索任何关键词。已打开本节点受阻搜索页：'+verificationKeyword+'；请在原页面完成人工验证，保留此页，验证通过后会自动恢复，无需回车或输入CONFIRM。会核对真实搜索响应和页面，首页登录成功不能代替搜索验证。':'无需输入或搜索任何关键词。若已显示自己的头像/“我”，且没有登录或验证提示，无需额外操作。');
 console.log('[自动恢复] 请只在浏览器完成登录或验证；程序轮询核验后自动恢复，不需要回车或CONFIRM。');

 try{
  bridge=await startLoginBridge({common,worker,context,page,platform,incidentId:state.incident?.incidentId,
   assertAllowed:async()=>{
    await assertNoNewStop();const current=await recovery.snapshot();recoveryState(current);
    if(current.incidentRaw!==snapshot.incidentRaw||current.sharedRaw!==snapshot.sharedRaw)throw new Error('INCIDENT_CHANGED');
   }});
 }catch{console.warn('[飞书登录桥] 初始化未成功；原登录核验与保护继续生效。');}
 onStage('VERIFY_LOGIN');
 await requireVerifiedLogin();
 if(state.needsShared)console.warn('[自动恢复] 仅处理本节点，保留共享人工保护。');
 // No terminal confirmation: successful repeated page verification is required.
 onStage('VERIFY_LOGIN');
 await requireVerifiedLogin();
 // Release the profile before waking a supervisor.
 onStage('CLOSE_BROWSER');
 await bridge?.prepareClose();
 await context.close();context=null;
 onStage('RECHECK_IDLE');
 await assertWorkerIdle(stateRoot);
 await assertNoNewStop();
 const sharedConfirmed=false;
 onStage('RESOLVE_MONITOR');
 const result=await recovery.resolve(snapshot,sharedConfirmed);
 if(!result.ok)throw new Error('RECOVERY_NOT_APPLIED：'+result.reason+'；事件已变化或保护不适用，请重新核对，未强行解除。');
 await bridge?.verified().catch(()=>console.warn('[飞书登录桥] 登录已验证，状态回执写入未确认。'));
 console.log('[登录恢复成功] 登录状态检查通过，监控事件已确认（仅核验页面，未领取或入库采集任务）。'+(result.sharedReset?'小红书共享人工保护已解除。':''));
 if(state.needsShared&&!sharedConfirmed)console.log('本机登录与事件已确认，小红书共享暂停仍保留，其他节点不会因此恢复。全部需要处理的节点恢复后，可再次运行本工具并明确确认共享恢复。');
 else console.log('原采集监督器若仍在等待会自动继续；本次单独登录入口是否续采，以启动请求授权为准。');
 console.log('人工停止标记保持原样，不会由此工具清除。');
}catch(error){
 const diagnostic=loginFailure(error,stage);
 if(stateRootForStop){const safe={at:Date.now(),pid:process.pid,retryable:error.code==='RECOVERY_NAVIGATION_FAILED',code:diagnostic.code,stage};await fs.writeFile(path.join(stateRootForStop,'login-auto-recovery-error.json'),JSON.stringify(safe)).catch(()=>{});}
 console.error('[登录恢复诊断] '+JSON.stringify(diagnostic));
 console.error('LOGIN_RECOVERY_FAILED：未确认成功；'+diagnostic.hint+' 未强行解除监控保护；人工停止标记保持原样。');
 process.exitCode=1;
}finally{
 await bridge?.close().catch(()=>{});
 searchWatch?.close();
 await context?.close().catch(()=>{});
 await recovery?.close().catch(()=>{});
}
