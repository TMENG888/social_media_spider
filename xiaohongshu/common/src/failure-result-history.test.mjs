import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {existsSync} from 'node:fs';
import {RedisTaskQueue as XQueue} from './redis-task-queue.mjs';
import {redisSettings,connectRedis} from './redis-connection.mjs';
const dySource=existsSync(new URL('../../../douyin/common/src/redis-task-queue.mjs',import.meta.url))
 ? '../../../douyin/common/src/' : '../../../抖音/common/src/';
const {RedisTaskQueue:DQueue}=await import(new URL(dySource+'redis-task-queue.mjs',import.meta.url));
for(const [name,Queue] of [['xhs',XQueue],['douyin',DQueue]]){
 test(`${name} failure evidence uses an explicit independent key, never shifts correction or deferral keys`,async()=>{
  let invocation;
  const queue=new Queue({campaign:'offline-failure-history',client:{eval:async(script,options)=>{invocation={script,...options};return '{}';}}});
  await queue.fail('task','token','error',{status:'completed',accepted:true});
  assert.equal(queue.keys.length,11);assert.equal(invocation.keys.length,12);
  assert.equal(invocation.keys[10],queue.namespace+':deferrals');
  assert.equal(invocation.keys[11],queue.namespace+':attempt-result-history');
  assert.match(invocation.script,/evidence.accepted=false/);
  assert.ok(invocation.script.indexOf("redis.call('HGET',KEYS[12]")<invocation.script.indexOf('local status, retry_at, attempt = retry_or_fail'));
 });
}
test('LIVE failure result history: latest readback replaces stale success but preserves every prior result',{
 skip:process.env.CORRECTION_REDIS_LIVE!=='1'},async()=>{
 assert.ok(process.env.CORRECTION_REDIS_COMMON);
 const client=await connectRedis(await redisSettings(process.env.CORRECTION_REDIS_COMMON));
 try{
  for(const [name,Queue] of [['xhs',XQueue],['douyin',DQueue]]){
   const queue=new Queue({client,campaign:'failure-evidence-fixture-'+randomUUID(),maxAttempts:2,retryDelayMs:0});
   const history=queue.namespace+':attempt-result-history';
   const read=async()=>JSON.parse(await client.eval(`local history={};for i=1,2 do
    local field='target|'..i;local value=redis.call('HGET',KEYS[12],field)
    if value then table.insert(history,field);table.insert(history,value) end end
    return cjson.encode({status=redis.call('HGET',KEYS[2],'target'),
    attempt=redis.call('HGET',KEYS[3],'target'),token=redis.call('HGET',KEYS[4],'target') or cjson.null,
    result=redis.call('HGET',KEYS[8],'target'),history=history})`,{keys:[...queue.keys,history],arguments:[]}));
   try{
    await queue.publish([{redisTaskId:'target',keyword:'fixture'}]);
    await queue.evaluate("redis.call('HSET',KEYS[8],'target',ARGV[1]);return '{}'",[JSON.stringify({accepted:true,legacyEvidence:'original'})]);
    const first=await queue.claim('fixture-owner','target');assert.equal(first.attempt,1);
    // Wrong key type must be detected before lease/result/status mutation.
    await client.eval("redis.call('ZADD',KEYS[1],1,'wrong-type');return 1",{keys:[history],arguments:[]});
    await assert.rejects(queue.fail('target',first.token,'MYSQL_IMPORT_FAILED',{version:1}),/WRONGTYPE/);
    const stillOwned=await queue.assertLease('target',first.token);assert.ok(stillOwned);
    await client.eval("redis.call('ZREM',KEYS[1],'wrong-type');return 1",{keys:[history],arguments:[]});
    await queue.fail('target',first.token,'MYSQL_IMPORT_FAILED',{version:1,accepted:true});
    let state=await read(),result=JSON.parse(state.result),historyRows=Object.fromEntries(Array.from({length:state.history.length/2},(_,i)=>[state.history[i*2],JSON.parse(state.history[i*2+1])]));
    assert.equal(state.status,'pending');assert.equal(result.version,1);assert.equal(result.accepted,false);
    assert.equal(JSON.parse(historyRows['target|1'].previousResult).legacyEvidence,'original');
    assert.equal(JSON.parse(historyRows['target|1'].submittedResult).version,1);
    const second=await queue.claim('fixture-owner','target');assert.equal(second.attempt,2);
    await assert.rejects(queue.fail('target','wrong-token','error',{version:99}),error=>error.code==='LEASE_LOST');
    await queue.fail('target',second.token,'detail gap',{version:2,status:'partial_error',error:'DETAILS_INCOMPLETE'});
    state=await read();result=JSON.parse(state.result);
    historyRows=Object.fromEntries(Array.from({length:state.history.length/2},(_,i)=>[state.history[i*2],JSON.parse(state.history[i*2+1])]));
    assert.equal(state.status,'skipped_unresolved');assert.equal(state.attempt,'2');assert.equal(result.version,2);
    assert.equal(result.accepted,false);assert.equal(result.queueDisposition,'skipped_unresolved');
    assert.equal(JSON.parse(historyRows['target|2'].previousResult).version,1);
    assert.equal(Object.keys(historyRows).length,2);
    await assert.rejects(queue.fail('target',second.token,'again',{}),error=>error.code==='LEASE_LOST');
   }finally{
    const remaining=await client.eval(`local count=0;for _,key in ipairs(KEYS) do
     local r=redis.pcall('HDEL',key,'target','target|1','target|2')
     if type(r)=='table' and r.err then redis.call('ZREM',key,'target','wrong-type') end
     local n=redis.pcall('HLEN',key);if type(n)=='table' and n.err then n=redis.call('ZCARD',key) end
     count=count+n end;return count`,{keys:[...queue.keys,history],arguments:[]});
    assert.equal(remaining,0,name+' isolated fixture cleanup');
   }
  }
 }finally{await client.close();}
});
