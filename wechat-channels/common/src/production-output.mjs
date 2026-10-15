// Local durable output ledger. Never expose subtitles, comments or credentials.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
const sourceRoot=path.dirname(fileURLToPath(import.meta.url));
const tables=new Set(['ods_social_media_post','ods_social_media_comment']);
const passive=new Set(['id','文章获取时间','评论获取时间','关键词','清洗标注','文章标注','分类','平台','项目']);
export const normalize=v=>v===null || v===undefined || v==='' ? null : v instanceof Date ? v.toISOString() : String(v);
export function changedFields(before,after) {
  return Object.keys(after).filter(k=>!passive.has(k) && normalize(before?.[k])!==normalize(after[k]));
}
export function meaningfulHint(before,candidate) {
  return !before || Object.keys(candidate).some(k=>!passive.has(k) && normalize(candidate[k])!==null && normalize(before[k])!==normalize(candidate[k]));
}
export function rowHash(row,fields) {
  return crypto.createHash('sha256').update(JSON.stringify(fields.map(k=>[k,normalize(row[k])]))).digest('hex');
}
function durableWrite(file,data) {
  fs.mkdirSync(path.dirname(file),{recursive:true});
  const temp=file+'.tmp-'+crypto.randomUUID();
  const fd=fs.openSync(temp,'wx');
  try {fs.writeFileSync(fd,JSON.stringify(data,null,2),'utf8');fs.fsyncSync(fd);} finally {fs.closeSync(fd);}
  fs.renameSync(temp,file);
}
export class ProductionOutputRecorder {
  constructor({root,identity,source='mysql_import'}={}) {
    const workerRoot=process.env.WECHAT_WORKER_ROOT;
    this.root=root || path.join(workerRoot || path.resolve(sourceRoot,'../..'),'.state','production-output');
    this.identity=identity || {computer:os.hostname(),worker:process.env.WECHAT_WORKER_ID || (workerRoot ? path.basename(workerRoot) : 'unassigned'),consumer:process.env.WECHAT_REDIS_CONSUMER || null,runId:process.env.REDIS_RUN_ID || process.env.WECHAT_REDIS_RUN_ID || null,generation:process.env.WECHAT_REDIS_GENERATION || null,taskId:process.env.WECHAT_REDIS_TASK_ID || null,topic:process.env.WECHAT_REDIS_TOPIC || null,keyword:process.env.WECHAT_REDIS_KEYWORD || null};
    this.source=source;this.rows=new Map();this.prepared=null;
  }
  track(table,before,after,{approved=false}={}) {
    if (!tables.has(table)) throw new Error('Unsupported telemetry table');
    const key=table+':'+String(after.id),prior=this.rows.get(key);
    this.rows.set(key,{table,before:prior ? prior.before : before,after,approved:approved || prior?.approved});
  }
  prepare() {
    const items=[],verification=[];
    for (const {table,before,after,approved} of this.rows.values()) {
      const changes=changedFields(before,after);
      if (before && !changes.length) continue;
      const comment=table==='ods_social_media_comment';
      if (!normalize(after['文章id']) && !normalize(after['文章链接'])) continue;
      if (comment && !normalize(after['评论内容'])) continue;
      const subtitle=!comment && changes.includes('文章视频内容') && normalize(after['文章视频内容'])!==null;
      const fields=Object.keys(after).filter(k=>!passive.has(k)).sort();
      verification.push({table,id:String(after.id),fields,hash:rowHash(after,fields)});
      items.push({table,dbId:String(after.id),articleId:after['文章id'] || null,commentId:comment ? after['评论id'] || null : null,project:after['项目'] || null,platform:after['平台'] || null,keyword:this.identity.keyword || after['关键词'] || null,operation:before ? 'update' : 'insert',changedFields:changes,types:comment ? ['comment'] : [...(!before || changes.some(k=>k!=='文章视频内容') ? ['metadata'] : []),...(subtitle ? ['subtitle'] : [])],subtitleAccepted:subtitle,subtitleApproval:subtitle ? approved ? 'manual_approval' : 'production_import_path_not_independent_quality_audit' : null});
    }
    if (!items.length) return null;
    const event={schemaVersion:1,event:'production_output_committed',eventId:crypto.randomUUID(),...this.identity,source:this.source,preparedAt:new Date().toISOString(),committedAt:null,verifiedAt:null,readbackVerified:false,items,verification};
    const file=path.join(this.root,'prepared',event.eventId+'.json');
    durableWrite(file,event);this.prepared={file,event};return event;
  }
  markCommitted() {
    if (!this.prepared) return;
    this.prepared.event.committedAt=new Date().toISOString();
    durableWrite(this.prepared.file,this.prepared.event);
  }
  async verify(conn) {
    if (!this.prepared) return;
    const rows={};
    for (const table of tables) {
      const targets=this.prepared.event.verification.filter(v=>v.table===table);
      for (let i=0;i<targets.length;i+=100) {
        const chunk=targets.slice(i,i+100);
        const [found]=await conn.execute(`SELECT * FROM \`${table}\` WHERE id IN (${chunk.map(()=>'?').join(',')})`,chunk.map(v=>v.id));
        for (const row of found) rows[table+':'+String(row.id)]=row;
      }
    }
    return this.confirmRows(rows);
  }
  confirmRows(rows) {
    if (!this.prepared) return;
    const {event}=this.prepared;
    if (!event.committedAt) throw new Error('Commit receipt required before output verification');
    for (const v of event.verification) {
      const row=rows[v.table+':'+v.id];
      if (!row || rowHash(row,v.fields)!==v.hash) throw new Error('Output readback mismatch');
    }
    event.readbackVerified=true;event.verifiedAt=new Date().toISOString();
    const ready=path.join(this.root,'pending',event.eventId+'.json');
    durableWrite(ready,event);
    // Keep prepared audit evidence. Only pending records are eligible for Redis.
    durableWrite(this.prepared.file,event);
    const verifiedDirectory=path.join(this.root,'verified');
    fs.mkdirSync(verifiedDirectory,{recursive:true});
    fs.renameSync(this.prepared.file,path.join(verifiedDirectory,event.eventId+'.json'));
    return event;
  }
  abort() {
    if (!this.prepared || this.prepared.event.committedAt) return;
    this.prepared.event.outcome=this.commitAttempted ? 'commit_outcome_unknown_do_not_publish' : 'rolled_back';durableWrite(this.prepared.file,this.prepared.event);
  }
  flush() {
    const python=process.env.WECHAT_PYTHON || path.join(sourceRoot,'../runtime/python/python.exe');
    const result=spawnSync(python,[path.join(sourceRoot,'production_output_publisher.py'),'--outbox',this.root],{encoding:'utf8',windowsHide:true,timeout:20000});
    if (result.stdout) process.stdout.write(result.stdout);
    if (result.error || result.status!==0) console.log(JSON.stringify({event:'production_output_upload_deferred',reason:result.error?.code || 'publisher_failed',localOutboxPreserved:true}));
  }
}
export async function finishOutput(recorder,conn) {
  try {recorder.markCommitted();await recorder.verify(conn);recorder.flush();return {state:recorder.prepared ? 'verified_local' : 'no_effective_change',eventId:recorder.prepared?.event.eventId || null};}
  catch(e) {console.log(JSON.stringify({event:'production_output_verification_deferred',errorType:e.code || e.name,localOutboxPreserved:true,databaseCommitUnaffected:true}));return {state:'verification_pending',eventId:recorder.prepared?.event.eventId || null};}
}

export async function recoverCommittedOutputs(conn,root) {
  const directory=path.join(root,'prepared');
  if (!fs.existsSync(directory)) return 0;
  let recovered=0;
  let eligible=0;
  for (const name of fs.readdirSync(directory).filter(n=>n.endsWith('.json'))) {
    try {
      const event=JSON.parse(fs.readFileSync(path.join(directory,name),'utf8'));
      if (!event.committedAt || event.readbackVerified || event.outcome) continue;
      if (++eligible>100) break;
      const recorder=new ProductionOutputRecorder({root,identity:event});
      recorder.prepared={file:path.join(directory,name),event};
      await recorder.verify(conn);recovered++;
    } catch { /* Mismatch/outcome unknown stays in prepared, never fabricate a success. */ }
  }
  return recovered;
}
