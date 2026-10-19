import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {openCheckpoint,saveCandidates,markCompleted,claimAsrJob,failAsrJob,asrJobStats,mediaSourceRecoveryIds,exportCheckpoint,settleExpiredMediaGaps} from './checkpoint.mjs';

const keyword='原检索词',noteId='7657112687285413361';
const job=url=>({keyword,noteId,articleId:noteId,mediaUrl:url,sourceObserved:true});
const result=url=>({post:{文章id:noteId,文章视频链接:url,内容类型:'视频'},comments:[],audit:{commentsComplete:true},postTextAudit:{subtitle_status:'pending'}});
function fixture(){
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'dy-source-recovery-'));
 const db=openCheckpoint(path.join(folder,'checkpoint.sqlite'));
 saveCandidates(db,keyword,[{noteId,url:'https://www.douyin.com/video/'+noteId}],0);
 markCompleted(db,keyword,{noteId},result('https://example.invalid/old'),{asrJob:job('https://example.invalid/old')});
 db.prepare("UPDATE asr_job SET status='pending'").run();
 return {db,folder,close(){db.close();fs.rmSync(folder,{recursive:true,force:true});}};
}
test('403 stops retrying the same URL; one verified different source preserves attempts and full evidence',async()=>{
 const f=fixture(),{db}=f;
 try{
  const first=claimAsrJob(db);assert.equal(first.attempts,1);
  assert.equal(failAsrJob(db,first,new Error('视频下载失败 HTTP 403')),'waiting_source_refresh');
  assert.equal(claimAsrJob(db),null);assert.equal(asrJobStats(db).pendingTotal,1);
  assert.deepEqual(mediaSourceRecoveryIds(db,keyword),[noteId]);
  const oldJob=db.prepare('SELECT * FROM asr_job').get(),oldCandidate=db.prepare('SELECT * FROM candidate').get();
  markCompleted(db,keyword,{noteId},result('https://example.invalid/new'),{asrJob:job('https://example.invalid/new')});
  const history=db.prepare('SELECT * FROM asr_source_refresh_history').get();
  assert.deepEqual(JSON.parse(history.old_job_json),{...oldJob});
  assert.deepEqual(JSON.parse(history.old_candidate_json),{...oldCandidate});
  const current=db.prepare('SELECT * FROM asr_job').get();
  assert.equal(current.attempts,1);assert.equal(current.media_url,'https://example.invalid/new');assert.equal(current.media_path,null);
  assert.equal(current.max_attempts,2);
  assert.equal(current.status,'waiting_import');assert.equal(claimAsrJob(db),null);
  db.prepare("UPDATE asr_job SET status='pending'").run();
  const second=claimAsrJob(db);assert.equal(second.attempts,2);
  assert.equal(failAsrJob(db,second,new Error('视频下载失败 HTTP 403')),'dead_letter');
  assert.equal(claimAsrJob(db),null);assert.deepEqual(mediaSourceRecoveryIds(db,keyword),[]);
  markCompleted(db,keyword,{noteId},result('https://example.invalid/third'),{asrJob:job('https://example.invalid/third')});
  assert.equal(db.prepare('SELECT COUNT(*) AS n FROM asr_source_refresh_history').get().n,1);
  assert.equal(db.prepare('SELECT media_url FROM asr_job').get().media_url,'https://example.invalid/new');
  await exportCheckpoint(db,f.folder);
  assert.equal(fs.readFileSync(path.join(f.folder,'asr_source_refresh_history.jsonl'),'utf8').trim().split('\n').length,1);
 }finally{f.close();}
});
test('legacy exhausted 403 gets at most one extra observed-source attempt, never a lifetime reset',()=>{
 const f=fixture(),{db}=f;
 try{
  db.prepare("UPDATE asr_job SET status='dead_letter',attempts=3,max_attempts=3,last_error='视频下载失败 HTTP 403',media_path='stale.mp4'").run();
  for(const input of [job('https://example.invalid/old'),{...job('https://example.invalid/new'),sourceObserved:false},{...job('https://example.invalid/new'),articleId:'other'}]){
   markCompleted(db,keyword,{noteId},result(input.mediaUrl),{asrJob:input});
   assert.equal(db.prepare('SELECT COUNT(*) AS n FROM asr_source_refresh_history').get().n,0);
   assert.equal(db.prepare('SELECT media_url FROM asr_job').get().media_url,'https://example.invalid/old');
  }
  markCompleted(db,keyword,{noteId},result('https://example.invalid/new'),{asrJob:job('https://example.invalid/new')});
  const current=db.prepare('SELECT * FROM asr_job').get();assert.equal(current.attempts,3);assert.equal(current.max_attempts,4);
  db.prepare("UPDATE asr_job SET status='pending'").run();const fourth=claimAsrJob(db);assert.equal(fourth.attempts,4);
  assert.equal(failAsrJob(db,fourth,new Error('temporary media error')),'dead_letter');assert.equal(claimAsrJob(db),null);
 }finally{f.close();}
});
test('refresh after an early 403 cannot inherit extra unused retry slots',()=>{
 const f=fixture(),{db}=f;
 try{
  const first=claimAsrJob(db);assert.equal(first.attempts,1);
  failAsrJob(db,first,new Error('视频下载失败 HTTP 403'));
  markCompleted(db,keyword,{noteId},result('https://example.invalid/new'),{asrJob:job('https://example.invalid/new')});
  const archived=JSON.parse(db.prepare('SELECT old_job_json FROM asr_source_refresh_history').get().old_job_json);
  assert.equal(archived.max_attempts,3);assert.equal(archived.attempts,1);
  db.prepare("UPDATE asr_job SET status='pending'").run();
  const second=claimAsrJob(db);assert.equal(second.attempts,2);assert.equal(second.maxAttempts,2);
  assert.equal(failAsrJob(db,second,new Error('temporary media error')),'dead_letter');
  assert.equal(claimAsrJob(db),null);assert.equal(db.prepare('SELECT attempts FROM asr_job').get().attempts,2);
 }finally{f.close();}
});
test('failed evidence archival rolls back candidate and job without partial refresh',()=>{
 const f=fixture(),{db}=f;
 try{
  const first=claimAsrJob(db);failAsrJob(db,first,new Error('视频下载失败 HTTP 403'));
  const before=JSON.stringify(db.prepare('SELECT * FROM candidate').get()),oldJob=JSON.stringify(db.prepare('SELECT * FROM asr_job').get());
  db.exec("CREATE TRIGGER reject_source_history BEFORE INSERT ON asr_source_refresh_history BEGIN SELECT RAISE(ABORT,'fixture archive failure'); END");
  assert.throws(()=>markCompleted(db,keyword,{noteId},result('https://example.invalid/new'),{asrJob:job('https://example.invalid/new')}),/archive failure/);
  assert.equal(JSON.stringify(db.prepare('SELECT * FROM candidate').get()),before);assert.equal(JSON.stringify(db.prepare('SELECT * FROM asr_job').get()),oldJob);
 }finally{f.close();}
});
test('only a verified complete search may archive unresolved source as failed, never as collection success',()=>{
 const f=fixture(),{db}=f;
 try{
  const first=claimAsrJob(db);failAsrJob(db,first,new Error('视频下载失败 HTTP 403'));
  assert.deepEqual(settleExpiredMediaGaps(db,keyword),[]);assert.equal(asrJobStats(db).pendingTotal,1);
  assert.deepEqual(settleExpiredMediaGaps(db,keyword,{scanComplete:true}),[noteId]);
  assert.equal(asrJobStats(db).dead_letter,1);assert.equal(asrJobStats(db).completed||0,0);
  assert.equal(db.prepare('SELECT status FROM asr_job').get().status,'dead_letter');
  assert.equal(db.prepare('SELECT attempts FROM asr_job').get().attempts,1);
  assert.equal(JSON.parse(db.prepare('SELECT old_job_json FROM asr_source_resolution_history').get().old_job_json).status,'waiting_source_refresh');
  assert.deepEqual(settleExpiredMediaGaps(db,keyword,{scanComplete:true}),[]);
 }finally{f.close();}
});
