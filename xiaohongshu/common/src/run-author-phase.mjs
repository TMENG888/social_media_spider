import fs from 'node:fs/promises';
import path from 'node:path';
import mysql from 'mysql2/promise';
import {chromium} from 'playwright';
import {RedisDispatcher} from './redis-dispatcher.mjs';
import {mysqlConnectionOptions} from './import-mysql.mjs';
import {withImportLease} from './lease-guard.mjs';
import {writeJsonAtomic} from './checkpoint.mjs';
import {postsReady,buildAuthorTasks,validAuthorUrl,collectAuthor,AuthorCheckpoint,updateAuthorMetrics} from './author-tasks.mjs';
import {itemPause,waitForPacing} from './collection-pacing.mjs';

export async function runAuthorPhase({root,stateRoot,runsRoot,workerId,stopFile,postDispatcher,cdpUrl,cooldown=null,
  createConnection=()=>mysql.createConnection(mysqlConnectionOptions()),openDispatcher=options=>RedisDispatcher.open(options),
  connectBrowser=url=>chromium.connectOverCDP(url,{timeout:15000}),fencedImport=withImportLease}){
  const report={phase:'authors',status:'running',completed:0,startedAt:new Date().toISOString(),tasks:[]};
  const output=path.join(runsRoot,'authors',postDispatcher.campaign);
  const authorState=path.join(stateRoot,'authors',postDispatcher.campaign);
  await fs.mkdir(authorState,{recursive:true});await fs.mkdir(output,{recursive:true});
  let connection,dispatcher,browser,store;
  const stopped=()=>fs.access(stopFile).then(()=>true).catch(()=>false);
  try{
    await cooldown?.assertReady();
    const stats=await postDispatcher.queue.stats();
    if(!postsReady(stats.counts,postDispatcher.manifest.taskCount)){
      report.status='waiting_for_posts';report.postCounts=stats.counts;
      console.log('[阶段门禁] 帖子任务尚未全部完成，作者队列保持关闭');return report;
    }
    if(await stopped()){report.status='partial_stopped';return report;}
    connection=await createConnection();
    const [rows]=await connection.execute('SELECT `作者id`,`文章id`,`平台` FROM `ods_social_media_post` WHERE `平台`=?',['小红书']);
    const {tasks,rejected}=buildAuthorTasks(rows);
    report.rejectedAuthors=rejected;report.totalAuthors=tasks.length;
    await writeJsonAtomic(path.join(output,'author_manifest.json'),{source:'mysql/ods_social_media_post',postCampaign:postDispatcher.campaign,taskCount:tasks.length,tasks,rejected});
    if(rejected.length)throw new Error('AUTHOR_SOURCE_INVALID：'+rejected.length+'篇帖子缺少有效作者ID，需修复源数据');
    if(!tasks.length){report.status='completed';return report;}
    const campaign=postDispatcher.campaign+'-authors-v1';
    report.campaign=campaign;
    dispatcher=await openDispatcher({root,stateRoot:authorState,workerId,skipImport:false,stopFile,
      campaignOverride:campaign,manifestOverride:{taskCount:tasks.length,tasks,manifestHash:'authors-v1'}});
    // Author pool uses a different cluster hash tag; check shared guard directly.
    dispatcher.cooldown=cooldown;
    store=new AuthorCheckpoint(path.join(authorState,'authors.sqlite'));
    browser=await connectBrowser(cdpUrl);
    const page=browser.contexts()[0].pages().find(p=>p.url().includes('xiaohongshu.com'))||browser.contexts()[0].pages()[0];
    if(!page)throw new Error('AUTHOR_BROWSER_PAGE_MISSING');
    const config=JSON.parse(await fs.readFile(path.join(root,'config.json'),'utf8'));
    for await(const [,task] of dispatcher.tasks()){
      if(await stopped()){report.status='partial_stopped';break;}
      if(!postsReady((await postDispatcher.queue.stats()).counts,postDispatcher.manifest.taskCount))throw new Error('STOP_POST_PHASE_REOPENED：帖子任务重新开放，停止作者阶段');
      try{
        await cooldown?.assertReady();
        let snapshot=store.get(task.authorId);
        if(!snapshot){
          const [links]=await connection.execute('SELECT `作者主页链接` FROM `ods_social_media_post` WHERE `平台`=? AND `作者id`=? ORDER BY `文章获取时间` DESC LIMIT 100',['小红书',task.authorId]);
          const url=links.map(r=>validAuthorUrl(r['作者主页链接'],task.authorId)).find(Boolean);
          if(!url)throw new Error('AUTHOR_SOURCE_LINK_MISSING：数据表无有效作者主页链接');
          snapshot=await collectAuthor(page,task,url,{verify:async()=>{await cooldown?.assertReady();await dispatcher.verify();},shouldStop:stopped,timeout:config.navigationTimeoutMs||45000});
          store.save(snapshot);
        }
        // Persist first, then fenced idempotent SQL update, then Redis ack.
        const updated=await fencedImport(verify=>updateAuthorMetrics(connection,snapshot,{verify}),{...process.env,...dispatcher.env(),XHS_WORKER_ROOT:root});
        store.save(snapshot,'completed');
        await dispatcher.finish('complete',{...snapshot,...updated});
        report.completed++;report.tasks.push({authorId:task.authorId,status:'completed',...updated});
        console.log(`[作者回填] ${task.authorId}：粉丝${snapshot.followerCount}，获赞与收藏${snapshot.likeCount}，关联${updated.matchedPosts}篇帖子`);
      }catch(error){
        await cooldown?.record(error,`author:${postDispatcher.owner}:${task.authorId}`);
        if(!dispatcher.lost){
          const release=/^STOP_(?:REQUESTED|SECURITY_CHALLENGE|LOGIN_REQUIRED|POST_PHASE_REOPENED)|^(?:RATE_LIMIT_COOLDOWN_ACTIVE|COOLDOWN_MANUAL_REQUIRED)/.test(String(error.message));
          await dispatcher.finish(release?'release':'fail',{error:String(error.message)});
        }
        throw error; // First author-page restriction stops the node, not subsequent authors.
      }
      const pause=itemPause(config,'authors',report.completed);
      if(pause.kind==='batch')console.log(`[作者批次休息] 已完成${report.completed}位作者，休息${Math.ceil(pause.ms/1000)}秒；可安全停止`);
      await waitForPacing(pause.ms,{shouldStop:stopped});
    }
    const final=await dispatcher.report();report.counts=final.counts;
    await writeJsonAtomic(path.join(stateRoot,'redis_queue_status.json'),{campaign,phase:'authors',...final});
    report.status=await stopped()?'partial_stopped':final.counts.failed?'author_failed':final.counts.completed===final.counts.total?'completed':'incomplete';
    if(report.status==='author_failed'||report.status==='incomplete')throw new Error('AUTHOR_PHASE_INCOMPLETE');
    return report;
  }catch(error){
    report.status=String(error.message).startsWith('STOP_REQUESTED')?'partial_stopped':'author_failed';
    report.error=String(error.message);throw error;
  }finally{
    report.finishedAt=new Date().toISOString();
    await store?.export(output).catch(()=>{});store?.close();
    await dispatcher?.close({stopped:await stopped()}).catch(()=>{});
    await browser?.close().catch(()=>{});await connection?.end().catch(()=>{});
    await writeJsonAtomic(path.join(output,'author_status.json'),report);
  }
}
