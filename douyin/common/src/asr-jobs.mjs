import fs from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
import { enqueueAsrJob, claimAsrJob, markAsrRunning, completeAsrJob, failAsrJob, deferAsrJob, asrJobStats } from "./checkpoint.mjs";

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const runtimeUnavailable = error => /mkl_malloc|failed to allocate memory|cannot allocate memory|not enough memory|paging file|std::bad_alloc|ASR模型初始化超时/i.test(String(error?.message || error));
const extensionFor = url => {
  try {
    const match = new URL(url).pathname.match(/\.(mp4|m4a|m4s|webm|mov)$/i);
    return match ? `.${match[1].toLowerCase()}` : ".mp4";
  } catch { return ".mp4"; }
};

export class AsrJobProcessor {
  constructor({ db, service, mediaDir, maxAttempts = 3, retryDelayMs = 3000, keepMedia = false, onCompleted = null, shouldStop = async () => false }) {
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
  }

  start() {
    if (!this.loopPromise) this.loopPromise = this.loop();
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

  async process(job) {
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
        await this.service.download(job.mediaUrl, temporary, job.referer || "https://www.douyin.com/");
        await fs.rm(mediaPath, { force: true }).catch(() => {});
        await fs.rename(temporary, mediaPath);
      }
      markAsrRunning(this.db, job, mediaPath);
      console.log(`[ASR后台] ${job.noteId}：第${job.attempts}/${job.maxAttempts}次识别`);
      // The first pass uses the note context. A quality retry drops the prompt
      // so a bad title/tag hint cannot be echoed into the transcript again.
      const output = await this.service.transcribePath(mediaPath, job.articleId || job.noteId, job.attempts === 1 ? job.prompt : null);
      if (!output.text && output.audit?.status === "quality_rejected") {
        const qualityError = new Error(`ASR_QUALITY_REJECTED：${output.audit?.quality?.reason || "字幕完整性或幻觉检测未通过"}`);
        qualityError.audit = output.audit;
        throw qualityError;
      }
      const updated = completeAsrJob(this.db, job, output);
      console.log(`[ASR回填] ${job.noteId}：${output.text ? `成功，${output.text.length}字` : `完成（${output.audit?.status || "no_speech"}）`}`);
      if (this.onCompleted) {
        try { await this.onCompleted(job, output, updated); }
        catch (error) { console.warn(`[ASR入库] ${job.noteId}：本地回填成功，MySQL增量回填稍后由全量收尾兜底：${String(error.message || error).split("\n")[0]}`); }
      }
      if (!this.keepMedia) await fs.rm(mediaPath, { force: true }).catch(() => {});
    } catch (error) {
      await fs.rm(temporary, { force: true }).catch(() => {});
      if (runtimeUnavailable(error)) {
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

  async loop() {
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

  async drain() {
    this.drainRequested = true;
    this.start();
    this.wake();
    await this.loopPromise;
    const stats = asrJobStats(this.db);
    console.log(`[ASR队列] 本轮收尾：完成${stats.completed || 0}，死信${stats.dead_letter || 0}，待处理${stats.pendingTotal}`);
    return { ...stats, runtimeUnavailable: Boolean(this.haltedReason), runtimeError: this.haltedReason };
  }

  async close() {
    this.stopping = true;
    this.wake();
    await this.loopPromise?.catch(() => {});
  }
}

