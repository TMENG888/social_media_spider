import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
const bootstrap=new URL('./fixtures/mysql-transport.mjs',import.meta.url).href;
const wrapper=fileURLToPath(new URL('../src/mysql-import-retry.mjs',import.meta.url));
const preflight=fileURLToPath(new URL('../src/mysql-check.mjs',import.meta.url));

for(const mode of ['dns','deadlock','lock','exhausted','auth','commit_unknown'])test('real importer + retry CLI with fake DB: '+mode,async()=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'channels-mysql-transport-'));
 try{
  const posts=path.join(dir,'posts.jsonl'),statusFile=path.join(dir,'status.json');
  await fs.writeFile(posts,JSON.stringify({文章链接:'https://weixin.qq.com/sph/fixture',文章id:'fixture',平台:'微信视频号',项目:'fixture',文章标题:'fixture'})+'\n');
  const run=spawnSync(process.execPath,[wrapper,'--posts',posts,'--status',statusFile,'--standby-minutes','0'],{encoding:'utf8',windowsHide:true,timeout:30000,
   env:{...process.env,NODE_OPTIONS:'--import='+bootstrap,CHANNELS_MYSQL_TEST_ROOT:dir,CHANNELS_MYSQL_TEST_MODE:mode,
    WECHAT_WORKER_ROOT:dir,MYSQL_USER:'fixture',MYSQL_PASSWORD:'fixture-only',REDIS_URL:'',REDIS_PASSWORD:''}});
  assert.equal(run.error,undefined);const state=JSON.parse(await fs.readFile(path.join(dir,'fake-database.json'),'utf8'));
  const receipt=JSON.parse(await fs.readFile(statusFile,'utf8'));
  assert.doesNotMatch(run.stdout+run.stderr,/fixture-only SQL\/password/);
  if(['dns','deadlock','lock'].includes(mode)){
   assert.equal(run.status,0,run.stderr);assert.equal(receipt.status,'success');assert.equal(state.rows.length,1);
   assert.equal(state.commits,1);assert.equal(state.connections,mode==='dns'?3:2);
  }else{
   assert.equal(run.status,2);assert.equal(receipt.status,'failed');
   assert.equal(state.connections,mode==='exhausted'?3:1);
   if(mode==='commit_unknown'){
    assert.equal(state.commits,1);assert.equal(state.rows.length,1);assert.equal(receipt.retrySafe,false);
    assert.equal(receipt.commitState,'unknown');assert.doesNotMatch(run.stdout,/mysql_import_transient_retry/);
   }else{assert.equal(state.commits,0);assert.equal(state.rows.length,0);}
  }
 }finally{await fs.rm(dir,{recursive:true,force:true});}
});
for(const mode of ['standby_recover','exhausted','stop_wait','standby_auth','standby_commit_unknown'])test('network standby through real CLI + fake DB: '+mode,async()=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'channels-mysql-standby-'));
 try{
  const posts=path.join(dir,'posts.jsonl'),status=path.join(dir,'status.json'),stop=path.join(dir,'stop.requested');
  const row={文章链接:'https://weixin.qq.com/sph/standby-fixture',文章id:'standby-fixture',平台:'微信视频号',项目:'fixture'};
  const content=JSON.stringify(row)+'\n';await fs.writeFile(posts,content);
  const run=spawnSync(process.execPath,[wrapper,'--posts',posts,'--status',status,'--stop-file',stop],{
   encoding:'utf8',windowsHide:true,timeout:30000,env:{...process.env,NODE_OPTIONS:'--import='+bootstrap,
    CHANNELS_MYSQL_TEST_ROOT:dir,CHANNELS_MYSQL_TEST_MODE:mode,WECHAT_WORKER_ROOT:dir,
    CHANNELS_MYSQL_STANDBY_MINUTES:'3',MYSQL_USER:'fixture',MYSQL_PASSWORD:'fixture-only',REDIS_URL:'',REDIS_PASSWORD:''}});
  assert.equal(run.error,undefined);const state=JSON.parse(await fs.readFile(path.join(dir,'fake-database.json'),'utf8'));
  const receipt=JSON.parse(await fs.readFile(status,'utf8'));
  assert.equal(await fs.readFile(posts,'utf8'),content);assert.equal(state.active,0);
  assert.match(run.stdout,/mysql_import_standby_started/);assert.doesNotMatch(run.stdout+run.stderr,/fixture-only SQL\/password/);
  if(mode==='standby_recover'){
   assert.equal(run.status,0,run.stderr);assert.equal(state.connections,5);assert.equal(state.commits,1);
   assert.equal(state.rows.length,1);assert.equal(state.closed,1);assert.equal(receipt.status,'success');
   assert.match(run.stdout,/mysql_import_standby_recovered/);
  }else{
   assert.equal(run.status,mode==='stop_wait'?75:2,run.stderr);assert.equal(receipt.status,'failed');
   assert.equal(state.connections,['exhausted'].includes(mode)?5:mode==='stop_wait'?3:4);
   if(mode==='standby_commit_unknown'){
    assert.equal(receipt.commitState,'unknown');assert.equal(receipt.retrySafe,false);assert.equal(state.commits,1);
    assert.equal(state.rows.length,1);assert.equal(state.closed,1);
   }else{assert.equal(state.commits,0);assert.equal(state.rows.length,0);}
   if(mode==='exhausted')assert.match(run.stdout,/mysql_import_standby_exhausted/);
   if(mode==='stop_wait'){
    assert.match(run.stdout,/mysql_import_wait_cancelled/);assert.equal(await fs.readFile(stop,'utf8'),'manual-stop');
   }
  }
 }finally{await fs.rm(dir,{recursive:true,force:true});}
});
test('stop marker prevents even the first import; no receipt or connection is manufactured',async()=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'channels-mysql-stop-'));
 try{
  const stop=path.join(dir,'stop.requested');await fs.writeFile(stop,'operator');
  const run=spawnSync(process.execPath,[wrapper,'--posts',path.join(dir,'unused.jsonl'),'--stop-file',stop],{
   encoding:'utf8',windowsHide:true,timeout:30000,env:{...process.env,NODE_OPTIONS:'--import='+bootstrap,
    CHANNELS_MYSQL_TEST_ROOT:dir,CHANNELS_MYSQL_TEST_MODE:'exhausted'}});
  assert.equal(run.status,75,run.stderr);assert.match(run.stdout,/mysql_import_wait_cancelled/);
  await assert.rejects(()=>fs.access(path.join(dir,'fake-database.json')));
  assert.equal(await fs.readFile(stop,'utf8'),'operator');
 }finally{await fs.rm(dir,{recursive:true,force:true});}
});
test('real mysql preflight CLI waits through DNS faults and succeeds only after queries',async()=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'channels-mysql-preflight-'));
 try{
  const status=path.join(dir,'preflight.json');
  const run=spawnSync(process.execPath,[preflight,'--status',status],{encoding:'utf8',windowsHide:true,timeout:30000,
   env:{...process.env,NODE_OPTIONS:'--import='+bootstrap,CHANNELS_MYSQL_TEST_ROOT:dir,CHANNELS_MYSQL_TEST_MODE:'dns',
    MYSQL_USER:'fixture',MYSQL_PASSWORD:'fixture-only'}});
  assert.equal(run.status,0,run.stderr);assert.equal(JSON.parse(await fs.readFile(status,'utf8')).status,'success');
  assert.equal(JSON.parse(await fs.readFile(path.join(dir,'fake-database.json'),'utf8')).connections,3);
 }finally{await fs.rm(dir,{recursive:true,force:true});}
});
test('a previous unknown-commit receipt survives restart and blocks all import replay',async()=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'channels-mysql-unknown-'));
 try{
  const status=path.join(dir,'status.json');const receipt={status:'failed',commitState:'unknown',retrySafe:false};
  await fs.writeFile(status,JSON.stringify(receipt));
  const run=spawnSync(process.execPath,[wrapper,'--posts',path.join(dir,'unused.jsonl'),'--status',status],{
   encoding:'utf8',windowsHide:true,timeout:30000,env:{...process.env,NODE_OPTIONS:'--import='+bootstrap,
    CHANNELS_MYSQL_TEST_ROOT:dir,CHANNELS_MYSQL_TEST_MODE:'dns'}});
  assert.equal(run.status,2);assert.deepEqual(JSON.parse(await fs.readFile(status,'utf8')),receipt);
  await assert.rejects(()=>fs.access(path.join(dir,'fake-database.json')));
  assert.match(run.stderr,/mysql_import_commit_reconciliation_required/);
 }finally{await fs.rm(dir,{recursive:true,force:true});}
});
