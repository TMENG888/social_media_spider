import fs from 'node:fs/promises';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {createPageDiagnostics,safeUrl,safeText,diagnosticError} from './page-diagnostics.mjs';
import mysql from 'mysql2/promise';
import {openCheckpoint,saveCandidates,checkpointCandidates,markCompleted,markSkipped,markFailed,markBaseImported,markImportPending,recoverSavedImportFailures,migrateCheckpointCommentThreads,setMeta,completedResults,exportCheckpoint,asrJobStats,writeJsonAtomic,mediaSourceRecoveryIds,settleExpiredMediaGaps} from './checkpoint.mjs';
import {mergeCommentResults} from './comment-threads.mjs';
import {YearBoundary,inTargetYear,searchExhaustionEvidence,verifiedAnnualSearchEnd} from './collection-policy.mjs';
import {postFromAweme,DouyinResponseObserver,shanghaiTime} from './douyin-data.mjs';
import {assertAccess,navigateSearch,selectLatest,visibleCards,openCard,restoreSearch,collectComments,ensureSingleColumn,searchEndUi,scrollSearchResults} from './douyin-browser.mjs';
import {AsrService} from './asr.mjs';
import {AsrJobProcessor} from './asr-jobs.mjs';
import {assessAsrAcceptance} from './acceptance-gate.mjs';
import {importRows,mysqlConnectionOptions,retryMysqlDeadlock} from './import-mysql.mjs';
import {assertLocalLease,withImportLease} from './lease-guard.mjs';
import {itemPause,waitForPacing} from './collection-pacing.mjs';
import {transientImportError} from './recovery-policy.mjs';
import {recordCommittedPosts,subtitleWriteCount} from './monitor-telemetry.mjs';
import {settleObservedOldCandidates,incompleteCandidates,observedLatestSearchCandidates} from './candidate-acceptance.mjs';
import {retrySnapshot,unchangedRetry} from './retry-no-change.mjs';
import {recoverableContentGap,boundedRecoveryDisposition,recoverySearchBudget} from './content-recovery.mjs';
import {verifyCheckpointCoverage} from './coverage-gate.mjs';
import {searchScrollProgress} from './search-scroll.mjs';
import {readTaskVolume,validateVolumeSnapshot} from './volume-acceptance.mjs';
import {finalizeAsr} from './asr-finalization.mjs';
import {planObservedSearchItems} from './search-response-recovery.mjs';
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function patchTranscript(result) {
 await retryMysqlDeadlock(()=>withImportLease(async verify=>{
  const connection=await mysql.createConnection(mysqlConnectionOptions());
  try{
   await verify();
   // Backfills allocate no IDs. Resolve a unique row without taking broad
   // predicate locks, then update its primary key only. The shared allocation
   // lock remains in importRows, not in this single-column operation.
   const[rows]=await connection.execute('SELECT `id`,`文章视频内容` FROM ods_social_media_post WHERE `平台`=? AND `项目`=? AND `文章id`=? LIMIT 2',['抖音',result.post.项目,result.post.文章id]);
   if(rows.length!==1)throw new Error(rows.length?'ASR_DUPLICATE_BASE_POST':'ASR_BASE_POST_NOT_IMPORTED');
   await connection.beginTransaction();
   const [updated]=await connection.execute('UPDATE ods_social_media_post SET `文章视频内容`=? WHERE `id`=?',[result.post.文章视频内容,rows[0].id]);
   if(!updated.affectedRows)throw new Error('ASR_BASE_POST_NOT_IMPORTED');
   await verify();await connection.commit();
   await recordCommittedPosts(connection,[result.post],{inserted:0,videoContentWrites:subtitleWriteCount(rows[0]['文章视频内容'],result.post.文章视频内容)},new Date().toISOString(),true);
  }catch(e){await connection.rollback();throw e;}finally{await connection.end();}
 }));
}
export async function collectKeyword({page,task,config,commonRoot,stateDir,outputDir,shouldStop,sampleLimit=0,commit=true,allowManualLogin=false,importer=importRows}) {
 const volumeMode=commit&&!sampleLimit&&process.env.SOCIAL_VOLUME_ENABLED==='1';
 const volumeSnapshot=volumeMode?validateVolumeSnapshot(JSON.parse(await fs.readFile(process.env.SOCIAL_VOLUME_SNAPSHOT,'utf8')),{platform:'抖音'}):null;
 const volumeRead=()=>readTaskVolume({connect:()=>mysql.createConnection(mysqlConnectionOptions()),snapshot:volumeSnapshot,taskId:task.redisTaskId||task.id});
 await fs.mkdir(stateDir,{recursive:true});await fs.mkdir(outputDir,{recursive:true});
 const db=openCheckpoint(path.join(stateDir,'checkpoint.sqlite'));
 const retryBefore=retrySnapshot(db,task.keyword);
 const observer=new DouyinResponseObserver(page),boundary=new YearBoundary(config.targetYear||2026,task.searchStopWindow||8);
 const seen=new Set(),summary={keyword:task.keyword,topic:task.topic,status:'running',posts:0,comments:0,verified:0,old:0,error:null,sortConfirmed:false,stopReason:null};
 Object.assign(summary,{taskId:task.redisTaskId||task.id,projectName:task.projectName,
  startedAt:new Date().toISOString(),checkpointDb:path.join(stateDir,'checkpoint.sqlite')});
 const diagnostics=createPageDiagnostics({page,platform:'抖音',keyword:task.keyword,outputDir,
  workerId:path.resolve(stateDir).split(/[\\/]/).findLast(part=>/^worker-\d+$/.test(part))||'',runId:task.redisTaskId||task.id});
 const onDiagnostic=async event=>{
  diagnostics.mark(event.stage,event.details);
  if(event.error){
   const captured=await diagnostics.capture(event.stage,event.error,event.details);
   (summary.pageDiagnostics||=[]).push(captured);
  }
 };
 if(sampleLimit)summary.sampleNoteIds=[];
 let service=null,asr=null,error=null,baseImported=false;
 const stop=async()=>{await assertLocalLease();return shouldStop?await shouldStop():false;};
 const check=async()=>{if(await stop())throw new Error('STOP_REQUESTED：已安全停止');};
 const releaseJobs=()=>db.prepare("UPDATE asr_job SET status='pending' WHERE status='waiting_import' AND EXISTS (SELECT 1 FROM candidate c WHERE c.keyword=asr_job.keyword AND c.note_id=asr_job.note_id AND c.status='completed' AND (c.import_status='imported' OR ?=1))").run(commit?0:1);
 const importResults=async results=>{
  const ids=results.map(r=>String(r.post.文章id));
  try {
   if(commit&&results.length)await importer({posts:results.map(r=>r.post),comments:results.flatMap(r=>r.audit?.comments?.aggregation_mode==='legacy_unresolved'?[]:r.comments||[]),shouldStop:stop});
   if(commit)markBaseImported(db,task.keyword,ids);
  }catch(e){markImportPending(db,task.keyword,ids,e);e.importPending=true;throw e;}
 };
 const importSaved=async()=>{
  const results=completedResults(db),posts=results.map(r=>r.post),comments=results.flatMap(r=>r.comments||[]);
  await importResults(results);
  if(commit&&posts.length)console.log(`[断点保全入库] ${task.keyword}: ${posts.length}篇，${comments.length}条评论`);
  baseImported=true;releaseJobs();asr?.wake();return {posts:posts.length,comments:comments.length};
 };
 try{
  await check();
  summary.commentThreadMigration=migrateCheckpointCommentThreads(db);
  if(summary.commentThreadMigration.changed)console.log(`[评论讨论串修复] 已处理${summary.commentThreadMigration.changed}篇旧断点；原记录已保留，不重置采集任务`);
  if(summary.commentThreadMigration.deferred)console.log(`[评论关联待复采] ${summary.commentThreadMigration.deferred}篇旧断点缺少父子关联证据，保留原文；不把子评论猜作父评论入库`);
  summary.recoveredImportNotes=recoverSavedImportFailures(db,task,config.targetYear||2026);
  if(summary.recoveredImportNotes.length)console.log(`[断点修复] ${task.keyword}: ${summary.recoveredImportNotes.length}篇已保存帖子恢复为待入库；不重新访问帖子、不改评论完整性`);
  if(config.asrEnabled){
   service=new AsrService({pythonExecutable:path.join(commonRoot,'runtime/python/python.exe'),model:path.resolve(commonRoot,config.asrModelPath),device:config.asrDevice||'cpu',computeType:config.asrComputeType||'int8_float32',cpuThreads:config.asrCpuThreads||1,beamSize:config.asrBeamSize||1,localFilesOnly:true,tempDir:path.join(stateDir,'media'),cacheDir:path.join(stateDir,'asr-cache')});
   asr=new AsrJobProcessor({db,service,mediaDir:path.join(stateDir,'media'),keepMedia:config.asrKeepMedia===true,shouldStop:stop,onCompleted:async(_job,_output,result)=>{if(commit&&baseImported)await patchTranscript(result);}});
  }
  await importSaved();
  asr?.start().catch(e=>{summary.asrError=String(e.message);});
  await navigateSearch(page,task.keyword,{shouldStop:stop,timeoutMs:config.navigationTimeoutMs||45000,allowManualLogin,
   onObservation:audit=>{summary.searchNavigation=audit;}});
  if(allowManualLogin){
   const deadline=Date.now()+300000;
   while(Date.now()<deadline){
    await check();
    try{await assertAccess(page);break;}catch(e){if(!/LOGIN_REQUIRED/.test(e.message))throw e;console.log('[人工登录] 请在采集浏览器窗口中完成抖音登录；不会自动填写账号或验证码');await pause(5000);}
   }
  }
  await assertAccess(page);
  let prepared=await selectLatest(page,observer,task.keyword,{shouldStop:stop,onDiagnostic});summary.sortConfirmed=true;summary.searchPreparation=prepared;
  const observedPlan=()=>planObservedSearchItems({items:observer.searchItems,scope:{keyword:task.keyword,after:prepared.at},
   task,notes:checkpointCandidates(db,task.keyword),year:config.targetYear||2026,cutoff:task.cutoff||'2026-01-01'});
  await page.screenshot({path:path.join(outputDir,'latest-search.png'),timeout:4000}).catch(()=>{});
  console.log(`[筛选确认] ${task.keyword}: 最新发布，全年日期不限；${prepared.layout==='empty'?'搜索响应与页面均确认零结果':`单列已生效，已读到${prepared.cards}张卡片`}；后续不逐帖重选筛选`);
  // Quantity/annual-low mode retries only the original keyword from its search
  // origin. It never schedules a separate old-post or subtitle recovery pass.
  const mediaRecoveryIds=new Set(volumeMode?[]:mediaSourceRecoveryIds(db,task.keyword));
  const recoveryIds=new Set(volumeMode?[]:[...incompleteCandidates(checkpointCandidates(db,task.keyword)).map(n=>n.noteId),...mediaRecoveryIds]);
  let recovering=recoveryIds.size>0;
  summary.recoveredDetailNotes=[];summary.recoveredOldNotes=[];
  if(recovering)console.log(`[缺口优先恢复] ${task.keyword}: 先在当前搜索列表定位${recoveryIds.size}篇详情/评论缺口，再继续年度搜索`);
  let stagnant=0,round=0,done=false,layoutRecovered=false,endKey=null,endChecks=0,handled=0;
  let recoverySearchRounds=0,recoverySearchMs=0;
  let scrollProgress={};summary.searchScrollDiagnostics=[];
  const advanceSearch=async()=>{
   const searchStarted=Date.now();
   const snapshot=await scrollSearchResults(page,{keyword:task.keyword});
   scrollProgress=searchScrollProgress(scrollProgress,snapshot);
   summary.searchScrollDiagnostics.push({at:new Date().toISOString(),...snapshot,progressed:scrollProgress.progressed});
   summary.searchScrollDiagnostics=summary.searchScrollDiagnostics.slice(-30);
   if(scrollProgress.progressed)stagnant=0;else stagnant++;
   await pause(2000);
   if(recovering){recoverySearchRounds++;recoverySearchMs+=Math.max(0,Date.now()-searchStarted);}
  };
  while(!done){
   await check();await assertAccess(page);await observer.flush();
   // Register current response-only gaps before evaluating exhaustion, not
   // just after the endpoint proof has already been recorded.
   saveCandidates(db,task.keyword,observedLatestSearchCandidates(observer.searchPages,{keyword:task.keyword,after:prepared.at}),seen.size);
   if(volumeMode&&!process.env.SOCIAL_RECOLLECT_ONCE){const quantity=await volumeRead();if(quantity.ok){summary.stopReason='volume_threshold';summary.volumeAcceptance=quantity;done=true;break;}}
   if(recovering&&!recoveryIds.size){
    // Recovery may have scrolled past newer cards. Restart this search once,
    // then reconfirm latest; never reopen individual articles by direct URL.
    await navigateSearch(page,task.keyword,{shouldStop:stop,timeoutMs:config.navigationTimeoutMs||45000,
     onObservation:audit=>{summary.recoverySearchNavigation=audit;}});
    prepared=await selectLatest(page,observer,task.keyword,{shouldStop:stop});summary.searchPreparation=prepared;
    recovering=false;seen.clear();stagnant=0;layoutRecovered=false;scrollProgress={};
    summary.posts=0;summary.comments=0;summary.verified=0;summary.old=0;
    if(sampleLimit)summary.sampleNoteIds=[];
    console.log(`[缺口核对收尾] ${task.keyword}: 已恢复并持久化${summary.recoveredDetailNotes.length}篇；另有${summary.recoveredOldNotes.length}篇已核实非目标年度，${summary.unlocatedCandidates?.length||0}篇未定位保留；重新确认最新后继续年度扫描`);
    continue;
   }
   const cards=await visibleCards(page);
   const candidates=cards.filter(n=>!seen.has(n.noteId)&&(!recovering||recoveryIds.has(n.noteId)));
   saveCandidates(db,task.keyword,cards,seen.size);
   // Reuse only already-observed, matching-ID creation dates. This avoids
   // reopening known old-year cards; unknown dates/IDs still require detail.
   summary.observedOldCandidateDispositions||=[];
   const responsePlan=observedPlan();summary.searchResponseCandidateDiagnostics=responsePlan.diagnostics;
   const observedOld=[...settleObservedOldCandidates(db,task.keyword,responsePlan.oldAwemes,config.targetYear||2026,task.cutoff||'2026-01-01',{evidenceById:responsePlan.oldEvidence}),
    ...settleObservedOldCandidates(db,task.keyword,observer.awemes,config.targetYear||2026,task.cutoff||'2026-01-01',{excludedIds:responsePlan.conflictingIds})];
   summary.observedOldCandidateDispositions.push(...observedOld);
   if(recovering)for(const old of observedOld)if(recoveryIds.delete(old.noteId))summary.recoveredOldNotes.push(old.noteId);
   if(!candidates.length){
    // Still inside this original keyword scan: a current search response may
    // carry the complete base article even when its virtual card never mounts.
    // No detail URL/API fetch, no new task and no invented comment completion.
    if(volumeMode&&!recovering&&responsePlan.recoverable.length){
     await check();await assertAccess(page);
     const {note,result,evidence}=responsePlan.recoverable[0];
     const job=config.asrEnabled&&result.post.文章视频链接?{keyword:task.keyword,noteId:note.noteId,articleId:note.noteId,mediaUrl:result.post.文章视频链接,referer:result.post.文章链接,prompt:null,sourceObserved:true}:null;
     markCompleted(db,task.keyword,note,result,{asrJob:job,observedSearchEvidence:evidence});
     await importResults([result]);baseImported=true;releaseJobs();asr?.wake();
     seen.add(note.noteId);summary.posts++;summary.verified++;
     summary.searchResponseRecoveredNotes||=[];summary.searchResponseRecoveredNotes.push({noteId:note.noteId,evidence});
     console.log(`[当前搜索响应入库] ${task.keyword} / ${note.noteId}：同ID、年度、作者、媒体及相关性核对通过；不声明已采集评论`);
     await writeJsonAtomic(path.join(outputDir,'collector_progress.json'),{...summary,asr:asrJobStats(db),updatedAt:new Date().toISOString()});
     continue;
    }
    if(recovering){
     const budget=recoverySearchBudget({rounds:recoverySearchRounds,elapsedMs:recoverySearchMs});
     if(stagnant>=Number(config.maxStagnantRounds||15)||budget.exhausted){
      Object.assign(summary,boundedRecoveryDisposition(recoveryIds));
      summary.recoverySearchBudget=budget;
      console.warn(`[旧缺口搜索到限] 保留${recoveryIds.size}个未定位候选，不判删除或成功；继续原关键词新结果扫描`);
      // Missing old targets must not prevent discovering the rest of this
      // keyword. Preserve them in the final coverage denominator, then scan.
      recoveryIds.clear();continue;
     }
     await advanceSearch();continue;
    }
    const evidence=searchExhaustionEvidence({keyword:task.keyword,after:prepared.at,sortConfirmed:summary.sortConfirmed,pages:observer.searchPages,failures:observer.searchFailures,uiEnd:await searchEndUi(page,task.keyword),candidates:checkpointCandidates(db,task.keyword)});
    summary.searchExhaustion=evidence;
    if(evidence.confirmed){
     const key=JSON.stringify(evidence);endChecks=key===endKey?endChecks+1:1;endKey=key;
     if(endChecks>=2){
      summary.stopReason='search_exhausted';summary.searchExhaustion.stableChecks=endChecks;done=true;
      console.log(`[搜索结束确认] ${task.keyword}: 最新分页与页面终点一致；详情缺口${evidence.gaps?.length||0}篇仍需计入入库验收分母`);break;
     }
     await waitForPacing(1500,{shouldStop:stop});continue;
    }
    endKey=null;endChecks=0;
    if(!cards.length&&!layoutRecovered){
     await ensureSingleColumn(page,{shouldStop:stop,onDiagnostic});layoutRecovered=true;
     console.log(`[列表恢复] ${task.keyword}: 重新核验单列布局，不重选最新、不重载搜索`);continue;
    }
    if(stagnant>=Number(config.maxStagnantRounds||15))throw new Error('SEARCH_STAGNANT_INCOMPLETE：分页与页面终点尚未共同确认，不以无增长冒充完成');
    await advanceSearch();round++;continue;
   }
   stagnant=0;endKey=null;endChecks=0;
   // One current visible card per pass, then rescan; virtual lists can rerender.
   const note=candidates[0];seen.add(note.noteId);
   const prior=checkpointCandidates(db,task.keyword).find(n=>n.noteId===note.noteId);
   if(prior?.status==='skipped_old'){
    if(recovering&&recoveryIds.delete(note.noteId))summary.recoveredOldNotes.push(note.noteId);
    summary.verified++;summary.old++;
    if(!recovering&&boundary.observe(note.noteId,prior.publishedAt))summary.oldDateWindowObserved=true;
    continue;
   }
   if(prior?.status==='completed'&&prior.result?.audit?.commentsComplete!==false&&!mediaRecoveryIds.has(note.noteId)){
    summary.verified++;summary.posts++;
    if(sampleLimit)summary.sampleNoteIds.push(note.noteId);
    summary.comments+=prior.result.comments?.length||0;
    if(!recovering&&boundary.observe(note.noteId,prior.publishedAt))summary.oldDateWindowObserved=true;
    if(sampleLimit&&summary.posts>=sampleLimit){summary.stopReason='sample_limit';done=true;}
    continue;
   }
   console.log(`[详情开始] ${task.keyword} / ${note.noteId}`);
   await writeJsonAtomic(path.join(outputDir,'collector_progress.json'),{...summary,currentNote:note.noteId,updatedAt:new Date().toISOString()});
   let opened=false,result=null,noteError=null,durable=false,dateExcluded=false;
   try{
    await openCard(page,note);opened=true;
    for(let attempt=0;attempt<10&&!observer.awemes.has(note.noteId);attempt++){await check();await pause(500);await observer.flush();}
    const raw=observer.awemes.get(note.noteId);
    if(!raw||String(raw.aweme_id)!==String(note.noteId))throw new Error('DETAIL_DATA_NOT_OBSERVED：详情响应未取得对应帖子');
    result=postFromAweme(raw,task);summary.verified++;
    const date=result.post.文章时间地点;
    if(!inTargetYear(date,config.targetYear||2026,task.cutoff||'2026-01-01')){
     markSkipped(db,task.keyword,note,'不在目标年度',date);summary.old++;dateExcluded=true;
     if(!recovering&&boundary.observe(note.noteId,date))summary.oldDateWindowObserved=true;
     console.log(`[日期跳过] ${note.noteId}: ${date}`);
    }else{
     let commentError=null;
     if(task.collectComments){
      try{const output=await collectComments(page,observer,result.post,{shouldStop:stop,maxRounds:Number(config.maxCommentScrolls)||0,priorResult:prior?.result,pacingConfig:config});result.comments=output.rows;result.commentAudits=output.commentAudits||[];result.audit.comments=output.audit;result.audit.commentsComplete=output.audit.complete;}
      catch(e){
       const merged=mergeCommentResults(result.post,prior?.result,{comments:e.partialComments||[],commentAudits:e.partialCommentAudits||[],audit:{comments:e.commentAudit}});
       result.comments=merged.rows;result.commentAudits=merged.commentAudits;result.audit.comments={...e.commentAudit,status:'incomplete',complete:false,aggregation_mode:'comment_thread',aggregation_version:1,collected:merged.rawCommentCount,raw_comment_count:merged.rawCommentCount,thread_count:merged.threadCount,orphan_comment_ids:merged.orphanCommentIds,unattached_comments:merged.unattachedComments};result.audit.commentsComplete=false;result.audit.commentsError=e.message;commentError=e;
      }
     }
     const job=config.asrEnabled&&result.post.文章视频链接?{keyword:task.keyword,noteId:note.noteId,articleId:note.noteId,mediaUrl:result.post.文章视频链接,referer:result.post.文章链接,prompt:null,sourceObserved:true}:null;
     markCompleted(db,task.keyword,note,result,{asrJob:job});
     durable=true;
     await importResults([result]);
     baseImported=true;releaseJobs();asr?.wake();
     summary.posts++;summary.comments+=result.comments.length;if(!recovering)boundary.observe(note.noteId,date);
     console.log(`[详情完成] ${result.post.文章标题}；评论讨论串${result.comments.length}条；文章已持久化${commit?'并入库':''}`);
     await writeJsonAtomic(path.join(outputDir,'collector_progress.json'),{...summary,currentNote:note.noteId,asr:asrJobStats(db),updatedAt:new Date().toISOString()});
     if(commentError)throw commentError;
     if(sampleLimit&&!recovering)summary.sampleNoteIds.push(note.noteId);
     if(sampleLimit&&!recovering&&summary.posts>=sampleLimit){summary.stopReason='sample_limit';done=true;}
    }
   }catch(e){
    noteError=e;
    if(!durable)markFailed(db,task.keyword,note,e);
    if(!recovering)boundary.observe(note.noteId,null);
    if(!recoverableContentGap(e))throw e;
    summary.contentGaps||=[];summary.contentGaps.push({noteId:note.noteId,reason:String(e.message).split('：')[0]});
    console.warn(`[单帖缺口保留] ${note.noteId}: 不计入成功；继续搜索并在最后核对80%入库率`);
   }finally{
    if(opened&&!/STOP_PLATFORM_RESTRICTION|STOP_LOGIN_REQUIRED/.test(noteError?.message||result?.audit?.commentsError||'')){
     try{await restoreSearch(page,task.keyword,note.noteId);}
     catch(closeError){throw Object.assign(new Error('STOP_SEARCH_CONTEXT_LOST：详情关闭未能恢复原检索列表'),{cause:closeError,originalContentError:noteError?.message});}
    }
   }
   if(recovering){
    recoveryIds.delete(note.noteId);
    if(!noteError&&durable)summary.recoveredDetailNotes.push(note.noteId);
    else if(!noteError&&dateExcluded)summary.recoveredOldNotes.push(note.noteId);
   }
   // Count actual card visits, including old-year details, not the frozen number
   // of imported current-year posts. The eighth visit rests exactly once.
   handled++;
   if(done)continue;
   const delay=itemPause(config,'posts',handled);
   console.log(`[采集休息] ${delay.kind}: ${Math.round(delay.ms/1000)}秒`);
   await waitForPacing(delay.ms,{shouldStop:stop});
  }
  await observer.flush();
  saveCandidates(db,task.keyword,observedLatestSearchCandidates(observer.searchPages,{keyword:task.keyword,after:prepared.at}),seen.size);
  summary.observedOldCandidateDispositions||=[];
  const finalResponsePlan=observedPlan();
  summary.searchResponseCandidateDiagnostics=finalResponsePlan.diagnostics;
  summary.observedOldCandidateDispositions.push(...settleObservedOldCandidates(db,task.keyword,finalResponsePlan.oldAwemes,config.targetYear||2026,task.cutoff||'2026-01-01',{evidenceById:finalResponsePlan.oldEvidence}));
  summary.observedOldCandidateDispositions.push(...settleObservedOldCandidates(db,task.keyword,observer.awemes,config.targetYear||2026,task.cutoff||'2026-01-01',{excludedIds:finalResponsePlan.conflictingIds}));
  const gaps=incompleteCandidates(checkpointCandidates(db,task.keyword));
  summary.knownIncomplete=gaps.map(n=>n.noteId);
  if(sampleLimit&&gaps.some(n=>summary.sampleNoteIds.includes(n.noteId)))throw new Error('KNOWN_CANDIDATES_INCOMPLETE：抽样必须逐条核验');
  if(sampleLimit&&summary.posts<sampleLimit)throw new Error(`SAMPLE_LIMIT_NOT_REACHED：搜索已结束但只取得${summary.posts}/${sampleLimit}篇，不能冒充抽样数量通过`);
  summary.status=sampleLimit?'sample_completed':'completed';
 }catch(e){
  error=e;summary.error=String(e.message||e);summary.status=/STOP_REQUESTED/.test(summary.error)?'partial_stopped':'incomplete';
  summary.firstFailureAt=new Date().toISOString();
  (summary.pageDiagnostics||=[]).push(await diagnostics.capture('collector_failure',e,{sortConfirmed:summary.sortConfirmed,firstFailureAt:summary.firstFailureAt}));
  console.error(`[采集异常] ${task.keyword}: ${summary.error}；当前媒体或入库收尾后退出`);
  await page.screenshot({path:path.join(outputDir,'failure-page.png'),timeout:4000,
    mask:[page.locator('input,canvas,iframe,[class*="qr"],[class*="QR"],[data-e2e*="qr"]')]}).catch(()=>{});
  const failureUi=await page.locator('[data-e2e]').evaluateAll(nodes=>nodes.filter(n=>/comment|feed-active-video|modal-video/.test(n.getAttribute('data-e2e'))).map(n=>({e2e:n.getAttribute('data-e2e'),visible:Boolean(n.getClientRects().length),cardId:n.closest('.search-result-card')?.querySelector('[data-e2e-vid]')?.getAttribute('data-e2e-vid'),text:n.innerText?.slice(0,100)}))).catch(()=>[]);
  await writeJsonAtomic(path.join(outputDir,'failure-ui.json'),{url:safeUrl(page.url()),error:safeText(summary.error),causes:diagnosticError(e),nodes:failureUi});
  await writeJsonAtomic(path.join(outputDir,'collector_progress.json'),{...summary,asr:asrJobStats(db),updatedAt:new Date().toISOString()});
 }
 finally{
  observer.detach();await observer.flush().catch(()=>{});
  if(asr){try{summary.asrFinalization=await finalizeAsr(asr,{volumeMode,closeOnly:Boolean(error&&!recoverableContentGap(error)),readStats:()=>asrJobStats(db)});}catch(e){summary.asrError=String(e.message);}}
  await service?.close().catch(()=>{});
  try{await check();const totals=await importSaved();summary.savedPosts=totals.posts;summary.savedComments=totals.comments;}catch(e){summary.importError=String(e.message);if(!error||e.code==='LEASE_LOST')error=e;summary.status=/STOP_REQUESTED/.test(error.message)?'partial_stopped':'incomplete';}
  summary.imports=db.prepare('SELECT import_status AS status,COUNT(*) AS count FROM candidate WHERE keyword=? AND status=\'completed\' GROUP BY import_status').all(task.keyword);
  const retryKey=`import_retry_cycles/${task.keyword}`;
  if(error?.importPending&&transientImportError(error)){
   const priorRetry=db.prepare('SELECT value FROM run_meta WHERE key=?').get(retryKey);
   const cycles=(Number(priorRetry?.value)||0)+1;
   setMeta(db,retryKey,cycles);summary.importRetryCycles=cycles;
   error.recoverableImport=true;error.recoveryExhausted=cycles>=3;
   summary.retryEligible=!error.recoveryExhausted;
  }else if(!error)setMeta(db,retryKey,0);
  summary.unresolvedMediaSources=settleExpiredMediaGaps(db,task.keyword,{scanComplete:!error&&verifiedAnnualSearchEnd(summary)});
  summary.asr=asrJobStats(db);
  summary.asr.runtimeUnavailable=Boolean(asr?.haltedReason);
  summary.importOk=commit&&!summary.importError;
  summary.asrAcceptance=assessAsrAcceptance(summary.asr,{required:!volumeMode&&Boolean(config.asrEnabled),allowExhaustedSkip:true});
  if(!error && summary.status==='completed' && summary.asrAcceptance.status==='accepted_with_skips'){
   summary.status='completed_with_skips';summary.asr.skippedExhausted=summary.asrAcceptance.skipped;
  }
  if(!volumeMode&&!error && (summary.asrError || !summary.asrAcceptance.ok)){
   error=Object.assign(new Error(`${summary.asrAcceptance.reason||'ASR_DRAIN_FAILED'}：字幕未通过最终验收`),{reviewRequired:summary.asrAcceptance.status==='asr_review_required'});
   summary.status=summary.asrAcceptance.status==='accepted'?'asr_deferred':summary.asrAcceptance.status;
   summary.error=error.message;
  }
  summary.annualBoundary={targetYear:boundary.year,requiredWindow:boundary.size,reached:boundary.reached,recent:boundary.recent};
  const noChange=unchangedRetry(retryBefore,retrySnapshot(db,task.keyword),{
   error:[summary.error,summary.asrError].filter(Boolean).join(' | '),status:summary.status,
   freshSearch:summary.sortConfirmed,boundedRecoverySearch:summary.boundedRecoverySearch,
   stopped:await stop(),importOk:commit&&!summary.importError,runtimeUnavailable:summary.asr.runtimeUnavailable,
   pendingAsr:summary.asr.pendingTotal||0});
  if(volumeMode&&!await stop()){
   try{summary.volumeAcceptance=await volumeRead();
    if(summary.volumeAcceptance.ok){summary.previousCollectionError=error?.message||null;
     summary.mustStopNode=Boolean(error&&/LOGIN_REQUIRED|SECURITY_CHALLENGE|PLATFORM_RESTRICTION/.test(error.message));
     summary.status='completed';summary.accepted=true;summary.error=null;error=null;}
    else if(!error){error=new Error(summary.volumeAcceptance.reason);summary.status='incomplete';summary.error=error.message;}
   }catch(e){error=e;summary.status='incomplete';summary.error='VOLUME_DATABASE_READBACK_FAILED';}
  }else if(commit&&!sampleLimit&&!error){
   try{summary.coverage=await verifyCheckpointCoverage({checkpointDb:path.join(stateDir,'checkpoint.sqlite'),keyword:task.keyword,scanComplete:verifiedAnnualSearchEnd(summary),year:config.targetYear||2026,cutoff:task.cutoff||'2026-01-01'});}
   catch(e){summary.coverage={ok:false,reason:'DB_READBACK_FAILED',errorCode:e.code||'READBACK_ERROR'};}
   if(!summary.coverage.ok){error=new Error(summary.coverage.reason);summary.status='incomplete';summary.error=error.message;}
   else if(summary.coverage.unresolved){summary.status='completed_with_skips';summary.accepted=true;}
  }
  if(noChange)summary.stagnationEvidence=noChange;
  setMeta(db,'collection_summary',summary);
  summary.finishedAt=new Date().toISOString();
  await exportCheckpoint(db,outputDir,{projectName:task.projectName,cutoff:task.cutoff||'2026-01-01',targetYear:config.targetYear||2026,collectComments:task.collectComments,collectionCompleteness:summary.status});
  await writeJsonAtomic(path.join(outputDir,'collector_status.json'),summary);
  diagnostics.dispose();
  db.close();
 }
 if(error)throw Object.assign(error,{collectionSummary:summary});
 return summary;
}
