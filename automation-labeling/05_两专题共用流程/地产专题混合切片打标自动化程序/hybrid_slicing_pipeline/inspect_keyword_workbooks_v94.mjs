import fs from 'node:fs/promises';
import path from 'node:path';
import {SpreadsheetFile,FileBlob} from '@oai/artifact-tool';
const [directory]=process.argv.slice(2);
const col=n=>{let s='';for(n++;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;};
for(const kind of ['产品信息单元','观点信息单元']){
 const p=JSON.parse(await fs.readFile(path.join(directory,kind+'_workbook_payload.json'),'utf8'));
 const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(path.join(directory,p.filename)));
 const name=p.main_name;const sheet=wb.worksheets.getItem(name);
 const joint=p.filename.includes('切片标签联合');
 const changes=p.tables['标签补选与纠错'].filter(e=>e['处理']===(joint?'联合关键词规则直接补标':'关键词规则直接补标'));
 const ids=[...new Set(changes.map(e=>e.unit_id))].slice(0,2);
 const emphasisCol=col(p.schemas[name].indexOf('标签强调方向'));
 for(const uid of ids){
  const row=p.tables[name].findIndex(e=>e.unit_id===uid)+2;
  const range=`${emphasisCol}${row}:${emphasisCol}${row}`;
  const value=sheet.getRange(range).values[0][0];if(!value)throw Error('Missing displayed direction: '+uid);
  const preview=await wb.render({sheetName:name,range,scale:1,format:'png'});
  await fs.writeFile(path.join(directory,name+'_核验',`保存后强调方向_${row}.png`),new Uint8Array(await preview.arrayBuffer()));
  console.log(JSON.stringify({file:p.filename,unit_id:uid,range,direction:value}));
 }
 if(joint){
  const audit=p.tables['标签补选与纠错'];
  const direct=audit.findIndex(e=>e['处理']==='联合关键词规则直接补标');
  const row=(direct>=0?direct:audit.findIndex(e=>e['处理']==='联合关键词补标待核'))+2;
  const header=[...new Set(audit.flatMap(e=>Object.keys(e)))];
  for(const heading of ['联合命中核心字眼','来源标签ID','来源标签原文证据','对象绑定方式']){
   if(row<2)continue;
   const range=`${col(header.indexOf(heading))}${row}:${col(header.indexOf(heading))}${row}`;
   const preview=await wb.render({sheetName:'标签补选与纠错',range,scale:1,format:'png'});
   await fs.writeFile(path.join(directory,name+'_核验',heading+'_保存后.png'),new Uint8Array(await preview.arrayBuffer()));
  }
 }
}
process.exit(0);
