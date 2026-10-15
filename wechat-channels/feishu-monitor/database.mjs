import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const root=path.dirname(fileURLToPath(import.meta.url));
const require=createRequire(path.join(root,'../common/package.json'));
const mysql=require('mysql2/promise');
const {atomicWriteFileSync}=await import('../common/src/atomic-file.mjs');
const config=JSON.parse(fs.readFileSync(path.join(root,'config.json'),'utf8'));
let conn,result;
// Raw nonempty counts are retained separately from media-applicable denominators.
// Douyin deliberately stores its caption in title and keeps article body NULL.
const coreColumns = `SUM(NULLIF(TRIM(\`文章标题\`),'') IS NOT NULL) AS titleNonempty,
  SUM(NULLIF(TRIM(\`文章内容\`),'') IS NOT NULL) AS bodyNonempty,
  SUM(NULLIF(TRIM(\`文章视频内容\`),'') IS NOT NULL) AS videoContentNonempty,
  SUM(CASE WHEN \`内容类型\`='视频' THEN 1 ELSE 0 END) AS videoEligible,
  SUM(CASE WHEN \`内容类型\`='视频' AND NULLIF(TRIM(\`文章视频内容\`),'') IS NOT NULL THEN 1 ELSE 0 END) AS videoEligibleNonempty,
  SUM(CASE WHEN NULLIF(TRIM(\`内容类型\`),'') IS NULL OR \`内容类型\` NOT IN ('视频','图文','纯文本') THEN 1 ELSE 0 END) AS mediaTypeUnknown,
  SUM(CASE WHEN NULLIF(TRIM(\`文章标题\`),'') IS NULL OR
    (\`平台\` NOT IN ('抖音','微信视频号') AND NULLIF(TRIM(\`文章内容\`),'') IS NULL) OR
    (\`内容类型\`='视频' AND NULLIF(TRIM(\`文章视频内容\`),'') IS NULL) THEN 1 ELSE 0 END) AS coreMissing`;
try {
  if (!process.env.MYSQL_USER || !process.env.MYSQL_PASSWORD) throw new Error('credential unavailable');
  conn=await mysql.createConnection({host:process.env.MYSQL_HOST || '127.0.0.1',port:Number(process.env.MYSQL_PORT||3306),database:config.database,user:process.env.MYSQL_USER,password:process.env.MYSQL_PASSWORD,connectTimeout:12000,charset:'utf8mb4',ssl:/^(1|true|yes)$/i.test(process.env.MYSQL_SSL||'')?{}:undefined});
  await conn.query('SET SESSION MAX_EXECUTION_TIME=15000');
  await conn.query('START TRANSACTION READ ONLY');
  const placeholders=config.projects.map(()=>'?').join(',');
  const [posts]=await conn.execute(`SELECT \`项目\` AS project, COUNT(*) AS posts, ${coreColumns}, SUM(NULLIF(TRIM(\`文章视频内容\`),'') IS NOT NULL) AS subtitleNonempty, MAX(\`文章获取时间\`) AS latestCollectedAt FROM ods_social_media_post WHERE \`平台\`=? AND \`项目\` IN (${placeholders}) GROUP BY \`项目\``,['微信视频号',...config.projects]);
  const [comments]=await conn.execute(`SELECT \`项目\` AS project,COUNT(*) AS comments FROM ods_social_media_comment WHERE \`平台\`=? AND \`项目\` IN (${placeholders}) GROUP BY \`项目\``,['微信视频号',...config.projects]);
  const observedProjects=new Set(config.projects);
  for (const platform of ['小红书','抖音']) {
    const observation=JSON.parse(fs.readFileSync(path.join(root,'output',`platform-${platform}.json`),'utf8'));
    for (const project of observation.projects || []) observedProjects.add(project);
  }
  const projects=[...observedProjects];
  const [otherPlatforms]=await conn.execute(`SELECT \`平台\` AS platform,\`项目\` AS project,COUNT(*) AS posts,${coreColumns},SUM(NULLIF(TRIM(\`文章视频内容\`),'') IS NOT NULL) AS contentNonempty FROM ods_social_media_post WHERE \`平台\` IN (?,?) AND \`项目\` IN (${projects.map(()=>'?').join(',')}) GROUP BY \`平台\`,\`项目\``,['小红书','抖音',...projects]);
  await conn.commit();
  result={source:'ok',generatedAt:new Date().toISOString(),posts,comments,otherPlatforms,scope:'historical rows for configured projects and observed production-queue projects; separate platform groups, not exclusively current Redis runs',qualifiedSubtitleRate:null,hourlyInserts:null,hourlyQualifiedSubtitles:null,averageVideoCollectionSeconds:null};
} catch(e) {result={source:'unavailable',errorType:e.code || e.name,generatedAt:new Date().toISOString()};}
finally {if(conn)await conn.end().catch(()=>{});}
atomicWriteFileSync(path.join(root,'output/database.json'),JSON.stringify(result,null,2));
console.log(JSON.stringify({database:result.source,errorType:result.errorType}));
