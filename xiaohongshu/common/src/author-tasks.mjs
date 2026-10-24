import fs from 'node:fs/promises';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { stableId } from './schema.mjs';
import {assertPlatformAccess} from './platform-access.mjs';

export function postsReady(counts, expectedTotal) {
  return Number(expectedTotal) > 0 && counts?.total === expectedTotal
    && counts.completed === expectedTotal && !counts.pending && !counts.leased && !counts.failed;
}

export function buildAuthorTasks(rows) {
  const authors = new Set();
  const rejected = [];
  for (const row of rows) {
    if (row['平台'] && row['平台'] !== '小红书') continue;
    const id = String(row['作者id'] || '').trim().toLowerCase();
    if (!/^[a-f0-9]{24}$/.test(id)) { rejected.push({ articleId: row['文章id'] || null, reason: 'AUTHOR_ID_INVALID' }); continue; }
    authors.add(id);
  }
  return { rejected, tasks: [...authors].sort().map(id => ({
    redisTaskId: stableId('xhs-author-v1:'+id), authorId: id, kind: 'author',
    keyword: id, topic: '作者补采', sequence: parseInt(id.slice(0,8),16)+1
  })) };
}

export function validAuthorUrl(value, authorId) {
  try {
    const url = new URL(value);
    if (url.hostname !== 'www.xiaohongshu.com' || url.protocol !== 'https:'
      || url.pathname !== '/user/profile/'+authorId) return null;
    return url.toString();
  } catch { return null; }
}

export function parseAuthorMetrics(body) {
  const count = label => {
    const match = body.match(new RegExp('([\\d,]+(?:\\.\\d+)?\\s*[万亿wWkK]?)\\s*'+label));
    if (!match) return null;
    const raw=match[1].replace(/[\s,]/g,'');
    const multiplier=/[万wW]$/.test(raw)?10000:/亿$/.test(raw)?100000000:/[kK]$/.test(raw)?1000:1;
    const value=Number.parseFloat(raw)*multiplier;
    return Number.isFinite(value) && value>=0 ? Math.round(value) : null;
  };
  return { followerCount:count('粉丝'),likeCount:count('获赞与收藏') };
}

export async function assertAuthorAccessible(page, authorId = null) {
  await assertPlatformAccess(page,'小红书');
  if (page.isClosed()) throw new Error('STOP_BROWSER_CLOSED：作者采集页已关闭');
  if (await page.getByText('当前笔记暂时无法浏览',{exact:true}).isVisible().catch(()=>false))
    throw new Error('STOP_AUTHOR_UNAVAILABLE：作者页访问受限；停止本节点，不影响帖子状态');
  if(authorId && !validAuthorUrl(page.url(),authorId))
    throw new Error('STOP_AUTHOR_CONTEXT_LOST：作者页面跳转至非目标作者地址：'+page.url().split('?')[0]);
}

export async function collectAuthor(page, task, url, {verify=async()=>{},shouldStop=async()=>false,timeout=45000}={}) {
  if(await shouldStop())throw new Error('STOP_REQUESTED：打开下一位作者前安全停止');
  await verify();
  const target=validAuthorUrl(url,task.authorId);
  if(!target)throw new Error('AUTHOR_URL_INVALID');
  await page.goto(target,{waitUntil:'domcontentloaded',timeout});
  // Inspect visible counters only. Do not issue private API requests or solve challenges.
  for(let attempt=0;attempt<12;attempt++){
    await verify();await assertAuthorAccessible(page);
    const metrics=parseAuthorMetrics(await page.locator('body').innerText());
    if(metrics.followerCount!==null && metrics.likeCount!==null){
      await assertAuthorAccessible(page,task.authorId);
      return {...metrics,authorId:task.authorId,collectedAt:new Date().toISOString(),source:'visible_profile'};
    }
    if(await shouldStop())throw new Error('STOP_REQUESTED：作者统计未就绪，保留任务');
    await page.waitForTimeout(500);
  }
  await assertAuthorAccessible(page,task.authorId);
  throw new Error('AUTHOR_METRICS_MISSING：未发现两项作者统计，不伪造为零');
}

export class AuthorCheckpoint {
  constructor(file){
    this.db=new DatabaseSync(file);
    this.db.exec('PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; CREATE TABLE IF NOT EXISTS author_snapshot(author_id TEXT PRIMARY KEY,payload TEXT NOT NULL,status TEXT NOT NULL);');
  }
  get(id){const row=this.db.prepare('SELECT payload,status FROM author_snapshot WHERE author_id=?').get(id);return row?{...JSON.parse(row.payload),localStatus:row.status}:null;}
  save(snapshot,status='pending_import'){
    this.db.prepare('INSERT INTO author_snapshot VALUES(?,?,?) ON CONFLICT(author_id) DO UPDATE SET payload=excluded.payload,status=excluded.status')
      .run(snapshot.authorId,JSON.stringify(snapshot),status);
  }
  async export(directory){
    await fs.mkdir(directory,{recursive:true});
    const rows=this.db.prepare('SELECT payload,status FROM author_snapshot ORDER BY author_id').all().map(row=>({...JSON.parse(row.payload),localStatus:row.status}));
    await fs.writeFile(path.join(directory,'author_snapshots.jsonl'),rows.map(JSON.stringify).join('\n')+(rows.length?'\n':''));
    return rows.length;
  }
  close(){this.db.close();}
}

export async function updateAuthorMetrics(connection,snapshot,{verify=async()=>{}}={}){
  if(!/^[a-f0-9]{24}$/.test(snapshot.authorId) || ![snapshot.followerCount,snapshot.likeCount].every(v=>Number.isSafeInteger(v)&&v>=0))throw new Error('AUTHOR_SNAPSHOT_INVALID');
  let locked=false;
  try{
    const [lock]=await connection.query("SELECT GET_LOCK('social_xhs_distributed_import',120) AS acquired");
    if(Number(lock[0]?.acquired)!==1)throw new Error('AUTHOR_IMPORT_LOCK_TIMEOUT');locked=true;
    await verify();await connection.beginTransaction();
    const [matched]=await connection.execute('SELECT COUNT(*) AS n FROM `ods_social_media_post` WHERE `平台`=? AND `作者id`=?',['小红书',snapshot.authorId]);
    if(!Number(matched[0]?.n))throw new Error('AUTHOR_POSTS_NOT_FOUND：源帖子已不存在，禁止空更新确认完成');
    const [result]=await connection.execute('UPDATE `ods_social_media_post` SET `作者粉丝数`=?,`作者点赞数`=? WHERE `平台`=? AND `作者id`=?',
      [snapshot.followerCount,snapshot.likeCount,'小红书',snapshot.authorId]);
    await verify();await connection.commit();
    return {matchedPosts:Number(matched[0].n),changedRows:Number(result.affectedRows||0)};
  }catch(error){await connection.rollback().catch(()=>{});throw error;}
  finally{if(locked)await connection.query("SELECT RELEASE_LOCK('social_xhs_distributed_import')").catch(()=>{});}
}
