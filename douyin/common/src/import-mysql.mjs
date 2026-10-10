import fs from "node:fs/promises";
import path from "node:path";
import mysql from "mysql2/promise";
import { POST_FIELDS, COMMENT_FIELDS, canonicalDouyinPostUrl } from "./schema.mjs";
import { pathToFileURL } from "node:url";
import { assertLocalLease, withImportLease } from "./lease-guard.mjs";
import {normaliseDouyinPostFields,normaliseDouyinCommentFields} from './douyin-data.mjs';

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
    host: String(process.env.MYSQL_HOST || "mysql.example.com"),
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
  return rows.map((row) => ({ ...row, 文章链接: canonicalDouyinPostUrl(row["文章id"], row["文章链接"]) }));
}
export function updateFieldAssignment(table,field){
  if(table==='ods_social_media_post'&&field==='文章视频内容')return `\`${field}\`=COALESCE(?,\`${field}\`)`;
  return table==='ods_social_media_post' && ['作者粉丝数','作者点赞数'].includes(field)
    ? `\`${field}\`=COALESCE(\`${field}\`,?)` : `\`${field}\`=?`;
}
const BUSINESS_FIELDS=Object.freeze({ods_social_media_post:['文章id','平台','项目'],ods_social_media_comment:['评论id','文章id','平台','项目']});
export function businessRowKey(table,row){
 const fields=BUSINESS_FIELDS[table];if(!fields)throw new Error('不支持的目标数据表');
 return JSON.stringify(fields.map(field=>String(row[field]??'')));
}
export async function existingBusinessRows(connection,table,rows){
 const fields=BUSINESS_FIELDS[table];if(!fields)throw new Error('不支持的目标数据表');
 const groups=new Map(),found=new Map();
 for(const row of rows){const key=JSON.stringify([row.平台,row.项目]);if(!groups.has(key))groups.set(key,{platform:row.平台,project:row.项目,ids:new Set()});groups.get(key).ids.add(String(row[fields[0]]));}
 // The cross-platform import mutex already serializes base-row writers.
 // Scan once per bounded ID batch, not once per comment; resolve IDs using a
 // plain read and update by primary key. Do not acquire broad predicate locks
 // that conflict with independent ASR single-column backfills.
 for(const group of groups.values()){
  const ids=[...group.ids];for(let offset=0;offset<ids.length;offset+=250){
   await assertLocalLease();const batch=ids.slice(offset,offset+250);
   const[existing]=await connection.execute(`SELECT \`id\`,${fields.map(f=>`\`${f}\``).join(',')} FROM \`${table}\` WHERE \`平台\`=? AND \`项目\`=? AND \`${fields[0]}\` IN (${batch.map(()=>'?').join(',')})`,[group.platform,group.project,...batch]);
   for(const row of existing){const key=businessRowKey(table,row);if(found.has(key))throw new Error('MYSQL_DUPLICATE_BUSINESS_KEY：拒绝任意覆盖重复业务行');found.set(key,row);}
  }
 }
 return found;
}
async function upsertRows(connection, table, fields, rows) {
  if(!rows.length)return {inserted:0,updated:0};
  const existingRows=await existingBusinessRows(connection,table,rows);
  let id = await nextId(connection, table), inserted = 0, updated = 0;
  const dataFields = fields.filter((f) => f !== "id");
  const insertSql = `INSERT INTO \`${table}\` (${fields.map((f) => `\`${f}\``).join(",")}) VALUES (${fields.map(() => "?").join(",")})`;
  // Phase-one exports (including old checkpoints and ASR callbacks) must never
  // overwrite a phase-two author snapshot, even with stale non-null values.
  const updateSql = `UPDATE \`${table}\` SET ${dataFields.map((f) => updateFieldAssignment(table,f)).join(",")} WHERE \`id\`=?`;
  for (const row of rows) {
    await assertLocalLease();
    const key=businessRowKey(table,row),existing=existingRows.get(key);
    if (existing) {
      row.id = String(existing.id);
      await connection.execute(updateSql, [...dataFields.map((f) => row[f]), row.id]);
      updated += 1;
    } else {
      id += 1n; row.id = id.toString();
      await connection.execute(insertSql, fields.map((f) => row[f]));
      existingRows.set(key,{...row,id:row.id});
      inserted += 1;
    }
  }
  return { inserted, updated };
}
export async function retryMysqlDeadlock(operation,{attempts=3,delayMs=300}={}){
  for(let attempt=1;;attempt++){
    await assertLocalLease();
    try{return await operation();}
    catch(error){
      if(attempt>=attempts||!(error.code==='ER_LOCK_DEADLOCK'||Number(error.errno)===1213))throw error;
      console.warn(`[数据库事务重试] 已回滚死锁事务；第${attempt}/${attempts}次，不重复访问平台`);
      await new Promise(resolve=>setTimeout(resolve,delayMs*attempt));
    }
  }
}
export async function acquireImportLock(connection,{lockTimeoutSeconds=10,maxLockWaitMs=600000,shouldStop=null,verifyLease=async()=>{}}={}){
  const started=Date.now(),deadline=started+Math.max(0,Number(maxLockWaitMs)||0);
  let warnedAt=0;
  do{
    if(await shouldStop?.())throw new Error('STOP_REQUESTED：等待入库锁时安全停止，数据保留在本地');
    await verifyLease();
    const seconds=Math.max(0,Math.min(10,Number(lockTimeoutSeconds)||0,Math.ceil((deadline-Date.now())/1000)));
    const[rows]=await connection.query("SELECT GET_LOCK('social_xhs_distributed_import', ?) AS acquired",[seconds]);
    if(Number(rows[0]?.acquired)===1)return;
    if(rows[0]?.acquired==null)throw new Error('MYSQL_IMPORT_LOCK_ERROR：共享入库锁不可用');
    if(Date.now()-warnedAt>=60000){console.log(`[入库锁等待] 其他批次正在入库，已等待${Math.round((Date.now()-started)/1000)}秒；未重新访问平台`);warnedAt=Date.now();}
    if(seconds===0)break;
  }while(Date.now()<deadline);
  throw Object.assign(new Error('MYSQL_IMPORT_LOCK_WAIT_TIMEOUT：共享入库锁限时等待结束，数据保留在本地'),{code:'MYSQL_IMPORT_LOCK_WAIT_TIMEOUT'});
}
export async function importRows({ posts = [], comments = [], verify = false, lockTimeoutSeconds = 10,maxLockWaitMs=600000,shouldStop=null } = {}) {
  // 最后一道入库防线：无论数据来自实时采集、旧断点还是人工JSON，分类都必须写成SQL NULL。
  posts = repairArticleLinks(forceNullCategory(posts.map(normaliseDouyinPostFields)));
  comments = repairArticleLinks(forceNullCategory(comments.map(normaliseDouyinCommentFields)));
  return retryMysqlDeadlock(()=>withImportLease(async verifyLease => {
  const connection = await mysql.createConnection(mysqlConnectionOptions());
  let importLockAcquired = false;
  try {
    await acquireImportLock(connection,{lockTimeoutSeconds,maxLockWaitMs,shouldStop,verifyLease});
    importLockAcquired = true;
    if(await shouldStop?.())throw new Error('STOP_REQUESTED：已取得入库锁但请求安全停止，数据保留在本地');
    await verifyLease();
    if (verify) {
      await verifyTable(connection, "ods_social_media_post", POST_FIELDS);
      if (comments.length) await verifyTable(connection, "ods_social_media_comment", COMMENT_FIELDS);
    }
    const postCompatibility = await makeRowsCompatibleWithTable(connection, "ods_social_media_post", posts);
    const commentCompatibility = await makeRowsCompatibleWithTable(connection, "ods_social_media_comment", comments);
    posts = postCompatibility.rows;
    comments = commentCompatibility.rows;
    const compatibility = { posts: postCompatibility.stats, comments: commentCompatibility.stats };
    const changedRows = compatibility.posts.changedRows + compatibility.comments.changedRows;
    if (changedRows) {
      const fields = [...new Set([...compatibility.posts.fields, ...compatibility.comments.fields])].sort();
      console.warn(`[字符集兼容] ${changedRows}行包含utf8mb3无法直接保存的字符；已最小化转换，字段=${fields.join(",")}`);
    }
    await connection.beginTransaction();
    const postResult = await upsertRows(connection, "ods_social_media_post", POST_FIELDS, posts);
    const commentResult = await upsertRows(connection, "ods_social_media_comment", COMMENT_FIELDS, comments);
    await verifyLease();
    await connection.commit();
    return { postResult, commentResult, charsetCompatibility: compatibility };
  } catch (error) {
    await connection.rollback().catch(() => {});
    throw error;
  } finally {
    if (importLockAcquired) await connection.query("SELECT RELEASE_LOCK('social_xhs_distributed_import')").catch(() => {});
    await connection.end();
  }
  }));
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
    const { postResult, commentResult } = await importRows({ posts, comments, verify: true });
    await fs.writeFile(path.join(inputDir, "mysql_import_status.json"), JSON.stringify({ status: "success", postResult, commentResult, reviewed: false, autoApproved: true, committedAt: new Date().toISOString() }, null, 2));
    console.log(JSON.stringify({ committed: true, postResult, commentResult }, null, 2));
  }
}

