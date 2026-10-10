import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

async function loadArtifactTool() {
  try { return await import("@oai/artifact-tool"); } catch {}
  const candidate = process.env.ARTIFACT_TOOL_MODULE || (process.env.USERPROFILE && path.join(process.env.USERPROFILE, ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs"));
  if (candidate) { try { await fs.access(candidate); return import(pathToFileURL(candidate).href); } catch {} }
  throw new Error("未找到Excel组件，请设置 ARTIFACT_TOOL_MODULE");
}

async function findFiles(root, filename) {
  const found = [];
  async function walk(dir) {
    for (const entry of await fs.readdir(dir, { withFileTypes: true })) {
      if (["node_modules", "browser-profile"].includes(entry.name)) continue;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) await walk(full);
      else if (entry.name === filename) found.push(full);
    }
  }
  await walk(root);
  return found;
}

async function readJson(file) {
  try { return JSON.parse(await fs.readFile(file, "utf8")); } catch { return null; }
}

function readJsonl(text) {
  return text.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
}

function excelDate(value) {
  if (!value) return null;
  const normalized = String(value).replace(" ", "T");
  const date = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(normalized) ? normalized : `${normalized}+08:00`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function host(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return null; }
}

function comparableUrl(value) {
  try {
    const url = new URL(value);
    url.hash = "";
    for (const key of [...url.searchParams.keys()]) if (/^(?:utm_.+|spm|from|source|wfr|for)$/i.test(key)) url.searchParams.delete(key);
    url.searchParams.sort();
    return url.href.replace(/\?$/, "");
  } catch { return String(value || "").replace(/#.*$/, ""); }
}

function isAccepted(item) {
  return item.accepted === true || (item.accepted == null && item.status === "parsed" && item.dateStatus === "in_window" && Number(item.contentLength) >= 100);
}

function statusText(item) {
  if (isAccepted(item)) return "成功";
  if (item.status === "failed") return "失败";
  if (item.status === "incomplete") return "字段不完整";
  if (item.status === "excluded") return "非资讯排除";
  if (item.status === "pending") return "待抓取";
  if (item.dateStatus === "unknown") return "日期待复核";
  return "已处理未入库";
}

function completionText(summary) {
  if (summary.stopReason) return `异常停止：${summary.stopReason}`;
  return ({ older_than_start_date_found: "批内发现2026年前文章，正常结束", no_new_results: "没有新的搜索结果", max_items_reached: "达到最大文章数", max_pages_reached: "达到最大页数" })[summary.completionReason] || summary.completionReason || "";
}

function taskId(item) {
  return `CRAWL-${crypto.createHash("sha1").update(`${item.keywordTaskId || item.query || ""}|${item.url || item.finalUrl || ""}`).digest("hex").slice(0, 16).toUpperCase()}`;
}

function styleHeader(sheet, address) {
  sheet.getRange(address).format = { fill: "#1F4E78", font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { preset: "inside", style: "thin", color: "#FFFFFF" } };
}

export async function buildCrawlTaskWorkbook(outputRoot, outputFile, options = {}) {
  const root = path.resolve(outputRoot);
  const summaryFiles = await findFiles(root, "run_summary.json");
  const auditFiles = await findFiles(root, "crawl_audit.jsonl");
  const discoveredFiles = await findFiles(root, "discovered_links.jsonl");
  const dedupeFiles = await findFiles(root, "database_dedupe.jsonl");
  const mysqlStatusFiles = await findFiles(root, "mysql_import_status.json");
  const summaries = (await Promise.all(summaryFiles.map(readJson))).filter(Boolean);
  const dedupes = [];
  for (const file of dedupeFiles) dedupes.push(...readJsonl(await fs.readFile(file, "utf8")));
  const dedupeByUrl = new Map(dedupes.filter((item) => item.sourceUrl).flatMap((item) => [[item.sourceUrl, item], [comparableUrl(item.sourceUrl), item]]));
  const mysqlStatusByKeyword = new Map();
  for (const file of mysqlStatusFiles) {
    const status = await readJson(file);
    if (status?.keyword) mysqlStatusByKeyword.set(status.keyword, status);
  }
  const tasks = [];
  for (const file of auditFiles) tasks.push(...readJsonl(await fs.readFile(file, "utf8")));
  const taskUrls = new Set(tasks.map((item) => item.url));
  for (const file of discoveredFiles) {
    for (const item of readJsonl(await fs.readFile(file, "utf8"))) {
      if (taskUrls.has(item.url)) continue;
      taskUrls.add(item.url);
      tasks.push({ ...item, status: "pending", accepted: false, dateStatus: "unknown", attemptCount: 0, error: "已发现链接，尚未完成详情页采集" });
    }
  }
  for (const summary of summaries) {
    if (!summary.stopReason || tasks.some((item) => item.query === summary.query)) continue;
    const searchUrl = new URL("https://www.baidu.com/s");
    searchUrl.search = new URLSearchParams({ tn: "news", rtt: "4", bsst: "1", cl: "2", wd: summary.query, medium: "0", pn: "0" }).toString();
    tasks.push({ query: summary.query, keywordTaskId: summary.keywordTaskId, title: "搜索结果列表未加载", url: searchUrl.href, source: "百度资讯", platform: "百度资讯列表页", status: "failed", accepted: false, dateStatus: "unknown", attemptCount: 1, error: summary.stopReason });
  }
  if (!summaries.length && !tasks.length) throw new Error(`未在 ${root} 找到爬虫运行数据`);

  const { SpreadsheetFile, Workbook } = await loadArtifactTool();
  const workbook = Workbook.create();
  const summarySheet = workbook.worksheets.add("任务汇总");
  const taskSheet = workbook.worksheets.add("爬虫任务");
  const retrySheet = workbook.worksheets.add("失败待重试");
  const dedupeSheet = workbook.worksheets.add("入库去重");
  summarySheet.tabColor = "#1F4E78";
  retrySheet.tabColor = "#C55A11";
  dedupeSheet.tabColor = "#7F8C8D";

  const taskByKeyword = new Map();
  for (const item of tasks) {
    const keyword = item.query || "未标明检索词";
    if (!taskByKeyword.has(keyword)) taskByKeyword.set(keyword, []);
    taskByKeyword.get(keyword).push(item);
  }
  for (const summary of summaries) if (!taskByKeyword.has(summary.query)) taskByKeyword.set(summary.query, []);
  const summaryMap = new Map(summaries.map((item) => [item.query, item]));
  const summaryHeaders = ["检索词任务ID", "检索词", "发现链接", "成功", "非资讯排除", "失败", "字段不完整", "日期待复核", "待抓取", "2026年前", "批次数", "完成状态"];
  const summaryRows = [...taskByKeyword].map(([keyword, rows]) => {
    const summary = summaryMap.get(keyword) || {};
    return [summary.keywordTaskId || rows.find((item) => item.keywordTaskId)?.keywordTaskId || "", keyword, summary.discovered ?? rows.length, rows.filter(isAccepted).length, rows.filter((item) => item.status === "excluded").length, rows.filter((item) => item.status === "failed").length, rows.filter((item) => item.status === "incomplete").length, rows.filter((item) => item.status !== "excluded" && item.dateStatus === "unknown").length, rows.filter((item) => item.status === "pending").length, rows.filter((item) => item.dateStatus === "older_than_start").length, summary.batchesProcessed ?? 0, completionText(summary)];
  });
  summarySheet.showGridLines = false;
  summarySheet.freezePanes.freezeRows(5);
  summarySheet.getRange("A2").values = [["百度资讯爬虫任务汇总"]];
  summarySheet.getRange("A2").format.font = { name: "Arial", size: 15, bold: true, color: "#1F2937" };
  summarySheet.getRange("A3").values = [["失败、字段不完整、日期待复核和待抓取任务可用于断点续爬。数据库状态不影响文章抓取状态。"]];
  summarySheet.getRange("A5:L5").values = [summaryHeaders];
  summarySheet.getRangeByIndexes(5, 0, summaryRows.length, summaryHeaders.length).values = summaryRows;
  styleHeader(summarySheet, "A5:L5");
  summarySheet.tables.add(`A5:L${5 + summaryRows.length}`, true, "CrawlTaskSummary").style = "TableStyleMedium2";
  summarySheet.getRange("A:L").format.font = { name: "Arial", size: 10, color: "#1F2937" };
  summarySheet.getRange("A:B").format.columnWidth = 26;
  summarySheet.getRange("C:K").format.columnWidth = 13;
  summarySheet.getRange("L:L").format.columnWidth = 42;

  const headers = ["爬虫任务ID", "检索词任务ID", "检索词", "渠道", "发现页码", "页内排名", "发现时间", "文章标题", "百度来源", "百度卡片日期", "百度结果链接", "最终文章链接", "所属平台", "解析器", "详情发布时间", "日期判断", "爬虫状态", "是否成功", "是否进入ODS", "清洗前长度", "清洗后长度", "清洗规则", "尝试次数", "最近尝试时间", "失败或缺失原因", "数据库状态", "下一步操作"];
  const duplicateFor = (item) => dedupeByUrl.get(item.finalUrl || "") || dedupeByUrl.get(comparableUrl(item.finalUrl)) || dedupeByUrl.get(item.url || "") || dedupeByUrl.get(comparableUrl(item.url));
  const duplicateText = (duplicate) => duplicate?.rule === "content_exact" ? "重复跳过：正文完全一致" : duplicate?.rule === "content_similarity" ? `重复跳过：正文相似${(Number(duplicate.similarity) * 100).toFixed(1)}%` : null;
  const rowFor = (item) => {
    const duplicate = duplicateFor(item);
    const mysqlStatus = mysqlStatusByKeyword.get(item.query);
    const keywordImported = options.dbImported || mysqlStatus?.status === "success" || mysqlStatus?.status === "already_imported";
    const databaseStatus = duplicateText(duplicate) || (isAccepted(item) ? (keywordImported ? "已入库" : mysqlStatus?.status === "failed" ? `入库失败：${mysqlStatus.error || "待重试"}` : "待入库") : "不入库");
    const nextAction = duplicate ? "无需入库" : isAccepted(item) ? (keywordImported ? "已完成" : "执行数据库入库/下次启动自动重试") : item.status === "excluded" ? "无需重试" : (["failed", "incomplete", "pending"].includes(item.status) || item.dateStatus === "unknown" ? "断点续爬/补充平台解析器" : "无需重试");
    return [taskId(item), item.keywordTaskId || "", item.query || "", "百度资讯", Number(item.pageIndex ?? ((item.batch || 1) - 1)) + 1, Number(item.rank) || null, excelDate(item.foundAt), item.title || "", item.source || "", item.cardDate || "", item.url || "", item.finalUrl || "", item.platform || item.source || host(item.finalUrl || item.url) || "未知平台", item.parser || "", excelDate(item.publishedAt), item.dateStatus || "unknown", statusText(item), isAccepted(item) ? "是" : "否", isAccepted(item) ? "是" : "否", Number(item.rawContentLength ?? item.contentLength) || 0, Number(item.contentLength) || 0, item.contentCleaningVersion || "legacy", Number(item.attemptCount) || 0, excelDate(item.lastAttemptAt), item.error || (item.missingFields || []).join("、"), databaseStatus, nextAction];
  };
  const retryTasks = tasks.filter((item) => item.status !== "excluded" && (item.status === "failed" || item.status === "incomplete" || item.status === "pending" || item.dateStatus === "unknown"));

  function writeTasks(sheet, title, items, tableName) {
    const emptyRow = Array(headers.length).fill("");
    emptyRow[3] = "百度资讯";
    emptyRow[7] = "无待重试任务";
    const rows = items.length ? items.map(rowFor) : [emptyRow];
    const last = 5 + rows.length;
    sheet.showGridLines = false;
    sheet.freezePanes.freezeRows(5);
    sheet.freezePanes.freezeColumns(3);
    sheet.getRange("A2").values = [[title]];
    sheet.getRange("A2").format.font = { name: "Arial", size: 15, bold: true, color: "#1F2937" };
    sheet.getRange("A3").values = [["同一检索词下保留每个百度发现链接、最终平台、执行状态、错误和重试信息。"]];
    sheet.getRange("A5:AA5").values = [headers];
    sheet.getRangeByIndexes(5, 0, rows.length, headers.length).values = rows;
    sheet.getRange(`A2:AA${last}`).format.font = { name: "Arial", size: 10, color: "#1F2937" };
    sheet.getRange("A2").format.font = { name: "Arial", size: 15, bold: true, color: "#1F2937" };
    styleHeader(sheet, "A5:AA5");
    sheet.tables.add(`A5:AA${last}`, true, tableName).style = "TableStyleMedium2";
    for (const column of ["G", "O", "X"]) sheet.getRange(`${column}6:${column}${last}`).setNumberFormat("yyyy-mm-dd hh:mm:ss");
    for (const [range, width] of [["A:B", 24], ["C:C", 26], ["D:G", 14], ["H:H", 42], ["I:J", 18], ["K:L", 55], ["M:N", 18], ["O:P", 20], ["Q:S", 15], ["T:W", 16], ["X:X", 20], ["Y:Y", 42], ["Z:AA", 24]]) sheet.getRange(range).format.columnWidth = width;
    sheet.getRange(`Q6:Q${last}`).conditionalFormats.add("containsText", { text: "失败", format: { fill: "#FDE9E7", font: { bold: true, color: "#C00000" } } });
    sheet.getRange(`Q6:Q${last}`).conditionalFormats.add("containsText", { text: "待", format: { fill: "#FFF2CC", font: { color: "#7F6000" } } });
  }
  writeTasks(taskSheet, "全部文章爬虫任务", tasks, "CrawlTasks");
  writeTasks(retrySheet, "失败及待重试任务", retryTasks, "RetryTasks");

  const dedupeHeaders = ["检索词", "去重规则", "正文相似度", "待入库标题", "待入库链接", "待入库平台", "命中数据库ID", "命中数据库标题", "命中数据库链接", "命中数据库平台", "去重年份", "判定时间"];
  const dedupeRows = dedupes.length ? dedupes.map((item) => [item.keyword || "", item.rule === "content_exact" ? "正文完全一致" : "正文字符相似", Number(item.similarity) || 0, item.sourceTitle || "", item.sourceUrl || "", item.sourcePlatform || "", item.matchedId || "", item.matchedTitle || "", item.matchedUrl || "", item.matchedPlatform || "", Number(item.dedupeYear) || null, excelDate(item.skippedAt)]) : [["", "无重复文章", 0, "", "", "", "", "", "", "", null, null]];
  const dedupeLast = 5 + dedupeRows.length;
  dedupeSheet.showGridLines = false;
  dedupeSheet.freezePanes.freezeRows(5);
  dedupeSheet.freezePanes.freezeColumns(3);
  dedupeSheet.getRange("A2").values = [["入库前重复文章"]];
  dedupeSheet.getRange("A3").values = [["标题仅作辅助，不单独拦截；以清洗后正文为准，正文完全一致或4字符片段Dice相似度达到50%即跳过入库。"]];
  dedupeSheet.getRange("A5:L5").values = [dedupeHeaders];
  dedupeSheet.getRangeByIndexes(5, 0, dedupeRows.length, dedupeHeaders.length).values = dedupeRows;
  dedupeSheet.getRange(`A2:L${dedupeLast}`).format.font = { name: "Arial", size: 10, color: "#1F2937" };
  dedupeSheet.getRange("A2").format.font = { name: "Arial", size: 15, bold: true, color: "#1F2937" };
  styleHeader(dedupeSheet, "A5:L5");
  dedupeSheet.tables.add(`A5:L${dedupeLast}`, true, "DatabaseDedupes").style = "TableStyleMedium2";
  dedupeSheet.getRange(`C6:C${dedupeLast}`).setNumberFormat("0.0%");
  dedupeSheet.getRange(`L6:L${dedupeLast}`).setNumberFormat("yyyy-mm-dd hh:mm:ss");
  for (const [range, width] of [["A:B", 22], ["C:C", 14], ["D:D", 42], ["E:E", 55], ["F:G", 18], ["H:H", 42], ["I:I", 55], ["J:K", 18], ["L:L", 20]]) dedupeSheet.getRange(range).format.columnWidth = width;

  workbook.recalculate();
  const inspection = await workbook.inspect({ kind: "table", range: `任务汇总!A2:L${5 + summaryRows.length}`, include: "values,formulas", tableMaxRows: 30, tableMaxCols: 13, maxChars: 10000 });
  const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 } });
  if (!/matched 0 entries/.test(errors.ndjson || "")) throw new Error("爬虫任务表存在公式错误");
  if (options.previewDir) {
    await fs.mkdir(options.previewDir, { recursive: true });
    for (const [name, range] of [["任务汇总", `A1:L${Math.min(35, 5 + summaryRows.length)}`], ["爬虫任务", `A1:AA${Math.min(25, 6 + tasks.length)}`], ["失败待重试", `A1:AA${Math.min(25, 6 + retryTasks.length)}`], ["入库去重", `A1:L${Math.min(25, 6 + dedupeRows.length)}`]]) {
      const preview = await workbook.render({ sheetName: name, range, scale: 1, format: "png" });
      await fs.writeFile(path.join(options.previewDir, `${name}.png`), new Uint8Array(await preview.arrayBuffer()));
    }
  }
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await fs.mkdir(path.dirname(path.resolve(outputFile)), { recursive: true });
  await output.save(path.resolve(outputFile));
  return { outputFile: path.resolve(outputFile), keywords: summaryRows.length, tasks: tasks.length, retryTasks: retryTasks.length, dedupes: dedupes.length, inspection: inspection.ndjson };
}

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

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const args = parseArgs(process.argv);
  const root = path.resolve(String(args["output-dir"] || "batch-data"));
  const output = path.resolve(String(args.output || path.join(root, "爬虫任务表.xlsx")));
  console.log(JSON.stringify(await buildCrawlTaskWorkbook(root, output, { previewDir: args["preview-dir"] ? path.resolve(String(args["preview-dir"])) : null, dbImported: args["db-imported"] === true || args["db-imported"] === "true" }), null, 2));
}
