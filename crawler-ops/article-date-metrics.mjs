import {publicationDate,COLLECTION_PASS} from './article-dates.mjs';

export async function verifyImportedDates(connection,requests) {
  const results=[];
  for(const r of requests){
    const out={machine:r.machine,platform:r.platform,keyword:r.keyword,taskId:r.taskId,collectionPass:r.collectionPass,source:'unavailable',earliestImportedPublishedAt:null,verifiedPosts:null};
    try{
      if(!['xhs','douyin'].includes(r.platform)||!Array.isArray(r.ids)||r.ids.length>10000)throw new Error('DATE_IDS_INVALID');
      if(r.collectionPass!==COLLECTION_PASS||!new RegExp('^'+(r.platform==='xhs'?'xhs':'dy')+'-[a-f0-9]{64}$').test(r.taskId||''))throw new Error('DATE_BATCH_INVALID');
      const ids=[...new Set(r.ids.map(String))],found=new Set(),dates=[];
      const platform=r.platform==='xhs'?'小红书':'抖音';
      for(let start=0;start<ids.length;start+=500){
        const batch=ids.slice(start,start+500);
        const [rows]=await connection.execute({sql:'SELECT `文章id` AS articleId, CAST(`文章时间地点` AS CHAR) AS publishedAt FROM ods_social_media_post WHERE `平台`=? AND `项目`=? AND `文章id` IN ('+batch.map(()=>'?').join(',')+')',timeout:16000},[platform,'全国地产设计产品力监测',...batch]);
        for(const row of rows){found.add(String(row.articleId));const date=publicationDate(row.publishedAt);if(date)dates.push(date);}
      }
      dates.sort();out.source='ok';out.verifiedPosts=found.size;out.earliestImportedPublishedAt=dates[0]||null;
      out.importedDatesMissing=found.size>0&&!dates.length;
    }catch(e){out.errorType=e.code||'DATE_DB_READ_FAILED';}
    results.push(out);
  }
  return results;
}
