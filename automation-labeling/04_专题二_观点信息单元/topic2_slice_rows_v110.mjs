// Deterministic presentation merge. Does not change semantic labels or scores.
import {validateFieldValue} from './topic2_field_options_v108.mjs';
export const DETAIL_GRAIN='source-and-original-span-v110';
const clone=v=>structuredClone(v);
const parse=v=>typeof v==='string'?JSON.parse(v):clone(v);
const canonical=v=>JSON.stringify(v,(_,x)=>x&&typeof x==='object'&&!Array.isArray(x)?Object.fromEntries(Object.keys(x).sort().map(k=>[k,x[k]])):x);
const uniq=xs=>[...new Set(xs)];
const span=r=>JSON.stringify([r.record_id,r.起点,r.终点]);
const textKey=r=>JSON.stringify([r.record_id,r['原始摘录']]);
const fields=['来源类型','源表id','父文章ODS主键','发布日期','平台','发布者角色','原始摘录','情绪评分','热度指数'];
const preservedFields=['切片ID','原切片ID','起点','终点','project_id','项目名称','项目角色','观点摘要','标签明细','打标说明','表达类型','情绪态度','项目与标签证据'];

function expand(row){
 const proof=parse(row['项目与标签证据']);
 if(!['source-and-original-span-v109',DETAIL_GRAIN].includes(proof?.format))return [clone(row)];
 if(!proof.project_views?.length)throw Error('Merged slice lacks original project bindings');
 return proof.project_views.map(view=>({...clone(row),...clone(view)}));
}
function labelsOf(row){
 const labels=parse(row['标签明细']),pid=row.project_id;
 if(typeof pid!=='string'||!pid||/[;；]/.test(pid))throw Error('Expected one explicit project per original view');
 if(!Array.isArray(labels)||!labels.length)throw Error('Labeled view has no labels');
 const result=new Map();
 for(const label of labels){
  if(!label['标签路径ID']||(label.project_id&&label.project_id!==pid))throw Error('Invalid label/project binding');
  const key=label['标签路径ID'];
  if(result.has(key)&&canonical(result.get(key))!==canonical(label))throw Error('Conflicting definitions for same project/tag');
  result.set(key,clone(label));
 }
 return [...result.values()];
}
function validateIdentity(row){
 if(!row.record_id||!row['原切片ID']||!Number.isInteger(row.起点)||!Number.isInteger(row.终点)||row.起点<0||row.终点<=row.起点||typeof row['原始摘录']!=='string'||!row['原始摘录'])throw Error('Missing source/slice identity, text or valid offsets');
}
function statements(views,field){
 if(uniq(views.map(r=>r[field]??'')).length===1)return views[0][field];
 return uniq(views.filter(r=>r[field]).map(r=>`【${r['项目名称']}】${r[field]}`)).join('\n');
}
function categories(views,field){
 const values=uniq(views.flatMap(r=>String(r[field]??'').split(';')));
 const value=values.join(';');
 validateFieldValue(field,value,views[0].record_id);
 return value;
}
export function assertUniqueDetailRows(rows){
 const spans=new Set(),texts=new Set(),ids=new Set();
 for(const row of rows){
  validateIdentity(row);
  const s=span(row),t=textKey(row),id=JSON.stringify([row.record_id,row['原切片ID']]);
  if(spans.has(s)||texts.has(t)||ids.has(id))throw Error('Duplicate original slice in final delivery');
  spans.add(s);texts.add(t);ids.add(id);
  for(const field of ['表达类型','情绪态度','发布者角色'])validateFieldValue(field,row[field],row.record_id);
  const seen=new Set();
  for(const label of parse(row['标签明细'])){
   const pid=label.project_id??row.project_id;
   if(!pid||/[;；]/.test(pid)||!label['标签路径ID'])throw Error('Label lacks an unambiguous project/tag binding');
   const key=JSON.stringify([pid,label['标签路径ID']]);
   if(seen.has(key))throw Error('Duplicate label in final slice');
   seen.add(key);
  }
 }
 return true;
}
export function mergeDetailRows(input){
 if(!Array.isArray(input))throw Error('Detail rows must be an array');
 const groups=new Map(),spanTexts=new Map(),idSpans=new Map();
 for(const entry of input)for(const original of expand(entry)){
  validateIdentity(original);
  const s=span(original),text=textKey(original),id=JSON.stringify([original.record_id,original['原切片ID']]);
  if(spanTexts.has(s)&&spanTexts.get(s)!==text)throw Error('Conflicting original text for identical source offsets');
  if(idSpans.has(id)&&idSpans.get(id)!==s)throw Error('One original slice ID has conflicting offsets');
  spanTexts.set(s,text);idSpans.set(id,s);
  original['标签明细']=labelsOf(original);
  if(!groups.has(text))groups.set(text,[]);
  groups.get(text).push(original);
 }
 const output=[];
 for(const views of groups.values()){
  const first=views[0];
  for(const view of views)for(const field of fields)
   if(canonical(view[field]??null)!==canonical(first[field]??null))throw Error(`Cannot merge conflicting ${field}: ${first.record_id}/${first['原切片ID']}`);
  const expression=categories(views,'表达类型'),attitude=categories(views,'情绪态度');
  if(views.length===1){output.push(clone(first));continue;}
  const projects=new Map(),labels=new Map(),originals=new Map();
  for(const view of views){
   const project={project_id:view.project_id,'项目名称':view['项目名称'],'项目角色':view['项目角色']};
   const pid=view.project_id;
   if(projects.has(pid)&&canonical(projects.get(pid))!==canonical(project))throw Error('Conflicting project identity');
   projects.set(pid,project);
   for(const label of view['标签明细']){
    const annotated={...label,...project},key=JSON.stringify([pid,label['标签路径ID']]);
    if(labels.has(key)&&canonical(labels.get(key))!==canonical(annotated))throw Error('Conflicting label definition');
    labels.set(key,annotated);
   }
   const original=Object.fromEntries(preservedFields.map(k=>[k,k==='项目与标签证据'?parse(view[k]):clone(view[k])]));
   originals.set(canonical(original),original);
  }
  const merged=clone(first),ps=[...projects.values()];
  merged['切片ID']=first['原切片ID'];
  for(const field of ['project_id','项目名称','项目角色'])merged[field]=ps.map(p=>p[field]).join('；');
  merged['观点摘要']=statements(views,'观点摘要');
  merged['打标说明']=statements(views,'打标说明');
  merged['标签明细']=[...labels.values()];
  merged['表达类型']=expression;merged['情绪态度']=attitude;
  merged['项目与标签证据']={format:DETAIL_GRAIN,record_id:first.record_id,
   original_slice_ids:uniq(views.map(r=>r['原切片ID'])),original_view_ids:uniq(views.map(r=>r['切片ID'])),
   source_spans:[...new Map(views.map(r=>[span(r),{start:r.起点,end:r.终点}])).values()],
   project_views:[...originals.values()],note:'同来源相同原文合并；标签按项目与字典ID去重，保留原项目绑定、所有位置与证据，未重新打标或评分。'};
  output.push(merged);
 }
 assertUniqueDetailRows(output);
 return output;
}
