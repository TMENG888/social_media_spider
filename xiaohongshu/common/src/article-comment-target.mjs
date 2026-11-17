import {createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import mysql from 'mysql2/promise';
import {checkpointCandidates} from './checkpoint.mjs';
import {inTargetYear} from './collection-policy.mjs';
import {observedScopeRelevance} from './coverage-scope.mjs';
import {frontendClosed} from './foreground-budget.mjs';
import {mysqlConnectionOptions,utf8mb3CompatibleText} from './import-mysql.mjs';

export const ARTICLE_COMMENT_TARGET_POLICY='xhs-200-articles-comments-20261114-v1';
export const COMMENT_PROCESSING_POLICY='xhs-comment-processing-20261114-v1';
export const ARTICLE_COMMENT_TARGET=200;
const digest=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const id=value=>String(value??'');
const compare=(a,b)=>a<b?-1:a>b?1:0;
const commentFields=['评论id','文章id','平台','项目','评论内容'];
const articleFields=['文章链接','文章标题','文章内容'];

// This records execution of the existing bounded comment flow. It does not
// claim every comment/reply on the platform was exposed or collected.
export function commentEvidence(result,{allowLegacy=true}={}){
 const p=result?.post,rows=result?.comments;
 if(!p||frontendClosed(result)||result.audit?.commentsComplete===false||!Array.isArray(rows))return null;
 const unique=new Map();
 for(const row of rows){
  if(!row||!row.评论id||!String(row.评论内容||'').trim()||id(row.文章id)!==id(p.文章id)
   ||row.平台!=='小红书'||row.项目!==p.项目)return null;
  const key=id(row.评论id),prior=unique.get(key);
  if(prior&&digest(commentFields.map(f=>prior[f]??null))!==digest(commentFields.map(f=>row[f]??null)))return null;
  unique.set(key,row);
 }
 const comments=[...unique.values()].sort((a,b)=>compare(id(a.评论id),id(b.评论id)));
 if(!comments.length&&p.文章评论数!==0)return null;
 const proof={policy:COMMENT_PROCESSING_POLICY,noteId:id(p.文章id),projectName:p.项目,
  count:comments.length,zeroCommentsObserved:comments.length===0&&p.文章评论数===0,
  commentsDigest:digest(comments.map(c=>commentFields.map(f=>c[f]??null)))};
 const stored=result.commentCollection;
 if(stored){
  if(stored.policy!==proof.policy||stored.noteId!==proof.noteId||stored.projectName!==proof.projectName
   ||stored.count!==proof.count||stored.zeroCommentsObserved!==proof.zeroCommentsObserved
   ||stored.commentsDigest!==proof.commentsDigest||!Number.isFinite(Date.parse(stored.finishedAt)))return null;
 }else{
  // Old article-only rows have neither comments nor thread audits. Never infer
  // comment processing from the checkpoint's global configuration flag.
  const audited=new Set((Array.isArray(result.commentAudits)?result.commentAudits:[]).filter(a=>a&&id(a.article_id)===id(p.文章id)).map(a=>id(a.comment_id)));
  if(!allowLegacy||!comments.length||!comments.every(c=>audited.has(id(c.评论id))))return null;
 }
 return {...proof,comments};
}

export function markCommentProcessing(post,comments){
 const temporary={post,comments,commentCollection:null,
  commentAudits:comments.map(c=>({article_id:c.文章id,comment_id:c.评论id}))};
 // A fresh normal return can establish a genuine zero-comment observation.
 if(!comments.length&&post.文章评论数===0){
  return {policy:COMMENT_PROCESSING_POLICY,noteId:id(post.文章id),projectName:post.项目,count:0,
   zeroCommentsObserved:true,commentsDigest:digest([]),finishedAt:new Date().toISOString()};
 }
 const proof=commentEvidence(temporary);if(!proof)return null;
 const {comments:ignored,...fields}=proof;
 return {...fields,finishedAt:new Date().toISOString()};
}

export function eligibleArticleComments(note,{keyword,projectName,year=2026,cutoff=`${year}-01-01`}={}){
 const p=note.result?.post;
 if(note.status!=='completed'||!p||id(note.noteId)!==id(p.文章id)||!p.文章id||p.平台!=='小红书'
  ||!projectName||p.项目!==projectName||!p.文章链接||!String(p.文章标题||p.文章内容||'').trim()
  ||!inTargetYear(p.文章时间地点,year,cutoff)||!observedScopeRelevance(note,keyword))return null;
 const evidence=commentEvidence(note.result);return evidence?{note,evidence}:null;
}

export function selectArticleComments(notes,options){
 const found=new Map();
 for(const note of notes){const item=eligibleArticleComments(note,options);if(item)found.set(id(note.noteId),item);}
 return [...found.values()].sort((a,b)=>compare(id(a.note.noteId),id(b.note.noteId)));
}

export function targetProof(items,{keyword,projectName,year=2026,cutoff=`${year}-01-01`,dbReadbackVerified=false}={}){
 const selected=items.slice(0,ARTICLE_COMMENT_TARGET);
 const articles=selected.map(({note,evidence})=>({noteId:id(note.noteId),commentCount:evidence.count,
  zeroCommentsObserved:evidence.zeroCommentsObserved,commentsDigest:evidence.commentsDigest}));
 return {policy:ARTICLE_COMMENT_TARGET_POLICY,threshold:ARTICLE_COMMENT_TARGET,platform:'小红书',
  keyword,projectName,year,cutoff,ok:articles.length===ARTICLE_COMMENT_TARGET,
  count:articles.length,eligibleCount:items.length,articles,articlesDigest:digest(articles),
  commentCount:articles.reduce((n,a)=>n+a.commentCount,0),dbReadbackVerified,
  checkedAt:new Date().toISOString(),reason:articles.length===ARTICLE_COMMENT_TARGET?'article_comment_target':'ARTICLE_COMMENT_TARGET_NOT_REACHED'};
}

export function validTargetProof(proof,{keyword,projectName,requireDatabase=false}={}){
 if(proof?.policy!==ARTICLE_COMMENT_TARGET_POLICY||proof.ok!==true||proof.threshold!==ARTICLE_COMMENT_TARGET
  ||proof.platform!=='小红书'||!proof.keyword||!proof.projectName||proof.keyword!==keyword||proof.projectName!==projectName
  ||!Number.isSafeInteger(proof.year)||proof.cutoff!==`${proof.year}-01-01`
  ||proof.count!==ARTICLE_COMMENT_TARGET||!Number.isSafeInteger(proof.eligibleCount)||proof.eligibleCount<proof.count
  ||!Array.isArray(proof.articles)||proof.articles.length!==proof.count
  ||(requireDatabase&&proof.dbReadbackVerified!==true)||!Number.isFinite(Date.parse(proof.checkedAt)))return false;
 const seen=new Set();let comments=0;
 for(const a of proof.articles){
  if(!a||typeof a.noteId!=='string'||!a.noteId||seen.has(a.noteId)||!Number.isSafeInteger(a.commentCount)||a.commentCount<0
   ||(a.commentCount===0&&a.zeroCommentsObserved!==true)||!(/^[a-f0-9]{64}$/.test(a.commentsDigest)))return false;
  seen.add(a.noteId);comments+=a.commentCount;
 }
 return comments===proof.commentCount&&digest(proof.articles)===proof.articlesDigest;
}

// Final completion uses an independent read-only snapshot of both tables.
// Pending background subtitles are intentionally outside this foreground rule.
export async function verifyArticleCommentTarget({checkpointDb,keyword,projectName,year=2026,cutoff=`${year}-01-01`,
 connect=()=>mysql.createConnection(mysqlConnectionOptions()),readNotes}={}){
 let notes;
 if(readNotes)notes=await readNotes();else{
  const cp=new DatabaseSync(checkpointDb,{readOnly:true});
  try{cp.exec('BEGIN');notes=checkpointCandidates(cp,keyword);cp.exec('COMMIT');}finally{cp.close();}
 }
 const options={keyword,projectName,year,cutoff},eligible=selectArticleComments(notes,options);
 if(eligible.length<ARTICLE_COMMENT_TARGET)return targetProof(eligible,options);
 const connection=await connect(),verified=[];
 try{
  await connection.query('SET TRANSACTION READ ONLY');await connection.beginTransaction();
  const mb3={};
  for(const table of ['ods_social_media_post','ods_social_media_comment']){
   const [columns]=await connection.query(`SHOW FULL COLUMNS FROM ${table}`);
   mb3[table]=new Set(columns.filter(c=>/^(utf8mb3|utf8)_/i.test(c.Collation||'')).map(c=>c.Field));
  }
  const equal=(table,actual,expected,fields)=>fields.every(f=>{
   const value=mb3[table].has(f)?utf8mb3CompatibleText(expected[f]):expected[f];
   return value==null?actual[f]==null:String(actual[f]??'')===String(value);
  });
  for(let offset=0;offset<eligible.length&&verified.length<ARTICLE_COMMENT_TARGET;offset+=100){
   const batch=eligible.slice(offset,offset+100),ids=batch.map(i=>id(i.note.noteId)),params=['小红书',projectName,...ids];
   const placeholders=ids.map(()=>'?').join(',');
   const [posts]=await connection.execute(`SELECT \`文章id\`,\`文章链接\`,\`文章标题\`,\`文章内容\` FROM ods_social_media_post WHERE \`平台\`=? AND \`项目\`=? AND \`文章id\` IN (${placeholders})`,params);
   const [comments]=await connection.execute(`SELECT \`评论id\`,\`文章id\`,\`平台\`,\`项目\`,\`评论内容\` FROM ods_social_media_comment WHERE \`平台\`=? AND \`项目\`=? AND \`文章id\` IN (${placeholders})`,params);
   const byPost=new Map(),byComment=new Map();
   for(const p of posts){const k=id(p.文章id);byPost.set(k,[...(byPost.get(k)||[]),p]);}
   for(const c of comments){const k=JSON.stringify([id(c.文章id),id(c.评论id)]);byComment.set(k,[...(byComment.get(k)||[]),c]);}
   for(const item of batch){
    const p=item.note.result.post,rows=byPost.get(id(item.note.noteId))||[];
    if(rows.length!==1||!equal('ods_social_media_post',rows[0],p,articleFields))continue;
    if(item.evidence.comments.every(c=>{
     const matches=byComment.get(JSON.stringify([id(c.文章id),id(c.评论id)]))||[];
     return matches.length===1&&equal('ods_social_media_comment',matches[0],c,commentFields);
    }))verified.push(item);
   }
  }
  await connection.commit();
 }finally{await connection.end();}
 const proof=targetProof(verified,{...options,dbReadbackVerified:true});
 return {...proof,eligibleCount:eligible.length};
}
