import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import {pathToFileURL,fileURLToPath} from 'node:url';
import pathModule from 'node:path';
const ROOT='D:/Codex/outputs/01a1349d-c76e-7b63-be36-3c8e0766deef/20261013_北京臻澐口碑数据库广告打标';
const OUT=ROOT+'/restore_20261014_247';
const COMMON=process.env.SPIDER_COMMON_ROOT||pathModule.resolve(pathModule.dirname(fileURLToPath(import.meta.url)),'../../../xiaohongshu/common');
const PROJECT='北京臻澐项目口碑';
const FIELDS=['平台','作者名字','文章标题','文章内容','文章标签','文章图片信息','文章视频内容'];
const hash=x=>crypto.createHash('sha256').update(JSON.stringify(x)).digest('hex');
const input=r=>Object.fromEntries(FIELDS.map(f=>[f,r[f]??'']));
const blank=v=>v==null||String(v).trim()==='';
const identity=(r,c)=>String(r.id)===c.id&&String(r['文章id']??'')===c.article_id&&r['项目']===c.project&&r['平台']===c.platform;
const guard=(r,c)=>identity(r,c)&&blank(r['是否广告'])&&hash(input(r))===c.commit.input_hash;
const write=async(name,data)=>{await fs.writeFile(OUT+'/'+name+'.tmp',JSON.stringify(data,null,2));await fs.rename(OUT+'/'+name+'.tmp',OUT+'/'+name);};
const candidates=JSON.parse(await fs.readFile(OUT+'/candidates.json','utf8'));
if(candidates.length!==247||new Set(candidates.map(c=>c.id)).size!==247)throw Error('Invalid candidate count/uniqueness');
const snapshot=JSON.parse(await fs.readFile(ROOT+'/before_snapshot_2026-10-13T10-51-37.876Z.json','utf8')).rows;
const snapshots=new Map(snapshot.map(r=>[String(r.id),r]));
const ledger=new Map((await fs.readFile(ROOT+'/committed_updates.jsonl','utf8')).trim().split('\n').map(s=>{const c=JSON.parse(s);return [c.id,c];}));
for(const c of candidates){
 const s=snapshots.get(c.id),l=ledger.get(c.id);
 if(!s||!identity(s,c)||!l||JSON.stringify(l)!==JSON.stringify(c.commit)||c.project!==PROJECT||c.platform!=='小红书'||!['是','否'].includes(l.after)||hash(input(s))!==l.input_hash||hash(c.input)!==l.input_hash||!blank(l.before))throw Error('Manifest identity/hash/ledger check failed');
 if(!/^[a-f0-9]{64}$/.test(l.signature))throw Error('Invalid cache signature');
 const cache=JSON.parse(await fs.readFile(ROOT+'/calls/'+l.signature+'.json','utf8'));
 if(cache.signature!==l.signature||cache.input_hash!==l.input_hash||cache.result?.is_ad!==l.after)throw Error('Cached result mismatch');
}
if(process.argv.includes('--self-test')){
 const c=candidates[0],r={...snapshots.get(c.id),'是否广告':null};
 if(!guard(r,c)||guard({...r,id:'999'},c)||guard({...r,'文章id':'wrong'},c)||guard({...r,'平台':'wrong'},c)||guard({...r,'项目':'wrong'},c)||guard({...r,'文章内容':String(r['文章内容']??'')+'changed'},c)||guard({...r,'是否广告':'否'},c))throw Error('Safety guard self-test failed');
 console.log('PASS: all 247 cache/ledger/snapshot/input matches; wrong ID/article/platform/project/content and nonblank label rejected. No DB or API accessed.');process.exit(0);
}
if(!process.argv.includes('--run'))throw Error('Explicit --run required');
const {default:mysql}=await import(pathToFileURL(COMMON+'/node_modules/mysql2/promise.js').href);
const {mysqlConnectionOptions}=await import(pathToFileURL(COMMON+'/src/import-mysql.mjs').href);
let db,transaction=false,job=false,shared=false,committed=false;
const state={started_at:new Date().toISOString(),pid:process.pid,candidate_count:247,updated:0,skipped:[],api_calls:0};
try{
 const opts=mysqlConnectionOptions();if(opts.database!=='social')throw Error('Wrong database');
 db=await mysql.createConnection(opts);await db.query('SET SESSION innodb_lock_wait_timeout=15');
 const [indexes]=await db.query('SHOW INDEX FROM `ods_social_media_post`');
 if(indexes.filter(i=>i.Key_name==='PRIMARY').length!==1||!indexes.some(i=>i.Key_name==='PRIMARY'&&i.Column_name==='id'))throw Error('Primary key guard failed');
 const [j]=await db.query("SELECT GET_LOCK('codex_ads_beijing_zhenyun',0) acquired");if(Number(j[0].acquired)!==1)throw Error('Another ad label job running');job=true;
 await write('progress.json',{...state,status:'waiting_for_crawler_lock'});
 for(let n=0;n<8&&!shared;n++){
  const [l]=await db.query("SELECT GET_LOCK('social_xhs_distributed_import',15) acquired");shared=Number(l[0].acquired)===1;
 }
 if(!shared)throw Error('Crawler lock unavailable; no writes');
 await db.beginTransaction();transaction=true;
 const [before]=await db.execute('SELECT * FROM `ods_social_media_post` WHERE BINARY `项目`=BINARY ? ORDER BY `id` FOR UPDATE',[PROJECT]);
 const byId=new Map(before.map(r=>[String(r.id),r]));const eligible=[];
 for(const c of candidates){const r=byId.get(c.id);if(r&&guard(r,c))eligible.push(c);else state.skipped.push({id:c.id,reason:!r?'not_in_project_or_deleted':!identity(r,c)?'identity_changed':!blank(r['是否广告'])?'already_nonempty':'input_changed'});}
 await write('before_snapshot.json',{project:PROJECT,rows:before,eligible_ids:eligible.map(c=>c.id),skipped:state.skipped});
 await write('update_intents.json',{project:PROJECT,rows:eligible.map(c=>({id:c.id,article_id:c.article_id,platform:c.platform,before:byId.get(c.id)['是否广告'],after:c.commit.after,input_hash:c.commit.input_hash,signature:c.commit.signature}))});
 for(const c of eligible){
  const [u]=await db.execute("UPDATE `ods_social_media_post` SET `是否广告`=? WHERE `id`=? AND BINARY `文章id`=BINARY ? AND BINARY `项目`=BINARY ? AND BINARY `平台`=BINARY ? AND (`是否广告` IS NULL OR TRIM(`是否广告`)='')",[c.commit.after,c.id,c.article_id,PROJECT,c.platform]);
  if(u.affectedRows!==1)throw Error('Conditional update failed');state.updated++;
 }
 const [after]=await db.execute('SELECT * FROM `ods_social_media_post` WHERE BINARY `项目`=BINARY ? ORDER BY `id`',[PROJECT]);
 const expected=new Map(eligible.map(c=>[c.id,c.commit.after]));
 if(after.length!==before.length)throw Error('Row count changed');
 for(let i=0;i<before.length;i++){
  const target={...before[i]};if(expected.has(String(target.id)))target['是否广告']=expected.get(String(target.id));
  if(hash(target)!==hash(after[i]))throw Error('Unexpected field/object change; rollback');
 }
 await db.commit();transaction=false;committed=true;
 await write('committed_updates.json',{committed_at:new Date().toISOString(),rows:eligible.map(c=>({id:c.id,article_id:c.article_id,after:c.commit.after,input_hash:c.commit.input_hash,signature:c.commit.signature}))});
 const [readback]=await db.execute('SELECT * FROM `ods_social_media_post` WHERE BINARY `项目`=BINARY ? ORDER BY `id`',[PROJECT]);
 state.readback_exact=hash(readback)===hash(after);
 state.ads_restored=eligible.filter(c=>c.commit.after==='是').length;state.non_ads_restored=eligible.filter(c=>c.commit.after==='否').length;
 state.remaining_empty_in_project=readback.filter(r=>blank(r['是否广告'])).length;
 state.completed=state.readback_exact;state.finished_at=new Date().toISOString();state.other_fields_unchanged=true;state.preexisting_labels_unchanged=true;
 await write('final_status.json',state);console.log(JSON.stringify(state,null,2));
 if(!state.completed)process.exitCode=1;
}catch(e){
 if(transaction)await db.rollback().catch(()=>{});
 await write('error_status.json',{...state,committed,error:e.code||e.message,updated:committed?state.updated:0}).catch(()=>{});
 console.error('Stopped safely:',e.code||e.message,'committed:',committed);process.exitCode=1;
}finally{
 if(db){if(shared)await db.query("SELECT RELEASE_LOCK('social_xhs_distributed_import')").catch(()=>{});if(job)await db.query("SELECT RELEASE_LOCK('codex_ads_beijing_zhenyun')").catch(()=>{});await db.end().catch(()=>{});}
}
