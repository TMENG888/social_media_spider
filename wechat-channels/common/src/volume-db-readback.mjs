import fs from 'node:fs';
import mysql from 'mysql2/promise';
import {mysqlConnectionOptions} from './mysql-connection-options.mjs';
import {readVolumeSnapshot,readTaskVolume,validateVolumeSnapshot} from './volume-acceptance.mjs';
import {assessChannelsAnnual} from './channels-annual-acceptance.mjs';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {retryInfrastructure} from './infrastructure-retry.mjs';
let stage='validation';
export async function executeReadback(input,{createConnection=options=>mysql.createConnection(options),retryOptions={}}={}){
 return retryInfrastructure(async()=>{
 stage='validation';
 const connect=async()=>{stage='connect';const c=await createConnection(mysqlConnectionOptions());stage='query';return c;};
 let result;
 if(input.operation==='probe'){
  const connection=await connect();
  try{
   await connection.query('SET TRANSACTION READ ONLY');await connection.beginTransaction();
   await connection.query('SELECT 1 FROM ods_social_media_post LIMIT 0');
   await connection.query('SELECT 1 FROM ods_social_media_comment LIMIT 0');
   await connection.commit();result={ok:true,dbReadbackVerified:true,readOnly:true};
  }catch(error){await connection.rollback().catch(()=>{});throw error;}
  finally{await connection.end();}
 }
 else if(input.operation==='snapshot')result=await readVolumeSnapshot({connect,platform:'微信视频号',tasks:input.tasks,population:'nonzero_keywords',minimumPosts:1});
 else if(input.operation==='validate'){validateVolumeSnapshot(input.snapshot,{platform:'微信视频号',tasks:input.tasks});result={ok:true};}
 else if(input.operation==='task')result=await readTaskVolume({connect,snapshot:input.snapshot,taskId:input.taskId});
 else if(input.operation==='annual'){
  const decision=await readTaskVolume({connect,snapshot:input.snapshot,taskId:input.taskId});
  const connection=await connect();
  try{
   await connection.query('SET TRANSACTION READ ONLY');await connection.beginTransaction();
   const [rows]=await connection.execute('SELECT `文章id` AS noteId,`文章时间地点` AS publishedAt,`文章标题` AS title,`文章链接` AS url,`作者名字` AS author FROM ods_social_media_post WHERE `平台`=? AND `项目`=? AND `关键词`=?',
    [decision.platform,decision.projectName,decision.keyword]);
   result=assessChannelsAnnual(decision,input,rows);await connection.commit();
  }catch(error){await connection.rollback().catch(()=>{});throw error;}
  finally{await connection.end();}
 }
 else throw new Error('VOLUME_OPERATION_INVALID');
 return result;
 },{operation:'database_readback',...retryOptions});
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))try{
 console.log(JSON.stringify(await executeReadback(JSON.parse(fs.readFileSync(0,'utf8')))));
}catch(error){
 const configurationErrors=new Set(['MYSQL_CREDENTIALS_MISSING','MYSQL_TARGET_INVALID']);
 const errorCode=error.code||(configurationErrors.has(error.message)?error.message:stage==='validation'?'VOLUME_VALIDATION_FAILED':'VOLUME_READBACK_FAILED');
 // Never print error.message/sql/parameters/credentials from driver exceptions.
 console.error(JSON.stringify({ok:false,errorCode,stage}));process.exitCode=1;
}
