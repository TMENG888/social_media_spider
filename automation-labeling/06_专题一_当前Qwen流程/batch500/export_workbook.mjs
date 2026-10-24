import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const root=path.dirname(fileURLToPath(import.meta.url));
const [input,output,previewDir]=process.argv.slice(2);
const col=n=>{let s='';while(n){n--;s=String.fromCharCode(65+n%26)+s;n=Math.floor(n/26);}return s;};
const widthsFor=s=>s.headers.map(h=>{
 if(!h)return 3;
 if(h==='原文摘录')return 84;
 if(['打标说明','备注'].includes(h))return 110;
 if(['标签明细','品牌分类依据','标签品牌关联'].includes(h))return 100;
 if(['具体产品做法','创新依据','标签定义','文章标题','说明'].includes(h))return 74;
 if(['文章链接'].includes(h))return 66;
 if(h==='源表id')return 26;
 if(/unit_id|content_id|证据定位/.test(h))return 35;
 if(['项目','品牌名称','发布者角色','发布者角色分组','创新等级','经营主体','采集项目'].includes(h))return 30;
 if(/标签|方向/.test(h))return 24;
 if(h==='发布日期')return 24;
 return Math.max(15,Math.min(25,h.length*2+3));
});
const wb=Workbook.create();
if(input==='--baseline'){
 const schema=JSON.parse(await fs.readFile(path.join(root,'schema.json'),'utf8'));
 const ws=wb.worksheets.add('议题指标');ws.showGridLines=false;
 const rows=schema[0].sample.slice(0,11).map(r=>Array.from({length:19},(_,j)=>r[j]??null));
 ws.getRange('A1:S11').values=rows;ws.getRange('A1:S11').format.font={name:'Arial',size:10,color:'#202B3C'};
 widthsFor(schema[0]).forEach((w,j)=>ws.getRangeByIndexes(0,j,11,1).format.columnWidth=w);
 ws.getRange('A2').format.font={name:'Arial',size:14,bold:true};
 ws.getRange('A5:P5').format={fill:'#263B56',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:36};
 ws.getRange('G6:H11').setNumberFormat('0.00%');ws.getRange('I6:I11').setNumberFormat('0.00');
 wb.recalculate();await fs.mkdir(output,{recursive:true});
 const png=await wb.render({sheetName:'议题指标',range:'A1:L10',scale:1,format:'png'});await fs.writeFile(path.join(output,'模板预览.png'),new Uint8Array(await png.arrayBuffer()));
 process.exit(0);
}
const plan=JSON.parse(await fs.readFile(input,'utf8'));
await fs.mkdir(previewDir,{recursive:true});
for(const [index,s] of plan.sheets.entries()){
 const ws=wb.worksheets.add(s.name);ws.showGridLines=false;
 const n=s.rows.length,last=col(s.headers.length),end=n+5;
 ws.getRange(`A1:${last}${end}`).format={font:{name:'Arial',size:10,color:'#202B3C'},verticalAlignment:'center',rowHeight:25};
 ws.getRange('A2').values=[[s.name]];ws.getRange('A2').format.font={name:'Arial',size:14,bold:true};
 ws.getRange('A3').writeValues([s.top||[s.name==='项目平台文章评论统计'?'采集项目是源表专题；本批只处理文章，评论为0。':`专题一${plan.model}${plan.delivery_kind==='10篇试标'?'试标':plan.delivery_kind==='批量'?'批量':'回归集'+plan.batch}，${plan.source_count}篇文章`]]);
 const mainCols=s.notes.length?s.headers.indexOf(null):s.headers.length;
 ws.getRange(`A5:${col(mainCols)}${end}`).values=[s.headers.slice(0,mainCols),...s.rows.map(r=>Array.from({length:mainCols},(_,j)=>r[j]??null))];
 ws.getRange(`A5:${col(mainCols)}5`).format={fill:'#263B56',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},horizontalAlignment:'center',verticalAlignment:'center',wrapText:true,rowHeight:40};
 const widths=widthsFor(s);widths.forEach((w,j)=>ws.getRangeByIndexes(4,j,n+1,1).format.columnWidth=w);
 if(s.notes.length){
  ws.getRange('K5:L5').values=[['指标','统计口径']];ws.getRange('K5:L5').format={fill:'#263B56',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:40};
  ws.getRange('K6').writeValues(s.notes);ws.getRange(`K6:L${s.notes.length+5}`).format.wrapText=false;
  ws.getRange(`K5:K${s.notes.length+5}`).format.columnWidth=18;ws.getRange(`L5:L${s.notes.length+5}`).format.columnWidth=95;
 }
 ws.getRange(`A6:${col(mainCols)}${end}`).format.wrapText=true;
 // Match template numeric conventions and retain identifiers as text.
 s.headers.slice(0,mainCols).forEach((h,j)=>{
  const rg=ws.getRangeByIndexes(5,j,n,1);
  if(/覆盖率|浓度/.test(h))rg.setNumberFormat('0.00%');
  else if(h==='热度指数'||h==='议题热度')rg.setNumberFormat('0.00');
  else if(/数$|证据序号|起点|终点|原编号/.test(h))rg.setNumberFormat('0');
  else if(/[Ii][Dd]$|字典ID|源表id/.test(h))rg.setNumberFormat('@');
  if(/覆盖率|浓度|热度|指数|数$|起点|终点/.test(h)&&!/来源$/.test(h))rg.format.horizontalAlignment='right';
 });
 if(s.name==='产品信息单元'){
  s.rows.forEach((r,i)=>{
   const lines=Math.max(...r.map((v,j)=>String(v??'').split('\n').reduce((sum,line)=>sum+Math.max(1,Math.ceil([...line].reduce((k,c)=>k+(c.charCodeAt(0)>255?2:1),0)/Math.max(10,widths[j]-2))),0)));
   ws.getRange(`A${i+6}:${last}${i+6}`).format.rowHeight=Math.min(409,Math.max(60,lines*14+12));
  });
  ws.getRange(`A6:${last}${end}`).format.verticalAlignment='top';
 }
 if(s.name==='专题一标签体系')ws.getRange(`A6:${last}${end}`).format.rowHeight=65;
 ws.tables.add(`A5:${col(mainCols)}${end}`,true,`Topic1Delivery${index}`);
 ws.freezePanes.freezeRows(5);
 console.log('Built',s.name,n);
}
wb.recalculate();
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},maxChars:1200})).ndjson);
console.log((await wb.inspect({kind:'table',range:'议题指标!G5:I9',include:'values,formulas',tableMaxRows:5,tableMaxCols:3,maxChars:1000})).ndjson);
for(const s of plan.sheets){
 const ws=wb.worksheets.getItem(s.name),cols=s.notes.length?s.headers.indexOf(null):s.headers.length;
 const values=ws.getRange(`A6:${col(cols)}${s.rows.length+5}`).values;
 assert.equal(values.length,s.rows.length);
 for(let i=0;i<s.rows.length;i++)for(let j=0;j<cols;j++){
  const v=s.rows[i][j],got=values[i][j];
  if(v==null||v==='')assert(got==null||got==='');else assert.equal(got,v,`${s.name}:${i}:${j}`);
 }
 const rg=s.name==='产品信息单元'?'D5:I7':s.name==='专题一标签体系'?'C5:J8':s.name==='品牌发布者角色指标'?'A5:L9':`A1:${col(Math.min(cols,12))}10`;
 const png=await wb.render({sheetName:s.name,range:rg,scale:1,format:'png'});
 await fs.writeFile(path.join(previewDir,s.name+'.png'),new Uint8Array(await png.arrayBuffer()));
}
for(const [name,range] of [['产品标签与做法','J5:P7'],['产品指标与来源','Q5:AB7']]){
 const png=await wb.render({sheetName:'产品信息单元',range,scale:1,format:'png'});await fs.writeFile(path.join(previewDir,name+'.png'),new Uint8Array(await png.arrayBuffer()));
}
await fs.mkdir(path.dirname(output),{recursive:true});
await(await SpreadsheetFile.exportXlsx(wb)).save(output);
await fs.writeFile(path.join(previewDir,'receipt.json'),JSON.stringify({model:plan.model,output,sheets:plan.sheets.map(s=>({name:s.name,rows:s.rows.length})),source_count:plan.source_count,unit_count:plan.unit_count,partition_count:plan.partition_count,input_sha256:plan.input_sha256,annotation_sha256:plan.annotation_sha256},null,2));
console.log('EXPORTED',output);
