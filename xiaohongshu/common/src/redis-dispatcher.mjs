import os from 'node:os';

import fs from 'node:fs/promises';

import path from 'node:path';

import { randomUUID } from 'node:crypto';

import { RedisTaskQueue } from './redis-task-queue.mjs';

import {claimCorrection,pauseCorrection} from './correction-lease.mjs';

import { redisSettings, connectRedis } from './redis-connection.mjs';

import { loadTaskManifest } from './redis-task-manifest.mjs';

import { writeJsonAtomic } from './checkpoint.mjs';

import {validTargetProof} from './article-comment-target.mjs';
import {ANNUAL_RESUME_VERSION,AnnualCheckpointStore,seedLegacyTask} from './annual-resume.mjs';

import {scopedTasks} from './task-scope.mjs';

import {schedulingPlan} from './scheduling-priority.mjs';

import {completeLocalP80,localP80Exception,readLocalP80,LOCAL_P80_POLICY} from './local-post-p80.mjs';



const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));



export class RedisDispatcher {

  static async open({ root, stateRoot, workerId, skipImport, stopFile, manifestOverride = null, campaignOverride = null, selectedTaskId = null }) {

    const settings = await redisSettings(root);

    const manifest = manifestOverride || await loadTaskManifest(path.join(root, 'tasks', 'redis-tasks.json'));

    const client = await connectRedis(settings);

    // Different task revisions and export-only tests cannot acknowledge production work.

    const campaign = campaignOverride || (!skipImport && settings.taskPoolCampaign) || `${settings.campaign}-${skipImport ? 'export' : 'mysql'}-${manifest.manifestHash.slice(0, 16)}`;

    try {

      const dispatcher = new RedisDispatcher({ root, settings, manifest, client, campaign, stateRoot, workerId, stopFile });

      dispatcher.schedulingTasks = await scopedTasks(root, manifest.tasks);

      dispatcher.scopeLimited = dispatcher.schedulingTasks.length !== manifest.tasks.length;

      if (dispatcher.schedulingTasks.length !== manifest.tasks.length) {

        console.log(`[专题调度] 仅领取${[...new Set(dispatcher.schedulingTasks.map(t=>t.topic))].join('、')}：${dispatcher.schedulingTasks.length}词；其余专题任务及断点保留。`);

      }

      await client.ping();

      const selected=selectedTaskId?manifest.tasks.find(t=>(t.redisTaskId||t.id)===selectedTaskId):null;

      if(selectedTaskId&&!selected)throw new Error('SELECTED_TASK_NOT_IN_MANIFEST');

      // A selected retry never publishes or recreates tasks, including other

      // missing manifest entries. Verify the stored payload read-only instead.

      dispatcher.annualResume=!skipImport&&!manifestOverride;

      dispatcher.queue.annualResume=dispatcher.annualResume;

      const published = selected ? await dispatcher.queue.verifyExisting(selected)

        : dispatcher.annualResume ? (await Promise.all(dispatcher.schedulingTasks.map(task=>dispatcher.queue.verifyExisting(task)))).at(-1)

        : await dispatcher.queue.publish(dispatcher.schedulingTasks);

      console.log(`[年度断点策略] ${ANNUAL_RESUME_VERSION}；不再按40篇或一次重采结案`);

      console.log(`[Redis预检] 通过；任务池=${campaign}，清单${manifest.taskCount}项，新增${published.added}项、已存在${published.existing}项`);

      if(dispatcher.annualResume){

        const p80=await readLocalP80(client,dispatcher.queue.namespace,manifest.manifestHash,manifest.tasks[0].keyword);

        console.log(`[本地P80异常结案] ${LOCAL_P80_POLICY}；全平台，不分专题或项目；${p80.ok?`P80=${p80.threshold}篇，样本${p80.samples}词`:'总体尚未就绪，保留原年度验收'} `);

      }

      await dispatcher.report();

      return dispatcher;

    } catch (error) { await client.close(); throw error; }

  }



  constructor({ root, settings, manifest, client, campaign, stateRoot, workerId, stopFile }) {

    Object.assign(this, { root, settings, manifest, client, campaign, stateRoot, workerId, stopFile });

    this.checkpointSource=os.hostname()+':'+workerId;

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



  async *tasks({taskId=null,correctionPolicy=null,mayClaim=()=>true}={}) {

    if(this.annualResume){

      if(correctionPolicy)throw new Error('LEGACY_RECOLLECTION_REMOVED');

      const selected=(this.schedulingTasks||this.manifest.tasks).filter(t=>!taskId||(t.redisTaskId||t.id)===taskId);

      if(!selected.length)throw new Error('SELECTED_TASK_NOT_IN_SCOPE');

      let index=0,lastPriority=null;

      while(!this.halted&&!await this.stopped()&&mayClaim()){

        const plan=taskId?{tasks:selected,priorityActive:false}:await schedulingPlan(this.root,this.manifest.tasks,this.queue);

        const chosen=plan.tasks;

        if(lastPriority!==plan.priorityActive){console.log(`[品牌调度] ${plan.priorityActive?plan.label+'优先，其他品牌保留断点排后':'优先品牌已处理，按原顺序继续后续任务'}`);lastPriority=plan.priorityActive;}

        let pending=plan.priorityActive;

        for(const task of chosen){

          if(this.halted||await this.stopped()||!mayClaim())return;

          await this.cooldown?.assertReady();

          const id=task.redisTaskId||task.id,inspect=await this.queue.inspect(id);

          if(inspect.status==='leased'||inspect.status==='pending')pending=true;

          if(inspect.status!=='pending'&&inspect.status!=='leased')continue;

          const started=Date.now(),lease=await this.queue.claim(this.owner,id);if(!lease)continue;

          this.current=lease;this.lost=false;await this.saveLease(started);this.scheduleHeartbeat();

          console.log(`[年度任务领取] ${this.workerId}：${task.keyword}；日期断点续采，累计尝试${lease.attempt}`);

          yield[index++,lease.task];

          if(this.current)throw new Error('ANNUAL_PREVIOUS_LEASE_NOT_CONFIRMED');

          if(taskId)return;

        }

        if(!pending)return;

        await sleep(2000);

      }

      return;

    }

    if(correctionPolicy&&!taskId)throw new Error('CORRECTION_EXACT_TASK_REQUIRED');

    if(taskId&&!this.manifest.tasks.some(t=>(t.redisTaskId||t.id)===taskId))throw new Error('SELECTED_TASK_NOT_IN_MANIFEST');

    let index = 0, lastReport = 0;

    while (!this.halted && !await this.stopped() && mayClaim()) {

      await this.cooldown?.assertReady();

      if (this.current) throw new Error('上一个Redis任务尚未确认，禁止领取新任务');

      const started = Date.now();

      if(taskId&&!correctionPolicy){

        const target=await this.queue.inspect(taskId);

        if(['completed','completed_with_skips','skipped_unresolved'].includes(target.status))return;

        if(target.status==='failed'||target.status==='missing')throw new Error('SELECTED_TASK_UNAVAILABLE');

      }

      if(this.halted||await this.stopped()||!mayClaim())return;

      const lease = correctionPolicy ? await claimCorrection(this.queue,this.owner,taskId,correctionPolicy) : await this.queue.claim(this.owner,taskId);

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

      if(taskId)return; // One real attempt only; never fall through to other tasks.

    }

  }



  env() {

    if (!this.current) return {};

    return { XHS_CHECKPOINT_SOURCE:this.checkpointSource,XHS_ANNUAL_RESUME:this.annualResume?'1':'',SOCIAL_RECOLLECT_ONCE:'',SOCIAL_VOLUME_ENABLED:'', XHS_DISPATCH: 'redis', XHS_LEASE_FILE: this.leaseFile,

      XHS_LEASE_TASK_ID: this.current.taskId, XHS_LEASE_TOKEN: this.current.token, XHS_LEASE_CAMPAIGN: this.campaign };

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

    if(this.annualResume){

      if(kind==='local_p80'){

        if(!localP80Exception(result))confirmation={ok:false,reason:'LOCAL_P80_EXCEPTION_REQUIRED'};

        else confirmation=await completeLocalP80(this.queue,this.manifest.manifestHash,taskId,token,result);

        if(!confirmation.acceptedByLocalP80){this.scheduleHeartbeat();return confirmation;}

      }else if(kind==='complete'){

        if(result?.annualResumePolicy!==ANNUAL_RESUME_VERSION||(result?.searchAcceptance?.ok!==true&&!(result?.acceptedBy==='article_comment_target'&&validTargetProof(result.articleCommentTarget,{keyword:result.keyword,projectName:result.projectName,requireDatabase:true})))||result?.importExitCode!==0)

          throw new Error('ANNUAL_COMPLETION_UNVERIFIED');

        confirmation=await this.queue.complete(taskId,token,result);

      }else if(kind==='release')confirmation=await this.queue.release(taskId,token);

      else confirmation=await this.queue.continueAnnual(taskId,token,result);

    }

    if(!this.annualResume){

      if(kind==='complete')confirmation=await this.queue.complete(taskId,token,result);

      else if(kind==='review')confirmation=await this.queue.park(taskId,token,result);

      else if(kind==='release')confirmation=await this.queue.release(taskId,token);

      else if(kind==='defer')confirmation=await this.queue.defer(taskId,token,result);

      else confirmation=await this.queue.fail(taskId,token,result?.error||result?.status||'Worker interrupted',result);

    }

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
