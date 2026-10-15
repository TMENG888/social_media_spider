import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {targetKey,controlKey,parseRequest,RemoteStopControl,requestStop,releaseStop,controlStatus,controlCommand,controlContext,connectControl} from './remote-stop-control.mjs';
import {heartbeatLoop} from './monitor-telemetry.mjs';

function memoryRedis(){
  const hashes=new Map(),calls=[];
  return {calls,hashes,isOpen:true,isReady:true,destroy(){this.isOpen=false;},async sendCommand(p){
    calls.push(p);const [cmd,key,field,value]=p;const h=hashes.get(key)||new Map();hashes.set(key,h);
    if(cmd==='TIME')return ['1791940000','0'];
    if(cmd==='HGET')return h.get(field)||null;
    if(cmd==='HGETALL')return [...h.entries()].flat();
    if(cmd==='HVALS')return [...h.values()];
    if(cmd==='HSET'){h.set(field,value);return 1;}
    if(cmd==='HSETNX'){if(h.has(field))return 0;h.set(field,value);return 1;}
    if(cmd==='EVAL'){
      if(p[1]==="return redis.call('HGETALL',KEYS[1])")return [...(hashes.get(p[3])||new Map()).entries()].flat();
      const q=hashes.get(p[3])||new Map(),v=q.get(p[4]);hashes.set(p[3],q);
      if(p[1].includes('return ARGV[2]')){if(v)return v;q.set(p[4],p[5]);return p[5];}
      if(!v)return 0;
      if(JSON.parse(v).commandId!==p[5])return -1;q.delete(p[4]);return 1;
    }
    throw new Error('UNEXPECTED_COMMAND');
  }};
}
test('English repository and Chinese deployment directories preserve canonical platform',()=>fixture(async(ctx,client,dir)=>{
  for(const [directory,platform,prefix] of [['xiaohongshu','小红书','xhs'],['小红书','小红书','xhs'],['douyin','抖音','xhs:douyin'],['抖音','抖音','xhs:douyin']]){
    const common=path.join(dir,directory,'common');
    await fs.mkdir(path.join(common,'tasks'),{recursive:true});
    await fs.writeFile(path.join(common,'redis-config.json'),JSON.stringify({url:'redis://127.0.0.1:6379/0',campaign:'offline',taskPoolCampaign:'offline'}));
    await fs.writeFile(path.join(common,'tasks/redis-tasks.json'),JSON.stringify({manifestHash:'offline',tasks:[]}));
    const control=await controlContext(common);
    assert.equal(control.platform,platform);
    assert.equal(control.namespace,prefix+':{offline}');
  }
}));

async function fixture(fn,{live=false}={}){
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'remote-stop-test-'));
  const campaign='remote-stop-test_'+randomUUID().replaceAll('-','');
  let ctx={platform:'小红书',namespace:'xhs:{'+campaign+'}',campaign,computer:'FIXTURE-PC',worker:'worker-01',workerRoot:dir,target:'FIXTURE-PC/worker-01'};
  let client=memoryRedis();
  if(live){const prod=await controlContext(path.resolve(import.meta.dirname,'..'));ctx={...ctx,settings:prod.settings,platform:prod.platform,namespace:(prod.platform==='小红书'?'xhs':'xhs:douyin')+':{'+campaign+'}'};client=await connectControl(ctx);}
  try{await fn(ctx,client,dir);}
  finally{
    try{if(live&&client.isOpen){
      assert.match(ctx.campaign,/^remote-stop-test_[a-f0-9]{32}$/);
      for(const suffix of ['stop-requests','stop-acks'])await client.sendCommand(['EVAL',"return redis.call('HDEL',KEYS[1],ARGV[1])",'1',controlKey(ctx.namespace,suffix),ctx.target]);
    }}catch(error){console.error('Fixture expiry unavailable: '+(String(error.message).startsWith('NOPERM')?'NOPERM':'ERROR'));}
    finally{if(client.isOpen)client.destroy();}
    const resolved=await fs.realpath(dir),base=await fs.realpath(os.tmpdir()),relative=path.relative(base,resolved);
    assert.ok(!path.isAbsolute(relative)&&!relative.includes(path.sep)&&/^remote-stop-test-/.test(relative));
    await fs.rm(resolved,{recursive:true,force:true});
  }
}
test('exact target and dedicated keys reject wildcards/task keys',async()=>{
  assert.equal(targetKey('pc-a','WORKER-01'),'PC-A/worker-01');
  for(const [host,worker] of [['*','worker-01'],['PC','all'],['PC/x','worker-01'],['PC','worker-01/..']])assert.throws(()=>targetKey(host,worker));
  for(const ns of ['wechat:tasks','xhs:{bad}:statuses'])assert.throws(()=>controlKey(ns,'stop-requests'));
  for(const suffix of ['statuses','tokens','pending'])assert.throws(()=>controlKey('xhs:{test}',suffix));
  await assert.rejects(()=>controlCommand(memoryRedis(),{namespace:'xhs:{test}'},'XACK','stop-requests'));
});
test('stop is idempotent; no task commands and no cross-host flags',()=>fixture(async(ctx,c,dir)=>{
  const first=await requestStop(c,ctx,'fixture-pc','worker-01');
  const second=await requestStop(c,ctx,'fixture-pc','worker-01');assert.equal(first.commandId,second.commandId);
  const foreign=new RemoteStopControl({...ctx,target:'OTHER-PC/worker-01'},c);assert.equal(await foreign.poll(),false);
  await assert.rejects(()=>fs.access(path.join(dir,'.state','stop.requested')));
  assert.ok(c.calls.every(p=>(p[0]==='EVAL'?p[3]:p[1]).includes(':control:')));
}));
test('receive persists both flags before acknowledgement; final status and command match',()=>fixture(async(ctx,c,dir)=>{
  const req=await requestStop(c,ctx,'FIXTURE-PC','worker-01');const control=new RemoteStopControl(ctx,c);
  assert.equal((await controlStatus(c,ctx))[0].status,'requested_only');
  assert.equal(await control.poll(),true);
  for(const name of ['supervisor.stop','stop.requested'])assert.equal(JSON.parse(await fs.readFile(path.join(dir,'.state',name),'utf8')).commandId,req.commandId);
  assert.equal((await controlStatus(c,ctx))[0].status,'draining');
  await control.poll({terminal:'stopped'});assert.equal((await controlStatus(c,ctx))[0].status,'stopped');
}));
test('startup hold blocks gate; compare-release cannot erase a new command',()=>fixture(async(ctx,c,dir)=>{
  const req=await requestStop(c,ctx,'FIXTURE-PC','worker-01');const control=new RemoteStopControl(ctx,c);
  await assert.rejects(()=>control.gate(),/REMOTE_STOP_HOLD/);
  await assert.rejects(()=>releaseStop(c,ctx,'FIXTURE-PC','worker-01',randomUUID()),/STOP_COMMAND_CHANGED/);
  assert.equal(await releaseStop(c,ctx,'FIXTURE-PC','worker-01',req.commandId),1);
  // Accepted stop remains latched in this run, even if the hold is released.
  assert.equal(await control.poll(),true);
  const next=new RemoteStopControl(ctx,c);await next.gate();
  assert.equal((await controlStatus(c,ctx))[0].status,'no_remote_hold');
  // Release never deletes manual flags or launches a process.
  await fs.access(path.join(dir,'.state','supervisor.stop'));
}));
test('malformed, wrong platform and wrong campaign commands fail closed',()=>fixture(async(ctx,c)=>{
  const req=await requestStop(c,ctx,'FIXTURE-PC','worker-01');
  for(const bad of [{...req,platform:'抖音'},{...req,campaign:'other'},{...req,action:'force_kill'},{...req,target:'OTHER-PC/worker-01'},{...req,commandId:'bad'}])assert.throws(()=>parseRequest(JSON.stringify(bad),ctx));
  await c.sendCommand(['HSET',controlKey(ctx.namespace,'stop-requests'),ctx.target,'bad JSON']);
  await assert.rejects(()=>new RemoteStopControl(ctx,c).gate());
}));
test('lost ACK still leaves durable receipt; failed cleanup cannot claim safe stop',()=>fixture(async(ctx,c,dir)=>{
  await requestStop(c,ctx,'FIXTURE-PC','worker-01');const send=c.sendCommand.bind(c);
  c.sendCommand=async p=>{if(p[0]==='HSET')throw new Error('ACK_LOST');return send(p);};
  const control=new RemoteStopControl(ctx,c);await assert.rejects(()=>control.poll(),/ACK_LOST/);
  const receipt=JSON.parse(await fs.readFile(control.receiptFile,'utf8'));assert.equal(receipt.status,'draining');
  c.sendCommand=send;await control.poll({terminal:'exit_unconfirmed'});
  assert.equal((await controlStatus(c,ctx))[0].status,'exit_unconfirmed');
}));
test('collector exit is distinct from supervisor safe-stop and stale heartbeat',()=>fixture(async(ctx,c)=>{
  await requestStop(c,ctx,'FIXTURE-PC','worker-01');const control=new RemoteStopControl(ctx,c);await control.poll();await control.ack('collector_stopped');
  await c.sendCommand(['HSET',ctx.namespace+':monitor:workers','FIXTURE-PC/worker-01',JSON.stringify({computer:'FIXTURE-PC',worker:'worker-01',lastSeenAt:'2020-01-01T00:00:00Z'})]);
  const row=(await controlStatus(c,ctx))[0];assert.equal(row.status,'collector_stopped');assert.equal(row.heartbeatFresh,false);
}));
test('independent supervisor receives stop during rest and confirms only final stopped state',()=>fixture(async(ctx,c,dir)=>{
  await requestStop(c,ctx,'FIXTURE-PC','worker-01');const control=new RemoteStopControl(ctx,c),sleeps=[];
  let cycle=0;
  await heartbeatLoop(dir,123,'fixture-session',{
    context:async()=>({...ctx,worker:dir,workerId:'worker-01'}),parentAlive:()=>true,now:()=>0,
    controlFactory:async()=>control,connect:async()=>c,flushOutbox:async()=>{},sleep:async ms=>{sleeps.push(ms);},
    readState:async()=>({sessionId:'fixture-session',supervisorPid:123,state:cycle++?'stopped':'resting'})
  });
  assert.deepEqual(sleeps,[3000]);assert.equal(JSON.parse(await fs.readFile(control.receiptFile,'utf8')).status,'stopped');
  const acks=c.calls.filter(p=>p[0]==='HSET'&&p[1].endsWith(':control:stop-acks')).map(p=>JSON.parse(p[3]).status);
  assert.deepEqual(acks,['draining','stopped']);await fs.access(path.join(dir,'.state','supervisor.stop'));
}));
test('parent disappears after receipt: no forged stopped acknowledgement',()=>fixture(async(ctx,c,dir)=>{
  await requestStop(c,ctx,'FIXTURE-PC','worker-01');const control=new RemoteStopControl(ctx,c);
  let alive=true;
  await heartbeatLoop(dir,123,'fixture-session',{
    context:async()=>({...ctx,worker:dir,workerId:'worker-01'}),parentAlive:()=>alive,now:()=>0,
    controlFactory:async()=>control,connect:async()=>c,flushOutbox:async()=>{},sleep:async()=>{alive=false;},
    readState:async()=>({sessionId:'fixture-session',supervisorPid:123,state:'collecting'})
  });
  assert.equal(JSON.parse(await fs.readFile(control.receiptFile,'utf8')).status,'draining');
}));
test('source supervises rest and does not overwrite worker errors with stop success',async()=>{
  const common=path.resolve(import.meta.dirname,'..'),ps=await fs.readFile(path.join(common,'run-distributed-worker.ps1'),'utf8');
  assert.match(ps,/Assert-RemoteControlAvailable/);assert.match(ps,/remote-stop-control\.mjs/);
  assert.match(ps,/Close-MonitorSupervisor \$RemoteFinalState/);
  const supervisor=await fs.readFile(path.join(common,'monitor-supervisor.ps1'),'utf8');
  assert.match(supervisor,/remote-control-ready\.json/);assert.match(supervisor,/exit_unconfirmed/);
});
test('LIVE isolated Redis stop, receive, fail/finish ACK, startup hold and release',{skip:process.env.REMOTE_CONTROL_LIVE_TEST!=='1'},()=>fixture(async(ctx,c,dir)=>{
  const req=await requestStop(c,ctx,'FIXTURE-PC','worker-01');
  assert.equal((await requestStop(c,ctx,'FIXTURE-PC','worker-01')).commandId,req.commandId);
  const control=new RemoteStopControl(ctx,c);await assert.rejects(()=>control.gate(),/REMOTE_STOP_HOLD/);
  await control.poll({terminal:'exit_unconfirmed'});assert.equal((await controlStatus(c,ctx))[0].status,'exit_unconfirmed');
  await control.poll({terminal:'stopped'});assert.equal((await controlStatus(c,ctx))[0].status,'stopped');
  await assert.rejects(()=>releaseStop(c,ctx,'FIXTURE-PC','worker-01',randomUUID()),/STOP_COMMAND_CHANGED/);
  assert.equal(await releaseStop(c,ctx,'FIXTURE-PC','worker-01',req.commandId),1);
  await new RemoteStopControl(ctx,c).gate();
  for(const name of ['supervisor.stop','stop.requested'])await fs.access(path.join(dir,'.state',name));
},{live:true}));
