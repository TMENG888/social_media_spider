import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {randomUUID} from 'node:crypto';
import {createInterface} from 'node:readline/promises';
import {stdin,stdout} from 'node:process';
import {atomic,readJson,loadManifest,Checkpoint,hash,count} from './core.mjs';
import {Queue,connect} from './queue.mjs';
import {collect} from './collector.mjs';
import {preflight,importCheckpoint,importAuthor} from './mysql.mjs';

export function args(argv){const a={};for(let i=0;i<argv.length;i++)if(argv[i].startsWith('--'))a[argv[i].slice(2)]=argv[i+1]&&!argv[i+1].startsWith('--')?argv[++i]:true;return a;}
const exists=file=>fs.access(file).then(()=>true,()=>false);
const random=range=>Math.floor(range[0]+Math.random()*(range[1]-range[0]));
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
export async function run(cli){
 const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');const config=await readJson(path.join(root,'config.json'));const settings=await readJson(path.join(root,'redis-config.json'));const manifest=await loadManifest(path.join(root,'tasks/redis-tasks.json'));
 const workerId=String(cli.worker||'worker-01');if(!/^worker-0[1-5]$/.test(workerId))throw new Error('WORKER_ID_INVALID');
 const sample=cli.smoke===true;const mode=cli.mysql?'mysql':'export';
 const scopeHash=hash({manifestHash:manifest.manifestHash,policy:'zhihu-v1',maxStagnantRounds:config.maxStagnantRounds,maxSearchScrolls:config.maxSearchScrolls,maxCommentPages:config.maxCommentPages,requireLatestSort:config.requireLatestSort,collectAuthors:config.collectAuthors});
 const campaign=`${settings.campaign}-${mode}-${scopeHash.slice(0,16)}`;
 const runRoot=path.resolve(cli['data-root']||config.dataRoot);const outRoot=path.resolve(cli['output-root']||config.outputRoot);
 const browserRoot=process.env.PLAYWRIGHT_BROWSERS_PATH||config.browserRoot;process.env.PLAYWRIGHT_BROWSERS_PATH=browserRoot;
 for(const dir of [runRoot,outRoot,browserRoot]){if(!path.isAbsolute(dir))throw new Error('ABSOLUTE_DATA_PATH_REQUIRED');await fs.mkdir(dir,{recursive:true});}
 let executable=process.env.ZHIHU_BROWSER_EXECUTABLE||config.browserExecutable;if(executable&&!await exists(executable))executable=undefined;
 const {chromium}=await import('playwright');const {ZhihuBrowser}=await import('./browser.mjs');if(!cli.stop&&!executable&&!await exists(chromium.executablePath()))throw new Error('BROWSER_NOT_INSTALLED：先运行安装运行环境.bat');
 const state=path.join(runRoot,workerId,sample?'smoke':'production');const output=path.join(outRoot,workerId,sample?'smoke':campaign);
 await fs.mkdir(state,{recursive:true});await fs.mkdir(output,{recursive:true});
 const stopFile=path.join(state,'stop.requested');
 if(cli.stop){await fs.writeFile(stopFile,new Date().toISOString());console.log('已请求安全停止：'+workerId);return;}
 if(cli.check){console.log(JSON.stringify({ok:true,node:process.version,worker:workerId,tasks:manifest.taskCount,topics:manifest.topicCounts,campaign,state,output,browserRoot,redisConfigured:Boolean(settings.url)},null,2));return;}
 // Atomic directory lock survives crashes. Never infer a remote worker's death
 // from a PID on this machine; each worker must use its own local data directory.
 const lock=path.join(state,'worker.lock');try{await fs.mkdir(lock);}catch(e){if(e.code==='EEXIST')throw new Error('WORKER_LOCKED：节点已运行，异常退出后的处理见部署说明');throw e;}
 await atomic(path.join(lock,'owner.json'),{pid:process.pid,host:process.env.COMPUTERNAME,started:new Date().toISOString()});
 let browser,client,queue,postQueue,authorQueue,phase='posts',current,timer,heartbeat=Promise.resolve(),lost=false,localUntil=0,shutdown=false;
 const signal=()=>{shutdown=true;};process.on('SIGINT',signal);process.on('SIGTERM',signal);
 await fs.rm(stopFile,{force:true});
 const stopped=async()=>shutdown||await exists(stopFile);
 const assertLease=async()=>{if(!current)return;if(lost||Date.now()>=localUntil)throw new Error('LEASE_LOST');await queue.assert(current.task.id,current.token);};
 let deadline=Infinity;
 const guard=async()=>{if(await stopped()||Date.now()>=deadline)throw new Error('STOP_REQUESTED');await assertLease();};
 const delay=async range=>{const end=Date.now()+random(range);while(Date.now()<end){await guard();await sleep(Math.min(1000,end-Date.now()));}};
 const startHeartbeat=()=>{timer=setTimeout(()=>{heartbeat=(async()=>{try{await queue.renew(current.task.id,current.token);localUntil=Date.now()+settings.leaseMs-30000;startHeartbeat();}catch{lost=true;console.error('Redis 心跳失败，停止访问与入库，保留本地数据');}})();},settings.heartbeatMs||30000);};
 const stopHeartbeat=async()=>{clearTimeout(timer);await heartbeat;clearTimeout(timer);};
 try{
  if(cli.login){browser=await ZhihuBrowser.open(path.join(state,'browser-profile'),config);const page=await browser.context.newPage();await page.goto('https://www.zhihu.com/signin',{waitUntil:'domcontentloaded'});const rl=createInterface({input:stdin,output:stdout});let verified=false;try{while(!verified){const answer=await rl.question('请在本浏览器中人工登录/处理平台提示，完成后按 Enter 核验“北京臻澐”搜索权限；输入 q 退出：');if(answer.trim().toLowerCase()==='q')break;try{await browser.navigate(page,'https://www.zhihu.com/search?type=content&q='+encodeURIComponent('北京臻澐'));await browser.authenticated(page);verified=true;}catch(e){if(!/LOGIN_REQUIRED|RISK_CONTROLLED/.test(e.message))throw e;console.log('搜索权限仍未通过：'+e.message);console.log('浏览器保持打开；完成平台正常流程后可再次按 Enter 核验，程序不会自动处理验证码或自动重试。');}}}finally{rl.close();}if(!verified)throw new Error('LOGIN_SEARCH_ACCESS_UNVERIFIED：未通过搜索权限核验，保留本节点资料');console.log('本节点登录态与实际搜索访问均已核验通过');return;}
  if(cli.mysql){await preflight();console.log('MySQL 连接与字段预检通过');}
  if(!sample){client=await connect({...settings,url:process.env.REDIS_URL||settings.url});postQueue=queue=new Queue(client,{...settings,campaign});authorQueue=new Queue(client,{...settings,campaign:campaign+'-authors'});await queue.publish(manifest.tasks);console.log('[任务池]',campaign,await queue.stats());}
  let sampleDone=false;
  do{
   deadline=Date.now()+random(config.cycleMinutes)*60000;
   browser=await ZhihuBrowser.open(path.join(state,'browser-profile'),config);
   while(!await stopped()&&Date.now()<deadline){
    let task;
    if(sample){if(sampleDone)break;task=manifest.tasks.find(t=>t.keyword===(cli.keyword||'北京臻澐'));if(!task)throw new Error('SMOKE_KEYWORD_NOT_FOUND');sampleDone=true;}
    else{
     current=await queue.claim(workerId+'-'+randomUUID());if(!current){const stats=await queue.stats();await atomic(path.join(output,phase+'_queue_status.json'),stats);if(!stats.pending&&!stats.leased){console.log(phase+'任务池结束',stats);if(stats.failed){process.exitCode=2;break;}if(phase==='posts'&&config.collectAuthors){phase='authors';queue=authorQueue;continue;}break;}await sleep(2000);continue;}
     task=current.task;localUntil=Date.now()+settings.leaseMs-30000;lost=false;startHeartbeat();
    }
    if(phase==='authors'){
     const authorDir=path.join(output,'authors',task.id);
     try{await guard();const raw=await browser.author(task.authorUrl);const stats={followers:count(raw?.followers),votes:count(raw?.votes)};if(stats.followers==null&&stats.votes==null)throw new Error('AUTHOR_STATS_UNKNOWN');await guard();if(cli.mysql)await importAuthor(task.authorUrl,stats,assertLease);await atomic(path.join(authorDir,'author.json'),{url:task.authorUrl,stats,at:new Date().toISOString()});await stopHeartbeat();await assertLease();await queue.finish(task.id,current.token,'completed',{scanComplete:true,commentsComplete:true,persisted:true,unresolved:0});current=null;await delay(config.detailDelayMs);}
     catch(e){await atomic(path.join(authorDir,'error.json'),{error:e.message});if(current){await stopHeartbeat();if(!lost){await assertLease();await queue.finish(task.id,current.token,/STOP_REQUESTED|LOGIN_REQUIRED|RISK_CONTROLLED/.test(e.message)?'released':'retry',{error:e.message});current=null;}}if(!/STOP_REQUESTED/.test(e.message))throw e;break;}
     continue;
    }
    console.log('[开始]',task.sequence,task.topic,task.keyword);
    const taskDir=path.join(state,campaign,task.id);const outDir=path.join(output,task.id);await fs.mkdir(taskDir,{recursive:true});const cp=new Checkpoint(path.join(taskDir,'checkpoint.sqlite'));
    const flush=async()=>{await cp.export(outDir);if(cli.mysql){await assertLease();await importCheckpoint(cp,assertLease);}if(authorQueue&&config.collectAuthors){await assertLease();await authorQueue.publish(cp.authors().map(([url])=>({id:'author-'+hash(url),sequence:1,authorUrl:url})));}};
    try{
     const result=await collect({browser,task,checkpoint:cp,config,guard,delay,flush,smokeLimit:sample?Number(cli.limit||2):0});await atomic(path.join(outDir,'task_status.json'),{task,result,mode,at:new Date().toISOString()});
     if(!sample){await stopHeartbeat();await assertLease();const complete=result.scanComplete&&result.commentsComplete&&result.unresolved===0;await queue.finish(task.id,current.token,complete?'completed':'retry',result);current=null;}
     console.log('[结果]',task.keyword,result.stopReason,result.posts,'篇，未解决',result.unresolved);
    }catch(e){
     await cp.export(outDir);await browser.diagnose(outDir,e);await atomic(path.join(outDir,'task_status.json'),{task,status:'incomplete',error:e.message,at:new Date().toISOString()});
     if(current){await stopHeartbeat();if(!lost){await assertLease();const release=/STOP_REQUESTED|RISK_CONTROLLED|LOGIN_REQUIRED/.test(e.message);await queue.finish(task.id,current.token,release?'released':'retry',{error:e.message});current=null;}}
     if(!/STOP_REQUESTED/.test(e.message))throw e;break;
    }finally{cp.close();}
    if(sample)break;await delay(config.keywordDelayMs).catch(e=>{if(!/STOP_REQUESTED/.test(e.message))throw e;});
   }
   await browser.close();browser=null;
   if(sample||!cli.supervise||await stopped())break;
   const stats=await queue.stats();if(!stats.pending&&!stats.leased)break;if(stats.failed)throw new Error('FAILED_TASKS：存在重试耗尽任务，停止监督器');
   const until=Date.now()+random(config.restMinutes)*60000;console.log('本轮收尾，休息后继续');while(Date.now()<until&&!await stopped())await sleep(1000);
  }while(true);
 }finally{await stopHeartbeat();if(browser)await browser.close().catch(()=>{});if(client)client.close();process.off('SIGINT',signal);process.off('SIGTERM',signal);await fs.rm(lock,{recursive:true,force:true});}
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))run(args(process.argv.slice(2))).catch(e=>{console.error(e.message);process.exitCode=1;});
