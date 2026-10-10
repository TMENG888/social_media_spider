import fs from "node:fs/promises";
import path from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import { spawn } from "node:child_process";
import readline from "node:readline";
import { fileURLToPath } from "node:url";
import { cleanText } from "./text-cleaner.mjs";

const workerScript = fileURLToPath(new URL("./asr-worker.py", import.meta.url));

function withTimeout(promise, timeoutMs, message) {
  let timer;
  return Promise.race([
    promise,
    new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(message)), timeoutMs); })
  ]).finally(() => clearTimeout(timer));
}

export class AsrService {
  constructor(options) {
    this.options = options;
    this.pending = new Map();
    this.sequence = 0;
    this.process = null;
    this.readyPromise = null;
  }

  async start() {
    if (this.readyPromise) return this.readyPromise;
    let resolveReady, rejectReady;
    this.readyPromise = new Promise((resolve, reject) => { resolveReady = resolve; rejectReady = reject; });
    const args = [workerScript, "--model", this.options.model, "--device", this.options.device,
      "--compute-type", this.options.computeType, "--language", this.options.language,
      "--download-root", this.options.modelDir];
    this.process = spawn(this.options.pythonExecutable, args, {
      stdio: ["pipe", "pipe", "pipe"], windowsHide: true,
      env: { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" }
    });
    this.process.stdout.setEncoding("utf8");
    this.process.stderr.setEncoding("utf8");
    this.process.stderr.on("data", (chunk) => {
      const line = String(chunk).trim();
      if (line) console.warn(`[ASR] ${line.split("\n").at(-1)}`);
    });
    this.process.on("error", (error) => rejectReady(error));
    this.process.on("exit", (code) => {
      const error = new Error(`ASR进程退出，代码${code}`);
      rejectReady(error);
      for (const pending of this.pending.values()) pending.reject(error);
      this.pending.clear();
    });
    const lines = readline.createInterface({ input: this.process.stdout });
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
    return withTimeout(this.readyPromise, this.options.startupTimeoutMs, "ASR模型初始化超时");
  }

  async download(url, target, referer = "https://www.xiaohongshu.com/") {
    await fs.mkdir(path.dirname(target), { recursive: true });
    const response = await fetch(url, {
      redirect: "follow",
      headers: { "User-Agent": "Mozilla/5.0", Referer: referer },
      signal: AbortSignal.timeout(this.options.downloadTimeoutMs)
    });
    if (!response.ok || !response.body) throw new Error(`视频下载失败 HTTP ${response.status}`);
    await pipeline(Readable.fromWeb(response.body), (await import("node:fs")).createWriteStream(target));
    return Number(response.headers.get("content-length")) || (await fs.stat(target)).size;
  }

  async transcribeUrl(url, articleId, prompt = null, referer = null) {
    await this.start();
    const safeId = String(articleId || "video").replace(/[^a-zA-Z0-9_-]/g, "_");
    const mediaPath = path.join(this.options.tempDir, `${safeId}-${Date.now()}.mp4`);
    let bytes = null;
    try {
      bytes = await this.download(url, mediaPath, referer || "https://www.xiaohongshu.com/");
      const id = `${safeId}-${++this.sequence}`;
      const resultPromise = new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
      this.process.stdin.write(`${JSON.stringify({ id, path: mediaPath, language: this.options.language, prompt: String(prompt || "").slice(0, 500) || null })}\n`);
      const result = await withTimeout(resultPromise, this.options.transcriptionTimeoutMs, `ASR识别超时：${articleId}`);
      const cleaned = cleanText(result.text, { removeEmoji: true, singleParagraph: true, paragraphSeparator: "，" });
      return { text: cleaned.text || null, source: "audio_asr", audit: { ...result, bytes, cleaning_stats: cleaned.stats } };
    } finally {
      if (!this.options.keepMedia) await fs.rm(mediaPath, { force: true }).catch(() => {});
    }
  }

  async close() {
    if (!this.process || this.process.killed) return;
    this.process.stdin.write(`${JSON.stringify({ type: "close" })}\n`);
    await new Promise((resolve) => {
      const timer = setTimeout(resolve, 3000);
      this.process.once("exit", () => { clearTimeout(timer); resolve(); });
    });
    if (!this.process.killed) this.process.kill();
  }
}
