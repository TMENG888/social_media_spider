import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {chromium} from 'playwright';
import mysql from 'mysql2/promise';
import {collectKeyword} from './collector.mjs';
import {RedisDispatcher} from './redis-dispatcher.mjs';
import {loadTaskManifest} from './redis-task-manifest.mjs';
import {mysqlConnectionOptions,verifyTable} from './import-mysql.mjs';
import {POST_FIELDS,COMMENT_FIELDS,stableId} from './schema.mjs';
import {writeJsonAtomic} from './checkpoint.mjs';
import {authorPhase} from './author-phase.mjs';
import {keywordPause,waitForPacing} from './collection-pacing.mjs';
import {collectionFailureAction} from './recovery-policy.mjs';
import {RemoteStopControl} from './remote-stop-control.mjs';
import {maySkipExhausted} from './retry-disposition.mjs';
import {cleanupWorkerAsrMedia} from './cleanup-worker-asr-media.mjs';
import {supportedCorrectionPolicy} from './correction-lease.mjs';
import {keywordQueueConfirmed as volumeQueueConfirmed,reconcileVolumeCompletion} from './volume-confirmation.mjs';
import {OperationalGate,classifyRestriction} from './operational-gate.mjs';
import {setAccessIncidentReporter} from './douyin-browser.mjs';
const common=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const args={};for(let i=2;i<process.argv.length;i++){if(!process.argv[i].startsWith('--'))continue;const k=process.argv[i].slice(2),v=process.argv[i+1];args[k]=v&&!v.startsWith('--')?process.argv[++i]:true;}
const worker=path.resolve(String(args['worker-root']||path.join(common,'../worker-01')));
const workerId=path.basename(worker),stateRoot=path.join(worker,'.state'),runsRoot=path.join(worker,'runs');
const readJson=async file=>JSON.parse((await fs.readFile(file,'utf8')).replace(/^\uFEFF/,''));
const exists=async file=>fs.access(file).then(()=>true,()=>false);
const config=await readJson(path.join(common,'config.json'));
await fs.mkdir(stateRoot,{recursive:true});await fs.mkdir(runsRoot,{recursive:true});
const stopFile=path.join(stateRoot,'stop.requested');
process.env.DY_WORKER_ROOT=common;
const manifest=await loadTaskManifest(path.join(common,'tasks/redis-tasks.json'));
const chrome=path.join(common,'runtime/browsers/chrome-win64/chrome.exe'),python=path.join(common,'runtime/python/python.exe'),model=path.join(common,config.asrModelPath);
if(args.preflight){
 const probe=spawnSync(python,['-c','import faster_whisper,ctranslate2,av; print("ok")'],{encoding:'utf8',windowsHide:true,timeout:30000});
 const checks={workerId,platform:'抖音',taskCount:manifest.taskCount,topicCounts:manifest.topicCounts,browserExists:await exists(chrome),pythonExists:await exists(python),asrDependenciesReady:probe.status===0,asrModelReady:await exists(path.join(model,'model.bin')),collectionPhases:'posts_then_authors',category:null};
 checks.ok=checks.browserExists&&checks.pythonExists&&(!config.asrEnabled||(checks.asrDependenciesReady&&checks.asrModelReady));
 if(probe.status!==0)checks.asrError=probe.error?.message||String(probe.stderr).split('\n').at(-2);
 console.log(JSON.stringify(checks,null,2));process.exit(checks.ok?0:1);
}
const commit=!args['export-only'],test=Boolean(args.test),phase=String(args.phase||'auto');
const onlyKeywords=args['only-keywords']?String(args['only-keywords']).split('|').filter(Boolean):null;
if(onlyKeywords&&test)throw new Error('SELECTED_ANNUAL_RUN_CANNOT_USE_SAMPLE_TEST_MODE');
const selectedTasks=onlyKeywords?.map(keyword=>{const task=manifest.tasks.find(t=>t.keyword===keyword);if(!task)throw new Error(`SELECTED_KEYWORD_NOT_IN_MANIFEST：${keyword}`);return task;});
const correctionPolicy=args['correction-policy']?String(args['correction-policy']):null;
if(correctionPolicy&&(!supportedCorrectionPolicy(correctionPolicy)||selectedTasks?.length!==1||test||!commit||phase!=='posts'||args['verification-sample']))throw new Error('CORRECTION_REQUIRES_EXACT_PRODUCTION_TASK_AND_CURRENT_POLICY');
const verificationSample=args['verification-sample']?Number(args['verification-sample']):0;
if(args['verification-sample']&&(!Number.isInteger(verificationSample)||verificationSample<1||verificationSample>100||test||!selectedTasks||phase!=='posts'))throw new Error('VERIFICATION_SAMPLE_REQUIRES_SELECTED_POST_TASKS_AND_LIMIT_1_TO_100');
if(!['auto','posts','authors'].includes(phase))throw new Error('phase must be auto/posts/authors');
const runtimeMinutes=Number(args['max-runtime-minutes']??60);
if(!Number.isFinite(runtimeMinutes)||runtimeMinutes<0)throw new Error('MAX_RUNTIME_INVALID');
const deadline=runtimeMinutes===0?Infinity:Date.now()+runtimeMinutes*60000;
let requested=false,dispatcher=null,context=null,fatal=null,retryAfterRest=false;
let remoteControl=null,operations=null;
const shouldStop=async()=>requested||Date.now()>=deadline||await exists(stopFile);
process.on('SIGINT',()=>{requested=true;});process.on('SIGTERM',()=>{requested=true;});
const lockFile=path.join(stateRoot,'worker.lock');let lock;
try{lock=await fs.open(lockFile,'wx');await lock.writeFile(JSON.stringify({pid:process.pid,at:new Date().toISOString()}));}
catch(e){if(e.code!=='EEXIST')throw e;let old;try{old=await readJson(lockFile);}catch{}let alive=false;if(old?.pid){try{process.kill(old.pid,0);alive=true;}catch{}}
 if(alive)throw new Error('WORKER_ALREADY_RUNNING：同一节点禁止重复启动');await fs.rm(lockFile,{force:true});lock=await fs.open(lockFile,'wx');await lock.writeFile(JSON.stringify({pid:process.pid}));}
const status={workerId,startedAt:new Date().toISOString(),phase,tasks:[],completed:0,failed:0,status:'running',fatalError:null};
try{
 if(!test&&commit){remoteControl=await RemoteStopControl.open(common,worker);await remoteControl.gate();remoteControl.watch();}
 if(!test&&commit){operations=await OperationalGate.open({root:common,workerId,platform:'抖音'});await operations.assertReady();}
 if(operations)setAccessIncidentReporter(message=>operations.record(message,{taskId:dispatcher?.current?.taskId||'',keyword:status.currentKeyword||''}));
 try{await cleanupWorkerAsrMedia({stateRoot,mediaName:'media',keepMedia:config.asrKeepMedia===true,dryRun:false});}
 catch(e){console.warn(`[ASR媒体清理] 跳过本轮清理，不影响采集：${e.message}`);}
 if(commit){
  const db=await mysql.createConnection(mysqlConnectionOptions());
  try{await verifyTable(db,'ods_social_media_post',POST_FIELDS);await verifyTable(db,'ods_social_media_comment',COMMENT_FIELDS);console.log('[数据库预检] 连接与两张目标表结构通过');}finally{await db.end();}
 }
 if(!test)dispatcher=await RedisDispatcher.open({root:common,stateRoot,workerId,skipImport:!commit,stopFile,selectedTaskIds:selectedTasks?.map(t=>t.redisTaskId||t.id)||null});
 if(dispatcher){dispatcher.operations=operations;dispatcher.operationalShouldStop=shouldStop;}
 context=await chromium.launchPersistentContext(path.join(stateRoot,'browser-profile'),{executablePath:chrome,headless:false,viewport:null,timeout:45000});
 const page=context.pages()[0]||await context.newPage();
 // Reject accidental popup navigation during the posts phase instead of
 // silently collecting in another tab and losing the latest search context.
 page.on('popup',popup=>{void popup.close();});
 if(phase!=='authors'){
  const keywords=test?String(args.keywords||'中海 住宅|北京臻澐').split('|'):null;
  const sampleTasks=test?keywords.map(keyword=>{const task=manifest.tasks.find(t=>t.keyword===keyword);if(!task)throw new Error(`TEST_KEYWORD_NOT_IN_MANIFEST：${keyword}`);return task;}):null;
  const tasks=dispatcher?dispatcher.tasks({taskIds:selectedTasks?.map(t=>t.redisTaskId||t.id)||null,...(correctionPolicy?{correctionPolicy}:{})}):(async function*(){for(let i=0;i<sampleTasks.length;i++)yield[i,sampleTasks[i]];})();
  for await(const[,task]of tasks){
   if(await shouldStop())break;
   if(dispatcher)Object.assign(process.env,dispatcher.env());
   const taskKey=stableId(`${task.topic}/${task.keyword}`),replay=dispatcher?.current?.recollectionPolicy||'',stateDir=path.join(stateRoot,'tasks',taskKey,replay),outputDir=path.join(runsRoot,taskKey,replay);
   status.currentKeyword=task.keyword;await writeJsonAtomic(path.join(runsRoot,'worker_status.json'),status);
   try{
    const result=await collectKeyword({page,task,config,commonRoot:common,stateDir,outputDir,shouldStop,sampleLimit:test?Number(args.limit||10):verificationSample,commit,allowManualLogin:test});
    const confirmation=dispatcher?await dispatcher.finish(verificationSample?'release':'complete',result):null;
    if(dispatcher?.volume&&!verificationSample){
     Object.assign(result,reconcileVolumeCompletion(result,confirmation));
     if(!result.redisConfirmed){
      status.tasks.push(result);status.failed++;retryAfterRest=true;status.recoveryReason=result.error;
      console.warn('[数量确认未通过] 本地采集完成不等于最终数量验收；保留原任务和证据，不计入完成');
      break;
     }
    }
    status.tasks.push(result);
    if(verificationSample)status.sampleVerified=(status.sampleVerified||0)+1;
    else if(result.disposition==='no_change')status.noChangeCompleted=(status.noChangeCompleted||0)+1;
    else if(result.status==='completed_with_skips')status.completedWithSkips=(status.completedWithSkips||0)+1;
    else status.completed++;
    if(result.mustStopNode){const restriction=classifyRestriction(result.error);if(restriction)status.operationalHold=restriction;requested=true;break;}
    // A verified sample is not an annual keyword completion. Keep all saved
    // rows/checkpoints, return the real lease, and leave production pending.
   }catch(e){
    const restriction=classifyRestriction(e);
    if(restriction&&operations){await operations.record(e,{taskId:task.redisTaskId||task.id,keyword:task.keyword});status.operationalHold={kind:restriction.kind,requiresHuman:restriction.requiresHuman};}
    let action=collectionFailureAction(e,{test:test||Boolean(verificationSample)});status.tasks.push(e.collectionSummary||{keyword:task.keyword,error:e.message});
    if(restriction&&operations)action='stop';
    const boundedContentRetry=!test&&!verificationSample&&maySkipExhausted(e.collectionSummary);
    if(boundedContentRetry&&!restriction)action='content_retry';
    const failureRecord=e.collectionSummary||{error:e.message};
    if(restriction)failureRecord.error=e.message;
    const confirmation=dispatcher&&!dispatcher.lost?await dispatcher.finish(e.reviewRequired?'review':action==='stop'?'release':action==='rest_retry'?'defer':'fail',failureRecord):null;
    if(volumeQueueConfirmed(confirmation)){
     Object.assign(failureRecord,reconcileVolumeCompletion(failureRecord,confirmation));
     status.completed++;if(/LOGIN_REQUIRED|SECURITY_CHALLENGE|PLATFORM_RESTRICTION/.test(e.message)){requested=true;break;}continue;}
    if(action==='stop'){requested=true;break;}
    if(action==='rest_retry'||action==='content_retry'){
     retryAfterRest=true;status.recoveryReason=e.message;
     console.warn(action==='content_retry'
      ? '[内容重试休息] 本地断点已保全，内容失败按共享上限处理；耗尽后留证跳过，不计成功'
      : '[入库恢复休息] 本地数据已保全，暂缓次数有共享上限；耗尽后保留故障，不计完成');break;
    }
    status.failed++;throw e; // First restriction or context error stops this node.
   }
   // A selected final keyword has no successor. Keep inter-keyword pacing
   // for ordinary runs and earlier selections, not after the final task.
   const finalSelected=selectedTasks?.at(-1)?.redisTaskId===(task.redisTaskId||task.id);
   if(!test&&!verificationSample&&!finalSelected&&!await shouldStop()){
    const delay=keywordPause(config);
    console.log(`[关键词休息] 当前任务已入库并归还租约，休息${Math.round(delay.ms/1000)}秒再领取后续任务`);
    try{await waitForPacing(delay.ms,{shouldStop});}
    catch(e){if(/STOP_REQUESTED/.test(e.message)){requested=true;break;}throw e;}
   }
  }
 }
 if(dispatcher&&commit&&phase!=='posts'&&!retryAfterRest&&!await shouldStop())status.authors=await authorPhase({page,root:common,stateRoot,workerId,stopFile,postDispatcher:dispatcher,config,shouldStop});
 status.status=await shouldStop()?'partial_stopped':retryAfterRest?'retry_after_rest':verificationSample?'sample_completed':'completed';
 if(test&&commit&&!await shouldStop()){
  const results=[];const db=await mysql.createConnection(mysqlConnectionOptions());
  try{for(const task of status.tasks){const id=stableId(`${task.topic}/${task.keyword}`),posts=(await fs.readFile(path.join(runsRoot,id,'ods_social_media_post.jsonl'),'utf8')).split(/\r?\n/).filter(Boolean).map(JSON.parse);
   for(const p of posts){const[rows]=await db.execute('SELECT `文章id`,`文章时间地点`,`文章链接`,`文章视频内容`,`分类` FROM ods_social_media_post WHERE `平台`=? AND `项目`=? AND `文章id`=?',['抖音',p.项目,p.文章id]);results.push({keyword:task.keyword,articleId:p.文章id,matches:rows.length,row:rows[0]||null});}
  }}finally{await db.end();}
  await writeJsonAtomic(path.join(runsRoot,'mysql-readback.json'),results);
  // Exports also retain older samples across a resumed test. New latest posts
  // can appear between runs, so retained export totals may exceed this sample.
  if(status.tasks.length!==String(args.keywords||'中海 住宅|北京臻澐').split('|').length||status.tasks.some(t=>t.status!=='sample_completed'||t.posts!==Number(args.limit||10))||results.some(r=>r.matches!==1||!String(r.row.文章时间地点).startsWith('2026')||r.row.分类!==null))throw new Error('LIVE_TEST_READBACK_FAILED');
  console.log(`[入库回读验证] ${results.length}篇，业务键各1条，2026日期及分类NULL通过`);
 }
}catch(e){
 const restriction=classifyRestriction(e);
 if(e.code==='OPERATIONAL_HOLD'||restriction&&operations){
  try{
   if(restriction)await operations.record(e,{keyword:status.currentKeyword||''});
   requested=true;status.status='operational_hold';status.operationalHold=restriction||{kind:e.state.kind,requiresHuman:e.state.requiresHuman};
  }catch(monitorError){fatal=monitorError;status.status='failed';status.fatalError='MONITOR_STATE_UNAVAILABLE';}
  console.warn('[平台等待] 保护仍有效；已退出采集进程并释放浏览器与节点锁，等待登录恢复工具确认。');
 }else{fatal=e;status.status='failed';status.fatalError=String(e.message||e);console.error(`[节点停止] ${status.fatalError}`);}
}
finally{
 await context?.close().catch(e=>{fatal ||= e;});await dispatcher?.close({stopped:await shouldStop()}).catch(e=>{fatal ||= e;console.error(`[Redis收尾] ${e.code||'ERROR'}`);});
 await remoteControl?.close(fatal?'exit_unconfirmed':'collector_stopped').catch(()=>{fatal ||= new Error('REMOTE_CONTROL_FINAL_ACK_UNAVAILABLE');});
 await operations?.close().catch(()=>{fatal ||= new Error('MONITOR_STATE_UNAVAILABLE');});
 setAccessIncidentReporter(null);
 status.finishedAt=new Date().toISOString();await writeJsonAtomic(path.join(runsRoot,'worker_status.json'),status);await lock.close();await fs.rm(lockFile,{force:true});
}
console.log(JSON.stringify(status,null,2));process.exitCode=fatal?1:0;
