import fs from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { RedisTaskQueue } from './redis-task-queue.mjs';
import { redisSettings, connectRedis } from './redis-connection.mjs';
import { loadTaskManifest } from './redis-task-manifest.mjs';
import { writeJsonAtomic } from './checkpoint.mjs';

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

export class RedisDispatcher {
  static async open({ root, stateRoot, workerId, skipImport, stopFile, manifestOverride = null, campaignOverride = null }) {
    const settings = await redisSettings(root);
    const manifest = manifestOverride || await loadTaskManifest(path.join(root, 'tasks', 'redis-tasks.json'));
    const client = await connectRedis(settings);
    // Different task revisions and export-only tests cannot acknowledge production work.
    const campaign = campaignOverride || `${settings.campaign}-${skipImport ? 'export' : 'mysql'}-${manifest.manifestHash.slice(0, 16)}`;
    try {
      const dispatcher = new RedisDispatcher({ settings, manifest, client, campaign, stateRoot, workerId, stopFile });
      await client.ping();
      const published = await dispatcher.queue.publish(manifest.tasks);
      console.log(`[Redis预检] 通过；任务池=${campaign}，清单${manifest.taskCount}项，新增${published.added}项、已存在${published.existing}项`);
      await dispatcher.report();
      return dispatcher;
    } catch (error) { await client.close(); throw error; }
  }

  constructor({ settings, manifest, client, campaign, stateRoot, workerId, stopFile }) {
    Object.assign(this, { settings, manifest, client, campaign, stateRoot, workerId, stopFile });
    this.owner = `${workerId}-${randomUUID()}`;
    this.queue = new RedisTaskQueue({ client, campaign, leaseMs: settings.leaseMs, maxAttempts: settings.maxAttempts, retryDelayMs: settings.retryDelayMs });
    this.leaseFile = path.join(stateRoot, 'redis-active-lease.json');
    this.current = null;
    this.timer = null;
    this.heartbeat = null;
    this.verification = null;
    this.leaseWrites = Promise.resolve();
    this.lost = false;
    this.halted = false;
    this.lastStats = null;
    this.localLeaseValidUntil = 0;
  }

  async report() {
    this.lastStats = await this.queue.stats();
    const { pending, leased, completed, failed, total } = this.lastStats.counts;
    console.log(`[全局任务进度] ${completed}/${total}已完成；待领取${pending}，执行中${leased}，重试耗尽${failed}`);
    await writeJsonAtomic(path.join(this.stateRoot, 'redis_queue_status.json'), {
      campaign: this.campaign, checkedAt: new Date().toISOString(), ...this.lastStats });
    return this.lastStats;
  }

  async stopped() { return fs.access(this.stopFile).then(() => true).catch(() => false); }

  async *tasks({taskIds=null}={}) {
    let index = 0, lastReport = 0,targetIndex=0;
    if(taskIds&&(!Array.isArray(taskIds)||!taskIds.length||taskIds.some(id=>!this.manifest.tasks.some(t=>(t.redisTaskId||t.id)===id))))throw new Error('SELECTED_TASK_NOT_IN_MANIFEST');
    while (!this.halted && !await this.stopped()) {
      if(taskIds&&targetIndex>=taskIds.length)return;
      if (this.current) throw new Error('上一个Redis任务尚未确认，禁止领取新任务');
      const started = Date.now();
      const targetId=taskIds?.[targetIndex]||null;
      if(targetId){const target=await this.queue.inspect(targetId);if(target.status==='completed'){targetIndex++;continue;}if(target.status==='failed'||target.status==='missing')throw new Error(`SELECTED_TASK_UNAVAILABLE：${targetId}状态=${target.status}`);}
      const lease = await this.queue.claim(this.owner,targetId);
      if (!lease) {
        const stats = await this.queue.stats();
        this.lastStats = stats;
        if (!stats.counts.pending && !stats.counts.leased) { await this.report(); return; }
        if (Date.now() - lastReport > 60000) { await this.report(); lastReport = Date.now(); }
        await sleep(2000);
        continue;
      }
      this.current = lease;
      this.lost = false;
      await this.saveLease(started);
      this.scheduleHeartbeat();
      console.log(`[任务领取] ${this.workerId}：${lease.task.topic} / ${lease.task.keyword}，尝试${lease.attempt}/${this.settings.maxAttempts}`);
      yield [index++, lease.task];
      if(targetId){const target=await this.queue.inspect(targetId);if(target.status==='completed')targetIndex++;else return;} // A partial first task must not advance to topic two.
    }
  }

  env() {
    if (!this.current) return {};
    return { DY_DISPATCH: 'redis', DY_LEASE_FILE: this.leaseFile,
      DY_LEASE_TASK_ID: this.current.taskId, DY_LEASE_TOKEN: this.current.token, DY_LEASE_CAMPAIGN: this.campaign };
  }

  writeLease(value) {
    const write = this.leaseWrites.catch(() => {}).then(() =>
      writeJsonAtomic(this.leaseFile, value.active && this.lost ? { active: false, validUntil: 0 } : value));
    this.leaseWrites = write;
    return write;
  }

  async saveLease(started, lease = this.current) {
    const margin = Math.max(5000, this.settings.commandTimeoutMs * 2, this.settings.leaseSafetyMs || 0);
    this.localLeaseValidUntil = started + this.settings.leaseMs - margin;
    await this.writeLease({ taskId: lease.taskId, token: lease.token,
      active: true, validUntil: this.localLeaseValidUntil });
  }

  scheduleHeartbeat() {
    if (this.lost || this.halted || !this.current) return;
    this.timer = setTimeout(() => {
      this.heartbeat = this.verify().then(() => this.scheduleHeartbeat()).catch(error => this.markLost(error));
    }, this.settings.heartbeatMs);
  }

  async markLost(error) {
    if (this.lost) return;
    this.lost = true;
    clearTimeout(this.timer);
    await this.writeLease({ active: false, validUntil: 0 }).catch(() => {});
    await fs.writeFile(this.stopFile, 'Redis lease lost', 'utf8').catch(() => {});
    console.warn(`[Redis停止] 心跳或租约异常（${error.code || 'CONNECTION_ERROR'}），停止本节点；本地数据保留，不再确认任务`);
  }

  async verify() {
    if (this.lost || !this.current) throw Object.assign(new Error('STOP_LEASE_LOST：本节点已失去任务租约'), { code: 'LEASE_LOST' });
    if (this.verification) return this.verification;
    const lease = this.current;
    const operation = (async () => {
      let warned = false;
      while (true) {
        const started = Date.now();
        try {
          await this.queue.renew(lease.taskId, lease.token);
          if (this.lost || this.current !== lease) throw Object.assign(new Error('STOP_LEASE_LOST：租约已失效或被替换'), { code: 'LEASE_LOST' });
          await this.saveLease(started, lease);
          if (warned) console.log('[Redis心跳] 连接已恢复，租约续期成功');
          return;
        } catch (error) {
          const message = String(error.message || error);
          const fatal = error.code === 'LEASE_LOST' || error.code === 'REDIS_CLIENT_CLOSED' ||
            /\b(?:WRONGPASS|NOAUTH|NOPERM|TASK_PAYLOAD_CONFLICT)\b/u.test(message);
          const retryMs = this.settings.heartbeatRetryMs || 5000;
          const remaining = this.localLeaseValidUntil - Date.now();
          if (fatal || remaining <= retryMs + 1000) throw error;
          if (!warned) console.warn(`[Redis心跳] 暂时无法续期（${error.code || 'CONNECTION_ERROR'}），将在安全租约窗口内自动重连`);
          warned = true;
          await sleep(Math.min(retryMs, Math.max(500, remaining - 1000)));
        }
      }
    })();
    this.verification = operation;
    try {
      await operation;
    } catch (error) { await this.markLost(error); throw error; }
    finally { if (this.verification === operation) this.verification = null; }
  }

  async finish(kind, result) {
    clearTimeout(this.timer);
    await this.heartbeat;
    clearTimeout(this.timer);
    if (!this.current) return;
    if (this.lost) throw Object.assign(new Error('STOP_LEASE_LOST：未确认任务，等待租约到期回收'), { code: 'LEASE_LOST' });
    const { taskId, token } = this.current;
    await this.verify();
    let confirmation;
    if (kind === 'complete') confirmation = await this.queue.complete(taskId, token, result);
    else if (kind === 'release') confirmation = await this.queue.release(taskId, token);
    else confirmation = await this.queue.fail(taskId, token, result?.error || result?.status || 'Worker interrupted');
    this.current = null;
    try { await this.writeLease({ active: false, validUntil: 0 }); }
    catch (error) {
      // Redis already confirmed this task. Do not convert a local reporting failure into an ack failure.
      this.halted = true;
      await fs.writeFile(this.stopFile, 'Local lease state could not be updated', 'utf8').catch(() => {});
      console.warn(`[Redis收尾] 任务已确认，但本地租约文件更新失败（${error.code || 'LOCAL_STATE_ERROR'}），停止领取下一任务`);
    }
    try { await this.report(); }
    catch (error) { console.warn(`[Redis进度] 任务已确认，进度刷新失败（${error.code || 'CONNECTION_ERROR'}）；以上全局进度可能过时`); }
    return confirmation;
  }

  async close({ stopped = false } = {}) {
    clearTimeout(this.timer);
    await this.heartbeat;
    clearTimeout(this.timer);
    try {
      if (this.current && !this.lost) await this.finish(stopped ? 'release' : 'fail', { error: '节点未确认任务即退出' });
    } finally {
      await this.writeLease({ active: false, validUntil: 0 }).catch(() => {});
      await this.client.close();
    }
  }
}

