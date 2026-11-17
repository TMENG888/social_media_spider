import {markCompleted} from './checkpoint.mjs';
import {frontendClosed} from './foreground-budget.mjs';
export {frontendClosed};
// Merge by stable IDs. When two captures of a thread differ, keep the richer
// row for import and retain the other capture in the audit, never erase it.
export function retainForegroundComments(result,prior){
 if(!prior?.comments?.length)return result;
 const rows=new Map(),variants=[];
 for(const row of [...prior.comments,...(result.comments||[])]){
  const key=String(row.评论id||'');if(!key)continue;
  const previous=rows.get(key);
  if(!previous){rows.set(key,row);continue;}
  if(JSON.stringify(previous)===JSON.stringify(row))continue;
  const richer=(Number(row.评论回复数)||0)>(Number(previous.评论回复数)||0)||((Number(row.评论回复数)||0)===(Number(previous.评论回复数)||0)&&String(row.评论内容||'').length>=String(previous.评论内容||'').length);
  variants.push(richer?previous:row);if(richer)rows.set(key,row);
 }
 const audits=new Map([...(prior.commentAudits||[]),...(result.commentAudits||[])].map(a=>[String(a.comment_id),a]));
 return {...result,comments:[...rows.values()],commentAudits:[...audits.values()],audit:{...result.audit,...(variants.length?{foregroundRetainedCommentVariants:variants}:{})}};
}
export function completeForegroundTimeout(db,keyword,note,error,{result=null,prior=null,asrJob=null}={}){
 const saved=result?.post?result:prior?.post?prior:null;
 const completion={...error.foregroundCompletion,frontendCompleted:true,allItemsCollected:false};
 if(saved){
  const output={...saved,comments:saved.comments||[],audit:{...saved.audit,commentsComplete:false,foregroundCompletion:completion}};
  markCompleted(db,keyword,note,output,{asrJob});return output;
 }
 // No fabricated title/body, no fake database row or current-year evidence.
 const output={foregroundCompletion:completion,comments:[],publishedAt:null};
 db.prepare("UPDATE candidate SET status='front_timeout',attempts=attempts+1,result_json=?,last_error=?,updated_at=? WHERE keyword=? AND note_id=?")
  .run(JSON.stringify(output),'CONTENT_FOREGROUND_TIMEOUT',new Date().toISOString(),keyword,note.noteId);
 return output;
}
