import fs from "node:fs/promises";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";
import { cleanupCompletedAsrMedia } from "./asr-media-cleanup.mjs";

const skippedDirs = new Set(["browser-profile", "media", "asr-media", "asr-models", "node_modules", "runtime"]);

export async function cleanupWorkerAsrMedia({ stateRoot, mediaName, keepMedia = false, dryRun = true }) {
  if (!["media", "asr-media"].includes(mediaName)) throw new Error("Invalid ASR media directory name");
  const total = { checkpoints: 0, deleted: 0, eligible: 0, bytes: 0, retained: 0, missing: 0, errors: 0, dryRun };
  if (keepMedia) return total;
  const root = path.resolve(stateRoot);
  try {
    const stat = await fs.lstat(root);
    if (!stat.isDirectory() || stat.isSymbolicLink()) return total;
  } catch (error) { if (error.code === "ENOENT") return total; throw error; }
  const directories = [root];
  while (directories.length) {
    const dir = directories.pop();
    const entries = await fs.readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
      if (entry.isSymbolicLink()) continue;
      const target = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (!skippedDirs.has(entry.name)) directories.push(target);
      } else if (entry.isFile() && entry.name === "checkpoint.sqlite") {
        let db;
        try {
          // Never call openCheckpoint here: it recovers running jobs as a write.
          db = new DatabaseSync(target, { readOnly: true });
          db.exec("PRAGMA busy_timeout=5000");
          const stats = await cleanupCompletedAsrMedia({ db, mediaDir: path.join(dir, mediaName), dryRun });
          total.checkpoints++;
          for (const key of ["deleted", "eligible", "bytes", "retained", "missing", "errors"]) total[key] += stats[key];
        } catch (error) {
          total.errors++;
          console.warn(`[ASR媒体清理] 断点跳过，未修改任务：${String(error.message || error).split("\n")[0]}`);
        } finally { db?.close(); }
      }
    }
  }
  if (total.eligible) console.log(`[ASR历史媒体清理] ${dryRun ? "预览可清理" : "已删除"}${total.eligible}个，${(total.bytes / 1073741824).toFixed(2)} GB；待处理和需复核媒体保留`);
  return total;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const state = args.indexOf("--state-root");
  const media = args.indexOf("--media-name");
  if (state < 0 || media < 0 || !args[state + 1] || !args[media + 1]) {
    throw new Error("Usage: cleanup-worker-asr-media.mjs --state-root <worker/.state> --media-name media|asr-media [--apply]");
  }
  const common = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const config = JSON.parse((await fs.readFile(path.join(common, "config.json"), "utf8")).replace(/^\uFEFF/, ""));
  console.log(JSON.stringify(await cleanupWorkerAsrMedia({
    stateRoot: args[state + 1], mediaName: args[media + 1],
    dryRun: !args.includes("--apply"), keepMedia: config.asrKeepMedia === true
  })));
}
