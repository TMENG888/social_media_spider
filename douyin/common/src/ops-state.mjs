// A one-way, best-effort public copy. Collection never reads these files back.
import path from 'node:path';
import {existsSync} from 'node:fs';
import fs from 'node:fs/promises';
import {BackgroundStateWriter} from './background-state-writer.mjs';
export const OPS_STATE_VERSION='ops-state-split-20261111-v1';
const writers=new Map();
const pick=(v,keys)=>Object.fromEntries(keys.filter(k=>v?.[k]!==undefined).map(k=>[k,v[k]]));
export function opsDestination(file){
  const absolute=path.resolve(file),name=path.basename(absolute),parent=path.dirname(absolute);
  let worker,kind;
  if(name==='worker_status.json'&&path.basename(parent)==='runs'){worker=path.dirname(parent);kind='worker-status';}
  else if(path.basename(parent)==='.state'){
    kind={'monitor-supervisor.json':'supervisor','collection-cycle-pause.json':'pause','rate-limit-cooldown.json':'cooldown'}[name];worker=path.dirname(parent);
  }else if(name==='session.json'&&path.basename(parent)==='login-bridge'&&path.basename(path.dirname(parent))==='.state'){
    worker=path.dirname(path.dirname(parent));kind='login';
  }
  if(!kind||!/^worker-\d{2}$/.test(path.basename(worker||'')))return null;
  return {worker,kind,file:path.join(worker,'.state','ops',kind==='login'?'login-v2.json':kind+'.json')};
}
export function opsEnvelope(destination,value,now=Date.now()){
  const {kind,worker}=destination;let data;
  if(kind==='worker-status'){
    data=pick(value,['campaign','currentKeyword','startedAt','finishedAt']);
    data.tasks=(value.tasks||[]).slice(-2).map(t=>pick(t,['keyword','status','startedAt','finishedAt','posts','commentThreads','pendingImport']));
  }else if(kind==='supervisor')data=pick(value,['state','updatedAt','resumeAt','supervisorPid','sessionId']);
  else if(kind==='pause')data=pick(value,['phase','resumeAtMs','deadlineAtMs']);
  else if(kind==='cooldown')data=pick(value,['active','untilMs','automaticResume','manualRequired','serverTime','scope']);
  else if(kind==='login'){
    data=pick(value,['machine','platform','workerId','sessionId','updatedAt','phase','generation','verifiedAt','challenge','feedback','auth','smsReason']);
    data.image=pick(value.image,['filename','sha256']);
    data.ack=pick(value.ack,['commandId','ok','reason','at']);
    data.sms=pick(value.sms,['challengeId','publicKey','expiresAt','attempts']);
  }
  return {schemaVersion:1,version:OPS_STATE_VERSION,kind,projectionVersion:kind==='login'?'login-auth-copy-20261111-v2':undefined,publishedAt:new Date(now).toISOString(),data,
    stops:kind==='supervisor'||kind==='worker-status'?['supervisor.stop','stop.requested'].filter(n=>existsSync(path.join(worker,'.state',n))):[]};
}
export function publishOpsState(file,value){
  try{
    const destination=opsDestination(file);if(!destination)return false;
    let writer=writers.get(destination.file);
    if(!writer){writer=new BackgroundStateWriter({file:destination.file,logFile:path.join(destination.worker,'.state','ops-write-diagnostics.jsonl')});writers.set(destination.file,writer);}
    return writer.enqueue(opsEnvelope(destination,value));
  }catch(error){console.warn('[运维副本保存失败] '+(error.code||'OPS_PUBLISH_FAILED'));return false;}
}
export async function flushOpsState(file){const destination=opsDestination(file);return destination?await writers.get(destination.file)?.flush():true;}
export async function closeOpsStates(){const active=[...writers.values()];writers.clear();return Promise.all(active.map(w=>w.close()));}
// The existing on-machine heartbeat republishes state for old producers during
// rolling upgrades. All private reads stay local; the dashboard never opens them.
export async function refreshOpsCopies(worker){
  const files=['runs/worker_status.json','.state/monitor-supervisor.json','.state/collection-cycle-pause.json','.state/rate-limit-cooldown.json','.state/login-bridge/session.json'];
  return Promise.all(files.map(async name=>{
    const file=path.join(worker,name);
    try{return publishOpsState(file,JSON.parse((await fs.readFile(file,'utf8')).replace(/^\uFEFF/,'')));}
    catch(error){if(error.code==='ENOENT')return publishOpsState(file,{});console.warn('[运维副本源状态不可用] '+name+' '+(error.code||'INVALID_JSON'));return false;}
  }));
}
