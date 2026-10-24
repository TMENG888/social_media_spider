import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const dep=process.env.ARTIFACT_NODE_MODULES||'C:/Users/YS-Insight/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const require=createRequire(path.join(dep,'../artifact_loader.cjs'));
const {Workbook,SpreadsheetFile,FileBlob}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const input=process.argv[2],output=process.argv[3];
if(!input||!output)throw Error('Usage: node export_delivery_v4.mjs delivery_results.json output.xlsx');
const p=JSON.parse(await fs.readFile(input,'utf8'));const wb=Workbook.create();const verification=[];
const finalOnly=process.argv.includes('--two-tables');const s=p.summary;const previews=[];
const outDir=path.dirname(output);await fs.mkdir(outDir,{recursive:true});
const supportDir=path.join(outDir,path.basename(output,'.xlsx')+'_核验');await fs.mkdir(supportDir,{recursive:true});
const column=i=>{let s='',n=i+1;while(n){s=String.fromCharCode(65+(n-1)%26)+s;n=Math.floor((n-1)/26)}return s};
const text=v=>v==null?null:typeof v==='object'?JSON.stringify(v):typeof v==='string'&&v.startsWith('=')?"'"+v:v;
function addTable(sheet,rows,headers,start=1){
 const cell=(v,h)=>{
  if(h==='发布日期'&&typeof v==='string'){
   const m=v.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$/);
   if(m){
    const stamp=Date.UTC(+m[1],+m[2]-1,+m[3],+(m[4]||0),+(m[5]||0),+(m[6]||0)),date=new Date(stamp);
    // Do not normalize impossible source dates into a fabricated valid date.
    if(date.getUTCFullYear()===+m[1]&&date.getUTCMonth()===+m[2]-1&&date.getUTCDate()===+m[3]
       &&+(m[4]||0)<24&&+(m[5]||0)<60&&+(m[6]||0)<60)return stamp/86400000+25569;
   }
  }
  return text(v);
 };
 const matrix=[headers,...rows.map(r=>headers.map(h=>cell(r[h],h)))];const last=start+rows.length,end=column(headers.length-1);
 sheet.getRange(`A${start}:${end}${last}`).values=matrix;
 sheet.getRange(`A${start}:${end}${last}`).format={font:{name:'Arial',size:10,color:'#243447'},verticalAlignment:'top',wrapText:true,rowHeightPx:40};
 const widths=headers.map(h=>h==='标签明细'||/校验|confidence|标签证据|模型输出|排除校验|末轮|原始标签选择|覆盖审核/.test(h)?(finalOnly?1800:1300):/打标说明|备注|审核原因|原因/.test(h)?(finalOnly?1200:850):/原文|摘录|摘要|做法|审计内容|说明|机制|验证|排除单元追溯|变更候选/.test(h)?(finalOnly?900:650):/专题|项目名称|ID|id|主键/.test(h)?235:150);
 headers.forEach((h,c)=>{const col=sheet.getRangeByIndexes(start-1,c,matrix.length,1);col.format.columnWidthPx=widths[c];
  if(rows.length&&/ID|id|主键/.test(h))sheet.getRangeByIndexes(start,c,rows.length,1).setNumberFormat('@');
  if(rows.length&&/指数|费用/.test(h)&&!/数$/.test(h)){
   sheet.getRangeByIndexes(start,c,rows.length,1).setNumberFormat(finalOnly?'0.00':'0.000000');
   sheet.getRangeByIndexes(start,c,rows.length,1).format.horizontalAlignment='right';
  }
  else if(rows.length&&h==='发布日期')sheet.getRangeByIndexes(start,c,rows.length,1).setNumberFormat('yyyy-mm-dd');
  else if(rows.length&&/数$|序号|Token/.test(h)&&!/ID|id|主键/.test(h))sheet.getRangeByIndexes(start,c,rows.length,1).setNumberFormat('#,##0');
 });
 // Full cell contents remain available; extreme audit payloads use edit bar/JSON.
 for(let r=1;r<matrix.length;r++){
  let lines=2;matrix[r].forEach((v,c)=>{lines=Math.max(lines,String(v??'').split('\n').reduce((n,t)=>n+Math.max(1,Math.ceil(t.length/Math.floor(widths[c]/14))),0))});
  sheet.getRangeByIndexes(start+r-1,0,1,headers.length).format.rowHeightPx=Math.min(540,lines*(finalOnly?22:17)+(finalOnly?22:14));
 }
 if(rows.length){const t=sheet.tables.add(`A${start}:${end}${last}`,true,'DeliveryTable'+verification.length);t.style='TableStyleMedium2';}
 sheet.getRange(`A${start}:${end}${start}`).format={fill:'#17365D',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeightPx:44,horizontalAlignment:'center',wrapText:true};
 sheet.showGridLines=false;verification.push({sheet:sheet.name,range:`A${start}:${end}${last}`,matrix});
 if(headers.includes('验收状态')&&rows.length){const c=headers.indexOf('验收状态');sheet.getRangeByIndexes(start,c,rows.length,1).conditionalFormats.add('containsText',{text:'需人工审核',format:{fill:'#FFF2CC',font:{color:'#9C5700'}}});}
 if(headers.includes('人工审核结果')&&rows.length){const c=headers.indexOf('人工审核结果');sheet.getRangeByIndexes(start,c,rows.length,1).dataValidation={rule:{type:'list',values:['待审核','通过','修改后通过','剔除','暂无法判断']}};
  for(const h of ['人工审核结果','修改后标签明细','修改后摘要或做法','复核人','复核时间'])sheet.getRangeByIndexes(start,headers.indexOf(h),rows.length,1).format.fill='#FFF2CC';
 }
 return {headers,last};
}
if(!finalOnly){
const overview=wb.worksheets.add('测试汇总');overview.showGridLines=false;
overview.getRange('A2').values=[['两专题切片打标与验收测试']];overview.getRange('A2').format.font={name:'Arial',size:14,bold:true,color:'#17365D'};
const summary=[['模式',s.pipeline || (s.mode==='api'?'真实API生成＋独立语义校验':'离线规则候选，不是模型打标')],['处理文章数',s.processed_articles],['处理评论数',s.processed_comments],
 ['产品信息单元数',s.product_units],['文章观点单元数',s.article_view_units],['评论观点单元数',s.comment_view_units],['机器自动通过数',s.automatic_pass],['需人工审核单元数',s.human_review],
 ['未完成文档数',s.incomplete_documents],['累计逻辑请求数',s.cumulative_logical_calls],['本次新增逻辑请求数',s.new_logical_calls],['总Token',s.tokens],['累计已知估算费用（元）',s.estimated_yuan],
 ['未知usage或价格请求数',s.unknown_usage_or_price_calls],['平均每文章Token',s['文章平均Token']],['平均每评论Token',s['评论平均Token']],
 ['平均每文章已知估算费用（元）',s['文章平均已知估算费用元']],['平均每评论已知估算费用（元）',s['评论平均已知估算费用元']],
 ['含前期冒烟的全部请求数',s.folder_all_versions_calls],['含前期冒烟的全部Token',s.folder_all_versions_tokens],['含前期冒烟的已知估算费用（元）',s.folder_all_versions_estimated_yuan],
 ['含前期冒烟的未知费用请求数',s.folder_all_versions_unknown_price_calls],
 ['验收边界',s.note],['价格口径',p.price_note],['审计查看','主表原文与标签JSON不截断；长审计仅展示概要，完整内容见配套原始JSON。']].map(([项目,结果])=>({项目,结果}));
if(s.mapping_contract)summary.push({项目:'评论映射口径',结果:s.mapping_contract});
if(s['指定样例API请求数'])summary.push({项目:'指定样例独立请求数',结果:s['指定样例API请求数']},{项目:'指定样例已知估算费用（元）',结果:s['指定样例已知费用元']},{项目:'指定样例边界',结果:s['指定样例说明']});
try{const q=JSON.parse(await fs.readFile(path.join(path.dirname(input),'quality_diagnostics.json'),'utf8'));
 summary.splice(8,0,...[['无有效标签、仍需审核单元数',q.no_valid_label_units],['待转写产品做法单元数',q.empty_product_practice],['待生成观点摘要单元数',q.empty_view_summary],['一片多标签单元数',q.multi_label_units]].map(([项目,结果])=>({项目,结果})));
}catch(e){if(e.code!=='ENOENT')throw e;}
addTable(overview,summary,['项目','结果'],4);overview.getRange(`A4:A${summary.length+4}`).format.columnWidthPx=320;overview.getRange(`B4:B${summary.length+4}`).format.columnWidthPx=780;
summary.forEach((r,i)=>{const row=i+5;overview.getRange(`A${row}:B${row}`).format.rowHeightPx=Math.max(36,Math.ceil(String(r.结果??'').length/55)*17+14);
 if(typeof r.结果==='number')overview.getRange(`B${row}`).setNumberFormat(/费用/.test(r.项目)?'0.000000':/平均/.test(r.项目)?'#,##0.0':'#,##0');
});
previews.push(['测试汇总','A2:B13']);
}
for(const [name,rows] of Object.entries(p.tables)){
 if(finalOnly&&!['产品信息单元','观点信息单元'].includes(name))continue;
 const sheet=wb.worksheets.add(name);const headers=p.schemas[name]||[...new Set(rows.flatMap(r=>Object.keys(r)))];
 addTable(sheet,rows,headers.length?headers:['说明']);sheet.freezePanes.freezeRows(1);sheet.freezePanes.freezeColumns(finalOnly?2:name==='观点信息单元'?4:2);
 if(!rows.length){sheet.getRange('A3').values=[['当前测试没有此类记录；不是未执行的空白模板。']];}
 let range='A1:'+column(Math.min(headers.length-1,5))+'3';
 if(name==='产品信息单元')range=finalOnly?'K1:K3':'J1:L3';
 if(name==='观点信息单元')range=finalOnly?'N1:N3':'K1:P3';
 if(name==='人工审核')range='B1:D3';
 if(name==='长审计续页')range='E1:H3';
 if(!finalOnly)previews.push([name,range]);
 if(finalOnly&&name==='产品信息单元')previews.push([name,'A1:E3'],[name,'J1:L3'],[name,'R1:S3']);
 if(finalOnly&&name==='观点信息单元')previews.push([name,'A1:D3'],[name,'J1:M3'],[name,'S1:T3']);
}
// Source invariants and exact eight-key tag contract, independent of model status.
const tagKeys=['标签路径ID','标签编号','一级标签','二级标签','三级标签','四级标签','五级标签','标签强调方向'];
const units=[...p.tables['产品信息单元'],...p.tables['观点信息单元']];
for(const u of units){
 const t=p.tables['来源追溯'].find(t=>t.unit_id===u.unit_id);if(!t)throw Error('Missing source trace');
 const r=p.results.find(r=>r.document.record_id===t.record_id);if(!r)throw Error('Missing source document');
 if(Array.from(r.document.text).slice(t['起点'],t['终点']).join('')!==t['原文证据'])throw Error('Evidence mismatch');
 const mappedExpected=(s.version?.startsWith('delivery-v5.1')||s.version?.startsWith('delivery-v6')||s.version?.startsWith('delivery-v7')||s.version?.startsWith('delivery-v8')||s.version?.startsWith('delivery-v11')||s.version?.startsWith('delivery-v76'))?(r.document.row['文章id']||null):t['所属文章ODS主键'];
 if(u['来源类型']==='评论'&&(u['映射文章id']!==mappedExpected||u['原始摘录']!==r.document.text))throw Error('Comment mapping/slicing mismatch');
 if(u['来源类型']==='文章'&&u['映射文章id']!=null)throw Error('Article should not carry mapping ID');
 for(const tag of u['标签明细'])if(JSON.stringify(Object.keys(tag))!==JSON.stringify(tagKeys))throw Error('Tag JSON keys differ');
}
wb.recalculate();console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#SPILL!',options:{useRegex:true,maxResults:10},maxChars:500})).ndjson);
for(const [name,range] of previews){const png=await wb.render({sheetName:name,range,scale:1,format:'png'});await fs.writeFile(path.join(supportDir,'v4_'+name+'_'+range.replace(':','_')+'.png'),new Uint8Array(await png.arrayBuffer()));}
await(await SpreadsheetFile.exportXlsx(wb)).save(output);
const saved=await SpreadsheetFile.importXlsx(await FileBlob.load(output));
for(const v of verification){const actual=saved.worksheets.getItem(v.sheet).getRange(v.range).values;for(let r=0;r<v.matrix.length;r++)for(let c=0;c<v.matrix[r].length;c++){const a=v.matrix[r][c],b=actual[r][c];if(a!==b&&!((a==null||a==='')&&(b==null||b==='')))throw Error('Export altered value '+v.sheet+' '+r+' '+c);}}
await fs.writeFile(path.join(supportDir,'export_v4_verification.json'),JSON.stringify({output,verifiedTables:verification.length,summary:s},null,2));
console.log(JSON.stringify({output,verifiedTables:verification.length}));
// Some desktop hosts report a native cleanup failure after successful export.
process.exit(0);
