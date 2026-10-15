// Dedicated control keys only. Never claim, ACK, reset a task, or kill a PID.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {randomUUID} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {createClient} from 'redis';
import {redisSettings} from './redis-connection.mjs';

export function targetKey(computer,worker) {
  computer=String(computer||'').trim().toUpperCase();
  worker=String(worker||'').trim().toLowerCase();
  if(!/^[A-Z0-9][A-Z0-9_.-]{0,62}$/.test(computer)||!/^worker-[0-9]{2}$/.test(worker))throw new Error('EXACT_TARGET_REQUIRED');
  return computer+'/'+worker;
}
export function controlKey(namespace,suffix) {
  if(!/^(xhs|xhs:douyin):\{[A-Za-z0-9_-]{1,200}\}$/.test(namespace)||!['stop-requests','stop-acks'].includes(suffix))throw new Error('CONTROL_KEY_REJECTED');
  return namespace+':control:'+suffix;
}
export function parseRequest(raw,ctx) {
  if(!raw)return null;
  const value=JSON.parse(raw);
  if(value.schemaVersion!==1||value.action!=='safe_stop'||value.target!==ctx.target||value.campaign!==ctx.campaign||value.platform!==ctx.platform||! /^[a-f0-9-]{36}$/.test(value.commandId)||!Number.isFinite(Date.parse(value.requestedAt)))throw new Error('INVALID_STOP_REQUEST');
  return value;
}
export async function controlContext(commonRoot,workerRoot=null) {
  const root=path.resolve(commonRoot),directory=path.basename(path.dirname(root));
  const platform=({'xiaohongshu':'小红书','douyin':'抖音'})[directory] || directory;
  const prefix=platform==='小红书'?'xhs':platform==='抖音'?'xhs:douyin':null;
  if(!prefix)throw new Error('UNSUPPORTED_CONTROL_PLATFORM');
  const settings=await redisSettings(root);
  const config=JSON.parse((await fs.readFile(path.join(root,'redis-config.json'),'utf8')).replace(/^\uFEFF/,''));
  const manifest=JSON.parse((await fs.readFile(path.join(root,'tasks/redis-tasks.json'),'utf8')).replace(/^\uFEFF/,''));
  const campaign=config.taskPoolCampaign||settings.campaign+'-mysql-'+manifest.manifestHash.slice(0,16);
  const namespace=prefix+':{'+campaign+'}';controlKey(namespace,'stop-requests');
  const computer=os.hostname().toUpperCase();
  if(workerRoot){
    workerRoot=path.resolve(workerRoot);
    if(path.dirname(workerRoot)!==path.dirname(root))throw new Error('WORKER_ROOT_REJECTED');
  }
  const worker=workerRoot?path.basename(workerRoot):null;
  return {settings,namespace,campaign,platform,computer,worker,workerRoot,target:worker?targetKey(computer,worker):null};
}
export async function connectControl(ctx) {
  const client=createClient({RESP:2,url:ctx.settings.url,username:ctx.settings.username,password:ctx.settings.password,
    disableOfflineQueue:true,socket:{connectTimeout:3000,reconnectStrategy:false}});
  client.on('error',()=>{});
  let timer;
  try {await Promise.race([client.connect(),new Promise((_,reject)=>{timer=setTimeout(()=>{client.destroy();reject(new Error('CONTROL_CONNECT_TIMEOUT'));},4000);})]);return client;}
  catch(error){if(client.isOpen)client.destroy();throw error;}
  finally{clearTimeout(timer);}
}
export async function boundedCommand(client,parts) {
  let timer;
  try{return await Promise.race([client.sendCommand(parts),new Promise((_,reject)=>{timer=setTimeout(()=>{if(client.isOpen)client.destroy();reject(new Error('CONTROL_TIMEOUT'));},4000);})]);}
  finally{clearTimeout(timer);}
}
export async function controlCommand(client,ctx,command,suffix,args=[]) {
  if(!['HGET','HVALS','HSET','TIME'].includes(command))throw new Error('CONTROL_COMMAND_REJECTED');
  const parts=command==='TIME'?['TIME']:[command,controlKey(ctx.namespace,suffix),...args.map(String)];
  try{return await boundedCommand(client,parts);}catch(error){
    if(!String(error.message).startsWith('NOPERM'))throw error;
    // Existing workers expose the queue's script interface, not every raw
    // hash command. Use only this fixed operation and its validated control key.
    const script=command==='TIME'?"return redis.call('TIME')":
      "return redis.call('"+command+"',KEYS[1],unpack(ARGV))";
    return boundedCommand(client,['EVAL',script,command==='TIME'?'0':'1',...(command==='TIME'?[]:[controlKey(ctx.namespace,suffix),...args.map(String)])]);
  }
}
async function atomicJson(file,value) {
  await fs.mkdir(path.dirname(file),{recursive:true});const temp=file+'.'+randomUUID()+'.tmp';
  await fs.writeFile(temp,JSON.stringify(value,null,2),'utf8');await fs.rename(temp,file);
}
export class RemoteStopControl {
  constructor(ctx,client){this.ctx=ctx;this.client=client;this.request=null;this.timer=null;this.polling=null;this.closed=false;}
  static async open(commonRoot,workerRoot){const ctx=await controlContext(commonRoot,workerRoot);return new RemoteStopControl(ctx,await connectControl(ctx));}
  get receiptFile(){return path.join(this.ctx.workerRoot,'.state','remote-stop-receipt.json');}
  async flags(request) {
    const state=path.join(this.ctx.workerRoot,'.state');await fs.mkdir(state,{recursive:true});
    // Supervisor first; no future cycle may clear the collector stop flag.
    for(const name of ['supervisor.stop','stop.requested'])await atomicJson(path.join(state,name),{source:'redis_remote_control',...request});
  }
  async ack(status) {
    if(!this.request)return;
    const value={...this.request,status,computer:this.ctx.computer,worker:this.ctx.worker,observedAt:new Date().toISOString()};
    await atomicJson(this.receiptFile,value);
    await controlCommand(this.client,this.ctx,'HSET','stop-acks',[this.ctx.target,JSON.stringify(value)]);
    return value;
  }
  async poll({terminal=null}={}) {
    const raw=await controlCommand(this.client,this.ctx,'HGET','stop-requests',[this.ctx.target]);
    const request=parseRequest(raw,this.ctx);
    if(request){this.request=request;await this.flags(request);await this.ack(terminal||'draining');}
    return Boolean(this.request);
  }
  async gate() {
    // An authoritative empty read is needed before a manual new launch.
    const held=await this.poll();
    if(held)throw new Error('REMOTE_STOP_HOLD: release the exact command before manual startup');
    await fs.unlink(this.receiptFile).catch(error=>{if(error.code!=='ENOENT')throw error;});
  }
  watch(onFailure=()=>{}) {
    const tick=async()=>{
      if(this.closed)return;
      this.polling=this.poll().catch(async()=>{
        // Fail closed on control-channel loss; no forced termination, no false ACK.
        await this.flags({reason:'REMOTE_CONTROL_UNAVAILABLE'});await onFailure();
      });
      try{await this.polling;}finally{if(!this.closed)this.timer=setTimeout(tick,3000);}
    };
    this.timer=setTimeout(tick,3000);
  }
  async close(status=null) {
    this.closed=true;clearTimeout(this.timer);await this.polling;
    try{if(status)await this.ack(status);}finally{if(this.client.isOpen)this.client.destroy();}
  }
}
export async function requestStop(client,ctx,computer,worker,reason='Operator requested safe stop') {
  const target=targetKey(computer,worker);
  const request={schemaVersion:1,commandId:randomUUID(),action:'safe_stop',platform:ctx.platform,campaign:ctx.campaign,target,requestedAt:new Date().toISOString(),reason:String(reason).slice(0,200)};
  // Idempotent: repeated clicks must not replace an outstanding stop command.
  const script="local v=redis.call('HGET',KEYS[1],ARGV[1]); if v then return v end; redis.call('HSET',KEYS[1],ARGV[1],ARGV[2]); return ARGV[2]";
  const raw=await boundedCommand(client,['EVAL',script,'1',controlKey(ctx.namespace,'stop-requests'),target,JSON.stringify(request)]);
  return parseRequest(raw,{...ctx,target});
}
export async function releaseStop(client,ctx,computer,worker,commandId) {
  if(!/^[a-f0-9-]{36}$/.test(commandId||''))throw new Error('EXACT_COMMAND_ID_REQUIRED');
  const key=controlKey(ctx.namespace,'stop-requests'),target=targetKey(computer,worker);
  // No other Lua or arbitrary keys are accepted. A stale release cannot erase a newer stop.
  const script="local v=redis.call('HGET',KEYS[1],ARGV[1]); if not v then return 0 end; local c=cjson.decode(v); if c.commandId~=ARGV[2] then return -1 end; return redis.call('HDEL',KEYS[1],ARGV[1])";
  let timer;
  try{
    const result=await Promise.race([client.sendCommand(['EVAL',script,'1',key,target,commandId]),new Promise((_,reject)=>{timer=setTimeout(()=>{if(client.isOpen)client.destroy();reject(new Error('CONTROL_TIMEOUT'));},4000);})]);
    if(Number(result)===-1)throw new Error('STOP_COMMAND_CHANGED');return Number(result);
  }finally{clearTimeout(timer);}
}
const records=values=>(values||[]).map(v=>JSON.parse(v));
export async function controlStatus(client,ctx,computer=null,worker=null) {
  const requests=Object.fromEntries(records(await controlCommand(client,ctx,'HVALS','stop-requests')).map(v=>[v.target,v]));
  const acknowledgements=Object.fromEntries(records(await controlCommand(client,ctx,'HVALS','stop-acks')).map(v=>[v.target,v]));
  // Dedicated telemetry registry only; task leases are not machine evidence.
  const workers=Object.fromEntries(records(await boundedCommand(client,['HVALS',ctx.namespace+':monitor:workers'])).map(v=>[targetKey(v.computer,v.worker),v]));
  const targets=new Set([...Object.keys(requests),...Object.keys(acknowledgements),...Object.values(workers).map(w=>targetKey(w.computer,w.worker))]);
  const selected=computer||worker?targetKey(computer,worker):null;
  if(selected)targets.add(selected);
  return [...targets].filter(t=>!selected||t===selected).map(target=>{
    const request=requests[target]||null,ack=acknowledgements[target]||null;
    const machine=Object.values(workers).find(w=>targetKey(w.computer,w.worker)===target)||null;
    const matching=ack&&request&&ack.commandId===request.commandId;
    return {target,request,ack:matching?ack:null,lastAck:ack,heartbeat:machine,
      heartbeatFresh:Boolean(machine&&Date.now()-Date.parse(machine.lastSeenAt)>=0&&Date.now()-Date.parse(machine.lastSeenAt)<30000),
      status:request?(matching?ack.status:'requested_only'):'no_remote_hold'};
  });
}
if(process.argv[1]&&pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url){
  const args={};for(let i=2;i<process.argv.length;i++){const key=process.argv[i].replace(/^--/,'');args[key]=process.argv[++i];}
  let client,control;
  try {
    if(args.action==='gate'){
      control=await RemoteStopControl.open(args.root,args['worker-root']);await control.gate();console.log('Remote stop gate verified: no hold.');
    }else{
      const ctx=await controlContext(args.root);
      if(args.action==='preview'){
        console.log(JSON.stringify({platform:ctx.platform,campaign:ctx.campaign,target:targetKey(args.computer,args.worker),action:'safe_stop',dryRun:true},null,2));
      }else{
      client=await connectControl(ctx);
      let result;
      if(args.action==='status')result=await controlStatus(client,ctx,args.computer,args.worker);
      else if(['stop','release'].includes(args.action)){
        if(args['confirm-target']!==targetKey(args.computer,args.worker))throw new Error('CONFIRM_EXACT_TARGET_REQUIRED');
        result=args.action==='stop'?{request:await requestStop(client,ctx,args.computer,args.worker),delivery:'requested_only; query status for node acknowledgement'}:
          {released:await releaseStop(client,ctx,args.computer,args.worker,args['command-id']),note:'Hold release does not start any process. Manually launch after verifying stop.'};
      }else throw new Error('EXPLICIT_ACTION_REQUIRED');
      console.log(JSON.stringify(result,null,2));
      }
    }
  }catch(error){console.error(error.message?.startsWith('REMOTE_STOP_HOLD')?'REMOTE_STOP_HOLD: collection remains blocked.':'Remote control failed: '+(/^[A-Z_]+$/.test(error.message||'')?error.message:'CONNECTION_OR_VALIDATION_ERROR'));process.exitCode=1;}
  finally{await control?.close().catch(()=>{});if(client?.isOpen)client.destroy();}
}
