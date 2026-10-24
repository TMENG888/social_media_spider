import fs from 'node:fs/promises';
import path from 'node:path';
import {FileBlob,SpreadsheetFile} from '@oai/artifact-tool';
const [source,out,mode='inspect']=process.argv.slice(2);
await fs.mkdir(out,{recursive:true});
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(source));
const s=wb.worksheets.getItem('Sheet1');
console.log((await wb.inspect({kind:'region',sheetId:'Sheet1',range:'F377:L380',maxChars:2000})).ndjson);
const before=await wb.render({sheetName:'Sheet1',range:'F377:L380',scale:1});
await fs.writeFile(path.join(out,'taxonomy_before.png'),new Uint8Array(await before.arrayBuffer()));
if(mode==='edit'){
 const policy=JSON.parse(await fs.readFile(path.join(out,'gym_policy.json'),'utf8'));
 if(s.getRange('F379').values[0][0]!=='健身房器械')throw Error('Unexpected taxonomy row');
 s.getRange('J379').values=[[policy.instruction]];
 s.getRange('A379:M379').format.rowHeightPx=116;
 wb.recalculate();
 console.log((await wb.inspect({kind:'table',range:'Sheet1!I379:J379',include:'values,formulas',maxChars:1800})).ndjson);
 const after=await wb.render({sheetName:'Sheet1',range:'F377:L380',scale:1});
 await fs.writeFile(path.join(out,'taxonomy_after.png'),new Uint8Array(await after.arrayBuffer()));
 await (await SpreadsheetFile.exportXlsx(wb)).save(path.join(out,'taxonomy_artifact_edited.xlsx'));
 console.log('ARTIFACT_EDIT_SAVED');
}
