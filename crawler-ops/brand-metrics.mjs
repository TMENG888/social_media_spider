// Read-only cumulative topic-one inventory, attributed by the stored keyword.
import fs from 'node:fs/promises';
import path from 'node:path';

export async function readBrandInventory(connection,packageRoot){
 const result={source:'unavailable',scope:'topic1_database_cumulative',includesHistorical:true,rows:[],unassigned:[]};
 try{
  const catalogs=[];
  for(const platform of ['小红书','抖音']){
   const catalog=JSON.parse((await fs.readFile(path.join(packageRoot,platform,'common/tasks/keyword-catalog.json'),'utf8')).replace(/^\uFEFF/,''));
   const brands=new Map(),seen=new Map();
   for(const t of catalog.tasks||[]){
    const keyword=String(t.keyword||'').trim(),brand=String(t.brand||'').split(/[／/]/)[0].trim();
    if(!keyword||!brand)throw new Error('BRAND_CATALOG_INVALID');
    if(seen.has(keyword)&&seen.get(keyword)!==brand)throw new Error('BRAND_CATALOG_CONFLICT');
    seen.set(keyword,brand);
    if(!brands.has(brand))brands.set(brand,new Set());brands.get(brand).add(keyword);
   }
   if(!brands.size)throw new Error('BRAND_CATALOG_EMPTY');
   catalogs.push({platform,brands});
  }
  for(const {platform,brands} of catalogs){
   const rows=new Map([...brands.keys()].map(brand=>[brand,{platform,brand,posts:0,comments:0}]));
   const unassigned={platform,posts:0,comments:0};
   const cases=[],params=[];
   for(const [brand,words] of brands){const list=[...words];cases.push('WHEN TRIM(`关键词`) IN ('+list.map(()=>'?').join(',')+') THEN ?');params.push(...list,brand);}
   const expr='CASE '+cases.join(' ')+' ELSE NULL END';
   for(const [table,field,ids] of [['ods_social_media_post','posts','`文章id`'],['ods_social_media_comment','comments','`文章id`,`评论id`']]){
    const [counts]=await connection.execute({sql:'SELECT '+expr+' AS brand,COUNT(DISTINCT '+ids+') AS n FROM '+table+' WHERE `项目`=? AND `平台`=? GROUP BY brand',timeout:16000},[...params,'全国地产设计产品力监测',platform]);
    for(const r of counts){if(r.brand==null)unassigned[field]=Number(r.n);else {const brand=String(r.brand);if(!rows.has(brand))throw new Error('BRAND_DB_MAPPING_INVALID');rows.get(brand)[field]=Number(r.n);}}
   }
   result.rows.push(...rows.values());result.unassigned.push(unassigned);
  }
  return {...result,source:'ok',at:new Date().toISOString()};
 }catch(e){return {...result,source:'unavailable',rows:[],unassigned:[],errorType:e.code||e.message||'BRAND_DB_READ_FAILED'};}
}
