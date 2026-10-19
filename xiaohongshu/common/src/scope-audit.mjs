import {assessKeywordScope} from './search-acceptance.mjs';
import {createHash} from 'node:crypto';

export function recordScope(db, keyword, note, result, assessment, {fresh=false}={}) {
  const stamp=new Date().toISOString();
  db.exec('BEGIN IMMEDIATE');
  try {
    const previous=db.prepare('SELECT * FROM candidate WHERE keyword=? AND note_id=?').get(keyword,note.noteId);
    const previousScope=db.prepare('SELECT * FROM scope_audit WHERE keyword=? AND note_id=?').get(keyword,note.noteId)||null;
    // Fresh observed evidence replaces the cached detail, but only after the
    // complete old checkpoint and keyed assessment are durably archived.
    if(previous?.result_json&&((fresh&&assessment.status==='out_of_scope')
      ||(previousScope&&previousScope.assessment_json!==JSON.stringify(assessment)))){
      const oldJson=JSON.stringify(previous),scopeJson=JSON.stringify(previousScope);
      const digest=createHash('sha256').update(JSON.stringify([oldJson,scopeJson])).digest('hex');
      db.prepare('INSERT OR IGNORE INTO scope_evidence_history VALUES(?,?,?,?,?,?)')
        .run(keyword,note.noteId,digest,oldJson,scopeJson,stamp);
    }
    db.prepare(`INSERT INTO scope_audit(keyword,note_id,assessment_json,checked_at) VALUES(?,?,?,?)
      ON CONFLICT(keyword,note_id) DO UPDATE SET assessment_json=excluded.assessment_json,checked_at=excluded.checked_at`)
      .run(keyword,note.noteId,JSON.stringify(assessment),stamp);
    if(assessment.status==='out_of_scope')db.prepare(`UPDATE candidate SET status='skipped_irrelevant',
      attempts=attempts+?,result_json=COALESCE(?,result_json,?),last_error='SCOPE_ENTITY_ANCHOR_NOT_OBSERVED',updated_at=? WHERE keyword=? AND note_id=?`)
      .run(fresh?1:0,fresh?JSON.stringify(result):null,JSON.stringify(result),stamp,keyword,note.noteId);
    else if(assessment.status==='unobserved')db.prepare("UPDATE candidate SET status='scope_unverified',last_error='SCOPE_DETAIL_CONTENT_NOT_OBSERVED',updated_at=? WHERE keyword=? AND note_id=?")
      .run(stamp,keyword,note.noteId);
    else if(previous?.result_json)db.prepare("UPDATE candidate SET status=?,last_error=NULL,updated_at=? WHERE keyword=? AND note_id=? AND status IN ('skipped_irrelevant','scope_unverified')")
      .run(assessment.status==='uncertain'?'pending':result?.post?'completed':'pending',stamp,keyword,note.noteId);
    db.exec('COMMIT');
  } catch(error){db.exec('ROLLBACK');throw error;}
}

export function auditExistingScope(db, keyword, options={}) {
  const rows=db.prepare("SELECT note_id AS noteId,result_json FROM candidate WHERE keyword=? AND result_json IS NOT NULL AND status IN ('completed','skipped_irrelevant','scope_unverified')").all(keyword);
  for(const row of rows){
    const result=JSON.parse(row.result_json);
    recordScope(db,keyword,row,result,assessKeywordScope(keyword,result,options));
  }
  return scopeSummary(db,keyword);
}

export function scopeSummary(db,keyword) {
  const rows=db.prepare("SELECT s.assessment_json FROM scope_audit s JOIN candidate c ON c.keyword=s.keyword AND c.note_id=s.note_id WHERE s.keyword=? AND c.status NOT IN ('skipped_old','dead_letter')").all(keyword);
  const counts={accepted:0,out_of_scope:0,uncertain:0,unobserved:0};
  for(const row of rows)counts[JSON.parse(row.assessment_json).status]++;
  const legacyImportedExcluded=Number(db.prepare(`SELECT COUNT(*) AS n FROM candidate c WHERE c.keyword=? AND c.status='skipped_irrelevant'
    AND EXISTS(SELECT 1 FROM import_batch b WHERE b.keyword=c.keyword AND b.note_id=c.note_id)`).get(keyword).n);
  return {...counts,legacyImportedExcluded,legacyDatabaseRowsRemoved:false};
}
