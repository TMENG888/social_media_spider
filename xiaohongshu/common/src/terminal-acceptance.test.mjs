import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {terminalEvidenceReason,recheckTerminalAcceptance,TERMINAL_RECHECK_POLICY} from './terminal-acceptance.mjs';
import {SearchExhaustion} from './search-acceptance.mjs';
import {openCheckpoint,saveCandidates,markCompleted} from './checkpoint.mjs';
import {RedisTaskQueue} from './redis-task-queue.mjs';
import {redisSettings,connectRedis} from './redis-connection.mjs';
import {CORRECTION_POLICY} from './correction-lease.mjs';

function evidence(checkpointDb='C:/fixture/state/checkpoint.sqlite',outputDir='C:/fixture/output'){
 const at=Date.now()-1000,task={id:'original-id',redisTaskId:'target',topic:'fixture',keyword:'fixture keyword',cutoff:'2026-01-01',collectorConfig:{asrEnabled:false,maxStagnantRounds:15}};
 const endpoint=new SearchExhaustion();let exhaustion;
 for(let i=0;i<16;i++)exhaustion=endpoint.observe({contextValid:true,rendered:true,loading:false,loadFailed:false,atBottom:true,count:10,height:1000,lastId:'last',terminal:false});
 const collector={runId:`${at}-fixture`,checkpointDb,status:'completed_with_skips',error:null,finishedAt:new Date().toISOString(),
  scopeAcceptance:{ok:true,acceptanceVersion:'20261014-scoped-verified-search-end-v2'},asrJobs:{completed:8,pendingTotal:0},
  searchSummaries:[{keyword:task.keyword,reason:'platform_exhausted',exhaustion}]};
 const record={taskId:task.id,workerId:'fixture',keyword:task.keyword,topic:task.topic,runId:collector.runId,checkpointDb,stateDir:path.dirname(checkpointDb),outputDir,
  status:'incomplete',exitCode:0,importExitCode:0,finishedAt:new Date().toISOString(),error:'USABLE_DB_COVERAGE_BELOW_80'};
 const payload=JSON.stringify(task);
 const correction={policy:CORRECTION_POLICY,taskId:'target',originalPayload:payload,correctionAttempt:4,claimedAt:at-1000,owner:'fixture-owner'};
 const snapshot={taskId:'target',status:'failed',payload,attempts:'4',result:'{"oldEvidence":true}',error:'old-error',deferrals:'2',failed:'1',
  pending:null,lease:null,token:null,owner:null,recheck:null,correction:JSON.stringify(correction)};
 return {task,collector,record,snapshot,checkpointDb,outputDir};
}

test('terminal-only recheck accepts only the same healthy correction run with replayable endpoint proof',()=>{
 const input=evidence();assert.equal(terminalEvidenceReason(input),null);
 const cases=[
  [x=>x.snapshot.status='leased','REQUIRES_TERMINAL'],[x=>x.snapshot.pending='1','ACTIVE_OR_QUEUED'],
  [x=>x.snapshot.token='stale-token','ACTIVE_OR_QUEUED'],[x=>x.snapshot.lease='1','ACTIVE_OR_QUEUED'],
  [x=>x.snapshot.recheck='{}','ALREADY_COMMITTED'],[x=>x.snapshot.correction=null,'HISTORY_MISMATCH'],
  [x=>x.snapshot.attempts='5','HISTORY_MISMATCH'],[x=>x.collector.runId='old','SOURCE_MISMATCH'],
  [x=>x.record.checkpointDb='C:/other.sqlite','SOURCE_MISMATCH'],[x=>x.record.importExitCode=3,'RUN_NOT_HEALTHY'],
  [x=>x.collector.status='partial_stopped','RUN_NOT_HEALTHY'],[x=>x.record.error='MYSQL_IMPORT_FAILED','RUN_NOT_HEALTHY'],
  [x=>{x.task.collectorConfig.asrEnabled=true;x.collector.asrJobs.pendingTotal=1;},'ASR_UNFINISHED'],
  [x=>x.collector.asrJobs.pendingTotal=1,'ASR_UNFINISHED'],
  [x=>x.collector.searchSummaries[0].reason='year_boundary','SEARCH_END_UNVERIFIED'],
  [x=>x.collector.searchSummaries[0].exhaustion.observations=[],'SEARCH_END_UNVERIFIED'],
  [x=>x.collector.searchSummaries[0].exhaustion.observations.at(-1).loading=true,'SEARCH_END_UNVERIFIED']
 ];
 for(const [change,reason] of cases){const changed=structuredClone(input);change(changed);assert.match(terminalEvidenceReason(changed),new RegExp(reason));}
 const old=structuredClone(input);old.record.runId=old.collector.runId='1-stale';assert.equal(terminalEvidenceReason(old),'TERMINAL_RECHECK_STALE_RUN');
});

async function fixture(){
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'terminal-recheck-fixture-'));
 const state=path.join(dir,'state'),output=path.join(dir,'output');await fs.mkdir(state);await fs.mkdir(output);
 const input=evidence(path.join(state,'checkpoint.sqlite'),output),posts=[];
 const cp=openCheckpoint(input.checkpointDb);
 try{for(let i=0;i<10;i++){
  const noteId=String(i),post={文章id:noteId,文章链接:`https://example.invalid/${i}`,文章标题:'fixture keyword',文章时间地点:'2026-10-01',项目:'fixture',平台:'fixture',内容类型:'图文'};
  posts.push(post);saveCandidates(cp,input.task.keyword,[{noteId,url:post.文章链接}]);markCompleted(cp,input.task.keyword,{noteId},{post,comments:[],audit:{commentsComplete:true}});
 }}finally{cp.close();}
 await fs.writeFile(path.join(output,'task_status.json'),JSON.stringify(input.record));await fs.writeFile(path.join(output,'collector_status.json'),JSON.stringify(input.collector));
 let rows=8;
 const connection={query:async sql=>sql.startsWith('SHOW')?[[]]:[],beginTransaction:async()=>{},commit:async()=>{},end:async()=>{},execute:async()=>[posts.slice(0,rows)]};
 return {...input,dir,connect:async()=>connection,setRows:n=>{rows=n;},cleanup:()=>fs.rm(dir,{recursive:true,force:true})};
}

test('preview requires fresh SQL readback, never commits or rescans, and retains the 80% boundary',async()=>{
 const f=await fixture();let writes=0;
 const queue={namespace:'xhs:{offline}',keys:Array.from({length:11},(_,i)=>String(i)),verifyExisting:async()=>{},client:{eval:async script=>{
  if(!script.endsWith('return cjson.encode(current)'))writes++;
  return JSON.stringify(f.snapshot);
 }}};
 try{
  let r=await recheckTerminalAcceptance({...f,queue});assert.equal(r.ok,true);assert.equal(r.committed,false);assert.equal(r.coverage.numerator,8);assert.equal(writes,0);
  f.setRows(7);r=await recheckTerminalAcceptance({...f,queue,commit:true});assert.equal(r.ok,false);assert.equal(r.committed,false);assert.equal(writes,0);
  const before=await fs.readFile(path.join(f.outputDir,'task_status.json'),'utf8');
  f.setRows(8);f.connect=async()=>{await fs.writeFile(path.join(f.outputDir,'task_status.json'),before+' ');return {query:async sql=>sql.startsWith('SHOW')?[[]]:[],beginTransaction:async()=>{},commit:async()=>{},end:async()=>{},execute:async()=>[[]]};};
  r=await recheckTerminalAcceptance({...f,queue,commit:true});assert.equal(r.reason,'TERMINAL_RECHECK_LOCAL_EVIDENCE_CHANGED');assert.equal(writes,0);
 }finally{await f.cleanup();}
});

test('LIVE isolated terminal recheck: no extra attempt, immutable history, CAS, and no other lease mutation',{
 skip:process.env.CORRECTION_REDIS_LIVE!=='1'},async()=>{
 assert.ok(process.env.CORRECTION_REDIS_COMMON);
 const client=await connectRedis(await redisSettings(process.env.CORRECTION_REDIS_COMMON));
 try{
  for(const scenario of ['success','concurrent','wrong-type','stale']){
   const f=await fixture(),queue=new RedisTaskQueue({client,campaign:'terminal-recheck-fixture-'+randomUUID()});
   const history=queue.namespace+':acceptance-recheck-history',corrections=queue.namespace+':correction-history',keys=[...queue.keys,history,corrections];
   try{
    await queue.publish([f.task,{redisTaskId:'other',keyword:'other'}]);
    const payload=await client.eval("return redis.call('HGET',KEYS[1],'target')",{keys:queue.keys,arguments:[]});
    const correction={...JSON.parse(f.snapshot.correction),originalPayload:payload};
    await client.eval(`redis.call('HSET',KEYS[2],'target','failed','other','leased');redis.call('HSET',KEYS[3],'target','4');
     redis.call('HSET',KEYS[8],'target','{"oldEvidence":true}');redis.call('HSET',KEYS[9],'target','old-error');
     redis.call('HSET',KEYS[11],'target','2');redis.call('ZREM',KEYS[6],'target','other');redis.call('ZADD',KEYS[10],1,'target');
     redis.call('HSET',KEYS[4],'other','other-token');redis.call('HSET',KEYS[5],'other','other-owner');redis.call('ZADD',KEYS[7],1,'other');
     redis.call('HSET',KEYS[13],ARGV[1],ARGV[2]);return 1`,{keys,arguments:['target|'+CORRECTION_POLICY,JSON.stringify(correction)]});
    if(scenario==='wrong-type')await client.eval("redis.call('ZADD',KEYS[1],1,'wrong-type');return 1",{keys:[history],arguments:[]});
    if(scenario==='stale'){
     const realClient=queue.client;queue.client={eval:async(script,options)=>{
      if(script.includes('local before=cjson.decode(ARGV[3])')){
       const changed=[...options.arguments],payload=JSON.parse(changed[3]);payload.acceptanceRecheck.checkedAtMs-=61000;changed[3]=JSON.stringify(payload);
       return realClient.eval(script,{...options,arguments:changed});
      }
      return realClient.eval(script,options);
     }};
     await assert.rejects(recheckTerminalAcceptance({...f,queue,commit:true}),/STALE_OR_MISSING_EVIDENCE/);
    }else if(scenario==='concurrent'){
     const connect=f.connect;f.connect=async()=>{await client.eval("redis.call('HSET',KEYS[1],'target','concurrent-error');return 1",{keys:[queue.keys[8]],arguments:[]});return connect();};
     await assert.rejects(recheckTerminalAcceptance({...f,queue,commit:true}),/CONCURRENT_CHANGE/);
    }else if(scenario==='wrong-type')await assert.rejects(recheckTerminalAcceptance({...f,queue,commit:true}),/WRONGTYPE/);
    else{
     const r=await recheckTerminalAcceptance({...f,queue,commit:true});assert.equal(r.committed,true);assert.equal(r.confirmation.status,'completed_with_skips');
     assert.equal(r.confirmation.attempts,4);
     const ledger=JSON.parse(await client.eval("return redis.call('HGET',KEYS[1],ARGV[1])",{keys:[history],arguments:['target|'+TERMINAL_RECHECK_POLICY]}));
     assert.equal(JSON.parse(ledger.originalState.result).oldEvidence,true);assert.equal(ledger.originalState.deferrals,'2');
     const second=await recheckTerminalAcceptance({...f,queue,commit:true});assert.equal(second.reason,'TERMINAL_RECHECK_ALREADY_COMMITTED');
    }
    const preserved=await queue.evaluate(`return cjson.encode({attempts=redis.call('HGET',KEYS[3],'target'),deferrals=redis.call('HGET',KEYS[11],'target'),otherToken=redis.call('HGET',KEYS[4],'other'),otherOwner=redis.call('HGET',KEYS[5],'other'),otherLease=redis.call('ZSCORE',KEYS[7],'other'),status=redis.call('HGET',KEYS[2],'target')})`);
    assert.equal(preserved.attempts,'4');assert.equal(preserved.deferrals,'2');assert.equal(preserved.otherToken,'other-token');assert.equal(preserved.otherOwner,'other-owner');assert.equal(preserved.otherLease,'1');
    if(scenario!=='success')assert.equal(preserved.status,'failed');
   }finally{
    const fields=['target','other','wrong-type','target|'+CORRECTION_POLICY,'target|'+TERMINAL_RECHECK_POLICY];
    const remaining=await client.eval(`local remaining=0;for _,key in ipairs(KEYS) do
     local removed=redis.pcall('HDEL',key,unpack(ARGV));if type(removed)=='table' and removed.err then redis.call('ZREM',key,unpack(ARGV)) end
     local count=redis.pcall('HLEN',key);if type(count)=='table' and count.err then count=redis.call('ZCARD',key) end
     remaining=remaining+count end;return remaining`,{keys,arguments:fields});
    assert.equal(remaining,0,'all isolated fixture keys cleaned');await f.cleanup();
   }
  }
 }finally{await client.close();}
});
