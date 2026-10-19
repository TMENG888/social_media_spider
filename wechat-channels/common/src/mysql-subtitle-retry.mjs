// Precise retry DB boundary: no INSERT, no title-only lookup, no Redis ACK.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {ProductionOutputRecorder} from './production-output.mjs';
import {mysqlConnectionOptions} from './mysql-connection-options.mjs';
export const textHash = value => crypto.createHash('sha256').update(String(value ?? ''), 'utf8').digest('hex');
export function selector(request) {
  if (request.platform !== '微信视频号' || !request.project) throw new Error('Exact platform/project required');
  const field = request.dbId ? 'id' : request.articleId ? '文章id' : request.url ? '文章链接' : null;
  if (!field) throw new Error('Database id, article id or canonical URL required; title-only match is forbidden');
  return {sql:`\`${field}\`=? AND \`平台\`=? AND \`项目\`=?`,
    values:[String(request.dbId || request.articleId || request.url),request.platform,request.project]};
}
function verify(row, request) {
  if (request.articleId && String(row['文章id'])!==String(request.articleId)) throw new Error('Article id mismatch');
  if (request.url && row['文章链接']!==request.url) throw new Error('Canonical link mismatch');
  if (!/^https:\/\/weixin\.qq\.com\/sph\/[A-Za-z0-9]+$/.test(String(row['文章链接'] || ''))) throw new Error('No valid Channels canonical link');
  for (const [key,field] of [['expectedAuthor','作者名字'],['expectedTitle','文章标题']]) {
    if (request[key] && request[key] !== row[field]) throw new Error(`Identity mismatch: ${field}`);
  }
}
export async function lookup(conn, request, lock=false) {
  const s=selector(request);
  const [rows]=await conn.execute(`SELECT * FROM ods_social_media_post WHERE ${s.sql} LIMIT 2${lock?' FOR UPDATE':''}`,s.values);
  if (rows.length!==1) throw new Error(`Exact lookup must match one row, found ${rows.length}`);
  verify(rows[0],request);
  return rows[0];
}
export async function updateSubtitle(conn, request, writeBackup, recorder=null) {
  if (request.approved!==true || !String(request.subtitle || '').trim()) throw new Error('Approved nonempty candidate required');
  if (/全国地产设计产品力监测|北京臻澐项目口碑(?:监测|采集)/u.test(request.subtitle)) throw new Error('Candidate contains known internal pollution');
  if (!request.expectedOldHash) throw new Error('Old subtitle hash required');
  let committed=false;
  await conn.beginTransaction();
  try {
    const old=await lookup(conn,request,true);
    if (textHash(old['文章视频内容'])!==request.expectedOldHash) throw new Error('Old subtitle changed; retry requires new review');
    await writeBackup({at:new Date().toISOString(),id:String(old.id),url:old['文章链接'],
      platform:old['平台'],project:old['项目'],oldSubtitle:old['文章视频内容'],
      newSubtitle:request.subtitle,reason:request.reason || 'approved precise subtitle retry'});
    if (old['文章视频内容']!==request.subtitle) {
      const [result]=await conn.execute('UPDATE ods_social_media_post SET `文章视频内容`=? WHERE id=? AND `平台`=? AND `项目`=? AND `文章链接`=? AND `文章视频内容` <=> ?',
        [request.subtitle,old.id,old['平台'],old['项目'],old['文章链接'],old['文章视频内容']]);
      if (result.affectedRows!==1) throw new Error('UPDATE did not affect exactly one row');
    }
    const updated=await lookup(conn,{...request,dbId:String(old.id)},true);
    if (updated['文章视频内容']!==request.subtitle) throw new Error('Readback subtitle mismatch');
    for (const k of Object.keys(old)) {
      if (k==='文章视频内容') continue;
      if (JSON.stringify(old[k])!==JSON.stringify(updated[k])) throw new Error(`Unexpected field change: ${k}`);
    }
    if (recorder) {recorder.track('ods_social_media_post',old,updated,{approved:true});recorder.prepare();recorder.commitAttempted=true;}
    await conn.commit();committed=true;
    if (recorder) {try {recorder.markCommitted();} catch {console.log(JSON.stringify({event:'production_output_verification_deferred',databaseCommitUnaffected:true}));}}
    const final=await lookup(conn,{...request,dbId:String(old.id)});
    if (final['文章视频内容']!==request.subtitle) throw new Error('Post-commit readback failed; do not confirm Redis');
    if (recorder) {try {recorder.confirmRows({['ods_social_media_post:'+String(old.id)]:final});recorder.flush();} catch {console.log(JSON.stringify({event:'production_output_verification_deferred',databaseCommitUnaffected:true}));}}
    return {committed:true,readbackVerified:true,id:String(old.id),url:final['文章链接'],subtitleHash:textHash(final['文章视频内容']),updatedFields:['文章视频内容']};
  } catch(error) {
    if (!committed) await conn.rollback();
    if (!committed && recorder) {try {recorder.abort();} catch {}}
    throw error;
  }
}
async function main() {
  const [action,requestFile,outputFile]=process.argv.slice(2);
  if (!['lookup','update'].includes(action) || !requestFile || !outputFile) throw new Error('Usage: lookup|update request.json output.json');
  if (!process.env.MYSQL_USER || !process.env.MYSQL_PASSWORD) throw new Error('MYSQL_USER/MYSQL_PASSWORD absent; no DB operation performed');
  const request=JSON.parse(await fs.readFile(requestFile,'utf8'));
  const {default:mysql}=await import('mysql2/promise');
  const conn=await mysql.createConnection({...mysqlConnectionOptions(),
    supportBigNumbers:true,bigNumberStrings:true});
  try {
    const result=action==='lookup' ? await lookup(conn,request) : await updateSubtitle(conn,request,async backup=>{
      const backupFile=path.join(path.dirname(outputFile),`subtitle-retry-backup-${Date.now()}-${crypto.randomUUID()}.json`);
      const handle=await fs.open(backupFile,'wx');try {await handle.writeFile(JSON.stringify(backup,null,2));await handle.sync();}finally {await handle.close();}
    },new ProductionOutputRecorder({source:'precise_subtitle_retry'}));
    const tmp=outputFile+'.tmp-'+crypto.randomUUID();await fs.writeFile(tmp,JSON.stringify(result,null,2));await fs.rename(tmp,outputFile);
    console.log(JSON.stringify({action,ok:true,output:outputFile}));
  } finally {await conn.end();}
}
if (process.argv[1] && import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href) main().catch(e=>{console.error(e.message);process.exitCode=1;});
