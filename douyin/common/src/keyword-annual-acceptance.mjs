import {createHash} from 'node:crypto';
export const ANNUAL_COMPLETION_POLICY='20261016-keyword-p80-or-low-year-v2';
export const ANNUAL_MINIMUM_DATABASE_COVERAGE=0.8;
const sourcePolicies=new Set(['20261014-verified-search-end-v1','douyin-latest-pagination-and-ui-v1','20261015-bound-search-end-v1']);
const integer=value=>Number.isSafeInteger(value)&&value>=0;
const stamp=value=>typeof value==='string'?Date.parse(value):NaN;
const digest=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const reject=reason=>({ok:false,policy:ANNUAL_COMPLETION_POLICY,reason});
const forbiddenError=/(?:STOP_|LOGIN|CAPTCHA|SECURITY|RESTRICTION|COOLDOWN|LEASE|DATABASE|MYSQL|IMPORT|CONTEXT|TIMEOUT|GATEWAY|SEARCH_LIMIT|SEARCH_STAGNANT|SEARCH_END_UNVERIFIED|UNAVAILABLE)/i;

/** A low-volume close ends the ORIGINAL keyword, not individual missing items.
 * Unknown dates, dead letters and unlocated results remain in the upper bound.
 * This proves a bound on available browser-search results, not platform recall.
 */
export function assessAnnualLowVolume(decision,{scan,inventory,error=null,year=2026}={}, {now=Date.now(),maxScanAgeMs=1800000}={}){
 if(!decision||decision.dbReadbackVerified!==true||decision.subtitleQualityRequired!==false||decision.qualityVerified!==false
  ||!integer(decision.posts)||!integer(decision.threshold)||decision.threshold<1||!decision.taskId||!decision.keyword||!decision.projectName)
  return reject('ANNUAL_SQL_EVIDENCE_INVALID');
 const checkedAt=stamp(decision.checkedAt);
 if(!Number.isFinite(checkedAt)||now-checkedAt>60000||checkedAt>now+1000)return reject('ANNUAL_SQL_EVIDENCE_STALE');
 if(decision.posts>=decision.threshold)return reject('USE_QUANTITY_COMPLETION');
 if(error&&error!=='VOLUME_BELOW_THRESHOLD'&&error!=='KNOWN_CANDIDATES_INCOMPLETE')return reject('ANNUAL_COLLECTOR_ERROR');
 if(error&&forbiddenError.test(error))return reject('ANNUAL_COLLECTOR_ERROR');
 if(!scan||!sourcePolicies.has(scan.policy)||scan.ok!==true||scan.keyword!==decision.keyword
  ||scan.taskId!==decision.taskId||scan.projectName!==decision.projectName||scan.year!==year
  ||scan.startedAtTop!==true||(scan.latestConfirmed!==true
   &&!(scan.policy==='20261015-bound-search-end-v1'&&scan.orderIndependentExhaustiveScan===true))
  ||scan.scope!=='platform_current_visible_results'||!integer(scan.observations)||scan.observations<2)
  return reject('ANNUAL_SEARCH_END_UNVERIFIED');
 const started=stamp(scan.startedAt),finished=stamp(scan.finishedAt);
 if(!Number.isFinite(started)||!Number.isFinite(finished)||finished<started||finished>now+1000||now-finished>maxScanAgeMs)
  return reject('ANNUAL_SEARCH_RUN_STALE');
 if(!Array.isArray(inventory)||!integer(year)||year<2000)return reject('ANNUAL_INVENTORY_INVALID');
 const known=new Set(),unknown=[],imported=[],excluded=[];
 for(const row of inventory){
  if(!row||typeof row.noteId!=='string'||!row.noteId||known.has(row.noteId))return reject('ANNUAL_INVENTORY_INVALID');
  known.add(row.noteId);
  if(row.keyword!==decision.keyword||row.projectName!==decision.projectName)return reject('ANNUAL_INVENTORY_SCOPE_MISMATCH');
  if(row.disposition==='imported_current_year'){
   if(row.year!==year||row.importVerified!==true)return reject('ANNUAL_IMPORT_UNVERIFIED');
   imported.push(row.noteId);
  }else if(row.disposition==='excluded_old'){
   if(!integer(row.year)||row.year===year||row.dateVerified!==true)return reject('ANNUAL_DATE_EXCLUSION_UNVERIFIED');
   excluded.push(row.noteId);
  }else if(row.disposition==='excluded_irrelevant'){
   if(row.scopeVerified!==true)return reject('ANNUAL_SCOPE_EXCLUSION_UNVERIFIED');
   excluded.push(row.noteId);
  }else if(row.disposition==='unknown_or_missing'){
   unknown.push(row.noteId);
  }else return reject('ANNUAL_DISPOSITION_INVALID');
 }
 if(imported.length>decision.posts)return reject('ANNUAL_IMPORT_SQL_MISMATCH');
 // SQL can include older saved rows outside the local checkpoint: counting all
 // SQL posts PLUS every unresolved local ID deliberately overestimates supply.
 const upperBound=decision.posts+unknown.length;
 if(upperBound>=decision.threshold)return reject('ANNUAL_SUPPLY_NOT_PROVEN_BELOW_P80');
 const coverageLowerBound=upperBound===0?1:decision.posts/upperBound;
 if(coverageLowerBound<ANNUAL_MINIMUM_DATABASE_COVERAGE)return {
  ...reject('ANNUAL_DATABASE_COVERAGE_INSUFFICIENT'),annualAvailableUpperBound:upperBound,
  databaseCoverageLowerBound:coverageLowerBound,minimumDatabaseCoverage:ANNUAL_MINIMUM_DATABASE_COVERAGE,
  missingCandidateIds:unknown.sort()};
 const body={policy:ANNUAL_COMPLETION_POLICY,taskId:decision.taskId,keyword:decision.keyword,
  projectName:decision.projectName,snapshotId:decision.snapshotId,platform:decision.platform,year,
  acceptedBy:'verified_low_year_search',posts:decision.posts,threshold:decision.threshold,
  annualAvailableUpperBound:upperBound,databaseCoverageLowerBound:coverageLowerBound,
  minimumDatabaseCoverage:ANNUAL_MINIMUM_DATABASE_COVERAGE,missingCandidateIds:unknown.sort(),knownCandidates:known.size,
  importedCandidateCount:imported.length,verifiedExclusions:excluded.length,searchEvidence:scan,
  inventoryDigest:digest(inventory),checkedAt:decision.checkedAt,checkedAtMs:checkedAt,
  qualityVerified:false,subtitleQualityRequired:false,retryUnit:'original_keyword',
  quantityAccepted:false,allItemsCollected:unknown.length===0,scope:'platform_current_visible_results'};
 return {ok:true,...body,evidenceDigest:digest(body)};
}

export function douyinAnnualScan(run,task){
 const summary=run?.tasks?.findLast(row=>row.keyword===task.keyword);
 const proof=summary?.searchExhaustion;
 const safeStatus=['completed','failed'].includes(run?.status)
  &&(!run.fatalError||run.fatalError==='VOLUME_BELOW_THRESHOLD'||run.fatalError==='KNOWN_CANDIDATES_INCOMPLETE');
 const ok=safeStatus&&run.currentKeyword===task.keyword&&summary?.sortConfirmed===true
  &&summary.stopReason==='search_exhausted'&&proof?.confirmed===true&&proof.reason==='search_exhausted'
  &&proof.keyword===task.keyword&&proof.sortConfirmed===true&&proof.hasMore===false
  &&integer(proof.stableChecks)&&proof.stableChecks>=2&&integer(proof.returnedCount)
  &&String(proof.uiText||'').trim().match(/^(暂时没有更多了|没有更多了|暂无搜索结果|没有找到相关结果)$/)!==null;
 return {ok:Boolean(ok),policy:'douyin-latest-pagination-and-ui-v1',taskId:task.taskId,
  keyword:task.keyword,projectName:task.projectName,year:task.year||2026,startedAtTop:true,
  latestConfirmed:summary?.sortConfirmed===true,scope:'platform_current_visible_results',
  observations:proof?.stableChecks||0,startedAt:run?.startedAt,finishedAt:run?.finishedAt,
  rawEvidenceDigest:proof?digest(proof):null};
}

const observedYear=value=>{
 const m=String(value||'').match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T]|$)/);
 if(!m)return null;const [y,month,day]=m.slice(1).map(Number),date=new Date(Date.UTC(y,month-1,day));
 return date.getUTCFullYear()===y&&date.getUTCMonth()===month-1&&date.getUTCDate()===day?y:null;
};
export function annualInventoryFromNotes(notes,{keyword,projectName,year=2026,importedIds=[],verifiedIrrelevantIds=[]}={}){
 const imported=new Set(importedIds.map(String)),excluded=new Set(verifiedIrrelevantIds.map(String));
 if(!Array.isArray(notes))throw new Error('ANNUAL_NOTES_REQUIRED');
 return notes.map(note=>{
  const noteId=String(note.noteId||''),publishedYear=observedYear(note.publishedAt);
  const base={noteId,keyword,projectName,disposition:'unknown_or_missing'};
  if(note.status==='skipped_old'&&publishedYear!==null&&publishedYear!==year
   &&['detail_page','browser_response_create_time'].includes(note.result?.source))
   return {...base,disposition:'excluded_old',year:publishedYear,dateVerified:true};
  if(note.status==='skipped_irrelevant'&&excluded.has(noteId))
   return {...base,disposition:'excluded_irrelevant',scopeVerified:true};
  if(note.status==='completed'&&publishedYear===year&&imported.has(noteId)
   &&note.result?.post?.['文章id']===noteId&&note.result.post['项目']===projectName&&note.result.post['关键词']===keyword)
   return {...base,disposition:'imported_current_year',year,importVerified:true};
  return base;
 });
}
