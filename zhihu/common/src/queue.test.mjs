import test from 'node:test';
import assert from 'node:assert/strict';
import {Queue,connect} from './queue.mjs';
import {randomUUID} from 'node:crypto';
const url=process.env.ZHIHU_TEST_REDIS_URL;
test('isolated Redis: concurrent claims, recovery, fencing, bounded retries, completion proof',{skip:!url},async()=>{
 const client=await connect({url,commandTimeoutMs:3000});const campaign='zhihu-test-'+randomUUID();const q=new Queue(client,{campaign,leaseMs:100,maxAttempts:2,retryDelayMs:0});
 const tasks=Array.from({length:5},(_,i)=>({id:'t'+i,keyword:'word'+i,sequence:i+1}));
 try{
  assert.deepEqual(await q.publish(tasks),{added:5});assert.deepEqual(await q.publish(tasks),{added:0});await assert.rejects(q.publish([{...tasks[0],keyword:'changed'}]),/PAYLOAD_CONFLICT/);
  const leases=await Promise.all(tasks.map((_,i)=>q.claim('worker-'+i)));assert.equal(new Set(leases.map(l=>l.task.id)).size,5);
  const a=leases[0];await assert.rejects(q.assert(a.task.id,'bad'),/LEASE_LOST/);
  await assert.rejects(q.finish(a.task.id,a.token,'completed',{scanComplete:false}),/INCOMPLETE_EVIDENCE/);
  await q.finish(a.task.id,a.token,'completed',{scanComplete:true,commentsComplete:true,persisted:true,unresolved:0});
  const b=leases[1];await q.finish(b.task.id,b.token,'released');const again=await q.claim('replacement');assert.equal(again.task.id,b.task.id);await assert.rejects(q.finish(b.task.id,b.token,'released'),/LEASE_LOST/);
  await new Promise(r=>setTimeout(r,140));await assert.rejects(q.assert(again.task.id,again.token),/LEASE_LOST/);const recovered=await q.claim('recovery');assert(recovered);
  await q.finish(recovered.task.id,recovered.token,'retry',{error:'fixture failure'});
  for(let i=0;i<12;i++){const next=await q.claim('drain');if(!next)break;await q.finish(next.task.id,next.token,'retry',{error:'fixture failure'});}
  const stats=await q.stats();assert.equal(stats.completed,1);assert.equal(stats.failed,4);assert.equal(stats.pending,0);
 }finally{client.close();}
});
