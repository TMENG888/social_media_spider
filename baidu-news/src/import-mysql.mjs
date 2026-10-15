import fs from "node:fs/promises";
import path from "node:path";
import readline from "node:readline/promises";
import process from "node:process";
import mysql from "mysql2/promise";
import { ODS_FIELDS, applyNumericDefaults, legacyStableBigInt } from "./schema.mjs";
import { ArticleDeduper } from "./dedupe.mjs";
import { normalizeSingleKeyword, preferExistingKeyword } from "./keyword-attribution.mjs";

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    if (!argv[i].startsWith("--")) continue;
    const key = argv[i].slice(2);
    const value = argv[i + 1];
    args[key] = !value || value.startsWith("--") ? true : value;
    if (args[key] !== true) i += 1;
  }
  return args;
}

async function askText(prompt) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  try { return (await rl.question(prompt)).trim(); }
  finally { rl.close(); }
}

async function askSecret(prompt) {
  if (!process.stdin.isTTY) throw new Error("非交互终端必须通过 MYSQL_PASSWORD 环境变量提供密码");
  process.stdout.write(prompt);
  process.stdin.setRawMode(true);
  process.stdin.resume();
  process.stdin.setEncoding("utf8");
  let secret = "";
  return new Promise((resolve, reject) => {
    const finish = () => {
      process.stdin.setRawMode(false);
      process.stdin.pause();
      process.stdin.removeListener("data", onData);
      process.stdout.write("\n");
      resolve(secret);
    };
    const onData = (char) => {
      if (char === "\r" || char === "\n") return finish();
      if (char === "\u0003") {
        process.stdin.setRawMode(false);
        process.stdin.removeListener("data", onData);
        reject(new Error("用户取消输入"));
        return;
      }
      if (char === "\u007f" || char === "\b") { secret = secret.slice(0, -1); return; }
      secret += char;
    };
    process.stdin.on("data", onData);
  });
}

const cli = parseArgs(process.argv);
const host = String(cli.host || process.env.MYSQL_HOST || "127.0.0.1");
const port = Number(cli.port || process.env.MYSQL_PORT || 3306);
const database = String(cli.database || process.env.MYSQL_DATABASE || "social");
const table = String(cli.table || process.env.MYSQL_TABLE || "ods_social_media_post");
if (!/^[A-Za-z0-9_]+$/.test(database) || !/^[A-Za-z0-9_]+$/.test(table)) throw new Error("数据库名或表名包含不安全字符");
const inputFile = path.resolve(String(cli.input || "batch-data/combined_ods_social_media_post.jsonl"));
const LEGACY_HASH_ID_MIN = 1000000000000000n;
const shanghaiYear = Number(new Intl.DateTimeFormat("en", { timeZone: "Asia/Shanghai", year: "numeric" }).format(new Date()));
const dedupeYear = Number(cli["dedupe-year"] || shanghaiYear);
const contentSimilarityThreshold = Number(cli["content-similarity-threshold"] || 0.5);
if (!Number.isInteger(dedupeYear) || dedupeYear < 2000 || dedupeYear > 2100) throw new Error("去重年份无效");
if (!(contentSimilarityThreshold > 0 && contentSimilarityThreshold <= 1)) throw new Error("正文相似度阈值必须在0到1之间");

const source = await fs.readFile(inputFile, "utf8");
const records = source.split(/\r?\n/).filter(Boolean).map((line, index) => {
  const row = JSON.parse(line);
  const keys = Object.keys(row);
  if (keys.length !== ODS_FIELDS.length || keys.some((key, i) => key !== ODS_FIELDS[i])) {
    throw new Error(`输入第 ${index + 1} 行字段或顺序不符合 ODS_FIELDS`);
  }
  return applyNumericDefaults(row);
});
if (!records.length) throw new Error("输入文件没有可入库记录");
if (cli["validate-only"] === true || cli["validate-only"] === "true") {
  console.log(JSON.stringify({ inputFile, records: records.length, fields: ODS_FIELDS.length, valid: true, connected: false }, null, 2));
  process.exit(0);
}

const user = String(process.env.MYSQL_USER || await askText("MySQL 用户名："));
const password = String(process.env.MYSQL_PASSWORD || await askSecret("MySQL 密码（不会显示或写入磁盘）："));
if (!user || !password) throw new Error("用户名和密码不能为空");

const connection = await mysql.createConnection({
  host, port, user, password, database,
  charset: "utf8mb4",
  supportBigNumbers: true,
  bigNumberStrings: true,
  ssl: /^(1|true|yes)$/i.test(process.env.MYSQL_SSL || "") ? {} : undefined,
  connectTimeout: 15000
});

try {
  const [columns] = await connection.query(`SHOW COLUMNS FROM \`${table}\``);
  const actualFields = columns.map((column) => column.Field);
  if (JSON.stringify(actualFields) !== JSON.stringify(ODS_FIELDS)) {
    throw new Error(`数据库字段不匹配。期望：${ODS_FIELDS.join(",")}；实际：${actualFields.join(",")}`);
  }
  await connection.beginTransaction();
  const [lastRows] = await connection.execute(`SELECT \`id\` FROM \`${table}\` WHERE \`id\` < ? ORDER BY \`id\` DESC LIMIT 1 FOR UPDATE`, [LEGACY_HASH_ID_MIN.toString()]);
  let nextId = BigInt(lastRows[0]?.id || 0);
  const yearStart = `${dedupeYear}-01-01 00:00:00`;
  const nextYearStart = `${dedupeYear + 1}-01-01 00:00:00`;
  const [yearRows] = await connection.execute(
    `SELECT \`id\`, \`文章标题\`, \`文章内容\`, \`文章链接\`, \`文章id\`, \`平台\`, \`项目\` FROM \`${table}\` WHERE \`文章时间地点\` >= ? AND \`文章时间地点\` < ?`,
    [yearStart, nextYearStart]
  );
  const dedupers = new Map();
  const getDeduper = (projectName) => {
    const key = String(projectName || "");
    if (!dedupers.has(key)) {
      const scopedRows = yearRows.filter((row) => String(row["项目"] || "") === key).map((row) => ({
        id: String(row.id), title: row["文章标题"], content: row["文章内容"], url: row["文章链接"], articleId: row["文章id"], platform: row["平台"], source: "database"
      }));
      dedupers.set(key, new ArticleDeduper(scopedRows, { threshold: contentSimilarityThreshold, gramSize: 4, minimumContentLength: 100 }));
    }
    return dedupers.get(key);
  };
  const dataFields = ODS_FIELDS.filter((field) => field !== "id");
  const insertSql = `INSERT INTO \`${table}\` (${ODS_FIELDS.map((field) => `\`${field}\``).join(",")}) VALUES (${ODS_FIELDS.map(() => "?").join(",")})`;
  const updateSql = `UPDATE \`${table}\` SET ${dataFields.map((field) => `\`${field}\`=?`).join(",")} WHERE \`id\`=?`;
  let inserted = 0;
  let updated = 0;
  let repairedLegacyHashIds = 0;
  let skippedExactContent = 0;
  let skippedSimilarContent = 0;
  const assignedIds = [];
  const duplicateReport = [];
  for (const record of records) {
    record["关键词"] = normalizeSingleKeyword(record["关键词"]);
    const deduper = getDeduper(record["项目"]);
    let existingRows = [];
    if (record["文章链接"]) {
      [existingRows] = await connection.execute(`SELECT \`id\`, \`关键词\` FROM \`${table}\` WHERE \`文章链接\` = ? AND \`项目\` <=> ? LIMIT 1 FOR UPDATE`, [record["文章链接"], record["项目"]]);
    }
    if (!existingRows.length && record["文章id"]) {
      [existingRows] = await connection.execute(`SELECT \`id\`, \`关键词\` FROM \`${table}\` WHERE \`文章id\` = ? AND \`平台\` <=> ? AND \`项目\` <=> ? LIMIT 1 FOR UPDATE`, [record["文章id"], record["平台"], record["项目"]]);
    }
    let assignedId;
    if (existingRows.length) {
      assignedId = BigInt(existingRows[0].id);
      // One database article belongs to one retrieval task. Repeated hits from
      // later keywords update the article but retain its first attribution.
      record["关键词"] = preferExistingKeyword(existingRows[0]["关键词"], record["关键词"]);
      const expectedLegacyHash = record["文章链接"] ? BigInt(legacyStableBigInt(record["文章链接"])) : null;
      if (expectedLegacyHash !== null && assignedId === expectedLegacyHash) {
        nextId += 1n;
        await connection.execute(`UPDATE \`${table}\` SET \`id\`=? WHERE \`id\`=?`, [nextId.toString(), assignedId.toString()]);
        assignedId = nextId;
        repairedLegacyHashIds += 1;
      }
      await connection.execute(updateSql, [...dataFields.map((field) => record[field]), assignedId.toString()]);
      updated += 1;
    } else {
      const duplicate = deduper.find({ title: record["文章标题"], content: record["文章内容"], url: record["文章链接"] });
      if (duplicate) {
        if (duplicate.rule === "content_exact") skippedExactContent += 1;
        else skippedSimilarContent += 1;
        duplicateReport.push({
          keyword: record["关键词"] || null,
          sourceTitle: record["文章标题"] || null,
          sourceUrl: record["文章链接"] || null,
          sourcePlatform: record["平台"] || null,
          rule: duplicate.rule,
          similarity: Number(duplicate.similarity.toFixed(6)),
          titleMatched: duplicate.titleMatched,
          matchedId: duplicate.matched.id || null,
          matchedTitle: duplicate.matched.title || null,
          matchedUrl: duplicate.matched.url || null,
          matchedPlatform: duplicate.matched.platform || null,
          dedupeYear,
          skippedAt: new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", dateStyle: "short", timeStyle: "medium", hourCycle: "h23" }).format(new Date())
        });
        continue;
      }
      nextId += 1n;
      assignedId = nextId;
      record.id = assignedId.toString();
      await connection.execute(insertSql, ODS_FIELDS.map((field) => record[field]));
      inserted += 1;
      deduper.add({ id: assignedId.toString(), title: record["文章标题"], content: record["文章内容"], url: record["文章链接"], articleId: record["文章id"], platform: record["平台"], source: "current_batch" });
    }
    record.id = assignedId.toString();
    assignedIds.push(assignedId);
  }
  await connection.commit();
  try {
    const duplicateReportFile = path.join(path.dirname(inputFile), "database_dedupe.jsonl");
    await fs.writeFile(duplicateReportFile, duplicateReport.map((item) => JSON.stringify(item)).join("\n") + (duplicateReport.length ? "\n" : ""));
    await fs.writeFile(inputFile, records.map((record) => JSON.stringify(record)).join("\n") + "\n");
    const csvFile = inputFile.replace(/\.jsonl$/i, ".csv");
    if (csvFile !== inputFile) {
      const csvCell = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
      const csv = `\uFEFF${ODS_FIELDS.map(csvCell).join(",")}\n${records.map((row) => ODS_FIELDS.map((field) => csvCell(row[field])).join(",")).join("\n")}\n`;
      await fs.writeFile(csvFile, csv);
    }
  } catch (writeError) {
    console.warn(`数据库已提交，但回写本地ID失败：${writeError.message || writeError}`);
  }
  console.log(JSON.stringify({ host, port, database, table, inputFile, inputRecords: records.length, imported: inserted + updated, inserted, updated, skippedDuplicates: duplicateReport.length, skippedExactContent, skippedSimilarContent, dedupeYear, contentSimilarityThreshold, dedupeReport: path.join(path.dirname(inputFile), "database_dedupe.jsonl"), repairedLegacyHashIds, assignedIdMin: assignedIds.length ? assignedIds.reduce((a, b) => a < b ? a : b).toString() : null, assignedIdMax: assignedIds.length ? assignedIds.reduce((a, b) => a > b ? a : b).toString() : null, idStrategy: "数据库有效最大ID + 1；同链接沿用原ID；跨链接按正文去重" }, null, 2));
} catch (error) {
  try { await connection.rollback(); } catch {}
  throw error;
} finally {
  await connection.end();
}
