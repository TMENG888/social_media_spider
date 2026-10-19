import path from 'node:path';
import {DatabaseSync} from 'node:sqlite';
import {annualInventoryFromNotes} from './keyword-annual-acceptance.mjs';
import {collectorAnnualScan} from './annual-scan-adapter.mjs';
import {attachScopeAudits,verifiedScopeExclusion} from './coverage-scope.mjs';

// Only a finished collector for THIS original keyword may supply a scan.
// Read the checkpoint without migrations/recovery writes and SQL in read-only
// isolation. A local import ledger is never substituted for a SQL readback.
export async function annualInputFromCollector({decision,task,record,stateRoot,connect}){
 if(!record||record.keyword!==decision.keyword||record.projectName!==decision.projectName
  ||typeof record.checkpointDb!=='string')return null;
 if(record.importError||record.importExitCode!=null&&record.importExitCode!==0)return null;
 const checkpoint=path.resolve(record.checkpointDb),relative=path.relative(path.resolve(stateRoot),checkpoint);
 if(!relative||relative.startsWith('..')||path.isAbsolute(relative)||path.basename(checkpoint)!=='checkpoint.sqlite')return null;
 const identity={taskId:decision.taskId,keyword:decision.keyword,projectName:decision.projectName,
  year:Number(String(task.cutoff||task.minPublishedDate||'2026-01-01').slice(0,4))};
 const scan=collectorAnnualScan(record,identity);
 if(!scan.ok)return {scan,inventory:[],error:record.error,year:identity.year};
 const cp=new DatabaseSync(checkpoint,{readOnly:true});let notes;
 try{
  cp.exec('BEGIN');
  notes=cp.prepare('SELECT note_id AS noteId,status,result_json FROM candidate WHERE keyword=? ORDER BY note_id').all(decision.keyword).map(row=>{
   let result=null;try{result=JSON.parse(row.result_json);}catch{}
   return {...row,result,publishedAt:result?.post?.文章时间地点||result?.publishedAt||null};
  });
  notes=attachScopeAudits(cp,notes,decision.keyword);cp.exec('COMMIT');
 }finally{cp.close();}
 const connection=await connect();let importedIds;
 try{
  await connection.query('SET TRANSACTION READ ONLY');await connection.beginTransaction();
  const [rows]=await connection.execute(
   "SELECT `文章id` AS noteId,`文章时间地点` AS publishedAt FROM ods_social_media_post WHERE `平台`=? AND `项目`=? AND `关键词`=?",
   [decision.platform,decision.projectName,decision.keyword]);
  const ids=new Set(rows.map(row=>String(row.noteId||'').trim()).filter(Boolean));
  if(ids.size!==decision.posts)throw new Error('ANNUAL_SQL_SNAPSHOT_CHANGED');
  if(rows.some(row=>!String(row.publishedAt||'').startsWith(identity.year+'-')))throw new Error('ANNUAL_SQL_YEAR_UNVERIFIED');
  importedIds=rows.filter(row=>String(row.publishedAt||'').startsWith(identity.year+'-')).map(row=>String(row.noteId));
  await connection.commit();
 }catch(error){await connection.rollback().catch(()=>{});throw error;}
 finally{await connection.end();}
 const verifiedIrrelevantIds=notes.filter(note=>verifiedScopeExclusion(note,decision.keyword)).map(note=>note.noteId);
 return {scan,inventory:annualInventoryFromNotes(notes,{...identity,importedIds,verifiedIrrelevantIds}),
  error:record.error||null,year:identity.year};
}
