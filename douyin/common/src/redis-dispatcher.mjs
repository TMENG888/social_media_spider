import fs from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { RedisTaskQueue } from './redis-task-queue.mjs';
import {claimCorrection,pauseCorrection} from './correction-lease.mjs';
import { redisSettings, connectRedis } from './redis-connection.mjs';
import { loadTaskManifest } from './redis-task-manifest.mjs';
import { writeJsonAtomic } from './checkpoint.mjs';
import {openVolumeRuntime} from './volume-runtime.mjs';

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

export class RedisDispatcher {
  static async open({ root, stateRoot, workerId, skipImport, stopFile, manifestOverride = null, campaignOverride = null, selectedTaskIds = null }) {
    const settings = await redisSettings(root);
    const manifest = manifestOverride || await loadTaskManifest(path.join(root, 'tasks', 'redis-tasks.json'));
    const client = await connectRedis(settings);
    // Different task revisions and export-only tests cannot acknowledge production work.
    const campaign = campaignOverride || (!skipImport && settings.taskPoolCampaign) || `${settings.campaign}-${skipImport ? 'export' : 'mysql'}-${manifest.manifestHash.slice(0, 16)}`;
    try {
      const dispatcher = new RedisDispatcher({ settings, manifest, client, campaign, stateRoot, workerId, stopFile });
      await client.ping();
      const chosen=selectedTaskIds ? manifest.tasks.filter(t=>selectedTaskIds.includes(t.redisTaskId||t.id)) : null;
      if(chosen && chosen.length!==selectedTaskIds.length)throw new Error('SELECTED_TASK_NOT_IN_MANIFEST');
      dispatcher.volume=skipImport||manifestOverride?null:await openVolumeRuntime({root,stateRoot,queue:dispatcher.queue,manifest,platform:'抖音'});
      const published=chosen||dispatcher.volume ? (await Promise.all((chosen||manifest.tasks).map(task=>dispatcher.queue.verifyExisting(task)))).at(-1)
        : await dispatcher.queue.publish(manifest.tasks);
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
    const { pending, leased, completed, completed_with_skips=0, skipped_unresolved=0, failed, total } = this.lastStats.counts;
    console.log(`[全局任务进度] ${completed}/${total}成功完成，含跳过完成${completed_with_skips}，整词跳过${skipped_unresolved}；待领取${pending}，执行中${leased}，故障保留${failed}`);
    await writeJsonAtomic(path.join(this.stateRoot, 'redis_queue_status.json'), {
      campaign: this.campaign, checkedAt: new Date().toISOString(), ...this.lastStats });
    return this.lastStats;
  }

  async stopped() { return fs.access(this.stopFile).then(() => true).catch(() => false); }

  async *tasks({taskIds=null,correctionPolicy=null}={}) {
    if(this.volume){
      if(correctionPolicy)throw new Error('VOLUME_AND_LEGACY_CORRECTION_ARE_EXCLUSIVE');
      let index=0;
      const chosen=taskIds?taskIds.map(id=>this.manifest.tasks.find(t=>(t.redisTaskId||t.id)===id)):this.manifest.tasks;
      if(chosen.some(t=>!t))throw new Error('SELECTED_TASK_NOT_IN_MANIFEST');
      for(const task of chosen){
        if(this.halted||await this.stopped())return;
        if(this.operations&&!(await this.operations.wait({shouldStop:this.operationalShouldStop})).ready)return;
        const id=task.redisTaskId||task.id,prepared=await this.volume.prepare(id);
        console.log(`[数量判定] ${task.keyword}：${prepared.decision.posts}/${prepared.decision.threshold}篇，${prepared.confirmation.status}`);
        if(prepared.confirmation.status!=='pending')continue;
        const started=Date.now(),lease=await this.queue.claim(this.owner,id);if(!lease)continue;
        if(prepared.confirmation.recollection){await this.volume.recollection.start(id,lease.token);lease.recollectionPolicy=prepared.confirmation.policy;}
        this.current=lease;this.lost=false;await this.saveLease(started);this.scheduleHeartbeat();
        yield[index++,lease.task];
        if(this.current)throw new Error('VOLUME_PREVIOUS_LEASE_NOT_CONFIRMED');
      }
      return;
    }
    if(correctionPolicy&&(!taskIds||taskIds.length!==1))throw new Error('CORRECTION_EXACT_TASK_REQUIRED');
    let index = 0, lastReport = 0,targetIndex=0;
    if(taskIds&&(!Array.isArray(taskIds)||!taskIds.length||taskIds.some(id=>!this.manifest.tasks.some(t=>(t.redisTaskId||t.id)===id))))throw new Error('SELECTED_TASK_NOT_IN_MANIFEST');
    while (!this.halted && !await this.stopped()) {
      if(this.operations&&!(await this.operations.wait({shouldStop:this.operationalShouldStop})).ready)return;
      if(taskIds&&targetIndex>=taskIds.length)return;
      if (this.current) throw new Error('上一个Redis任务尚未确认，禁止领取新任务');
      const started = Date.now();
      const targetId=taskIds?.[targetIndex]||null;
      if(targetId&&!correctionPolicy){const target=await this.queue.inspect(targetId);if(['completed','completed_with_skips','skipped_unresolved'].includes(target.status)){targetIndex++;continue;}if(target.status==='failed'||target.status==='missing')throw new Error(`SELECTED_TASK_UNAVAILABLE：${targetId}状态=${target.status}`);}
      const lease = correctionPolicy ? await claimCorrection(this.queue,this.owner,targetId,correctionPolicy) : await this.queue.claim(this.owner,targetId);
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
      if(correctionPolicy)return;
      if(targetId){const target=await this.queue.inspect(targetId);if(['completed','completed_with_skips','skipped_unresolved'].includes(target.status))targetIndex++;else return;} // A partial first task must not advance to topic two.
    }
  }

  env() {
    if (!this.current) return {};
    return { SOCIAL_RECOLLECT_ONCE:this.current.recollectionPolicy||'', ...(this.volume?{SOCIAL_VOLUME_ENABLED:'1',SOCIAL_VOLUME_TARGET_POSTS:String(this.volume.snapshot.threshold),SOCIAL_VOLUME_SNAPSHOT:this.volume.snapshotFile}:{}), DY_DISPATCH: 'redis', DY_LEASE_FILE: this.leaseFile,
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
    const volumeResult=this.volume?await this.volume.finish(taskId,token,result,{pause:kind==='release'}):null;
    if(volumeResult?.annualEvidence&&result)result.annualAcceptance=volumeResult.annualEvidence;
    if(volumeResult?.confirmation){confirmation=volumeResult.confirmation;Object.assign(result||{},
      ...(confirmation.acceptedByResetOnce?[{collectionError:result?.collectionError||result?.error||null,
       collectionSucceeded:confirmation.collectionSucceeded===true,dataImported:confirmation.dataImported===true,
       pendingImport:confirmation.pendingImport===true,businessCompleted:true}]:[]),
      {status:'completed',accepted:true,error:null,
      quantityAccepted:confirmation.acceptedByVolume===true,retryExhaustedCompletion:confirmation.acceptedByExhaustion===true,
      acceptedBy:confirmation.acceptedByResetOnce?'reset_once_recollection':confirmation.acceptedByExhaustion?'retry_exhausted_completion':confirmation.acceptedByAnnual?'verified_low_year_search':'keyword_post_count_p80',
      resetOnceCompletion:confirmation.acceptedByResetOnce===true,volumeAcceptance:volumeResult.decision});}
    else if(this.current.correctionPolicy&&['release','defer'].includes(kind)) confirmation=await pauseCorrection(this.queue,taskId,token,result);
    else if(this.volume&&kind==='complete')confirmation=await this.queue.fail(taskId,token,'VOLUME_BELOW_THRESHOLD',result);
    else if (kind === 'complete') confirmation = await this.queue.complete(taskId, token, result);
    else if (kind === 'review') confirmation = await this.queue.park(taskId, token, result);
    else if (kind === 'release') confirmation = await this.queue.release(taskId, token);
    else if (kind === 'defer') confirmation = await this.queue.defer(taskId, token, result);
    else confirmation = await this.queue.fail(taskId, token, result?.error || result?.status || 'Worker interrupted', result);
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
