import {markCompleted} from './checkpoint.mjs';
import {frontendClosed} from './foreground-budget.mjs';
export {frontendClosed};
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
