import fs from 'node:fs';
import path from 'node:path';
import mysql from 'mysql2/promise';
import { atomicWriteFileSync } from './atomic-file.mjs';
import {ProductionOutputRecorder,meaningfulHint,finishOutput,recoverCommittedOutputs} from './production-output.mjs';

const args = {};
for (let i = 2; i < process.argv.length; i += 1) {
  if (process.argv[i].startsWith('--')) args[process.argv[i].slice(2)] = process.argv[i + 1]?.startsWith('--') ? true : process.argv[++i];
}
const postsFile = path.resolve(String(args.posts || ''));
const commentsFile = args.comments && args.comments !== true ? path.resolve(String(args.comments)) : null;
const statusFile = path.resolve(String(args.status || path.join(path.dirname(postsFile), 'mysql_import_status.json')));
const host = process.env.MYSQL_HOST || '127.0.0.1';
const port = Number(process.env.MYSQL_PORT || 3306);
const database = process.env.MYSQL_DATABASE || 'social';
const user = process.env.MYSQL_USER;
const password = process.env.MYSQL_PASSWORD;
if (!postsFile || !fs.existsSync(postsFile)) throw new Error(`文章文件不存在: ${postsFile}`);
if (!user || !password) throw new Error('MYSQL_USER 和 MYSQL_PASSWORD 未设置，拒绝无凭据入库');
const read = (file) => fs.existsSync(file) ? fs.readFileSync(file, 'utf8').split(/\r?\n/).filter(Boolean).map(JSON.parse) : [];
const posts = read(postsFile), comments = commentsFile ? read(commentsFile) : [];
const postFields = ['id','文章图片链接','文章图片信息','作者名字','文章标题','文章内容','文章标签','文章时间地点','文章点赞数','文章收藏数','文章评论数','文章链接','文章id','作者主页链接','文章视频链接','文章视频内容','关键词','作者id','作者粉丝数','作者点赞数','文章分享数','文章视频时长','平台','文章获取时间','文章标注','分类','清洗标注','项目','地点','内容类型','是否广告','广告关键词'];
const commentFields = ['id','评论id','评论用户链接','评论用户id','评论用户名字','评论内容','评论时间','评论IP','评论点赞数','评论回复数','文章链接','文章id','关键词','评论获取时间','平台','分类','项目','清洗标注'];
const value = (row, field) => row[field] === '' || row[field] === undefined ? null : row[field];
const makeId = (seed) => { let h = 2166136261n; for (const ch of String(seed)) h = BigInt.asUintN(63, (h ^ BigInt(ch.codePointAt(0))) * 16777619n); return (1000000000000000n + (h % 8000000000000000000n)).toString(); };
const normalizedVideoText = (input) => String(input || '').toLowerCase()
  .replace(/[\u0000-\u001f\s]+/gu, '')
  .replace(/[，。！？；：、“”‘’（）()【】［］《》<>「」,.!?;:'"`~·—–_\-]/gu, '');
const videoShingles = (input, size = 5) => {
  const result = new Set();
  for (let index = 0; index + size <= input.length; index += 1) result.add(input.slice(index, index + size));
  return result;
};
const videoSimilarity = (left, right) => {
  const a = normalizedVideoText(left), b = normalizedVideoText(right);
  if (!a || !b) return 0;
  if (a === b) return 1;
  if (Math.min(a.length, b.length) < 5) return 0;
  const sa = videoShingles(a), sb = videoShingles(b);
  let overlap = 0;
  for (const token of sa) if (sb.has(token)) overlap += 1;
  return overlap / Math.min(sa.size, sb.size);
};
const conn = await mysql.createConnection({host, port, user, password, database, charset:'utf8mb4', supportBigNumbers:true, bigNumberStrings:true, ssl:/^(1|true|yes)$/i.test(process.env.MYSQL_SSL || '') ? {} : undefined, connectTimeout:15000});
let insertedPosts=0, updatedPosts=0, insertedComments=0, updatedComments=0, duplicatePostsSkipped=0, duplicateCommentsSkipped=0;
let compatibilitySanitizedValues=0;
const subtitleBackups = [];
const outputRecorder=new ProductionOutputRecorder();
const subtitleBackupPath = path.join(path.dirname(statusFile), `subtitle-backup-${Date.now()}-${process.pid}.json`);
try {
  const [lockRows] = await conn.query("SELECT GET_LOCK('wechat_ods_import', 60) AS acquired");
  if (Number(lockRows[0]?.acquired) !== 1) throw new Error('MySQL import lock unavailable; no writes performed');
  try {await recoverCommittedOutputs(conn,outputRecorder.root);} catch {}
  await conn.beginTransaction();
  // Existing production ODS tables were originally created with a mixture of
  // utf8mb3 and utf8mb4 columns.  Keep the connection at utf8mb4, inspect the
  // real target schema, and remove only non-BMP code points for legacy columns
  // so one emoji/supplementary glyph cannot roll back an otherwise valid batch.
  // New installations use the utf8mb4 DDL shipped with this package.
  const [columnRows] = await conn.execute(
    "SELECT TABLE_NAME,COLUMN_NAME,COLLATION_NAME FROM information_schema.COLUMNS " +
    "WHERE TABLE_SCHEMA=? AND TABLE_NAME IN ('ods_social_media_post','ods_social_media_comment')",
    [database],
  );
  const legacyUtf8mb3Columns = new Map();
  for (const column of columnRows) {
    if (!String(column.COLLATION_NAME || '').toLowerCase().startsWith('utf8mb3_')) continue;
    if (!legacyUtf8mb3Columns.has(column.TABLE_NAME)) legacyUtf8mb3Columns.set(column.TABLE_NAME, new Set());
    legacyUtf8mb3Columns.get(column.TABLE_NAME).add(column.COLUMN_NAME);
  }
  const databaseValue = (table, row, field) => {
    const original = value(row, field);
    if (typeof original !== 'string' || !legacyUtf8mb3Columns.get(table)?.has(field)) return original;
    const sanitized = original.replace(/[\u{10000}-\u{10FFFF}]/gu, '');
    if (sanitized !== original) compatibilitySanitizedValues += 1;
    return sanitized === '' ? null : sanitized;
  };
  const upsert = async (table, fields, row, keySql, keyValues, fallbackKey) => {
    const selectFields = '*';
    const [existing] = await conn.execute(`SELECT ${selectFields} FROM \`${table}\` WHERE ${keySql} LIMIT 1 FOR UPDATE`, keyValues);
    let id = existing[0]?.id ? String(existing[0].id) : makeId(fallbackKey);
    const data = fields.filter((f) => f !== 'id');
    if (existing.length) {
      const oldSubtitle = existing[0]['文章视频内容'];
      const newSubtitle = value(row, '文章视频内容');
      if (table === 'ods_social_media_post' && oldSubtitle && newSubtitle && oldSubtitle !== newSubtitle) {
        subtitleBackups.push({id, url:row['文章链接'], project:row['项目'],
          oldSubtitle, newSubtitle, reason:'nonempty quality-gated subtitle replacement',
          backedUpAt:new Date().toISOString()});
        // Persist before the transaction update; rollback does not erase this
        // recoverable preimage. No schema change or deletion is required.
        atomicWriteFileSync(subtitleBackupPath, JSON.stringify(subtitleBackups, null, 2), 'utf8');
      }
      const incoming=Object.fromEntries(data.map(f=>[f,databaseValue(table,row,f)]));
      await conn.execute(
        `UPDATE \`${table}\` SET ${data.map((f) => `\`${f}\`=COALESCE(?,\`${f}\`)`).join(',')} WHERE id=?`,
        [...data.map((f) => incoming[f]), id],
      );
      if (meaningfulHint(existing[0],incoming)) {
        const [after]=await conn.execute(`SELECT * FROM \`${table}\` WHERE id=?`,[id]);
        outputRecorder.track(table,existing[0],after[0]);
      }
      return {id, updated:true};
    }
    // The table uses a caller-assigned BIGINT primary key. In the unlikely
    // event that a deterministic ID is already occupied by another natural
    // key, derive another stable candidate instead of failing the whole batch.
    for (let collision = 0; collision < 100; collision += 1) {
      const [occupied] = await conn.execute(`SELECT id FROM \`${table}\` WHERE id=? LIMIT 1 FOR UPDATE`, [id]);
      if (!occupied.length) break;
      id = makeId(`${fallbackKey}|collision:${collision + 1}`);
      if (collision === 99) throw new Error(`Unable to allocate a unique id for ${table}`);
    }
    const payload = {...row, id};
    await conn.execute(`INSERT INTO \`${table}\` (${fields.map((f) => `\`${f}\``).join(',')}) VALUES (${fields.map(() => '?').join(',')})`, fields.map((f) => databaseValue(table, payload, f)));
    const [after]=await conn.execute(`SELECT * FROM \`${table}\` WHERE id=?`,[id]);
    outputRecorder.track(table,null,after[0]);
    return {id, updated:false};
  };
  const videoPoolCache = new Map();
  const skippedPostUrls = new Set();
  const getVideoPool = async (platform, project) => {
    const cacheKey = `${platform}|${project ?? '<null>'}`;
    if (!videoPoolCache.has(cacheKey)) {
      const [rows] = await conn.execute(
        "SELECT `id`,`文章链接`,`文章视频内容` FROM `ods_social_media_post` " +
        "WHERE `平台`=? AND `项目` <=> ? AND NULLIF(TRIM(`文章视频内容`),'') IS NOT NULL FOR UPDATE",
        [platform, project],
      );
      videoPoolCache.set(cacheKey, rows.map((item) => ({
        id: String(item.id), url: item['文章链接'], content: item['文章视频内容'],
      })));
    }
    return videoPoolCache.get(cacheKey);
  };
  for (const row of posts) {
    if (/全国地产设计产品力监测|北京臻澐项目口碑(?:监测|采集)/u.test(String(row['文章视频内容'] || ''))) {
      row['文章视频内容'] = null; // COALESCE keeps the existing MySQL value intact.
    }
    // Normalize blanks exactly as INSERT/UPDATE does. Previously the lookup
    // used '' while storage converted it to NULL, breaking retry idempotency.
    const project = value(row, '项目'), platform = value(row, '平台') || '微信视频号';
    if (platform === '微信视频号' && value(row, '文章视频内容')) {
      const [sameLink] = await conn.execute(
        "SELECT `id` FROM `ods_social_media_post` WHERE `文章链接`=? AND `平台`=? AND `项目` <=> ? LIMIT 1 FOR UPDATE",
        [row['文章链接'], platform, project],
      );
      if (!sameLink.length) {
        const pool = await getVideoPool(platform, project);
        const duplicate = pool.find((item) => videoSimilarity(item.content, row['文章视频内容']) >= 0.8);
        if (duplicate) {
          duplicatePostsSkipped++;
          if (row['文章链接']) skippedPostUrls.add(row['文章链接']);
          continue;
        }
      }
    }
    const result = await upsert('ods_social_media_post', postFields, row, '`文章链接`=? AND `平台`=? AND `项目` <=> ?', [row['文章链接'], platform, project], `${platform}|${project}|${row['文章链接'] || row['文章id']}`);
    result.updated ? updatedPosts++ : insertedPosts++;
    if (platform === '微信视频号' && value(row, '文章视频内容')) {
      const pool = await getVideoPool(platform, project);
      const existing = pool.find((item) => item.url === row['文章链接']);
      if (existing) existing.content = row['文章视频内容'];
      else pool.push({id: result.id, url: row['文章链接'], content: row['文章视频内容']});
    }
  }
  for (const row of comments) {
    if (row['文章链接'] && skippedPostUrls.has(row['文章链接'])) {
      duplicateCommentsSkipped++;
      continue;
    }
    const project = value(row, '项目'), platform = value(row, '平台') || '微信视频号';
    const keySql = row['评论id'] ? '`评论id`=? AND `平台`=? AND `项目` <=> ?' : '`文章链接`=? AND `评论内容`=? AND `评论时间`=? AND `平台`=? AND `项目` <=> ?';
    const keyValues = row['评论id'] ? [row['评论id'], platform, project] : [row['文章链接'], row['评论内容'], row['评论时间'], platform, project];
    const result = await upsert('ods_social_media_comment', commentFields, row, keySql, keyValues, `${platform}|${project}|${row['文章id']}|${row['评论id'] || row['评论内容']}|${row['评论时间']}`);
    result.updated ? updatedComments++ : insertedComments++;
  }
  outputRecorder.prepare();
  outputRecorder.commitAttempted=true;
  await conn.commit();
  const outputTelemetry=await finishOutput(outputRecorder,conn);
  const status = {status:'success',host,database,posts:posts.length,comments:comments.length,insertedPosts,updatedPosts,duplicatePostsSkipped,insertedComments,updatedComments,duplicateCommentsSkipped,compatibilitySanitizedValues,subtitleBackupCount:subtitleBackups.length,subtitleBackupPath:subtitleBackups.length ? subtitleBackupPath : null,completedAt:new Date().toISOString(),outputTelemetry};
  atomicWriteFileSync(statusFile, JSON.stringify(status,null,2), 'utf8');
  console.log(JSON.stringify(status,null,2));
} catch (error) {
  await conn.rollback().catch(() => {});
  try {outputRecorder.abort();} catch {}
  const status = {status:'failed',host,database,error:String(error?.message || error),failedAt:new Date().toISOString()};
  atomicWriteFileSync(statusFile, JSON.stringify(status,null,2), 'utf8');
  console.error(JSON.stringify(status,null,2));
  process.exitCode = 2;
} finally {
  await conn.query("SELECT RELEASE_LOCK('wechat_ods_import')").catch(() => {});
  await conn.end();
}
