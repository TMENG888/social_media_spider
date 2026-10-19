import test from 'node:test';import assert from 'node:assert/strict';
import fs from 'node:fs/promises';import os from 'node:os';import path from 'node:path';
import {openCheckpoint,saveCandidates,markCompleted,claimAsrJob,completeAsrJob,quarantineUnverifiedMedia,enqueueAsrJob} from './checkpoint.mjs';
import {bindCurrentMedia} from './media-provenance.mjs';
import {archiveSubtitleReplacement} from './import-mysql.mjs';
const id='6a50baaf000000002102222a',keyword='fixture',url='https://example.invalid/current.mp4';
const bound=()=>bindCurrentMedia({noteId:id,routeId:id,recordId:id,video:{masterUrl:url},pageDuration:184});
async function fixture(fn){const dir=await fs.mkdtemp(path.join(os.tmpdir(),'xhs-source-test-'));const db=openCheckpoint(path.join(dir,'test.sqlite'));try{await fn(db);}finally{db.close();await fs.rm(dir,{recursive:true,force:true});}}
const result=()=>({post:{文章id:id,内容类型:'视频',文章视频内容:null},mediaProvenance:bound().binding});
const job=()=>({keyword,noteId:id,articleId:id,mediaUrl:url,mediaBinding:bound().binding});
test('wrong duration cannot commit transcript or completed state',()=>fixture(db=>{
 saveCandidates(db,keyword,[{noteId:id,url:'https://example.invalid/note'}]);markCompleted(db,keyword,{noteId:id},result(),{asrJob:job()});
 db.exec("UPDATE asr_job SET status='pending'");const claimed=claimAsrJob(db);
 assert.throws(()=>completeAsrJob(db,claimed,{text:'old transcript',audit:{status:'ok',duration:95.434}}),/DURATION_MISMATCH/);
 assert.notEqual(db.prepare('SELECT status FROM asr_job').get().status,'completed');
 const updated=completeAsrJob(db,claimed,{text:'verified transcript',audit:{status:'ok',duration:184,segments:30}});
 assert.equal(updated.postTextAudit.subtitle_audit.mediaProvenance.durationVerified,true);
}));
test('legacy quarantine preserves original evidence and attempts; correction budget is idempotent',()=>fixture(db=>{
 saveCandidates(db,keyword,[{noteId:id,url:'https://example.invalid/note'}]);
 const old=result();delete old.mediaProvenance;old.post.文章视频内容='legacy wrong source';
 markCompleted(db,keyword,{noteId:id},old,{asrJob:{...job(),mediaBinding:null}});
 db.exec("UPDATE asr_job SET attempts=3,max_attempts=3,status='completed',transcript='legacy wrong source'");
 assert.equal(quarantineUnverifiedMedia(db),1);assert.equal(quarantineUnverifiedMedia(db),0);
 assert.match(db.prepare('SELECT original_result FROM media_correction_history').get().original_result,/legacy wrong source/);
 assert.equal(db.prepare('SELECT attempts FROM asr_job').get().attempts,3);
 enqueueAsrJob(db,job());enqueueAsrJob(db,job());
 assert.equal(db.prepare('SELECT max_attempts FROM asr_job').get().max_attempts,6);
 assert.equal(db.prepare('SELECT attempts FROM asr_job').get().attempts,3);
}));
test('new source never reuses an old cached media file',()=>fixture(db=>{
 enqueueAsrJob(db,{...job(),mediaUrl:'https://example.invalid/old.mp4'});
 db.exec("UPDATE asr_job SET media_path='old-file.mp4',attempts=2,status='retry_pending'");
 enqueueAsrJob(db,job());const row=db.prepare('SELECT media_path,attempts FROM asr_job').get();
 assert.equal(row.media_path,null);assert.equal(row.attempts,2);
}));

test('legacy completed job on a failed detail cannot masquerade as a verified new job',()=>fixture(db=>{
 saveCandidates(db,keyword,[{noteId:id,url:'https://example.invalid/note'}]);
 enqueueAsrJob(db,{...job(),mediaBinding:null});
 db.exec("UPDATE asr_job SET status='completed',attempts=3,audit_json='{\"duration\":95.434}',transcript='wrong old source'");
 enqueueAsrJob(db,job());const row=db.prepare('SELECT status,transcript,attempts,max_attempts FROM asr_job').get();
 assert.equal(row.status,'pending');assert.equal(row.transcript,null);assert.equal(row.attempts,3);assert.equal(row.max_attempts,6);
 assert.match(db.prepare('SELECT original_job FROM media_correction_history').get().original_job,/wrong old source/);
}));

test('database old subtitle is archived before replacement, not claimed as committed',async()=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'subtitle-archive-test-')),archive=path.join(dir,'archive.jsonl');
 try{
  assert.equal(await archiveSubtitleReplacement({id:'1',文章视频内容:'old database evidence'},{文章视频内容:'corrected',文章id:id,平台:'test',项目:'test'},{archive}),true);
  const record=JSON.parse(await fs.readFile(archive,'utf8'));
  assert.equal(record.before,'old database evidence');assert.equal(record.event,'subtitle_replacement_attempt');
  assert.equal(record.committed,undefined);
 }finally{await fs.rm(dir,{recursive:true,force:true});}
});
