import fs from 'node:fs/promises';
import { redisSettings, connectRedis } from './redis-connection.mjs';
import { RedisTaskQueue } from './redis-task-queue.mjs';

export async function assertLocalLease(env = process.env) {
  if (env.XHS_DISPATCH !== 'redis') return;
  let lease;
  try { lease = JSON.parse(await fs.readFile(env.XHS_LEASE_FILE, 'utf8')); } catch {}
  if (!lease || lease.token !== env.XHS_LEASE_TOKEN || lease.taskId !== env.XHS_LEASE_TASK_ID ||
      lease.active !== true || !Number.isFinite(lease.validUntil) || lease.validUntil <= Date.now()) {
    throw Object.assign(new Error('STOP_LEASE_LOST：任务租约失效，数据留在本地，禁止旧节点继续采集或入库'), { code: 'LEASE_LOST' });
  }
}

export async function withImportLease(callback, env = process.env) {
  if (env.XHS_DISPATCH !== 'redis') return callback(async () => {});
  await assertLocalLease(env);
  const settings = await redisSettings(env.XHS_WORKER_ROOT || '.', env);
  const client = await connectRedis(settings);
  try {
    const queue = new RedisTaskQueue({ client, campaign: env.XHS_LEASE_CAMPAIGN, leaseMs: settings.leaseMs });
    const verify = async () => {
      await assertLocalLease(env);
      await queue.assertLease(env.XHS_LEASE_TASK_ID, env.XHS_LEASE_TOKEN);
    };
    await verify();
    return await callback(verify);
  }
  finally { await client.close(); }
}
