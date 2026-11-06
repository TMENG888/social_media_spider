import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import http from 'node:http';
import {spawnSync} from 'node:child_process';
import {AsrService,transientDownloadError} from './asr.mjs';
import {AsrJobProcessor} from './asr-jobs.mjs';
import {openCheckpoint,saveCandidates,markCompleted,claimAsrJob} from './checkpoint.mjs';

async function fixture(){
 const folder=await fs.mkdtemp(path.join(os.tmpdir(),'dy-download-retry-'));
 const db=openCheckpoint(path.join(folder,'checkpoint.sqlite'));
 const keyword='isolated-download-test',noteId='fixture-video';
 saveCandidates(db,keyword,[{noteId,url:'https://example.invalid/video'}],0);
 markCompleted(db,keyword,{noteId},{post:{文章id:noteId},comments:[],audit:{},postTextAudit:{}},
  {asrJob:{keyword,noteId,articleId:noteId,mediaUrl:'https://example.invalid/media'}});
 db.prepare("UPDATE asr_job SET status='pending'").run();
 return {db,folder,async close(){db.close();await fs.rm(folder,{recursive:true,force:true});},
  processor(service,extra={}){return new AsrJobProcessor({db,service,mediaDir:path.join(folder,'media'),retryDelayMs:0,downloadAttempts:4,downloadBaseDelayMs:1,downloadMaxDelayMs:20,...extra});},
  row(){return db.prepare('SELECT status,attempts,last_error FROM asr_job').get();}};
}
const transient=()=>Object.assign(new Error('MEDIA_DOWNLOAD_HTTP'),{httpStatus:429,transientDownload:true,retryAfterMs:0});

test('real HTTP 429, 504 and truncated response recover before the first recognition attempt',async()=>{
 const f=await fixture();let requests=0,transcriptions=0;
 const server=http.createServer((req,res)=>{
  requests++;
  if(requests===1){res.writeHead(429,{'Retry-After':'0'});return res.end();}
  if(requests===2){res.writeHead(504);return res.end();}
  if(requests===3){res.writeHead(200,{'Content-Length':'10000'});res.write('partial');return setTimeout(()=>res.destroy(),5);}
  res.end('fixture-media');
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 try{
  const service=new AsrService({downloadTimeoutMs:1000,tempDir:path.join(f.folder,'temp')});
  service.transcribePath=async()=>{transcriptions++;return {text:'故障恢复后的模拟字幕',audit:{status:'extracted'}};};
  f.db.prepare('UPDATE asr_job SET media_url=?').run('http://127.0.0.1:'+server.address().port+'/media');
  const stats=await f.processor(service).drain();
  assert.equal(requests,4);assert.equal(transcriptions,1);
  assert.equal(f.row().status,'completed');assert.equal(f.row().attempts,1);assert.equal(stats.pendingTotal,0);
 }finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));await f.close();}
});

test('persistent transient failures stop this queue, retain work and refund recognition count; next cycle recovers',async()=>{
 const f=await fixture();let requests=0;
 try{
  const first=f.processor({download:async()=>{requests++;throw transient();},transcribePath:async()=>assert.fail('must not transcribe')});
  const stats=await first.drain();
  assert.equal(requests,4);assert.equal(f.row().status,'retry_pending');assert.equal(f.row().attempts,0);
  assert.equal(stats.downloadDeferred,true);assert.equal(stats.pendingTotal,1);
  assert.equal((await fs.readdir(path.join(f.folder,'media'))).length,0);
  const second=f.processor({download:async(url,file)=>fs.writeFile(file,'media'),transcribePath:async()=>({text:'恢复成功',audit:{status:'extracted'}})});
  await second.drain();assert.equal(f.row().status,'completed');assert.equal(f.row().attempts,1);
 }finally{await f.close();}
});

test('expired 403 source keeps its existing source-refresh protection, no transport retry',async()=>{
 const f=await fixture();let requests=0;
 try{
  const p=f.processor({download:async()=>{requests++;throw new Error('视频下载失败 HTTP 403');}});
  await p.process(claimAsrJob(f.db));
  assert.equal(requests,1);assert.equal(f.row().status,'waiting_source_refresh');assert.equal(claimAsrJob(f.db),null);
 }finally{await f.close();}
});

test('real recognition failures still exhaust the original three-attempt cap',async()=>{
 const f=await fixture();let downloads=0,recognitions=0;
 try{
  await f.processor({download:async(url,file)=>{downloads++;await fs.writeFile(file,'media');},
   transcribePath:async()=>{recognitions++;throw new Error('ASR_QUALITY_REJECTED');}}).drain();
  assert.equal(downloads,1);assert.equal(recognitions,3);assert.equal(f.row().status,'dead_letter');assert.equal(f.row().attempts,3);
 }finally{await f.close();}
});

test('a stop during download backoff preserves pending work and does not continue requests',async()=>{
 const f=await fixture();let requests=0;
 try{
  const p=f.processor({download:async()=>{requests++;throw transient();}},{shouldStop:async()=>requests>0});
  await p.drain();
  assert.equal(requests,1);assert.equal(f.row().status,'retry_pending');assert.equal(f.row().attempts,0);
  assert.equal(p.haltedReason,'MEDIA_DOWNLOAD_STOPPED');
 }finally{await f.close();}
});

test('long Retry-After is deferred to a later cycle, not shortened into another request',async()=>{
 const f=await fixture();let requests=0;
 try{
  const p=f.processor({download:async()=>{requests++;throw Object.assign(transient(),{retryAfterMs:3600000});}});
  await p.drain();assert.equal(requests,1);assert.equal(f.row().attempts,0);assert.equal(f.row().status,'retry_pending');
 }finally{await f.close();}
});

test('disk and source/permission failures are not treated as transient transport problems',()=>{
 for(const code of ['ENOSPC','EACCES','ENOENT'])assert.equal(transientDownloadError(Object.assign(new Error('fixture'),{code})),false);
 for(const status of [400,401,403,404,410])assert.equal(transientDownloadError(Object.assign(new Error('HTTP '+status),{httpStatus:status})),false);
 assert.equal(transientDownloadError(new Error('terminated')),true);
});

test('background loop rejection is observed immediately but still reported by drain',async()=>{
 const f=await fixture();
 try{
  const p=f.processor({}, {shouldStop:async()=>{throw new Error('injected control failure');}});
  p.start(); // callers such as enqueue do not await this promise
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(p.haltedReason,'ASR_BACKGROUND_FAILED');
  await assert.rejects(()=>p.drain(),/injected control failure/);
  assert.equal(f.row().status,'pending');
 }finally{await f.close();}
});

test('fatal process diagnostics preserve the real nonzero exit without leaking the error message',async()=>{
 const folder=await fs.mkdtemp(path.join(os.tmpdir(),'dy-download-retry-'));
 try{
  const script="import {installWorkerDiagnostics} from "+JSON.stringify(new URL('./worker-diagnostics.mjs',import.meta.url).href)+";installWorkerDiagnostics("+JSON.stringify(folder)+");Promise.reject(Object.assign(new Error('password=fixture-secret'),{code:'INJECTED_FAILURE'}));";
  const child=spawnSync(process.execPath,['--input-type=module','-e',script],{encoding:'utf8',windowsHide:true,timeout:10000});
  assert.equal(child.status,1);
  const file=(await fs.readdir(path.join(folder,'runs'))).find(name=>name.endsWith('.jsonl'));
  const text=await fs.readFile(path.join(folder,'runs',file),'utf8');
  const events=text.trim().split('\n').map(line=>JSON.parse(line));
  assert.ok(events.some(e=>e.reason==='uncaught_exception'&&e.code==='INJECTED_FAILURE'));
  assert.equal(events.at(-1).exitCode,1);assert.equal(text.includes('fixture-secret'),false);
 }finally{await fs.rm(folder,{recursive:true,force:true});}
});
