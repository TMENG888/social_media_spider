import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import {canonical,dateValue,count,postRow,commentRow} from './core.mjs';
import {accessIssue,appealSummary} from './access.mjs';

export function walk(value,visit,depth=0){if(!value||typeof value!=='object'||depth>18)return;visit(value);for(const child of Object.values(value))if(child&&typeof child==='object')walk(child,visit,depth+1);}
export function fromEntity(entity,c){
 const id=String(entity.id??'');if(id!==c.numericId)return null;
 const author=entity.author||{};const token=author.url_token||author.urlToken;
 return {url:c.url,title:entity.title||entity.question?.title||'',contentHtml:entity.content||'',publishedDate:dateValue(entity.created_time??entity.createdTime??entity.created??entity.datePublished),updatedDate:dateValue(entity.updated_time??entity.updatedTime),authorId:author.id||null,authorName:author.name||null,authorUrl:token?'https://www.zhihu.com/people/'+token:null,voteCount:entity.voteup_count??entity.voteupCount,favoriteCount:entity.favlists_count??entity.favlistsCount,commentCount:entity.comment_count??entity.commentCount,tags:(entity.topics||[]).map(t=>t.name).filter(Boolean)};
}
export class ZhihuBrowser{
 static async open(profile,config){await fs.mkdir(profile,{recursive:true});let executablePath=process.env.ZHIHU_BROWSER_EXECUTABLE||config.browserExecutable;if(executablePath&&!await fs.access(executablePath).then(()=>true,()=>false))executablePath=undefined;const context=await chromium.launchPersistentContext(profile,{headless:config.headless,executablePath:executablePath||undefined,acceptDownloads:false,locale:'zh-CN',timezoneId:'Asia/Shanghai',viewport:{width:1440,height:1000}});context.setDefaultTimeout(12000);context.setDefaultNavigationTimeout(config.navigationTimeoutMs);return new ZhihuBrowser(context,config);}
 constructor(context,config){Object.assign(this,{context,config});this.search=null;this.commentCaptures=new WeakMap();this.accessEvidence=new WeakMap();context.on('response',response=>{if(!/^https:\/\/www\.zhihu\.com\/api\/v4\/anticrawl\/new_captcha_appeal(?:[?]|$)/.test(response.url()))return;response.json().then(payload=>{const page=response.frame().page();this.accessEvidence.set(page,appealSummary(payload));}).catch(()=>{});});}
 async gate(page,httpStatus=null){
  const body=(await page.locator('body').innerText()).slice(0,18000);
  const issue=accessIssue({url:page.url(),text:body,httpStatus,appeal:this.accessEvidence.get(page)});if(issue)throw Object.assign(new Error(issue.code+'：'+issue.message),{code:issue.code});
  if(await page.locator('.SignFlowModal,.SignFlow,.SignContainer-content').filter({visible:true}).count())throw new Error('LOGIN_REQUIRED：请先运行登录知乎');
 }
 async authenticated(page){await this.gate(page);const logged=await page.locator('.AppHeader-userInfo .Avatar,.AppHeader-profile,.AppHeader-userInfo [aria-label="消息"],button[aria-label="消息"]').count();const cookies=await this.context.cookies('https://www.zhihu.com');if(!logged&&!cookies.some(c=>c.name==='z_c0'&&c.value))throw new Error('LOGIN_REQUIRED：没有已登录会话，拒绝把空结果记为完成');}
 async navigate(page,url){
  this.accessEvidence.delete(page);let status=null;
  const navigation=response=>{try{if(response.request().isNavigationRequest()&&response.frame()===page.mainFrame())status=response.status();}catch{}};
  page.on('response',navigation);
  try{const r=await page.goto(url,{waitUntil:'domcontentloaded'});await page.waitForTimeout(r?.status()===403?3000:1500);await this.gate(page,status??r?.status());}finally{page.off('response',navigation);}
 }
 async startSearch(keyword){
  this.search=this.search||await this.context.newPage();const page=this.search;
  await this.navigate(page,'https://www.zhihu.com/search?type=content&q='+encodeURIComponent(keyword));await this.authenticated(page);
  let latest=page.getByText('最新发布',{exact:true});
  if(!await latest.isVisible().catch(()=>false)){
    const filter=page.getByText('筛选',{exact:true});if(await filter.count()){await filter.first().click();await page.waitForTimeout(400);}
  }
  latest=page.getByText('最新发布',{exact:true});if(await latest.isVisible().catch(()=>false)){await latest.click();await page.waitForTimeout(1200);}
  const url=new URL(page.url());const selected=await page.locator('[aria-selected="true"],.is-active,.SearchFilter-active,.SearchFilter-value,.SearchTabs-customFilter--tag.tag-selected').allTextContents();
  const sorted=url.searchParams.get('sort')==='created_time'||selected.some(t=>/最新发布/.test(t));
  if(this.config.requireLatestSort&&!sorted)throw new Error('SORT_UNVERIFIED：未确认知乎最新发布排序，需按实页更新选择器');
  await this.gate(page);return {sorted};
 }
 async candidates(){return this.search.locator('.SearchResult-Card a[href],.SearchResult-Card meta[itemprop="url"],.SearchResult-Card [itemprop="url"][content]').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('href')||n.getAttribute('content')).filter(Boolean)).then(urls=>[...new Map(urls.map(canonical).filter(Boolean).map(c=>[c.id,c])).values()]);}
 async searchEnd(){
  const main=this.search.locator('.SearchMain');if(!await main.count())return false;
  const text=await main.innerText();return /没有更多(内容|结果)|已显示全部|已加载全部|未搜索到相关内容|暂无搜索结果/.test(text);
 }
 async scrollSearch(){await this.search.mouse.wheel(0,850);}
 async detail(candidate){
  const page=await this.context.newPage();const entities=[];const pending=[];const commentCaptures=[];this.commentCaptures.set(page,commentCaptures);
  const listen=response=>{if(!/zhihu\.com\//.test(response.url())||!/json/i.test(response.headers()['content-type']||''))return;pending.push(response.json().then(j=>{if(/\/comment_v5\/|\/comments\b/.test(response.url()))commentCaptures.push({url:response.url(),json:j});walk(j,e=>{if(String(e.id??'')===candidate.numericId&&(e.type===candidate.kind||e.content))entities.push(e);});}).catch(()=>{}));};page.on('response',listen);
  try{
   await this.navigate(page,candidate.url);await Promise.all(pending);
   const expand=page.getByRole('button',{name:/^(展开阅读全文|阅读全文|显示全部)$/});if(await expand.count())await expand.first().click();
   if(await page.getByText(/购买后|开通会员.*阅读|盐选专栏/).count())throw new Error('PAID_CONTENT_UNAVAILABLE');
   const dom=await page.evaluate(()=>{
    const txt=s=>document.querySelector(s)?.innerText||'';const attr=(s,a)=>document.querySelector(s)?.getAttribute(a)||null;
    const content=document.querySelector('.AnswerItem .RichContent-inner .RichText,.Post-RichTextContainer .RichText,.Post-RichTextContainer,.AnswerItem .RichContent-inner');
    const initial=document.querySelector('#js-initialData')?.textContent;
    let parsed=null;try{parsed=JSON.parse(initial||'null');}catch{}
    return {title:txt('h1.QuestionHeader-title,h1.Post-Title,h1'),content:content?.innerText||'',images:content?[...content.querySelectorAll('img')].map(i=>i.getAttribute('data-original')||i.src).filter(u=>u&&!u.startsWith('data:')):[],publishedMeta:attr('meta[itemprop="dateCreated"],meta[itemprop="datePublished"],meta[property="article:published_time"]','content'),publishedText:txt('.ContentItem-time'),authorName:txt('.AnswerItem .AuthorInfo-name,.Post-Author .AuthorInfo-name'),authorUrl:document.querySelector('.AnswerItem .AuthorInfo-name a,.Post-Author .AuthorInfo-name a')?.href||null,voteText:txt('.VoteButton--up'),commentText:txt('.ContentItem-actions button:nth-child(2)'),parsed};
   });
   walk(dom.parsed,e=>{if(String(e.id??'')===candidate.numericId&&(e.type===candidate.kind||e.content))entities.push(e);});
   let raw=entities.map(e=>fromEntity(e,candidate)).find(Boolean)||{url:candidate.url};
   // Search/detail creation timestamps take precedence over "edited at" text.
   raw={...raw,title:dom.title||raw.title,content:dom.content,images:dom.images,authorName:raw.authorName||dom.authorName,authorUrl:raw.authorUrl||dom.authorUrl,publishedDate:raw.publishedDate||dateValue(dom.publishedMeta)||(/发布于/.test(dom.publishedText)?dateValue(dom.publishedText):null),voteCount:raw.voteCount??count(dom.voteText),publishedText:dom.publishedText};
   if(!raw.content)throw new Error('DETAIL_CONTENT_MISSING');if(!raw.publishedDate)throw new Error('PUBLISHED_DATE_UNKNOWN');
   raw.authorId=raw.authorId||raw.authorUrl?.split('/').filter(Boolean).at(-1)||null;
   return {page,raw};
  }catch(e){await page.close();throw e;}finally{page.off('response',listen);}
 }
 async comments(page,post,task,checkpoint,guard,delay){
  let expected=post['文章评论数'];if(expected===0)return true;
  const records=new Map();const roots=new Set();const replyEnds=new Set();const unknownReplies=new Set();let rootEnd=false;let responseSeen=false;const jobs=[];
  const consume=(url,j)=>{
    const numeric=post['文章id'].replace(/^(answer|article)-/,'');
    const child=url.match(/\/(?:comment_v5\/)?comments?\/(\d+)\/(?:child_comment|repl)/);
    if(child&&!roots.has(child[1]))return;
    if(!child&&!new RegExp('/(?:articles|answers)/'+numeric+'/(?:root_comment|comments)(?:[/?]|$)').test(url))return;
    responseSeen=true;const end=j.paging?.is_end===true;
    if(child&&end)replyEnds.add(child[1]);else if(end&&!child)rootEnd=true;
    walk(j,e=>{if(!e.id||typeof e.content!=='string'||!e.author)return;const author=e.author.member||e.author;const token=author.url_token||author.urlToken;const raw={id:String(e.id),content:e.content,authorId:author.id,authorName:author.name,authorUrl:token?'https://www.zhihu.com/people/'+token:null,date:dateValue(e.created_time||e.createdTime),voteCount:e.vote_count??e.like_count,replyCount:e.child_comment_count??e.reply_count,parentId:e.reply_to_comment_id||null};records.set(raw.id,raw);if(!child&&raw.replyCount==null)unknownReplies.add(raw.id);if(count(raw.replyCount)>0)roots.add(raw.id);});
  };
  const listener=response=>{
   const url=response.url();if(!/\/comment_v5\/|\/comments\b|\/root_comment\b|\/child_comment\b/.test(url))return;
   jobs.push(response.json().then(j=>consume(url,j)).catch(()=>{}));
  };page.on('response',listener);
  for(const saved of this.commentCaptures.get(page)||[])consume(saved.url,saved.json);
  try{
   const button=page.getByRole('button',{name:/\d.*条评论|添加评论|展开评论|查看全部.*评论/});if(!responseSeen){if(!await button.count())return false;await guard();await button.first().click();}
   let stagnant=0,last=0,round=0;
   while(true){
    await guard();await delay([1800,3000]);await this.gate(page);await Promise.all(jobs);
    const htmlRecords=[...records.values()];for(const raw of htmlRecords){const text=await page.evaluate(html=>{const d=new DOMParser().parseFromString(html,'text/html');return d.body.textContent||'';},raw.content);const normalized={...raw,content:text};const row=commentRow(normalized,post,task);checkpoint.save('comment',row['文章id']+':'+raw.id,row,raw);}
    if(responseSeen&&rootEnd&&unknownReplies.size===0&&[...roots].every(id=>replyEnds.has(id)||count(records.get(id)?.replyCount)===0))return true;
    if(records.size===last)stagnant++;else stagnant=0;last=records.size;
    if(stagnant>=8||this.config.maxCommentPages>0&&++round>=this.config.maxCommentPages)return false;
    const replies=page.getByRole('button',{name:/查看.*(?:条回复|条回覆)|展开.*回复|加载更多回复/});if(await replies.count()){await replies.first().click();continue;}
    const next=page.getByRole('button',{name:/^(下一页|加载更多评论)$/});if(await next.count()&&await next.last().isEnabled()){await next.last().click();continue;}
    const panel=page.locator('.CommentsV2-body,.CommentListV2,.Comments-container').last();if(await panel.count())await panel.hover();await page.mouse.wheel(0,700);
   }
  }finally{page.off('response',listener);await Promise.all(jobs);}
 }
 async author(url){
  if(!/^https:\/\/www\.zhihu\.com\/(people|org)\/[\w-]+$/.test(url))return null;const page=await this.context.newPage();
  try{await this.navigate(page,url);return await page.evaluate(()=>{const text=document.querySelector('.Profile-sideColumn')?.innerText||'';const followers=document.querySelector('a[href$="/followers"] .NumberBoard-itemValue')?.textContent;return {followers:followers||null,votes:text.match(/获得\s*([\d,.万亿]+)\s*次赞同/)?.[1]||null};});}finally{await page.close();}
 }
 async diagnose(dir,error){await fs.mkdir(dir,{recursive:true});if(this.search&&!this.search.isClosed())await this.search.screenshot({path:path.join(dir,'failure.png'),fullPage:false}).catch(()=>{});await fs.writeFile(path.join(dir,'error.txt'),String(error.message||error),'utf8');}
 close(){return this.context.close();}
}
