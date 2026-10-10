import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { redisSettings, connectRedis } from "./redis-connection.mjs";
import { loadTaskManifest } from "./redis-task-manifest.mjs";

function argsOf(argv) {
  const out = {};
  for (let index = 2; index < argv.length; index += 1) {
    if (!argv[index].startsWith("--")) continue;
    const key = argv[index].slice(2), next = argv[index + 1];
    out[key] = !next || next.startsWith("--") ? true : next;
    if (out[key] !== true) index += 1;
  }
  return out;
}

const cli = argsOf(process.argv);
if (!cli["keywords-file"]) throw new Error("缺少--keywords-file");
const commonRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const settings = await redisSettings(commonRoot);
const manifest = await loadTaskManifest(path.join(commonRoot, "tasks", "redis-tasks.json"));
const expectedCampaign = `${settings.campaign}-mysql-${manifest.manifestHash.slice(0, 16)}`;
const campaign = String(cli.campaign || expectedCampaign);
if (campaign !== expectedCampaign) throw new Error(`campaign不匹配：${campaign}；预期${expectedCampaign}`);

const keywordSource = JSON.parse(await fs.readFile(path.resolve(String(cli["keywords-file"])), "utf8"));
const keywords = [...new Set(Array.isArray(keywordSource) ? keywordSource : keywordSource.keywords || [])].map(String);
if (!keywords.length) throw new Error("关键词清单为空");
const selected = manifest.tasks.filter((task) => keywords.includes(task.keyword));
const missing = keywords.filter((keyword) => !selected.some((task) => task.keyword === keyword));
if (missing.length) throw new Error(`任务清单缺少关键词：${missing.join("、")}`);

const prefix = `xhs:{${campaign}}:`;
const keys = {
  payloads: `${prefix}payloads`, statuses: `${prefix}statuses`, attempts: `${prefix}attempts`,
  tokens: `${prefix}tokens`, owners: `${prefix}owners`, pending: `${prefix}pending`,
  leases: `${prefix}leases`, results: `${prefix}results`, errors: `${prefix}errors`, failed: `${prefix}failed`
};
const client = await connectRedis(settings);
try {
  const inspectScript = `
local rows = {}
for _, id in ipairs(ARGV) do
  table.insert(rows, {
    redisTaskId = id,
    status = redis.call('HGET', KEYS[1], id) or cjson.null,
    attempts = tonumber(redis.call('HGET', KEYS[2], id)) or 0,
    owner = redis.call('HGET', KEYS[3], id) or cjson.null,
    pendingScore = tonumber(redis.call('ZSCORE', KEYS[4], id)) or cjson.null,
    leaseScore = tonumber(redis.call('ZSCORE', KEYS[5], id)) or cjson.null
  })
end
return cjson.encode(rows)
`;
  const inspect = async () => {
    const raw = await client.eval(inspectScript, {
      keys: [keys.statuses, keys.attempts, keys.owners, keys.pending, keys.leases],
      arguments: selected.map((task) => task.redisTaskId)
    });
    const state = new Map(JSON.parse(raw).map((item) => [item.redisTaskId, item]));
    return selected.map((task) => ({
      sequence: task.sequence, taskId: task.id, redisTaskId: task.redisTaskId, keyword: task.keyword,
      ...state.get(task.redisTaskId)
    }));
  };
  const before = await inspect();
  if (!cli.commit) {
    console.log(JSON.stringify({ committed: false, campaign, selected: before.length, tasks: before }, null, 2));
    process.exit(0);
  }

  const resetScript = `
for index = 1, #ARGV, 2 do
  local id = ARGV[index]
  if redis.call('HGET', KEYS[1], id) == 'leased' or redis.call('ZSCORE', KEYS[7], id) then
    return redis.error_reply('ACTIVE_LEASE ' .. id)
  end
  if not redis.call('HEXISTS', KEYS[10], id) then
    return redis.error_reply('MISSING_PAYLOAD ' .. id)
  end
end
for index = 1, #ARGV, 2 do
  local id = ARGV[index]
  local priority = ARGV[index + 1]
  redis.call('HSET', KEYS[1], id, 'pending')
  redis.call('HSET', KEYS[2], id, 0)
  redis.call('HDEL', KEYS[3], id)
  redis.call('HDEL', KEYS[4], id)
  redis.call('HDEL', KEYS[8], id)
  redis.call('HDEL', KEYS[9], id)
  redis.call('ZADD', KEYS[5], priority, id)
  redis.call('ZREM', KEYS[6], id)
  redis.call('ZREM', KEYS[7], id)
end
return #ARGV / 2
`;
  const resetCount = Number(await client.eval(resetScript, {
    keys: [keys.statuses, keys.attempts, keys.tokens, keys.owners, keys.pending, keys.failed, keys.leases, keys.results, keys.errors, keys.payloads],
    arguments: selected.flatMap((task) => [task.redisTaskId, String(task.sequence)])
  }));
  const after = await inspect();
  console.log(JSON.stringify({ committed: true, campaign, resetCount, before, after }, null, 2));
} finally {
  await client.close();
}
