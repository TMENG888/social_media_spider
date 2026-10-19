import {createHash} from 'node:crypto';
import {postFromAweme,shanghaiTime} from './douyin-data.mjs';
import {inTargetYear} from './collection-policy.mjs';
import {entityRelevance} from './enterprise-relevance.mjs';

export const RESPONSE_RECOVERY_POLICY='20261016-current-keyword-observed-search-v1';
const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const observedDate=value=>{try{return shanghaiTime(value);}catch{return null;}};

// Only payloads emitted by the ordinary current keyword/latest search. Never
// use the global detail cache: it can contain pre-sort or another search data.
export function scopedSearchItems(items,{keyword,after}={}){
 if(typeof keyword!=='string'||!keyword.trim()||!Number.isFinite(after)||after<=0)
  throw new Error('SEARCH_RESPONSE_SCOPE_INVALID');
 const byId=new Map();
 for(const item of items){
  if(item.keyword!==keyword||item.latest!==true||!Number.isFinite(item.at)||item.at<after)continue;
  const id=String(item.raw?.aweme_id||'');
  if(!/^\d{15,22}$/.test(id))continue;
  if(!byId.has(id))byId.set(id,[]);
  byId.get(id).push(item);
 }
 return byId;
}

export function planObservedSearchItems({items,scope,task,notes,year=2026,cutoff=`${year}-01-01`}){
 if(task.keyword!==scope.keyword||!task.projectName)throw new Error('SEARCH_RESPONSE_TASK_SCOPE_MISMATCH');
 const scoped=scopedSearchItems(items,scope),oldAwemes=new Map(),oldEvidence=new Map(),conflictingIds=new Set(),recoverable=[],diagnostics=[];
 const evidenceFor=(item,noteId,publishedAt)=>({policy:RESPONSE_RECOVERY_POLICY,source:'ordinary_browser_current_latest_search',
  keyword:scope.keyword,searchStartedAt:scope.after,responseAt:item.at,noteId,publishedAt,payloadDigest:hash(item.raw)});
 for(const note of notes){
  if(!['pending','failed'].includes(note.status))continue;
  const observed=scoped.get(String(note.noteId))||[];
  const dates=[...new Set(observed.map(item=>observedDate(item.raw.create_time)).filter(Boolean))];
  const diag={noteId:String(note.noteId),status:note.status,attempts:note.attempts,
   seenInCurrentLatestSearch:observed.length>0,observations:observed.length,
   publishedAt:dates.length===1?dates[0]:null,reason:'not_observed_in_current_latest_search'};
  diagnostics.push(diag);
  if(!observed.length)continue;
  if(dates.length!==1){diag.reason=dates.length?'conflicting_observed_dates':'date_not_observed';if(dates.length)conflictingIds.add(String(note.noteId));continue;}
  const exact=observed.filter(item=>observedDate(item.raw.create_time)===dates[0]);
  if(!inTargetYear(dates[0],year,cutoff)){
   const item=exact.at(-1),id=String(note.noteId);
   oldAwemes.set(id,item.raw);oldEvidence.set(id,evidenceFor(item,id,dates[0]));diag.reason='verified_non_target_year';continue;
  }
  // Search metadata alone must never certify comments that were not read.
  if(task.collectComments!==false){diag.reason='detail_comments_required';continue;}
  let accepted=null,lastError=null;
  for(const item of exact.toReversed()){
   try{
    const result=postFromAweme(item.raw,task),relevance=entityRelevance(task.keyword,result.post);
    if(result.post.项目!==task.projectName){lastError='project_scope_mismatch';continue;}
    if(!relevance.accepted){lastError='relevance_not_confirmed';continue;}
    const evidence={...evidenceFor(item,String(note.noteId),dates[0]),relevance};
    result.audit.searchResponseEvidence=evidence;
    accepted={note,result,evidence};break;
   }catch(error){lastError=String(error.message).split('：')[0];}
  }
  if(accepted){recoverable.push(accepted);diag.reason='current_search_base_metadata_verified';}
  else diag.reason=lastError||'base_metadata_incomplete';
 }
 return {oldAwemes,oldEvidence,conflictingIds,recoverable,diagnostics};
}
