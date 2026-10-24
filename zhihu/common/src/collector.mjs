import fs from 'node:fs/promises';
import {postRow} from './core.mjs';
export async function collect({browser,task,checkpoint,config,guard,delay,flush,smokeLimit=0}){
 const result={scanComplete:false,commentsComplete:true,persisted:false,unresolved:0,stopReason:null,visited:0,posts:0};
 const unresolved=new Set();const visited=new Set();let stale=0;let rounds=0;let dirty=0;
 const sorting=await browser.startSearch(task.keyword);checkpoint.meta('search',{keyword:task.keyword,sorted:sorting.sorted,started:new Date().toISOString()});
 // Zhihu's latest order may use update time. Scan to an explicit end instead of
 // treating eight old creation dates as proof that the rest are out of scope.
 while(true){
  await guard();await browser.gate(browser.search);const candidates=await browser.candidates();const fresh=candidates.filter(c=>!visited.has(c.id));
  for(const candidate of fresh){
   await guard();visited.add(candidate.id);result.visited++;
   const known=checkpoint.observed(candidate.id);
   if(known?.status==='excluded_date'||known?.status==='collected'){continue;}
   let detail;
   try{
    detail=await browser.detail(candidate);const {raw,page}=detail;const inYear=raw.publishedDate.startsWith(String(task.targetYear)+'-')&&raw.publishedDate>=task.cutoff;
    if(!inYear){checkpoint.evidence(candidate.id,{id:candidate.id,status:'excluded_date',date:raw.publishedDate,url:candidate.url});continue;}
    const post=postRow(raw,task);checkpoint.save('post',candidate.id,post,raw);
    let complete=true;
    if(task.collectComments)complete=await browser.comments(page,post,task,checkpoint,guard,delay);
    checkpoint.evidence(candidate.id,{id:candidate.id,status:complete?'collected':'comments_incomplete',date:raw.publishedDate,url:candidate.url,commentsComplete:complete});
    if(!complete){result.commentsComplete=false;unresolved.add(candidate.id);}
    result.posts++;dirty++;
    if(dirty>=config.importBatchSize){await flush();dirty=0;}
    if(smokeLimit&&result.posts>=smokeLimit){result.stopReason='sample_limit';break;}
   }catch(e){
    if(/STOP_REQUESTED|LEASE|RISK_CONTROLLED|LOGIN_REQUIRED|MYSQL_|REDIS_/.test(e.message))throw e;
    checkpoint.evidence(candidate.id,{id:candidate.id,status:'unresolved',error:e.message,url:candidate.url});unresolved.add(candidate.id);console.warn('[详情未完成]',candidate.id,e.message);
   }finally{if(detail)await detail.page.close();}
   await delay(config.detailDelayMs);
  }
  if(result.stopReason)break;
  if(await browser.searchEnd()){result.scanComplete=true;result.stopReason='explicit_search_end';break;}
  if(fresh.length===0)stale++;else stale=0;
  if(stale>=config.maxStagnantRounds){result.stopReason='platform_no_growth';break;}
  if(config.maxSearchScrolls>0&&++rounds>=config.maxSearchScrolls){result.stopReason='scroll_limit';break;}
  await browser.scrollSearch();await delay(config.scrollDelayMs);
 }
 result.unresolved=unresolved.size;await flush();
 // The worker publishes distinct author URLs to a second Redis pool. Profiles
 // are processed only after all global post tasks have completed.
 await flush();result.persisted=true;checkpoint.meta('lastResult',result);return result;
}
