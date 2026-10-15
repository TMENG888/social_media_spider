import {createHash} from 'node:crypto';

// Compare business content, not capture times, retry counters, or ASR diagnostics.
const volatile = new Set(['id','文章获取时间','评论获取时间','updated_at','created_at']);
function canonical(value) {
  if(Array.isArray(value))return value.map(canonical).sort((a,b)=>JSON.stringify(a).localeCompare(JSON.stringify(b)));
  if(value&&typeof value==='object')return Object.fromEntries(Object.keys(value).filter(k=>!volatile.has(k)).sort().map(k=>[k,canonical(value[k])]));
  return value??null;
}
export function contentDigest(value){return createHash('sha256').update(JSON.stringify(canonical(value))).digest('hex');}
export function retrySnapshot(db,keyword) {
  const rows=db.prepare('SELECT note_id,url,result_json,attempts,status FROM candidate WHERE keyword=? ORDER BY note_id').all(keyword);
  const jobs=db.prepare('SELECT note_id,article_id,transcript,attempts,status FROM asr_job WHERE keyword=? ORDER BY note_id').all(keyword);
  const parse=s=>{try{return JSON.parse(s||'null');}catch{throw new Error('NO_CHANGE_INVALID_CHECKPOINT');}};
  const content=rows.map(r=>{
    const result=parse(r.result_json);
    return {noteId:r.note_id,post:result?.post||null,comments:result?.comments||[],
      publishedAt:result?.publishedAt||null,commentsComplete:result?.audit?.commentsComplete??null};
  });
  const attempts=Object.fromEntries([...rows.map(r=>['detail:'+r.note_id,Number(r.attempts)]),...jobs.map(r=>['asr:'+r.note_id,Number(r.attempts)])]);
  return {digest:contentDigest({keyword,content,jobs:jobs.map(j=>({noteId:j.note_id,articleId:j.article_id,transcript:j.transcript||null}))}),
    count:rows.length,attempts,hasPriorEvidence:rows.some(r=>Number(r.attempts)>0||parse(r.result_json)?.post),
    unresolvedDetails:rows.filter(r=>r.status!=='skipped_irrelevant'&&(!['completed','skipped_old','dead_letter'].includes(r.status)||parse(r.result_json)?.audit?.commentsComplete===false)).map(r=>'detail:'+r.note_id),
    unresolvedAudio:jobs.filter(j=>!['completed','dead_letter','skipped_unresolved'].includes(j.status)).map(j=>'asr:'+j.note_id),
    emptySubtitles:content.filter(r=>r.post?.内容类型==='视频'&&!String(r.post.文章视频内容||'').trim()).length};
}
export function unchangedRetry(before,after,{error='',status='',freshSearch=false,boundedRecoverySearch=false,stopped=false,importOk=false,runtimeUnavailable=false,pendingAsr=0}={}) {
  const blocked=/SCOPE|SEARCH_END_UNVERIFIED|SEARCH_EXHAUSTION_UNCONFIRMED|LEASE|LOGIN|SECURITY|CAPTCHA|RESTRICTION|RISK|COOLDOWN|SORT|CONTEXT|BROWSER|MYSQL|IMPORT|MEMORY|RESOURCE|ECONN|ETIMEDOUT|LOCK.*TIMEOUT|DATABASE OR DISK IS FULL|STOP_|MODEL.*(?:LOAD|INIT)|登录|验证码|风控|冷却|内存|入库/i;
  const contentFailure=/DETAILS_INCOMPLETE|DETAIL_DATA_NOT_OBSERVED|KNOWN_CANDIDATES_INCOMPLETE|COMMENTS_INCOMPLETE|SEARCH_STAGNANT_INCOMPLETE|SEARCH_LIMIT_REACHED|STOP_FAILURE_THRESHOLD|ASR_QUALITY_REJECTED|ASR_QUALITY_REVIEW_REQUIRED/;
  if(!before?.hasPriorEvidence||!before.count||!after?.count||before.digest!==after.digest)return null;
  if(!freshSearch||stopped||!importOk||runtimeUnavailable||pendingAsr>0||blocked.test(error)||!contentFailure.test(error))return null;
  if(!['partial_error','incomplete','failure_threshold','asr_review_required'].includes(status))return null;
  const reattempted=Object.keys(after.attempts).filter(k=>(before.attempts[k]||0)>0&&after.attempts[k]>before.attempts[k]);
  if((before.unresolvedAudio||[]).some(k=>!reattempted.includes(k)))return null;
  if(!boundedRecoverySearch&&(before.unresolvedDetails||[]).some(k=>!reattempted.includes(k)))return null;
  // A verified, bounded search for previously saved missing targets is also a
  // real retry. Cache-only export and a process killed mid-search never qualify.
  if(!reattempted.length&&!boundedRecoverySearch)return null;
  return {policy:'20261014-user-authorized-no-change-v1',beforeDigest:before.digest,afterDigest:after.digest,
    candidateCount:after.count,emptySubtitles:after.emptySubtitles,reattempted,
    boundedRecoverySearch:Boolean(boundedRecoverySearch),freshSearch:true,importOk:true,
    accepted:false,disposition:'no_change'};
}
