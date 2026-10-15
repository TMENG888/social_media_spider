import fs from "node:fs/promises";
import path from "node:path";
import mysql from "mysql2/promise";
import { POST_FIELDS, COMMENT_FIELDS, canonicalXhsNoteUrl } from "./schema.mjs";
import { pathToFileURL } from "node:url";
import { assertLocalLease, withImportLease } from "./lease-guard.mjs";
import { createImportBatches, retryImportBatch, IMPORT_PENDING_EXIT_CODE } from "./import-recovery.mjs";
import { writeJsonAtomic } from "./checkpoint.mjs";
import {recordCommittedPosts,subtitleWriteCount} from './monitor-telemetry.mjs';

function argsOf(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i += 1) {
    if (!argv[i].startsWith("--")) continue;
    const key = argv[i].slice(2), next = argv[i + 1];
    out[key] = !next || next.startsWith("--") ? true : next;
    if (out[key] !== true) i += 1;
  }
  return out;
}

export function mysqlConnectionOptions() {
  const user = process.env.MYSQL_USER, password = process.env.MYSQL_PASSWORD;
  if (!user || !password) throw new Error("请通过当前进程环境变量 MYSQL_USER 和 MYSQL_PASSWORD 提供数据库凭据，不要写入配置文件");
  return {
    host: String(process.env.MYSQL_HOST || "127.0.0.1"),
    port: Number(process.env.MYSQL_PORT || 3306),
    database: String(process.env.MYSQL_DATABASE || "social"),
    user, password, charset: "utf8mb4", supportBigNumbers: true, bigNumberStrings: true, connectTimeout: 15000
  };
}

export async function verifyTable(connection, table, fields) {
  if (!["ods_social_media_post", "ods_social_media_comment"].includes(table)) throw new Error("不支持的目标数据表");
  const [cols] = await connection.query(`SHOW FULL COLUMNS FROM \`${table}\``);
  const actual = cols.map((c) => c.Field);
  const missing = fields.filter(field => !actual.includes(field));
  const extras = cols.filter(column => !fields.includes(column.Field));
  // INSERT/UPDATE explicitly name every supplied column. Physical order and
  // optional extra columns are irrelevant; required extras cannot be omitted.
  const requiredExtras = extras.filter(column => column.Null !== "YES" && column.Default == null
    && !/auto_increment|(?:VIRTUAL|STORED) GENERATED/i.test(String(column.Extra || "")));
  const generatedFields = cols.filter(column => fields.includes(column.Field)
    && /(?:VIRTUAL|STORED) GENERATED/i.test(String(column.Extra || ""))).map(column => column.Field);
  if (missing.length || requiredExtras.length || generatedFields.length) {
    const details = [missing.length ? `缺少必需字段：${missing.join("、")}` : null,
      requiredExtras.length ? `额外必填字段无默认值：${requiredExtras.map(column => column.Field).join("、")}` : null,
      generatedFields.length ? `目标字段为不可直接写入的生成列：${generatedFields.join("、")}` : null].filter(Boolean);
    throw Object.assign(new Error(`${table}数据库字段不兼容；${details.join("；")}`), { code: "MYSQL_SCHEMA_INCOMPATIBLE", table, missingFields: missing });
  }
  return { columns: cols, columnCount: actual.length, requiredFields: fields.length,
    extraFields: extras.map(column => column.Field), orderMatches: JSON.stringify(actual) === JSON.stringify(fields) };
}
const isUtf8mb3Collation = (value) => /^(?:utf8mb3|utf8)_/i.test(String(value || ""));
export function utf8mb3CompatibleText(value) {
  if (typeof value !== "string" || !value) return value;
  let output = "";
  for (const character of value) {
    const codePoint = character.codePointAt(0);
    if (codePoint <= 0xffff && !(codePoint >= 0xd800 && codePoint <= 0xdfff)) {
      output += character;
      continue;
    }
    // Compatibility characters such as mathematical bold digits can be
    // represented faithfully enough in utf8mb3 after per-character NFKC
    // normalization (for example, 𝟏𝟓 -> 15). Emoji and other remaining
    // supplementary-plane characters cannot be stored and are removed only
    // from columns whose live database collation is still utf8mb3.
    const compatible = character.normalize("NFKC");
    for (const normalized of compatible) {
      const normalizedCodePoint = normalized.codePointAt(0);
      if (normalizedCodePoint <= 0xffff && !(normalizedCodePoint >= 0xd800 && normalizedCodePoint <= 0xdfff)) output += normalized;
    }
  }
  return output;
}
async function makeRowsCompatibleWithTable(connection, table, rows) {
  if (!rows.length) return { rows, stats: { changedRows: 0, changedValues: 0, fields: [] } };
  const [columns] = await connection.query(`SHOW FULL COLUMNS FROM \`${table}\``);
  const utf8mb3Fields = new Set(columns.filter((column) => isUtf8mb3Collation(column.Collation)).map((column) => column.Field));
  const changedFields = new Set();
  let changedRows = 0, changedValues = 0;
  const compatibleRows = rows.map((row) => {
    let rowChanged = false;
    const compatible = { ...row };
    for (const field of utf8mb3Fields) {
      if (typeof compatible[field] !== "string") continue;
      const value = utf8mb3CompatibleText(compatible[field]);
      if (value === compatible[field]) continue;
      compatible[field] = value;
      rowChanged = true;
      changedValues += 1;
      changedFields.add(field);
    }
    if (rowChanged) changedRows += 1;
    return compatible;
  });
  return { rows: compatibleRows, stats: { changedRows, changedValues, fields: [...changedFields].sort() } };
}
async function nextId(connection, table) {
  const [rows] = await connection.query(`SELECT \`id\` FROM \`${table}\` ORDER BY \`id\` DESC LIMIT 1 FOR UPDATE`);
  return BigInt(rows[0]?.id || 0);
}
export function forceNullCategory(rows = []) {
  return rows.map((row) => ({ ...row, 分类: null }));
}
export function repairArticleLinks(rows = []) {
  return rows.map((row) => ({ ...row, 文章链接: canonicalXhsNoteUrl(row["文章id"], row["文章链接"]) }));
}
export function updateFieldAssignment(table,field){
  return table==='ods_social_media_post' && ['作者粉丝数','作者点赞数'].includes(field)
    ? `\`${field}\`=COALESCE(\`${field}\`,?)` : `\`${field}\`=?`;
}
export function importRowMatches(table,fields,actual,expected){
  return fields.filter(field=>field!=='id').every(field=>{
    const current=actual[field],incoming=expected[field];
    // Match the existing phase-one COALESCE write policy exactly.
    if(table==='ods_social_media_post'&&['作者粉丝数','作者点赞数'].includes(field)&&current!=null)return true;
    if(current instanceof Date){const date=new Date(incoming);return incoming!=null&&Number.isFinite(date.getTime())&&current.getTime()===date.getTime();}
    if(current==null||incoming==null)return current===incoming;
    if(typeof incoming==='boolean'&&['0','1'].includes(String(current)))return Number(incoming)===Number(current);
    return String(current)===String(incoming);
  });
}
export async function rowsNeedingImport(connection,table,fields,rows,uniqueWhere){
  if(!['ods_social_media_post','ods_social_media_comment'].includes(table))throw new Error('Unsupported import table');
  const pending=[];
  for(const row of rows){
    const {sql,values}=uniqueWhere(row);
    const [actual]=await connection.execute(`SELECT ${fields.map(f=>`\`${f}\``).join(',')} FROM \`${table}\` WHERE ${sql} LIMIT 2`,values);
    if(actual.length!==1||!importRowMatches(table,fields,actual[0],row))pending.push(row);
  }
  return pending;
}
async function upsertRows(connection, table, fields, rows, uniqueWhere) {
  if (!rows.length) return { inserted: 0, updated: 0 };
  let id = await nextId(connection, table), inserted = 0, updated = 0, videoContentWrites = 0;
  const dataFields = fields.filter((f) => f !== "id");
  const insertSql = `INSERT INTO \`${table}\` (${fields.map((f) => `\`${f}\``).join(",")}) VALUES (${fields.map(() => "?").join(",")})`;
  // Phase-one exports (including old checkpoints and ASR callbacks) must never
  // overwrite a phase-two author snapshot, even with stale non-null values.
  const updateSql = `UPDATE \`${table}\` SET ${dataFields.map((f) => updateFieldAssignment(table,f)).join(",")} WHERE \`id\`=?`;
  for (const row of rows) {
    await assertLocalLease();
    const { sql, values } = uniqueWhere(row);
    const [existing] = await connection.execute(`SELECT \`id\`${table==='ods_social_media_post'?',`文章视频内容`':''} FROM \`${table}\` WHERE ${sql} LIMIT 1 FOR UPDATE`, values);
    if (existing.length) {
      row.id = String(existing[0].id);
      await connection.execute(updateSql, [...dataFields.map((f) => row[f]), row.id]);
      if(table==='ods_social_media_post')videoContentWrites+=subtitleWriteCount(existing[0]['文章视频内容'],row['文章视频内容']);
      updated += 1;
    } else {
      id += 1n; row.id = id.toString();
      await connection.execute(insertSql, fields.map((f) => row[f]));
      if(table==='ods_social_media_post')videoContentWrites+=subtitleWriteCount(null,row['文章视频内容']);
      inserted += 1;
    }
  }
  return { inserted, updated, videoContentWrites };
}
export async function importRows({ posts = [], comments = [], verify = false, lockTimeoutSeconds = 15,
  batchRows = 10, maxAttempts = 4, retryDelayMs = 2000, onProgress = async () => {} } = {}) {
  if (!Number.isFinite(lockTimeoutSeconds) || lockTimeoutSeconds < 0 || lockTimeoutSeconds > 120) throw new Error('入库锁等待时间必须在0至120秒之间');
  // 最后一道入库防线：无论数据来自实时采集、旧断点还是人工JSON，分类都必须写成SQL NULL。
  posts = repairArticleLinks(forceNullCategory(posts));
  comments = repairArticleLinks(forceNullCategory(comments));
  return withImportLease(async verifyLease => {
  // Read schema/charset before taking the shared write lock.
  let compatibility;
  await retryImportBatch(async () => {
  const preparation = await mysql.createConnection(mysqlConnectionOptions());
  try {
    await verifyLease();
    if (verify) {
      await verifyTable(preparation, "ods_social_media_post", POST_FIELDS);
      if (comments.length) await verifyTable(preparation, "ods_social_media_comment", COMMENT_FIELDS);
    }
    const postCompatibility = await makeRowsCompatibleWithTable(preparation, "ods_social_media_post", posts);
    const commentCompatibility = await makeRowsCompatibleWithTable(preparation, "ods_social_media_comment", comments);
    posts = postCompatibility.rows;
    comments = commentCompatibility.rows;
    compatibility = { posts: postCompatibility.stats, comments: commentCompatibility.stats };
    const changedRows = compatibility.posts.changedRows + compatibility.comments.changedRows;
    if (changedRows) {
      const fields = [...new Set([...compatibility.posts.fields, ...compatibility.comments.fields])].sort();
      console.warn(`[字符集兼容] ${changedRows}行包含utf8mb3无法直接保存的字符；已最小化转换，字段=${fields.join(",")}`);
    }
  } finally { await preparation.end().catch(() => {}); }
  }, { maxAttempts, retryDelayMs, verifyLease,
    onRetry: info => console.warn(`[入库兜底] 数据库预检暂时失败（${info.code}）；稍后重连（${info.attempt}/${info.maxAttempts}）`) });
  const batches = createImportBatches(posts, comments, batchRows);
  const progress = { postResult: { inserted: 0, updated: 0, verifiedUnchanged: 0 }, commentResult: { inserted: 0, updated: 0, verifiedUnchanged: 0 },
    committedBatches: 0, totalBatches: batches.length, charsetCompatibility: compatibility };
  try {
    for (const [index, batch] of batches.entries()) {
      const result = await retryImportBatch(async () => {
        const connection = await mysql.createConnection(mysqlConnectionOptions());
        let acquired = false, transaction = false;
        try {
          // A failed tail must not wait behind the shared write lock merely
          // to rewrite earlier committed batches. Verify all effective fields
          // read-only first; only genuine differences enter the write path.
          const postChanges=await rowsNeedingImport(connection,'ods_social_media_post',POST_FIELDS,batch.posts,row=>({sql:'`文章id`=? AND `平台`=? AND `项目`=?',values:[row.文章id,row.平台,row.项目]}));
          const commentChanges=await rowsNeedingImport(connection,'ods_social_media_comment',COMMENT_FIELDS,batch.comments,row=>({sql:'`评论id`=? AND `文章id`=? AND `平台`=? AND `项目`=?',values:[row.评论id,row.文章id,row.平台,row.项目]}));
          await verifyLease();
          if(!postChanges.length&&!commentChanges.length)return {
            postResult:{inserted:0,updated:0,videoContentWrites:0,verifiedUnchanged:batch.posts.length},
            commentResult:{inserted:0,updated:0,verifiedUnchanged:batch.comments.length}};
          const [lock] = await connection.query("SELECT GET_LOCK('social_xhs_distributed_import', ?) AS acquired", [lockTimeoutSeconds]);
          if (Number(lock[0]?.acquired) !== 1) throw Object.assign(new Error('等待小红书分布式入库锁超时，请稍后重试'), { code: 'MYSQL_IMPORT_LOCK_TIMEOUT' });
          acquired = true;
          await verifyLease();
          await connection.query('SET SESSION innodb_lock_wait_timeout=15');
          await connection.beginTransaction(); transaction = true;
          const postResult = await upsertRows(connection, "ods_social_media_post", POST_FIELDS, postChanges, row => ({ sql: "`文章id`=? AND `平台`=? AND `项目`=?", values: [row["文章id"], row["平台"], row["项目"]] }));
          const commentResult = await upsertRows(connection, "ods_social_media_comment", COMMENT_FIELDS, commentChanges, row => ({ sql: "`评论id`=? AND `文章id`=? AND `平台`=? AND `项目`=?", values: [row["评论id"], row["文章id"], row["平台"], row["项目"]] }));
          postResult.verifiedUnchanged=batch.posts.length-postChanges.length;
          commentResult.verifiedUnchanged=batch.comments.length-commentChanges.length;
          await verifyLease();
          await connection.commit(); transaction = false;
          await recordCommittedPosts(connection,postChanges,postResult,new Date().toISOString());
          return { postResult, commentResult };
        } catch (error) {
          if (transaction) await connection.rollback().catch(() => {});
          throw error;
        } finally {
          if (acquired) await connection.query("SELECT RELEASE_LOCK('social_xhs_distributed_import')").catch(() => {});
          // Once committed, close errors must not turn successful data into a failed batch.
          await connection.end().catch(() => {});
        }
      }, { maxAttempts, retryDelayMs, verifyLease,
        onRetry: info => console.warn(`[入库兜底] 第${index + 1}/${batches.length}批，${info.code}；已释放连接，${Math.ceil(info.delayMs / 1000)}秒后重试（${info.attempt}/${info.maxAttempts}）`) });
      for (const kind of ['postResult', 'commentResult']) for (const count of ['inserted', 'updated','verifiedUnchanged']) progress[kind][count] += result[kind][count]||0;
      progress.committedBatches++;
      await onProgress({ ...progress, postResult: { ...progress.postResult }, commentResult: { ...progress.commentResult } });
      if (index + 1 < batches.length) {
        await new Promise(resolve => setTimeout(resolve, 250));
        await verifyLease();
      }
    }
    return progress;
  } catch (error) { error.importProgress = progress; throw error; }
  });
}

const isMain = process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url;
if (isMain) {
  const cli = argsOf(process.argv);
  const inputDir = path.resolve(String(cli["input-dir"] || "runs/latest"));
  const commit = cli.commit === true || cli.commit === "true";
  const autoApproved = cli["auto-approved"] === true || cli["auto-approved"] === "true";

  async function load(name, fields) {
    const file = path.join(inputDir, name);
    const source = await fs.readFile(file, "utf8");
    const rows = source.split(/\r?\n/).filter(Boolean).map((line, index) => {
      const row = JSON.parse(line);
      if (JSON.stringify(Object.keys(row)) !== JSON.stringify(fields)) throw new Error(`${name} 第${index + 1}行字段或顺序不匹配`);
      return row;
    });
    return rows;
  }
  const posts = await load("ods_social_media_post.jsonl", POST_FIELDS);
  let comments = [];
  try { comments = await load("ods_social_media_comment.jsonl", COMMENT_FIELDS); }
  catch (error) { if (error.code !== "ENOENT") throw error; }
  for (const [i, row] of posts.entries()) if (!row["文章id"] || !row["文章链接"] || !row["项目"]) throw new Error(`文章第${i + 1}行缺少文章id、链接或项目`);
  for (const [i, row] of comments.entries()) {
    if (!row["评论id"] || !row["文章id"] || !row["评论内容"]) throw new Error(`评论第${i + 1}行缺少关键字段`);
    if (row["评论id"] === row["评论用户id"]) throw new Error(`评论第${i + 1}行评论ID疑似误取成用户ID`);
  }
  if (!commit) {
    console.log(JSON.stringify({ valid: true, connected: false, committed: false, posts: posts.length, commentThreads: comments.length, message: "本地结构校验通过；增加 --commit --auto-approved 后自动入库" }, null, 2));
    process.exit(0);
  }
  if (!autoApproved) throw new Error("自动入库需要显式增加 --auto-approved");
  {
    const statusPath = path.join(inputDir, "mysql_import_status.json");
    const baseStatus = { posts: posts.length, comments: comments.length, autoApproved: true, reviewed: false };
    await writeJsonAtomic(statusPath, { ...baseStatus, status: 'importing', startedAt: new Date().toISOString() });
    try {
      const result = await importRows({ posts, comments, verify: true,
        onProgress: progress => writeJsonAtomic(statusPath, { ...baseStatus, ...progress, status: 'importing', updatedAt: new Date().toISOString() }) });
      await writeJsonAtomic(statusPath, { ...baseStatus, ...result, status: "success", committedAt: new Date().toISOString() });
      console.log(JSON.stringify({ committed: true, ...result }, null, 2));
    } catch (error) {
      const pending = error.code === 'IMPORT_RETRY_PENDING';
      await writeJsonAtomic(statusPath, { ...baseStatus, ...error.importProgress, status: pending ? 'pending' : 'failed',
        errorCode: error.code || 'MYSQL_IMPORT_ERROR', lastErrorCode: error.lastErrorCode || null,
        error: error.message, updatedAt: new Date().toISOString() });
      if (!pending) throw error;
      console.warn('[入库待补] 本地数据及分批进度已保存；下次领取该任务先恢复入库，不标为完成。');
      process.exitCode = IMPORT_PENDING_EXIT_CODE;
    }
  }
}
