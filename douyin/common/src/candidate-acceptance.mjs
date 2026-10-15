import {checkpointCandidates,markSkipped} from './checkpoint.mjs';
import {validDate,inTargetYear} from './collection-policy.mjs';
import {shanghaiTime} from './douyin-data.mjs';

// An eight-old-item boundary stops loading; it does not invent dates for
// candidates already discovered. Only an observed matching response can settle
// a known old-year candidate without opening its detail.
export function settleObservedOldCandidates(db,keyword,awemes,year,cutoff){
 const settled=[];
 for(const note of checkpointCandidates(db,keyword)){
  if(!['pending','failed'].includes(note.status))continue;
  const raw=awemes.get(note.noteId);
  if(!raw || String(raw.aweme_id)!==String(note.noteId) || !Number.isFinite(Number(raw.create_time)) || Number(raw.create_time)<=0)continue;
  const date=shanghaiTime(Number(raw.create_time));
  if(!validDate(date) || inTargetYear(date,year,cutoff))continue;
  markSkipped(db,keyword,note,'已观测同ID搜索响应create_time，非目标年度',date);
  settled.push({noteId:note.noteId,publishedAt:date,source:'browser_response_create_time'});
 }
 return settled;
}

export function incompleteCandidates(notes){
 return notes.filter(n=>!['completed','skipped_old','dead_letter'].includes(n.status)
  || (n.status==='completed' && n.result?.audit?.commentsComplete===false));
}
