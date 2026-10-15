import {commentFromRaw} from './douyin-data.mjs';
import {cleanText} from './text-cleaner.mjs';
export const COMMENT_THREAD_VERSION=1;
const parentId=value=>value!=null&&String(value)!=='0'&&String(value)!==''?String(value):null;
const count=value=>value!=null&&Number.isFinite(Number(value))?Math.max(0,Number(value)):null;

/** Durable components, not concatenated thread rows, are the merge unit. */
export function commentNodesFromResult(result){
 if(result?.audit?.comments?.aggregation_mode==='legacy_unresolved')return new Map();
 const nodes=new Map(),audits=new Map((result?.commentAudits||[]).map(a=>[String(a.comment_id),a]));
 for(const row of result?.comments||[]){
  const id=String(row.评论id),audit=audits.get(id);
  if(audit?.aggregation_mode==='comment_thread'&&audit.root_comment?.source_row){
   for(const node of [audit.root_comment,...(audit.child_comments||[])])if(node.source_row)nodes.set(String(node.comment_id),structuredClone(node));
  }else nodes.set(id,{comment_id:id,root_id:parentId(audit?.root_id),raw_text:audit?.raw_text??String(row.评论内容||''),reply_to_comment_id:parentId(audit?.reply_to_comment_id),reply_target:audit?.reply_target||null,source_row:{...row}});
 }
 for(const node of result?.audit?.comments?.unattached_comments||[])if(node.source_row)nodes.set(String(node.comment_id),structuredClone(node));
 return nodes;
}
function rawNode(raw,post){
 const row=commentFromRaw(raw,post);
 return {comment_id:String(raw.cid),root_id:parentId(raw.reply_id),raw_text:String(raw.text||''),
  reply_to_comment_id:parentId(raw.reply_to_reply_id||raw.reply_to_comment_id),
  reply_target:raw.reply_to_user?.nickname||raw.reply_to_user_name||raw.reply_to_username||null,source_row:row};
}
function findRoot(id,nodes){
 const seen=new Set();let node=nodes.get(id);
 while(node){
  if(seen.has(node.comment_id))return null;
  seen.add(node.comment_id);
  const parent=parentId(node.root_id);
  if(!parent||parent===node.comment_id)return node.comment_id;
  node=nodes.get(parent);
 }
 return null;
}
export function aggregateCommentThreads(raw,post,{priorResult=null,rootComplete=null}={}){
 const nodes=commentNodesFromResult(priorResult);
 for(const [id,node]of nodes)if(String(node.source_row.文章id)!==String(post.文章id))nodes.delete(id);
 for(const item of raw){if(String(item.aweme_id||post.文章id)!==String(post.文章id))continue;const node=rawNode(item,post);nodes.set(node.comment_id,node);}
 const groups=new Map(),unattached=[];
 for(const node of nodes.values()){
  const root=findRoot(node.comment_id,nodes);
  if(!root){unattached.push(node);continue;}
  if(!groups.has(root))groups.set(root,[]);
  if(node.comment_id!==root)groups.get(root).push(node);
 }
 const rows=[],commentAudits=[];
 for(const [rootId,children]of groups){
  const root=nodes.get(rootId),rootRow=root.source_row;
  const blocks=[`【父评论｜${rootRow.评论用户名字||'未知用户'}】\n${root.raw_text}`];
  children.forEach((child,index)=>{
   const target=child.reply_target||(child.reply_to_comment_id&&nodes.get(child.reply_to_comment_id)?.source_row.评论用户名字)||String(child.raw_text).match(/^回复\s*([^：:]+)[：:]/)?.[1]||null;
   child.reply_target=target;
   blocks.push(`【子评论${index+1}｜${child.source_row.评论用户名字||'未知用户'}${target?`｜回复${target}`:''}】\n${child.raw_text}`);
  });
  const rawText=blocks.join('\n\n'),cleaned=cleanText(rawText,{removeEmoji:true,singleParagraph:true});
  const rootLikes=count(rootRow.评论点赞数)||0,childLikes=children.reduce((sum,c)=>sum+(count(c.source_row.评论点赞数)||0),0);
  const displayed=count(rootRow.评论回复数),evidence=rootComplete?rootComplete(rootId):null;
  const priorAudit=(priorResult?.commentAudits||[]).find(a=>a.aggregation_mode==='comment_thread'&&String(a.comment_id)===rootId);
  const complete=(displayed==null?null:children.length>=displayed);
  const row={...rootRow,评论内容:cleaned.text,评论点赞数:rootLikes+childLikes,评论回复数:displayed??children.length,清洗标注:JSON.stringify(cleaned.stats)};
  rows.push(row);
  commentAudits.push({article_id:post.文章id,comment_id:rootId,root_id:null,aggregation_mode:'comment_thread',aggregation_version:COMMENT_THREAD_VERSION,
   root_comment_id:rootId,raw_text:rawText,cleaned_text:cleaned.text,cleaning_stats:cleaned.stats,
   displayed_reply_count:displayed,captured_reply_count:children.length,root_like_count:rootLikes,child_like_count:childLikes,thread_like_count:rootLikes+childLikes,
   thread_complete:complete,reply_end_confirmed:evidence??priorAudit?.reply_end_confirmed??null,root_comment:structuredClone(root),
   child_comments:children.map(c=>({...structuredClone(c),user_id:c.source_row.评论用户id,user_name:c.source_row.评论用户名字,like_count:c.source_row.评论点赞数}))});
 }
 return {rows,commentAudits,rawCommentCount:nodes.size,threadCount:rows.length,orphanCommentIds:unattached.map(c=>c.comment_id),unattachedComments:unattached};
}
export function mergeCommentResults(post,priorResult,incoming){
 const combined=commentNodesFromResult(priorResult);
 for(const [id,node]of commentNodesFromResult(incoming))combined.set(id,node);
 const seed={comments:[...combined.values()].map(n=>n.source_row),commentAudits:[...combined.values()].map(n=>({comment_id:n.comment_id,root_id:n.root_id,raw_text:n.raw_text,reply_to_comment_id:n.reply_to_comment_id,reply_target:n.reply_target}))};
 return aggregateCommentThreads([],post,{priorResult:seed});
}

/** Reformat only legacy results whose per-comment parent evidence is saved. */
export function normaliseCommentResult(result){
 if(result?.post?.平台!=='抖音'||!result.comments?.length)return result;
 if(result.audit?.comments?.aggregation_mode==='legacy_unresolved')return result;
 if(result.commentAudits?.length===result.comments.length&&result.commentAudits.every(a=>a.aggregation_mode==='comment_thread'&&a.aggregation_version===COMMENT_THREAD_VERSION))return result;
 const legacy=new Map((result.commentAudits||[]).map(a=>[String(a.comment_id),a]));
 if(result.comments.some(c=>!legacy.has(String(c.评论id))||!Object.hasOwn(legacy.get(String(c.评论id)),'root_id')))return {...result,audit:{...result.audit,commentsComplete:false,comments:{...result.audit?.comments,complete:false,aggregation_mode:'legacy_unresolved',migration_reason:'COMMENT_PARENT_EVIDENCE_MISSING'}}};
 const output=aggregateCommentThreads([],result.post,{priorResult:result});
 const incomplete=output.orphanCommentIds.length>0||output.commentAudits.some(a=>a.thread_complete===false);
 return {...result,comments:output.rows,commentAudits:output.commentAudits,audit:{...result.audit,commentsComplete:incomplete?false:result.audit?.commentsComplete,
  comments:{...result.audit?.comments,aggregation_mode:'comment_thread',aggregation_version:COMMENT_THREAD_VERSION,raw_comment_count:output.rawCommentCount,thread_count:output.threadCount,
   ...(incomplete?{complete:false,missingReplyRoots:[...new Set([...(result.audit?.comments?.missingReplyRoots||[]),...output.commentAudits.filter(a=>a.thread_complete===false).map(a=>a.comment_id)])]}:{}),collected:output.rawCommentCount,orphan_comment_ids:output.orphanCommentIds,unattached_comments:output.unattachedComments}}};
}
