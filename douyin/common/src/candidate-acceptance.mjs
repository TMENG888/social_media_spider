import {checkpointCandidates,markSkipped} from './checkpoint.mjs';
import {validDate,inTargetYear} from './collection-policy.mjs';
import {shanghaiTime} from './douyin-data.mjs';

// The observer also sees the default sort while the UI selects latest. Only
// responses from the confirmed current search interval can add new gaps.
// This never removes historical candidates or treats payloads as imported rows.
export function observedLatestSearchCandidates(pages,{keyword,after}={}){
 if(typeof keyword!=='string'||!keyword.trim()||!Number.isFinite(after)||after<=0)
  throw new Error('SEARCH_CANDIDATE_SCOPE_INVALID');
 const ids=new Set();
 for(const page of pages){
  if(page.keyword!==keyword||page.latest!==true||!Number.isFinite(page.at)||page.at<after)continue;
  for(const id of Array.isArray(page.noteIds)?page.noteIds:[])
   if(typeof id==='string'&&/^\d{15,22}$/.test(id))ids.add(id);
 }
 return [...ids].map(noteId=>({noteId,url:`https://www.douyin.com/video/${noteId}`}));
}

// An eight-old-item boundary stops loading; it does not invent dates for
// candidates already discovered. Only an observed matching response can settle
// a known old-year candidate without opening its detail.
export function settleObservedOldCandidates(db,keyword,awemes,year,cutoff,{evidenceById=new Map(),excludedIds=new Set()}={}){
 const settled=[];
 for(const note of checkpointCandidates(db,keyword)){
  if(!['pending','failed'].includes(note.status))continue;
  if(excludedIds.has(String(note.noteId)))continue;
  const raw=awemes.get(note.noteId);
  if(!raw || String(raw.aweme_id)!==String(note.noteId) || !Number.isFinite(Number(raw.create_time)) || Number(raw.create_time)<=0)continue;
  const date=shanghaiTime(Number(raw.create_time));
  if(!validDate(date) || inTargetYear(date,year,cutoff))continue;
  markSkipped(db,keyword,note,'已观测同ID搜索响应create_time，非目标年度',date,{source:'browser_response_create_time',
   observedSearchEvidence:evidenceById.get(String(note.noteId))||null});
  settled.push({noteId:note.noteId,publishedAt:date,source:'browser_response_create_time'});
 }
 return settled;
}

export function incompleteCandidates(notes){
 return notes.filter(n=>!['completed','skipped_old','dead_letter'].includes(n.status)
  || (n.status==='completed' && n.result?.audit?.commentsComplete===false));
}
