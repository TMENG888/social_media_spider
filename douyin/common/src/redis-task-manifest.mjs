import fs from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
import { POLICY_VERSION, projectForTopic, validDate } from "./collection-policy.mjs";

export const MANIFEST_VERSION = "douyin-redis-task-manifest-v1";
export const COLLECTOR_CONFIG_KEYS = Object.freeze([
  "maxNotesPerKeyword", "maxSearchScrolls", "maxCommentScrolls", "maxStagnantRounds",
  "navigationTimeoutMs", "loginWaitSeconds", "headless", "visitAuthorProfile",
  "actionDelayMs", "detailDelayMs", "keywordDelayMs", "batchSize", "batchCooldownMs",
  "maxConsecutiveFailures", "asrEnabled", "asrModel", "asrDevice", "asrComputeType",
  "asrCpuThreads", "asrBeamSize", "asrLanguage", "asrStartupTimeoutMs",
  "asrDownloadTimeoutMs", "asrTranscriptionTimeoutMs", "asrKeepMedia",
  "category", "projectName", "cutoff", "minPublishedDate", "collectAllCurrentYear",
  "collectComments", "searchStopWindow", "importBatchSize"
]);
const DEFAULTS = Object.freeze({
  maxNotesPerKeyword: 3, maxSearchScrolls: 0, maxCommentScrolls: 8, maxStagnantRounds: 15,
  navigationTimeoutMs: 45000, loginWaitSeconds: 300, headless: false, visitAuthorProfile: true,
  actionDelayMs: [1500, 3000], detailDelayMs: [3000, 6000], keywordDelayMs: [8000, 15000],
  batchSize: 8, batchCooldownMs: [45000, 90000], maxConsecutiveFailures: 3,
  asrEnabled: true, asrModel: "small", asrDevice: "cpu", asrComputeType: "int8",
  asrCpuThreads: 4, asrBeamSize: 1, asrLanguage: "zh", asrStartupTimeoutMs: 900000,
  asrDownloadTimeoutMs: 600000, asrTranscriptionTimeoutMs: 1800000, asrKeepMedia: false,
  category: null, collectAllCurrentYear: true, searchStopWindow: 8, importBatchSize: 20
});
const hash = value => createHash("sha256").update(canonicalJson(value)).digest("hex");
export function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
  if (typeof value === "number" && !Number.isFinite(value)) throw new Error("任务配置包含非有限数值");
  const encoded = JSON.stringify(value);
  if (encoded === undefined) throw new Error("任务配置包含无法序列化的值");
  return encoded;
}
const present = value => value !== undefined && value !== null && value !== "";
const first = (...values) => values.find(present);
function flag(value, name) {
  if (value === true || value === "true") return true;
  if (value === false || value === "false") return false;
  throw new Error(`任务配置${name}必须是布尔值`);
}
function integer(value, name, minimum = 1) {
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < minimum) throw new Error(`任务配置${name}必须是大于等于${minimum}的整数`);
  return parsed;
}
function selectedConfig(source) {
  return Object.fromEntries(COLLECTOR_CONFIG_KEYS.filter(key => Object.hasOwn(source, key) && source[key] !== undefined).map(key => [key, structuredClone(source[key])]));
}

/** Merge portable collection settings. Paths and credentials never enter payloads. */
export function normalizeTask(task, queueDefaults = {}, sharedDefaults = {}) {
  if (!task || typeof task !== "object") throw new Error("任务必须是对象");
  const topic = String(task.topic || "").trim();
  if (!["专题一", "专题二"].includes(topic)) throw new Error(`未知专题：${topic}`);
  const keyword = String(task.keyword || "").trim();
  if (!keyword) throw new Error("任务检索词为空");
  const config = {
    ...structuredClone(DEFAULTS), ...selectedConfig(sharedDefaults),
    ...selectedConfig(queueDefaults), ...selectedConfig(queueDefaults.collectorConfig || {}),
    ...selectedConfig(task.collectorConfig || {}), ...selectedConfig(task)
  };
  // Match the existing runner's cutoff precedence; normalized payloads always
  // carry an explicit cutoff, so all workers execute the same date scope.
  const cutoff = String(first(task.cutoff, queueDefaults.cutoff, task.minPublishedDate,
    queueDefaults.minPublishedDate, config.cutoff, config.minPublishedDate, "2026-01-01"));
  if (validDate(cutoff) !== cutoff) throw new Error(`任务截止起点格式无效：${cutoff}`);
  const projectName = projectForTopic(topic);
  const collectComments = topic === "专题二";
  const maxNotes = integer(first(task.maxNotes, queueDefaults.maxNotes, config.maxNotesPerKeyword, 3), "maxNotes");
  const maxSearchScrolls = integer(config.maxSearchScrolls, "maxSearchScrolls", 0);
  const collectAllCurrentYear = flag(config.collectAllCurrentYear, "collectAllCurrentYear");
  const searchStopWindow = integer(config.searchStopWindow, "searchStopWindow");
  const importBatchSize = integer(config.importBatchSize, "importBatchSize");
  const transitionDelaySeconds = Number(first(task.transitionDelaySeconds, queueDefaults.transitionDelaySeconds, 0));
  if (!Number.isFinite(transitionDelaySeconds) || transitionDelaySeconds < 0) throw new Error("切词等待秒数无效");
  const sequence = present(task.sequence) ? integer(task.sequence, "sequence") : null;
  for (const name of ["headless", "visitAuthorProfile", "asrEnabled", "asrKeepMedia"]) config[name] = flag(config[name], name);
  if (/^(?:[a-zA-Z]:[\\/]|[\\/])/.test(String(config.asrModel))) throw new Error("共享任务asrModel不能使用本机绝对路径");
  Object.assign(config, { projectName, collectComments, cutoff, minPublishedDate: cutoff,
    maxNotesPerKeyword: maxNotes, maxSearchScrolls, collectAllCurrentYear, searchStopWindow, importBatchSize });
  const redisTaskId = `dy-${hash({ topic, keyword, cutoff })}`;
  const payload = {
    topic, keyword, cutoff, minPublishedDate: cutoff, projectName, category: config.category,
    enabled: true, maxNotes, maxSearchScrolls, collectAllCurrentYear, collectComments,
    searchStopWindow, importBatchSize, transitionDelaySeconds, sequence, policyVersion: POLICY_VERSION,
    collectorConfig: config
  };
  return { id: String(task.id || redisTaskId), redisTaskId, payloadHash: hash(payload), ...payload };
}

export function buildTaskManifest(queues, sharedDefaults = {}) {
  if (!Array.isArray(queues)) throw new Error("任务队列必须是数组");
  const tasks = [], seen = new Map();
  for (const queue of queues) {
    for (const source of queue.tasks || []) {
      if (source.enabled === false || source.enabled === "false") continue;
      const task = normalizeTask(source, queue, sharedDefaults);
      if (seen.has(task.redisTaskId)) {
        const conflict = seen.get(task.redisTaskId).payloadHash !== task.payloadHash;
        throw new Error(`${conflict ? "配置冲突" : "重复任务"}：${task.topic} / ${task.keyword} / ${task.cutoff}`);
      }
      seen.set(task.redisTaskId, task);
      tasks.push(task);
    }
  }
  const sequenced = tasks.some(task => task.sequence != null);
  if (sequenced) {
    if (tasks.some(task => task.sequence == null) || new Set(tasks.map(task => task.sequence)).size !== tasks.length) throw new Error("任务sequence必须全部存在且唯一");
    tasks.sort((a, b) => a.sequence - b.sequence);
  } else tasks.sort((a, b) => a.redisTaskId < b.redisTaskId ? -1 : a.redisTaskId > b.redisTaskId ? 1 : 0);
  const topicCounts = Object.fromEntries(["专题一", "专题二"].map(topic => [topic, tasks.filter(task => task.topic === topic).length]));
  const manifestHash = hash({ schemaVersion: MANIFEST_VERSION, policyVersion: POLICY_VERSION,
    tasks: tasks.map(({ redisTaskId, payloadHash }) => ({ redisTaskId, payloadHash })) });
  return { schemaVersion: MANIFEST_VERSION, policyVersion: POLICY_VERSION, manifestHash, taskCount: tasks.length, topicCounts, tasks };
}

export async function loadWorkerTaskManifest(packageRoot) {
  const root = path.resolve(packageRoot);
  const commonConfig = JSON.parse((await fs.readFile(path.join(root, "common", "config.json"), "utf8")).replace(/^\uFEFF/, ""));
  const queues = await Promise.all([1, 2, 3, 4, 5].map(async worker => JSON.parse((await fs.readFile(path.join(root, `worker-0${worker}`, "tasks", "task-queue.json"), "utf8")).replace(/^\uFEFF/, ""))));
  // The original master list was distributed round-robin across five workers.
  // Zip the shards back together so Redis claims follow the requirement-sheet order.
  const merged = [], maxLength = Math.max(...queues.map(queue => queue.tasks?.length || 0));
  for (let row = 0; row < maxLength; row += 1) for (const queue of queues) {
    const task = queue.tasks?.[row];
    if (task) merged.push({ ...task, sequence: merged.length + 1 });
  }
  const defaults = Object.fromEntries(Object.entries(queues[0]).filter(([key]) => key !== "tasks"));
  return buildTaskManifest([{ ...defaults, tasks: merged }], commonConfig);
}

export async function loadTaskManifest(file) {
  const source = JSON.parse((await fs.readFile(path.resolve(file), "utf8")).replace(/^\uFEFF/, ""));
  if (source.schemaVersion !== MANIFEST_VERSION || source.policyVersion !== POLICY_VERSION) throw new Error("Redis任务清单版本不匹配");
  if (!Array.isArray(source.tasks) || source.tasks.some(task => task.enabled === false || task.enabled === "false")) throw new Error("Redis任务清单格式不完整");
  const verified = buildTaskManifest([{ tasks: source.tasks }]);
  const originals = new Map(source.tasks.map(task => [task.redisTaskId, task]));
  for (const task of verified.tasks) {
    const original = originals.get(task.redisTaskId);
    if (!original || original.payloadHash !== task.payloadHash) throw new Error(`Redis任务payloadHash不匹配：${task.keyword}`);
  }
  if (verified.manifestHash !== source.manifestHash || verified.taskCount !== source.taskCount || canonicalJson(verified.topicCounts) !== canonicalJson(source.topicCounts)) throw new Error("Redis任务清单manifestHash或任务统计不匹配");
  return verified;
}

