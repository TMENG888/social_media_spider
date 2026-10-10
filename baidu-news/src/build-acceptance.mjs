import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

async function loadArtifactTool() {
  try { return await import("@oai/artifact-tool"); } catch {}
  const candidates = [
    process.env.ARTIFACT_TOOL_MODULE,
    process.env.USERPROFILE && path.join(process.env.USERPROFILE, ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs")
  ].filter(Boolean);
  for (const candidate of candidates) {
    try { await fs.access(candidate); return import(pathToFileURL(candidate).href); } catch {}
  }
  throw new Error("未找到Excel生成组件。请设置 ARTIFACT_TOOL_MODULE 为 @oai/artifact-tool/dist/artifact_tool.mjs 的完整路径");
}

async function findFiles(root, filename) {
  const results = [];
  async function walk(dir) {
    for (const entry of await fs.readdir(dir, { withFileTypes: true })) {
      if (["node_modules", "browser-profile"].includes(entry.name)) continue;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) await walk(full);
      else if (entry.name === filename) results.push(full);
    }
  }
  await walk(root);
  return results;
}

async function readJson(file) {
  try { return JSON.parse(await fs.readFile(file, "utf8")); } catch { return null; }
}

function readJsonl(text) {
  return text.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
}

function host(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return null; }
}

function excelDate(value) {
  if (!value) return null;
  const normalized = String(value).replace(" ", "T");
  const date = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(normalized) ? normalized : `${normalized}+08:00`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function outcome(item) {
  if (isAccepted(item)) return "已进入ODS";
  if (item.status === "failed" && item.dateStatus === "in_window") return "2026候选采集失败";
  if (item.status === "failed") return "详情页采集失败";
  if (item.status === "incomplete" && item.dateStatus === "in_window") return "2026文章字段不完整";
  if (item.dateStatus === "unknown") return "日期未知未入库";
  if (item.dateStatus === "older_than_start") return "早于2026，不入库";
  if (item.dateStatus === "newer_than_end") return "晚于运行日，不入库";
  return "未入库";
}

function isAccepted(item) {
  return item.accepted === true || (item.accepted == null && item.status === "parsed" && item.dateStatus === "in_window" && Number(item.contentLength) > 0);
}

function completionText(value) {
  const labels = {
    older_than_start_date_found: "批内发现2026年前文章，正常结束",
    no_new_results: "没有新的搜索结果",
    max_items_reached: "达到最大文章数",
    max_pages_reached: "达到最大页数"
  };
  return labels[value] || value || "";
}

function formatDataSheet(sheet, rangeAddress, headerAddress, urlColumns = []) {
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(5);
  const used = sheet.getRange(rangeAddress);
  used.format.font = { name: "Arial", size: 10, color: "#1F2937" };
  used.format.verticalAlignment = "center";
  const header = sheet.getRange(headerAddress);
  header.format = {
    fill: "#1F4E78",
    font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "inside", style: "thin", color: "#FFFFFF" }
  };
  for (const column of urlColumns) sheet.getRange(column).format.wrapText = false;
}

export async function buildAcceptanceWorkbook(outputRoot, outputFile, options = {}) {
  const root = path.resolve(outputRoot);
  const auditFiles = await findFiles(root, "crawl_audit.jsonl");
  const summaryFiles = await findFiles(root, "run_summary.json");
  const audits = [];
  const summaries = (await Promise.all(summaryFiles.map(readJson))).filter(Boolean);
  for (const file of auditFiles) {
    const rows = readJsonl(await fs.readFile(file, "utf8"));
    audits.push(...rows);
  }
  if (!summaryFiles.length && !auditFiles.length) throw new Error(`未在 ${root} 找到运行结果`);
  for (const summary of summaries) {
    if (!summary.stopReason || audits.some((item) => item.query === summary.query)) continue;
    const searchUrl = new URL("https://www.baidu.com/s");
    searchUrl.search = new URLSearchParams({ tn: "news", rtt: "4", bsst: "1", cl: "2", wd: summary.query, medium: "0", pn: "0" }).toString();
    audits.push({ query: summary.query, batch: 0, rank: 0, title: "搜索结果列表未加载", url: searchUrl.href, finalUrl: null, source: "百度资讯", platform: "百度资讯列表页", parser: null, publishedAt: null, cardDate: null, dateStatus: "unknown", contentLength: 0, status: "failed", accepted: false, missingFields: [], error: summary.stopReason, synthetic: true });
  }

  const { SpreadsheetFile, Workbook } = await loadArtifactTool();
  const workbook = Workbook.create();
  const summarySheet = workbook.worksheets.add("验收汇总");
  const issueSheet = workbook.worksheets.add("失败及未入库");
  const detailSheet = workbook.worksheets.add("全部明细");
  summarySheet.tabColor = "#1F4E78";
  issueSheet.tabColor = "#C55A11";
  summarySheet.showGridLines = false;

  const byKeyword = new Map();
  for (const item of audits) {
    const keyword = item.query || "未标明关键词";
    if (!byKeyword.has(keyword)) byKeyword.set(keyword, []);
    byKeyword.get(keyword).push(item);
  }
  for (const summary of summaries) if (!byKeyword.has(summary.query)) byKeyword.set(summary.query, []);
  const summaryByKeyword = new Map(summaries.map((item) => [item.query, item]));
  const summaryHeaders = ["关键词", "发现数", "处理数", "进入ODS", "2026候选失败", "字段不完整", "日期未知", "采集失败", "2026年前", "批次数", "完成原因"];
  const summaryRows = [...byKeyword].map(([keyword, rows]) => {
    const run = summaryByKeyword.get(keyword) || {};
    return [
      keyword, run.discovered ?? rows.length, run.processed ?? rows.length,
      rows.filter(isAccepted).length,
      rows.filter((row) => !isAccepted(row) && row.dateStatus === "in_window").length,
      rows.filter((row) => row.status === "incomplete").length,
      rows.filter((row) => row.dateStatus === "unknown").length,
      rows.filter((row) => row.status === "failed").length,
      rows.filter((row) => row.dateStatus === "older_than_start").length,
      run.batchesProcessed ?? Math.max(0, ...rows.map((row) => Number(row.batch) || 0)),
      run.stopReason || completionText(run.completionReason)
    ];
  });
  summarySheet.getRange("A2").values = [["批量关键词爬虫任务验收"]];
  summarySheet.getRange("A2").format.font = { name: "Arial", size: 15, bold: true, color: "#1F2937" };
  summarySheet.getRange("A3").values = [[`日期口径：2026-01-01至运行当天；文章获取时间：北京时间；生成时间：${new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", dateStyle: "medium", timeStyle: "medium", hourCycle: "h23" }).format(new Date())}`]];
  summarySheet.getRange("A3").format.font = { name: "Arial", size: 10, color: "#6B7280" };
  summarySheet.getRange("A5:K5").values = [summaryHeaders];
  summarySheet.getRangeByIndexes(5, 0, summaryRows.length, summaryHeaders.length).values = summaryRows;
  formatDataSheet(summarySheet, `A2:K${5 + summaryRows.length}`, "A5:K5");
  summarySheet.tables.add(`A5:K${5 + summaryRows.length}`, true, "AcceptanceSummary").style = "TableStyleMedium2";
  summarySheet.getRange("A:A").format.columnWidth = 24;
  summarySheet.getRange("B:J").format.columnWidth = 12;
  summarySheet.getRange("K:K").format.columnWidth = 30;

  const detailHeaders = ["序号", "关键词", "批次", "排名", "验收结果", "是否2026候选", "平台", "文章标题", "详情发布时间", "百度卡片日期", "解析器", "正文长度", "失败或缺失原因", "百度结果链接", "最终文章链接", "日期判断"];
  const makeRow = (item, index) => [
    index + 1, item.query || "", Number(item.batch) || null, Number(item.rank) || null, outcome(item),
    item.dateStatus === "in_window" ? "是" : "否/未知", item.platform || item.source || host(item.finalUrl || item.url) || "未知平台",
    item.title || "", excelDate(item.publishedAt), item.cardDate || "", item.parser || "", Number(item.contentLength) || 0,
    item.error || (item.missingFields || []).join("、"), item.url || "", item.finalUrl || "", item.dateStatus || "unknown"
  ];
  const issues = audits.filter((item) => item.status === "failed" || item.status === "incomplete" || item.dateStatus === "unknown");
  const writeDetail = (sheet, title, rows, tableName) => {
    const safeRows = rows.length ? rows.map(makeRow) : [[1, "", null, null, "无待复核记录", "", "", "", null, "", "", 0, "", "", "", ""]];
    sheet.getRange("A2").values = [[title]];
    sheet.getRange("A2").format.font = { name: "Arial", size: 15, bold: true, color: "#1F2937" };
    sheet.getRange("A3").values = [["“2026候选”以详情页成功识别的发布日期为准；日期未知项单独保留，供开发复核解析器。"]];
    sheet.getRange("A3").format.font = { name: "Arial", size: 10, color: "#6B7280" };
    sheet.getRange("A5:P5").values = [detailHeaders];
    sheet.getRangeByIndexes(5, 0, safeRows.length, detailHeaders.length).values = safeRows;
    const last = 5 + safeRows.length;
    formatDataSheet(sheet, `A2:P${last}`, "A5:P5", [`N6:O${last}`]);
    sheet.tables.add(`A5:P${last}`, true, tableName).style = "TableStyleMedium2";
    sheet.getRange(`I6:I${last}`).setNumberFormat("yyyy-mm-dd hh:mm:ss");
    sheet.getRange("A:A").format.columnWidth = 8;
    sheet.getRange("B:B").format.columnWidth = 24;
    sheet.getRange("C:G").format.columnWidth = 13;
    sheet.getRange("H:H").format.columnWidth = 42;
    sheet.getRange("I:J").format.columnWidth = 20;
    sheet.getRange("K:L").format.columnWidth = 14;
    sheet.getRange("M:M").format.columnWidth = 36;
    sheet.getRange("N:O").format.columnWidth = 55;
    sheet.getRange("P:P").format.columnWidth = 19;
    sheet.getRange(`E6:E${last}`).conditionalFormats.add("containsText", { text: "失败", format: { fill: "#FDE9E7", font: { bold: true, color: "#C00000" } } });
    sheet.getRange(`E6:E${last}`).conditionalFormats.add("containsText", { text: "未知", format: { fill: "#FFF2CC", font: { color: "#7F6000" } } });
  };
  writeDetail(issueSheet, "失败及未入库任务", issues, "AcceptanceIssues");
  writeDetail(detailSheet, "全部文章采集明细", audits, "AcceptanceDetails");

  workbook.recalculate();
  const inspection = await workbook.inspect({ kind: "table", range: `验收汇总!A2:K${5 + summaryRows.length}`, include: "values,formulas", tableMaxRows: 30, tableMaxCols: 12, maxChars: 8000 });
  const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 }, summary: "final formula error scan" });
  if (/\"matches\"\s*:\s*\[[^\]]/.test(errors.ndjson || "")) throw new Error("验收工作簿存在公式错误");

  if (options.previewDir) {
    await fs.mkdir(options.previewDir, { recursive: true });
    for (const [sheetName, range] of [["验收汇总", `A1:K${Math.min(35, 5 + summaryRows.length)}`], ["失败及未入库", `A1:P${Math.min(30, 6 + issues.length)}`], ["全部明细", `A1:P${Math.min(30, 6 + audits.length)}`]]) {
      const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
      await fs.writeFile(path.join(options.previewDir, `${sheetName}.png`), new Uint8Array(await preview.arrayBuffer()));
    }
  }
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await fs.mkdir(path.dirname(path.resolve(outputFile)), { recursive: true });
  await output.save(path.resolve(outputFile));
  return { outputFile: path.resolve(outputFile), keywords: summaryRows.length, auditRows: audits.length, issueRows: issues.length, inspection: inspection.ndjson };
}

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    if (!argv[i].startsWith("--")) continue;
    const key = argv[i].slice(2);
    const next = argv[i + 1];
    args[key] = !next || next.startsWith("--") ? true : next;
    if (args[key] !== true) i += 1;
  }
  return args;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const args = parseArgs(process.argv);
  const root = path.resolve(String(args["output-dir"] || "batch-data"));
  const file = path.resolve(String(args.output || path.join(root, "批量关键词爬虫任务验收表.xlsx")));
  console.log(JSON.stringify(await buildAcceptanceWorkbook(root, file, { previewDir: args["preview-dir"] ? path.resolve(String(args["preview-dir"])) : null }), null, 2));
}
