import fs from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
import { needsAsrQualityRetry } from "./checkpoint.mjs";

const noSpeech = new Set(["no_speech", "no_audio_track", "empty_audio_track", "silent_audio"]);
const normalPath = value => process.platform === "win32" ? path.resolve(value).toLowerCase() : path.resolve(value);
const inside = (root, file) => {
  const relative = path.relative(root, file);
  return Boolean(relative) && relative !== ".." && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
};
const importFingerprint = result => createHash('sha256').update(JSON.stringify({
  articleId: result?.post?.['文章id'] ?? null, platform: result?.post?.['平台'] ?? null,
  project: result?.post?.['项目'] ?? null, transcript: result?.post?.['文章视频内容'] ?? null,
  subtitle: result?.postTextAudit ?? null
})).digest('hex');

// Called only after the current transcript's MySQL commit/readback succeeded.
// No media deletion or ASR state change if this small local receipt cannot save.
export function recordAsrMediaImport(db, job, result) {
  db.exec(`CREATE TABLE IF NOT EXISTS asr_media_import_receipt (
    keyword TEXT NOT NULL,note_id TEXT NOT NULL,result_hash TEXT NOT NULL,
    confirmed_at TEXT NOT NULL,PRIMARY KEY(keyword,note_id))`);
  db.prepare(`INSERT INTO asr_media_import_receipt VALUES(?,?,?,?)
    ON CONFLICT(keyword,note_id) DO UPDATE SET result_hash=excluded.result_hash,confirmed_at=excluded.confirmed_at`)
    .run(job.keyword,job.noteId,importFingerprint(result),new Date().toISOString());
}
const readRows = db => {
  const hasReceipts = db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='asr_media_import_receipt'").get();
  const receipt = hasReceipts ? db.prepare('SELECT result_hash FROM asr_media_import_receipt WHERE keyword=? AND note_id=?') : null;
  return db.prepare(`
  SELECT j.keyword,j.note_id,j.status,j.media_path,j.transcript,j.audit_json,
         c.status AS candidate_status,c.result_json
  FROM asr_job j LEFT JOIN candidate c
    ON c.keyword=j.keyword AND c.note_id=j.note_id
  WHERE j.media_path IS NOT NULL
`).all().map(row => {
    let confirmed = false;
    try { confirmed = receipt?.get(row.keyword,row.note_id)?.result_hash === importFingerprint(JSON.parse(row.result_json)); } catch {}
    return {...row,import_confirmed:confirmed};
  });
};

// A local FULL-synchronous transaction has saved both transcript and article.
// SQL backfill can be replayed from this checkpoint without the original media.
export function canDeleteAsrMedia(row) {
  if (row.status !== "completed" || row.candidate_status !== "completed" || row.import_confirmed !== true) return false;
  try {
    const result = JSON.parse(row.result_json);
    const audit = JSON.parse(row.audit_json);
    const saved = result?.postTextAudit;
    if (!audit || !saved || saved.subtitle_source !== "audio_asr") return false;
    if (JSON.stringify(saved.subtitle_audit) !== JSON.stringify(audit)) return false;
    if (audit.quality?.accepted === false || needsAsrQualityRetry(result)) return false;
    const text = row.transcript || "";
    if ((result?.post?.["文章视频内容"] || "") !== text) return false;
    if (text.trim()) return audit.status === "ok" && saved.subtitle_status === "extracted";
    return noSpeech.has(audit.status) && saved.subtitle_status === "no_speech";
  } catch { return false; }
}

async function safeFile(root, target) {
  if (!inside(root, target)) return null;
  if (!/\.(mp4|m4a|m4s|webm|mov|mp3|wav|ogg|aac|flac|opus)$/i.test(target)) return null;
  // Reject junctions, symlinks and directories, including the media root.
  let current = target;
  let fileStat;
  for (;;) {
    const stat = await fs.lstat(current);
    if (stat.isSymbolicLink()) return null;
    if (current === target) {
      if (!stat.isFile() || stat.nlink > 1) return null;
      fileStat = stat;
    } else if (!stat.isDirectory()) return null;
    if (normalPath(current) === normalPath(root)) break;
    current = path.dirname(current);
  }
  if (normalPath(await fs.realpath(root)) !== normalPath(root)) return null;
  if (normalPath(await fs.realpath(target)) !== normalPath(target)) return null;
  return fileStat;
}

// Exact-file deletion only. Never walk media directories looking for "old" files.
export async function cleanupCompletedAsrMedia({ db, mediaDir, keepMedia = false, job = null, dryRun = false, onWarning = console.warn }) {
  const stats = { deleted: 0, eligible: 0, bytes: 0, retained: 0, missing: 0, errors: 0, dryRun };
  if (keepMedia) return stats;
  const root = path.resolve(mediaDir);
  const rows = readRows(db);
  const targets = new Set(rows.filter(row => !job || (row.keyword === job.keyword && row.note_id === job.noteId))
    .filter(row => row.media_path).map(row => path.resolve(row.media_path)));
  for (const target of targets) {
    try {
      const references = rows.filter(row => normalPath(row.media_path) === normalPath(target));
      if (!references.length || references.some(row => !canDeleteAsrMedia(row))) { stats.retained++; continue; }
      const stat = await safeFile(root, target);
      if (!stat) { stats.retained++; continue; }
      // Recheck after filesystem awaits: another local job may now need this file.
      const fresh = readRows(db).filter(row => normalPath(row.media_path) === normalPath(target));
      if (!fresh.length || fresh.some(row => !canDeleteAsrMedia(row))) { stats.retained++; continue; }
      if (!dryRun) await fs.unlink(target);
      stats.eligible++;
      stats.bytes += stat.size;
      if (!dryRun) stats.deleted++;
    } catch (error) {
      if (error.code === "ENOENT") { stats.missing++; continue; }
      stats.errors++;
      onWarning(`[ASR媒体清理] 文件保留，下次启动重试：${String(error.message || error).split("\n")[0]}`);
    }
  }
  return stats;
}
