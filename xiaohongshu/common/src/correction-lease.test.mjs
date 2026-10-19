import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import fs from 'node:fs/promises';
import {existsSync} from 'node:fs';
import {RedisTaskQueue as XQueue} from './redis-task-queue.mjs';
import * as x from './correction-lease.mjs';
import {redisSettings,connectRedis} from './redis-connection.mjs';
const dySource=existsSync(new URL('../../../douyin/common/src/redis-task-queue.mjs',import.meta.url))
 ? '../../../douyin/common/src/' : '../../../抖音/common/src/';
const {RedisTaskQueue:DQueue}=await import(new URL(dySource+'redis-task-queue.mjs',import.meta.url));
const d=await import(new URL(dySource+'correction-lease.mjs',import.meta.url));

for(const [name,Queue,correction] of [['xhs',XQueue,x],['douyin',DQueue,d]]){
 test(`${name}: correction ledger never overwrites deferral counters and keeps cooldown guard`,async()=>{
  let invocation;
  const queue=new Queue({campaign:'offline-correction',client:{eval:async(script,options)=>{
   invocation={script,options};return JSON.stringify({payload:JSON.stringify({keyword:'fixture'}),attempt:4,correctionPolicy:correction.CORRECTION_POLICY});
  }}});
  queue.cooldownKey=queue.namespace+':rate-limit-cooldown:shared';
  assert.equal((await correction.claimCorrection(queue,'owner','task',correction.CORRECTION_POLICY)).attempt,4);
  assert.equal(invocation.options.keys[10],queue.namespace+':deferrals');
  assert.equal(invocation.options.keys[11],queue.namespace+':correction-history');
  assert.equal(invocation.options.keys[12],queue.cooldownKey);
  assert.match(invocation.script,/CORRECTION_ALREADY_ATTEMPTED/);
  assert.match(invocation.script,/RATE_LIMIT_COOLDOWN_ACTIVE/);
  assert.doesNotMatch(invocation.script,/HSET',KEYS\[3\],id,0|HSET',KEYS\[11\]/);
  await assert.rejects(correction.claimCorrection(queue,'owner','task','wrong'),/POLICY_NOT_SUPPORTED/);
 });
 test(`${name}: ordinary selected retry cannot reclaim other task leases`,async()=>{
  let script;
  const queue=new Queue({campaign:'offline-correction',client:{eval:async(value)=>{script=value;return null;}}});
  await queue.claim('owner','exact-task');
  assert.match(script,/for _, id in ipairs\(expired\) do\s+if not ARGV\[6\] or ARGV\[6\] == '' or id == ARGV\[6\] then/);
 });
 test(`${name}: correction interruption does not decrement or requeue attempts`,async()=>{
  let script;
  const queue=new Queue({campaign:'offline-correction',client:{eval:async(value)=>{script=value;return '{}';}}});
  await correction.pauseCorrection(queue,'task','token',{status:'stopped'});
  assert.match(script,/CORRECTION_INTERRUPTED/);assert.match(script,/LEASE_LOST/);
  assert.doesNotMatch(script,/HINCRBY|HSET',KEYS\[3\]|ZADD',KEYS\[6\]/);
 });
}
test('XHS correction selection still requires production posts and an exact existing task',async()=>{
 const source=await fs.readFile(new URL('./run-worker.mjs',import.meta.url),'utf8');
 assert.match(source,/correctionPolicy.*!onlyTaskId/);
 assert.match(source,/onlyTaskId&&\(skipImport\|\|phase!=='posts'\)/);
});

test('live isolated correction fixtures: history, one-shot scope, stop, cooldown and atomicity',{
 skip:process.env.CORRECTION_REDIS_LIVE!=='1'},async()=>{
 assert.ok(process.env.CORRECTION_REDIS_COMMON,'Explicit existing Redis credential context required');
 const settings=await redisSettings(process.env.CORRECTION_REDIS_COMMON),client=await connectRedis(settings);
 try{
  for(const [name,Queue,correction] of [['xhs',XQueue,x],['douyin',DQueue,d]]){
   const queue=new Queue({client,campaign:'coverage80-correction-fixture-'+randomUUID()});
   const ledger=queue.namespace+':correction-history',cooldown=queue.namespace+':fixture-cooldown';
   const allKeys=[...queue.keys,ledger,cooldown];
   try{
    await queue.publish([{redisTaskId:'target',keyword:'fixture'},{redisTaskId:'other',keyword:'fixture-other'}]);
    await queue.evaluate(`redis.call('HSET',KEYS[2],'target','skipped_unresolved');redis.call('HSET',KEYS[3],'target','3');
     redis.call('HSET',KEYS[8],'target','{"oldEvidence":true}');redis.call('HSET',KEYS[9],'target','old-error');
     redis.call('HSET',KEYS[11],'target','2');redis.call('ZREM',KEYS[6],'target');
     redis.call('HSET',KEYS[2],'other','leased');redis.call('HSET',KEYS[3],'other','2');
     redis.call('HSET',KEYS[4],'other','other-token');redis.call('HSET',KEYS[5],'other','other-owner');
     redis.call('ZREM',KEYS[6],'other');redis.call('ZADD',KEYS[7],1,'other');return '{}'`);
    const snapshot=()=>queue.evaluate(`return cjson.encode({status=redis.call('HGET',KEYS[2],'target'),attempts=redis.call('HGET',KEYS[3],'target'),
      deferrals=redis.call('HGET',KEYS[11],'target'),otherStatus=redis.call('HGET',KEYS[2],'other'),otherToken=redis.call('HGET',KEYS[4],'other')})`);
    // A ledger wrong-type must fail before any state mutation (Lua does not roll back).
    await client.eval("redis.call('ZADD',KEYS[1],1,'wrong-type');return 1",{keys:[ledger],arguments:[]});
    await assert.rejects(correction.claimCorrection(queue,'owner','target',correction.CORRECTION_POLICY),/WRONGTYPE/);
    assert.equal((await snapshot()).status,'skipped_unresolved');
    await client.eval("redis.call('ZREM',KEYS[1],'wrong-type');redis.call('HSET',KEYS[2],'state','{\"manualRequired\":true}');return 1",{keys:[ledger,cooldown],arguments:[]});
    queue.cooldownKey=cooldown;
    await assert.rejects(correction.claimCorrection(queue,'owner','target',correction.CORRECTION_POLICY),/COOLDOWN_ACTIVE/);
    assert.equal((await snapshot()).attempts,'3');
    await client.eval("redis.call('HDEL',KEYS[1],'state');return 1",{keys:[cooldown],arguments:[]});
    const lease=await correction.claimCorrection(queue,'owner','target',correction.CORRECTION_POLICY);
    assert.equal(lease.attempt,4);assert.equal(lease.task.keyword,'fixture');
    const old=JSON.parse(await client.eval("return redis.call('HGET',KEYS[1],ARGV[1])",{keys:[ledger],arguments:['target|'+correction.CORRECTION_POLICY]}));
    assert.equal(old.originalAttempts,3);assert.equal(old.originalStatus,'skipped_unresolved');
    assert.equal(JSON.parse(old.originalResult).oldEvidence,true);assert.equal(old.originalError,'old-error');
    assert.equal((await snapshot()).deferrals,'2');assert.equal((await snapshot()).otherToken,'other-token');
    await assert.rejects(correction.claimCorrection(queue,'other-owner','target',correction.CORRECTION_POLICY),/ALREADY_ATTEMPTED/);
    await assert.rejects(queue.complete('target',lease.token,{status:'completed',coverage:{ok:true}}),/COVERAGE_UNVERIFIED/);
    await assert.rejects(correction.pauseCorrection(queue,'target','wrong-token',{}),/LEASE_LOST/);
    await correction.pauseCorrection(queue,'target',lease.token,{status:'stopped'});
    const after=await snapshot();assert.equal(after.status,'failed');assert.equal(after.attempts,'4');
    assert.equal(after.otherStatus,'leased');assert.equal(after.otherToken,'other-token');
    await assert.rejects(correction.claimCorrection(queue,'owner','target',correction.CORRECTION_POLICY),/ALREADY_ATTEMPTED/);
    assert.equal(await queue.claim('owner','target'),null);
    assert.equal((await snapshot()).otherToken,'other-token',name+' selected claim must not recover unrelated expired lease');
    // Isolated fixture only: exercise the new scoped completion gate, including
    // old-policy and denominator-reduction rejection before accepting 8/10.
    await queue.publish([{redisTaskId:'scope-success',keyword:'fixture-scope'}]);
    const scopedLease=await queue.claim('owner','scope-success');
    const coverage={policy:'20261015-scoped-usable-db-80-v3',scopePolicy:'20261015-target-year-relevant-v2',ok:true,
     scanComplete:true,dbReadbackVerified:true,numerator:8,denominator:10,discoveredUniqueCount:12,
     excludedWithDateEvidence:1,excludedWithScopeEvidence:1,scopeExclusions:[{noteId:'excluded',evidenceDigest:'a'.repeat(64)}],scopeExclusionsDigest:'b'.repeat(64)};
    await assert.rejects(queue.complete('scope-success',scopedLease.token,{status:'completed',coverage:{...coverage,policy:'20261015-usable-db-80-v1'}}),/COVERAGE_UNVERIFIED/);
    await assert.rejects(queue.complete('scope-success',scopedLease.token,{status:'completed',coverage:{...coverage,discoveredUniqueCount:11}}),/SCOPE_EVIDENCE_UNVERIFIED/);
    await assert.rejects(queue.complete('scope-success',scopedLease.token,{status:'completed',coverage:{...coverage,scopeExclusions:[]}}),/SCOPE_EVIDENCE_UNVERIFIED/);
    const accepted=await queue.complete('scope-success',scopedLease.token,{status:'completed',coverage});
    assert.equal(accepted.status,'completed');
    assert.equal((await snapshot()).otherToken,'other-token');
   }finally{
    const remaining=await client.eval(`local remaining=0;for _,key in ipairs(KEYS) do
      local result=redis.pcall('HDEL',key,'target','other','scope-success',ARGV[1],'state')
      if type(result)=='table' and result.err then redis.call('ZREM',key,'target','other','scope-success','wrong-type') end
      local count=redis.pcall('HLEN',key)
      if type(count)=='table' and count.err then count=redis.call('ZCARD',key) end
      remaining=remaining+count
     end;return remaining`,{keys:allKeys,arguments:['target|'+correction.CORRECTION_POLICY]});
    assert.equal(remaining,0,'isolated fixture keys fully cleaned');
   }
  }
 }finally{await client.close();}
});
