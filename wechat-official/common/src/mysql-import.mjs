import fs from 'node:fs';
import path from 'node:path';
import mysql from 'mysql2/promise';
import { articleIdentityKeys, canonicalWechatUrl, dedupePostsGlobal, relinkAndDedupeComments } from './wechat-dedupe.mjs';

const args = {};
for (let i = 2; i < process.argv.length; i += 1) {
  if (process.argv[i].startsWith('--')) {
    const key = process.argv[i].slice(2);
    const next = process.argv[i + 1];
    args[key] = !next || next.startsWith('--') ? true : process.argv[++i];
  }
}
const postsFile = path.resolve(String(args.posts || ''));
const commentsFile = args.comments && args.comments !== true ? path.resolve(String(args.comments)) : null;
const statusFile = path.resolve(String(args.status || path.join(path.dirname(postsFile), 'mysql_import_status.json')));
const host = process.env.MYSQL_HOST || 'mysql.example.com';
const port = Number(process.env.MYSQL_PORT || 3306);
const database = process.env.MYSQL_DATABASE || 'social';
const user = process.env.MYSQL_USER;
const password = process.env.MYSQL_PASSWORD;
const normalizationSelfTest = args['normalization-self-test'] === true;
if (!normalizationSelfTest && (!postsFile || !fs.existsSync(postsFile))) throw new Error(`文章文件不存在: ${postsFile}`);
if (!normalizationSelfTest && (!user || !password)) throw new Error('MYSQL_USER 和 MYSQL_PASSWORD 未设置，拒绝无凭据入库');
const read = (file) => fs.existsSync(file) ? fs.readFileSync(file, 'utf8').split(/\r?\n/).filter(Boolean).map(JSON.parse) : [];
const postFields = ['id','文章图片链接','文章图片信息','作者名字','文章标题','文章内容','文章标签','文章时间地点','文章点赞数','文章收藏数','文章评论数','文章链接','文章id','作者主页链接','文章视频链接','文章视频内容','关键词','作者id','作者粉丝数','作者点赞数','文章分享数','文章视频时长','平台','文章获取时间','文章标注','分类','清洗标注','项目','地点','内容类型','是否广告','广告关键词'];
const commentFields = ['id','评论id','评论用户链接','评论用户id','评论用户名字','评论内容','评论时间','评论IP','评论点赞数','评论回复数','文章链接','文章id','关键词','评论获取时间','平台','分类','项目','清洗标注'];
const value = (row, field) => row[field] === '' || row[field] === undefined ? null : row[field];
// The supplied production DDL mixes utf8mb3 and utf8mb4 columns. Titles,
// author names and labels can contain supplementary-plane emoji, and MySQL
// rejects those parameters before an otherwise-idempotent batch can commit.
// Preserve full Unicode in the declared utf8mb4 fields; remove only code
// points that the legacy utf8mb3 destination physically cannot represent.
const utf8mb4Fields = {
  ods_social_media_post: new Set(['文章内容', '文章链接', '项目']),
  ods_social_media_comment: new Set(['评论内容', '项目']),
};
let sanitizedUtf8mb3Values = 0;
const utf8mb3Safe = (input) => {
  if (typeof input !== 'string') return input;
  const output = Array.from(input).filter((character) => character.codePointAt(0) <= 0xffff).join('');
  if (output !== input) sanitizedUtf8mb3Values += 1;
  return output;
};
const dbValue = (table, row, field) => {
  const raw = value(row, field);
  if (raw === null || utf8mb4Fields[table]?.has(field)) return raw;
  return utf8mb3Safe(raw);
};
if (normalizationSelfTest) {
  const sample = {'文章标题':'项目😀发布', '文章内容':'正文😀保留'};
  const result = {
    title: dbValue('ods_social_media_post', sample, '文章标题'),
    content: dbValue('ods_social_media_post', sample, '文章内容'),
    sanitizedUtf8mb3Values,
  };
  console.log(JSON.stringify(result));
  if (result.title !== '项目发布' || result.content !== '正文😀保留' || result.sanitizedUtf8mb3Values !== 1) process.exit(9);
  process.exit(0);
}
const inputPosts = read(postsFile).map((row, inputIndex) => ({...row, __dedupeSource:`input:${inputIndex}`}));
const inputComments = commentsFile ? read(commentsFile) : [];
const makeId = (seed) => { let h = 2166136261n; for (const ch of String(seed)) h = BigInt.asUintN(63, (h ^ BigInt(ch.codePointAt(0))) * 16777619n); return (1000000000000000n + (h % 8000000000000000000n)).toString(); };
const conn = await mysql.createConnection({host, port, user, password, database, charset:'utf8mb4', supportBigNumbers:true, bigNumberStrings:true, dateStrings:true, ssl:/^(1|true|yes)$/i.test(process.env.MYSQL_SSL || '') ? {} : undefined, connectTimeout:15000});
let insertedPosts=0, updatedPosts=0, insertedComments=0, updatedComments=0;
try {
  await conn.query("SELECT GET_LOCK('wechat_ods_import', 60)");
  await conn.beginTransaction();
  const upsert = async (table, fields, row, keySql, keyValues, fallbackKey) => {
    const [existing] = await conn.execute(`SELECT id FROM \`${table}\` WHERE ${keySql} LIMIT 1 FOR UPDATE`, keyValues);
    let id = existing[0]?.id ? String(existing[0].id) : makeId(fallbackKey);
    const data = fields.filter((f) => f !== 'id');
    if (existing.length) {
      await conn.execute(`UPDATE \`${table}\` SET ${data.map((f) => `\`${f}\`=?`).join(',')} WHERE id=?`, [...data.map((f) => dbValue(table, row, f)), id]);
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
    await conn.execute(`INSERT INTO \`${table}\` (${fields.map((f) => `\`${f}\``).join(',')}) VALUES (${fields.map(() => '?').join(',')})`, fields.map((f) => dbValue(table, payload, f)));
    return {id, updated:false};
  };
  // Compare every incoming keyword batch with the already stored WeChat
  // corpus. This closes the gap where the same repost arrives from another
  // keyword, project or worker on a later run.
  const [databasePostsRaw] = await conn.query(`SELECT ${postFields.map((field) => `\`${field}\``).join(',')} FROM \`ods_social_media_post\` WHERE \`平台\`=?`, ['微信公众号']);
  const databasePosts = databasePostsRaw.map((row) => ({...row, id:String(row.id), __dedupeSource:`database:${row.id}`}));
  const databaseIds = new Set(databasePosts.map((row) => String(row.id)));
  const postDedupe = dedupePostsGlobal([...databasePosts, ...inputPosts]);
  const touchedSurvivors = new Set();
  for (const row of inputPosts) {
    const survivorIndex = articleIdentityKeys(row).map((key) => postDedupe.aliases.get(key)).find((value) => value !== undefined);
    if (survivorIndex !== undefined) touchedSurvivors.add(survivorIndex);
  }
  const posts = [...touchedSurvivors].map((index) => postDedupe.records[index]);
  const commentDedupe = relinkAndDedupeComments(inputComments, postDedupe);
  const comments = commentDedupe.records;
  const dedupeAuditFile = statusFile.replace(/\.json$/i, '_dedupe_audit.jsonl');
  const relevantAudit = postDedupe.audit.filter((item) => String(item.duplicateSource || '').startsWith('input:') || String(item.survivorSource || '').startsWith('input:'));
  fs.writeFileSync(dedupeAuditFile, relevantAudit.map((item) => JSON.stringify(item)).join('\n') + (relevantAudit.length ? '\n' : ''), 'utf8');

  for (const sourceRow of posts) {
    const row = Object.fromEntries(Object.entries(sourceRow).filter(([key]) => !key.startsWith('__dedupe')));
    const platform = dbValue('ods_social_media_post', row, '平台') || '微信公众号';
    const articleId = dbValue('ods_social_media_post', row, '文章id');
    const canonicalUrl = canonicalWechatUrl(row['文章链接']);
    let keySql, keyValues;
    if (row.id != null && databaseIds.has(String(row.id))) {
      keySql = '`id`=?'; keyValues = [String(row.id)];
    } else if (articleId) {
      keySql = '`文章id`=? AND `平台`=?'; keyValues = [articleId, platform];
    } else {
      keySql = '`文章链接`=? AND `平台`=?'; keyValues = [canonicalUrl || row['文章链接'], platform];
      if (canonicalUrl) row['文章链接'] = canonicalUrl;
    }
    const result = await upsert('ods_social_media_post', postFields, row, keySql, keyValues, `${platform}|${articleId || canonicalUrl || row['文章链接']}`);
    result.updated ? updatedPosts++ : insertedPosts++;
  }
  for (const row of comments) {
    const platform = dbValue('ods_social_media_comment', row, '平台') || '微信公众号';
    const keySql = row['评论id'] ? '`评论id`=? AND `平台`=?' : '`文章链接`=? AND `评论内容`=? AND `评论时间`=? AND `平台`=?';
    const keyValues = row['评论id'] ? [row['评论id'], platform] : [row['文章链接'], row['评论内容'], row['评论时间'], platform];
    const result = await upsert('ods_social_media_comment', commentFields, row, keySql, keyValues, `${platform}|${row['文章id'] || row['文章链接']}|${row['评论id'] || row['评论内容']}|${row['评论时间']}`);
    result.updated ? updatedComments++ : insertedComments++;
  }
  await conn.commit();
  const status = {status:'success',host,database,inputPosts:inputPosts.length,deduplicatedPosts:posts.length,inputComments:inputComments.length,deduplicatedComments:comments.length,insertedPosts,updatedPosts,insertedComments,updatedComments,dedupeAuditFile,sanitizedUtf8mb3Values,completedAt:new Date().toISOString()};
  fs.writeFileSync(statusFile, JSON.stringify(status,null,2), 'utf8');
  console.log(JSON.stringify(status,null,2));
} catch (error) {
  await conn.rollback().catch(() => {});
  const status = {status:'failed',host,database,error:String(error?.message || error),failedAt:new Date().toISOString()};
  fs.writeFileSync(statusFile, JSON.stringify(status,null,2), 'utf8');
  console.error(JSON.stringify(status,null,2));
  process.exitCode = 2;
} finally {
  await conn.query("SELECT RELEASE_LOCK('wechat_ods_import')").catch(() => {});
  await conn.end();
}
