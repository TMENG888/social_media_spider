import {AsyncLocalStorage} from 'node:async_hooks';
import {performance} from 'node:perf_hooks';
export const FRONTEND_BUDGET_VERSION='single-content-foreground-15min-20261108-v1';
export const FRONTEND_LIMIT_MS=15*60*1000;
const storage=new AsyncLocalStorage();
export class ForegroundBudget {
 constructor({limitMs=FRONTEND_LIMIT_MS,now=()=>performance.now(),articleId}={}){
  if(!Number.isFinite(limitMs)||limitMs<=0)throw new Error('INVALID_FOREGROUND_BUDGET');
  Object.assign(this,{limitMs,now,articleId,start:now(),excludedMs:0,depth:0,holdStart:0});
 }
 elapsed(){return Math.max(0,this.now()-this.start-this.excludedMs-(this.depth?this.now()-this.holdStart:0));}
 evidence(){return {policy:FRONTEND_BUDGET_VERSION,articleId:this.articleId,limitMs:this.limitMs,activeMs:this.elapsed(),excludedMs:this.excludedMs,frontendCompleted:true,allItemsCollected:false,reason:'foreground_timeout'};}
 error(){return Object.assign(new Error('CONTENT_FOREGROUND_TIMEOUT：单篇前台采集达到15分钟，保留已采内容并继续下一篇'),{code:'CONTENT_FOREGROUND_TIMEOUT',foregroundCompletion:this.evidence()});}
 check(){if(this.elapsed()>=this.limitMs)throw this.error();}
 async suspend(fn){if(this.depth++===0)this.holdStart=this.now();try{return await fn();}finally{if(--this.depth===0)this.excludedMs+=Math.max(0,this.now()-this.holdStart);}}
}
export const currentForegroundBudget=()=>storage.getStore();
export const checkForegroundBudget=()=>storage.getStore()?.check();
export const withoutForegroundBudget=fn=>storage.run(undefined,fn);
export const suspendForegroundBudget=fn=>storage.getStore()?.suspend(fn)??fn();
export const isForegroundTimeout=error=>error?.code==='CONTENT_FOREGROUND_TIMEOUT';
export const frontendClosed=result=>result?.audit?.foregroundCompletion?.frontendCompleted===true||result?.foregroundCompletion?.frontendCompleted===true;
export async function withForegroundBudget(budget,fn){
 return storage.run(budget,async()=>{budget.check();try{const result=await fn();try{budget.check();}catch(error){error.partialResult=result;throw error;}return result;}catch(error){
  // A timeout caused by our clamped browser action is the same item deadline.
  if(!isForegroundTimeout(error)&&budget.elapsed()>=budget.limitMs&&!/STOP_|LEASE_LOST/.test(String(error?.code||'')+' '+String(error?.message||'')))throw Object.assign(budget.error(),{cause:error});
  throw error;
 }});
}
const optionsAt={goto:1,reload:0,goBack:0,goForward:0,waitForURL:1,waitForLoadState:1,waitForSelector:1,click:0,dblclick:0,hover:0,focus:0,fill:1,press:1,type:1,check:0,uncheck:0,setChecked:1,selectOption:1,scrollIntoViewIfNeeded:0,waitFor:0,textContent:0,innerText:0,inputValue:0,getAttribute:1,isVisible:0,isHidden:0,screenshot:0,waitForFunction:2,waitForResponse:1,waitForRequest:1,waitForEvent:1};
export function foregroundActionArgs(key,args,kind){
 const budget=currentForegroundBudget();if(!budget)return args;budget.check();const remaining=Math.max(1,Math.ceil(budget.limitMs-budget.elapsed()));
 if(key==='waitForTimeout')return [Math.min(Number(args[0])||0,remaining),...args.slice(1)];
 const pageOptions={click:1,dblclick:1,hover:1,focus:1,fill:2,press:2,type:2,check:1,uncheck:1,setChecked:2,selectOption:2,textContent:1,innerText:1,inputValue:1,getAttribute:2,isVisible:1,isHidden:1};
 const index=['Page','Frame'].includes(kind)&&key in pageOptions?pageOptions[key]:optionsAt[key];if(index===undefined)return args;
 const result=[...args],opts=args[index];if(opts!=null&&(typeof opts!=='object'||Array.isArray(opts)))return args;
 result[index]={...opts,timeout:Math.min(Number(opts?.timeout)>0?Number(opts.timeout):30000,remaining)};return result;
}
