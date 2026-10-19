import fs from "node:fs/promises";
import path from "node:path";
import { inTargetYear } from "./collection-policy.mjs";
import { DatabaseSync } from "node:sqlite";
import { POST_FIELDS, COMMENT_FIELDS, canonicalXhsNoteUrl } from "./schema.mjs";
import {assertMediaProvenance,MEDIA_BINDING_VERSION} from './media-provenance.mjs';

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
      PRIMARY KEY(keyword, note_id)
    );
    CREATE TABLE IF NOT EXISTS run_meta (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS scope_audit (
      keyword TEXT NOT NULL,note_id TEXT NOT NULL,assessment_json TEXT NOT NULL,
      checked_at TEXT NOT NULL,PRIMARY KEY(keyword,note_id)
    );
    CREATE TABLE IF NOT EXISTS scope_evidence_history (
      keyword TEXT NOT NULL,note_id TEXT NOT NULL,evidence_hash TEXT NOT NULL,
      previous_candidate_json TEXT NOT NULL,previous_scope_json TEXT,
      replaced_at TEXT NOT NULL,PRIMARY KEY(keyword,note_id,evidence_hash)
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
  `);
  if(!db.prepare('PRAGMA table_info(asr_job)').all().some(c=>c.name==='binding_json'))db.exec('ALTER TABLE asr_job ADD COLUMN binding_json TEXT');
  db.exec(`CREATE TABLE IF NOT EXISTS media_correction_history (
    keyword TEXT NOT NULL,note_id TEXT NOT NULL,version TEXT NOT NULL,
    original_result TEXT,original_job TEXT,created_at TEXT NOT NULL,
    PRIMARY KEY(keyword,note_id,version))`);
  // A killed process cannot still own a local download/inference operation.
  // Keep the durable job and retry only this video on the next start.
  db.prepare(`UPDATE asr_job SET status='retry_pending',last_error=COALESCE(last_error,'进程中断后恢复'),updated_at=?
    WHERE status IN ('downloading','running','waiting_import','partial_review')`).run(now());
  db.prepare("UPDATE asr_job SET status='dead_letter',last_error=COALESCE(last_error,'ASR_ATTEMPTS_EXHAUSTED'),updated_at=? WHERE status IN ('pending','retry_pending') AND attempts>=max_attempts").run(now());
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
  return db.prepare("SELECT note_id AS noteId,url,candidate_index AS candidateIndex,status,attempts,result_json AS resultJson,last_error AS lastError FROM candidate WHERE keyword=? ORDER BY candidate_index,note_id").all(keyword).map(row => {
    let result = null;
    try { result = JSON.parse(row.resultJson); } catch {}
    const publishedAt = result?.post?.["文章时间地点"] || result?.publishedAt || null;
    return { ...row, result, publishedAt, projectName: result?.post?.["项目"] || null };
  });
}

export function markCompleted(db, keyword, note, result, {asrJob=null,asrMaxAttempts=3}={}) {
  // The article and its transcription intent must survive together, including
  // a crash or SQL failure before the base article import has finished.
  db.exec('BEGIN IMMEDIATE');
  try{
    retainCompletedAsrEvidence(db,keyword,note.noteId,result);
    db.prepare(`UPDATE candidate SET status='completed',attempts=attempts+1,result_json=?,last_error=NULL,updated_at=?
      WHERE keyword=? AND note_id=?`).run(JSON.stringify(result), now(), keyword, note.noteId);
    if(asrJob){
      enqueueAsrJob(db,asrJob,asrMaxAttempts);
      db.prepare("UPDATE asr_job SET status='waiting_import' WHERE keyword=? AND note_id=? AND status NOT IN ('completed','dead_letter','running','downloading')").run(keyword,note.noteId);
    }
    db.exec('COMMIT');
  }catch(error){db.exec('ROLLBACK');throw error;}
}

function retainCompletedAsrEvidence(db,keyword,noteId,result) {
  // Detail refreshes must not erase an already verified background transcript.
  // Restore only blank fields with the same article identity and a trustworthy
  // durable audit; never overwrite a new nonempty text or revive failed jobs.
  if(!result?.post || result.post.内容类型!=='视频' || String(result.post.文章视频内容||'').trim())return false;
  const job=db.prepare('SELECT status,article_id,transcript,audit_json,media_url,binding_json FROM asr_job WHERE keyword=? AND note_id=?').get(keyword,noteId);
  if(job?.status!=='completed'||String(job.article_id)!==String(result.post.文章id))return false;
  let audit;try{audit=JSON.parse(job.audit_json||'null');}catch{return false;}
  try{assertMediaProvenance(JSON.parse(job.binding_json||'null'),{noteId,url:job.media_url,duration:audit?.duration});}catch{return false;}
  const currentDuration=Number(result.mediaProvenance?.expectedDuration);
  if(!(currentDuration>0)||Math.abs(currentDuration-Number(audit.duration))>Math.max(2,currentDuration*.03))return false;
  const text=String(job.transcript||'');
  const noSpeech=!text&&['no_speech','no_audio_track','empty_audio_track','silent_audio'].includes(audit?.status);
  if(audit?.quality?.accepted===false||(!noSpeech&&(!text||audit?.status!=='ok')))return false;
  const before=JSON.stringify(result);
  result.post.文章视频内容=text||null;
  result.postTextAudit={...(result.postTextAudit||{}),subtitle_source:'audio_asr',
    subtitle_status:text?'extracted':'no_speech',subtitle_error:null,subtitle_audit:audit};
  return JSON.stringify(result)!==before;
}

export function markSkipped(db, keyword, note, reason, publishedAt = null) {
  db.prepare(`UPDATE candidate SET status='skipped_old',attempts=attempts+1,last_error=?,result_json=?,updated_at=?
    WHERE keyword=? AND note_id=?`).run(String(reason || ""), JSON.stringify({ publishedAt, source: "detail_page" }), now(), keyword, note.noteId);
}

export function markFailed(db, keyword, note, error, maxAttempts = 3) {
  db.prepare(`UPDATE candidate SET status='failed',attempts=attempts+1,last_error=?,updated_at=?
    WHERE keyword=? AND note_id=?`).run(String(error?.message || error || "unknown error"), now(), keyword, note.noteId);
  const row=db.prepare("SELECT attempts FROM candidate WHERE keyword=? AND note_id=?").get(keyword,note.noteId);
  if(Number(row?.attempts)>=maxAttempts){
    // Keep the actual failure count; do not manufacture another attempt.
    return markNoteDeadLetter(db,keyword,note,error,maxAttempts,false);
  }
  return 'failed';
}

export function enqueueAsrJob(db, job, maxAttempts = 3) {
  const timestamp = now();
  const previous=db.prepare('SELECT * FROM asr_job WHERE keyword=? AND note_id=?').get(job.keyword,job.noteId);
  // Completed, verified evidence belongs to its original source. A refreshed
  // signed URL must not rewrite its provenance underneath that evidence.
  if(previous?.status==='completed'){
    let verified=null;try{verified=assertMediaProvenance(JSON.parse(previous.binding_json||'null'),{noteId:job.noteId,url:previous.media_url,duration:JSON.parse(previous.audit_json||'null')?.duration});}catch{}
    if(verified){
      const expected=Number(job.mediaBinding?.expectedDuration);
      if(!(expected>0)||Math.abs(expected-verified.decodedDuration)>Math.max(2,expected*.03))throw new Error('MEDIA_NOTE_CONTENT_CHANGED：此前核验媒体与当前详情时长冲突');
      return;
    }
  }
  const changed=previous&&previous.media_url!==job.mediaUrl;
  if(changed&&['running','downloading'].includes(previous.status))throw new Error('MEDIA_SOURCE_CHANGE_WHILE_RUNNING');
  const ownsTransaction=!db.isTransaction;
  if(ownsTransaction)db.exec('BEGIN IMMEDIATE');
  try{
  let priorBinding;try{priorBinding=JSON.parse(previous?.binding_json||'null');}catch{}
  if(previous&&previous.status!=='quarantined'&&priorBinding?.version!==MEDIA_BINDING_VERSION&&job.mediaBinding?.version===MEDIA_BINDING_VERSION){
    const candidate=db.prepare('SELECT result_json,attempts FROM candidate WHERE keyword=? AND note_id=?').get(job.keyword,job.noteId);
    const archived=db.prepare('INSERT OR IGNORE INTO media_correction_history VALUES(?,?,?,?,?,?)')
      .run(job.keyword,job.noteId,MEDIA_BINDING_VERSION,candidate?.result_json||null,JSON.stringify({...previous,candidateAttempts:candidate?.attempts||0}),timestamp);
    if(!Number(archived.changes))throw new Error('MEDIA_LEGACY_CORRECTION_ALREADY_CONSUMED');
    db.prepare("UPDATE asr_job SET status='quarantined' WHERE keyword=? AND note_id=?").run(job.keyword,job.noteId);
    previous.status='quarantined';
  }
  db.prepare(`INSERT INTO asr_job(keyword,note_id,article_id,media_url,media_path,referer,prompt,status,attempts,max_attempts,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?,'pending',0,?,?,?)
    ON CONFLICT(keyword,note_id) DO UPDATE SET
      article_id=excluded.article_id,media_url=excluded.media_url,
      media_path=CASE WHEN asr_job.media_url=excluded.media_url THEN asr_job.media_path ELSE NULL END,
      referer=excluded.referer,prompt=excluded.prompt,
      status=CASE
        WHEN asr_job.status IN ('completed','dead_letter','running','downloading') THEN asr_job.status
        ELSE 'pending'
      END,
      attempts=asr_job.attempts,
      max_attempts=asr_job.max_attempts,
      last_error=asr_job.last_error,
      updated_at=excluded.updated_at`)
    .run(String(job.keyword), String(job.noteId), String(job.articleId), String(job.mediaUrl), job.mediaPath || null,
      job.referer || null, job.prompt || null, Math.max(1, Number(maxAttempts) || 3), timestamp, timestamp);
  db.prepare('UPDATE asr_job SET binding_json=? WHERE keyword=? AND note_id=?').run(JSON.stringify(job.mediaBinding||null),job.keyword,job.noteId);
  if(previous?.status==='quarantined'){
    // Exactly one correction budget per migration; cumulative attempts/history
    // are retained. Reopening the process or refreshing URLs grants no budget.
    db.prepare("UPDATE asr_job SET status='pending',media_path=NULL,max_attempts=attempts+?,transcript=NULL,audit_json=NULL WHERE keyword=? AND note_id=?")
      .run(Math.max(1,Number(maxAttempts)||3),job.keyword,job.noteId);
  }
  if(ownsTransaction)db.exec('COMMIT');
  }catch(error){if(ownsTransaction)db.exec('ROLLBACK');throw error;}
}

export function markNoteDeadLetter(db, keyword, note, error, maxAttempts=3, countAttempt=true) {
  const message=String(error?.message||error),timestamp=now();
  db.exec('BEGIN IMMEDIATE');
  try{
    const row=db.prepare("SELECT attempts FROM candidate WHERE keyword=? AND note_id=?").get(keyword,note.noteId);
    const attempts=Number(row?.attempts||0)+(countAttempt?1:0);
    const status=attempts>=maxAttempts?'dead_letter':'failed';
    const changed=db.prepare("UPDATE candidate SET status=?,attempts=?,last_error=?,updated_at=? WHERE keyword=? AND note_id=?")
      .run(status,attempts,message,timestamp,keyword,note.noteId);
    if(Number(changed.changes)!==1)throw new Error('DEAD_LETTER_CANDIDATE_MISSING');
    db.prepare(`INSERT INTO note_dead_letter(keyword,note_id,url,reason,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)
      ON CONFLICT(keyword,note_id) DO UPDATE SET url=excluded.url,reason=excluded.reason,status=excluded.status,updated_at=excluded.updated_at`)
      .run(keyword,note.noteId,note.url,message,status==='dead_letter'?'dead_letter':'retry_pending',timestamp,timestamp);
    db.exec('COMMIT');
    return status;
  }catch(error){db.exec('ROLLBACK');throw error;}
}

export function claimAsrJob(db) {
  db.exec("BEGIN IMMEDIATE");
  try {
    const row = db.prepare(`SELECT keyword,note_id AS noteId,article_id AS articleId,media_url AS mediaUrl,
      media_path AS mediaPath,referer,prompt,status,attempts,max_attempts AS maxAttempts,binding_json AS bindingJson
      FROM asr_job WHERE status IN ('pending','retry_pending') AND attempts < max_attempts
      AND NOT EXISTS(SELECT 1 FROM candidate c WHERE c.keyword=asr_job.keyword AND c.note_id=asr_job.note_id AND c.status='skipped_irrelevant')
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
    return { ...row, mediaBinding:JSON.parse(row.bindingJson||'null'), attempts: Number(row.attempts) + 1 };
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
  const provenance=assertMediaProvenance(job.mediaBinding,{noteId:job.noteId,url:job.mediaUrl,duration:output.audit?.duration});
  output={...output,audit:{...output.audit,mediaProvenance:provenance}};
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

export function quarantineUnverifiedMedia(db) {
  const rows=db.prepare("SELECT keyword,note_id,result_json,attempts FROM candidate WHERE status='completed' AND result_json IS NOT NULL").all();
  let count=0;
  db.exec('BEGIN IMMEDIATE');
  try{
  for(const row of rows){
    let result;try{result=JSON.parse(row.result_json);}catch{continue;}
    if(result?.post?.内容类型!=='视频')continue;
    const job=db.prepare('SELECT * FROM asr_job WHERE keyword=? AND note_id=?').get(row.keyword,row.note_id);
    const binding=result.mediaProvenance;
    if(binding?.version===MEDIA_BINDING_VERSION&&binding.identityVerified===true)continue;
    const archived=db.prepare('INSERT OR IGNORE INTO media_correction_history VALUES(?,?,?,?,?,?)')
      .run(row.keyword,row.note_id,MEDIA_BINDING_VERSION,row.result_json,JSON.stringify({...job,candidateAttempts:row.attempts}),now());
    if(!Number(archived.changes))continue;
    // Preserve the original evidence before making it ineligible for export.
    result.post.文章视频内容=null;result.post.文章视频链接=null;
    result.postTextAudit={...result.postTextAudit,subtitle_source:null,subtitle_status:'source_recheck_required',subtitle_error:'MEDIA_LEGACY_SOURCE_UNVERIFIED'};
    db.prepare("UPDATE candidate SET status='failed',result_json=?,last_error='MEDIA_LEGACY_SOURCE_UNVERIFIED',updated_at=? WHERE keyword=? AND note_id=?")
      .run(JSON.stringify(result),now(),row.keyword,row.note_id);
    db.prepare("UPDATE asr_job SET status='quarantined',last_error='MEDIA_LEGACY_SOURCE_UNVERIFIED',updated_at=? WHERE keyword=? AND note_id=?")
      .run(now(),row.keyword,row.note_id);count++;
  }
    db.exec('COMMIT');return count;
  }catch(error){db.exec('ROLLBACK');throw error;}
}

export function detailAttemptLimit(db,keyword,noteId){
  const history=db.prepare('SELECT original_job FROM media_correction_history WHERE keyword=? AND note_id=? AND version=?').get(keyword,noteId,MEDIA_BINDING_VERSION);
  let prior;try{prior=JSON.parse(history?.original_job||'null');}catch{}
  return Number.isSafeInteger(prior?.candidateAttempts)?Math.max(3,prior.candidateAttempts+3):3;
}

export function failAsrJob(db, job, error) {
  const terminal = Number(job.attempts) >= Number(job.maxAttempts || 3);
  const status = terminal ? "dead_letter" : "retry_pending";
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
  const counts = Object.fromEntries(db.prepare("SELECT status,COUNT(*) AS n FROM asr_job WHERE NOT EXISTS(SELECT 1 FROM candidate c WHERE c.keyword=asr_job.keyword AND c.note_id=asr_job.note_id AND c.status='skipped_irrelevant') GROUP BY status").all().map(row => [row.status, Number(row.n)]));
  return { ...counts, pendingTotal: ["pending", "retry_pending", "downloading", "running", "waiting_import"].reduce((sum, key) => sum + (counts[key] || 0), 0) };
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

export function completedResults(db) {
  return db.prepare("SELECT result_json FROM candidate WHERE status='completed' AND result_json IS NOT NULL ORDER BY keyword,candidate_index,note_id")
    .all().map((row) => JSON.parse(row.result_json));
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
  const quarantinedMedia=quarantineUnverifiedMedia(db);
  const rows = db.prepare("SELECT keyword,note_id,result_json FROM candidate WHERE status='completed' AND result_json IS NOT NULL").all();
  let links = 0, asr = 0, restoredAsr = 0;
  const update = db.prepare("UPDATE candidate SET result_json=?,updated_at=? WHERE keyword=? AND note_id=?");
  const resetAsr = db.prepare(`UPDATE asr_job SET status=CASE WHEN attempts>=max_attempts THEN 'dead_letter' ELSE 'retry_pending' END,last_error='ASR_QUALITY_RECHECK_REQUIRED',updated_at=? WHERE keyword=? AND note_id=?`);
  db.exec("BEGIN IMMEDIATE");
  try {
    for (const row of rows) {
      let result;
      try { result = JSON.parse(row.result_json); } catch { continue; }
      let changed = false;
      if(retainCompletedAsrEvidence(db,row.keyword,row.note_id,result)){
        restoredAsr += 1; changed = true;
      }
      if (result.post) {
        const fixed = canonicalXhsNoteUrl(result.post["文章id"] || row.note_id, result.post["文章链接"]);
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
  return { links, asr, restoredAsr,quarantinedMedia };
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
    const articleUrl = canonicalXhsNoteUrl(result?.post?.["文章id"], result?.post?.["文章链接"]);
    const rejectAsr = needsAsrQualityRetry(result);
    return {
      ...result,
      post: result.post && { ...result.post, ...taskLabels, 文章链接: articleUrl,
        ...(rejectAsr ? { 文章视频内容: null } : {}) },
      postTextAudit: rejectAsr ? { ...(result.postTextAudit || {}), subtitle_source: null,
        subtitle_status: "asr_failed", subtitle_error: "ASR_QUALITY_RECHECK_REQUIRED" } : result.postTextAudit,
      comments: extra.collectComments === false ? [] : (result.comments || []).map(comment => ({ ...comment, ...taskLabels, 文章链接: articleUrl }))
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
  const scopeAudits=db.prepare('SELECT keyword,note_id AS noteId,assessment_json,checked_at AS checkedAt FROM scope_audit ORDER BY keyword,note_id').all()
    .map(({assessment_json,...row})=>({...row,assessment:JSON.parse(assessment_json)}));
  await atomicWrite(path.join(outputDir,'scope_audit.jsonl'),scopeAudits.map(JSON.stringify).join('\n')+(scopeAudits.length?'\n':''));
  const scopeHistory=db.prepare('SELECT * FROM scope_evidence_history ORDER BY keyword,note_id,replaced_at,evidence_hash').all();
  await atomicWrite(path.join(outputDir,'scope_evidence_history.jsonl'),scopeHistory.map(JSON.stringify).join('\n')+(scopeHistory.length?'\n':''));
  const excluded=db.prepare("SELECT keyword,note_id AS noteId,result_json FROM candidate WHERE status='skipped_irrelevant' ORDER BY keyword,note_id").all()
    .map(({result_json,...row})=>({...row,result:JSON.parse(result_json||'null')}));
  await atomicWrite(path.join(outputDir,'excluded_scope_records.jsonl'),excluded.map(JSON.stringify).join('\n')+(excluded.length?'\n':''));
  const summary = { posts: posts.length, commentThreads: comments.length, checkpointedNotes: results.length, exportedAt: now(), ...extra,
    deadLetterNotes:deadLetters.length,collectionCompleteness:deadLetters.length?'has_dead_letters':'no_dead_letters' };
  await atomicWrite(path.join(outputDir, "run_summary.json"), JSON.stringify(summary, null, 2));
  return { posts, comments, audits, postTextAudits, commentThreadAudits, summary };
}

export async function writeJsonAtomic(file, value) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  await atomicWrite(file, JSON.stringify(value, null, 2));
}
