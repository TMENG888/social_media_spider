import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {assessKeywordScope,SearchExhaustion,assessSearchAcceptance} from './search-acceptance.mjs';
import {auditExistingScope,recordScope,scopeSummary} from './scope-audit.mjs';
import {incompleteCandidates} from './candidate-acceptance.mjs';
import {asrJobStats,openCheckpoint,saveCandidates,markCompleted,exportCheckpoint,claimAsrJob} from './checkpoint.mjs';
import {YearBoundary,POLICY_VERSION,ACCEPTANCE_VERSION} from './collection-policy.mjs';
import fs from 'node:fs/promises';
import {maySkipExhausted} from './retry-disposition.mjs';
import os from 'node:os';
import path from 'node:path';

const keyword='保利熙瑞 看房';
test('collector upgrade keeps existing queue identity and separately versions acceptance',()=>{
  assert.equal(POLICY_VERSION,'20260928-streaming-year-window-v1');
  assert.equal(ACCEPTANCE_VERSION,'20261014-scoped-verified-search-end-v2');
});
test('scope/endpoint failures cannot become exhausted content skips',()=>{
  for(const error of ['SCOPE_UNVERIFIED','SEARCH_END_UNVERIFIED','SEARCH_EXHAUSTION_UNCONFIRMED'])
    assert.equal(maySkipExhausted({status:'incomplete',error:'DETAILS_INCOMPLETE | '+error}),false);
});
test('confirmed cross-city examples excluded by explicit entity policy',()=>{
  for(const title of ['广州天河现房！ 省一级300出 原450','天河精装 3＋1房 260w出 一梯队']){
    const result=assessKeywordScope(keyword,{post:{文章标题:title,文章内容:'体育东均和小学 天河外国语均和学校',文章标签:'广州买房 广州天河'}});
    assert.equal(result.status,'out_of_scope');assert.equal(result.reason,'entity_anchor_not_observed');
  }
});
test('anchor in title, body, or tags accepted; intent word not mandatory',()=>{
  for(const field of ['文章标题','文章内容','文章标签'])assert.equal(assessKeywordScope(keyword,{post:{[field]:'北京 保利·熙瑞 户型'}}).status,'accepted');
  assert.equal(assessKeywordScope(keyword,{post:{文章标题:'保利天瑞 看房'}}).status,'out_of_scope');
});
test('task labels and other users comments are never relevance evidence',()=>{
  assert.equal(assessKeywordScope(keyword,{post:{关键词:keyword,项目:keyword,文章标题:'别的楼盘'},comments:[{评论内容:'保利熙瑞'}]}).status,'out_of_scope');
});
test('empty or missing detail must be reobserved, not silently excluded',()=>{
  assert.equal(assessKeywordScope(keyword,{post:{}}).status,'unobserved');
  assert.throws(()=>assessKeywordScope('',{}),/SCOPE_ANCHOR_INVALID/);
});
const snapshot={contextValid:true,rendered:true,loading:false,loadFailed:false,count:20,height:3000,lastId:'n20',atBottom:true,terminal:false};
test('healthy stable scroll endpoint required repeatedly',()=>{
  const gate=new SearchExhaustion({stableRounds:3});
  for(let i=0;i<3;i++)assert.equal(gate.observe(snapshot).ok,false);
  const evidence=gate.observe(snapshot);assert.equal(evidence.ok,true);assert.equal(evidence.scope,'platform_current_visible_results');
});
test('visible terminal still requires repeated healthy observations',()=>{
  const gate=new SearchExhaustion({terminalRounds:2});
  assert.equal(gate.observe({...snapshot,terminal:true}).ok,false);
  assert.equal(gate.observe({...snapshot,terminal:true}).ok,false);
  assert.equal(gate.observe({...snapshot,terminal:true}).ok,true);
  for(let i=0;i<5;i++)assert.equal(gate.observe({...snapshot,terminal:true,atBottom:false}).ok,false);
});
for(const change of [{loading:true},{loadFailed:true},{contextValid:false},{rendered:false},{atBottom:false},{count:21},{height:4000},{lastId:'other'}]){
  test('end streak reset by '+JSON.stringify(change),()=>{
    const gate=new SearchExhaustion({stableRounds:2});gate.observe(snapshot);gate.observe(snapshot);
    assert.equal(gate.observe({...snapshot,...change}).ok,false);
  });
}
test('interleaved old dates cannot prove annual completion',()=>{
  const boundary=new YearBoundary(2026,8);
  for(let i=0;i<8;i++)boundary.observe('old'+i,'2025-09-09');
  assert.equal(boundary.reached,true);
  assert.equal(assessSearchAcceptance([{reason:'year_window',boundary:boundary.recent}]).ok,false);
  boundary.observe('new','2026-10-01');assert.equal(boundary.reached,false);
  assert.equal(assessSearchAcceptance([{reason:'platform_no_growth'}]).ok,false);
  const endpoint=assessSearchAcceptance([{reason:'platform_exhausted',exhaustion:{ok:true},failed:5}]);
  assert.equal(endpoint.ok,true);
  assert.equal(endpoint.reason,'verified_search_endpoint');
  assert.doesNotMatch(endpoint.reason,/candidates_disposed/);
});

function fixture(){
  const db=new DatabaseSync(':memory:');
  db.exec(`CREATE TABLE candidate(keyword TEXT,note_id TEXT,result_json TEXT,status TEXT,attempts INTEGER,last_error TEXT,updated_at TEXT);
    CREATE TABLE scope_audit(keyword TEXT,note_id TEXT,assessment_json TEXT,checked_at TEXT,PRIMARY KEY(keyword,note_id));
    CREATE TABLE import_batch(keyword TEXT,note_id TEXT);
    CREATE TABLE asr_job(keyword TEXT,note_id TEXT,status TEXT);`);
  const old={post:{文章id:'old',文章标题:'广州天河现房',文章内容:'广州天河',文章视频内容:null},comments:[{评论id:'c',评论内容:'保留'}]};
  db.prepare('INSERT INTO candidate VALUES(?,?,?,?,?,?,?)').run(keyword,'old',JSON.stringify(old),'completed',3,null,'old');
  db.prepare('INSERT INTO import_batch VALUES(?,?)').run(keyword,'old');
  db.prepare('INSERT INTO asr_job VALUES(?,?,?)').run(keyword,'old','dead_letter');
  return {db,old};
}
test('legacy scope exclusion preserves full records and retry history',()=>{
  const {db,old}=fixture();try{
    const audit=auditExistingScope(db,keyword);assert.equal(audit.out_of_scope,1);assert.equal(audit.legacyImportedExcluded,1);
    const row=db.prepare('SELECT * FROM candidate').get();assert.equal(row.status,'skipped_irrelevant');assert.equal(row.attempts,3);
    assert.deepEqual(JSON.parse(row.result_json),old);assert.equal(db.prepare('SELECT COUNT(*) AS n FROM import_batch').get().n,1);
    assert.deepEqual(incompleteCandidates([{status:row.status}]),[]);assert.equal(asrJobStats(db).dead_letter,undefined);
  }finally{db.close();}
});
test('fresh exclusion records one real detail observation and no repeat acquisition',()=>{
  const {db,old}=fixture();try{
    db.exec("UPDATE candidate SET status='pending',attempts=0,result_json=NULL");
    const assessment=assessKeywordScope(keyword,old);recordScope(db,keyword,{noteId:'old'},old,assessment,{fresh:true});
    assert.equal(db.prepare('SELECT attempts FROM candidate').get().attempts,1);
    auditExistingScope(db,keyword);assert.equal(db.prepare('SELECT attempts FROM candidate').get().attempts,1);
  }finally{db.close();}
});
test('missing evidence remains unresolved and is not allowed by scope summary',()=>{
  const {db}=fixture();try{
    db.exec("UPDATE candidate SET result_json='{}'");auditExistingScope(db,keyword);
    assert.equal(scopeSummary(db,keyword).unobserved,1);
    assert.equal(incompleteCandidates([{status:db.prepare('SELECT status FROM candidate').get().status}]).length,1);
  }finally{db.close();}
});
test('full checkpoint export excludes foreign content but durably retains its evidence and ASR history',async()=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'xhs-scope-regression-'));
  const db=openCheckpoint(path.join(root,'checkpoint.sqlite'));
  try{
    const notes=[{noteId:'a'.repeat(24),url:'https://www.xiaohongshu.com/explore/'+ 'a'.repeat(24)},
      {noteId:'b'.repeat(24),url:'https://www.xiaohongshu.com/explore/'+ 'b'.repeat(24)}];
    saveCandidates(db,keyword,notes);
    for(const [index,note] of notes.entries())markCompleted(db,keyword,note,{post:{文章id:note.noteId,文章标题:index?'广州天河':'保利熙瑞户型',
      文章内容:index?'广州现房':'北京保利熙瑞',文章时间地点:'2026-10-14',平台:'小红书',项目:'北京臻澐项目口碑'},comments:[],publishedAt:'2026-10-14'});
    db.prepare(`INSERT INTO asr_job(keyword,note_id,article_id,media_url,status,attempts,max_attempts,created_at,updated_at)
      VALUES(?,?,?,?,'retry_pending',2,3,'old','old')`).run(keyword,notes[1].noteId,notes[1].noteId,'https://example.invalid/video');
    auditExistingScope(db,keyword);
    assert.equal(claimAsrJob(db),null);assert.equal(asrJobStats(db).pendingTotal,0);
    assert.equal(db.prepare('SELECT attempts FROM asr_job').get().attempts,2);
    const exported=await exportCheckpoint(db,path.join(root,'out'),{targetYear:2026,cutoff:'2026-01-01'});
    assert.equal(exported.posts.length,1);assert.equal(exported.posts[0]['文章id'],notes[0].noteId);
    const excluded=JSON.parse((await fs.readFile(path.join(root,'out/excluded_scope_records.jsonl'),'utf8')).trim());
    assert.equal(excluded.result.post['文章id'],notes[1].noteId);
    assert.equal((await fs.readFile(path.join(root,'out/scope_audit.jsonl'),'utf8')).trim().split('\n').length,2);
  }finally{
    db.close();
    if(path.dirname(root)!==path.resolve(os.tmpdir())||!path.basename(root).startsWith('xhs-scope-regression-'))throw new Error('TEST_CLEANUP_PATH_INVALID');
    await fs.rm(root,{recursive:true,force:true});
  }
});
test('crawler and worker cannot use legacy year windows or no-change to bypass the new gates',async()=>{
  const source=await fs.readFile(new URL('./index.mjs',import.meta.url),'utf8');
  assert.doesNotMatch(source,/progress\.reason = "year_window"/);
  assert.match(source,/if\(boundary\.reached\)progress\.oldDateWindowObserved=true/);
  assert.match(source,/process\.env\.XHS_ASR_CPU_THREADS/);
  assert.match(source,/processNote\(note, false, true\)/);
  assert.doesNotMatch(source,/visited\.has/);
  assert.match(source,/const remaining = incompleteCandidates\(checkpointCandidates\(checkpoint,task.keyword\)\);/);
  assert.match(source,/await detail\.goto\(note.url,[\s\S]*?await ensureLogin\(detail\)/);
  assert.match(source,/if\(recoverSaved\)\{await detail\.close\(\)/);
  const worker=await fs.readFile(new URL('./run-worker.mjs',import.meta.url),'utf8');
  assert.match(worker,/if\(noChange&&acceptanceVerified\)/);
  assert.match(worker,/includes\(taskState\)&&!acceptanceVerified/);
  assert.match(worker,/"--keyword", task.keyword/);
  assert.match(worker,/previous\?\.scopeAcceptance\?\.acceptanceVersion===ACCEPTANCE_VERSION/);
});

test('endpoint recovery keeps failed visits and missing old candidates without resetting their attempts',()=>{
  const notes=[{noteId:'clicked-but-failed',status:'failed',attempts:2},
    {noteId:'old-not-in-list',status:'pending',attempts:1},
    {noteId:'saved',status:'completed',attempts:2},
    {noteId:'exhausted',status:'dead_letter',attempts:3}];
  const recovery=incompleteCandidates(notes);
  assert.deepEqual(recovery.map(n=>n.noteId),['clicked-but-failed','old-not-in-list']);
  assert.deepEqual(recovery.map(n=>n.attempts),[2,1]);
});
