import test from 'node:test';
import assert from 'node:assert/strict';
import {retryImport} from '../src/mysql-import-retry.mjs';
const failure=error=>({code:2,error,retrySafe:true,commitState:'not_attempted'});
function harness(extra={}){
 let time=0;const waits=[],logs=[];
 return {waits,logs,now:()=>time,pause:async ms=>{waits.push(ms);time+=ms;},
  options:{standbyMs:1800000,now:()=>time,log:e=>logs.push(e),...extra}};
}
for(const error of ['ENOTFOUND','EAI_AGAIN','ETIMEDOUT','ECONNRESET','ECONNREFUSED','EHOSTUNREACH','ENETUNREACH','EPIPE','PROTOCOL_CONNECTION_LOST','PROTOCOL_SEQUENCE_TIMEOUT'])test('standby recovers safe network failure: '+error,async()=>{
 const h=harness();let calls=0;
 const code=await retryImport(async()=>++calls<6?failure(error):{code:0},h.pause,3,h.options);
 assert.equal(code,0);assert.deepEqual(h.waits,[5000,10000,30000,60000,120000]);
 assert.equal(h.logs.at(-1).event,'mysql_import_standby_recovered');assert.equal(calls,6);
});
test('30-minute budget is finite; the last wait is capped and no import starts at deadline',async()=>{
 const h=harness();let calls=0;
 assert.equal(await retryImport(async()=>{calls++;return failure('ENOTFOUND');},h.pause,3,h.options),2);
 assert.equal(h.now(),1815000);assert.equal(calls,19);assert.equal(h.waits.at(-1),30000);
 assert.equal(h.logs.filter(e=>e.event==='mysql_import_standby_started').length,1);
 assert.equal(h.logs.at(-2).event,'mysql_import_standby_exhausted');
});
for(const error of ['ER_ACCESS_DENIED_ERROR','ER_BAD_DB_ERROR','ER_NO_SUCH_TABLE','ENOSPC','ER_DUP_ENTRY','MYSQL_IMPORT_LOCK_TIMEOUT','ER_LOCK_DEADLOCK','ER_CON_COUNT_ERROR'])test('no long standby for non-network failure: '+error,async()=>{
 const h=harness();let calls=0;
 assert.equal(await retryImport(async()=>{calls++;return failure(error);},h.pause,3,h.options),2);
 assert.equal(calls,/LOCK|CON_COUNT/.test(error)?3:1);
 assert.equal(h.logs.some(e=>e.event==='mysql_import_standby_started'),false);
});
for(const unsafe of [{retrySafe:false},{retrySafe:undefined},{commitState:'unknown'},{commitState:'committed'},{commitState:'unverified'}])test('strict replay safety guard: '+JSON.stringify(unsafe),async()=>{
 const h=harness();let calls=0;
 assert.equal(await retryImport(async()=>{calls++;return {...failure('ENOTFOUND'),...unsafe};},h.pause,3,h.options),2);
 assert.equal(calls,1);assert.deepEqual(h.waits,[]);
});
test('stop observed within one-second polling prevents another import',async()=>{
 const h=harness({shouldStop:()=>h.now()>=20000});let calls=0;
 assert.equal(await retryImport(async()=>{calls++;return failure('ENOTFOUND');},h.pause,3,h.options),75);
 assert.equal(calls,3);assert.equal(h.now(),20000);assert.ok(h.waits.every(ms=>ms<=1000));
 assert.equal(h.logs.at(-1).event,'mysql_import_wait_cancelled');
});
test('an in-flight successful commit is honoured even if stop arrives during it',async()=>{
 let stop=false,calls=0;
 assert.equal(await retryImport(async()=>{calls++;stop=true;return {code:0};},()=>assert.fail(),3,{shouldStop:()=>stop}),0);
 assert.equal(calls,1);
});
test('unsafe outcome or auth error after standby never replays again',async()=>{
 for(const last of [{...failure('ECONNRESET'),commitState:'unknown'},failure('ER_ACCESS_DENIED_ERROR')]){
  const h=harness();let calls=0;
  assert.equal(await retryImport(async()=>++calls<4?failure('ENOTFOUND'):last,h.pause,3,h.options),2);
  assert.equal(calls,4);assert.deepEqual(h.waits,[5000,10000,30000]);
 }
});
test('invalid standby policy is rejected before any import',async()=>{
 for(const standbyMs of [-1,Infinity,NaN,7200001])await assert.rejects(
  ()=>retryImport(()=>assert.fail(),()=>assert.fail(),3,{standbyMs}),/IMPORT_STANDBY_POLICY_INVALID/);
});
