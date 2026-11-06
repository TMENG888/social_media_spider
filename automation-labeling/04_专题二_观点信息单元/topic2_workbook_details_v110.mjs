import {mergeDetailRows,assertUniqueDetailRows} from './topic2_slice_rows_v110.mjs';
const cell=v=>v!==null&&typeof v==='object'?JSON.stringify(v):v??null;
// Apply the same detail grain to pilot and production workbook plans.
export function mergeWorkbookDetails(input){
 const result=structuredClone(input),sheet=result.sheets.find(s=>s.name==='打标明细');
 if(!sheet)throw Error('Missing detail worksheet');
 const rows=mergeDetailRows(sheet.rows.map(r=>Object.fromEntries(sheet.headers.map((h,i)=>[h,r[i]]))));
 assertUniqueDetailRows(rows);
 sheet.rows=rows.map(r=>sheet.headers.map(h=>cell(r[h])));
 if(sheet.rows.some(r=>r.some(v=>typeof v==='string'&&v.length>32767)))throw Error('Merged detail exceeds Excel cell limit');
 sheet.note=String(sheet.note??'').replaceAll('每片每项目合并全部标签','同来源同原片一行，标签保留各自项目绑定').replaceAll('每片每项目合并标签','同来源同原片一行，标签保留各自项目绑定');
 return result;
}
