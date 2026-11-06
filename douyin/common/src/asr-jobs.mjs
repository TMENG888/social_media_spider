import {configureTiming,timed,timedSync,contentTiming,timingDisposition,timingMarker,timingProgress,timingFailure,timingStop} from './keyword-timing.mjs';
import fs from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
import { enqueueAsrJob, claimAsrJob, markAsrRunning, completeAsrJob, failAsrJob, deferAsrJob, asrJobStats } from "./checkpoint.mjs";
import { cleanupCompletedAsrMedia, recordAsrMediaImport } from "./asr-media-cleanup.mjs";
import { transientDownloadError } from "./asr.mjs";

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const runtimeUnavailable = error => /mkl_malloc|failed to allocate memory|cannot allocate memory|not enough memory|paging file|std::bad_alloc|ASR模型初始化超时/i.test(String(error?.message || error));
const extensionFor = url => {
  try {
    const match = new URL(url).pathname.match(/\.(mp4|m4a|m4s|webm|mov)$/i);
    return match ? `.${match[1].toLowerCase()}` : ".mp4";
  } catch { return ".mp4"; }
};

export class AsrJobProcessor {
  constructor({ db, service, mediaDir, maxAttempts = 3, retryDelayMs = 3000, downloadAttempts = 4, downloadBaseDelayMs = 3000, downloadMaxDelayMs = 60000, keepMedia = false, onCompleted = null, shouldStop = async () => false }) {
    this.db = db;
    this.service = service;
    this.mediaDir = path.resolve(mediaDir);
    this.maxAttempts = Math.max(1, Number(maxAttempts) || 3);
    this.retryDelayMs = Math.max(0, Number(retryDelayMs) || 0);
    this.keepMedia = keepMedia;
    this.onCompleted = onCompleted;
    this.shouldStop = shouldStop;
    this.loopPromise = null;
    this.waiter = null;
    this.stopping = false;
    this.drainRequested = false;
    this.haltedReason = null;
    this.downloadAttempts=Math.min(8,Math.max(1,Number(downloadAttempts)||4));
    this.downloadBaseDelayMs=Math.max(0,Number(downloadBaseDelayMs)||0);
    this.downloadMaxDelayMs=Math.max(0,Number(downloadMaxDelayMs)||0);
    this.haltedKind=null;
    this.loopError=null;
  }

  start() {
    if (!this.loopPromise) {
      this.loopPromise = this.loop();
      // enqueue() starts this in the background. Observe rejection immediately,
      // without hiding it from drain() or turning a failure into success.
      this.loopPromise.catch(error=>{
        this.loopError=error;
        this.haltedKind='processor';
        this.haltedReason='ASR_BACKGROUND_FAILED';
        console.warn('[ASR后台异常] ASR_BACKGROUND_FAILED；作业保留，收尾将报告失败');
      });
    }
    this.wake();
    return this.loopPromise;
  }

  enqueue(job) {
    enqueueAsrJob(this.db, job, this.maxAttempts);
    console.log(`[ASR入队] ${job.noteId}：媒体下载、识别与回填已交给后台队列`);
    this.start();
  }

  wake() {
    this.waiter?.();
    this.waiter = null;
  }

  async waitForWork() {
    await new Promise(resolve => { this.waiter = resolve; });
  }

  mediaPath(job) {
    if (job.mediaPath) return path.resolve(job.mediaPath);
    const key = createHash("sha256").update(`${job.keyword}\n${job.noteId}\n${job.mediaUrl}`).digest("hex");
    return path.join(this.mediaDir, `${key}${extensionFor(job.mediaUrl)}`);
  }

  async downloadMedia(job,temporary) {
    for(let attempt=1;attempt<=this.downloadAttempts;attempt++){
      try {
        await fs.rm(temporary,{force:true});
        await this.service.download(job.mediaUrl,temporary,job.referer||"https://www.douyin.com/");
        return;
      } catch(error) {
        if(!transientDownloadError(error))throw error;
        const requestedDelay=Math.max(this.downloadBaseDelayMs*2**(attempt-1),Number(error.retryAfterMs)||0);
        console.warn(`[ASR下载重试] ${job.noteId}：${attempt}/${this.downloadAttempts}，${error.httpStatus||'NETWORK'}；不消耗识别重试次数`);
        if(attempt===this.downloadAttempts||requestedDelay>this.downloadMaxDelayMs){
          throw Object.assign(new Error('MEDIA_DOWNLOAD_RETRY_EXHAUSTED'),{downloadDeferred:true});
        }
        // Check for a stop during backoff, instead of sleeping uninterruptibly.
        const until=Date.now()+requestedDelay;
        do {
          if(this.stopping||await this.shouldStop())throw Object.assign(new Error('MEDIA_DOWNLOAD_STOPPED'),{downloadDeferred:true});
          await sleep(Math.min(250,Math.max(0,until-Date.now())));
        }while(Date.now()<until);
      }
    }
  }

  async process(job) {return timed('asr_job',()=>this.processTimingImpl(job),{keyword:job.keyword,articleId:job.noteId,lane:'asr',attempt:job.attempts});}
  async processTimingImpl(job) {
    const mediaPath = this.mediaPath(job);
    const temporary = `${mediaPath}.part`;
    try {
      let size = 0;
      try { size = (await fs.stat(mediaPath)).size; } catch {}
      if (!size) {
        console.log(`[ASR下载] ${job.noteId}：开始持久化视频音轨来源`);
        await fs.mkdir(path.dirname(mediaPath), { recursive: true });
        await fs.rm(mediaPath, { force: true }).catch(() => {});
        await fs.rm(temporary, { force: true }).catch(() => {});
        await timed('media_download',()=>this.downloadMedia(job,temporary));
        await fs.rm(mediaPath, { force: true }).catch(() => {});
        await fs.rename(temporary, mediaPath);
      }
      markAsrRunning(this.db, job, mediaPath);
      console.log(`[ASR后台] ${job.noteId}：第${job.attempts}/${job.maxAttempts}次识别`);
      // The first pass uses the note context. A quality retry drops the prompt
      // so a bad title/tag hint cannot be echoed into the transcript again.
      const output = await timed('asr_inference',()=>this.service.transcribePath(mediaPath, job.articleId || job.noteId, job.attempts === 1 ? job.prompt : null));
      if (!output.text && output.audit?.status === "quality_rejected") {
        const qualityError = new Error(`ASR_QUALITY_REJECTED：${output.audit?.quality?.reason || "字幕完整性或幻觉检测未通过"}`);
        qualityError.audit = output.audit;
        throw qualityError;
      }
      const updated = completeAsrJob(this.db, job, output);
      console.log(`[ASR回填] ${job.noteId}：${output.text ? `成功，${output.text.length}字` : `完成（${output.audit?.status || "no_speech"}）`}`);
      let importConfirmed = false;
      if (this.onCompleted) {
        try { importConfirmed = await this.onCompleted(job, output, updated) === true; }
        catch (error) { console.warn(`[ASR入库] ${job.noteId}：本地回填成功，MySQL增量回填稍后由全量收尾兜底：${String(error.message || error).split("\n")[0]}`); }
      }
      if (importConfirmed) {
        try { recordAsrMediaImport(this.db, job, updated); await this.cleanupMedia(job); }
        catch { console.warn(`[ASR媒体保留] ${job.noteId}：入库确认记录未保存，媒体保留；ASR完成状态不变`); }
      } else console.log(`[ASR媒体保留] ${job.noteId}：当前字幕入库未确认，媒体保留`);
    } catch (error) {
      await fs.rm(temporary, { force: true }).catch(() => {});
      if(error.downloadDeferred){
        deferAsrJob(this.db,job,error);
        this.haltedKind='download';
        this.haltedReason=error.message;
        console.warn(`[ASR下载待补] ${job.noteId}：${error.message}；已退回识别计数，本轮停止后台下载，文章采集继续，下轮重试`);
        return false;
      }
      if (runtimeUnavailable(error)) {
        this.haltedKind='runtime';
        deferAsrJob(this.db, job, error);
        this.haltedReason = String(error.message || error).split("\n")[0];
        console.warn(`[ASR后台降级] ${job.noteId}：运行资源暂不可用；任务保留为retry_pending，本轮文章采集继续`);
        return false;
      }
      const status = failAsrJob(this.db, job, error);
      console.warn(`[ASR精准重试] ${job.noteId}：${status}，${String(error.message || error).split("\n")[0]}`);
      if (status === "retry_pending" && this.retryDelayMs) await sleep(this.retryDelayMs);
    }
    return true;
  }

  async cleanupMedia(job = null) {
    // Cleanup failures must never demote a successfully committed ASR job.
    try {
      const stats = await cleanupCompletedAsrMedia({ db: this.db, mediaDir: this.mediaDir, keepMedia: this.keepMedia, job });
      if (stats.deleted) console.log(`[ASR媒体清理] 已删除${stats.deleted}个完成媒体，释放${(stats.bytes / 1048576).toFixed(1)} MB；字幕和识别记录保留`);
      return stats;
    } catch (error) {
      console.warn(`[ASR媒体清理] 本轮跳过，下次启动重试：${String(error.message || error).split("\n")[0]}`);
      return null;
    }
  }

  async loop() {
    await this.cleanupMedia();
    while (!this.stopping) {
      if (await this.shouldStop()) {
        this.stopping = true;
        console.log('[ASR安全停止] 当前任务已收尾，剩余ASR任务保留，不再领取');
        break;
      }
      const job = claimAsrJob(this.db);
      if (job) {
        const keepRunning = await this.process(job);
        if (keepRunning === false) break;
        continue;
      }
      if (this.drainRequested) break;
      await this.waitForWork();
    }
  }

  async drain() {return timed('asr_drain',()=>this.drainDetailedImpl(),{lane:'persistence'});}
  async drainDetailedImpl() {
    this.drainRequested = true;
    this.start();
    this.wake();
    await this.loopPromise;
    const stats = asrJobStats(this.db);
    console.log(`[ASR队列] 本轮收尾：完成${stats.completed || 0}，死信${stats.dead_letter || 0}，待处理${stats.pendingTotal}`);
    return { ...stats, runtimeUnavailable: Boolean(this.haltedReason), runtimeError: this.haltedReason, haltedKind:this.haltedKind,downloadDeferred:this.haltedKind==='download' };
  }

  async close() {
    this.stopping = true;
    this.wake();
    await this.loopPromise?.catch(() => {});
  }
}
