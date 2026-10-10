import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { readKeywordTasks } from "./read-keyword-tasks.mjs";

function parseArgs(argv) {
  const args = {};
  for (let index = 2; index < argv.length; index += 1) {
    if (!argv[index].startsWith("--")) continue;
    const key = argv[index].slice(2);
    const value = argv[index + 1];
    args[key] = !value || value.startsWith("--") ? true : value;
    if (args[key] !== true) index += 1;
  }
  return args;
}

function shanghaiDateTime() {
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Shanghai", dateStyle: "short", timeStyle: "medium", hourCycle: "h23"
  }).format(new Date());
}

function normalizeKeyword(value) {
  return String(value || "").normalize("NFKC").replace(/\s+/g, " ").trim().toLowerCase();
}

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

const args = parseArgs(process.argv);
const source = path.resolve(String(args.source || "百度资讯_检索词任务表.xlsx"));
const outputDir = path.resolve(String(args["output-dir"] || "检索词任务"));
const workerCount = Number(args.workers || 5);
if (!Number.isInteger(workerCount) || workerCount < 1 || workerCount > 100) throw new Error("设备数量必须是1到100之间的整数");

const tasks = (await readKeywordTasks(source)).sort((left, right) => left.id.localeCompare(right.id, "zh-CN", { numeric: true }) || left.keyword.localeCompare(right.keyword, "zh-CN"));
const uniqueIds = new Set(tasks.map((task) => task.id));
const uniqueKeywords = new Set(tasks.map((task) => normalizeKeyword(task.keyword)));
if (uniqueIds.size !== tasks.length) throw new Error("检索词任务ID存在重复，已停止分配");
if (uniqueKeywords.size !== tasks.length) throw new Error("完整检索词存在重复，已停止分配");

const assignments = Array.from({ length: workerCount }, () => []);
tasks.forEach((task, index) => assignments[index % workerCount].push({
  id: task.id,
  channel: "百度资讯",
  keyword: task.keyword,
  enabled: true,
  status: "待执行",
  startDate: task.startDate || "2026-01-01",
  endDate: task.endDate || null,
  batchSize: task.batchSize || 10,
  maxPages: task.maxPages || 20,
  maxItems: task.maxItems || 200
}));

await fs.mkdir(outputDir, { recursive: true });
const generatedAt = shanghaiDateTime();
const files = [];
for (let index = 0; index < assignments.length; index += 1) {
  const workerId = `worker-${String(index + 1).padStart(2, "0")}`;
  const filename = `设备${String(index + 1).padStart(2, "0")}_百度资讯检索词任务.json`;
  const payload = {
    schemaVersion: "1.0",
    workerId,
    deviceNumber: index + 1,
    sourceTaskFile: path.basename(source),
    generatedAt,
    timezone: "Asia/Shanghai",
    taskCount: assignments[index].length,
    keywords: assignments[index]
  };
  const content = `${JSON.stringify(payload, null, 2)}\n`;
  await fs.writeFile(path.join(outputDir, filename), content, "utf8");
  files.push({ workerId, deviceNumber: index + 1, filename, taskCount: assignments[index].length, sha256: sha256(content), taskIds: assignments[index].map((task) => task.id) });
}

const assignedIds = files.flatMap((file) => file.taskIds);
if (assignedIds.length !== tasks.length || new Set(assignedIds).size !== tasks.length || tasks.some((task) => !assignedIds.includes(task.id))) {
  throw new Error("分配校验失败：存在遗漏或重复任务");
}

const manifest = {
  schemaVersion: "1.0",
  sourceTaskFile: path.basename(source),
  generatedAt,
  timezone: "Asia/Shanghai",
  allocationMethod: "按任务ID稳定排序后轮转分配",
  workerCount,
  sourceTaskCount: tasks.length,
  assignedTaskCount: assignedIds.length,
  uniqueTaskIdCount: new Set(assignedIds).size,
  uniqueKeywordCount: uniqueKeywords.size,
  missingTaskCount: 0,
  duplicateAssignmentCount: 0,
  workers: files
};
await fs.writeFile(path.join(outputDir, "5台设备_任务分配总表.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");

console.log(JSON.stringify({ outputDir, sourceTaskCount: tasks.length, workerCounts: files.map((file) => file.taskCount), missingTaskCount: 0, duplicateAssignmentCount: 0, files: files.map((file) => file.filename) }, null, 2));
