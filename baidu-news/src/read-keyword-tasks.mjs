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

export async function readKeywordTasks(file) {
  const { FileBlob, SpreadsheetFile } = await loadArtifactTool();
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(path.resolve(file)));
  const sheet = workbook.worksheets.getItem("检索词任务");
  const values = sheet.getUsedRange(true).values;
  const headerIndex = values.findIndex((row) => row.includes("检索词任务ID") && row.includes("完整检索词"));
  if (headerIndex < 0) throw new Error("任务表未找到‘检索词任务ID/完整检索词’表头");
  const headers = values[headerIndex].map((value) => String(value || "").trim());
  const index = Object.fromEntries(headers.map((name, i) => [name, i]));
  const normalizeDate = (value) => {
    if (!value) return null;
    if (value instanceof Date) return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(value);
    if (typeof value === "number" && Number.isFinite(value)) {
      const date = new Date(Date.UTC(1899, 11, 30) + Math.round(value * 86400000));
      return date.toISOString().slice(0, 10);
    }
    const match = String(value).match(/20\d{2}-\d{2}-\d{2}/);
    return match?.[0] || null;
  };
  return values.slice(headerIndex + 1).filter((row) => {
    const keyword = String(row[index["完整检索词"]] || "").trim();
    const enabled = String(row[index["是否启用"]] || "是").trim();
    const status = String(row[index["执行状态"]] || "待执行").trim();
    const channel = String(row[index["渠道"]] || "百度资讯").trim();
    return keyword && enabled !== "否" && channel === "百度资讯" && status !== "已完成";
  }).map((row) => ({
    id: String(row[index["检索词任务ID"]] || "").trim(),
    keyword: String(row[index["完整检索词"]]).trim(),
    startDate: normalizeDate(row[index["开始日期"]]),
    endDate: normalizeDate(row[index["结束日期"]]),
    batchSize: Number(row[index["每批条数"]]) || null,
    maxPages: Number(row[index["最大页数"]]) || null,
    maxItems: Number(row[index["最大文章数"]]) || null
  }));
}
