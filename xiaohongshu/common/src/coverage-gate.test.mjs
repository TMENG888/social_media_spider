import test from 'node:test';import assert from 'node:assert/strict';
import {assessCoverage,verifyCheckpointCoverage} from './coverage-gate.mjs';
import {openCheckpoint,saveCandidates,markCompleted} from './checkpoint.mjs';
import fs from 'node:fs/promises';import os from 'node:os';import path from 'node:path';
const note=i=>({noteId:String(i),status:'completed',publishedAt:'2026-10-01',result:{post:{文章id:String(i),文章链接:`https://example.invalid/${i}`,项目:'test',文章标题:'fixture 内容',内容类型:'图文'}}});
test('80% is per keyword, unresolved and skipped stay in denominator',()=>{
 const notes=Array.from({length:10},(_,i)=>note(i));notes[8].status='dead_letter';notes[9].status='pending';
 const options={scanComplete:true,verifiedIds:notes.slice(0,8).map(n=>n.noteId)};
 assert.equal(assessCoverage(notes,options).ok,true);assert.equal(assessCoverage(notes,options).denominator,10);
 assert.equal(assessCoverage(notes,{...options,verifiedIds:options.verifiedIds.slice(0,7)}).ok,false);
 assert.equal(assessCoverage(notes,{...options,scanComplete:false}).ok,false);
});
test('unknown media and false old-year claims cannot inflate coverage',()=>{
 const n=note(1);n.result.post.内容类型='视频';n.result.post.文章视频内容='wrong';n.result.postTextAudit={subtitle_status:'extracted'};
 assert.equal(assessCoverage([n],{scanComplete:true,verifiedIds:['1'],strictMedia:true}).numerator,0);
 n.status='skipped_old';n.publishedAt=null;
 assert.equal(assessCoverage([n],{scanComplete:true}).denominator,1);
 n.publishedAt='2025-01-01';assert.equal(assessCoverage([n],{scanComplete:true}).emptyScope,true);
});
test('duplicate IDs do not inflate either side and empty unscanned is not success',()=>{
 const n=note(1);assert.equal(assessCoverage([n,n],{scanComplete:true,verifiedIds:['1']}).denominator,1);
 assert.equal(assessCoverage([]).ok,false);
});

test('database snapshot readback, not local completion, decides the numerator',async()=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'coverage-db-fixture-')),checkpointDb=path.join(dir,'cp.sqlite');
 const cp=openCheckpoint(checkpointDb);
 try{
  for(let i=0;i<10;i++){
   const n=note(i);n.result.post.平台='fixture';n.result.post.文章时间地点=n.publishedAt;
   saveCandidates(cp,'fixture',[{noteId:n.noteId,url:n.result.post.文章链接}]);markCompleted(cp,'fixture',n,n.result);
  }
 }finally{cp.close();}
 const db={query:async sql=>sql.startsWith('SHOW')?[[]]:[],beginTransaction:async()=>{},commit:async()=>{},end:async()=>{},execute:async()=>[Array.from({length:8},(_,i)=>({...note(i).result.post,平台:'fixture'}))]};
 try{
  let coverage=await verifyCheckpointCoverage({checkpointDb,keyword:'fixture',scanComplete:true,connect:async()=>db});
  assert.equal(coverage.ok,true);assert.equal(coverage.numerator,8);assert.equal(coverage.denominator,10);
  db.execute=async()=>[Array.from({length:10},(_,i)=>({...note(i).result.post,平台:'fixture',文章标题:i<3?'different':note(i).result.post.文章标题}))];
  coverage=await verifyCheckpointCoverage({checkpointDb,keyword:'fixture',scanComplete:true,connect:async()=>db});
  assert.equal(coverage.ok,false);assert.equal(coverage.numerator,7);
 }finally{await fs.rm(dir,{recursive:true,force:true});}
});
