import {validDate} from './collection-policy.mjs';

export const YEAR_BOUNDARY_STOP_POLICY='xhs-consecutive-old-detail-stop-20261111-v1';

export function verifiedYearBoundary(summary){
 const proof=summary?.yearBoundary;
 if(summary?.reason!=='year_boundary'||summary.latestConfirmed!==true
  ||proof?.policy!==YEAR_BOUNDARY_STOP_POLICY||proof.source!=='verified_detail_dates'
  ||!Number.isSafeInteger(proof.year)||proof.year<2000||summary.targetYear!==proof.year
  ||!Number.isSafeInteger(proof.required)||proof.required<8
  ||!Array.isArray(proof.observations)||proof.observations.length!==proof.required)return false;
 const seen=new Set();
 for(const item of proof.observations){
  const date=validDate(item?.date);
  if(typeof item?.noteId!=='string'||!item.noteId||seen.has(item.noteId)||!date
   ||Number(date.slice(0,4))>=proof.year)return false;
  seen.add(item.noteId);
 }
 return true;
}

// Closing the async iterator here prevents its next scroll/load operation.
// Existing candidate recovery and database acceptance remain separate stages.
export async function consumeSearchCandidates(source,{processNote,boundary,progress,
 collectAllCurrentYear,maxNotesPerKeyword,targetReached=()=>false,now=()=>new Date().toISOString()}){
 if(await targetReached()){progress.reason="article_comment_target";progress.finishedAt=now();return;}
 for await(const note of source){
  progress.freshSearch=true;
  await processNote(note);
  if(await targetReached()){progress.reason="article_comment_target";progress.finishedAt=now();return;}
  if(collectAllCurrentYear&&progress.latestConfirmed===true&&boundary.reached){
   progress.reason='year_boundary';
   progress.oldDateWindowObserved=true;
   progress.yearBoundary={policy:YEAR_BOUNDARY_STOP_POLICY,year:boundary.year,required:boundary.size,
    source:'verified_detail_dates',observations:boundary.recent.map(item=>({...item}))};
   if(!verifiedYearBoundary(progress))throw new Error('YEAR_BOUNDARY_EVIDENCE_INVALID');
   progress.finishedAt=now();
   return;
  }
  if(!collectAllCurrentYear&&progress.accepted>=maxNotesPerKeyword){progress.reason='sample_limit';return;}
 }
}
