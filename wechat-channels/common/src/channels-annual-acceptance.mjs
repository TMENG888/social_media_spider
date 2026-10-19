import {assessAnnualLowVolume} from './keyword-annual-acceptance.mjs';
import {cleanCompactContent} from './channels-field-normalization.mjs';
import {createHash} from 'node:crypto';
const digest=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const yearOf=value=>{
 const m=String(value||'').match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T]|$)/);if(!m)return null;
 const [y,month,day]=m.slice(1).map(Number),d=new Date(Date.UTC(y,month-1,day));
 return d.getUTCFullYear()===y&&d.getUTCMonth()===month-1&&d.getUTCDate()===day?y:null;
};
const same=(actual,expected)=>String(actual??'')===String(expected??'')
 ||String(actual??'')===String(expected??'').replace(/[\u{10000}-\u{10FFFF}]/gu,'');

export function assessChannelsAnnual(decision,{scan,checkpoints,year=2026}={},rows=[]){
 if(!checkpoints||typeof checkpoints!=='object'||Array.isArray(checkpoints))throw new Error('ANNUAL_CHECKPOINTS_REQUIRED');
 const sql=new Map();
 for(const row of rows){
  const id=String(row.noteId||'').trim();if(!id||sql.has(id)||yearOf(row.publishedAt)!==year)throw new Error('ANNUAL_SQL_YEAR_OR_ID_UNVERIFIED');
  sql.set(id,row);
 }
 if(sql.size!==decision.posts)throw new Error('ANNUAL_SQL_SNAPSHOT_CHANGED');
 const groups=new Map();
 for(const [fingerprint,cp] of Object.entries(checkpoints)){
  // Only an exact business article ID can collapse two observed fingerprints.
  const scoped=cp&&cp.keyword===decision.keyword&&cp.project===decision.projectName;
  const key=scoped&&String(cp.article_key||'').trim()?'article:'+cp.article_key:'checkpoint:'+fingerprint;
  if(!groups.has(key))groups.set(key,[]);
  groups.get(key).push(scoped?cp:null);
 }
 const inventory=[...groups].map(([noteId,copies])=>{
  const base={noteId,keyword:decision.keyword,projectName:decision.projectName,disposition:'unknown_or_missing'};
  for(const cp of copies){
   const row=cp?.row,actual=cp?sql.get(String(cp.article_key)):null;
   if(!row||!actual||row.keyword!==decision.keyword||row.project!==decision.projectName||yearOf(row.published_at)!==year)continue;
   if(!row.title||!row.url||!row.author_name||actual.url!==row.url)continue;
   if(!same(actual.title,row.title)&&!same(actual.title,cleanCompactContent(row.title).content))continue;
   if(!same(actual.author,row.author_name))continue;
   // Subtitle text, ASR/dead-letter status and duration quality deliberately
   // do not gate the original keyword's metadata/database acceptance.
   return {...base,disposition:'imported_current_year',year,importVerified:true};
  }
  return base;
 });
 const evidence=assessAnnualLowVolume(decision,{scan,inventory,year});
 return {decision,evidence,checkpointInventoryDigest:digest(inventory)};
}
