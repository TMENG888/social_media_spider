// Presentation grain only. Never reassign projects, retag or recompute scores.
export const DETAIL_GRAIN='source-and-original-span-v109';
const clone=v=>structuredClone(v);
const parse=v=>typeof v==='string'?JSON.parse(v):clone(v);
const uniq=xs=>[...new Set(xs)];
const scalarFields=['来源类型','源表id','父文章ODS主键','发布日期','平台','发布者角色','起点','终点','原始摘录','情绪评分','热度指数'];
const variantFields=['切片ID','原切片ID','project_id','项目名称','项目角色','观点摘要','标签明细','打标说明','表达类型','情绪态度','项目与标签证据'];
const identity=r=>JSON.stringify([r.record_id,r.起点,r.终点]);
function expand(row){
 const proof=parse(row['项目与标签证据']);
 if(proof?.format!==DETAIL_GRAIN)return [clone(row)];
 if(!Array.isArray(proof.project_views)||!proof.project_views.length)throw Error('Merged slice lacks original project bindings');
 return proof.project_views.map(view=>({...clone(row),...clone(view)}));
}
function words(rows,field){return uniq(rows.flatMap(r=>String(r[field]??'').split(';').filter(Boolean))).join(';');}
function statements(rows,field){
 if(uniq(rows.map(r=>r[field]??'')).length===1)return rows[0][field];
 return uniq(rows.filter(r=>r[field]).map(r=>`【${r['项目名称']}】${r[field]}`)).join('\n');
}
export function mergeDetailRows(input){
 if(!Array.isArray(input))throw Error('Detail rows must be an array');
 const groups=new Map(),idSpans=new Map();
 for(const original of input){
  if(!original.record_id||!original['原切片ID']||!Number.isInteger(original.起点)||!Number.isInteger(original.终点)||original.起点<0||original.终点<=original.起点)throw Error('Missing source/slice identity or invalid offsets');
  const key=identity(original),idKey=JSON.stringify([original.record_id,original['原切片ID']]);
  if(idSpans.has(idKey)&&idSpans.get(idKey)!==key)throw Error('One original slice ID has conflicting source offsets');
  idSpans.set(idKey,key);
  if(!groups.has(key))groups.set(key,[]);
  groups.get(key).push(original);
 }
 const output=[];
 for(const entries of groups.values()){
  if(entries.length===1){output.push(clone(entries[0]));continue;}
  const views=entries.flatMap(expand),first=views[0];
  for(const view of views)for(const field of scalarFields){
   if(JSON.stringify(view[field]??null)!==JSON.stringify(first[field]??null))throw Error(`Cannot merge conflicting ${field}: ${first.record_id}/${first['原切片ID']}`);
  }
  const projects=new Map(),labels=new Map(),originals=new Map();
  for(const view of views){
   const pid=view.project_id;
   if(typeof pid!=='string'||!pid||/[;；]/.test(pid))throw Error('Expected one explicit project in each original view');
   const project={project_id:pid,'项目名称':view['项目名称'],'项目角色':view['项目角色']};
   if(projects.has(pid)&&JSON.stringify(projects.get(pid))!==JSON.stringify(project))throw Error('Conflicting project identity');
   projects.set(pid,project);
   const ls=parse(view['标签明细']);
   if(!Array.isArray(ls)||!ls.length)throw Error('Labeled project view has no labels');
   for(const l of ls){
    if(!l['标签路径ID'])throw Error('Label missing dictionary ID');
    if(l.project_id&&l.project_id!==pid)throw Error('Label project does not match original view');
    const annotated={...l,...project},key=JSON.stringify([pid,l['标签路径ID']]);
    if(labels.has(key)&&JSON.stringify(labels.get(key))!==JSON.stringify(annotated))throw Error('Conflicting definition for same project/tag');
    labels.set(key,annotated);
   }
   const preserved=Object.fromEntries(variantFields.map(k=>[k,k==='标签明细'||k==='项目与标签证据'?parse(view[k]):view[k]]));
   originals.set(JSON.stringify(preserved),preserved);
  }
  const merged=clone(first),ps=[...projects.values()];
  merged['切片ID']=first['原切片ID'];
  for(const field of ['project_id','项目名称','项目角色'])merged[field]=ps.map(p=>p[field]).join('；');
  merged['观点摘要']=statements(views,'观点摘要');
  merged['打标说明']=statements(views,'打标说明');
  merged['标签明细']=[...labels.values()];
  // Preserve the existing Qwen categories losslessly; this merge is not a
  // new whole-slice sentiment decision and must not pick a project's verdict.
  merged['表达类型']=words(views,'表达类型');
  merged['情绪态度']=words(views,'情绪态度');
  merged['项目与标签证据']={format:DETAIL_GRAIN,record_id:first.record_id,original_slice_ids:uniq(views.map(r=>r['原切片ID'])),
   original_view_ids:uniq(views.map(r=>r['切片ID'])),project_views:[...originals.values()],
   note:'仅合并同来源同原文范围的项目视图；项目、标签、原始证据、类别及评分未重新裁决。'};
  output.push(merged);
 }
 if(new Set(output.map(identity)).size!==output.length)throw Error('Duplicate source span survived detail merge');
 if(new Set(output.map(r=>JSON.stringify([r.record_id,r['原切片ID']]))).size!==output.length)throw Error('Duplicate original slice survived detail merge');
 return output;
}
