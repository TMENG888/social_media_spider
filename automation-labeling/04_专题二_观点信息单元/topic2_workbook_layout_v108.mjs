// Final T2 delivery schema. Does not alter labeling, attribution or scoring.
import fs from 'node:fs';
import {validateDeliveryFields} from './topic2_field_options_v108.mjs';
import {mergeDetailRows,DETAIL_GRAIN} from './topic2_slice_rows_v109.mjs';
import {layout as legacyLayout,col} from 'file:///E:/Codex/work/20261017_v104_acceptance/workbook_layout_v104.mjs';
export {col};
export const schema=JSON.parse(fs.readFileSync(new URL('./topic2_delivery_schema_v108.json',import.meta.url),'utf8'));
const groups=new Map([['标签指标','全部'],['北京臻澐_标签指标','P01'],['建发海晏_标签指标','C01'],['中海·安澜北京_标签指标','C02'],['保利熙瑞_标签指标','C05']]);
const aliases=new Map([['北京臻澐_标签指标','北京臻澐指标'],['建发海晏_标签指标','建发海晏指标'],['中海·安澜北京_标签指标','中海安澜北京指标'],['保利熙瑞_标签指标','保利熙瑞指标']]);
const cell=v=>v===undefined?null:v!==null&&typeof v==='object'?JSON.stringify(v):typeof v==='string'&&v.startsWith('=')?`'${v}`:v;
export function layout(x){
 validateDeliveryFields(x);
 const base=legacyLayout(x),byName=new Map(base.sheets.map(s=>[s.name,s]));
 const sources=new Map(x.sources.map(s=>[s.record_id,s]));
 const sheets=schema.sheets.map(spec=>{
  const prior=byName.get(aliases.get(spec.name)||spec.name);
  let objects=prior?prior.rows.map(r=>Object.fromEntries(prior.headers.map((h,i)=>[h,r[i]]))):[];
  if(spec.name==='打标明细')objects=mergeDetailRows(objects);
  if(spec.name==='历史撤标与补标'){
   const history=x.history_changes??x.history??[];
   if(!Array.isArray(history))throw Error('history_changes must be a list of original audit records');
   objects=history;
  }
  if(spec.name==='来源范围')objects=objects.map(o=>{
   const s=sources.get(o.record_id);
   return {...o,'标题':o['自身标题'],'原文字段':s.field??null,'全目录及事实自检':s.catalogue_checked??null,'来源沿用':s.prior_selected_reuse??null};
  });
  if(spec.name==='源记录与文章关联')objects=objects.map(o=>({...o,'该项目字典ID':[...new Set(x.pairs.filter(p=>p.record_id===o.record_id&&p.group===o.project_id).map(p=>p.tag_id))].join('；')}));
  const rows=objects.map(o=>spec.headers.map(h=>cell(o[h])));
  if(rows.some(r=>r.some(v=>typeof v==='string'&&v.length>32767)))throw Error('Excel text limit exceeded after slice merge: '+spec.name);
  const dateColumns=spec.headers.flatMap((h,i)=>h==='发布日期'?[i]:[]);
  const textColumns=spec.headers.flatMap((h,i)=>/id$|ID$|主键$|源表id$|平台文章id$/.test(h)?[i]:[]);
  const s={...structuredClone(spec),rows,dateColumns,textColumns,end:rows.length+5};
  if(groups.has(spec.name)){
   s.group=groups.get(spec.name);s.metrics=prior.metrics;
   s.metricValues=prior.metrics.map(m=>[m.ratio,m.heat,m.sentiment,m.data_count]);
   // Aggregations are computed upstream; never retain references to removed
   // audit worksheets, or smuggle those worksheets back as hidden tabs.
   s.rows.forEach((r,i)=>r.splice(6,4,...s.metricValues[i]));
   s.metricFormulas=null;
  }
  if(spec.name==='来源范围'){
   // Never report the template's frozen paths/hashes as current provenance.
   s.side_rows=(x.provenance??[]).map(p=>[p.path??null,p.sha256??null]);
  }
  if(rows.some(r=>r.length!==s.headers.length))throw Error('Invalid row width '+s.name);
  return s;
 });
 const main=sheets.find(s=>s.name==='打标明细');
 if(main.headers.length!==23||main.headers.some(h=>schema.removed_detail_headers.includes(h))||main.side_headers.length)throw Error('Forbidden detail field');
 if(sheets.length!==9||new Set(sheets.map(s=>s.name)).size!==9||sheets.some(s=>schema.removed_delivery_sheets.includes(s.name)))throw Error('Delivery worksheet mismatch');
 return {...base,sheets,requiredSheets:sheets.map(s=>s.name),schema_version:schema.version,detail_grain:DETAIL_GRAIN};
}
