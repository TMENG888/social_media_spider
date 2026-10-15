import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {RedisTaskQueue} from './redis-task-queue.mjs';
import {RedisDispatcher} from './redis-dispatcher.mjs';
test('selected claim carries exact id and keeps same cooldown guard and limits',async()=>{
 let invocation;
 const client={eval:async(script,options)=>{invocation={script,options};return null;}};
 const queue=new RedisTaskQueue({client,campaign:'offline-audit',leaseMs:300000,maxAttempts:3,retryDelayMs:60000});
 queue.cooldownKey=queue.namespace+':rate-limit-cooldown:shared';
 assert.equal(await queue.claim('worker','existing-task'),null);
 assert.equal(invocation.options.arguments[5],'existing-task');
 assert.deepEqual(invocation.options.arguments.slice(2,5),['300000','3','60000']);
 assert.equal(invocation.options.keys.at(-1),queue.cooldownKey);
 assert.match(invocation.script,/RATE_LIMIT_COOLDOWN_ACTIVE/);
 assert.match(invocation.script,/id == ARGV\[6\]/);
 assert.match(invocation.script,/ready_at <= now/);
 await queue.claim('worker');assert.equal(invocation.options.arguments[5],'');
});
test('selected dispatcher yields only one attempt and does not advance global queue',async()=>{
 const d=Object.create(RedisDispatcher.prototype);
 let claims=0;
 Object.assign(d,{manifest:{tasks:[{redisTaskId:'existing-task'}]},halted:false,current:null,lost:false,
  workerId:'offline',owner:'offline',settings:{maxAttempts:3},stopped:async()=>false,
  saveLease:async()=>{},scheduleHeartbeat:()=>{},queue:{inspect:async()=>({status:'pending'}),
   claim:async(owner,id)=>{claims++;assert.equal(id,'existing-task');return {taskId:id,attempt:2,task:{keyword:'offline',topic:'offline'}};}}});
 const iterator=d.tasks({taskId:'existing-task'});
 assert.equal((await iterator.next()).done,false);
 d.current=null;
 assert.equal((await iterator.next()).done,true);assert.equal(claims,1);
});
test('unknown/completed selected tasks never claim',async()=>{
 const d=Object.create(RedisDispatcher.prototype);
 Object.assign(d,{manifest:{tasks:[{redisTaskId:'existing-task'}]},halted:false,current:null,stopped:async()=>false,
  queue:{inspect:async()=>({status:'completed'}),claim:async()=>{throw new Error('must not claim');}}});
 await assert.rejects(d.tasks({taskId:'unknown'}).next(),/SELECTED_TASK_NOT_IN_MANIFEST/);
 assert.equal((await d.tasks({taskId:'existing-task'}).next()).done,true);
});
test('selection does not weaken final completion predicate',async()=>{
 const source=await fs.readFile(new URL('./run-worker.mjs',import.meta.url),'utf8');
 assert.match(source,/\["completed","completed_with_skips"\]\.includes\(taskState\) && \(skipImport \|\| importResult\?\.code === 0\)/);
 assert.match(source,/dispatcher\.tasks\(\{taskId:onlyTaskId\}\)/);
 assert.match(source,/onlyTaskId&&\(skipImport\|\|phase!=='posts'\)/);
  assert.match(source,/if\(!onlyTaskId\)\{\s*const categoryRepair/);
});
test('selected preflight verifies payload without publishing or recreating tasks',async()=>{
 let invocation;
 const queue=new RedisTaskQueue({client:{eval:async(script,options)=>{invocation={script,options};return JSON.stringify({added:0,existing:1,total:279});}},campaign:'offline-audit'});
 assert.equal((await queue.verifyExisting({redisTaskId:'existing-task',keyword:'offline'})).added,0);
 assert.equal(invocation.options.arguments[0],'existing-task');
 assert.doesNotMatch(invocation.script,/HSET|ZADD|HDEL|XADD/);
 assert.match(invocation.script,/SELECTED_TASK_UNAVAILABLE/);
 assert.match(invocation.script,/TASK_PAYLOAD_CONFLICT/);
});
