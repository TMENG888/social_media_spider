import path from 'node:path';
import fs from 'node:fs/promises';
import os from 'node:os';
import {redisSettings,connectRedis} from './redis-connection.mjs';
import {loadTaskManifest} from './redis-task-manifest.mjs';
import {scopedTasks} from './task-scope.mjs';
import {AnnualCheckpointStore,seedLegacyTask,ANNUAL_RESUME_VERSION} from './annual-resume.mjs';

const args=Object.fromEntries(process.argv.slice(2).filter((_,i)=>i%2===0).map((k,i)=>[k.slice(2),process.argv.slice(2)[2*i+1]]));
const root=path.resolve(args.root||'.'),worker=path.resolve(args.worker||'.');
const settings=await redisSettings(root),client=await connectRedis(settings);
const manifest=await loadTaskManifest(path.join(root,'tasks','redis-tasks.json'));
const campaign=settings.taskPoolCampaign||`${settings.campaign}-mysql-${manifest.manifestHash.slice(0,16)}`;
const namespace=`xhs:{${campaign}}`,tasks=await scopedTasks(root,manifest.tasks);
const slug=text=>String(text).normalize('NFKC').replace(/[\\/:*?"<>|\s]+/g,'_').replace(/^_+|_+$/g,'').slice(0,100);
const report=[];
try{
 for(const task of tasks){
  const id=task.redisTaskId||task.id;
  const store=new AnnualCheckpointStore({client,namespace,taskId:id,source:os.hostname()+':'+path.basename(worker)});
  const base=path.join(worker,'.state','redis',campaign,task.topic||'default',`${slug(task.keyword)}-${id.slice(-12)}`);
  let count=0;try{count=await seedLegacyTask({base,keyword:task.keyword,store});}
  catch(e){if(!/ANNUAL_SEED_TASK_BUSY/.test(e.message))throw e;report.push({keyword:task.keyword,status:'active_lease_preserved'});continue;}
  const raw=await client.eval(`
local t=redis.call('TIME');local now=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
local status=redis.call('HGET',KEYS[1],ARGV[1]);local expiry=tonumber(redis.call('ZSCORE',KEYS[2],ARGV[1])) or 0
if status=='leased' and expiry>now then return cjson.encode({status='active_lease_preserved'}) end
if not status then return redis.error_reply('ANNUAL_TASK_MISSING') end
local old=redis.call('HGET',KEYS[3],ARGV[1]);local result=old and cjson.decode(old) or nil
if type(result)=='table' and result.searchAcceptance and result.searchAcceptance.ok==true and result.importExitCode==0
 and (status=='completed' or status=='completed_with_skips') then return cjson.encode({status='verified_annual_kept'}) end
if redis.call('HEXISTS',KEYS[4],ARGV[1])==0 then
 redis.call('HSET',KEYS[4],ARGV[1],cjson.encode({status=status,result=old or false,error=redis.call('HGET',KEYS[5],ARGV[1]) or false,
 attempts=redis.call('HGET',KEYS[6],ARGV[1]) or false,at=now,policy=ARGV[3]}))
end
if status=='failed' or status=='completed' or status=='completed_with_skips' or status=='skipped_unresolved' or status=='leased' then
 redis.call('HSET',KEYS[1],ARGV[1],'pending');redis.call('ZADD',KEYS[7],tonumber(ARGV[2]),ARGV[1])
 redis.call('ZREM',KEYS[2],ARGV[1]);redis.call('HDEL',KEYS[8],ARGV[1]);redis.call('HDEL',KEYS[9],ARGV[1]);redis.call('ZREM',KEYS[10],ARGV[1])
 return cjson.encode({status='annual_continuation_pending',previous=status})
end
return cjson.encode({status=status,unchanged=true})`,{
   keys:['statuses','leases','results','annual-migration-history-v1','errors','attempts','pending','tokens','owners','failed'].map(k=>namespace+':'+k),
   arguments:[id,String(task.sequence),ANNUAL_RESUME_VERSION]});
  report.push({keyword:task.keyword,seeded:count,...JSON.parse(raw)});
 }
 const output={policy:ANNUAL_RESUME_VERSION,at:new Date().toISOString(),machine:os.hostname(),worker:path.basename(worker),rows:report};
 await fs.writeFile(args.output,JSON.stringify(output,null,2),'utf8');
 console.log(JSON.stringify({policy:ANNUAL_RESUME_VERSION,machine:os.hostname(),seeded:report.reduce((n,r)=>n+(r.seeded||0),0),counts:Object.fromEntries([...new Set(report.map(r=>r.status))].map(s=>[s,report.filter(r=>r.status===s).length]))}));
}finally{await client.close();}
