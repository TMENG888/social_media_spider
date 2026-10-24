import mysql from 'mysql2/promise';
import {POST_FIELDS,COMMENT_FIELDS} from './schema.mjs';
import {mysqlTargetOptions} from './mysql-target-options.mjs';

export function options(){return {...mysqlTargetOptions(),user:process.env.MYSQL_USER||'social_user',password:process.env.MYSQL_PASSWORD,charset:'utf8mb4',supportBigNumbers:true,bigNumberStrings:true,connectTimeout:15000};}
const fieldsFor=table=>table==='ods_social_media_post'?POST_FIELDS:COMMENT_FIELDS;
export async function preflight(){const c=await mysql.createConnection(options());try{for(const table of ['ods_social_media_post','ods_social_media_comment']){const [cols]=await c.query(`SHOW FULL COLUMNS FROM \`${table}\``);const fields=fieldsFor(table);const missing=fields.filter(f=>!cols.some(c=>c.Field===f));if(missing.length)throw new Error('MYSQL_SCHEMA_MISMATCH '+table+':'+missing.join(','));}await c.ping();}finally{await c.end();}}
export async function importAuthor(url,stats,assertLease){
 await assertLease();const c=await mysql.createConnection(options());try{await c.beginTransaction();await c.execute('UPDATE `ods_social_media_post` SET `作者粉丝数`=COALESCE(?,`作者粉丝数`),`作者点赞数`=COALESCE(?,`作者点赞数`) WHERE `平台`=? AND `作者主页链接`=? AND `项目`=?',[stats.followers,stats.votes,'知乎',url,'北京臻澐项目口碑']);await assertLease();await c.commit();}catch(e){await c.rollback().catch(()=>{});throw e;}finally{await c.end();}
}
export async function importCheckpoint(checkpoint,assertLease){
 const posts=checkpoint.rows('post',true),comments=checkpoint.rows('comment',true);if(!posts.length&&!comments.length)return {posts:0,comments:0};
 for(let attempt=0;;attempt++){
  await assertLease();const c=await mysql.createConnection(options());let locked=false;
  try{
   const deadline=Date.now()+600000;
   while(!locked){await assertLease();const [r]=await c.query("SELECT GET_LOCK('social_xhs_distributed_import',10) acquired");locked=Number(r[0]?.acquired)===1;if(Date.now()>deadline)throw new Error('MYSQL_IMPORT_LOCK_TIMEOUT');}
   await c.beginTransaction();
   for(const [table,rows] of [['ods_social_media_post',posts],['ods_social_media_comment',comments]]){
    if(!rows.length)continue;const fields=fieldsFor(table);const [columns]=await c.query(`SHOW FULL COLUMNS FROM \`${table}\``);const mb3=new Set(columns.filter(c=>/^utf8(?:mb3)?_/.test(c.Collation||'')).map(c=>c.Field));
    const [max]=await c.query(`SELECT id FROM \`${table}\` ORDER BY id DESC LIMIT 1 FOR UPDATE`);let next=BigInt(max[0]?.id||0);
    for(const original of rows){
     await assertLease();const row={...original,分类:null};for(const f of mb3)if(typeof row[f]==='string')row[f]=[...row[f]].filter(ch=>ch.codePointAt(0)<=65535).join('');
     const keys=table==='ods_social_media_post'?['文章id','平台','项目']:['评论id','文章id','平台','项目'];const where=keys.map(k=>`\`${k}\`=?`).join(' AND ');
     const [found]=await c.execute(`SELECT id FROM \`${table}\` WHERE ${where}`,keys.map(k=>row[k]));if(found.length>1)throw new Error('MYSQL_DUPLICATE_BUSINESS_KEY');
     if(found.length){const updates=fields.filter(f=>f!=='id');const nullable=['作者粉丝数','作者点赞数'];await c.execute(`UPDATE \`${table}\` SET ${updates.map(f=>nullable.includes(f)?`\`${f}\`=COALESCE(?,\`${f}\`)`:`\`${f}\`=?`).join(',')} WHERE id=?`,[...updates.map(f=>row[f]??null),found[0].id]);}
     else{row.id=(++next).toString();await c.execute(`INSERT INTO \`${table}\` (${fields.map(f=>'`'+f+'`').join(',')}) VALUES (${fields.map(()=>'?').join(',')})`,fields.map(f=>row[f]??null));}
    }
   }
   await assertLease();await c.commit();checkpoint.markImported();return {posts:posts.length,comments:comments.length};
  }catch(e){await c.rollback().catch(()=>{});if(attempt>=2||!['ER_LOCK_DEADLOCK','ER_LOCK_WAIT_TIMEOUT'].includes(e.code))throw e;}
  finally{if(locked)await c.query("SELECT RELEASE_LOCK('social_xhs_distributed_import')").catch(()=>{});await c.end();}
 }
}
