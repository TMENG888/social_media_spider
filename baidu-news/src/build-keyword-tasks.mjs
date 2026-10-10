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
  throw new Error("未找到Excel组件，请设置 ARTIFACT_TOOL_MODULE");
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

function priority(stage) {
  if (stage === "首轮") return "高";
  if (stage === "模块补查") return "中";
  return "低";
}

export async function buildKeywordTaskWorkbook(sourceFile, outputFile, options = {}) {
  const { FileBlob, SpreadsheetFile, Workbook } = await loadArtifactTool();
  const source = await SpreadsheetFile.importXlsx(await FileBlob.load(path.resolve(sourceFile)));
  const sourceSheet = source.worksheets.getItem("检索关键词");
  const values = sourceSheet.getRange("A5:H5000").values;
  const sourceRows = values.slice(1).filter((row) => String(row[3] || "").trim() && String(row[5] || "").includes("公开网页"));
  const seen = new Set();
  const rows = sourceRows.filter((row) => {
    const keyword = String(row[3]).trim();
    if (seen.has(keyword)) return false;
    seen.add(keyword);
    return true;
  }).map((row) => [
    `BDZX-${row[0]}`, row[0], "百度资讯", String(row[3]).trim(), row[1], row[2], row[4], row[5], row[6],
    "是", priority(row[4]), "待执行", new Date("2026-01-01T00:00:00+08:00"), null, 10, 20, 200,
    null, 0, 0, null, row[7]
  ]);

  const headers = ["检索词任务ID", "原关键词ID", "渠道", "完整检索词", "集团／主体", "检索方向", "使用阶段", "原适用渠道", "原确认状态", "是否启用", "优先级", "执行状态", "开始日期", "结束日期", "每批条数", "最大页数", "最大文章数", "最近执行时间", "成功文章数", "失败文章数", "完成原因", "备注"];
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add("检索词任务");
  const guide = workbook.worksheets.add("使用说明");
  sheet.tabColor = "#1F4E78";
  guide.tabColor = "#7F8C8D";
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(5);
  sheet.freezePanes.freezeColumns(4);
  sheet.getRange("A2").values = [["百度资讯检索词任务表"]];
  sheet.getRange("A2").format.font = { name: "Arial", size: 15, bold: true, color: "#1F2937" };
  sheet.getRange("A3").values = [[`来源：专题一 四品牌住宅产品采集确认表；共${rows.length}个公开网页检索词。黄色列可在执行前调整。`]];
  sheet.getRange("A3").format.font = { name: "Arial", size: 10, color: "#6B7280" };
  sheet.getRange("A5:V5").values = [headers];
  sheet.getRangeByIndexes(5, 0, rows.length, headers.length).values = rows;
  const last = 5 + rows.length;
  sheet.getRange(`A2:V${last}`).format.font = { name: "Arial", size: 10, color: "#1F2937" };
  sheet.getRange("A2").format.font = { name: "Arial", size: 15, bold: true, color: "#1F2937" };
  sheet.getRange("A5:V5").format = { fill: "#1F4E78", font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { preset: "inside", style: "thin", color: "#FFFFFF" } };
  sheet.getRange(`J6:Q${last}`).format.fill = "#FFF2CC";
  sheet.getRange(`M6:N${last}`).setNumberFormat("yyyy-mm-dd");
  sheet.getRange(`R6:R${last}`).setNumberFormat("yyyy-mm-dd hh:mm:ss");
  sheet.getRange(`J6:J${last}`).dataValidation = { rule: { type: "list", values: ["是", "否"] } };
  sheet.getRange(`K6:K${last}`).dataValidation = { rule: { type: "list", values: ["高", "中", "低"] } };
  sheet.getRange(`L6:L${last}`).dataValidation = { rule: { type: "list", values: ["待执行", "执行中", "已完成", "失败", "暂停"] } };
  sheet.tables.add(`A5:V${last}`, true, "BaiduKeywordTasks").style = "TableStyleMedium2";
  for (const [range, width] of [["A:B", 17], ["C:C", 12], ["D:D", 30], ["E:G", 20], ["H:H", 34], ["I:L", 13], ["M:N", 14], ["O:Q", 11], ["R:R", 20], ["S:T", 12], ["U:U", 28], ["V:V", 60]]) sheet.getRange(range).format.columnWidth = width;
  sheet.getRange(`L6:L${last}`).conditionalFormats.add("containsText", { text: "失败", format: { fill: "#FDE9E7", font: { bold: true, color: "#C00000" } } });

  guide.showGridLines = false;
  guide.getRange("A2").values = [["使用说明"]];
  guide.getRange("A2").format.font = { name: "Arial", size: 15, bold: true, color: "#1F2937" };
  guide.getRange("A4:B10").values = [
    ["项目", "说明"],
    ["是否启用", "只有“是”的任务会进入批量采集。"],
    ["执行状态", "默认执行“待执行、失败、暂停”；“已完成”默认跳过。"],
    ["结束日期", "留空时使用运行当天的北京时间。"],
    ["单关键词", "启动BAT后选择单关键词模式，直接输入检索词。"],
    ["批量关键词", "启动BAT后选择任务表模式，输入本文件完整路径。"],
    ["失败续爬", "选择断点续爬模式并输入上次输出目录，只重试失败、字段不完整和日期未知任务。"]
  ];
  guide.getRange("A4:B4").format = { fill: "#1F4E78", font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center" };
  guide.getRange("A4:B10").format.font = { name: "Arial", size: 10, color: "#1F2937" };
  guide.getRange("A:A").format.columnWidth = 20;
  guide.getRange("B:B").format.columnWidth = 75;
  guide.getRange("B5:B10").format.wrapText = true;
  guide.tables.add("A4:B10", true, "KeywordTaskGuide").style = "TableStyleMedium2";

  workbook.recalculate();
  const inspection = await workbook.inspect({ kind: "table", range: "检索词任务!A2:V12", include: "values,formulas", tableMaxRows: 12, tableMaxCols: 22, maxChars: 12000 });
  const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 } });
  if (!/matched 0 entries/.test(errors.ndjson || "")) throw new Error("检索词任务表存在公式错误");
  if (options.previewDir) {
    await fs.mkdir(options.previewDir, { recursive: true });
    for (const [name, range] of [["检索词任务", "A1:V20"], ["使用说明", "A1:B11"]]) {
      const preview = await workbook.render({ sheetName: name, range, scale: 1, format: "png" });
      await fs.writeFile(path.join(options.previewDir, `${name}.png`), new Uint8Array(await preview.arrayBuffer()));
    }
  }
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await fs.mkdir(path.dirname(path.resolve(outputFile)), { recursive: true });
  await output.save(path.resolve(outputFile));
  return { outputFile: path.resolve(outputFile), tasks: rows.length, inspection: inspection.ndjson };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const args = parseArgs(process.argv);
  if (!args.source) throw new Error("缺少 --source 确认表路径");
  const output = args.output || "百度资讯_检索词任务表.xlsx";
  console.log(JSON.stringify(await buildKeywordTaskWorkbook(String(args.source), String(output), { previewDir: args["preview-dir"] ? path.resolve(String(args["preview-dir"])) : null }), null, 2));
}
