import fs from "node:fs/promises";
import { createClient } from "redis";

const campaigns = process.argv.slice(2).filter(Boolean);
if (!campaigns.length) throw new Error("至少需要一个明确的campaign名称");
if (!process.env.REDIS_PASSWORD) throw new Error("缺少REDIS_PASSWORD进程环境变量");
const config = JSON.parse(await fs.readFile(new URL("../redis-config.json", import.meta.url), "utf8"));
const client = createClient({ url: config.url, username: config.username, password: process.env.REDIS_PASSWORD });
const hashNames = ["payloads", "statuses", "attempts", "tokens", "owners", "results", "errors"];
const zsetNames = ["pending", "leases", "failed"];
const clearScript = `
local removed = 0
for keyIndex = 1, 7 do
  removed = removed + redis.call('HDEL', KEYS[keyIndex], unpack(ARGV))
end
for keyIndex = 8, 10 do
  removed = removed + redis.call('ZREM', KEYS[keyIndex], unpack(ARGV))
end
return removed
`;

await client.connect();
const report = [];
try {
  for (const campaign of campaigns) {
    if (!/^xhs-[A-Za-z0-9_-]+$/u.test(campaign)) throw new Error(`非法campaign：${campaign}`);
    const prefix = `xhs:{${campaign}}:`;
    const payloads = await client.hVals(`${prefix}payloads`);
    const ids = [...new Set(payloads.map((value) => {
      try {
        const payload = JSON.parse(value);
        return String(payload.redisTaskId || payload.id || "");
      } catch { return ""; }
    }).filter(Boolean))];
    let removedMembers = 0;
    for (let offset = 0; offset < ids.length; offset += 100) {
      removedMembers += Number(await client.eval(clearScript, {
        keys: [...hashNames, ...zsetNames].map((name) => `${prefix}${name}`),
        arguments: ids.slice(offset, offset + 100)
      }));
    }
    const remaining = {};
    for (const name of hashNames) remaining[name] = await client.hLen(`${prefix}${name}`);
    for (const name of zsetNames) remaining[name] = await client.zCount(`${prefix}${name}`, "-inf", "+inf");
    report.push({ campaign, taskIds: ids.length, removedMembers, remainingMembers: Object.values(remaining).reduce((sum, value) => sum + Number(value), 0) });
  }
} finally {
  await client.quit();
}
console.log(JSON.stringify(report, null, 2));
