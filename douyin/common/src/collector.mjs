import fs from 'node:fs/promises';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import mysql from 'mysql2/promise';
import {openCheckpoint,saveCandidates,checkpointCandidates,markCompleted,markSkipped,markFailed,setMeta,completedResults,exportCheckpoint,asrJobStats,writeJsonAtomic} from './checkpoint.mjs';
import {YearBoundary,inTargetYear} from './collection-policy.mjs';
import {postFromAweme,DouyinResponseObserver,shanghaiTime} from './douyin-data.mjs';
import {assertAccess,searchUrl,selectLatest,visibleCards,openCard,restoreSearch,collectComments} from './douyin-browser.mjs';
import {AsrService} from './asr.mjs';
import {AsrJobProcessor} from './asr-jobs.mjs';
import {importRows,mysqlConnectionOptions,retryMysqlDeadlock} from './import-mysql.mjs';
import {assertLocalLease,withImportLease} from './lease-guard.mjs';
import {itemPause,waitForPacing} from './collection-pacing.mjs';
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function patchTranscript(result) {
 await retryMysqlDeadlock(()=>withImportLease(async verify=>{
  const connection=await mysql.createConnection(mysqlConnectionOptions());
  try{
   await verify();
   // Backfills allocate no IDs. Resolve a unique row without taking broad
   // predicate locks, then update its primary key only. The shared allocation
   // lock remains in importRows, not in this single-column operation.
   const[rows]=await connection.execute('SELECT `id` FROM ods_social_media_post WHERE `平台`=? AND `项目`=? AND `文章id`=? LIMIT 2',['抖音',result.post.项目,result.post.文章id]);
   if(rows.length!==1)throw new Error(rows.length?'ASR_DUPLICATE_BASE_POST':'ASR_BASE_POST_NOT_IMPORTED');
   await connection.beginTransaction();
   const [updated]=await connection.execute('UPDATE ods_social_media_post SET `文章视频内容`=? WHERE `id`=?',[result.post.文章视频内容,rows[0].id]);
   if(!updated.affectedRows)throw new Error('ASR_BASE_POST_NOT_IMPORTED');
   await verify();await connection.commit();
  }catch(e){await connection.rollback();throw e;}finally{await connection.end();}
 }));
}
export async function collectKeyword({page,task,config,commonRoot,stateDir,outputDir,shouldStop,sampleLimit=0,commit=true,allowManualLogin=false}) {
 await fs.mkdir(stateDir,{recursive:true});await fs.mkdir(outputDir,{recursive:true});
 const db=openCheckpoint(path.join(stateDir,'checkpoint.sqlite'));
 const observer=new DouyinResponseObserver(page),boundary=new YearBoundary(config.targetYear||2026,task.searchStopWindow||8);
 const seen=new Set(),summary={keyword:task.keyword,topic:task.topic,status:'running',posts:0,comments:0,verified:0,old:0,error:null,sortConfirmed:false,stopReason:null};
 if(sampleLimit)summary.sampleNoteIds=[];
 let service=null,asr=null,error=null,baseImported=false;
 const stop=async()=>{await assertLocalLease();return shouldStop?await shouldStop():false;};
 const check=async()=>{if(await stop())throw new Error('STOP_REQUESTED：已安全停止');};
 const releaseJobs=()=>db.prepare("UPDATE asr_job SET status='pending' WHERE status='waiting_import'").run();
 const importSaved=async()=>{
  const results=completedResults(db),posts=results.map(r=>r.post),comments=results.flatMap(r=>r.comments||[]);
  if(commit&&posts.length){await importRows({posts,comments,shouldStop:stop});console.log(`[断点保全入库] ${task.keyword}: ${posts.length}篇，${comments.length}条评论`);}
  baseImported=true;releaseJobs();asr?.wake();return {posts:posts.length,comments:comments.length};
 };
 try{
  await check();
  if(config.asrEnabled){
   service=new AsrService({pythonExecutable:path.join(commonRoot,'runtime/python/python.exe'),model:path.resolve(commonRoot,config.asrModelPath),device:config.asrDevice||'cpu',computeType:config.asrComputeType||'int8_float32',cpuThreads:config.asrCpuThreads||1,beamSize:config.asrBeamSize||1,localFilesOnly:true,tempDir:path.join(stateDir,'media'),cacheDir:path.join(stateDir,'asr-cache')});
   asr=new AsrJobProcessor({db,service,mediaDir:path.join(stateDir,'media'),keepMedia:config.asrKeepMedia!==false,shouldStop:stop,onCompleted:async(_job,_output,result)=>{if(commit&&baseImported)await patchTranscript(result);}});
  }
  await importSaved();
  asr?.start().catch(e=>{summary.asrError=String(e.message);});
  await page.goto(searchUrl(task.keyword),{waitUntil:'domcontentloaded',timeout:config.navigationTimeoutMs||45000});
  await pause(2500);
  if(allowManualLogin){
   const deadline=Date.now()+300000;
   while(Date.now()<deadline){
    await check();
    try{await assertAccess(page);break;}catch(e){if(!/LOGIN_REQUIRED/.test(e.message))throw e;console.log('[人工登录] 请在采集浏览器窗口中完成抖音登录；不会自动填写账号或验证码');await pause(5000);}
   }
  }
  await assertAccess(page);
  await selectLatest(page,observer,task.keyword);summary.sortConfirmed=true;
  await page.screenshot({path:path.join(outputDir,'latest-search.png'),timeout:4000}).catch(()=>{});
  console.log(`[筛选确认] ${task.keyword}: 最新发布，全年日期不限；后续不逐帖重选筛选`);
  let stagnant=0,round=0,done=false;
  while(!done){
   await check();await assertAccess(page);await observer.flush();
   const cards=await visibleCards(page);
   const candidates=cards.filter(n=>!seen.has(n.noteId));
   saveCandidates(db,task.keyword,cards,seen.size);
   if(!candidates.length){
    stagnant++;if(stagnant>=Number(config.maxStagnantRounds||15))throw new Error('SEARCH_STAGNANT_INCOMPLETE：尚未核验年度边界，不以无增长冒充完成');
    await page.mouse.wheel(0,750);await pause(2000);round++;continue;
   }
   stagnant=0;
   // One current visible card per pass, then rescan; virtual lists can rerender.
   const note=candidates[0];seen.add(note.noteId);
   const prior=checkpointCandidates(db,task.keyword).find(n=>n.noteId===note.noteId);
   if(prior?.status==='skipped_old'){
    if(boundary.observe(note.noteId,prior.publishedAt)){summary.stopReason='year_boundary';done=true;}
    continue;
   }
   if(prior?.status==='completed'&&prior.result?.audit?.commentsComplete!==false){
    summary.verified++;summary.posts++;
    if(sampleLimit)summary.sampleNoteIds.push(note.noteId);
    summary.comments+=prior.result.comments?.length||0;
    if(boundary.observe(note.noteId,prior.publishedAt)){summary.stopReason='year_boundary';done=true;}
    if(sampleLimit&&summary.posts>=sampleLimit){summary.stopReason='sample_limit';done=true;}
    continue;
   }
   console.log(`[详情开始] ${task.keyword} / ${note.noteId}`);
   await writeJsonAtomic(path.join(outputDir,'collector_progress.json'),{...summary,currentNote:note.noteId,updatedAt:new Date().toISOString()});
   let opened=false,result=null,noteError=null;
   try{
    await openCard(page,note);opened=true;
    for(let attempt=0;attempt<10&&!observer.awemes.has(note.noteId);attempt++){await check();await pause(500);await observer.flush();}
    const raw=observer.awemes.get(note.noteId);
    if(!raw)throw new Error('DETAIL_DATA_NOT_OBSERVED：详情响应未取得对应帖子');
    result=postFromAweme(raw,task);summary.verified++;
    const date=result.post.文章时间地点;
    if(!inTargetYear(date,config.targetYear||2026,task.cutoff||'2026-01-01')){
     markSkipped(db,task.keyword,note,'不在目标年度',date);summary.old++;
     if(boundary.observe(note.noteId,date)){summary.stopReason='year_boundary';done=true;}
     console.log(`[日期跳过] ${note.noteId}: ${date}`);
    }else{
     let commentError=null;
     if(task.collectComments){
      try{const output=await collectComments(page,observer,result.post,{shouldStop:stop,maxRounds:Number(config.maxCommentScrolls)||0,priorResult:prior?.result});result.comments=output.rows;result.commentAudits=output.commentAudits||[];result.audit.comments=output.audit;result.audit.commentsComplete=output.audit.complete;}
      catch(e){
       const comments=new Map((prior?.result?.comments||[]).map(c=>[c.评论id,c]));for(const c of e.partialComments||[])comments.set(c.评论id,c);
       const audits=new Map((prior?.result?.commentAudits||[]).map(c=>[c.comment_id,c]));for(const c of e.partialCommentAudits||[])audits.set(c.comment_id,c);
       result.comments=[...comments.values()];result.commentAudits=[...audits.values()];result.audit.comments=e.commentAudit||{status:'incomplete',complete:false};result.audit.commentsComplete=false;result.audit.commentsError=e.message;commentError=e;
      }
     }
     const job=config.asrEnabled&&result.post.文章视频链接?{keyword:task.keyword,noteId:note.noteId,articleId:note.noteId,mediaUrl:result.post.文章视频链接,referer:result.post.文章链接,prompt:null}:null;
     markCompleted(db,task.keyword,note,result,{asrJob:job});
     if(commit)await importRows({posts:[result.post],comments:result.comments,shouldStop:stop});
     baseImported=true;releaseJobs();asr?.wake();
     summary.posts++;summary.comments+=result.comments.length;boundary.observe(note.noteId,date);
     console.log(`[详情完成] ${result.post.文章标题}；评论${result.comments.length}条；文章已持久化${commit?'并入库':''}`);
     await writeJsonAtomic(path.join(outputDir,'collector_progress.json'),{...summary,currentNote:note.noteId,asr:asrJobStats(db),updatedAt:new Date().toISOString()});
     if(commentError)throw commentError;
     if(sampleLimit)summary.sampleNoteIds.push(note.noteId);
     if(sampleLimit&&summary.posts>=sampleLimit){summary.stopReason='sample_limit';done=true;}
    }
   }catch(e){
    noteError=e;
    if(!result||!result.audit?.commentsError)markFailed(db,task.keyword,note,e);
    boundary.observe(note.noteId,null);throw e;
   }finally{
    if(opened&&!/STOP_PLATFORM_RESTRICTION|STOP_LOGIN_REQUIRED/.test(noteError?.message||result?.audit?.commentsError||'')){
     try{await restoreSearch(page,task.keyword,note.noteId);}
     catch(closeError){if(!noteError)throw closeError;noteError.searchRestoreError=String(closeError.message);console.warn(`[搜索收尾异常] ${closeError.message}；保留原始采集错误，不覆盖`);}
    }
   }
   const delay=itemPause(config,'posts',summary.posts);
   console.log(`[采集休息] ${delay.kind}: ${Math.round(delay.ms/1000)}秒`);
   await waitForPacing(delay.ms,{shouldStop:stop});
  }
  const gaps=checkpointCandidates(db,task.keyword).filter(n=>n.status==='failed'||(n.status==='completed'&&n.result?.audit?.commentsComplete===false));
  summary.knownIncomplete=gaps.map(n=>n.noteId);
  if(gaps.some(n=>!sampleLimit||summary.sampleNoteIds.includes(n.noteId)))throw new Error(`KNOWN_CANDIDATES_INCOMPLETE：${gaps.map(n=>n.noteId).join(',')}；已知详情/评论缺口未补齐，不能确认年度完成`);
  summary.status=sampleLimit?'sample_completed':'completed';
 }catch(e){
  error=e;summary.error=String(e.message||e);summary.status=/STOP_REQUESTED/.test(summary.error)?'partial_stopped':'incomplete';
  console.error(`[采集异常] ${task.keyword}: ${summary.error}；当前媒体或入库收尾后退出`);
  await page.screenshot({path:path.join(outputDir,'failure-page.png'),timeout:4000}).catch(()=>{});
  const failureUi=await page.locator('[data-e2e]').evaluateAll(nodes=>nodes.filter(n=>/comment|feed-active-video|modal-video/.test(n.getAttribute('data-e2e'))).map(n=>({e2e:n.getAttribute('data-e2e'),visible:Boolean(n.getClientRects().length),cardId:n.closest('.search-result-card')?.querySelector('[data-e2e-vid]')?.getAttribute('data-e2e-vid'),text:n.innerText?.slice(0,100)}))).catch(()=>[]);
  await writeJsonAtomic(path.join(outputDir,'failure-ui.json'),{url:page.url(),error:summary.error,nodes:failureUi});
  await writeJsonAtomic(path.join(outputDir,'collector_progress.json'),{...summary,asr:asrJobStats(db),updatedAt:new Date().toISOString()});
 }
 finally{
  observer.detach();await observer.flush().catch(()=>{});
  if(asr){try{if(error)await asr.close();else await asr.drain();}catch(e){summary.asrError=String(e.message);}}
  await service?.close().catch(()=>{});
  try{await check();const totals=await importSaved();summary.savedPosts=totals.posts;summary.savedComments=totals.comments;}catch(e){summary.importError=String(e.message);if(!error)error=e;summary.status='incomplete';}
  summary.asr=asrJobStats(db);
  summary.annualBoundary={targetYear:boundary.year,requiredWindow:boundary.size,reached:boundary.reached,recent:boundary.recent};
  setMeta(db,'collection_summary',summary);
  await exportCheckpoint(db,outputDir,{projectName:task.projectName,cutoff:task.cutoff||'2026-01-01',targetYear:config.targetYear||2026,collectComments:task.collectComments,collectionCompleteness:summary.status});
  await writeJsonAtomic(path.join(outputDir,'collector_status.json'),summary);
  db.close();
 }
 if(error)throw Object.assign(error,{collectionSummary:summary});
 return summary;
}
