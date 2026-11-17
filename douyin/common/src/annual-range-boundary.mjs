import {createHash} from 'node:crypto';
export const ANNUAL_RANGE_POLICY='douyin-verified-year-boundary-20261107-v1';
const digest=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const validDay=value=>{
 const day=String(value||'').slice(0,10);
 if(!/^20\d{2}-\d{2}-\d{2}$/.test(day))return null;
 const date=new Date(day+'T00:00:00Z');
 return Number.isFinite(+date)&&date.toISOString().slice(0,10)===day?day:null;
};
const dayOfSeconds=value=>{
 const seconds=Number(value);if(!Number.isFinite(seconds)||seconds<=0)return null;
 const date=new Date(seconds*1000);if(!Number.isFinite(+date))return null;
 const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(date);
 return ['year','month','day'].map(k=>parts.find(p=>p.type===k)?.value).join('-');
};
const reject=reason=>({confirmed:false,policy:ANNUAL_RANGE_POLICY,reason});

// Only a fresh, latest-sorted search with a descending observed date sequence
// can establish this boundary. Interleaved, unknown or unfinished items keep
// the task open. An old card alone is never proof of annual completion.
export function assessAnnualRangeBoundary({keyword,year,cutoff=`${year}-01-01`,after,sortConfirmed,
 pages=[],items=[],failures=[],candidates=[],visitedOldIds=[],now=Date.now()}={}){
 if(!keyword||!Number.isSafeInteger(year)||!Number.isFinite(after)||!sortConfirmed||cutoff!==`${year}-01-01`)return reject('YEAR_BOUNDARY_SCOPE_INVALID');
 const current=pages.filter(p=>p.keyword===keyword&&p.at>=after);
 if(!current.length||String(current[0].offset??'')!=='0'||current.some(p=>p.latest!==true))return reject('YEAR_BOUNDARY_SEARCH_ORIGIN_UNVERIFIED');
 if(failures.some(p=>p.keyword===keyword&&p.at>=after))return reject('YEAR_BOUNDARY_SEARCH_FAILED');
 let offset=-1;const ids=[];
 for(const p of current){const value=Number(p.offset);if(p.offset==null||!Number.isSafeInteger(value)||value<offset)return reject('YEAR_BOUNDARY_PAGE_ORDER_UNVERIFIED');offset=value;for(const id of p.noteIds||[])if(!ids.includes(id))ids.push(id);}
 const dates=new Map();
 for(const item of items){
  if(item.keyword!==keyword||item.latest!==true||item.at<after)continue;
  const id=String(item.raw?.aweme_id||''),day=dayOfSeconds(item.raw?.create_time);
  if(!day)return reject('YEAR_BOUNDARY_DATE_UNKNOWN');
  if(dates.has(id)&&dates.get(id)!==day)return reject('YEAR_BOUNDARY_DATE_CONFLICT');dates.set(id,day);
 }
 const indexed=new Map(candidates.map(n=>[String(n.noteId),n])),sequence=[];
 let previous=null,old=false,visited=false;
 for(const id of ids){
  const day=dates.get(String(id)),n=indexed.get(String(id));
  if(!day||!n||Number(day.slice(0,4))>year)return reject('YEAR_BOUNDARY_DATE_UNKNOWN');
  if(previous&&day>previous)return reject('YEAR_BOUNDARY_DATES_NOT_DESCENDING');previous=day;
  if(day<cutoff){
   old=true;if(n.status!=='skipped_old'||validDay(n.publishedAt)!==day)return reject('YEAR_BOUNDARY_OLD_DATE_UNVERIFIED');
   if(visitedOldIds.includes(String(id)))visited=true;
  }else if(n.status!=='completed'||n.importStatus!=='imported'||n.result?.audit?.commentsComplete===false||validDay(n.publishedAt)!==day){return reject('YEAR_BOUNDARY_CURRENT_ITEM_INCOMPLETE');}
  sequence.push({noteId:String(id),day});
 }
 // Historical candidates absent from this search remain unresolved evidence.
 if(candidates.some(n=>!['completed','skipped_old'].includes(n.status)||(n.status==='completed'&&(n.importStatus!=='imported'||n.result?.audit?.commentsComplete===false))))return reject('YEAR_BOUNDARY_KNOWN_GAPS');
 if(!old||!visited||sequence.length<2)return reject('YEAR_BOUNDARY_NOT_REACHED');
 const body={policy:ANNUAL_RANGE_POLICY,confirmed:true,reason:'current_year_complete_old_year_reached',keyword,year,cutoff,
  scope:'platform_current_visible_results',startedAtTop:true,latestConfirmed:true,searchStartedAt:after,observedAt:now,
  observations:sequence.length,sequence,knownIncompleteCount:0,sequenceDigest:digest(sequence)};
 return {...body,evidenceDigest:digest(body)};
}

export function verifiedAnnualRangeBoundary(summary){
 const e=summary?.annualRangeBoundary;
 if(summary?.stopReason!=='annual_range_complete'||summary.sortConfirmed!==true||!e||e.policy!==ANNUAL_RANGE_POLICY
  ||e.confirmed!==true||e.keyword!==summary.keyword||e.reason!=='current_year_complete_old_year_reached'
  ||e.startedAtTop!==true||e.latestConfirmed!==true||e.scope!=='platform_current_visible_results'
  ||!Number.isSafeInteger(e.year)||e.cutoff!==`${e.year}-01-01`||e.knownIncompleteCount!==0
  ||!Array.isArray(e.sequence)||e.sequence.length<2||e.observations!==e.sequence.length
  ||!Number.isFinite(e.searchStartedAt)||!Number.isFinite(e.observedAt)||e.observedAt<e.searchStartedAt)return false;
 let previous=null,old=false;const ids=new Set();
 for(const row of e.sequence){
  if(!row?.noteId||ids.has(row.noteId)||validDay(row.day)!==row.day||Number(row.day.slice(0,4))>e.year||previous&&row.day>previous)return false;
  ids.add(row.noteId);previous=row.day;if(row.day<e.cutoff)old=true;
 }
 const {evidenceDigest,...body}=e;
 return old&&e.sequenceDigest===digest(e.sequence)&&evidenceDigest===digest(body);
}
