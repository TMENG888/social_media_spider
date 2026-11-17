// Independent read-only database snapshot. Does not load or execute a collector.
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import fs from 'node:fs';
import {verifyImportedDates} from './article-date-metrics.mjs';
import {readBrandInventory} from './brand-metrics.mjs';
const common=process.argv[2], require=createRequire(path.join(common,'package.json'));
const mysql=require('mysql2/promise');
const {mysqlTargetOptions}=await import(pathToFileURL(path.join(common,'src/mysql-target-options.mjs')));
let c;
try {
 c=await mysql.createConnection({...mysqlTargetOptions(),user:process.env.MYSQL_USER,password:process.env.MYSQL_PASSWORD,connectTimeout:8000});
 await c.query({sql:'SET SESSION MAX_EXECUTION_TIME=15000',timeout:16000});
 await c.query({sql:'START TRANSACTION READ ONLY',timeout:16000});
 const args=['全国地产设计产品力监测','北京臻澐项目口碑','小红书','抖音'];
 const [posts]=await c.execute({sql:'SELECT `平台` AS platform,`项目` AS project,COUNT(*) AS n FROM ods_social_media_post WHERE `项目` IN (?,?) AND `平台` IN (?,?) GROUP BY `平台`,`项目`',timeout:16000},args);
 const [comments]=await c.execute({sql:'SELECT `平台` AS platform,`项目` AS project,COUNT(*) AS n FROM ods_social_media_comment WHERE `项目` IN (?,?) AND `平台` IN (?,?) GROUP BY `平台`,`项目`',timeout:16000},args);
 const input=fs.readFileSync(0,'utf8').trim();
 const articleDates=await verifyImportedDates(c,input?JSON.parse(input):[]);
 const brands=await readBrandInventory(c,path.resolve(common,'../..'));
 await c.commit();
 console.log(JSON.stringify({source:'ok',at:new Date().toISOString(),posts,comments,articleDates,brands}));
} catch(e) {console.log(JSON.stringify({source:'unavailable',errorType:e.code||'DB_READ_FAILED',at:new Date().toISOString()}));}
finally {if(c)await c.end().catch(()=>{});}
