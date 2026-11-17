export const COVERAGE_SCOPE='20261114-target-year-no-lexical-filter-v1';

// Historical word-match exclusions no longer justify skipping a discovered note.
// The normal checkpoint audit preserves old evidence and reopens missing details.
export function verifiedScopeExclusion(){return null;}

// Compatibility name: presence of a saved article only, no semantic judgement.
// Year, identity, usable fields, comments and DB readback are checked by callers.
export function observedScopeRelevance(note){return Boolean(note.result?.post);}

export function attachScopeAudits(db,notes,keyword){
 if(!db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='scope_audit'").get())return notes;
 const proofs=new Map(db.prepare('SELECT keyword,note_id AS noteId,assessment_json,checked_at AS checkedAt FROM scope_audit WHERE keyword=?').all(keyword).map(row=>{
  let assessment;try{assessment=JSON.parse(row.assessment_json);}catch{assessment=null;}
  return [row.noteId,{keyword:row.keyword,noteId:row.noteId,checkedAt:row.checkedAt,assessment}];
 }));
 return notes.map(note=>({...note,scopeAudit:proofs.get(String(note.noteId))||null}));
}
