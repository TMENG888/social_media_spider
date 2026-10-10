import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { createHash } from "node:crypto";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import { spawn } from "node:child_process";
import readline from "node:readline";
import { fileURLToPath } from "node:url";
import { cleanText } from "./text-cleaner.mjs";

const workerScript = fileURLToPath(new URL("./asr-worker.py", import.meta.url));
const CACHE_VERSION = 2;

function withTimeout(promise, timeoutMs, message) {
  let timer;
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(Object.assign(new Error(message), { code: "ASR_TIMEOUT" })), timeoutMs);
    })
  ]).finally(() => clearTimeout(timer));
}

function mediaIdentity(url) {
  const parsed = new URL(url);
  // CDN signatures expire without changing the underlying media.
  for (const key of ["sign", "t", "expires", "xsec_token"]) parsed.searchParams.delete(key);
  parsed.hash = "";
  parsed.searchParams.sort();
  return parsed.toString();
}

export class AsrService {
  constructor(options = {}) {
    this.options = {
      pythonExecutable: "python", model: "small", device: "cpu", computeType: "int8", language: "zh",
      cpuThreads: Math.max(1, Math.min(4, os.availableParallelism?.() || os.cpus().length || 1)), beamSize: 1,
      startupTimeoutMs: 300000, downloadTimeoutMs: 120000, transcriptionTimeoutMs: 900000,
      tempDir: path.resolve(".asr-temp"), localFilesOnly: false, ...options
    };
    this.options.cacheDir ??= path.join(this.options.modelDir || this.options.tempDir, "transcripts");
    this.pending = new Map();
    this.sequence = 0;
    this.process = null;
    this.readyPromise = null;
    this.queue = Promise.resolve();
  }

  async start() {
    if (this.readyPromise) return this.readyPromise;
    let resolveReady, rejectReady;
    const ready = new Promise((resolve, reject) => { resolveReady = resolve; rejectReady = reject; });
    const args = [workerScript, "--model", this.options.model, "--device", this.options.device,
      "--compute-type", this.options.computeType, "--language", this.options.language,
      "--cpu-threads", String(this.options.cpuThreads), "--beam-size", String(this.options.beamSize)];
    if (this.options.modelDir) args.push("--download-root", this.options.modelDir);
    if (this.options.localFilesOnly) args.push("--local-files-only");
    const child = spawn(this.options.pythonExecutable, args, {
      stdio: ["pipe", "pipe", "pipe"], windowsHide: true,
      env: { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8",
        OMP_NUM_THREADS: String(this.options.cpuThreads), MKL_NUM_THREADS: String(this.options.cpuThreads),
        OPENBLAS_NUM_THREADS: String(this.options.cpuThreads), NUMEXPR_NUM_THREADS: String(this.options.cpuThreads) }
    });
    this.process = child;
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk) => {
      const line = String(chunk).trim();
      if (line) console.warn(`[ASR] ${line.split("\n").at(-1)}`);
    });
    const failed = (error) => {
      rejectReady(error);
      if (this.process !== child) return;
      this.process = null;
      this.readyPromise = null;
      for (const pending of this.pending.values()) pending.reject(error);
      this.pending.clear();
      if (child.exitCode === null && !child.killed) child.kill();
    };
    child.on("error", failed);
    child.stdin.on("error", failed);
    child.on("exit", (code) => failed(new Error(`ASR进程退出，代码${code}`)));
    const lines = readline.createInterface({ input: child.stdout });
    lines.on("line", (line) => {
      let message;
      try { message = JSON.parse(line); } catch { return; }
      if (message.type === "ready") return resolveReady(message);
      if (message.type === "fatal") return rejectReady(new Error(message.error));
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.type === "result") pending.resolve(message);
      else pending.reject(new Error(message.error || "ASR识别失败"));
    });
    this.readyPromise = withTimeout(ready, this.options.startupTimeoutMs, "ASR模型初始化超时")
      .catch((error) => { failed(error); child.kill(); throw error; });
    return this.readyPromise;
  }

  async download(url, target, referer = "https://www.douyin.com/") {
    await fs.mkdir(path.dirname(target), { recursive: true });
    const response = await fetch(url, {
      redirect: "follow", headers: { "User-Agent": "Mozilla/5.0", Referer: referer },
      signal: AbortSignal.timeout(this.options.downloadTimeoutMs)
    });
    if (!response.ok || !response.body) throw new Error(`视频下载失败 HTTP ${response.status}`);
    await pipeline(Readable.fromWeb(response.body), (await import("node:fs")).createWriteStream(target));
    const size = (await fs.stat(target)).size;
    if (!size) throw new Error("视频下载为空，无法提取音轨");
    return size;
  }

  async transcribeFile(mediaPath, articleId, prompt) {
    await this.start();
    const child = this.process;
    const id = `${articleId}-${++this.sequence}`;
    const resultPromise = new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      child.stdin.write(`${JSON.stringify({ id, path: mediaPath, language: this.options.language,
        prompt: String(prompt || "").slice(0, 500) || null })}\n`, (error) => { if (error) reject(error); });
    });
    try {
      return await withTimeout(resultPromise, this.options.transcriptionTimeoutMs, `ASR识别超时：${articleId}`);
    } catch (error) {
      // A timed-out inference must not block every subsequent video in the queue.
      if (error.code === "ASR_TIMEOUT" && this.process === child) {
        this.process = null;
        this.readyPromise = null;
        const exited = new Promise((resolve) => child.once("exit", resolve));
        child.kill();
        await withTimeout(exited, 5000, "ASR进程终止超时").catch(() => {});
      }
      throw error;
    } finally {
      this.pending.delete(id);
    }
  }

  async transcribePath(mediaPath, articleId, prompt = null) {
    const task = this.queue.then(async () => {
      const result = await this.transcribeFile(mediaPath, articleId, prompt);
      const cleaned = cleanText(result.text, { removeEmoji: true, singleParagraph: true, paragraphSeparator: "，" });
      const bytes = (await fs.stat(mediaPath)).size;
      return {
        text: cleaned.text || null,
        source: cleaned.text ? "audio_asr" : null,
        audit: { ...result, bytes, cache_hit: false, cleaning_stats: cleaned.stats }
      };
    });
    this.queue = task.catch(() => {});
    return task;
  }

  transcribeUrl(url, articleId, prompt = null, referer = null) {
    // One inference at a time: concurrent callers share a model without timeout starvation.
    const task = this.queue.then(() => this.transcribeUrlOnce(url, articleId, prompt, referer));
    this.queue = task.catch(() => {});
    return task;
  }

  async transcribeUrlOnce(url, articleId, prompt, referer) {
    const key = createHash("sha256").update(JSON.stringify({ version: CACHE_VERSION, media: mediaIdentity(url),
      articleId, model: this.options.model, language: this.options.language, beamSize: this.options.beamSize,
      computeType: this.options.computeType })).digest("hex");
    const cachePath = path.join(this.options.cacheDir, `${key}.json`);
    try {
      const cached = JSON.parse(await fs.readFile(cachePath, "utf8"));
      if (cached.version === CACHE_VERSION && cached.result?.text) {
        return { ...cached.result, audit: { ...cached.result.audit, cache_hit: true } };
      }
    } catch { /* Missing or damaged cache is retried from the actual media. */ }
    const safeId = String(articleId || "video").replace(/[^a-zA-Z0-9_-]/g, "_");
    const mediaPath = path.join(this.options.tempDir, `${safeId}-${process.pid}-${Date.now()}.mp4`);
    try {
      const bytes = await this.download(url, mediaPath, referer || "https://www.douyin.com/");
      const result = await this.transcribeFile(mediaPath, safeId, prompt);
      const cleaned = cleanText(result.text, { removeEmoji: true, singleParagraph: true, paragraphSeparator: "，" });
      const output = { text: cleaned.text || null, source: cleaned.text ? "audio_asr" : null,
        audit: { ...result, bytes, cache_hit: false, cleaning_stats: cleaned.stats } };
      // Only successful spoken text is cached. A transient failure/empty track remains retryable.
      if (output.text) {
        const temporaryCache = `${cachePath}.${process.pid}.tmp`;
        try {
          await fs.mkdir(this.options.cacheDir, { recursive: true });
          await fs.writeFile(temporaryCache, JSON.stringify({ version: CACHE_VERSION, result: output }), "utf8");
          await fs.rename(temporaryCache, cachePath);
        } catch (error) {
          console.warn(`[ASR] 转写成功，缓存写入失败：${error.code || error.message}`);
          await fs.rm(temporaryCache, { force: true }).catch(() => {});
        }
      }
      return output;
    } finally {
      if (!this.options.keepMedia) await fs.rm(mediaPath, { force: true }).catch(() => {});
    }
  }

  async close() {
    await this.queue;
    const child = this.process;
    if (!child || child.killed) return;
    const exited = new Promise((resolve) => child.once("exit", resolve));
    child.stdin.end(`${JSON.stringify({ type: "close" })}\n`);
    await withTimeout(exited, 3000, "ASR关闭超时").catch(() => child.kill());
    this.process = null;
    this.readyPromise = null;
  }
}

