import {createHash} from 'node:crypto';
import {entityRelevance} from './enterprise-relevance.mjs';

export const COVERAGE_SCOPE='20261015-target-year-relevant-v2';
const SCOPE_POLICY='20261015-positive-scope-evidence-v2';
const normalize=value=>String(value||'').normalize('NFKC').toLowerCase().replace(/[\s\p{P}\p{S}]/gu,'');
const digest=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');

// Read only: an exclusion flag alone is never sufficient. Retain and recheck
// the keyed audit against the actual stored detail, not task labels/comments.
export function verifiedScopeExclusion(note,keyword){
 if(note.status!=='skipped_irrelevant'||!String(keyword||'').trim())return null;
 const proof=note.scopeAudit,a=proof?.assessment,r=note.result;
 if(proof?.noteId!==String(note.noteId)||proof?.keyword!==keyword||!Number.isFinite(Date.parse(proof?.checkedAt)))return null;
 if(a?.policy!==SCOPE_POLICY||a.status!=='out_of_scope'||a.reason!=='configured_other_entity_observed'||!Array.isArray(a.matches)||a.matches.length)return null;
 const anchor=String(keyword).trim().split(/\s+/)[0];
 if(normalize(anchor).length<2||!Array.isArray(a.anchors)||a.anchors.length!==1||normalize(a.anchors[0])!==normalize(anchor))return null;
 if(r?.post&&String(r.post.文章id)!==String(note.noteId))return null;
 if(!r?.post&&!(r?.outsideScope===true&&r.scopeEvidence))return null;
 const p=r.post||r.scopeEvidence;
 if(entityRelevance(keyword,p).accepted)return null;
 const fields={title:p.文章标题??p.title,body:p.文章内容??p.body,tags:p.文章标签??p.tags,subtitle:p.文章视频内容??p.subtitle};
 const text=Object.values(fields).map(v=>normalize(Array.isArray(v)?v.join(' '):v));
 // Empty details and tags-only observations are uncertain, not exclusions.
 if(!normalize(fields.title)&&!normalize(fields.body))return null;
 if(text.some(value=>value.includes(normalize(anchor))))return null;
 // Absence of the full query name is not evidence of irrelevance. A narrow,
 // explicitly configured conflicting entity must be observed in the detail.
 const conflict=a.exclusion;
 if(conflict?.kind!=='configured_entity'||normalize(conflict.entity).length<2
  ||!['title','body'].includes(conflict.field)
  ||!normalize(fields[conflict.field]).includes(normalize(conflict.entity))
  ||normalize(anchor).includes(normalize(conflict.entity))
  ||normalize(conflict.entity).includes(normalize(anchor)))return null;
 return {noteId:String(note.noteId),reason:a.reason,assessmentPolicy:a.policy,
  checkedAt:proof.checkedAt,evidenceDigest:digest({keyword,noteId:note.noteId,fields,assessment:a})};
}

export function observedScopeRelevance(note,keyword){
 if(!String(keyword||'').trim())return true; // Unscoped diagnostic callers only.
 const p=note.result?.post;
 if(!p)return false;
 return entityRelevance(keyword,p).accepted;
}

export function attachScopeAudits(db,notes,keyword){
 if(!db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='scope_audit'").get())return notes;
 const proofs=new Map(db.prepare('SELECT keyword,note_id AS noteId,assessment_json,checked_at AS checkedAt FROM scope_audit WHERE keyword=?').all(keyword).map(row=>{
  let assessment;try{assessment=JSON.parse(row.assessment_json);}catch{assessment=null;}
  return [row.noteId,{keyword:row.keyword,noteId:row.noteId,checkedAt:row.checkedAt,assessment}];
 }));
 return notes.map(note=>({...note,scopeAudit:proofs.get(String(note.noteId))||null}));
}
