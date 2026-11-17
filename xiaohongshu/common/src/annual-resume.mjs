import {DatabaseSync} from 'node:sqlite';
import fs from 'node:fs/promises';
import path from 'node:path';
import {gzipSync,gunzipSync} from 'node:zlib';
import {beijingDateTime,parsePublishedText} from './xhs-utils.mjs';
import {setMeta} from './checkpoint.mjs';
import {recordLocalPosts,savedPostIdentity} from './local-post-p80.mjs';

export const ANNUAL_RESUME_VERSION='xhs-date-checkpoint-20261107-v1';
export function dateOnly(value){
 const d=String(value||'').slice(0,10);
 const ms=Date.parse(d+'T00:00:00Z');
 return /^\d{4}-\d{2}-\d{2}$/.test(d)&&Number.isFinite(ms)&&new Date(ms).toISOString().slice(0,10)===d?d:null;
}
const dayAdd=(d,n)=>new Date(Date.parse(d+'T00:00:00Z')+n*86400000).toISOString().slice(0,10);
export function resumeWindow(publishedAt,{today=beijingDateTime().slice(0,10),year=Number(today.slice(0,4))}={}){
 if(!dateOnly(today)||Number(today.slice(0,4))!==year)throw new Error('ANNUAL_TARGET_YEAR_NOT_CURRENT');
 const cutoff=`${year}-01-01`,center=dateOnly(publishedAt);
 if(!center||center<cutoff||center>today)return {policy:ANNUAL_RESUME_VERSION,year,cutoff,center:null,start:today,windowStart:today,windowEnd:today,initial:true};
 const start=[dayAdd(center,5),today].sort()[0];
 return {policy:ANNUAL_RESUME_VERSION,year,cutoff,center,start,windowStart:[dayAdd(center,-5),cutoff].sort().at(-1),windowEnd:start,initial:false};
}
export function cardDate(text,now=new Date()){return dateOnly(parsePublishedText(text,now));}
export function beforeResumeStart(value,window){const d=dateOnly(value);return Boolean(d&&d>window.start&&d.slice(0,4)===String(window.year));}

const tables=['candidate','scope_audit','scope_evidence_history','note_dead_letter','asr_job','media_correction_history'];
function rowsFor(db,table,keyword,noteId){
 try{return db.prepare(`SELECT * FROM ${table} WHERE keyword=? AND note_id=?`).all(keyword,noteId);}catch(e){if(/no such table/.test(e.message))return [];throw e;}
}
export function packNote(db,keyword,noteId,{source='',stamp=null}={}){
 const data=Object.fromEntries(tables.map(t=>[t,rowsFor(db,t,keyword,noteId)]));
 const candidate=data.candidate[0];if(!candidate)return null;
 return {policy:ANNUAL_RESUME_VERSION,source,stamp:stamp||candidate.updated_at,retained:candidate.status==='completed',data};
}
export function restoreNote(db,bundle,{source=''}={}){
 if(bundle?.policy!==ANNUAL_RESUME_VERSION||!bundle.data?.candidate?.length)throw new Error('ANNUAL_CHECKPOINT_INVALID');
 const incoming=bundle.data.candidate[0];
 const local=db.prepare('SELECT status,updated_at FROM candidate WHERE keyword=? AND note_id=?').get(incoming.keyword,incoming.note_id);
 if(local?.status==='completed'&&incoming.status!=='completed')return false;
 if(local&&local.updated_at>incoming.updated_at)return false;
 db.exec('BEGIN IMMEDIATE');
 try{
  for(const table of tables){
   const cols=db.prepare(`PRAGMA table_info(${table})`).all().map(c=>c.name);if(!cols.length)continue;
   for(const item of bundle.data[table]||[]){
    const row={...item};
    if(table==='asr_job'&&bundle.source!==source){row.media_path=null;if(['running','downloading','waiting_import'].includes(row.status))row.status='retry_pending';}
    const keys=cols.filter(k=>Object.hasOwn(row,k));
    db.prepare(`INSERT OR REPLACE INTO ${table} (${keys.join(',')}) VALUES (${keys.map(()=>'?').join(',')})`).run(...keys.map(k=>row[k]));
   }
  }
  db.exec('COMMIT');return true;
 }catch(e){db.exec('ROLLBACK');throw e;}
}
const FENCE=`local t=redis.call('TIME');local now=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
local status=redis.call('HGET',KEYS[1],ARGV[1]);local expiry=tonumber(redis.call('ZSCORE',KEYS[3],ARGV[1])) or 0
if ARGV[2]~='' then
 if status~='leased' or redis.call('HGET',KEYS[2],ARGV[1])~=ARGV[2] or expiry<=now then return redis.error_reply('LEASE_LOST') end
elseif status=='leased' and expiry>now then return redis.error_reply('ANNUAL_SEED_TASK_BUSY') end
`;
export class AnnualCheckpointStore{
 constructor({client,namespace,taskId,token='',source=''}){
  Object.assign(this,{client,namespace,taskId,token,source});
  this.keys=[namespace+':statuses',namespace+':tokens',namespace+':leases',namespace+':annual-notes:'+taskId,namespace+':annual-cursor'];
 }
 async read(){
  const raw=await this.client.eval(`local a=redis.call('HVALS',KEYS[1]);return cjson.encode({notes=a,cursor=redis.call('HGET',KEYS[2],ARGV[1]) or false})`,{keys:[this.keys[3],this.keys[4]],arguments:[this.taskId]});
  const data=JSON.parse(raw),values=Array.isArray(data.notes)?data.notes:[];
  const notes=values.map(value=>JSON.parse(gunzipSync(Buffer.from(JSON.parse(value).payload,'base64'),{maxOutputLength:32*1024*1024}).toString('utf8')));
  return {notes,cursor:data.cursor?JSON.parse(data.cursor):null};
 }
 async put(bundle,{cursor=null}={}){
  const row=bundle?.data?.candidate?.[0];if(!row||row.keyword==null)throw new Error('ANNUAL_NOTE_MISSING');
  const payload=gzipSync(JSON.stringify(bundle)).toString('base64');
  if(Buffer.byteLength(payload)>8*1024*1024)throw new Error('ANNUAL_CHECKPOINT_TOO_LARGE');
  const raw=await this.client.eval(FENCE+`
local field=ARGV[3];local prior=redis.call('HGET',KEYS[4],field)
local p=prior and cjson.decode(prior) or nil;local meta=cjson.decode(ARGV[5])
if p and ((p.retained and not meta.retained) or p.stamp>meta.stamp) then return 'false' end
meta.payload=ARGV[4];redis.call('HSET',KEYS[4],field,cjson.encode(meta))
if ARGV[6]~='' then
 local c=redis.call('HGET',KEYS[5],ARGV[1]);local old=c and cjson.decode(c) or nil;local proposed=cjson.decode(ARGV[6])
 if not old or old.savedAt<=proposed.savedAt then redis.call('HSET',KEYS[5],ARGV[1],ARGV[6]) end
end
return 'true'`,{keys:this.keys,arguments:[this.taskId,this.token,row.note_id,payload,JSON.stringify({stamp:bundle.stamp,retained:bundle.retained}),cursor?JSON.stringify(cursor):'']});
  if(raw==='true'&&row.status!=='out_of_scope'){
   let result;try{result=JSON.parse(row.result_json||'null');}catch{}
   const id=savedPostIdentity(result?.post,row.keyword);
   if(id)await recordLocalPosts(this.client,this.namespace,row.keyword,[id]);
  }
  return raw==='true';
 }
 async hydrate(db,keyword){
  const data=await this.read();let restored=0;
  for(const note of data.notes){if(note.data.candidate[0].keyword!==keyword)throw new Error('ANNUAL_KEYWORD_MISMATCH');restored+=Number(restoreNote(db,note,{source:this.source}));}
  if(data.cursor)setMeta(db,`annual-cursor:${keyword}`,data.cursor);
  return {...data,restored};
 }
 async publish(db,keyword,noteId,{advance=false}={}){
  const bundle=packNote(db,keyword,noteId,{source:this.source});if(!bundle)return;
  const row=bundle.data.candidate[0];let result;try{result=JSON.parse(row.result_json||'null');}catch{}
  const publishedAt=dateOnly(result?.post?.文章时间地点||result?.publishedAt);
  const cursor=advance&&row.status==='completed'&&publishedAt?{policy:ANNUAL_RESUME_VERSION,keyword,publishedAt,noteId,savedAt:row.updated_at,year:Number(publishedAt.slice(0,4)),source:this.source}:null;
  if(cursor)setMeta(db,`annual-cursor:${keyword}`,cursor);
  await this.put(bundle,{cursor});return cursor;
 }
}

// Import old ordinary/recollection checkpoints additively. Historical files and
// ledgers stay in place; only this task's rows are restored into its canonical DB.
export async function localCheckpointFiles(base,depth=3){
 const found=[];async function visit(dir,left){
  let entries;try{entries=await fs.readdir(dir,{withFileTypes:true});}catch(e){if(e.code==='ENOENT')return;throw e;}
  for(const item of entries){const p=path.join(dir,item.name);if(item.isFile()&&item.name==='checkpoint.sqlite')found.push(p);else if(item.isDirectory()&&left>0&&!['asr-media','media-corrections'].includes(item.name))await visit(p,left-1);}
 }await visit(base,depth);return found;
}
export async function seedLegacyTask({base,keyword,store}){
 let count=0;for(const file of await localCheckpointFiles(base)){
  const db=new DatabaseSync(file,{readOnly:true});
  try{
   const rows=db.prepare('SELECT note_id FROM candidate WHERE keyword=? ORDER BY updated_at,candidate_index,note_id').all(keyword);
   for(const row of rows){
    const bundle=packNote(db,keyword,row.note_id,{source:store.source});
    const c=bundle.data.candidate[0];let r;try{r=JSON.parse(c.result_json||'null');}catch{}
    const d=dateOnly(r?.post?.文章时间地点||r?.publishedAt);
    const cursor=c.status==='completed'&&d?{policy:ANNUAL_RESUME_VERSION,keyword,publishedAt:d,noteId:row.note_id,savedAt:r?.post?.文章获取时间||c.updated_at,source:store.source,year:Number(d.slice(0,4)),legacy:true}:null;
    await store.put(bundle,{cursor});count++;
   }
  }finally{db.close();}
 }return count;
}
