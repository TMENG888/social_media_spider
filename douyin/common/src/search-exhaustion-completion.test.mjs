import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import mysql from 'mysql2/promise';
import {buildVolumeSnapshot,volumeDecision} from './volume-acceptance.mjs';
import {assessSearchExhaustion,completeExhaustedSearch} from './search-exhaustion-completion.mjs';
import {applyVolumeDecision} from './volume-queue-policy.mjs';
import {keywordQueueConfirmed,volumeQueueConfirmed,reconcileVolumeCompletion} from './volume-confirmation.mjs';
import {openVolumeRuntime} from './volume-runtime.mjs';
import {RedisDispatcher} from './redis-dispatcher.mjs';

const clone=value=>structuredClone(value);
function fixture({posts=0,now=Date.now()}={}){
 const task={id:'dy-fixture-original',keyword:'富利建设 住宅',projectName:'fixture-project',cutoff:'2026-01-01'};
 const snapshot=buildVolumeSnapshot({platform:'抖音',tasks:[task],counts:[{...task,posts:37}],
  population:'nonzero_keywords',minimumPosts:1,dbReadbackVerified:true});
 const decision=volumeDecision(snapshot,{taskId:task.id,posts,readbackVerified:true,checkedAt:new Date(now).toISOString()});
 const record={taskId:task.id,keyword:task.keyword,projectName:task.projectName,status:'incomplete',
  startedAt:new Date(now-120000).toISOString(),finishedAt:new Date(now-1000).toISOString(),
  sortConfirmed:true,stopReason:'search_exhausted',error:'VOLUME_BELOW_THRESHOLD',importOk:true,savedPosts:posts,
  knownIncomplete:['7697504010770016763'],asr:{runtimeUnavailable:false,pendingTotal:0},
  searchExhaustion:{confirmed:true,reason:'search_exhausted',keyword:task.keyword,sortConfirmed:true,
   hasMore:false,stableChecks:2,returnedCount:13,checkpointCount:13,uiText:'暂时没有更多了',gaps:['7697504010770016763']}};
 return {task,snapshot,decision,record,now};
}

test('13 candidates, 12 old, 1 unresolved and 0/37 SQL rows may business-complete',()=>{
 const f=fixture(),e=assessSearchExhaustion(f.decision,f.task,f.record);
 assert.equal(e.ok,true);assert.equal(e.posts,0);assert.equal(e.quantityAccepted,false);
 assert.equal(e.allItemsCollected,false);assert.equal(e.deletedConfirmed,false);
 assert.deepEqual(e.missingCandidateIds,['7697504010770016763']);
 assert.equal(assessSearchExhaustion(fixture({posts:4}).decision,f.task,f.record).ok,true);
});

test('zero visible results can close, but high quantity uses existing P80 acceptance',()=>{
 const f=fixture();f.record.knownIncomplete=[];Object.assign(f.record.searchExhaustion,{gaps:[],returnedCount:0,checkpointCount:0,uiText:'暂无搜索结果'});
 const e=assessSearchExhaustion(f.decision,f.task,f.record);assert.equal(e.ok,true);assert.equal(e.allItemsCollected,true);
 assert.equal(assessSearchExhaustion(fixture({posts:37}).decision,f.task,f.record).ok,false);
});

test('a missing or forged search end is never quantity-shortage success',()=>{
 for(const mutate of [r=>r.sortConfirmed=false,r=>r.stopReason='search_stagnant',
  r=>r.searchExhaustion.confirmed=false,r=>r.searchExhaustion.hasMore=true,
  r=>r.searchExhaustion.stableChecks=1,r=>r.searchExhaustion.keyword='other',
  r=>r.searchExhaustion.uiText='加载中',r=>r.searchExhaustion.returnedCount=-1,
  r=>r.finishedAt=new Date(Date.now()-3600000).toISOString(),r=>r.startedAt='bad',
  r=>r.status='sample_completed',r=>r.taskId='other',r=>r.projectName='other']){
  const f=fixture();mutate(f.record);assert.equal(assessSearchExhaustion(f.decision,f.task,f.record).ok,false);
 }
});

test('safety, lease, SQL, disk, import and context failures remain protected',()=>{
 for(const message of ['STOP_REQUESTED','STOP_LOGIN_REQUIRED','SECURITY_CHALLENGE','LEASE_LOST',
  'MYSQL_IMPORT_FAILED','ECONNREFUSED','DATABASE OR DISK IS FULL','STOP_SEARCH_CONTEXT_LOST','TypeError','ETIMEDOUT']){
  for(const field of ['error','previousCollectionError','collectionError']){
   const f=fixture();f.record[field]=message;assert.equal(assessSearchExhaustion(f.decision,f.task,f.record).ok,false,message);
  }
 }
 for(const patch of [{importOk:false},{importError:'bad'},{importExitCode:1},{stopped:true},{mustStopNode:true},
  {asr:{runtimeUnavailable:true}},{asrError:'ASR_RUNTIME_FAILED'}]){
  const f=fixture();Object.assign(f.record,patch);assert.equal(assessSearchExhaustion(f.decision,f.task,f.record).ok,false);
 }
});

test('fresh task-bound SQL evidence required; every unresolved ID retained',()=>{
 const f=fixture();
 for(const patch of [{dbReadbackVerified:false},{posts:-1},{platform:'小红书'},
  {checkedAt:new Date(f.now-61000).toISOString()},{checkedAt:new Date(f.now+2000).toISOString()}]){
  assert.equal(assessSearchExhaustion({...f.decision,...patch},f.task,f.record,{now:f.now}).ok,false);
 }
 f.record.searchExhaustion.gaps=['extra'];
 assert.deepEqual(assessSearchExhaustion(f.decision,f.task,f.record).missingCandidateIds,['7697504010770016763','extra']);
 f.record.knownIncomplete=['duplicate','duplicate'];assert.equal(assessSearchExhaustion(f.decision,f.task,f.record).ok,false);
});

test('preview and rejected evidence make no Redis calls; forged decision rejected',async()=>{
 const f=fixture(),queue={client:{eval(){throw Error('MUST_NOT_CALL_REDIS');}}};
 const options={generation:'fixture-v1',token:'fixture-token'};
 assert.equal((await completeExhaustedSearch(queue,f.snapshot,f.decision,f.task,f.record,options)).confirmation.status,'preview');
 const bad={...f.record,importOk:false};
 assert.equal((await completeExhaustedSearch(queue,f.snapshot,f.decision,f.task,bad,{...options,commit:true})).confirmation,null);
 await assert.rejects(()=>completeExhaustedSearch(queue,f.snapshot,{...f.decision,reason:'FORGED_REASON'},f.task,f.record,options),/DECISION_INVALID/);
 await assert.rejects(()=>completeExhaustedSearch(queue,f.snapshot,f.decision,f.task,f.record,{...options,token:'',commit:true}),/LEASE_REQUIRED/);
});

test('only a Redis-confirmed search closure counts completed, not P80 or quality success',()=>{
 const f=fixture(),confirmation={status:'completed',acceptedBySearchExhaustion:true,acceptedByVolume:false};
 assert.equal(keywordQueueConfirmed(confirmation),true);assert.equal(volumeQueueConfirmed(confirmation),false);
 const result=reconcileVolumeCompletion(f.record,confirmation);
 assert.equal(result.status,'completed');assert.equal(result.redisConfirmed,true);assert.equal(result.quantityAccepted,false);
 assert.equal(result.searchExhaustionCompleted,true);assert.equal(result.error,null);
 assert.equal(keywordQueueConfirmed({...confirmation,status:'retry_pending'}),false);
 assert.equal(keywordQueueConfirmed({status:'completed'}),false);
});

// Optional real Lua 5.1 execution against in-memory command fixtures. No Redis
// server, credentials, browser or business database is opened by these tests.
const luaEnabled=Boolean(process.env.DY_TEST_LUA_RUNNER&&process.env.DY_TEST_LUA_SITE);
function luaClient(f){
 const namespace='xhs:douyin:{search-closure-fixture}',names=['payloads','statuses','attempts','tokens','owners','pending','leases','results','errors','failed','deferrals'];
 const queue={namespace,keys:names.map(n=>namespace+':'+n),maxAttempts:3};
 const state=Object.fromEntries(queue.keys.map(k=>[k,{}])),id=f.task.id;
 state[queue.keys[0]][id]=JSON.stringify(f.task);state[queue.keys[1]][id]='leased';
 state[queue.keys[2]][id]='4';state[queue.keys[3]][id]='token';state[queue.keys[4]][id]='worker-fixture';
 state[queue.keys[6]][id]=String(f.now+300000);state[queue.keys[7]][id]='{"previous":"retained"}';
 const client={state,types:Object.fromEntries(queue.keys.map((k,i)=>[k,[5,6,9].includes(i)?'zset':'hash'])),calls:[],
  async eval(script,options){
   const run=spawnSync(process.env.DY_TEST_PYTHON||'python',[process.env.DY_TEST_LUA_RUNNER],{
    input:JSON.stringify({script,...options,state:this.state,types:this.types,now:f.now}),encoding:'utf8',maxBuffer:8000000,windowsHide:true,
    env:{...process.env,PYTHONIOENCODING:'utf-8'}});
   if(run.status!==0)throw Error(run.stderr||run.error?.message||'LUA_FIXTURE_FAILED');
   const out=JSON.parse(run.stdout);this.state=out.state;this.types=out.types;this.calls.push(...out.calls);
   if(out.error)throw Error(out.error);return out.result;
  }};
 queue.client=client;return queue;
}

test('Lua closes original lease, preserves attempts/evidence; prepare is idempotent and cannot reset it', {skip:!luaEnabled},async()=>{
 const f=fixture(),q=luaClient(f),options={generation:'fixture-v1',token:'token',commit:true,now:f.now};
 const out=await completeExhaustedSearch(q,f.snapshot,f.decision,f.task,f.record,options);
 assert.equal(out.confirmation.acceptedBySearchExhaustion,true);assert.equal(q.client.state[q.keys[1]][f.task.id],'completed');
 assert.equal(q.client.state[q.keys[2]][f.task.id],'4');assert.equal(q.client.state[q.keys[3]][f.task.id],undefined);
 const result=JSON.parse(q.client.state[q.keys[7]][f.task.id]);assert.equal(result.quantityAccepted,false);
 assert.deepEqual(result.missingCandidateIds,['7697504010770016763']);assert.equal(result.collectorRecord.error,'VOLUME_BELOW_THRESHOLD');
 const ledger=JSON.parse(q.client.state[q.namespace+':volume-policy-history'][f.task.id+'|fixture-v1|verified-search-completion']);
 assert.equal(ledger.before[7],'{"previous":"retained"}');
 const before=clone(q.client.state);
 const again=await completeExhaustedSearch(q,f.snapshot,f.decision,f.task,f.record,options);
 assert.equal(again.confirmation.changed,false);assert.deepEqual(q.client.state,before);
 const prepared=await applyVolumeDecision(q,f.snapshot,f.decision,{generation:'fixture-v1',commit:true});
 assert.equal(prepared.status,'completed');assert.equal(prepared.acceptedBySearchExhaustion,true);assert.deepEqual(q.client.state,before);
});

test('Lua rejects wrong/expired lease, task mismatch, stale SQL, wrong types and ledger conflicts without writes', {skip:!luaEnabled},async()=>{
 for(const mutate of [q=>q.client.state[q.keys[3]]['dy-fixture-original']='other',
  (q,f)=>q.client.state[q.keys[6]][f.task.id]=String(f.now-1),q=>q.client.state[q.keys[2]]['dy-fixture-original']='0',
  (q,f)=>q.client.state[q.keys[0]][f.task.id]=JSON.stringify({...f.task,keyword:'other'}),
  q=>q.client.types[q.keys[5]]='hash',
  (q,f)=>q.client.state[q.namespace+':volume-policy-history']={[f.task.id+'|fixture-v1|verified-search-completion']:'{}'}]){
  const f=fixture(),q=luaClient(f);mutate(q,f);const before=clone(q.client.state);
  await assert.rejects(()=>completeExhaustedSearch(q,f.snapshot,f.decision,f.task,f.record,{generation:'fixture-v1',token:'token',commit:true,now:f.now}));
  assert.deepEqual(q.client.state,before);
 }
 // JS assessment uses fixture time; Redis clock is deliberately >60s later.
 const f=fixture(),q=luaClient(f);const now=f.now;f.now+=61000;const before=clone(q.client.state);
 await assert.rejects(()=>completeExhaustedSearch(q,f.snapshot,f.decision,f.task,f.record,{generation:'fixture-v1',token:'token',commit:true,now}),/EVIDENCE_INVALID/);
 assert.deepEqual(q.client.state,before);
});

test('full volume runtime + dispatcher closes 0/37 and yields next original keyword', {skip:!luaEnabled},async()=>{
 const f=fixture(),q=luaClient(f),next={...f.task,id:'dy-fixture-next',keyword:'下一个原词'};
 q.client.state[q.keys[0]][next.id]=JSON.stringify(next);q.client.state[q.keys[1]][next.id]='pending';q.client.state[q.keys[2]][next.id]='2';
 const manifest={tasks:[f.task,next]};
 const snapshot=buildVolumeSnapshot({platform:'抖音',tasks:manifest.tasks,counts:[{...f.task,posts:37},{...next,posts:37}],
  population:'nonzero_keywords',minimumPosts:1,dbReadbackVerified:true});
 q.client.state[q.namespace+':volume-policy-snapshots']={'fixture-v1':JSON.stringify(snapshot)};
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'dy-search-closure-'));
 const original=mysql.createConnection;
 const priorEnv={MYSQL_USER:process.env.MYSQL_USER,MYSQL_PASSWORD:process.env.MYSQL_PASSWORD};
 process.env.MYSQL_USER='fixture-user';process.env.MYSQL_PASSWORD='fixture-not-a-real-secret';
 let connections=0;
 mysql.createConnection=async()=>{connections++;return {query:async()=>{},beginTransaction:async()=>{},
  execute:async()=>[[{posts:0}]],commit:async()=>{},rollback:async()=>{},end:async()=>{}};};
 try{
  await fs.writeFile(path.join(dir,'acceptance-policy.json'),JSON.stringify({enabled:true,policy:snapshot.policy,population:'nonzero_keywords',generation:'fixture-v1'}));
  const volume=await openVolumeRuntime({root:dir,stateRoot:dir,queue:q,manifest,platform:'抖音'});
  q.client.state[q.keys[1]][f.task.id]='pending';
  for(const index of [3,4,6])delete q.client.state[q.keys[index]][f.task.id];
  q.claim=async(owner,id)=>{
   const task=manifest.tasks.find(t=>t.id===id);assert.ok(task);
   q.client.state[q.keys[1]][id]='leased';q.client.state[q.keys[3]][id]='token';
   q.client.state[q.keys[6]][id]=String(f.now+300000);
   q.client.state[q.keys[2]][id]=String(Number(q.client.state[q.keys[2]][id])+1);
   return {taskId:id,token:'token',task};
  };
  const dispatcher=Object.create(RedisDispatcher.prototype);
  Object.assign(dispatcher,{volume,queue:q,manifest,current:null,timer:null,heartbeat:null,lost:false,halted:false,
   verify:async()=>{},writeLease:async()=>{},report:async()=>{},stopped:async()=>false,saveLease:async()=>{},scheduleHeartbeat:()=>{}});
  const tasks=dispatcher.tasks();const first=await tasks.next();assert.equal(first.value[1].id,f.task.id);
  const attempts=q.client.state[q.keys[2]][f.task.id];
  const confirmation=await dispatcher.finish('fail',f.record);
  assert.equal(keywordQueueConfirmed(confirmation),true);assert.equal(dispatcher.current,null);
  assert.equal(f.record.status,'completed');assert.equal(f.record.businessCompleted,true);assert.equal(f.record.quantityAccepted,false);
  assert.equal(f.record.collectionError,'VOLUME_BELOW_THRESHOLD');assert.deepEqual(f.record.missingCandidateIds,['7697504010770016763']);
  assert.equal(q.client.state[q.keys[2]][f.task.id],attempts);
  const item=await tasks.next();assert.equal(item.done,false);assert.equal(item.value[1].keyword,next.keyword);
  dispatcher.current=null;assert.equal((await tasks.next()).done,true);assert.ok(connections>=3);
 }finally{mysql.createConnection=original;for(const [key,value] of Object.entries(priorEnv)){
  if(value===undefined)delete process.env[key];else process.env[key]=value;
 }await fs.rm(dir,{recursive:true,force:true});}
});
