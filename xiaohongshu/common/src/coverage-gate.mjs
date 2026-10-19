import {createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import mysql from 'mysql2/promise';
import {mysqlConnectionOptions,utf8mb3CompatibleText} from './import-mysql.mjs';
import {checkpointCandidates} from './checkpoint.mjs';
import {inTargetYear,validDate} from './collection-policy.mjs';
import {COVERAGE_SCOPE,verifiedScopeExclusion,attachScopeAudits,observedScopeRelevance} from './coverage-scope.mjs';
import {RELEVANCE_POLICY} from './enterprise-relevance.mjs';

export const COVERAGE_POLICY='20261015-scoped-usable-db-80-v3';
const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const contentFields=['文章链接','文章标题','文章内容','文章视频内容'];
export function usableResult(note,{strictMedia=false}={}){
 const r=note.result,p=r?.post,a=r?.postTextAudit||{};
 if(note.status!=='completed'||!p?.文章id||String(p.文章id)!==String(note.noteId)||!p.文章链接||!p.项目)return false;
 if(!String(p.文章标题||p.文章内容||'').trim()||r.audit?.commentsComplete===false)return false;
 if(p.内容类型==='视频'){
  if(strictMedia&&!(r.mediaProvenance?.identityVerified===true&&r.mediaProvenance.version==='20261015-note-bound-media-v1'))return false;
  if(!['extracted','no_speech'].includes(a.subtitle_status))return false;
  if(a.subtitle_status==='extracted'&&!String(p.文章视频内容||'').trim())return false;
  if(strictMedia){
   const proof=a.subtitle_audit?.mediaProvenance,current=r.mediaProvenance;
   if(proof?.durationVerified!==true||proof.noteId!==String(note.noteId)||proof.version!==current.version)return false;
   if(!(Number(proof.decodedDuration)>0)||Math.abs(Number(proof.decodedDuration)-Number(current.expectedDuration))>Math.max(2,Number(current.expectedDuration)*.03))return false;
   if(!(Number(p.文章视频时长)>0)||Math.abs(Number(p.文章视频时长)-Number(current.expectedDuration))>2)return false;
  }
  if(a.subtitle_audit?.quality?.accepted===false)return false;
 }
 return true;
}
export function assessCoverage(notes,{scanComplete=false,verifiedIds=[],year=2026,cutoff=`${year}-01-01`,strictMedia=false,keyword}={}){
 const unique=[...new Map(notes.map(n=>[String(n.noteId),n])).values()];
 const datedOut=unique.filter(n=>n.status==='skipped_old'&&validDate(n.publishedAt)&&!inTargetYear(n.publishedAt,year,cutoff));
 const datedIds=new Set(datedOut.map(n=>String(n.noteId)));
 const scopeExcluded=unique.filter(n=>!datedIds.has(String(n.noteId))).map(n=>verifiedScopeExclusion(n,keyword)).filter(Boolean);
 const scopeIds=new Set(scopeExcluded.map(n=>n.noteId));
 const eligible=unique.filter(n=>!datedIds.has(String(n.noteId))&&!scopeIds.has(String(n.noteId)));
 const verified=new Set(verifiedIds.map(String));
 const usable=eligible.filter(n=>observedScopeRelevance(n,keyword)&&inTargetYear(n.publishedAt,year,cutoff)&&usableResult(n,{strictMedia})&&verified.has(String(n.noteId)));
 const denominator=eligible.length,numerator=usable.length;
 const ok=scanComplete===true&&(denominator===0||5*numerator>=4*denominator);
 return {policy:COVERAGE_POLICY,scopePolicy:COVERAGE_SCOPE,relevancePolicy:RELEVANCE_POLICY,ok,scanComplete:scanComplete===true,dbReadbackVerified:true,
  numerator,denominator,discoveredUniqueCount:unique.length,excludedWithDateEvidence:datedOut.length,
  excludedWithScopeEvidence:scopeExcluded.length,scopeExclusions:scopeExcluded,scopeExclusionsDigest:hash(scopeExcluded),
  unverifiedScopeExclusions:eligible.filter(n=>n.status==='skipped_irrelevant').length,
  uncertainRelevanceCount:eligible.filter(n=>!observedScopeRelevance(n,keyword)).length,
  unresolved:denominator-numerator,ratio:denominator?numerator/denominator:null,
  emptyScope:denominator===0,discoveredDigest:hash(eligible.map(n=>n.noteId).sort()),usableDigest:hash(usable.map(n=>n.noteId).sort()),
  reason:!scanComplete?'SEARCH_END_UNVERIFIED':ok?'COVERAGE_ACCEPTED':'USABLE_DB_COVERAGE_BELOW_80'};
}
// Read back persisted business fields after the final import, in one database
// snapshot. Import exit codes/local ledgers alone are not database evidence.
export async function verifyCheckpointCoverage({checkpointDb,keyword,scanComplete,year=2026,cutoff,strictMedia=false,connect=()=>mysql.createConnection(mysqlConnectionOptions())}){
 const cp=new DatabaseSync(checkpointDb,{readOnly:true});let notes;
 try{cp.exec('BEGIN');notes=attachScopeAudits(cp,checkpointCandidates(cp,keyword),keyword);cp.exec('COMMIT');}finally{cp.close();}
 const connection=await connect();
 const verified=[];
 try{
  await connection.query('SET TRANSACTION READ ONLY');await connection.beginTransaction();
  const [columns]=await connection.query('SHOW FULL COLUMNS FROM ods_social_media_post');
  const mb3=new Set(columns.filter(c=>/^(utf8mb3|utf8)_/i.test(c.Collation||'')).map(c=>c.Field));
  const groups=new Map(),found=new Map();
  for(const note of notes.filter(n=>usableResult(n,{strictMedia}))){
   const p=note.result.post,key=JSON.stringify([p.平台,p.项目]);
   if(!groups.has(key))groups.set(key,{platform:p.平台,project:p.项目,ids:[]});
   groups.get(key).ids.push(String(p.文章id));
  }
  for(const group of groups.values())for(let offset=0;offset<group.ids.length;offset+=100){
   const batch=group.ids.slice(offset,offset+100);
   const [rows]=await connection.execute(`SELECT \`平台\`,\`项目\`,\`文章id\`,\`文章链接\`,\`文章标题\`,\`文章内容\`,\`文章视频内容\` FROM ods_social_media_post WHERE \`平台\`=? AND \`项目\`=? AND \`文章id\` IN (${batch.map(()=>'?').join(',')})`,[group.platform,group.project,...batch]);
   for(const row of rows){const key=JSON.stringify([row.平台,row.项目,String(row.文章id)]);if(!found.has(key))found.set(key,[]);found.get(key).push(row);}
  }
  for(const note of notes.filter(n=>usableResult(n,{strictMedia}))){
   const p=note.result.post;
   const rows=found.get(JSON.stringify([p.平台,p.项目,String(p.文章id)]))||[];
   if(rows.length!==1)continue;
   if(contentFields.every(f=>{
    const expected=mb3.has(f)?utf8mb3CompatibleText(p[f]):p[f],actual=rows[0][f];
    return expected==null?actual==null:String(actual??'')===String(expected);
   }))verified.push(String(note.noteId));
  }
  await connection.commit();
 }finally{await connection.end();}
 return {...assessCoverage(notes,{scanComplete,verifiedIds:verified,year,cutoff,strictMedia,keyword}),checkedAt:new Date().toISOString(),keyword};
}
