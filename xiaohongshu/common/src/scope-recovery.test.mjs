import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {openCheckpoint,saveCandidates,markCompleted,checkpointCandidates,exportCheckpoint} from './checkpoint.mjs';
import {recordScope,auditExistingScope} from './scope-audit.mjs';
import {assessKeywordScope} from './search-acceptance.mjs';
import {attachScopeAudits,verifiedScopeExclusion} from './coverage-scope.mjs';
import {incompleteCandidates} from './candidate-acceptance.mjs';

const keyword='保利熙瑞 看房',note={noteId:'a'.repeat(24),url:'https://www.xiaohongshu.com/explore/'+'a'.repeat(24)};
async function fixture(run){
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'xhs-scope-recovery-'));
 const db=openCheckpoint(path.join(root,'state.sqlite'));
 try{
  saveCandidates(db,keyword,[note]);
  const old={post:{文章id:note.noteId,文章标题:'',文章内容:'',文章标签:'广州',文章时间地点:'2026-06-01',平台:'小红书',项目:'test'},comments:[]};
  markCompleted(db,keyword,note,old);
  recordScope(db,keyword,note,old,assessKeywordScope(keyword,old));
  await run(db,root,old);
 }finally{
  db.close();
  if(path.dirname(root)!==path.resolve(os.tmpdir())||!path.basename(root).startsWith('xhs-scope-recovery-'))throw new Error('TEST_CLEANUP_PATH_INVALID');
  await fs.rm(root,{recursive:true,force:true});
 }
}

test('uncertain cached exclusion is recovered; fresh detail replaces it only after full old evidence archive',async()=>fixture(async(db,root,old)=>{
 const before=db.prepare('SELECT * FROM candidate').get();
 const beforeScope=db.prepare('SELECT * FROM scope_audit').get();
 let notes=attachScopeAudits(db,checkpointCandidates(db,keyword),keyword);
 assert.equal(verifiedScopeExclusion(notes[0],keyword),null);
 assert.equal(incompleteCandidates(notes,{keyword}).length,1);
 const fresh={outsideScope:true,publishedAt:'2026-06-01',scopeEvidence:{title:'广州天河现房',body:'广州现房介绍',tags:'广州'},comments:[]};
 recordScope(db,keyword,note,fresh,assessKeywordScope(keyword,fresh,{excludedEntities:['广州天河']}),{fresh:true});
 const after=db.prepare('SELECT * FROM candidate').get();
 assert.deepEqual(JSON.parse(after.result_json),fresh);
 assert.equal(after.attempts,before.attempts+1);
 const history=db.prepare('SELECT * FROM scope_evidence_history').get();
 assert.equal(history.previous_candidate_json,JSON.stringify(before));
 assert.equal(history.previous_scope_json,JSON.stringify(beforeScope));
 assert.deepEqual(JSON.parse(JSON.parse(history.previous_candidate_json).result_json),old);
 notes=attachScopeAudits(db,checkpointCandidates(db,keyword),keyword);
 assert.ok(verifiedScopeExclusion(notes[0],keyword));
 assert.equal(incompleteCandidates(notes,{keyword}).length,0);
 assert.equal(incompleteCandidates(notes,{keyword:'中海 住宅'}).length,1);
 await exportCheckpoint(db,path.join(root,'out'),{targetYear:2026});
 const exported=JSON.parse((await fs.readFile(path.join(root,'out/scope_evidence_history.jsonl'),'utf8')).trim());
 assert.equal(exported.previous_candidate_json,history.previous_candidate_json);
}));

test('archival failure rolls back fresh exclusion rather than losing old evidence',async()=>fixture(async(db)=>{
 const before=db.prepare('SELECT * FROM candidate').get(),scope=db.prepare('SELECT * FROM scope_audit').get();
 db.exec('DROP TABLE scope_evidence_history');
 const fresh={outsideScope:true,scopeEvidence:{title:'广州楼盘'},comments:[]};
 assert.throws(()=>recordScope(db,keyword,note,fresh,assessKeywordScope(keyword,fresh,{excludedEntities:['广州楼盘']}),{fresh:true}),/scope_evidence_history/);
 assert.deepEqual(db.prepare('SELECT * FROM candidate').get(),before);
 assert.deepEqual(db.prepare('SELECT * FROM scope_audit').get(),scope);
}));

test('readjudging old evidence cannot invent fresh detail or consume attempts',async()=>fixture(async(db)=>{
 const before=db.prepare('SELECT result_json,attempts FROM candidate').get();
 auditExistingScope(db,keyword);
 assert.deepEqual(db.prepare('SELECT result_json,attempts FROM candidate').get(),before);
 assert.equal(db.prepare('SELECT count(*) n FROM scope_evidence_history').get().n,0);
 const notes=attachScopeAudits(db,checkpointCandidates(db,keyword),keyword);
 assert.equal(incompleteCandidates(notes,{keyword}).length,1);
}));
test('old lexical exclusions are reopened for original-detail recovery with old scope evidence archived',async()=>fixture(async(db)=>{
 const full={post:{文章id:note.noteId,文章标题:'保利这个给我都去看',文章内容:'西四环的保利新房，南北双阳台'},comments:[]};
 db.prepare("UPDATE candidate SET status='skipped_irrelevant',result_json=?").run(JSON.stringify(full));
 const previous=db.prepare('SELECT * FROM candidate').get(),scope=db.prepare('SELECT * FROM scope_audit').get();
 auditExistingScope(db,keyword);
 const after=db.prepare('SELECT * FROM candidate').get();
 assert.equal(after.status,'pending');assert.equal(after.attempts,previous.attempts);assert.equal(after.result_json,previous.result_json);
 const archived=db.prepare('SELECT * FROM scope_evidence_history').get();
 assert.equal(archived.previous_candidate_json,JSON.stringify(previous));assert.equal(archived.previous_scope_json,JSON.stringify(scope));
}));
