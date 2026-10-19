import fs from "node:fs/promises";
import path from "node:path";
import { inTargetYear } from "./collection-policy.mjs";
import { DatabaseSync } from "node:sqlite";
import { POST_FIELDS, COMMENT_FIELDS, canonicalDouyinPostUrl } from "./schema.mjs";
import {normaliseCommentResult} from './comment-threads.mjs';

const now = () => new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Shanghai", dateStyle: "short", timeStyle: "medium", hourCycle: "h23"
}).format(new Date());

export function openCheckpoint(dbPath) {
  const db = new DatabaseSync(path.resolve(dbPath));
  db.exec("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA busy_timeout=5000;");
  db.exec(`
    CREATE TABLE IF NOT EXISTS candidate (
      keyword TEXT NOT NULL,
      note_id TEXT NOT NULL,
      url TEXT NOT NULL,
      candidate_index INTEGER NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      attempts INTEGER NOT NULL DEFAULT 0,
      result_json TEXT,
      last_error TEXT,
      updated_at TEXT NOT NULL,
      import_status TEXT NOT NULL DEFAULT 'pending',
      import_error TEXT,
      PRIMARY KEY(keyword, note_id)
    );
    CREATE TABLE IF NOT EXISTS run_meta (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS observed_search_transition_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      keyword TEXT NOT NULL,note_id TEXT NOT NULL,
      previous_candidate_json TEXT NOT NULL,evidence_json TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    -- 增量入库断点表：登记已写入 MySQL 的帖子/评论，异常终止后恢复时据此避免重复入库与漏库。
    CREATE TABLE IF NOT EXISTS note_dead_letter (
      keyword TEXT NOT NULL, note_id TEXT NOT NULL, url TEXT NOT NULL,
      reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'dead_letter',
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      PRIMARY KEY(keyword,note_id)
    );
    CREATE TABLE IF NOT EXISTS import_batch (
      keyword TEXT NOT NULL,
      batch_id TEXT NOT NULL,
      target_table TEXT NOT NULL,
      row_key TEXT NOT NULL,
      note_id TEXT,
      status TEXT NOT NULL DEFAULT 'imported',
      imported_at TEXT NOT NULL,
      PRIMARY KEY(keyword, target_table, row_key)
    );
    CREATE TABLE IF NOT EXISTS asr_job (
      keyword TEXT NOT NULL,
      note_id TEXT NOT NULL,
      article_id TEXT NOT NULL,
      media_url TEXT NOT NULL,
      media_path TEXT,
      referer TEXT,
      prompt TEXT,
      status TEXT NOT NULL DEFAULT 'pending',
      attempts INTEGER NOT NULL DEFAULT 0,
      max_attempts INTEGER NOT NULL DEFAULT 3,
      transcript TEXT,
      audit_json TEXT,
      last_error TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(keyword, note_id)
    );
    CREATE TABLE IF NOT EXISTS asr_source_refresh_history (
      keyword TEXT NOT NULL,note_id TEXT NOT NULL,old_job_json TEXT NOT NULL,
      old_candidate_json TEXT NOT NULL,new_media_url TEXT NOT NULL,created_at TEXT NOT NULL,
      PRIMARY KEY(keyword,note_id)
    );
    CREATE TABLE IF NOT EXISTS asr_source_resolution_history (
      keyword TEXT NOT NULL,note_id TEXT NOT NULL,old_job_json TEXT NOT NULL,
      old_candidate_json TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL,
      PRIMARY KEY(keyword,note_id)
    );
  `);
  const columns = new Set(db.prepare('PRAGMA table_info(candidate)').all().map(row => row.name));
  if (!columns.has('import_status')) db.exec("ALTER TABLE candidate ADD COLUMN import_status TEXT NOT NULL DEFAULT 'pending'");
  if (!columns.has('import_error')) db.exec('ALTER TABLE candidate ADD COLUMN import_error TEXT');
  // A killed process cannot still own a local download/inference operation.
  // Keep the durable job and retry only this video on the next start.
  db.prepare(`UPDATE asr_job SET status='retry_pending',last_error=COALESCE(last_error,'进程中断后恢复'),updated_at=?
    WHERE status IN ('downloading','running','waiting_import','partial_review')`).run(now());
  db.prepare("UPDATE asr_job SET status='dead_letter',last_error=COALESCE(last_error,'ASR_ATTEMPTS_EXHAUSTED'),updated_at=? WHERE status IN ('pending','retry_pending') AND attempts>=max_attempts").run(now());
  for(const row of db.prepare("SELECT keyword,note_id,last_error FROM asr_job WHERE status IN ('pending','retry_pending')").all()){
    if(expiredMediaSourceError(row.last_error))db.prepare("UPDATE asr_job SET status='waiting_source_refresh',updated_at=? WHERE keyword=? AND note_id=?").run(now(),row.keyword,row.note_id);
  }
  return db;
}

export function setMeta(db, key, value) {
  db.prepare(`INSERT INTO run_meta(key,value,updated_at) VALUES(?,?,?)
    ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at`)
    .run(String(key), JSON.stringify(value), now());
}

export function saveCandidates(db, keyword, links, offset = 0) {
  const statement = db.prepare(`INSERT INTO candidate(keyword,note_id,url,candidate_index,status,updated_at)
    VALUES(?,?,?,?, 'pending', ?)
    ON CONFLICT(keyword,note_id) DO UPDATE SET url=excluded.url,
      candidate_index=MIN(candidate.candidate_index,excluded.candidate_index),updated_at=excluded.updated_at`);
  db.exec("BEGIN IMMEDIATE");
  try {
    links.forEach((note, index) => statement.run(keyword, note.noteId, note.url, offset + index, now()));
    db.exec("COMMIT");
  } catch (error) {
    db.exec("ROLLBACK");
    throw error;
  }
}

export function checkpointCandidates(db, keyword) {
  return db.prepare("SELECT note_id AS noteId,url,candidate_index AS candidateIndex,status,attempts,result_json AS resultJson,last_error AS lastError,import_status AS importStatus,import_error AS importError FROM candidate WHERE keyword=? ORDER BY candidate_index,note_id").all(keyword).map(row => {
    let result = null;
    try { result = JSON.parse(row.resultJson); } catch {}
    const publishedAt = result?.post?.["文章时间地点"] || result?.publishedAt || null;
    return { ...row, result, publishedAt, projectName: result?.post?.["项目"] || null };
  });
}

export function markCompleted(db, keyword, note, result, {asrJob=null,asrMaxAttempts=3,observedSearchEvidence=null}={}) {
  // The article and its transcription intent must survive together, including
  // a crash or SQL failure before the base article import has finished.
  db.exec('BEGIN IMMEDIATE');
  try{
    const prior=db.prepare('SELECT * FROM candidate WHERE keyword=? AND note_id=?').get(keyword,note.noteId);
    if(observedSearchEvidence)archiveObservedSearchTransition(db,keyword,note.noteId,prior,observedSearchEvidence);
    const priorResult=prior?.result_json?JSON.parse(prior.result_json):null;
    const priorJob=db.prepare('SELECT status,transcript FROM asr_job WHERE keyword=? AND note_id=?').get(keyword,note.noteId);
    if(asrJob)refreshObservedMediaSource(db,asrJob,result);
    if(priorJob?.status==='completed'&&priorResult?.post?.内容类型==='视频'&&result?.post?.内容类型==='视频'){
      result.post.文章视频内容=priorJob.transcript;
      result.postTextAudit=priorResult.postTextAudit;
    }
    db.prepare(`UPDATE candidate SET status='completed',attempts=attempts+1,result_json=?,last_error=NULL,import_status='pending',import_error=NULL,updated_at=?
      WHERE keyword=? AND note_id=?`).run(JSON.stringify(result), now(), keyword, note.noteId);
    if(asrJob){
      enqueueAsrJob(db,asrJob,asrMaxAttempts);
      db.prepare("UPDATE asr_job SET status='waiting_import' WHERE keyword=? AND note_id=? AND status NOT IN ('completed','dead_letter','running','downloading','waiting_source_refresh')").run(keyword,note.noteId);
    }
    db.exec('COMMIT');
  }catch(error){db.exec('ROLLBACK');throw error;}
}

function archiveObservedSearchTransition(db,keyword,noteId,prior,evidence){
  if(!prior||evidence.keyword!==keyword||evidence.noteId!==String(noteId))throw new Error('OBSERVED_SEARCH_HISTORY_SCOPE_MISMATCH');
  db.prepare('INSERT INTO observed_search_transition_history(keyword,note_id,previous_candidate_json,evidence_json,created_at) VALUES(?,?,?,?,?)')
    .run(keyword,noteId,JSON.stringify(prior),JSON.stringify(evidence),now());
}

export function markSkipped(db, keyword, note, reason, publishedAt = null, {source='detail_page',observedSearchEvidence=null}={}) {
  if(observedSearchEvidence)db.exec('BEGIN IMMEDIATE');
  try{
    if(observedSearchEvidence){
      const prior=db.prepare('SELECT * FROM candidate WHERE keyword=? AND note_id=?').get(keyword,note.noteId);
      archiveObservedSearchTransition(db,keyword,note.noteId,prior,observedSearchEvidence);
    }
    db.prepare(`UPDATE candidate SET status='skipped_old',attempts=attempts+1,last_error=?,result_json=?,updated_at=?
      WHERE keyword=? AND note_id=?`).run(String(reason || ""), JSON.stringify({ publishedAt, source,
       ...(observedSearchEvidence?{searchResponseEvidence:observedSearchEvidence}:{}) }), now(), keyword, note.noteId);
    if(observedSearchEvidence)db.exec('COMMIT');
  }catch(error){if(observedSearchEvidence)db.exec('ROLLBACK');throw error;}
}

export function markFailed(db, keyword, note, error) {
  db.prepare(`UPDATE candidate SET status='failed',attempts=attempts+1,last_error=?,updated_at=?
    WHERE keyword=? AND note_id=?`).run(String(error?.message || error || "unknown error"), now(), keyword, note.noteId);
}

export function markImportPending(db, keyword, noteIds, error) {
  const update = db.prepare("UPDATE candidate SET import_status='pending',import_error=?,updated_at=? WHERE keyword=? AND note_id=? AND status='completed'");
  db.exec('BEGIN IMMEDIATE');
  try { for (const id of noteIds) update.run(String(error?.message || error), now(), keyword, id); db.exec('COMMIT'); }
  catch (e) { db.exec('ROLLBACK'); throw e; }
}

export function markBaseImported(db, keyword, noteIds) {
  const update = db.prepare("UPDATE candidate SET import_status='imported',import_error=NULL,updated_at=? WHERE keyword=? AND note_id=? AND status='completed'");
  db.exec('BEGIN IMMEDIATE');
  try { for (const id of noteIds) update.run(now(), keyword, id); db.exec('COMMIT'); }
  catch (e) { db.exec('ROLLBACK'); throw e; }
}

// Recover only durable articles demoted by the old SQL-stop bug. Keep any
// incomplete comment audit for ordinary detail recovery; never invent completion.
export function recoverSavedImportFailures(db, task, year = 2026) {
  const recovered = [];
  for (const row of checkpointCandidates(db, task.keyword)) {
    if (row.status !== 'failed' || !/^(?:STOP_REQUESTED：.*(?:入库|已安全停止)|MYSQL_IMPORT_LOCK_WAIT_TIMEOUT|Lock wait timeout exceeded|Deadlock found)/u.test(row.lastError || '')) continue;
    const post = row.result?.post;
    if (!post || String(post.文章id) !== row.noteId || post.平台 !== '抖音' || !post.项目 ||
        post.文章链接 !== canonicalDouyinPostUrl(row.noteId) || !post.作者id ||
        !inTargetYear(post.文章时间地点, year, task.cutoff || `${year}-01-01`) ||
        !['视频','图文'].includes(post.内容类型) ||
        (post.内容类型 === '视频' && !post.文章视频链接) || !Array.isArray(row.result.comments) ||
        (task.collectComments && typeof row.result.audit?.commentsComplete !== 'boolean')) continue;
    db.prepare("UPDATE candidate SET status='completed',import_status='pending',import_error=last_error,last_error=NULL,updated_at=? WHERE keyword=? AND note_id=? AND status='failed'")
      .run(now(), task.keyword, row.noteId);
    recovered.push(row.noteId);
  }
  return recovered;
}

export function enqueueAsrJob(db, job, maxAttempts = 3) {
  const timestamp = now();
  db.prepare(`INSERT INTO asr_job(keyword,note_id,article_id,media_url,media_path,referer,prompt,status,attempts,max_attempts,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?,'pending',0,?,?,?)
    ON CONFLICT(keyword,note_id) DO UPDATE SET
      article_id=excluded.article_id,media_url=CASE WHEN asr_job.status IN ('completed','dead_letter','running','downloading','waiting_source_refresh') THEN asr_job.media_url ELSE excluded.media_url END,
      media_path=COALESCE(asr_job.media_path,excluded.media_path),
      referer=excluded.referer,prompt=excluded.prompt,
      status=CASE
        WHEN asr_job.status IN ('completed','dead_letter','running','downloading','waiting_source_refresh') THEN asr_job.status
        ELSE 'pending'
      END,
      attempts=asr_job.attempts,
      max_attempts=asr_job.max_attempts,
      last_error=asr_job.last_error,
      updated_at=excluded.updated_at`)
    .run(String(job.keyword), String(job.noteId), String(job.articleId), String(job.mediaUrl), job.mediaPath || null,
      job.referer || null, job.prompt || null, Math.max(1, Number(maxAttempts) || 3), timestamp, timestamp);
}

export const expiredMediaSourceError=error=>/视频下载失败 HTTP (?:401|403|410)\b/.test(String(error?.message||error||''));

export function mediaSourceRecoveryIds(db,keyword){
 return db.prepare("SELECT note_id,last_error FROM asr_job WHERE keyword=? AND status IN ('pending','retry_pending','waiting_source_refresh','dead_letter')").all(keyword)
  .filter(row=>expiredMediaSourceError(row.last_error)&&!db.prepare('SELECT 1 FROM asr_source_refresh_history WHERE keyword=? AND note_id=?').get(keyword,row.note_id))
  .map(row=>String(row.note_id));
}

export function settleExpiredMediaGaps(db,keyword,{scanComplete=false}={}){
 if(scanComplete!==true)return [];
 const rows=db.prepare("SELECT * FROM asr_job WHERE keyword=? AND status='waiting_source_refresh'").all(keyword),settled=[];
 db.exec('BEGIN IMMEDIATE');
 try{
  for(const row of rows){
   if(!expiredMediaSourceError(row.last_error))continue;
   const candidate=db.prepare('SELECT * FROM candidate WHERE keyword=? AND note_id=?').get(keyword,row.note_id);
   if(!candidate)throw new Error('MEDIA_SOURCE_RESOLUTION_CANDIDATE_MISSING');
   db.prepare('INSERT OR IGNORE INTO asr_source_resolution_history(keyword,note_id,old_job_json,old_candidate_json,reason,created_at) VALUES(?,?,?,?,?,?)')
    .run(keyword,row.note_id,JSON.stringify(row),JSON.stringify(candidate),'verified_search_ended_without_usable_refreshed_source',now());
   db.prepare("UPDATE asr_job SET status='dead_letter',updated_at=? WHERE keyword=? AND note_id=? AND status='waiting_source_refresh'").run(now(),keyword,row.note_id);
   settled.push(row.note_id);
  }
  db.exec('COMMIT');return settled;
 }catch(error){db.exec('ROLLBACK');throw error;}
}

// Invoked only inside markCompleted's transaction, after an exact original
// detail response. One different source may receive one bounded extra attempt;
// lifetime attempts, old job and complete old candidate are never reset/lost.
function refreshObservedMediaSource(db,job,result){
 const old=db.prepare('SELECT * FROM asr_job WHERE keyword=? AND note_id=?').get(String(job.keyword),String(job.noteId));
 if(!old||!['pending','retry_pending','waiting_source_refresh','dead_letter'].includes(old.status)
  ||!expiredMediaSourceError(old.last_error)||job.sourceObserved!==true
  ||String(job.articleId)!==String(job.noteId)||String(result?.post?.文章id)!==String(job.noteId)
  ||String(result?.post?.文章视频链接)!==String(job.mediaUrl)||!job.mediaUrl||old.media_url===String(job.mediaUrl)
  ||db.prepare('SELECT 1 FROM asr_source_refresh_history WHERE keyword=? AND note_id=?').get(job.keyword,job.noteId))return false;
 const candidate=db.prepare('SELECT * FROM candidate WHERE keyword=? AND note_id=?').get(job.keyword,job.noteId);
 if(!candidate)throw new Error('MEDIA_SOURCE_REFRESH_CANDIDATE_MISSING');
 db.prepare('INSERT INTO asr_source_refresh_history(keyword,note_id,old_job_json,old_candidate_json,new_media_url,created_at) VALUES(?,?,?,?,?,?)')
  .run(job.keyword,job.noteId,JSON.stringify(old),JSON.stringify(candidate),String(job.mediaUrl),now());
 db.prepare("UPDATE asr_job SET status='pending',media_url=?,media_path=NULL,max_attempts=attempts+1,updated_at=? WHERE keyword=? AND note_id=?")
  .run(String(job.mediaUrl),now(),job.keyword,job.noteId);
 return true;
}

export function markNoteDeadLetter(db, keyword, note, error) {
  const message=String(error?.message||error),timestamp=now();
  db.exec('BEGIN IMMEDIATE');
  try{
    const changed=db.prepare("UPDATE candidate SET status='dead_letter',attempts=attempts+1,last_error=?,updated_at=? WHERE keyword=? AND note_id=?")
      .run(message,timestamp,keyword,note.noteId);
    if(Number(changed.changes)!==1)throw new Error('DEAD_LETTER_CANDIDATE_MISSING');
    db.prepare(`INSERT INTO note_dead_letter(keyword,note_id,url,reason,created_at,updated_at) VALUES(?,?,?,?,?,?)
      ON CONFLICT(keyword,note_id) DO UPDATE SET url=excluded.url,reason=excluded.reason,status='dead_letter',updated_at=excluded.updated_at`)
      .run(keyword,note.noteId,note.url,message,timestamp,timestamp);
    db.exec('COMMIT');
  }catch(error){db.exec('ROLLBACK');throw error;}
}

export function claimAsrJob(db) {
  db.exec("BEGIN IMMEDIATE");
  try {
    const row = db.prepare(`SELECT keyword,note_id AS noteId,article_id AS articleId,media_url AS mediaUrl,
      media_path AS mediaPath,referer,prompt,status,attempts,max_attempts AS maxAttempts
      FROM asr_job WHERE status IN ('pending','retry_pending') AND attempts < max_attempts
      ORDER BY updated_at,keyword,note_id LIMIT 1`).get();
    if (!row) {
      db.exec("COMMIT");
      return null;
    }
    const result = db.prepare(`UPDATE asr_job SET status='downloading',attempts=attempts+1,updated_at=?
      WHERE keyword=? AND note_id=? AND status IN ('pending','retry_pending') AND attempts=?`)
      .run(now(), row.keyword, row.noteId, row.attempts);
    if (Number(result.changes) !== 1) throw new Error(`ASR_CLAIM_CONFLICT：${row.keyword}/${row.noteId}`);
    db.exec("COMMIT");
    return { ...row, attempts: Number(row.attempts) + 1 };
  } catch (error) {
    db.exec("ROLLBACK");
    throw error;
  }
}

export function markAsrRunning(db, job, mediaPath) {
  db.prepare("UPDATE asr_job SET status='running',media_path=?,updated_at=? WHERE keyword=? AND note_id=?")
    .run(String(mediaPath), now(), job.keyword, job.noteId);
}

export function completeAsrJob(db, job, output) {
  const row = db.prepare("SELECT result_json AS resultJson FROM candidate WHERE keyword=? AND note_id=?").get(job.keyword, job.noteId);
  if (!row?.resultJson) throw new Error(`ASR_RESULT_MISSING：${job.keyword}/${job.noteId}没有文章断点`);
  const result = JSON.parse(row.resultJson);
  const noSpeechStatuses = new Set(["no_speech", "no_audio_track", "empty_audio_track", "silent_audio"]);
  const noSpeech = !output.text && noSpeechStatuses.has(output.audit?.status);
  if (output.audit?.quality?.accepted === false || (!output.text && !noSpeech)) {
    throw new Error('ASR_RESULT_UNVERIFIED：空白、质量拒绝或未知状态不能完成字幕作业');
  }
  result.post["文章视频内容"] = output.text || null;
  result.postTextAudit = {
    ...(result.postTextAudit || {}), subtitle_source: output.source || "audio_asr",
    subtitle_status: output.text ? "extracted" : noSpeech ? "no_speech" : "asr_failed",
    subtitle_error: null, subtitle_audit: output.audit || null
  };
  if (output.text && Array.isArray(result.audit?.missing)) {
    result.audit.missing = result.audit.missing.filter(field => field !== "文章视频内容");
  }
  db.exec("BEGIN IMMEDIATE");
  try {
    db.prepare("UPDATE candidate SET result_json=?,updated_at=? WHERE keyword=? AND note_id=?")
      .run(JSON.stringify(result), now(), job.keyword, job.noteId);
    db.prepare(`UPDATE asr_job SET status='completed',transcript=?,audit_json=?,last_error=NULL,updated_at=?
      WHERE keyword=? AND note_id=?`).run(output.text || null, JSON.stringify(output.audit || null), now(), job.keyword, job.noteId);
    db.exec("COMMIT");
  } catch (error) { db.exec("ROLLBACK"); throw error; }
  return result;
}

export function failAsrJob(db, job, error) {
  const expired=expiredMediaSourceError(error);
  const refreshed=expired&&Boolean(db.prepare('SELECT 1 FROM asr_source_refresh_history WHERE keyword=? AND note_id=?').get(job.keyword,job.noteId));
  const terminal = refreshed||(!expired&&Number(job.attempts) >= Number(job.maxAttempts || 3));
  const status = terminal ? "dead_letter" : expired ? 'waiting_source_refresh' : "retry_pending";
  const message = String(error?.message || error || "ASR失败").slice(0, 4000);
  db.exec("BEGIN IMMEDIATE");
  try {
    db.prepare("UPDATE asr_job SET status=?,last_error=?,updated_at=? WHERE keyword=? AND note_id=?")
      .run(status, message, now(), job.keyword, job.noteId);
    if (terminal) {
      const row = db.prepare("SELECT result_json AS resultJson FROM candidate WHERE keyword=? AND note_id=?").get(job.keyword, job.noteId);
      if (row?.resultJson) {
        const result = JSON.parse(row.resultJson);
        result.postTextAudit = { ...(result.postTextAudit || {}), subtitle_source: null,
          subtitle_status: "asr_failed", subtitle_error: message, subtitle_audit: error?.audit || null };
        db.prepare("UPDATE candidate SET result_json=?,updated_at=? WHERE keyword=? AND note_id=?")
          .run(JSON.stringify(result), now(), job.keyword, job.noteId);
      }
    }
    db.exec("COMMIT");
  } catch (dbError) { db.exec("ROLLBACK"); throw dbError; }
  return status;
}

/** Runtime/model resource failures are node-local. Preserve the video job for a
 * later cycle without consuming one of its content retry attempts. */
export function deferAsrJob(db, job, error) {
  const message = String(error?.message || error || "ASR运行环境暂不可用").slice(0, 4000);
  db.prepare(`UPDATE asr_job SET status='retry_pending',attempts=MAX(attempts-1,0),last_error=?,updated_at=?
    WHERE keyword=? AND note_id=?`).run(message, now(), job.keyword, job.noteId);
  return "retry_pending";
}

export function asrJobStats(db) {
  const counts = Object.fromEntries(db.prepare("SELECT status,COUNT(*) AS n FROM asr_job GROUP BY status").all().map(row => [row.status, Number(row.n)]));
  return { ...counts, pendingTotal: ["pending", "retry_pending", "downloading", "running", "waiting_import", "waiting_source_refresh"].reduce((sum, key) => sum + (counts[key] || 0), 0) };
}

/** 将一个增量入库批次涉及的帖子/评论登记进断点表；MySQL 侧按业务主键 upsert，重复入库不会产生重复行。 */
export function markImported(db, keyword, batchId, rows) {
  if (!rows.length) return;
  const statement = db.prepare(`INSERT INTO import_batch(keyword,batch_id,target_table,row_key,note_id,status,imported_at)
    VALUES(?,?,?,?,?, 'imported', ?)
    ON CONFLICT(keyword,target_table,row_key) DO UPDATE SET status='imported',batch_id=excluded.batch_id,imported_at=excluded.imported_at`);
  db.exec("BEGIN IMMEDIATE");
  try {
    rows.forEach((row) => statement.run(keyword, batchId, String(row.table), String(row.key), String(row.noteId || ""), now()));
    db.exec("COMMIT");
  } catch (error) {
    db.exec("ROLLBACK");
    throw error;
  }
}

export function importedStats(db, keyword) {
  const rows = db.prepare("SELECT target_table, COUNT(*) AS n FROM import_batch WHERE keyword=? GROUP BY target_table").all(keyword);
  return Object.fromEntries(rows.map((row) => [row.target_table, row.n]));
}

export function migrateCheckpointCommentThreads(db){
  const rows=db.prepare("SELECT keyword,note_id,result_json FROM candidate WHERE result_json IS NOT NULL").all();
  let changed=0,deferred=0;
  db.exec(`CREATE TABLE IF NOT EXISTS comment_thread_migration_backup(keyword TEXT NOT NULL,note_id TEXT NOT NULL,result_json TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(keyword,note_id)); BEGIN IMMEDIATE;`);
  try{
    for(const row of rows){
      let before;try{before=JSON.parse(row.result_json);}catch{continue;}
      const after=normaliseCommentResult(before);
      if(after.audit?.comments?.aggregation_mode==='legacy_unresolved')deferred++;
      if(after===before)continue;
      db.prepare('INSERT OR IGNORE INTO comment_thread_migration_backup(keyword,note_id,result_json,created_at) VALUES(?,?,?,?)').run(row.keyword,row.note_id,row.result_json,now());
      db.prepare("UPDATE candidate SET result_json=?,import_status='pending',updated_at=? WHERE keyword=? AND note_id=?").run(JSON.stringify(after),now(),row.keyword,row.note_id);changed++;
    }
    db.exec('COMMIT');
  }catch(error){db.exec('ROLLBACK');throw error;}
  return {changed,deferred};
}
export function completedResults(db) {
  return db.prepare("SELECT result_json FROM candidate WHERE status='completed' AND result_json IS NOT NULL ORDER BY keyword,candidate_index,note_id")
    .all().map((row) => normaliseCommentResult(JSON.parse(row.result_json)));
}

const speechKey = value => String(value || "").replace(/[^0-9A-Za-z\u4e00-\u9fff]+/g, "");
export function needsAsrQualityRetry(result) {
  const post = result?.post || {}, audit = result?.postTextAudit || {}, detail = audit.subtitle_audit || {};
  if (post["内容类型"] !== "视频" || audit.subtitle_source !== "audio_asr" || !post["文章视频内容"]) return false;
  const text = String(post["文章视频内容"]), duration = Number(detail.duration || post["文章视频时长"] || 0);
  const tooShort = duration >= 10 && speechKey(text).length < Math.max(8, Math.ceil(duration * 0.65));
  const lostSegments = duration >= 10 && Number(detail.segments || 0) === 0;
  const knownHallucination = /字幕\s*(?:by|来自|制作)|索兰娅|amara[.]org|优优独播剧场/i.test(text);
  return tooShort || lostSegments || knownHallucination || detail.quality?.accepted === false;
}

export function repairCheckpointDataQuality(db) {
  const rows = db.prepare("SELECT keyword,note_id,result_json FROM candidate WHERE status='completed' AND result_json IS NOT NULL").all();
  let links = 0, asr = 0;
  const update = db.prepare("UPDATE candidate SET result_json=?,updated_at=? WHERE keyword=? AND note_id=?");
  const resetAsr = db.prepare(`UPDATE asr_job SET status=CASE WHEN attempts>=max_attempts THEN 'dead_letter' ELSE 'retry_pending' END,last_error='ASR_QUALITY_RECHECK_REQUIRED',updated_at=? WHERE keyword=? AND note_id=?`);
  db.exec("BEGIN IMMEDIATE");
  try {
    for (const row of rows) {
      let result;
      try { result = JSON.parse(row.result_json); } catch { continue; }
      let changed = false;
      if (result.post) {
        const fixed = canonicalDouyinPostUrl(result.post["文章id"] || row.note_id, result.post["文章链接"]);
        if (fixed && fixed !== result.post["文章链接"]) { result.post["文章链接"] = fixed; links += 1; changed = true; }
        for (const comment of result.comments || []) if (comment["文章链接"] !== fixed) { comment["文章链接"] = fixed; changed = true; }
      }
      if (process.env.SOCIAL_VOLUME_ENABLED!=='1' && needsAsrQualityRetry(result)) {
        result.post["文章视频内容"] = null;
        result.postTextAudit = { ...(result.postTextAudit || {}), subtitle_source: null,
          subtitle_status: "asr_failed", subtitle_error: "ASR_QUALITY_RECHECK_REQUIRED" };
        resetAsr.run(now(), row.keyword, row.note_id);
        asr += 1; changed = true;
      }
      if (changed) update.run(JSON.stringify(result), now(), row.keyword, row.note_id);
    }
    db.exec("COMMIT");
  } catch (error) { db.exec("ROLLBACK"); throw error; }
  return { links, asr };
}

const csvCell = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
const csv = (rows, fields) => `\uFEFF${fields.map(csvCell).join(",")}\n${rows.map((row) => fields.map((field) => csvCell(row[field])).join(",")).join("\n")}\n`;

async function atomicWrite(file, content) {
  const temp = `${file}.tmp-${process.pid}`;
  await fs.writeFile(temp, content, "utf8");
  await fs.rename(temp, file);
}

export async function exportCheckpoint(db, outputDir, extra = {}) {
  await fs.mkdir(outputDir, { recursive: true });
  const taskLabels = {
    ...(extra.projectName ? { 项目: extra.projectName } : {}),
    // 旧断点中可能残留 true/1/旧概括值，恢复导出时一律纠正为 NULL。
    分类: null
  };
  const results = completedResults(db).filter(result => !extra.targetYear || inTargetYear(result?.post?.["文章时间地点"], extra.targetYear, extra.cutoff || `${extra.targetYear}-01-01`)).map(result => {
    const articleUrl = canonicalDouyinPostUrl(result?.post?.["文章id"], result?.post?.["文章链接"]);
    const rejectAsr = needsAsrQualityRetry(result);
    return {
      ...result,
      post: result.post && { ...result.post, ...taskLabels, 文章链接: articleUrl,
        ...(rejectAsr ? { 文章视频内容: null } : {}) },
      postTextAudit: rejectAsr ? { ...(result.postTextAudit || {}), subtitle_source: null,
        subtitle_status: "asr_failed", subtitle_error: "ASR_QUALITY_RECHECK_REQUIRED" } : result.postTextAudit,
      comments: extra.collectComments === false || result.audit?.comments?.aggregation_mode==='legacy_unresolved' ? [] : (result.comments || []).map(comment => ({ ...comment, ...taskLabels, 文章链接: articleUrl }))
    };
  });
  const posts = [...new Map(results.filter((x) => x?.post).map((x) => [`${x.post["平台"]}:${x.post["文章id"]}:${x.post["项目"]}`, x.post])).values()];
  const comments = [...new Map(results.flatMap((x) => x?.comments || []).map((x) => [`${x["平台"]}:${x["文章id"]}:${x["评论id"]}:${x["项目"]}`, x])).values()];
  const audits = results.flatMap((x) => x?.audit ? [x.audit] : []);
  const postTextAudits = results.flatMap((x) => x?.postTextAudit ? [x.postTextAudit] : []);
  const commentThreadAudits = results.flatMap((x) => x?.commentAudits || []);
  await atomicWrite(path.join(outputDir, "ods_social_media_post.jsonl"), posts.map(JSON.stringify).join("\n") + (posts.length ? "\n" : ""));
  await atomicWrite(path.join(outputDir, "ods_social_media_comment.jsonl"), comments.map(JSON.stringify).join("\n") + (comments.length ? "\n" : ""));
  await atomicWrite(path.join(outputDir, "ods_social_media_post.csv"), csv(posts, POST_FIELDS));
  await atomicWrite(path.join(outputDir, "ods_social_media_comment.csv"), csv(comments, COMMENT_FIELDS));
  await atomicWrite(path.join(outputDir, "人工质检清单.json"), JSON.stringify(audits, null, 2));
  await atomicWrite(path.join(outputDir, "post_text_audit.jsonl"), postTextAudits.map(JSON.stringify).join("\n") + (postTextAudits.length ? "\n" : ""));
  await atomicWrite(path.join(outputDir, "comment_thread_audit.jsonl"), commentThreadAudits.map(JSON.stringify).join("\n") + (commentThreadAudits.length ? "\n" : ""));
  const deadLetters=db.prepare("SELECT keyword,note_id AS noteId,url,reason,status,created_at AS createdAt,updated_at AS updatedAt FROM note_dead_letter WHERE status='dead_letter' ORDER BY keyword,note_id").all();
  await atomicWrite(path.join(outputDir,'note_dead_letters.jsonl'),deadLetters.map(JSON.stringify).join('\n')+(deadLetters.length?'\n':''));
  const sourceHistory=db.prepare('SELECT * FROM asr_source_refresh_history ORDER BY keyword,note_id').all();
  await atomicWrite(path.join(outputDir,'asr_source_refresh_history.jsonl'),sourceHistory.map(JSON.stringify).join('\n')+(sourceHistory.length?'\n':''));
  const sourceResolutions=db.prepare('SELECT * FROM asr_source_resolution_history ORDER BY keyword,note_id').all();
  await atomicWrite(path.join(outputDir,'asr_source_resolution_history.jsonl'),sourceResolutions.map(JSON.stringify).join('\n')+(sourceResolutions.length?'\n':''));
  const summary = { posts: posts.length, commentThreads: comments.length, checkpointedNotes: results.length, exportedAt: now(), ...extra,
    deadLetterNotes:deadLetters.length,collectionCompleteness:extra.collectionCompleteness || (deadLetters.length?'has_dead_letters':'no_dead_letters') };
  await atomicWrite(path.join(outputDir, "run_summary.json"), JSON.stringify(summary, null, 2));
  return { posts, comments, audits, postTextAudits, commentThreadAudits, summary };
}

export async function writeJsonAtomic(file, value) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  await atomicWrite(file, JSON.stringify(value, null, 2));
}
