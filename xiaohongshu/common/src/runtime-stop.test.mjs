import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {spawn} from 'node:child_process';
import {randomUUID} from 'node:crypto';
import {pathToFileURL, fileURLToPath} from 'node:url';

const base = process.env.XHS_TEST_COMMON || fileURLToPath(new URL('../',import.meta.url));
const work = process.env.XHS_TEST_WORK || os.tmpdir();
const {recoverOrphanRuntimeStop, consumeRuntimeStop} = await import(pathToFileURL(path.join(base,'src/runtime-stop.mjs')));
const oldCycle = '092e574836134832bf92b43d49e53826';
const exists = file => fs.access(file).then(()=>true,()=>false);
async function fixture() {
  const dir = await fs.mkdtemp(path.join(work,'case-'));
  const opt = {stopFile:path.join(dir,'stop.requested'),supervisorStopFile:path.join(dir,'supervisor.stop'),
    workerId:'worker-02',cycleId:randomUUID().replaceAll('-',''),isProcessAlive:()=>false};
  const marker = {schemaVersion:1,source:'cycle_runtime_limit',cycleId:oldCycle,workerId:'worker-02',
    pid:9668,token:'d5b0e1af-589c-488a-be29-dbe021ac71db',minutes:58,createdAt:'2026-10-18T13:42:54.805Z'};
  const raw = JSON.stringify(marker)+'\n';
  await fs.writeFile(opt.stopFile,raw);
  return {dir,opt,marker,raw};
}

test('reported 58-minute marker is preserved in archive without requiring overwritten status',async()=>{
  const {opt,raw}=await fixture();
  const r=await recoverOrphanRuntimeStop(opt);
  assert.equal(r.ready,true);assert.equal(r.reason,'orphan_runtime_stop_archived');
  assert.equal(await exists(opt.stopFile),false);assert.equal(await fs.readFile(r.archive,'utf8'),raw);
  assert.equal((await recoverOrphanRuntimeStop(opt)).reason,'no_stop_marker');
});
test('failed status remains failed; cleanup does not accept, reset or alter tasks',async()=>{
  const {dir,opt}=await fixture();
  const status=JSON.stringify({exitCode:1,fatalError:'CONTEXT_LOST',tasks:[{status:'context_lost'}]});
  const statusFile=path.join(dir,'worker_status.json');await fs.writeFile(statusFile,status);
  assert.equal((await consumeRuntimeStop({...opt,statusFile,cycleId:oldCycle})).ready,false);
  assert.equal((await recoverOrphanRuntimeStop(opt)).ready,true);
  assert.equal(await fs.readFile(statusFile,'utf8'),status);
});
for(const value of ['manual stop','SIGINT 2026-10-19','COOLDOWN_STATE_UNAVAILABLE',
  'RATE_LIMIT_COOLDOWN_ACTIVE','runtime limit 55 minutes 2026-10-18 00:57:59',
  '{invalid',JSON.stringify({source:'redis_remote_control',commandId:'stop-1'}),
  JSON.stringify({source:'cycle_runtime_limit',workerId:'worker-02'})]) {
  test('preserves manual, remote, safety and unverified legacy marker: '+value,async()=>{
    const {opt}=await fixture();await fs.writeFile(opt.stopFile,value);
    assert.equal((await recoverOrphanRuntimeStop(opt)).ready,false);
    assert.equal(await fs.readFile(opt.stopFile,'utf8'),value);
  });
}
for(const change of [{workerId:'worker-03'},{pid:0},{pid:-1},{pid:'9668'},
  {cycleId:'unknown'},{token:'bad-token'},{minutes:0},{minutes:10081},
  {createdAt:'invalid'},{createdAt:'2999-01-01T00:00:00Z'},{schemaVersion:2}]) {
  test('invalid/other-worker timer retained: '+JSON.stringify(change),async()=>{
    const {opt,marker}=await fixture();const raw=JSON.stringify({...marker,...change});
    await fs.writeFile(opt.stopFile,raw);assert.equal((await recoverOrphanRuntimeStop(opt)).ready,false);
    assert.equal(await fs.readFile(opt.stopFile,'utf8'),raw);
  });
}
test('same-cycle marker is never treated as historical',async()=>{
  const {opt}=await fixture();assert.equal((await recoverOrphanRuntimeStop({...opt,cycleId:oldCycle})).ready,false);
});
test('live/PID-reused owner prevents archive',async()=>{
  const {opt,raw}=await fixture();const r=await recoverOrphanRuntimeStop({...opt,isProcessAlive:()=>true});
  assert.equal(r.reason,'runtime_stop_owner_alive');assert.equal(await fs.readFile(opt.stopFile,'utf8'),raw);
});
test('real current process liveness probe preserves stop',async()=>{
  const {opt,marker}=await fixture();await fs.writeFile(opt.stopFile,JSON.stringify({...marker,pid:process.pid}));
  const {isProcessAlive,...real}=opt;
  assert.equal((await recoverOrphanRuntimeStop(real)).reason,'runtime_stop_owner_alive');
});
test('uncertain probe error does not modify marker',async()=>{
  const {opt,raw}=await fixture();
  await assert.rejects(recoverOrphanRuntimeStop({...opt,isProcessAlive:()=>{throw new Error('denied');}}));
  assert.equal(await fs.readFile(opt.stopFile,'utf8'),raw);
});
test('supervisor stop prevents recovery',async()=>{
  const {opt,raw}=await fixture();await fs.writeFile(opt.supervisorStopFile,'manual');
  assert.equal((await recoverOrphanRuntimeStop(opt)).reason,'supervisor_stop');
  assert.equal(await fs.readFile(opt.stopFile,'utf8'),raw);
});
test('manual replacement between read and rename is restored',async()=>{
  const {opt}=await fixture();const r=await recoverOrphanRuntimeStop({...opt,
    afterRead:()=>fs.writeFile(opt.stopFile,'manual racing')});
  assert.equal(r.ready,false);assert.equal(await fs.readFile(opt.stopFile,'utf8'),'manual racing');
});
test('new request after rename remains authoritative; timer evidence retained',async()=>{
  const {opt,raw}=await fixture();const r=await recoverOrphanRuntimeStop({...opt,
    afterMove:()=>fs.writeFile(opt.stopFile,'remote racing')});
  assert.equal(r.ready,false);assert.equal(await fs.readFile(opt.stopFile,'utf8'),'remote racing');
  assert.equal(await fs.readFile(r.archive,'utf8'),raw);
});
test('two racing human requests retain both pieces of evidence',async()=>{
  const {dir,opt}=await fixture();const r=await recoverOrphanRuntimeStop({...opt,
    afterRead:()=>fs.writeFile(opt.stopFile,'first human request'),
    afterMove:()=>fs.writeFile(opt.stopFile,'second human request')});
  assert.equal(r.ready,false);assert.equal(await fs.readFile(opt.stopFile,'utf8'),'second human request');
  const name=(await fs.readdir(dir)).find(n=>n.includes('runtime-archived'));
  assert.equal(await fs.readFile(path.join(dir,name),'utf8'),'first human request');
});
test('supervisor stop arriving during recovery blocks startup',async()=>{
  const {opt}=await fixture();const r=await recoverOrphanRuntimeStop({...opt,
    afterMove:()=>fs.writeFile(opt.supervisorStopFile,'manual')});
  assert.equal(r.ready,false);assert.equal(await fs.readFile(opt.supervisorStopFile,'utf8'),'manual');
});
test('oversized/unrecognized stop is not parsed or archived',async()=>{
  const {opt}=await fixture();await fs.writeFile(opt.stopFile,' '.repeat(17000));
  assert.equal((await recoverOrphanRuntimeStop(opt)).reason,'unknown_stop_marker');
});
test('existing directory in place of marker is left untouched',async()=>{
  const {opt}=await fixture();await fs.unlink(opt.stopFile);await fs.mkdir(opt.stopFile);
  assert.equal((await recoverOrphanRuntimeStop(opt)).reason,'unknown_stop_marker');
});

async function execute(file,args,env={}) {
  return new Promise((resolve,reject)=>{
    const proc=spawn(file,args,{env:{...process.env,...env},windowsHide:true});
    let stdout='',stderr='';
    proc.stdout.on('data',v=>stdout+=v);proc.stderr.on('data',v=>stderr+=v);
    const timeout=setTimeout(()=>{proc.kill();reject(new Error('Fixture process timed out'));},20000);
    proc.on('error',e=>{clearTimeout(timeout);reject(e);});
    proc.on('exit',code=>{clearTimeout(timeout);resolve({code,stdout,stderr,pid:proc.pid});});
  });
}

async function workerFixture(kind) {
  const {dir,marker}=await fixture();
  const common=path.join(dir,'common'),state=path.join(dir,'worker-02/.state'),runs=path.join(dir,'worker-02/runs');
  for(const d of [path.join(common,'src'),path.join(common,'runtime/browsers/chrome-win64'),state,runs,path.join(dir,'worker-02/tasks')])
    await fs.mkdir(d,{recursive:true});
  for(const name of ['index.mjs','checkpoint.mjs','import-mysql.mjs'])await fs.writeFile(path.join(common,'src',name),'// environment check only');
  await fs.writeFile(path.join(common,'runtime/browsers/chrome-win64/chrome.exe'),'fixture-not-executable');
  await fs.writeFile(path.join(common,'config.json'),JSON.stringify({asrEnabled:false}));
  const queueFile=path.join(dir,'worker-02/tasks/task-queue.json');
  await fs.writeFile(queueFile,JSON.stringify({workerId:'worker-02',stateRoot:'../.state',runsRoot:'../runs',
    tasks:[{keyword:'fixture-done',topic:'fixture',projectName:'fixture',enabled:true}]}));
  // In retry mode a previously completed fixture task is skipped, so no child
  // collector, database, Redis, browser, signed-in profile or network is used.
  await fs.mkdir(path.join(runs,'fixture/fixture-done'),{recursive:true});
  await fs.writeFile(path.join(runs,'fixture/fixture-done/task_status.json'),JSON.stringify({status:'completed'}));
  const dead=await execute(process.execPath,['-e','process.exit(0)']);
  const stopFile=path.join(state,'stop.requested');
  await fs.writeFile(stopFile,kind==='manual'?'manual stop fixture':JSON.stringify({...marker,pid:dead.pid}));
  if(kind==='supervisor')await fs.writeFile(path.join(state,'supervisor.stop'),'manual supervisor');
  if(kind==='locked')await fs.writeFile(path.join(state,'worker.lock'),JSON.stringify({pid:process.pid}));
  const result=await execute(process.execPath,[path.join(base,'src/run-worker.mjs'),
    '--mode','retry','--dispatch','local','--skip-import','true','--phase','posts',
    '--queue',queueFile,'--cycle-id',randomUUID().replaceAll('-','')],{
    XHS_WORKER_ROOT:common,XHS_CDP_URL:'http://127.0.0.1:1',
    XHS_SUPERVISOR_STOP_FILE:path.join(state,'supervisor.stop')});
  await fs.writeFile(path.join(dir,'worker.stdout.log'),result.stdout);
  await fs.writeFile(path.join(dir,'worker.stderr.log'),result.stderr);
  return {dir,state,runs,result,stopFile};
}
test('REAL run-worker startup archives orphan and reaches clean exit without production services',async()=>{
  const {runs,result,stopFile,state}=await workerFixture('orphan');
  assert.equal(result.code,0,result.stdout+result.stderr);
  assert.equal(await exists(stopFile),false);
  const status=JSON.parse(await fs.readFile(path.join(runs,'worker_status.json'),'utf8'));
  assert.equal(status.startupStopRecovery.reason,'orphan_runtime_stop_archived');
  assert.equal(status.exitCode,0);assert.equal(status.runtimeStop,undefined);
  assert.equal(status.tasks.length,0);
  assert.ok((await fs.readdir(state)).some(n=>n.includes('runtime-archived')));
  assert.ok((await fs.readFile(path.join(runs,(await fs.readdir(runs)).find(n=>n.startsWith('collection-lifecycle'))),'utf8')).includes('startup_stop_recovery'));
});
for(const kind of ['manual','supervisor'])test('REAL worker retains '+kind+' stop before any collection',async()=>{
  const {runs,result,stopFile}=await workerFixture(kind);
  assert.equal(result.code,1,result.stdout+result.stderr);assert.equal(await exists(stopFile),true);
  const status=JSON.parse(await fs.readFile(path.join(runs,'worker_status.json'),'utf8'));
  assert.equal(status.tasks.length,0);assert.match(status.fatalError,/STOP_REQUESTED/);
  assert.equal(status.cycleResumeEligible,false);
});
test('REAL worker lock excludes recovery when another worker is alive',async()=>{
  const {state,result,stopFile}=await workerFixture('locked');
  assert.equal(result.code,1);assert.equal(await exists(stopFile),true);
  assert.match(result.stderr,/已在运行/);
  assert.ok(!(await fs.readdir(state)).some(n=>n.includes('runtime-archived')));
});
