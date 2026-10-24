import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {POST_FIELDS,COMMENT_FIELDS,blankRecord} from './schema.mjs';
import {cleanText,normalizeTags} from './text-cleaner.mjs';

export const hash = v => createHash('sha256').update(typeof v==='string'?v:JSON.stringify(v)).digest('hex');
export async function readJson(file){return JSON.parse((await fs.readFile(file,'utf8')).replace(/^\uFEFF/,''));}
export async function atomic(file,value){await fs.mkdir(path.dirname(file),{recursive:true});const temp=file+'.tmp';await fs.writeFile(temp,JSON.stringify(value,null,2),'utf8');await fs.rename(temp,file);}
export function canonical(value){
  let u;try{u=new URL(value,'https://www.zhihu.com');}catch{return null;}
  if(u.protocol!=='https:')return null;
  let m;if(u.hostname==='www.zhihu.com'&&(m=u.pathname.match(/^\/question\/(\d+)\/answer\/(\d+)\/?$/)))return {id:'answer-'+m[2],kind:'answer',url:`https://www.zhihu.com/question/${m[1]}/answer/${m[2]}`,numericId:m[2]};
  if(u.hostname==='zhuanlan.zhihu.com'&&(m=u.pathname.match(/^\/p\/(\d+)\/?$/)))return {id:'article-'+m[1],kind:'article',url:`https://zhuanlan.zhihu.com/p/${m[1]}`,numericId:m[1]};
  return null;
}
export function dateValue(value){
  if(value==null||value==='')return null;
  if(typeof value==='number'||/^\d{10,13}$/.test(String(value))){const n=Number(value);const d=new Date(n<1e12?n*1000:n);return Number.isFinite(d.getTime())?new Date(d.getTime()+28800000).toISOString().slice(0,10):null;}
  const s=String(value);if(/^\d{4}-\d\d-\d\dT.*(?:Z|[+-]\d\d:\d\d)$/.test(s)){const d=new Date(s);return Number.isFinite(d.getTime())?new Date(d.getTime()+28800000).toISOString().slice(0,10):null;}const m=s.match(/(20\d\d)[年\-/](\d{1,2})[月\-/](\d{1,2})/);if(!m)return null;
  const iso=`${m[1]}-${m[2].padStart(2,'0')}-${m[3].padStart(2,'0')}`;const parsed=new Date(iso);return Number.isFinite(parsed.getTime())&&parsed.toISOString().slice(0,10)===iso?iso:null;
}
export const beijingNow=()=>new Date(Date.now()+28800000).toISOString().replace('T',' ').slice(0,19);
export function count(value){if(value==null)return null;if(typeof value==='number')return value;const s=String(value).replace(/,/g,'');const m=s.match(/([\d.]+)\s*(万|亿|[kKwW])?/);return m?Math.round(Number(m[1])*({万:1e4,亿:1e8,k:1e3,K:1e3,w:1e4,W:1e4}[m[2]]||1)):null;}
export function postRow(raw,task){
  const c=canonical(raw.url);if(!c)throw new Error('INVALID_DETAIL_URL');
  const title=cleanText(raw.title||'',{removeEmoji:true});const body=cleanText(raw.content||'',{removeEmoji:true});
  const row=blankRecord(POST_FIELDS);Object.assign(row,{'文章id':c.id,'文章链接':c.url,'文章标题':title.text||null,'文章内容':body.text||null,'文章标签':normalizeTags(raw.tags||[]),'作者名字':raw.authorName||null,'作者id':raw.authorId||null,'作者主页链接':raw.authorUrl||null,'文章图片链接':raw.images?.length?raw.images.join(','):null,'文章点赞数':count(raw.voteCount),'文章收藏数':count(raw.favoriteCount),'文章评论数':count(raw.commentCount),'文章时间地点':raw.publishedDate,'关键词':task.keyword,'平台':'知乎','项目':task.projectName,'分类':null,'文章获取时间':beijingNow(),'内容类型':c.kind==='answer'?'回答':'文章','清洗标注':JSON.stringify({标题:title.stats,正文:body.stats})});return row;
}
export function commentRow(raw,post,task){if(!raw.id)throw new Error('COMMENT_ID_MISSING');const cleaned=cleanText(raw.content||'',{removeEmoji:true});const row=blankRecord(COMMENT_FIELDS);Object.assign(row,{'评论id':String(raw.id),'评论内容':cleaned.text,'评论用户id':raw.authorId||null,'评论用户名字':raw.authorName||null,'评论用户链接':raw.authorUrl||null,'评论时间':raw.date||null,'评论点赞数':count(raw.voteCount),'评论回复数':count(raw.replyCount),'文章id':post['文章id'],'文章链接':post['文章链接'],'关键词':task.keyword,'项目':task.projectName,'平台':'知乎','分类':null,'评论获取时间':beijingNow(),'清洗标注':JSON.stringify(cleaned.stats)});return row;}
export async function loadManifest(file){const m=await readJson(file);if(m.schemaVersion!=='zhihu-tasks-v1'||hash(m.tasks)!==m.manifestHash||m.taskCount!==m.tasks.length)throw new Error('MANIFEST_HASH_MISMATCH');if(new Set(m.tasks.map(t=>t.id)).size!==m.taskCount)throw new Error('DUPLICATE_TASK');for(const t of m.tasks)if(!t.keyword||!['专题一','专题二'].includes(t.topic)||t.collectComments!==(t.topic==='专题二'))throw new Error('INVALID_TASK');return m;}
export class Checkpoint{
  constructor(file){this.db=new DatabaseSync(file);this.db.exec('PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS records(kind TEXT,id TEXT,payload TEXT,raw TEXT,imported INTEGER DEFAULT 0,PRIMARY KEY(kind,id)); CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY,payload TEXT); CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);');}
  save(kind,id,row,raw){this.db.prepare('INSERT INTO records(kind,id,payload,raw,imported) VALUES(?,?,?,?,0) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload,raw=excluded.raw,imported=0').run(kind,id,JSON.stringify(row),JSON.stringify(raw));}
  evidence(id,value){this.db.prepare('INSERT OR REPLACE INTO evidence VALUES(?,?)').run(id,JSON.stringify(value));}
  observed(id){const r=this.db.prepare('SELECT payload FROM evidence WHERE id=?').get(id);return r?JSON.parse(r.payload):null;}
  rows(kind,dirty=false){return this.db.prepare('SELECT payload FROM records WHERE kind=?'+(dirty?' AND imported=0':'')).all(kind).map(r=>JSON.parse(r.payload));}
  markImported(){this.db.exec('UPDATE records SET imported=1');}
  authors(){return [...new Map(this.rows('post').filter(r=>r['作者主页链接']).map(r=>[r['作者主页链接'],r['作者id']])).entries()];}
  meta(key,value){if(value!==undefined)this.db.prepare('INSERT OR REPLACE INTO meta VALUES(?,?)').run(key,JSON.stringify(value));const r=this.db.prepare('SELECT value FROM meta WHERE key=?').get(key);return r?JSON.parse(r.value):null;}
  async export(dir){await fs.mkdir(dir,{recursive:true});for(const [kind,name,fields] of [['post','ods_social_media_post',POST_FIELDS],['comment','ods_social_media_comment',COMMENT_FIELDS]]){const rows=this.rows(kind);await fs.writeFile(path.join(dir,name+'.jsonl'),rows.map(r=>JSON.stringify(r)).join('\n')+(rows.length?'\n':''),'utf8');const q=v=>'"'+String(v??'').replaceAll('"','""')+'"';await fs.writeFile(path.join(dir,name+'.csv'),'\uFEFF'+[fields.map(q).join(','),...rows.map(r=>fields.map(f=>q(r[f])).join(','))].join('\r\n'),'utf8');}await atomic(path.join(dir,'evidence.json'),this.db.prepare('SELECT payload FROM evidence').all().map(r=>JSON.parse(r.payload)));}
  close(){this.db.close();}
}
