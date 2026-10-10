import fs from 'node:fs/promises';
import path from 'node:path';
import { createClient } from 'redis';

export async function redisSettings(root, env = process.env) {
  let config = {};
  try { config = JSON.parse(await fs.readFile(path.join(root, 'redis-config.json'), 'utf8')); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  const url = String(env.REDIS_URL || config.url || '');
  if (!url) throw new Error('请先配置 REDIS_URL 或 common/redis-config.json 的 url（redis://主机:端口/库号）');
  let parsed;
  try { parsed = new URL(url); } catch { throw new Error('Redis URL格式错误（请勿把密码写入URL）'); }
  if (!['redis:', 'rediss:'].includes(parsed.protocol) || parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error('Redis 地址仅允许 redis:// 或 rediss://，不得在 URL 中保存用户名或密码；请使用隐藏输入');
  }
  const campaign = String(env.XHS_REDIS_RUN_ID || config.campaign || '');
  if (!/^[A-Za-z0-9_-]{1,100}$/.test(campaign)) throw new Error('Redis campaign 必须为1至100位字母、数字、横线或下划线，五机必须一致');
  const leaseMs = Number(config.leaseMs ?? 300000);
  const heartbeatMs = Number(config.heartbeatMs ?? 30000);
  const commandTimeoutMs = Number(config.commandTimeoutMs ?? 10000);
  const heartbeatRetryMs = Number(config.heartbeatRetryMs ?? 5000);
  const leaseSafetyMs = Number(config.leaseSafetyMs ?? 20000);
  if (!Number.isSafeInteger(leaseMs) || leaseMs < 60000 || !Number.isSafeInteger(heartbeatMs) || heartbeatMs < 1000 ||
      heartbeatMs > leaseMs / 4 || !Number.isSafeInteger(commandTimeoutMs) || commandTimeoutMs < 1000 || commandTimeoutMs > leaseMs / 4 ||
      !Number.isSafeInteger(heartbeatRetryMs) || heartbeatRetryMs < 500 || heartbeatRetryMs > leaseMs / 4 ||
      !Number.isSafeInteger(leaseSafetyMs) || leaseSafetyMs < commandTimeoutMs || leaseSafetyMs > leaseMs / 2) {
    throw new Error('Redis 租约/心跳/超时配置无效（默认300秒/30秒/10秒）');
  }
  return { url, username: env.REDIS_USERNAME || config.username || undefined,
    password: env.REDIS_PASSWORD || undefined, campaign, leaseMs, heartbeatMs, commandTimeoutMs,
    heartbeatRetryMs, leaseSafetyMs,
    maxAttempts: Number(config.maxAttempts ?? 3), retryDelayMs: Number(config.retryDelayMs ?? 60000),
    taskPoolCampaign: config.taskPoolCampaign || null };
}

// Commands are never queued offline. A later explicit call may reconnect, but every
// state-changing operation is still protected by the server-side lease token.
export async function connectRedis(settings) {
  let raw = null, connecting = null, closed = false;
  const createRaw = () => {
    const client = createClient({ RESP: 2, url: settings.url, username: settings.username, password: settings.password,
      disableOfflineQueue: true, socket: { connectTimeout: settings.commandTimeoutMs, reconnectStrategy: false } });
    client.on('error', () => {}); // Awaited calls handle errors; never print credential-bearing URLs.
    return client;
  };
  async function bounded(client, call) {
    let timer;
    try {
      return await Promise.race([call(), new Promise((_, reject) => {
        timer = setTimeout(() => {
          if (client.isOpen) client.destroy();
          const error = new Error('REDIS_TIMEOUT：Redis命令超时');
          error.code = 'REDIS_TIMEOUT';
          reject(error);
        }, settings.commandTimeoutMs);
      })]);
    } finally { clearTimeout(timer); }
  }
  async function ensureConnected() {
    if (closed) throw Object.assign(new Error('Redis client is closed'), { code: 'REDIS_CLIENT_CLOSED' });
    if (raw?.isReady) return raw;
    if (connecting) return connecting;
    const client = createRaw();
    raw = client;
    connecting = bounded(client, () => client.connect()).then(() => client).catch((error) => {
      if (client.isOpen) client.destroy();
      if (raw === client) raw = null;
      throw error;
    }).finally(() => { connecting = null; });
    return connecting;
  }
  async function execute(operation) {
    const client = await ensureConnected();
    try { return await bounded(client, () => operation(client)); }
    catch (error) {
      if (!client.isReady || error.code === 'REDIS_TIMEOUT') {
        if (client.isOpen) client.destroy();
        if (raw === client) raw = null;
      }
      throw error;
    }
  }
  await ensureConnected();
  return { eval: (...args) => execute(client => client.eval(...args)), ping: () => execute(client => client.ping()),
    reconnect: async () => {
      if (raw?.isOpen) raw.destroy();
      raw = null;
      return ensureConnected();
    },
    close: async () => {
      closed = true;
      if (raw?.isOpen) raw.destroy();
      raw = null;
    } };
}
