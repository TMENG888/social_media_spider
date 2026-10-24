import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=path.dirname(fileURLToPath(import.meta.url));
const {default:mysql}=await import(pathToFileURL(path.join(process.env.SPIDER_COMMON_ROOT||path.resolve(root,'../../..','xiaohongshu/common'),'node_modules/mysql2/promise.js')).href);
let db,transaction=false;
try {
 if(!process.env.MYSQL_USER||!process.env.MYSQL_PASSWORD)throw Object.assign(Error(),{code:'MISSING_CREDENTIALS'});
 db=await mysql.createConnection({host:process.env.MYSQL_HOST||'127.0.0.1',port:Number(process.env.MYSQL_PORT||3306),database:process.env.MYSQL_DATABASE||'social',user:process.env.MYSQL_USER,password:process.env.MYSQL_PASSWORD,charset:'utf8mb4',connectTimeout:20000,multipleStatements:false,bigNumberStrings:true,supportBigNumbers:true,dateStrings:true});
 delete process.env.MYSQL_PASSWORD;
 const query=async(sql,args=[])=>{const [rows]=await db.query({sql,timeout:90000},args);return rows;};
 await query('SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ');
 await query('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY');transaction=true;
 const started=new Date().toISOString();
 const fields=['id','项目','平台','内容类型','文章点赞数','文章收藏数','文章分享数','文章评论数','热度指数'];
 const rows=await query('SELECT '+fields.map(x=>'`'+x+'`').join(',')+' FROM ods_social_media_post WHERE BINARY `项目`=BINARY ? OR BINARY `项目`=BINARY ? ORDER BY id',['全国地产设计产品力监测','北京臻澐项目口碑']);
 await db.rollback();transaction=false;
 const csvEscape=value=>{const x=value==null?'':String(value);return /[",\r\n]/.test(x)?'"'+x.replaceAll('"','""')+'"':x;};
 const csv='\ufeff'+fields.join(',')+'\r\n'+rows.map(r=>fields.map(h=>csvEscape(r[h])).join(',')).join('\r\n')+'\r\n';
 const file=path.join(root,'full_two_topic_heat_baseline.csv');await fs.writeFile(file,csv,'utf8');
 const manifest={database_writes:false,started_at:started,finished_at:new Date().toISOString(),rows:rows.length,topic_counts:Object.fromEntries([...new Set(rows.map(r=>r['项目']))].map(t=>[t,rows.filter(r=>r['项目']===t).length])),file,sha256:crypto.createHash('sha256').update(Buffer.from(csv)).digest('hex')};
 await fs.writeFile(path.join(root,'heat_baseline_manifest.json'),JSON.stringify(manifest,null,2),'utf8');
 console.log(JSON.stringify(manifest));
}catch(e){console.error('Read-only heat snapshot failed:',/^[A-Z0-9_]+$/.test(String(e.code||''))?e.code:'QUERY_FAILED');process.exitCode=1;}
finally{delete process.env.MYSQL_PASSWORD;if(db){if(transaction)await db.rollback().catch(()=>{});await db.end().catch(()=>{});}}
