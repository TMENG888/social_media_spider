import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
import {layout,col,schema} from './topic2_workbook_layout_v108.mjs';
const [input,output,dependencyRoot,previewDir]=process.argv.slice(2);
if(!input||!output||!dependencyRoot)throw Error('Usage: node export_topic2_v108.mjs payload.json output.xlsx bundled_node_modules [preview_dir]');
const require=createRequire(path.join(dependencyRoot,'__topic2_resolver__.cjs'));
const {Workbook,SpreadsheetFile}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const data=JSON.parse(await fs.readFile(input,'utf8')),plan=layout(data);
const detail=plan.sheets.find(s=>s.name==='打标明细');
const detailIdentities=new Set(detail.rows.map(r=>JSON.stringify([r[1],r[21]])));
assert.equal(detailIdentities.size,detail.rows.length,'Duplicate source/slice in final delivery');
const wb=Workbook.create(),sheets=new Map(plan.sheets.map(s=>[s.name,wb.worksheets.add(s.name)]));
for(const [i,s]of plan.sheets.entries()){
 const ws=sheets.get(s.name),last=col(s.headers.length),end=Math.max(6,s.end);
 ws.showGridLines=false;
 ws.getRange(`A1:${last}${end}`).format.font={name:'Arial',size:11,color:'#24364A'};
 ws.getRange('A2').values=[[s.name]];ws.getRange('A2').format.font={name:'Arial',size:16,bold:true};
 if(data.partial_not_delivery)ws.getRange('A3').values=[['缓存回放结构测试，非本次新完成1000条交付。']];
 ws.getRange('A5').writeValues([s.headers,...s.rows]);
 ws.getRange(`A5:${last}5`).format={fill:'#284A6C',font:{name:'Arial',size:11,bold:true,color:'#FFFFFF'},horizontalAlignment:'center',verticalAlignment:'center',wrapText:true,rowHeight:38};
 ws.getRange(`A6:${last}${end}`).format={wrapText:true,verticalAlignment:'top',rowHeight:28};
 s.widths.forEach((w,j)=>ws.getRangeByIndexes(4,j,end-4,1).format.columnWidth=w);
 if(s.rows.length){
  ws.tables.add(`A5:${last}${s.end}`,true,`Topic2Final${i}`);
  for(const j of s.textColumns)ws.getRange(`${col(j+1)}6:${col(j+1)}${s.end}`).setNumberFormat('@');
  for(const j of s.dateColumns)ws.getRange(`${col(j+1)}6:${col(j+1)}${s.end}`).setNumberFormat('yyyy-mm-dd');
  s.headers.forEach((h,j)=>{if(/情绪评分|热度指数|议题热度/.test(h))ws.getRange(`${col(j+1)}6:${col(j+1)}${s.end}`).setNumberFormat('0.00');});
  ws.getRange(`A6:${last}${s.end}`).format.autofitRows();
 }
 if(s.side_headers.length){
  const start=s.headers.length+2,sideLast=col(start+s.side_headers.length-1),sideEnd=5+s.side_rows.length;
  ws.getRange(`${col(start)}5`).writeValues([s.side_headers,...s.side_rows]);
  ws.getRange(`${col(start)}5:${sideLast}5`).format={fill:'#284A6C',font:{name:'Arial',size:11,bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:38};
  s.side_widths.forEach((w,j)=>ws.getRangeByIndexes(4,start+j-1,Math.max(1,sideEnd-4),1).format.columnWidth=w);
  if(s.side_rows.length)ws.getRange(`${col(start)}6:${sideLast}${sideEnd}`).format={wrapText:true,verticalAlignment:'top'};
 }
 if(s.metricFormulas?.length){ws.getRange(`G6:J${s.end}`).formulas=s.metricFormulas;ws.getRange(`G6:G${s.end}`).setNumberFormat('0.0%');ws.getRange(`H6:I${s.end}`).setNumberFormat('0.00');ws.getRange(`J6:J${s.end}`).setNumberFormat('0');}
 ws.freezePanes.freezeRows(5);
}
wb.recalculate();
for(const s of plan.sheets.filter(s=>s.metricValues)){
 const values=sheets.get(s.name).getRange(`G6:J${s.end}`).values;
 s.metricValues.forEach((r,i)=>r.forEach((v,j)=>{const got=values[i][j];if(v===null)assert(got===null||got==='');else assert(Math.abs(got-v)<1e-8,`${s.name} ${i} ${j}: ${got} != ${v}`);}));
}
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},maxChars:1800});
console.log(errors.ndjson);
if(previewDir){await fs.mkdir(previewDir,{recursive:true});for(const s of plan.sheets){const range=s.name==='打标明细'?'T5:W8':`A1:${col(Math.min(8,s.headers.length))}8`;await fs.writeFile(path.join(previewDir,s.name+'.png'),new Uint8Array(await(await wb.render({sheetName:s.name,range,scale:1,format:'png'})).arrayBuffer()));}}
await fs.mkdir(path.dirname(output),{recursive:true});await(await SpreadsheetFile.exportXlsx(wb)).save(output);
await fs.writeFile(output+'.schema.json',JSON.stringify({input_file:path.resolve(input),schema_version:schema.version,detail_grain:plan.detail_grain,input_project_views:data.units.length,unique_detail_rows:detail.rows.length,duplicate_detail_rows:detail.rows.length-detailIdentities.size,sheets:plan.sheets.map(s=>({name:s.name,headers:s.headers,side_headers:s.side_headers,rows:s.rows.length})),source_count:data.total_sources,partial_not_delivery:data.partial_not_delivery??false},null,2));
console.log(JSON.stringify({output,sheets:plan.sheets.length,detail_fields:23,schema_version:schema.version}));
