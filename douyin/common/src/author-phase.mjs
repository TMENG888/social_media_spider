import mysql from 'mysql2/promise';
import {createHash} from 'node:crypto';
import {RedisDispatcher} from './redis-dispatcher.mjs';
import {mysqlConnectionOptions,retryMysqlDeadlock} from './import-mysql.mjs';
import {DouyinResponseObserver} from './douyin-data.mjs';
import {assertAccess} from './douyin-browser.mjs';
import {withImportLease} from './lease-guard.mjs';
import {itemPause,waitForPacing} from './collection-pacing.mjs';
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
export function authorTasksFromRows(rows){
 return [...new Set(rows.map(r=>String(r.authorId||'')).filter(Boolean))].sort().map((authorId,i)=>({id:`dy-author-${createHash('sha256').update(authorId).digest('hex')}`,redisTaskId:`dy-author-${createHash('sha256').update(authorId).digest('hex')}`,authorId,sequence:i+1,keyword:authorId,topic:'作者'}));
}
export function assertAuthorStats(profile){
 for(const key of ['follower_count','total_favorited'])if(profile?.[key]==null||!Number.isFinite(Number(profile[key]))||Number(profile[key])<0)throw new Error(`AUTHOR_PROFILE_STATS_MISSING：${key}缺少有效数据，不确认任务`);
 return profile;
}
export async function collectAuthorProfile(page,observer,authorId,{shouldStop=async()=>false}={}){
 await page.goto(`https://www.douyin.com/user/${encodeURIComponent(authorId)}`,{waitUntil:'domcontentloaded',timeout:45000});
 let profile;
 for(let i=0;i<20;i++){
  if(await shouldStop())throw new Error('STOP_REQUESTED：作者采集安全停止');
  await assertAccess(page);await observer.flush();profile=observer.profiles.get(authorId);if(profile)break;await sleep(500);
 }
 if(!profile)throw new Error('AUTHOR_PROFILE_DATA_MISSING：不以空值确认作者任务');
 return assertAuthorStats(profile);
}
export async function backfillAuthorProfile(authorId,profile){
 assertAuthorStats(profile);
 return retryMysqlDeadlock(()=>withImportLease(async verify=>{
  const db=await mysql.createConnection(mysqlConnectionOptions());
  try{await verify();await db.beginTransaction();
   const[updated]=await db.execute('UPDATE ods_social_media_post SET `作者粉丝数`=?,`作者点赞数`=? WHERE `平台`=? AND `作者id`=?',[profile.follower_count,profile.total_favorited,'抖音',authorId]);
   await verify();await db.commit();return {affectedRows:updated.affectedRows};
  }catch(e){await db.rollback();throw e;}finally{await db.end();}
 }));
}
export async function authorPhase({page,root,stateRoot,workerId,stopFile,postDispatcher,config,shouldStop}) {
 const stats=await postDispatcher.queue.stats();
 if(stats.counts.completed!==stats.counts.total||stats.counts.total===0)return {status:'waiting_for_posts',posts:stats.counts};
 const connection=await mysql.createConnection(mysqlConnectionOptions());
 let tasks;
 try{
  const [rows]=await connection.query('SELECT DISTINCT `作者id` AS authorId FROM ods_social_media_post WHERE `平台`=? AND `项目` IN (?,?) AND `作者id` IS NOT NULL',['抖音','全国地产设计产品力监测','北京臻澐项目口碑']);
  tasks=authorTasksFromRows(rows);
 }finally{await connection.end();}
 const hash=createHash('sha256').update(JSON.stringify(tasks)).digest('hex');
 const dispatcher=await RedisDispatcher.open({root,stateRoot,workerId,skipImport:false,stopFile,manifestOverride:{manifestHash:hash,taskCount:tasks.length,tasks},campaignOverride:`${postDispatcher.campaign}-authors-${hash.slice(0,12)}`});
 const observer=new DouyinResponseObserver(page);let completed=0;
 try{
  for await(const[,task]of dispatcher.tasks()){
   Object.assign(process.env,dispatcher.env());
   if(await shouldStop())break;
   const profile=await collectAuthorProfile(page,observer,task.authorId,{shouldStop});
   await backfillAuthorProfile(task.authorId,profile);
   await dispatcher.finish('complete',{authorId:task.authorId,followerCount:profile.follower_count,totalFavorited:profile.total_favorited??null});completed++;
   console.log(`[作者回填] ${profile.nickname}: 粉丝${profile.follower_count}，获赞${profile.total_favorited??'未知'}`);
   await waitForPacing(itemPause(config,'authors',completed).ms,{shouldStop});
  }
  return {status:await shouldStop()?'partial_stopped':'completed',completed};
 }finally{observer.detach();await dispatcher.close({stopped:await shouldStop()});Object.assign(process.env,postDispatcher.env());}
}
