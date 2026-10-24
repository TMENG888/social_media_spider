import path from 'node:path';
import os from 'node:os';
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import readline from 'node:readline/promises';
import {chromium} from 'playwright';
import {loginFailure,LOGIN_RECOVERY_VERSION,loginCheckSummary} from './login-diagnostics.mjs';
import {openRecovery,recoveryState,waitForManualLogin,recoveryConfirmation,workerStatePath,assertWorkerIdle} from './login-recovery.mjs';
const common=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const platformDirectory=path.basename(path.dirname(common));
const platform=({'xiaohongshu':'小红书','douyin':'抖音'})[platformDirectory]||platformDirectory;
const index=process.argv.indexOf('--worker-root');
if(index<0||!process.argv[index+1])throw new Error('worker-root is required');
const worker=path.resolve(process.argv[index+1]),workerId=path.basename(worker);
if(!['抖音','小红书'].includes(platform)||!/^worker-\d+$/.test(workerId)||path.dirname(worker)!==path.dirname(common))
 throw new Error('工作节点必须是当前平台目录下的 worker-*，禁止跨平台解除。');
const terminal=readline.createInterface({input:process.stdin,output:process.stdout});
let context,recovery,stage='READ_QUEUE';
const onStage=value=>{stage=value;console.log('[登录恢复阶段] '+value);};
async function requireVerifiedLogin(){
 let previous='';
 while(true){
  const check=await waitForManualLogin(context,platform,{onCheck:value=>{
   const summary=JSON.stringify(loginCheckSummary(value));
   if(summary!==previous){console.log('[页面登录核验] '+summary);previous=summary;}
  }});
  if(check.ok)return check;
  if(check.reason==='BROWSER_CLOSED')throw new Error('OPERATOR_CANCELLED：浏览器已关闭，事件保留。');
  console.warn('尚未确认登录，浏览器保持打开。请继续处理页面；不会因此解除事件，也不会执行关键词检索。');
  const action=await terminal.question('处理后按回车重新检查；输入 CANCEL 取消：');
  if(action.trim().toUpperCase()==='CANCEL')throw new Error('OPERATOR_CANCELLED：事件保留。');
 }
}
try{
 console.log('[登录恢复] '+platform+' / '+os.hostname()+' / '+workerId);
 console.log('[登录恢复版本] '+LOGIN_RECOVERY_VERSION);
 console.log('只操作此节点的浏览器登录资料和监控事件，不领取任务、不入库、不清除人工停止标记。');
 onStage('READ_QUEUE');
 const queue=JSON.parse((await fs.readFile(path.join(worker,'tasks','task-queue.json'),'utf8')).replace(/^\uFEFF/,''));
 onStage('VALIDATE_WORKER');
 const stateRoot=workerStatePath(worker,queue,platform);
 onStage('CHECK_IDLE');
 await assertWorkerIdle(stateRoot);
 if(platform==='小红书'&&process.env.XHS_CDP_URL)
  throw new Error('CUSTOM_CDP_CONFIGURED：此终端配置了外部采集浏览器，不能用默认节点资料代替；请先核对实际浏览器配置，事件保留。');
 onStage('OPEN_MONITOR');
 recovery=await openRecovery(common,workerId,platform,{onStage});
 onStage('READ_MONITOR_SNAPSHOT');
 const snapshot=await recovery.snapshot();
 onStage('VALIDATE_MONITOR_STATE');
 const state=recoveryState(snapshot);
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
 onStage('OPEN_HOMEPAGE');
 const page=context.pages()[0]||await context.newPage();
 await page.goto(platform==='抖音'?'https://www.douyin.com/':'https://www.xiaohongshu.com/explore',{waitUntil:'domcontentloaded',timeout:45000});
 console.log('无需输入或搜索任何关键词。若已显示自己的头像/“我”，且没有登录或验证提示，无需额外操作。');
 await terminal.question('请完成必要的人工登录/验证，然后回到此窗口按回车检查；直接关窗可取消。\n');
 onStage('VERIFY_LOGIN');
 await requireVerifiedLogin();
 if(state.needsShared){
  console.warn('注意：小红书共享人工保护目前生效，来源节点='+String(state.shared.workerId||'未知')+'。');
  console.warn('解除共享保护可能让其他正在等待的小红书节点自动恢复；本机登录成功不代表其他机器已恢复。');
  console.warn('输入 CONFIRM LOCAL 仅确认本机事件、保留共享暂停。仅当同组需要人工处理的节点均已处理并同意恢复同组时，输入 CONFIRM SHARED；其他输入取消。');
 }else console.log('如确认解除本机此节点的登录/验证码事件，输入 CONFIRM；其他输入取消。');
 onStage('CONFIRM_OPERATOR');
 const answer=await terminal.question('确认：');
 if(!recoveryConfirmation(answer,state.needsShared))throw new Error('OPERATOR_CANCELLED：事件保留，登录状态已保存。');
 onStage('VERIFY_LOGIN');
 await requireVerifiedLogin();
 // Release the profile before waking a supervisor.
 onStage('CLOSE_BROWSER');
 await context.close();context=null;
 onStage('RECHECK_IDLE');
 await assertWorkerIdle(stateRoot);
 const sharedConfirmed=state.needsShared&&answer.trim()==='CONFIRM SHARED';
 onStage('RESOLVE_MONITOR');
 const result=await recovery.resolve(snapshot,sharedConfirmed);
 if(!result.ok)throw new Error('RECOVERY_NOT_APPLIED：'+result.reason+'；事件已变化或保护不适用，请重新核对，未强行解除。');
 console.log('[登录恢复成功] 登录状态检查通过，监控事件已确认（未执行检索或采集）。'+(result.sharedReset?'小红书共享人工保护已解除。':''));
 if(state.needsShared&&!sharedConfirmed)console.log('本机登录与事件已确认，小红书共享暂停仍保留，其他节点不会因此恢复。全部需要处理的节点恢复后，可再次运行本工具并明确确认共享恢复。');
 else console.log('原采集窗口若仍在等待会自行继续；若已退出，请手动启动采集。');
 console.log('人工停止标记保持原样，不会由此工具清除。');
}catch(error){
 const diagnostic=loginFailure(error,stage);
 console.error('[登录恢复诊断] '+JSON.stringify(diagnostic));
 console.error('LOGIN_RECOVERY_FAILED：未确认成功；'+diagnostic.hint+' 未强行解除监控保护；人工停止标记保持原样。');
 process.exitCode=1;
}finally{
 await context?.close().catch(()=>{});
 await recovery?.close().catch(()=>{});terminal.close();
}
