import {checkpointCandidates} from './checkpoint.mjs';

// A cold restart restores local evidence before the browser starts, but SQL
// backfill belongs to the same background queue as newly collected content.
export function queueRetainedImports({checkpoint,entries,batchSize=5,enqueue}){
 const size=Number.isInteger(batchSize)&&batchSize>0?batchSize:5;
 let notes=0,batches=0;
 for(const task of entries){
  const rows=checkpointCandidates(checkpoint,task.keyword).filter(n=>n.status==='completed'&&n.result?.post)
   .map(n=>({noteId:n.noteId,post:n.result.post,comments:n.result.comments||[]}));
  if(!rows.length)continue;
  checkpoint.prepare("UPDATE asr_job SET status='waiting_import' WHERE keyword=? AND status IN ('pending','retry_pending') AND EXISTS(SELECT 1 FROM candidate c WHERE c.keyword=asr_job.keyword AND c.note_id=asr_job.note_id AND c.status='completed')").run(task.keyword);
  for(let i=0;i<rows.length;i+=size){enqueue(task.keyword,structuredClone(rows.slice(i,i+size)));batches++;}
  notes+=rows.length;
 }
 return {notes,batches};
}
