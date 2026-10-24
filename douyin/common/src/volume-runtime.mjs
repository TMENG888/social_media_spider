import fs from 'node:fs/promises';
import path from 'node:path';
import mysql from 'mysql2/promise';
import {mysqlConnectionOptions} from './import-mysql.mjs';
import {readVolumeSnapshot,readTaskVolume,validateVolumeSnapshot,VOLUME_POLICY} from './volume-acceptance.mjs';
import {applyVolumeDecision} from './volume-queue-policy.mjs';
import {annualInputFromCollector} from './annual-runtime-evidence.mjs';
import {completeAnnualKeyword} from './annual-queue-policy.mjs';
import {operationalFailure} from './retry-exhaustion.mjs';
import {ResetOncePolicy} from './reset-once.mjs';
import {completeExhaustedSearch} from './search-exhaustion-completion.mjs';

export async function openVolumeRuntime({root,stateRoot,queue,manifest,platform}){
 let config;
 try{config=JSON.parse((await fs.readFile(path.join(root,'acceptance-policy.json'),'utf8')).replace(/^\uFEFF/,''));}
 catch(error){if(error.code==='ENOENT')return null;throw error;}
 if(config.enabled!==true)return null;
 if(config.policy!==VOLUME_POLICY||config.population!=='nonzero_keywords'||!/^[-_a-zA-Z0-9]{1,100}$/.test(config.generation||''))throw new Error('VOLUME_CONFIG_INVALID');
 const connect=()=>mysql.createConnection(mysqlConnectionOptions());
 const key=queue.namespace+':volume-policy-snapshots';
 const existing=await queue.client.eval('return redis.call("HGET",KEYS[1],ARGV[1])',{keys:[key],arguments:[config.generation]});
 let snapshot=existing?JSON.parse(existing):await readVolumeSnapshot({connect,platform,tasks:manifest.tasks,population:config.population,minimumPosts:1});
 if(!existing){
  if(snapshot.threshold==null)throw new Error('VOLUME_POPULATION_EMPTY');
  const raw=await queue.client.eval('local old=redis.call("HGET",KEYS[1],ARGV[1]);if old then return old end;redis.call("HSET",KEYS[1],ARGV[1],ARGV[2]);return ARGV[2]',
   {keys:[key],arguments:[config.generation,JSON.stringify(snapshot)]});snapshot=JSON.parse(raw);
 }
 validateVolumeSnapshot(snapshot,{platform,tasks:manifest.tasks});
 if(snapshot.population!==config.population||snapshot.threshold<1)throw new Error('VOLUME_SHARED_SNAPSHOT_MISMATCH');
 const snapshotFile=path.join(stateRoot,'volume-acceptance-snapshot.json');
 await fs.writeFile(snapshotFile,JSON.stringify(snapshot,null,2));
 queue.volumeBaselineKey=queue.namespace+':volume-attempt-baseline';
 const recollection=new ResetOncePolicy(queue);
 console.log(`[数量验收] ${platform}，非零入库词P80=${snapshot.threshold}篇；字幕质量不阻塞；阈值版本=${config.generation}`);
 return {snapshot,snapshotFile,generation:config.generation,recollection,
  read:taskId=>readTaskVolume({connect,snapshot,taskId}),
  apply:(decision,options={})=>applyVolumeDecision(queue,snapshot,decision,{generation:config.generation,...options}),
  async prepare(taskId){
   const replay=await recollection.prepare(taskId);
   if(replay.status!=='absent')return {decision:{posts:null,threshold:snapshot.threshold},confirmation:replay};
   const decision=await this.read(taskId);const confirmation=await this.apply(decision,{commit:true});return {decision,confirmation};},
  async finish(taskId,token,record,{pause=false}={}){
   const replay=await recollection.finish(taskId,token,record,{pause});
   if(replay?.acceptedByResetOnce)return {confirmation:replay};
   if(replay)return {confirmation:null};
   if(pause)return {confirmation:null};
   if(operationalFailure(record))return {confirmation:null};
   const decision=await this.read(taskId);
   if(decision.ok)return {decision,confirmation:await this.apply(decision,{token,commit:true})};
   const task=manifest.tasks.find(t=>(t.redisTaskId||t.id)===taskId);
   const exhausted=await completeExhaustedSearch(queue,snapshot,decision,task,record,
    {generation:config.generation,token,commit:true});
   if(exhausted.confirmation)return {decision,searchExhaustionEvidence:exhausted.evidence,confirmation:exhausted.confirmation};
   const input=await annualInputFromCollector({decision,task,record,stateRoot,connect});
   if(input){
    const {evidence,confirmation}=await completeAnnualKeyword(queue,snapshot,decision,input,
     {generation:config.generation,token,commit:true,record});
    if(confirmation)return {decision,annualEvidence:evidence,confirmation};
   }
   const terminal=await this.apply(decision,{token,commit:true,finishBelow:true,record});
   return {decision,confirmation:terminal.status==='completed'?terminal:null};
  }};
}
