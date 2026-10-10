import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import { spawn } from "node:child_process";
import { ODS_FIELDS } from "./schema.mjs";
import { buildCrawlTaskWorkbook } from "./build-crawl-tasks.mjs";
import { readKeywordTasks } from "./read-keyword-tasks.mjs";
import { normalizeSingleKeyword, preferExistingKeyword } from "./keyword-attribution.mjs";

let activeChild = null;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const randomMilliseconds = ([min, max]) => Math.floor(min + Math.random() * (max - min + 1));

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

function slug(text) {
  return text.normalize("NFKC").replace(/[\\/:*?"<>|\s]+/g, "_").replace(/^_+|_+$/g, "");
}

function generatedTaskId(prefix, keyword) {
  return `${prefix}-${crypto.createHash("sha1").update(keyword).digest("hex").slice(0, 12).toUpperCase()}`;
}

async function readJsonKeywordTasks(file) {
  const parsed = JSON.parse(await fs.readFile(file, "utf8"));
  const rootProjectName = Array.isArray(parsed) ? null : parsed.projectName;
  const input = Array.isArray(parsed) ? parsed : (parsed.keywords || parsed.tasks);
  if (!Array.isArray(input)) throw new Error("JSON关键词文件必须是数组，或包含 keywords/tasks 数组");
  return input.map((entry) => typeof entry === "string" ? { keyword: entry } : entry).map((entry) => {
    const keyword = String(entry.keyword ?? entry["完整检索词"] ?? "").trim();
    return {
      id: String(entry.id ?? entry["检索词任务ID"] ?? generatedTaskId("JSON", keyword)).trim(),
      keyword,
      startDate: entry.startDate ?? entry["开始日期"] ?? null,
      endDate: entry.endDate ?? entry["结束日期"] ?? null,
      batchSize: Number(entry.batchSize ?? entry["每批条数"]) || null,
      maxPages: Number(entry.maxPages ?? entry["最大页数"]) || null,
      maxItems: Number(entry.maxItems ?? entry["最大文章数"]) || null,
      enabled: entry.enabled ?? entry["是否启用"] ?? true,
      status: entry.status ?? entry["执行状态"] ?? "待执行",
      projectName: entry.projectName ?? entry["项目"] ?? rootProjectName ?? null
    };
  }).filter((task) => task.keyword && ![false, "否", "false", 0].includes(task.enabled) && task.status !== "已完成");
}

function runNode(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, args, { stdio: "inherit", env: process.env });
    activeChild = child;
    child.on("error", (error) => { activeChild = null; reject(error); });
    child.on("exit", (code) => {
      activeChild = null;
      code === 0 ? resolve() : reject(new Error(`子任务退出码：${code}`));
    });
  });
}

async function importKeywordOutput(outputDir, task, trigger) {
  const inputFile = path.join(outputDir, "ods_social_media_post.jsonl");
  const markerFile = path.join(outputDir, "mysql_import_status.json");
  let sourceStat;
  try { sourceStat = await fs.stat(inputFile); } catch { return { status: "no_file", trigger }; }
  if (!sourceStat.size) return { status: "no_records", trigger };
  try {
    const marker = JSON.parse(await fs.readFile(markerFile, "utf8"));
    if (marker.status === "success" && marker.sourceSize === sourceStat.size && marker.sourceMtimeMs === sourceStat.mtimeMs) {
      return { ...marker, status: "already_imported", trigger };
    }
  } catch {}
  const startedAt = new Date().toISOString();
  try {
    await runNode([path.resolve("src/import-mysql.mjs"), "--input", inputFile]);
    const importedStat = await fs.stat(inputFile);
    const marker = {
      status: "success", trigger, keywordTaskId: task.id || null, keyword: task.keyword,
      inputFile, sourceSize: importedStat.size, sourceMtimeMs: importedStat.mtimeMs,
      startedAt, finishedAt: new Date().toISOString()
    };
    await fs.writeFile(markerFile, JSON.stringify(marker, null, 2));
    console.log(`关键词已入库：${task.keyword}`);
    return marker;
  } catch (error) {
    const marker = {
      status: "failed", trigger, keywordTaskId: task.id || null, keyword: task.keyword,
      inputFile, sourceSize: sourceStat.size, sourceMtimeMs: sourceStat.mtimeMs,
      startedAt, finishedAt: new Date().toISOString(), error: String(error.message || error)
    };
    try { await fs.writeFile(markerFile, JSON.stringify(marker, null, 2)); } catch {}
    console.error(`关键词入库失败，已保留待重试数据：${task.keyword}：${marker.error}`);
    return marker;
  }
}

const cli = parseArgs(process.argv);
const outputRoot = path.resolve(cli["output-dir"] || "batch-data");
const stateRoot = path.resolve(cli["state-dir"] || ".state/batch");
const maxPages = String(cli["max-pages"] || 20);
const maxItems = String(cli["max-items"] || 200);
const batchSize = String(cli["batch-size"] || 10);
const startDate = String(cli["start-date"] || "2026-01-01");
const endDate = cli["end-date"] ? String(cli["end-date"]) : null;
const force = cli.force === true || cli.force === "true";
const resumeFailed = cli["resume-failed"] === true || cli["resume-failed"] === "true";
const skipExcel = cli["skip-excel"] === true || cli["skip-excel"] === "true";
const importEachKeyword = cli["import-each-keyword"] === true || cli["import-each-keyword"] === "true";
const securityBetweenKeywordsMs = [
  Math.max(0, Number(cli["security-between-keywords-min-ms"] ?? 60000)),
  Math.max(0, Number(cli["security-between-keywords-max-ms"] ?? 180000))
];
if (securityBetweenKeywordsMs[1] < securityBetweenKeywordsMs[0]) securityBetweenKeywordsMs[1] = securityBetweenKeywordsMs[0];
const normalBetweenKeywordsMs = [
  Math.max(0, Number(cli["between-keywords-min-ms"] ?? 20000)),
  Math.max(0, Number(cli["between-keywords-max-ms"] ?? 60000))
];
if (normalBetweenKeywordsMs[1] < normalBetweenKeywordsMs[0]) normalBetweenKeywordsMs[1] = normalBetweenKeywordsMs[0];
const securityCircuitBreakerThreshold = Math.max(1, Number(cli["security-circuit-breaker-threshold"] ?? 3));
const securityCircuitBreakerMs = [
  Math.max(0, Number(cli["security-circuit-breaker-min-ms"] ?? 1800000)),
  Math.max(0, Number(cli["security-circuit-breaker-max-ms"] ?? 3600000))
];
if (securityCircuitBreakerMs[1] < securityCircuitBreakerMs[0]) securityCircuitBreakerMs[1] = securityCircuitBreakerMs[0];
if (importEachKeyword && (!process.env.MYSQL_USER || !process.env.MYSQL_PASSWORD)) {
  throw new Error("按关键词入库需要在爬虫启动前提供 MYSQL_USER 和 MYSQL_PASSWORD");
}
let interrupted = false;
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    if (interrupted) return;
    interrupted = true;
    console.warn(`\n收到 ${signal}，当前文章落盘后将尝试入库并安全退出……`);
    if (activeChild && !activeChild.killed) activeChild.kill();
  });
}
let keywordTasks;
if (cli.query) {
  keywordTasks = [{ id: `SINGLE-${Date.now()}`, keyword: String(cli.query).trim(), projectName: cli["project-name"] || null }];
} else if (cli["keyword-task-xlsx"]) {
  keywordTasks = await readKeywordTasks(path.resolve(String(cli["keyword-task-xlsx"])));
} else if (cli["keywords-json"]) {
  keywordTasks = await readJsonKeywordTasks(path.resolve(String(cli["keywords-json"])));
} else {
  const keywordFile = path.resolve(cli.keywords || "keywords.txt");
  keywordTasks = (await fs.readFile(keywordFile, "utf8")).split(/\r?\n/).map((line) => line.trim()).filter((line) => line && !line.startsWith("#")).map((keyword, index) => ({ id: `TXT-${String(index + 1).padStart(4, "0")}`, keyword }));
}
if (!keywordTasks.length) throw new Error("没有可执行的百度资讯检索词任务");

await fs.mkdir(outputRoot, { recursive: true });
await fs.mkdir(stateRoot, { recursive: true });
const summaries = [];
const databaseImports = [];
let consecutiveSecurityKeywords = 0;

for (const [index, task] of keywordTasks.entries()) {
  const keyword = task.keyword;
  const projectName = task.projectName || cli["project-name"] || "全国地产设计产品力监测";
  const key = slug(keyword);
  const outputDir = path.join(outputRoot, key);
  const stateDir = path.join(stateRoot, key);
  console.log(`\n[${index + 1}/${keywordTasks.length}] ${keyword}`);
  const summaryPath = path.join(outputDir, "run_summary.json");
  if (!force && !resumeFailed) {
    try {
      const summary = JSON.parse(await fs.readFile(summaryPath, "utf8"));
      const sameProject = summary.projectName ? summary.projectName === projectName : projectName === "全国地产设计产品力监测";
      if (sameProject && !summary.stopReason && summary.completionReason) {
        summaries.push({ keyword, outputDir, ...summary });
        console.log(`已完成，跳过重复请求：accepted=${summary.accepted}`);
        if (importEachKeyword) databaseImports.push(await importKeywordOutput(outputDir, task, "completed_task_recheck"));
        continue;
      }
      console.log("检测到未完成的历史任务，将从已有进度继续。");
    } catch {}
  }
  const childArgs = [
    path.resolve("src/index.mjs"), "--query", keyword, "--keyword-task-id", task.id || "", "--start-date", String(task.startDate || startDate).slice(0, 10),
    "--project-name", projectName,
    "--max-pages", String(task.maxPages || maxPages), "--max-items", String(task.maxItems || maxItems), "--batch-size", String(task.batchSize || batchSize),
    "--output-dir", outputDir, "--state-dir", stateDir, "--skip-acceptance"
  ];
  for (const option of ["max-security-retries", "security-cooldown-min-ms", "security-cooldown-max-ms", "headless", "browser-executable"]) {
    if (cli[option] != null) childArgs.push(`--${option}`, String(cli[option]));
  }
  if (task.endDate || endDate) childArgs.push("--end-date", String(task.endDate || endDate).slice(0, 10));
  let hasPartialProgress = false;
  try { await fs.access(path.join(outputDir, "crawl_tasks.jsonl")); hasPartialProgress = true; } catch {}
  if (!hasPartialProgress) {
    try { await fs.access(path.join(outputDir, "ods_social_media_post.jsonl")); hasPartialProgress = true; } catch {}
  }
  if (resumeFailed || hasPartialProgress) childArgs.push("--resume");
  try {
    await runNode(childArgs);
    const summary = JSON.parse(await fs.readFile(summaryPath, "utf8"));
    summaries.push({ keyword, outputDir, ...summary });
  } catch (error) {
    const failedSummary = { keywordTaskId: task.id || null, query: keyword, projectName, dateWindow: [task.startDate || startDate, task.endDate || endDate], discovered: 0, processed: 0, accepted: 0, completionReason: null, stopReason: String(error.message || error), finishedAt: new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", dateStyle: "short", timeStyle: "medium", hourCycle: "h23" }).format(new Date()), timezone: "Asia/Shanghai" };
    try {
      await fs.mkdir(outputDir, { recursive: true });
      await fs.writeFile(summaryPath, JSON.stringify(failedSummary, null, 2));
    } catch (summaryError) {
      console.error(`无法写入失败摘要，仍将尝试导入已有数据：${summaryError.message || summaryError}`);
    }
    summaries.push({ keyword, outputDir, ...failedSummary });
  }
  if (importEachKeyword) databaseImports.push(await importKeywordOutput(outputDir, task, interrupted ? "process_signal" : "keyword_finished_or_failed"));
  const latestSummary = summaries.at(-1);
  const securityLimited = /SECURITY_CHALLENGE|STOP_CAPTCHA|STOP_RATE_LIMIT/i.test(String(latestSummary?.stopReason || ""));
  consecutiveSecurityKeywords = securityLimited ? consecutiveSecurityKeywords + 1 : 0;
  if (!interrupted && index < keywordTasks.length - 1) {
    if (consecutiveSecurityKeywords >= securityCircuitBreakerThreshold) {
      const delayMs = randomMilliseconds(securityCircuitBreakerMs);
      console.warn(`[全局熔断] 已连续${consecutiveSecurityKeywords}个检索词触发安全验证，保留全部断点并休眠${Math.ceil(delayMs / 60000)}分钟后继续。`);
      await sleep(delayMs);
      consecutiveSecurityKeywords = 0;
    } else if (securityLimited) {
      const delayMs = randomMilliseconds(securityBetweenKeywordsMs);
      console.warn(`[安全验证] 当前检索词已保留断点，将继续后续任务；切换关键词前额外休眠${Math.ceil(delayMs / 1000)}秒。`);
      await sleep(delayMs);
    } else {
      const delayMs = randomMilliseconds(normalBetweenKeywordsMs);
      console.log(`[访问间隔] 随机休眠${Math.ceil(delayMs / 1000)}秒后处理下一个检索词。`);
      await sleep(delayMs);
    }
  }
  if (interrupted) break;
}

const merged = new Map();
for (const summary of summaries) {
  const file = path.join(summary.outputDir, "ods_social_media_post.jsonl");
  let text = "";
  try { text = await fs.readFile(file, "utf8"); } catch { continue; }
  for (const line of text.split(/\r?\n/).filter(Boolean)) {
    const record = JSON.parse(line);
    record["关键词"] = normalizeSingleKeyword(record["关键词"]);
    const key = record["文章链接"] || record.id;
    const existing = merged.get(key);
    if (!existing) merged.set(key, record);
    else existing["关键词"] = preferExistingKeyword(existing["关键词"], record["关键词"]);
  }
}

const records = [...merged.values()];
const csvCell = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
const csv = `\uFEFF${ODS_FIELDS.map(csvCell).join(",")}\n${records.map((row) => ODS_FIELDS.map((field) => csvCell(row[field])).join(",")).join("\n")}\n`;
await fs.writeFile(path.join(outputRoot, "combined_ods_social_media_post.jsonl"), records.map((row) => JSON.stringify(row)).join("\n") + (records.length ? "\n" : ""));
await fs.writeFile(path.join(outputRoot, "combined_ods_social_media_post.csv"), csv);
const finishedAt = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", dateStyle: "short", timeStyle: "medium", hourCycle: "h23" }).format(new Date());
await fs.writeFile(path.join(outputRoot, "batch_summary.json"), JSON.stringify({ keywords: summaries, databaseImports, keywordTaskCount: keywordTasks.length, uniqueAccepted: records.length, interrupted, finishedAt, timezone: "Asia/Shanghai" }, null, 2));
let acceptanceReport = null;
if (!skipExcel) {
  acceptanceReport = path.join(outputRoot, "爬虫任务表.xlsx");
  await buildCrawlTaskWorkbook(outputRoot, acceptanceReport);
}
console.log(JSON.stringify({ keywordCount: keywordTasks.length, uniqueAccepted: records.length, outputRoot, acceptanceReport }, null, 2));
if (databaseImports.some((item) => item.status === "failed")) process.exitCode = 2;
else if (interrupted) process.exitCode = 130;
