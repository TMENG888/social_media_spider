import test from 'node:test';
import assert from 'node:assert/strict';
import {monitoringKey,monitoringCommand,readbackPosts,subtitleWriteCount,recordCommittedPosts,parentAlive,heartbeatLoop,flushOutbox,commitBucket} from './monitor-telemetry.mjs';
async function removeOwnedFixture(temporary) {
 const fs=await import('node:fs/promises'),os=await import('node:os'),path=await import('node:path');
 const resolved=await fs.realpath(temporary),base=await fs.realpath(os.tmpdir());
 const relative=path.relative(base,resolved);
 if(path.isAbsolute(relative)||relative.startsWith('..')||relative.includes(path.sep)||!/^monitor-(outbox|ack)-test-/.test(relative))throw new Error('Unsafe test cleanup target');
 await fs.rm(resolved,{recursive:true,force:true});
}
test('monitor-only key and command guard',async()=>{
 const ns='xhs:{production}',calls=[],client={sendCommand:async p=>{calls.push(p);return 1;}};
 for(const key of ['statuses','leases','tokens','payloads','commits:bad'])assert.throws(()=>monitoringKey(ns,key));
 await assert.rejects(()=>monitoringCommand(client,ns,'EVAL','workers',[]));
 await assert.rejects(()=>monitoringCommand(client,ns,'XACK','workers',[]));
 await monitoringCommand(client,ns,'HSET','workers',['pc/worker-01','{}']);
 assert.equal(calls.length,1);assert.equal(calls[0][1],ns+':monitor:workers');
 assert.equal(monitoringKey(ns,'commits:2026101304'),ns+':monitor:commits:2026101304');
});
test('verified readback is bounded SELECT and respects deliberate Douyin null',async()=>{
 const p={文章id:'1',平台:'抖音',项目:'p',文章标题:'title',文章内容:null,文章视频内容:null};
 const calls=[],client={execute:async(sql,args)=>{calls.push(sql);return [[{...p,文章视频内容:'existing subtitle'}]];}};
 assert.equal(await readbackPosts(client,[p]),true);
 assert.ok(calls.every(sql=>sql.startsWith('SELECT ')&&!/FOR UPDATE/.test(sql)));
 assert.equal(await readbackPosts(client,[p,p]),false);
 assert.equal(await readbackPosts({execute:async()=>[[]]},[p]),false);
 assert.equal(await readbackPosts(client,[{...p,文章标题:'mismatch'}]),false);
});
test('subtitle writes exclude unchanged and blank reimports',()=>{
 assert.equal(subtitleWriteCount(null,'new'),1);
 assert.equal(subtitleWriteCount('old','new'),1);
 assert.equal(subtitleWriteCount('same','same'),0);
 assert.equal(subtitleWriteCount('old',null),0);
 assert.equal(subtitleWriteCount(null,'  '),0);
});
test('missing telemetry environment is non-fatal after commit',async()=>{
 const previous=process.env.MONITOR_WORKER_ROOT;delete process.env.MONITOR_WORKER_ROOT;
 try{assert.equal((await recordCommittedPosts(null,[{}],{},new Date().toISOString())).source,'not_enabled');}
 finally{if(previous===undefined)delete process.env.MONITOR_WORKER_ROOT;else process.env.MONITOR_WORKER_ROOT=previous;}
 assert.equal(parentAlive(process.pid),true);
});
test('readback failure cannot throw or cause a second business commit',async()=>{
 const previous=process.env.MONITOR_WORKER_ROOT;process.env.MONITOR_WORKER_ROOT='unavailable-test-path';
 try{
   assert.equal((await recordCommittedPosts({execute:async()=>{throw new Error('test read failure');}},[{文章id:'1',平台:'抖音',项目:'p'}],{},new Date().toISOString())).source,'unavailable');
 } finally {if(previous===undefined)delete process.env.MONITOR_WORKER_ROOT;else process.env.MONITOR_WORKER_ROOT=previous;}
});
test('independent heartbeat persists every three seconds through rest and flushes at close',async()=>{
 const ctx={namespace:'xhs:{production}',campaign:'production',platform:'小红书',worker:'unused-fixture',workerId:'worker-01',computer:'fixture-pc'};
 const writes=[],sleeps=[],phases=['collecting','resting','resting','stopped'];
 let index=0,flushes=0;
 const client={isReady:true,isOpen:true,sendCommand:async args=>{
   if(args[0]==='TIME')return ['1791864000','0'];
   writes.push(args);return 1;
 },destroy(){this.isOpen=false;}};
 await heartbeatLoop('unused',123,'session',{context:async()=>ctx,parentAlive:()=>true,now:()=>1000,
   readState:async()=>({supervisorPid:123,sessionId:'session',state:phases[index++],resumeAt:'2026-10-13T05:00:00Z'}),
   connect:async()=>client,sleep:async ms=>{sleeps.push(ms);},flushOutbox:async()=>{flushes++;}});
 assert.equal(writes.length,4);assert.deepEqual(sleeps,[3000,3000,3000]);assert.equal(flushes,4);
 assert.deepEqual(writes.map(w=>JSON.parse(w[3]).state),phases);
 assert.ok(writes.every(w=>w[0]==='HSET'&&w[1]==='xhs:{production}:monitor:workers'));
 assert.ok(writes.every(w=>JSON.parse(w[3]).heartbeatIntervalSeconds===3));
 assert.equal(client.isOpen,false);
});
test('parent loss or session mismatch never manufactures a safe-stop ACK',async()=>{
 let commands=0;
 const ctx={namespace:'xhs:{production}',worker:'unused-fixture'};
 const fake={context:async()=>ctx,parentAlive:()=>false,connect:async()=>{commands++;throw new Error('must not connect');}};
 await heartbeatLoop('unused',123,'session',fake);
 assert.equal(commands,0);
 await heartbeatLoop('unused',123,'session',{...fake,parentAlive:()=>true,readState:async()=>({supervisorPid:123,sessionId:'new-session',state:'collecting'})});
 assert.equal(commands,0);
});
test('UTC commit bucket is invariant under timezone notation',()=>{
 assert.equal(commitBucket({committedAt:'2026-10-13T12:10:00+08:00'}),'commits:2026101304');
 assert.equal(commitBucket({committedAt:'2026-10-13T04:10:00Z'}),'commits:2026101304');
});
test('malformed and old campaign outbox records cannot starve valid current commits',async()=>{
 const fs=await import('node:fs/promises'),os=await import('node:os'),path=await import('node:path');
 const temporary=await fs.mkdtemp(path.join(os.tmpdir(),'monitor-outbox-test-'));
 const ctx={worker:temporary,namespace:'xhs:{production}',campaign:'production',platform:'小红书',workerId:'worker-01',computer:'fixture-pc'};
 const outbox=path.join(temporary,'.state','monitor-outbox');
 await fs.mkdir(outbox,{recursive:true});
 const malformed='00000000-0000-0000-0000-000000000000.json',foreign='10000000-0000-0000-0000-000000000000.json',valid='20000000-0000-0000-0000-000000000000.json';
 const event={schemaVersion:1,eventId:valid.slice(0,-5),campaign:ctx.campaign,platform:ctx.platform,worker:ctx.workerId,computer:ctx.computer,
   committedAt:'2026-10-13T04:10:00Z',readbackVerified:true,verifiedRows:2,newPosts:1,videoContentWrites:1};
 await fs.writeFile(path.join(outbox,malformed),'bad JSON');
 await fs.writeFile(path.join(outbox,foreign),JSON.stringify({...event,campaign:'other',eventId:foreign.slice(0,-5)}));
 await fs.writeFile(path.join(outbox,valid),JSON.stringify(event));
 const writes=[],client={sendCommand:async parts=>{writes.push(parts);return 1;}};
 try {
   await flushOutbox(client,ctx);
   assert.ok((await fs.readdir(outbox)).includes(malformed+'.invalid'));
   assert.ok((await fs.readdir(outbox)).includes(foreign+'.unmatched'));
   assert.ok((await fs.readdir(outbox)).includes(valid+'.sent'));
   assert.equal(writes[0][1],'xhs:{production}:monitor:commits:2026101304');
   assert.equal(writes[0][2],event.eventId);
   assert.equal(writes[1][0],'EXPIRE');
 } finally {await removeOwnedFixture(temporary);}
});
test('lost acknowledgement retains outbox and idempotent hash avoids double counting',async()=>{
 const fs=await import('node:fs/promises'),os=await import('node:os'),path=await import('node:path');
 const temporary=await fs.mkdtemp(path.join(os.tmpdir(),'monitor-ack-test-'));
 const ctx={worker:temporary,namespace:'xhs:{production}',campaign:'production',platform:'小红书',workerId:'worker-01',computer:'fixture-pc'};
 const outbox=path.join(temporary,'.state','monitor-outbox');await fs.mkdir(outbox,{recursive:true});
 const name='30000000-0000-0000-0000-000000000000.json';
 const event={schemaVersion:1,eventId:name.slice(0,-5),campaign:ctx.campaign,platform:ctx.platform,worker:ctx.workerId,computer:ctx.computer,
   committedAt:'2026-10-13T04:10:00Z',readbackVerified:true,verifiedRows:1,newPosts:1,videoContentWrites:0};
 await fs.writeFile(path.join(outbox,name),JSON.stringify(event));
 const ledger=new Map();let lost=true;
 const client={sendCommand:async p=>{
   if(p[0]==='HSET'){ledger.set(p[2],p[3]);if(lost){lost=false;throw new Error('lost acknowledgement');}}
   return 1;
 }};
 try {
   await assert.rejects(()=>flushOutbox(client,ctx));
   assert.ok((await fs.readdir(outbox)).includes(name));
   await flushOutbox(client,ctx);assert.equal(ledger.size,1);
   assert.ok((await fs.readdir(outbox)).includes(name+'.sent'));
 } finally {await removeOwnedFixture(temporary);}
});
