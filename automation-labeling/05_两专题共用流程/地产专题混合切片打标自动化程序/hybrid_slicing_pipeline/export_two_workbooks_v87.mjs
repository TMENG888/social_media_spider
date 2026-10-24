import fs from 'node:fs/promises';
import path from 'node:path';
import {Workbook,SpreadsheetFile,FileBlob} from '@oai/artifact-tool';
const [input,outputDir]=process.argv.slice(2);if(!input||!outputDir)throw Error('payload.json outputDir required');
const p=JSON.parse(await fs.readFile(input,'utf8'));const wb=Workbook.create();const expected=[];let tableId=0;
await fs.mkdir(outputDir,{recursive:true});const qa=path.join(outputDir,p.main_name+'_核验');await fs.mkdir(qa,{recursive:true});
const col=i=>{let s='',n=i+1;while(n){s=String.fromCharCode(65+(n-1)%26)+s;n=Math.floor((n-1)/26)}return s;};
function cell(value,header){
 if(value==null)return null;
 if(header==='发布日期'&&typeof value==='string'){
  const m=value.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$/);
  if(m){let n=Date.UTC(+m[1],+m[2]-1,+m[3],+(m[4]||0),+(m[5]||0),+(m[6]||0));let d=new Date(n);
   if(d.getUTCFullYear()===+m[1]&&d.getUTCMonth()===+m[2]-1&&d.getUTCDate()===+m[3])return n/86400000+25569;
  }
 }
 let v=typeof value==='object'?JSON.stringify(value):value;
 if(typeof v==='string'&&v.length>32767)throw Error('Cell exceeds Excel limit: '+header);
 return typeof v==='string'&&v.startsWith('=')?"'"+v:v;
}
function table(name,rows,headers,start=1,explicitName=null){
 const s=wb.worksheets.add(name);s.showGridLines=false;
 const matrix=[headers,...rows.map(r=>headers.map(h=>cell(r[h],h)))],end=col(headers.length-1),last=start+rows.length;
 const range=`A${start}:${end}${last}`;s.getRange(range).values=matrix;
 s.getRange(range).format={font:{name:'Arial',size:10,color:'#243447'},wrapText:true,verticalAlignment:'top',rowHeightPx:38};
 const widths=headers.map(h=>h==='本轮项目归属核查'?1200:h==='命中核心字眼'||h==='联合命中核心字眼'?680:h==='关键词规则版本'||h==='补标方法'||h==='对象绑定方式'?250:h==='标签强调方向'||h==='专题标签词'?350:/标签明细/.test(h)?1400:/原文|摘录|原始主体/.test(h)?680:/打标说明|待审原因|备注|排除原因/.test(h)?800:/摘要|产品做法/.test(h)?570:/record_id|unit_id|content_id|主键|文章id|源表id|来源标签ID/.test(h)?250:/联合.*数|仅标签/.test(h)?200:/项目|平台|来源类型|主体字段|验收状态|内容类型/.test(h)?190:/Token|计.*数|费用|范围内|交付.*数|来源数/.test(h)?155:125);
 headers.forEach((h,c)=>{
  s.getRangeByIndexes(start-1,c,matrix.length,1).format.columnWidthPx=widths[c];
  if(rows.length){const r=s.getRangeByIndexes(start,c,rows.length,1);
   if(/_id|主键|文章id|源表id/.test(h))r.setNumberFormat('@');
   else if(h==='发布日期')r.setNumberFormat('yyyy-mm-dd');
   else if(/指数/.test(h))r.setNumberFormat('0.00');
   else if(/费用/.test(h))r.setNumberFormat('0.000000');
   else if(/数$|Token|序号|起点|终点/.test(h))r.setNumberFormat('#,##0');
   r.format.horizontalAlignment=/数$|指数|费用|Token|起点|终点|序号/.test(h)?'right':'left';
  }
 });
 for(let r=1;r<matrix.length;r++){
  const lines=Math.max(2,...matrix[r].map((v,c)=>String(v??'').split('\n').reduce((n,t)=>n+Math.max(1,Math.ceil(t.length/(widths[c]/14))),0)));
  s.getRangeByIndexes(start+r-1,0,1,headers.length).format.rowHeightPx=Math.min(540,lines*18+14);
 }
 s.getRange(`A${start}:${end}${start}`).format={fill:'#17365D',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeightPx:48,horizontalAlignment:'center',verticalAlignment:'center',wrapText:true};
 if(rows.length)s.tables.add(range,true,explicitName||'Delivery'+(++tableId)).style='TableStyleMedium2';
 s.freezePanes.freezeRows(start);if(name===p.main_name)s.freezePanes.freezeColumns(2);
 if(headers.includes('验收状态')&&rows.length)s.getRangeByIndexes(start,headers.indexOf('验收状态'),rows.length,1).conditionalFormats.add('containsText',{text:'需人工审核',format:{fill:'#FFF2CC',font:{color:'#9C5700'}}});
 if(headers.includes('人工审核结果')&&rows.length){
  s.getRangeByIndexes(start,headers.indexOf('人工审核结果'),rows.length,1).dataValidation={rule:{type:'list',values:['待审核','通过','修改后通过','排除','无法判断']}};
  for(const h of ['人工审核结果','修改后标签明细','修改后摘要或做法','复核人','复核时间'])s.getRangeByIndexes(start,headers.indexOf(h),rows.length,1).format.fill='#FFF2CC';
 }
 expected.push({name,range,matrix});return s;
}
const main=table(p.main_name,p.tables[p.main_name],p.schemas[p.main_name]);main.tabColor='#17365D';
const referenceName=Object.keys(p.tables).find(name=>/^专题[一二]标签体系$/.test(name));
if(referenceName){
 const reference=table(referenceName,p.tables[referenceName],p.schemas[referenceName],5,p.main_name==='产品信息单元'?'ProductLabelReference':'OpinionLabelReference');reference.tabColor='#537595';
 reference.getRange('A2').values=[[referenceName]];reference.getRange('A2').format={font:{name:'Arial',size:14,bold:true,color:'#17365D'},wrapText:false};
 reference.getRange('A3').values=[[`来源：${p.reference_source.file}，${p.reference_source.sheet}。原表行用于定位；标签路径ID沿用全字典行序。`]];
 reference.getRange('A3').format={font:{name:'Arial',size:10,color:'#526171'},wrapText:false};
 reference.getRange('O2').values=[['专题适用规则']];reference.getRange('O3').values=[[p.reference_source.topic_rule]];
 reference.getRange('O2:O3').format={font:{name:'Arial',size:10,color:'#526171'},wrapText:false,columnWidthPx:1000};
}
const statsRows=p.tables['测试渠道统计'];const statsHeaders=Object.keys(statsRows[0]);
const stats=table('测试渠道统计',statsRows,statsHeaders,5);
stats.getRange('A2').values=[['测试渠道统计']];stats.getRange('A2').format.font={name:'Arial',size:14,bold:true,color:'#17365D'};
stats.getRange('M2').values=[['统计口径']];stats.getRange('M2').format.font={name:'Arial',size:10,bold:true,color:'#17365D'};
for(let i=0;i<p.notes.length;i++){stats.getRange(`M${i+3}`).values=[[p.notes[i]]];stats.getRange(`M${i+3}`).format={font:{name:'Arial',size:10,color:'#526171'},wrapText:false,columnWidthPx:1150};}
for(const [name,rows] of Object.entries(p.tables)){
 if([p.main_name,'测试渠道统计',referenceName].includes(name))continue;
 const headers=[...new Set(rows.flatMap(r=>Object.keys(r)))];table(name,rows,headers.length?headers:['说明']);
}
const sourceRows=p.tables['源记录与文章关联'],sourceHeaders=Object.keys(sourceRows[0]);
const src=(h)=>`'源记录与文章关联'!$${col(sourceHeaders.indexOf(h))}$2:$${col(sourceHeaders.indexOf(h))}$${sourceRows.length+1}`;
for(let i=0;i<statsRows.length;i++){
 const r=i+6;const clauses=`${src('平台')},B${r},${src('来源类型')},C${r},${src('内容类型')},D${r}`;
 const f={
  '范围内行数':`=COUNTIFS(${clauses})`,
  '热度可计算数':`=COUNTIFS(${clauses},${src('热度指数')},"<>")`,
  '互动可计算数':`=COUNTIFS(${clauses},${src('互动深度指数')},"<>")`,
  '有交付单元来源数':`=COUNTIFS(${clauses},${src('交付单元数')},">0")`,
  '交付单元数':`=SUMIFS(${src('交付单元数')},${clauses})`,
  '未完成来源数':`=COUNTIFS(${clauses},${src('处理状态')},"<>已完成")`,
 };
 for(const [h,formula] of Object.entries(f))stats.getRange(`${col(statsHeaders.indexOf(h))}${r}`).formulas=[[formula]];
}
wb.recalculate();
for(const sheet of expected){
 const actual=wb.worksheets.getItem(sheet.name).getRange(sheet.range).values;
 for(let r=0;r<sheet.matrix.length;r++)for(let c=0;c<sheet.matrix[r].length;c++){
  const a=sheet.matrix[r][c],b=actual[r][c];if(a!==b&&!((a==null||a==='')&&(b==null||b==='')))throw Error(`Calculated value mismatch ${sheet.name} row ${r} col ${c}: ${a} != ${b}`);
 }
}
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#SPILL!',options:{useRegex:true,maxResults:10},maxChars:800})).ndjson);
for(const sh of expected){
 if(referenceName&&!p.filename.includes('全字典补选')&&!p.filename.includes('500篇')&&![referenceName,p.main_name,'测试渠道统计'].includes(sh.name))continue;
 let range=sh.name===referenceName?'H5:J8':sh.name==='测试渠道统计'?'A2:G15':sh.name===p.main_name?(p.main_name==='产品信息单元'?'J1:M3':'M1:O3'):'A1:D3';
 const blob=await wb.render({sheetName:sh.name,range,scale:1,format:'png'});await fs.writeFile(path.join(qa,sh.name+'.png'),new Uint8Array(await blob.arrayBuffer()));
}
if(referenceName){
 const blob=await wb.render({sheetName:referenceName,range:'A2:D8',scale:1,format:'png'});
 await fs.writeFile(path.join(qa,'标签字典来源与路径.png'),new Uint8Array(await blob.arrayBuffer()));
 const emphasisColumn=col(p.schemas[p.main_name].indexOf('标签强调方向'));
 const shortRows=p.tables[p.main_name].map((r,i)=>[r['标签强调方向']?.length||0,i+2]).filter(([n])=>n>0&&n<65).slice(0,3).map(([,r])=>r);
 for(const row of shortRows){
  const blob=await wb.render({sheetName:p.main_name,range:`${emphasisColumn}1:${emphasisColumn}${row}`,scale:1,format:'png'});
  await fs.writeFile(path.join(qa,`标签强调方向_${row}.png`),new Uint8Array(await blob.arrayBuffer()));
 }
}
if(p.main_name==='观点信息单元'&&p.filename.includes('项目上下文')){
 const blob=await wb.render({sheetName:p.main_name,range:'E10:G12',scale:1,format:'png'});
 await fs.writeFile(path.join(qa,'项目归属修复.png'),new Uint8Array(await blob.arrayBuffer()));
}
if(p.filename.includes('关键词兜底')||p.filename.includes('切片标签联合')){
 const joint=p.filename.includes('切片标签联合');
 const changes=p.tables['标签补选与纠错'].filter(e=>e['处理']===(joint?'联合关键词规则直接补标':'关键词规则直接补标'));
 const changedIds=[...new Set(changes.map(e=>e.unit_id))].slice(0,2);
 const tagCol=col(p.schemas[p.main_name].indexOf('标签明细'));
 const lastCol=col(p.schemas[p.main_name].indexOf(p.main_name==='产品信息单元'?'具体产品做法':'观点摘要'));
 for(const uid of changedIds){
  const row=p.tables[p.main_name].findIndex(e=>e.unit_id===uid)+2;
  const preview=await wb.render({sheetName:p.main_name,range:`${tagCol}${row}:${lastCol}${row}`,scale:1,format:'png'});
  await fs.writeFile(path.join(qa,`关键词新增_${row}.png`),new Uint8Array(await preview.arrayBuffer()));
 }
 const auditHeaders=[...new Set(p.tables['标签补选与纠错'].flatMap(r=>Object.keys(r)))];
 const first=p.tables['标签补选与纠错'].findIndex(e=>e['处理']===(joint?'联合关键词规则直接补标':'关键词规则直接补标'))+2;
 const startCol=col(auditHeaders.indexOf('处理'));const quoteCol=col(auditHeaders.indexOf('属性证据'));
 if(first>1){
  const preview=await wb.render({sheetName:'标签补选与纠错',range:`${startCol}${first}:${quoteCol}${first}`,scale:1,format:'png'});
  await fs.writeFile(path.join(qa,'关键词直接补标记录.png'),new Uint8Array(await preview.arrayBuffer()));
 }
 for(const name of ['补选覆盖记录','同批测试对照','本轮补选Token费用']){
  const sh=expected.find(e=>e.name===name);
  const firstCol=name==='补选覆盖记录'?Math.max(0,sh.matrix[0].indexOf(joint?'联合检查单元数':'关键词检查单元数')):0;
  const finalCol=name==='补选覆盖记录'?sh.matrix[0].length-1:Math.min(sh.matrix[0].length-1,7);
  const preview=await wb.render({sheetName:name,range:`${col(firstCol)}1:${col(finalCol)}${Math.min(sh.matrix.length,3)}`,scale:1,format:'png'});
  await fs.writeFile(path.join(qa,name+'_本轮.png'),new Uint8Array(await preview.arrayBuffer()));
 }
}
const output=path.join(outputDir,p.filename);await(await SpreadsheetFile.exportXlsx(wb)).save(output);
const saved=await SpreadsheetFile.importXlsx(await FileBlob.load(output));
for(const sh of expected){
 const actual=saved.worksheets.getItem(sh.name).getRange(sh.range).values;
 for(let r=0;r<sh.matrix.length;r++)for(let c=0;c<sh.matrix[r].length;c++){
  const a=sh.matrix[r][c],b=actual[r][c];if(a!==b&&!((a==null||a==='')&&(b==null||b==='')))throw Error(`Export mismatch ${sh.name} ${r}:${c}`);
 }
}
await fs.writeFile(path.join(qa,'export_verification.json'),JSON.stringify({output,verifiedSheets:expected.length,mainRows:p.tables[p.main_name].length,summary:p.summary},null,2));
console.log(JSON.stringify({output,verifiedSheets:expected.length,summary:p.summary}));process.exit(0);
