import {POST_FIELDS,COMMENT_FIELDS,blankRecord,stableId,canonicalDouyinPostUrl} from './schema.mjs';
import {projectForTopic,inTargetYear} from './collection-policy.mjs';
import {cleanText,normalizeTags} from './text-cleaner.mjs';
export const CLEANING_KEYS=['原始文字数','清理后文字数','表情个数','其他字符个数','重复字符个数'];
export function parseCleaningStats(value){
 try{const stats=typeof value==='string'?JSON.parse(value):value;return stats&&Object.keys(stats).length===5&&CLEANING_KEYS.every(k=>Number.isInteger(stats[k])&&stats[k]>=0)?stats:null;}catch{return null;}
}
export const shanghaiTime = seconds => {
 const ms=Number(seconds)*1000;
 if(!Number.isFinite(ms)||ms<=0) return null;
 return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'medium',hourCycle:'h23'}).format(new Date(ms));
};
const strings = value => Array.isArray(value)?value.filter(v=>typeof v==='string'&&/^https?:\/\//.test(v)):[];
export function mediaUrl(value) {
 const urls=strings(value?.url_list || value?.urlList);
 return urls.find(x=>x.startsWith('https://')) || urls[0] || null;
}
export function assertAweme(value) {
 if(!/^\d{15,22}$/.test(String(value?.aweme_id||'')))throw new Error('DOUYIN_AWEME_ID_MISSING');
 if(!shanghaiTime(value.create_time)) throw new Error('DOUYIN_DATE_UNKNOWN');
 if(!value.author?.sec_uid) throw new Error('DOUYIN_AUTHOR_ID_MISSING');
 return value;
}
export function captionDetails({caption='',title='',structuredTags=[]}={}){
 const tags=[...new Set((structuredTags.length?structuredTags:[...String(caption).matchAll(/#([^#\s]+)/g)].map(m=>m[1])).map(t=>String(t).replace(/^#+/,'').replace(/[，。！？,.!?]+$/,'').trim()).filter(Boolean))];
 let headline=String(title||String(caption).split('\n')[0]||'');
 for(const tag of [...tags].sort((a,b)=>b.length-a.length)){
  const escaped=tag.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  headline=headline.replace(new RegExp(`#${escaped}(?=$|[\\s#，。！？,.!?])`,'g'),'');
 }
 headline=headline.replace(/#[^#\s]+/g,'').replace(/[\t ]+/g,' ').trim();
 // Like XHS, removing tags is field splitting, not a removed-character count.
 // Douyin has no separate article body: caption/title is the counted text.
 const cleaned=cleanText(headline,{removeEmoji:true,singleParagraph:true});
 return {fields:{文章标题:cleaned.text||null,文章内容:null,文章标签:normalizeTags(tags),清洗标注:JSON.stringify(cleaned.stats)},rawText:String(caption||title||''),bodyBeforeCleaning:headline,stats:cleaned.stats};
}
export function captionFields(options={}){return captionDetails(options).fields;}
export function normaliseDouyinPostFields(post){
 if(post.平台!=='抖音')return {...post};
 const caption=String(post.文章内容||post.文章标题||'');
 const existing=String(post.文章标签||'');
 const legacyTags=existing.split(existing.includes(',')||existing.includes('，')?/[,，]+/:/\s+/).map(t=>t.trim()).filter(Boolean);
 const parsed=[...caption.matchAll(/#([^#\s]+)/g)].map(m=>m[1]);
 const fields=captionFields({caption,title:post.文章标题,structuredTags:[...parsed,...legacyTags]});
 const previous=parseCleaningStats(post.清洗标注);
 // Do not turn the second import of an already-cleaned record into zero stats.
 if(previous&&previous.清理后文字数===[...String(fields.文章标题||'')].length)fields.清洗标注=JSON.stringify(previous);
 return {...post,...fields};
}
export function normaliseDouyinCommentFields(comment){
 if(comment.平台!=='抖音')return {...comment};
 const cleaned=cleanText(comment.评论内容,{removeEmoji:true,singleParagraph:true});
 const previous=parseCleaningStats(comment.清洗标注);
 return {...comment,评论内容:cleaned.text,清洗标注:JSON.stringify(previous&&previous.清理后文字数===[...cleaned.text].length?previous:cleaned.stats)};
}
export function postFromAweme(raw,task) {
 const a=assertAweme(raw),post=blankRecord(POST_FIELDS),author=a.author,stats=a.statistics||{};
 const images=(a.images||a.image_post_info?.images||[]).map(x=>mediaUrl(x.display_image||x)).filter(Boolean);
 const isImage=images.length>0;
 const video=isImage?null:mediaUrl(a.video?.play_addr)||mediaUrl(a.video?.play_addr_h264)||mediaUrl(a.video?.bit_rate?.[0]?.play_addr);
 if(!isImage&&!video)throw new Error('DOUYIN_VIDEO_MEDIA_MISSING');
 const id=String(a.aweme_id),desc=String(a.desc||'');
 const date=shanghaiTime(a.create_time),caption=captionDetails({caption:desc,title:a.preview_title,structuredTags:(a.text_extra||[]).filter(t=>t.hashtag_name).map(t=>t.hashtag_name)});
 Object.assign(post,{
  id:stableId(`抖音/${task.projectName||projectForTopic(task.topic)}/${id}`),文章id:id,
  文章链接:canonicalDouyinPostUrl(id),...caption.fields,文章时间地点:date,
  作者id:String(author.sec_uid),作者名字:author.nickname||null,作者主页链接:`https://www.douyin.com/user/${encodeURIComponent(author.sec_uid)}`,
  文章图片链接:images.length?JSON.stringify(images):mediaUrl(a.video?.cover),文章图片信息:null,
  文章点赞数:stats.digg_count??null,文章收藏数:stats.collect_count??null,文章评论数:stats.comment_count??null,
  文章分享数:stats.share_count??null,文章视频链接:video,文章视频时长:isImage?null:Number(a.video?.duration??a.duration)/1000||null,
  文章视频内容:null,关键词:task.keyword,平台:'抖音',分类:null,项目:projectForTopic(task.topic),
  地点:a.ip_label||null,内容类型:isImage?'图文':'视频',文章获取时间:shanghaiTime(Date.now()/1000),
  是否广告:a.is_ads===true||a.is_ads===1?'是':null
 });
 return {post,comments:[],postTextAudit:{subtitle_status:video?'pending':'not_applicable',raw_text:caption.rawText,body_before_cleaning:caption.bodyBeforeCleaning,cleaned_text:post.文章标题,cleaning_stats:caption.stats,cleaning_scope:'caption_title_without_tags'},audit:{dateSource:'browser_response_create_time',commentsComplete:task.collectComments?false:null}};
}
export function commentFromRaw(raw,post,rootId=null) {
 if(!raw.cid||!raw.user?.sec_uid||raw.text==null)throw new Error('DOUYIN_COMMENT_IDENTITY_MISSING');
 const c=blankRecord(COMMENT_FIELDS);
 Object.assign(c,{id:stableId(`抖音/${post.项目}/${post.文章id}/${raw.cid}`),评论id:String(raw.cid),
  评论用户id:String(raw.user.sec_uid),评论用户名字:raw.user.nickname||null,
  评论用户链接:`https://www.douyin.com/user/${encodeURIComponent(raw.user.sec_uid)}`,
  评论内容:String(raw.text),评论时间:shanghaiTime(raw.create_time),评论IP:raw.ip_label||null,
  评论点赞数:raw.digg_count??null,评论回复数:raw.reply_comment_total??null,
  文章链接:post.文章链接,文章id:post.文章id,关键词:post.关键词,评论获取时间:shanghaiTime(Date.now()/1000),
  平台:'抖音',分类:null,项目:post.项目});
 return normaliseDouyinCommentFields(c);
}
export function commentAuditFromRaw(raw,rootId=null){
 const cleaned=cleanText(raw.text,{removeEmoji:true,singleParagraph:true});
 return {comment_id:String(raw.cid),root_id:rootId||null,raw_text:String(raw.text||''),cleaned_text:cleaned.text,cleaning_stats:cleaned.stats};
}
export function eligiblePost(raw,task,year=2026) {return inTargetYear(shanghaiTime(raw.create_time),year,task.cutoff||`${year}-01-01`);}
export function latestRequest(url,body='') {
 const u=new URL(url),p=new URLSearchParams(body);
 const value=k=>u.searchParams.get(k)||p.get(k);
 if(value('sort_type')==='2')return true;
 try{return String(JSON.parse(value('filter_selected')||'{}').sort_type)==='2';}catch{return false;}
}
// The normal single-column search response is length/framing-prefixed JSON,
// not one JSON document. Extract complete JSON objects without executing text.
export function decodeBrowserPayload(text) {
 try{return [JSON.parse(text)];}catch{}
 const values=[];let start=-1,depth=0,inString=false,escape=false;
 for(let i=0;i<text.length;i++){
  const c=text[i];
  if(start<0){if(c==='{'){start=i;depth=1;inString=false;escape=false;}continue;}
  if(inString){if(escape)escape=false;else if(c==='\\')escape=true;else if(c==='"')inString=false;continue;}
  if(c==='"')inString=true;else if(c==='{')depth++;else if(c==='}'&&--depth===0){try{values.push(JSON.parse(text.slice(start,i+1)));}catch{}start=-1;}
 }
 return values;
}
export async function boundedResponseText(response,timeoutMs=15000) {
 let timer;
 try{return await Promise.race([response.text(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('DOUYIN_RESPONSE_BODY_TIMEOUT')),timeoutMs);})]);}
 finally{clearTimeout(timer);}
}
export function searchPaginationMetadata(frames){
 const values=[];
 const visit=(value,depth=0)=>{
  if(depth>8||!value||typeof value!=='object'||Array.isArray(value)||value.aweme_id||value.cid)return;
  for(const key of ['has_more','hasMore'])if(Object.hasOwn(value,key)){
   const raw=value[key];
   if(raw===0||raw==='0'||raw===false)values.push(false);
   else if(raw===1||raw==='1'||raw===true)values.push(true);
  }
  // Pagination is a response envelope, never nested per-post/comment data.
  for(const [key,child]of Object.entries(value))if(!['aweme_info','aweme','comments','user','author','video','images','music'].includes(key))visit(child,depth+1);
 };
 for(const frame of frames)visit(frame);
 return values.length&&values.every(v=>v===values[0])?values[0]:null;
}
/** Observe only responses requested by ordinary browser interactions. No direct
 * API calls, signatures, private session exports or CAPTCHA workarounds. */
export class DouyinResponseObserver {
 constructor(page) {
  this.page=page;this.awemes=new Map();this.comments=new Map();this.commentPages=[];this.embeddedReplyCoverage=new Map();this.profiles=new Map();this.searchRequests=[];this.searchPages=[];this.searchFailures=[];this.pending=new Set();this.failures=[];
  this.listener=response=>{const job=this.consume(response).catch(e=>this.failures.push(String(e.message))).finally(()=>this.pending.delete(job));this.pending.add(job);};
  page.on('response',this.listener);
 }
 async flush(){await Promise.all([...this.pending]);}
 async consume(response){
  const u=new URL(response.url());
  if(!/(^|\.)douyin\.com$/.test(u.hostname)||!/(?:general\/search|aweme\/detail|comment\/list|user\/profile\/other)/.test(u.pathname))return;
  const isSearch=/general\/search/.test(u.pathname);
  const searchInfo=isSearch?{at:Date.now(),keyword:u.searchParams.get('keyword'),latest:latestRequest(response.url(),response.request().postData()||''),path:u.pathname,offset:u.searchParams.get('offset')||u.searchParams.get('cursor')||null}:null;
  if(!response.ok()){if(isSearch)this.searchFailures.push({...searchInfo,http:response.status()});return;}
  if(!/json/.test(response.headers()['content-type']||'')){if(isSearch)this.searchFailures.push({...searchInfo,error:'unexpected_content_type'});return;}
  let text;
  try{text=await boundedResponseText(response);}catch(error){if(isSearch)this.searchFailures.push({...searchInfo,error:String(error.message)});throw error;}
  const payload=decodeBrowserPayload(text);
  if(!payload.length){if(isSearch)this.searchFailures.push({...searchInfo,error:'unparseable'});throw new Error('DOUYIN_BROWSER_RESPONSE_UNPARSEABLE');}
  const searchIds=new Set(),validFrames=[];
  for(const data of payload){
  if(data.status_code!=null&&Number(data.status_code)!==0){if(isSearch)this.searchFailures.push({...searchInfo,statusCode:data.status_code});continue;}
  validFrames.push(data);
  const rootId=u.searchParams.get('comment_id')||null;
  const rootComment=rootId?[...this.comments.values()].find(c=>String(c.cid)===rootId):null;
  const responseAwemeId=String(u.searchParams.get('aweme_id')||u.searchParams.get('item_id')||rootComment?.aweme_id||data.comments?.[0]?.aweme_id||'');
  if(/search/.test(u.pathname))this.searchRequests.push({at:Date.now(),keyword:u.searchParams.get('keyword'),latest:latestRequest(response.url(),response.request().postData()||''),path:u.pathname});
  const visit=(v,depth=0,inheritedRoot=null)=>{
   if(depth>12||v==null||typeof v!=='object')return;
   // Incomplete post shapes still represent a known gap, not an empty result.
   if(isSearch&&v.aweme_id&&!v.cid&&(v.author||v.video||v.images||v.image_post_info))searchIds.add(String(v.aweme_id));
   if(v.aweme_id&&v.create_time&&v.author?.sec_uid&&(v.video||v.images||v.image_post_info)){this.awemes.set(String(v.aweme_id),v);if(isSearch)searchIds.add(String(v.aweme_id));return;}
   if(v.cid&&v.user&&v.text!=null){
    const aid=String(v.aweme_id||responseAwemeId);if(aid)this.comments.set(`${aid}/${v.cid}`,{...v,aweme_id:aid,reply_id:inheritedRoot||rootId||v.reply_id});
    const embedded=Array.isArray(v.reply_comment)?v.reply_comment:[];
    for(const child of embedded)visit(child,depth+1,String(v.cid));
    const ids=new Set(embedded.filter(r=>r.cid&&r.user&&r.text!=null).map(r=>String(r.cid)));
    if(aid&&Number(v.reply_comment_total)>0&&ids.size===Number(v.reply_comment_total))this.embeddedReplyCoverage.set(`${aid}/${v.cid}`,{complete:true,count:ids.size,source:'browser_embedded_reply_array'});
    return;
   }
   if(v.sec_uid&&v.nickname&&v.follower_count!=null)this.profiles.set(String(v.sec_uid),v);
   for(const child of Object.values(v))visit(child,depth+1);
  };visit(data);
  if(Array.isArray(data.comments))this.commentPages.push({at:Date.now(),awemeId:responseAwemeId,rootId,hasMore:data.has_more,cursor:data.cursor,count:data.comments.length});
  }
  if(isSearch&&validFrames.length)this.searchPages.push({...searchInfo,hasMore:searchPaginationMetadata(validFrames),noteIds:[...searchIds]});
 }
 detach(){this.page.off('response',this.listener);}
}
