import mysql from 'mysql2/promise';
import {pathToFileURL} from 'node:url';
import {cleanCompactContent,cleanVideoContent} from './channels-field-normalization.mjs';
import {mysqlConnectionOptions} from './mysql-connection-options.mjs';
import {transcriptArtifact} from './transcript-quality.mjs';
export async function verifyCheckpoints(connection,checkpoints,{collectComments=true}={}){
 const [columns]=await connection.query('SHOW FULL COLUMNS FROM ods_social_media_post');
 const legacy=new Set(columns.filter(c=>/^(utf8mb3|utf8)_/i.test(c.Collation||'')).map(c=>c.Field));
 const compatible=(field,value)=>{
  const text=String(value??'');return legacy.has(field)?text.replace(/[\u{10000}-\u{10FFFF}]/gu,''):text;
 };
 const matches=(field,actual,raw,normalized)=>[raw,normalized].some(value=>String(actual??'')===compatible(field,value));
 const verified=[];
 for(const [fp,cp] of Object.entries(checkpoints)){
  const r=cp.row||{};
  if(!['completed','no_content','not_applicable'].includes(cp.status)||!cp.article_key||!cp.project||!r.title||!r.url||!r.author_name)continue;
  if(/全国地产设计产品力监测|北京臻澐项目口碑(?:监测|采集)/u.test(r.video_content||''))continue;
  if(transcriptArtifact(r.video_content))continue;
  if(cp.status==='completed'&&(!r.video_content||!['completed','no_content','not_applicable'].includes(cp.asr_status)))continue;
  const [rows]=await connection.execute('SELECT `文章标题`,`文章链接`,`作者名字`,`文章视频内容`,`文章视频时长` FROM ods_social_media_post WHERE `平台`=? AND `项目`=? AND `文章id`=? LIMIT 2',['微信视频号',cp.project,cp.article_key]);
  if(rows.length!==1)continue;
  const actual=rows[0];
  if(!matches('文章标题',actual.文章标题,r.title,cleanCompactContent(r.title).content)
   ||actual.文章链接!==r.url||!matches('作者名字',actual.作者名字,r.author_name,r.author_name)
   ||!matches('文章视频内容',actual.文章视频内容,r.video_content,cleanVideoContent(r.video_content).text))continue;
  if(!(Number(r.video_duration)>0)||!Number.isFinite(Number(actual.文章视频时长))||!(Number(actual.文章视频时长)>0)||Math.abs(Number(actual.文章视频时长)-Number(r.video_duration))>2)continue;
  if(cp.field_completeness&&Object.entries(cp.field_completeness).some(([field,value])=>!(field==='comments'&&collectComments===false)&&value!==true))continue;
  verified.push(fp);
 }
 return {verifiedFingerprints:verified};
}
if(process.argv[1]&&pathToFileURL(process.argv[1]).href===import.meta.url){
 let connection;
 try{
  if(!process.env.MYSQL_USER||!process.env.MYSQL_PASSWORD)throw new Error('MYSQL_CREDENTIALS_MISSING');
  let input='';for await(const chunk of process.stdin)input+=chunk;
  const request=JSON.parse(input);
  connection=await mysql.createConnection(mysqlConnectionOptions());
  await connection.query('SET TRANSACTION READ ONLY');await connection.beginTransaction();
  const result=await verifyCheckpoints(connection,request.checkpoints,{collectComments:request.collectComments!==false});
  await connection.commit();process.stdout.write(JSON.stringify(result));
 }catch{process.stderr.write('DB_READBACK_FAILED');process.exitCode=1;}finally{await connection?.end();}
}
