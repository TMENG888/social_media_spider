// Monitoring writes are restricted to new :monitor: keys; never import a dispatcher.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {randomUUID} from 'node:crypto';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createClient} from 'redis';
import {redisSettings} from './redis-connection.mjs';
import {RemoteStopControl} from './remote-stop-control.mjs';

const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const platformDirectory=path.basename(path.dirname(root));
const platform=({'xiaohongshu':'小红书','douyin':'抖音'})[platformDirectory] || platformDirectory;
const prefix=platform==='小红书'?'xhs':platform==='抖音'?'xhs:douyin':null;
if(!prefix)throw new Error('Unsupported telemetry platform');
const nonempty=value=>String(value??'').trim().length>0;

export function monitoringKey(namespace,suffix) {
  if(!/^(xhs|xhs:douyin):\{[A-Za-z0-9_-]{1,200}\}$/.test(namespace)
      || !(suffix==='workers'||suffix==='probe'||suffix==='probe-events'||/^commits:[0-9]{10}$/.test(suffix)))throw new Error('Non-monitoring key rejected');
  return namespace+':monitor:'+suffix;
}
export async function context(workerRoot=process.env.MONITOR_WORKER_ROOT) {
  if(!workerRoot)throw new Error('Monitoring worker root unavailable');
  const worker=path.resolve(workerRoot);
  if(path.dirname(worker)!==path.dirname(root)||!/^worker-[0-9]{2}$/.test(path.basename(worker)))throw new Error('Invalid monitoring worker root');
  const settings=await redisSettings(root);
  const config=JSON.parse(await fs.readFile(path.join(root,'redis-config.json'),'utf8'));
  const manifest=JSON.parse(await fs.readFile(path.join(root,'tasks','redis-tasks.json'),'utf8'));
  const campaign=config.taskPoolCampaign||settings.campaign+'-mysql-'+manifest.manifestHash.slice(0,16);
  const namespace=prefix+':{'+campaign+'}';
  monitoringKey(namespace,'workers');
  return {settings,worker,workerId:path.basename(worker),campaign,namespace,platform,computer:os.hostname()};
}
async function clientFor(ctx) {
  const client=createClient({RESP:2,url:ctx.settings.url,username:ctx.settings.username,password:ctx.settings.password,
    disableOfflineQueue:true,socket:{connectTimeout:5000,reconnectStrategy:false}});
  client.on('error',()=>{});
  let timer;
  try {
    await Promise.race([client.connect(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Monitoring connection timeout')),6000);})]);
    return client;
  } catch(error){if(client.isOpen)client.destroy();throw error;}
  finally{clearTimeout(timer);}
}
async function bounded(client,parts) {
  let timer;
  try{return await Promise.race([client.sendCommand(parts),new Promise((_,reject)=>{
    timer=setTimeout(()=>{if(client.isOpen)client.destroy();reject(new Error('Monitoring command timeout'));},5000);
  })]);}finally{clearTimeout(timer);}
}
export async function monitoringCommand(client,namespace,command,suffix,args) {
  if(!['HSET','EXPIRE','TIME'].includes(command))throw new Error('Non-monitoring command rejected');
  const parts=command==='TIME'?['TIME']:[command,monitoringKey(namespace,suffix),...args.map(String)];
  try{return await bounded(client,parts);}catch(error){
    if(!String(error.message).startsWith('NOPERM'))throw error;
    const script=command==='TIME'?"return redis.call('TIME')":"return redis.call('"+command+"',KEYS[1],unpack(ARGV))";
    return bounded(client,['EVAL',script,command==='TIME'?'0':'1',...(command==='TIME'?[]:[monitoringKey(namespace,suffix),...args.map(String)])]);
  }
}
async function writeJson(file,value) {
  await fs.mkdir(path.dirname(file),{recursive:true});
  const temporary=file+'.tmp-'+randomUUID();
  await fs.writeFile(temporary,JSON.stringify(value));
  await fs.rename(temporary,file);
}
export async function readbackPosts(connection,posts,fields=['文章标题','文章内容','文章视频内容']) {
  const expected=new Map(),groups=new Map(),observed=new Map();
  for(const row of posts) {
    const key=JSON.stringify([row.文章id,row.平台,row.项目]);
    if(expected.has(key))return false;expected.set(key,row);
    const groupKey=JSON.stringify([row.平台,row.项目]);
    if(!groups.has(groupKey))groups.set(groupKey,{platform:row.平台,project:row.项目,ids:[]});
    groups.get(groupKey).ids.push(row.文章id);
  }
  for(const group of groups.values())for(let offset=0;offset<group.ids.length;offset+=250) {
    const ids=group.ids.slice(offset,offset+250);
    const sql='SELECT `文章id`,`平台`,`项目`,`文章标题`,`文章内容`,`文章视频内容` FROM ods_social_media_post WHERE `平台`=? AND `项目`=? AND `文章id` IN ('+ids.map(()=>'?').join(',')+')';
    const [rows]=await connection.execute(sql,[group.platform,group.project,...ids]);
    for(const row of rows) {
      const key=JSON.stringify([row.文章id,row.平台,row.项目]);
      if(observed.has(key))return false;observed.set(key,row);
    }
  }
  for(const [key,row] of expected) {
    const stored=observed.get(key);
    if(!stored)return false;
    for(const field of fields) {
      // Douyin's NULL subtitle is deliberately COALESCE-preserved.
      if(row.平台==='抖音'&&field==='文章视频内容'&&row[field]==null)continue;
      if(String(stored[field]??'')!==String(row[field]??''))return false;
    }
  }
  return true;
}
export const commitBucket=event=>'commits:'+new Date(event.committedAt).toISOString().replace(/[-:TZ.]/g,'').slice(0,10);
export function validCommit(event,ctx,name) {
  return event?.schemaVersion===1&&event.readbackVerified===true&&event.eventId+'.json'===name
    &&event.campaign===ctx.campaign&&event.platform===ctx.platform&&event.computer===ctx.computer&&event.worker===ctx.workerId
    &&Number.isFinite(Date.parse(event.committedAt))
    &&['newPosts','videoContentWrites','verifiedRows'].every(key=>Number.isSafeInteger(event[key])&&event[key]>=0)
    &&event.newPosts<=event.verifiedRows&&event.videoContentWrites<=event.verifiedRows;
}
async function writeCommit(client,ctx,event) {
  const suffix=commitBucket(event);
  await monitoringCommand(client,ctx.namespace,'HSET',suffix,[event.eventId,JSON.stringify(event)]);
  // Retention failure never invalidates an acknowledged ledger write.
  await monitoringCommand(client,ctx.namespace,'EXPIRE',suffix,[172800]).catch(()=>{});
}
export async function probeTelemetry(workerRoot) {
  const ctx=await context(workerRoot),client=await clientFor(ctx);
  try {
    const id=randomUUID(),payload=JSON.stringify({deploymentTest:true,checkedAt:new Date().toISOString()});
    await monitoringCommand(client,ctx.namespace,'HSET','probe',[id,payload]);
    await monitoringCommand(client,ctx.namespace,'HSET','probe-events',[id,payload]);
    await monitoringCommand(client,ctx.namespace,'EXPIRE','probe',[3600]).catch(()=>{});
    await monitoringCommand(client,ctx.namespace,'EXPIRE','probe-events',[3600]).catch(()=>{});
    return {platform:ctx.platform,monitorWritesConfirmed:true};
  } finally{if(client.isOpen)client.destroy();}
}
export function subtitleWriteCount(previous,next) {
  return nonempty(next)&&String(previous??'')!==String(next)?1:0;
}
export async function recordCommittedPosts(connection,posts,postResult,committedAt,subtitleOnly=false) {
  // All telemetry failures are non-fatal AFTER the business commit. Never cause a retry of committed data.
  try {
    if(!posts.length||!process.env.MONITOR_WORKER_ROOT)return {source:'not_enabled'};
    if(!await readbackPosts(connection,posts,subtitleOnly?['文章视频内容']:undefined))return {source:'readback_mismatch'};
    const ctx=await context();
    const event={schemaVersion:1,eventId:randomUUID(),platform:ctx.platform,campaign:ctx.campaign,
      computer:ctx.computer,worker:ctx.workerId,committedAt,readbackVerified:true,
      newPosts:Number(postResult.inserted||0),videoContentWrites:Number(postResult.videoContentWrites||0),
      verifiedRows:posts.length,projects:[...new Set(posts.map(r=>r.项目))].sort()};
    const outbox=path.join(ctx.worker,'.state','monitor-outbox');
    const file=path.join(outbox,event.eventId+'.json');
    await writeJson(file,event);
    // Network delivery is performed by the independent supervisor helper.
    // Never hold the shared business import mutex while waiting for Redis.
    return {source:'spooled',eventId:event.eventId};
  } catch{return {source:'unavailable'};}
}
export async function flushOutbox(client,ctx) {
  const outbox=path.join(ctx.worker,'.state','monitor-outbox');
  const files=await fs.readdir(outbox).catch(()=>[]);
  for(const name of files.filter(n=>/^[a-f0-9-]{36}\.json$/.test(n))) {
    const file=path.join(outbox,name);
    let event;
    try {event=JSON.parse(await fs.readFile(file,'utf8'));}catch(error) {
      if(error.code==='ENOENT')continue;
      // Preserve malformed monitoring records without blocking valid commits.
      await fs.rename(file,file+'.invalid').catch(()=>{});continue;
    }
    if(!validCommit(event,ctx,name)){
      await fs.rename(file,file+'.unmatched').catch(()=>{});continue;
    }
    await writeCommit(client,ctx,event);
    await fs.rename(file,file+'.sent');
    break; // One valid commit per frame; never starve the independent heartbeat.
  }
}
export function parentAlive(pid) {
  try{process.kill(pid,0);return true;}catch(error){return error.code==='EPERM';}
}
export async function heartbeatLoop(workerRoot,parentPid,sessionId,runtime={}) {
  const ctx=await (runtime.context||context)(workerRoot),stateFile=path.join(ctx.worker,'.state','monitor-supervisor.json');
  const alive=runtime.parentAlive||parentAlive,clock=runtime.now||Date.now;
  const readState=runtime.readState||(async()=>JSON.parse(await fs.readFile(stateFile,'utf8')));
  const connect=runtime.connect||clientFor,flush=runtime.flushOutbox||flushOutbox;
  const sleep=runtime.sleep||(ms=>new Promise(resolve=>setTimeout(resolve,ms)));
  let client;
  let control;
  try {
    while(alive(parentPid)) {
      const started=clock();
      try {
        const state=await readState();
        if(state.supervisorPid!==parentPid||state.sessionId!==sessionId)break;
        if(!runtime.context||runtime.controlFactory){
          try{
            control ||= await (runtime.controlFactory?runtime.controlFactory():RemoteStopControl.open(root,workerRoot));
            await control.poll({terminal:['stopped','exit_unconfirmed'].includes(state.state)?state.state:null});
          }catch(error){
            // No restart if the control channel cannot be checked while resting.
            for(const name of ['supervisor.stop','stop.requested'])await writeJson(path.join(ctx.worker,'.state',name),{source:'remote_control',reason:'REMOTE_CONTROL_UNAVAILABLE'});
            if(control){await control.flags({reason:'REMOTE_CONTROL_UNAVAILABLE'});await control.close().catch(()=>{});control=null;}
            throw error;
          }
        }
        if(!client?.isReady){if(client?.isOpen)client.destroy();client=await connect(ctx);}
        const serverTime=await monitoringCommand(client,ctx.namespace,'TIME',null,[]);
        const lastSeenAt=new Date(Number(serverTime[0])*1000+Number(serverTime[1])/1000).toISOString();
        const record={schemaVersion:1,platform:ctx.platform,campaign:ctx.campaign,computer:ctx.computer,worker:ctx.workerId,
          supervisorPid:parentPid,sessionId,lastSeenAt,heartbeatIntervalSeconds:3,state:state.state,resumeAt:state.resumeAt||null};
        await monitoringCommand(client,ctx.namespace,'HSET','workers',[ctx.computer+'/'+ctx.workerId,JSON.stringify(record)]);
        if(!runtime.context)await writeJson(path.join(ctx.worker,'.state','remote-control-ready.json'),{sessionId,supervisorPid:parentPid,readyAt:lastSeenAt});
        await flush(client,ctx);
        if(['stopped','exit_unconfirmed'].includes(state.state))break;
      } catch {
        // No secrets, raw error text, task state changes, or automatic crawler restart.
        if(client?.isOpen)client.destroy();client=null;
      }
      await sleep(Math.max(100,3000-(clock()-started)));
    }
    // Do not manufacture a safe-stop ACK when the parent disappears.
  } finally{await control?.close().catch(()=>{});if(client?.isOpen)client.destroy();}
}
if(process.argv[1]&&pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url) {
  const args=process.argv.slice(2);
  if(args[0]!=='--heartbeat')throw new Error('Explicit heartbeat mode required');
  const parentPid=Number(args[2]),sessionId=args[3];
  if(!Number.isSafeInteger(parentPid)||parentPid<1||!sessionId)throw new Error('Invalid supervisor identity');
  await heartbeatLoop(args[1],parentPid,sessionId);
}
