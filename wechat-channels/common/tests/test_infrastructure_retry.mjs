import test from 'node:test';
import assert from 'node:assert/strict';
import {retryInfrastructure} from '../src/infrastructure-retry.mjs';
import {retryImport,importReceipt,isTransient} from '../src/mysql-import-retry.mjs';
import {executeReadback} from '../src/volume-db-readback.mjs';
import {buildVolumeSnapshot} from '../src/volume-acceptance.mjs';

test('DNS/connection/lock failures recover with bounded waits and sanitized logs',async()=>{
 for(const code of ['ENOTFOUND','EAI_AGAIN','ETIMEDOUT','ECONNRESET','ECONNREFUSED','ER_LOCK_WAIT_TIMEOUT','ER_LOCK_DEADLOCK','MYSQL_IMPORT_LOCK_TIMEOUT','ER_CON_COUNT_ERROR']){
  let calls=0;const waits=[],logs=[];
  const result=await retryInfrastructure(async()=>{if(++calls<3)throw Object.assign(Error('SECRET sql/password'),{code});return 'ok';},
   {pause:async ms=>waits.push(ms),log:e=>logs.push(e)});
  assert.equal(result,'ok');assert.equal(calls,3);assert.deepEqual(waits,[5000,10000]);
  assert.equal(logs.at(-1).event,'infrastructure_retry_recovered');assert.doesNotMatch(JSON.stringify(logs),/SECRET/);
 }
});
test('third transient failure opens fuse; permanent/config/schema errors stop immediately',async()=>{
 let calls=0;const logs=[];
 await assert.rejects(()=>retryInfrastructure(async()=>{calls++;throw Object.assign(Error('secret'),{code:'ENOTFOUND'});},
  {pause:async()=>{},log:e=>logs.push(e)}),{code:'ENOTFOUND'});
 assert.equal(calls,3);assert.equal(logs.at(-1).event,'infrastructure_circuit_open');assert.equal(logs.at(-1).taskConfirmed,false);
 for(const code of ['ER_ACCESS_DENIED_ERROR','ER_BAD_DB_ERROR','ER_NO_SUCH_TABLE','ER_BAD_FIELD_ERROR','ER_DUP_ENTRY','MYSQL_TARGET_INVALID']){
  let count=0;await assert.rejects(()=>retryInfrastructure(async()=>{count++;throw Object.assign(Error('secret'),{code});},
   {pause:()=>assert.fail('must not wait'),log:()=>{}}));assert.equal(count,1);
 }
});
test('unknown/already committed writes are never automatically replayed',async()=>{
 for(const commitState of ['unknown','committed']){
  let calls=0;const code=await retryImport(async()=>{calls++;return {code:2,error:'ECONNRESET',retrySafe:false,commitState};},()=>assert.fail());
  assert.equal(code,2);assert.equal(calls,1);
 }
 let calls=0,waits=[];assert.equal(await retryImport(async()=>++calls<3?{code:2,error:'ENOTFOUND',retrySafe:true,commitState:'not_attempted'}:{code:0},async ms=>waits.push(ms)),0);
 assert.deepEqual(waits,[5000,10000]);assert.equal(isTransient('ENOTFOUND'),true);
 const receipt=importReceipt('noise',JSON.stringify({status:'failed',errorCode:'ECONNRESET',retrySafe:false,commitState:'unknown'}));
 assert.equal(receipt.retrySafe,false);assert.equal(importReceipt('stale stack trace','password secret'),null);
});
test('readonly quantity readback reconnects and re-queries; never manufactures zero on failure',async()=>{
 const old={MYSQL_USER:process.env.MYSQL_USER,MYSQL_PASSWORD:process.env.MYSQL_PASSWORD};
 process.env.MYSQL_USER='fixture';process.env.MYSQL_PASSWORD='fixture-only';
 const task={id:'fixture-id',keyword:'fixture',projectName:'fixture'};
 const snapshot=buildVolumeSnapshot({platform:'微信视频号',tasks:[task],counts:[{...task,posts:37}],population:'nonzero_keywords',minimumPosts:1,dbReadbackVerified:true});
 try{
  let calls=0,queries=0,rollbacks=0,closed=0;const waits=[];
  const createConnection=async()=>{
   if(++calls===1)throw Object.assign(Error('secret'),{code:'ENOTFOUND'});
   const attempt=calls;return {query:async()=>{},beginTransaction:async()=>{},
    execute:async()=>{queries++;if(attempt===2)throw Object.assign(Error('secret'),{code:'ECONNRESET'});return [[{posts:29}]];},
    rollback:async()=>{rollbacks++;},commit:async()=>{},end:async()=>{closed++;}};
  };
  const input={operation:'task',snapshot,taskId:task.id};
  const result=await executeReadback(input,{createConnection,retryOptions:{pause:async ms=>waits.push(ms),log:()=>{}}});
  assert.equal(result.posts,29);assert.equal(result.dbReadbackVerified,true);assert.equal(calls,3);
  assert.equal(queries,2);assert.equal(rollbacks,1);assert.equal(closed,2);assert.deepEqual(waits,[5000,10000]);
  let failures=0;await assert.rejects(()=>executeReadback(input,{createConnection:async()=>{failures++;throw Object.assign(Error('secret'),{code:'ENOTFOUND'});},
   retryOptions:{pause:async()=>{},log:()=>{}}}),{code:'ENOTFOUND'});assert.equal(failures,3);
 }finally{for(const [key,value]of Object.entries(old)){if(value===undefined)delete process.env[key];else process.env[key]=value;}}
});
