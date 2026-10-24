import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {collect} from './collector.mjs';
import {Checkpoint,canonical} from './core.mjs';
async function fixture(t,{noGrowth=false,detailError=false,commentOK=true,topic='专题一'}={}){
 const base=process.env.ZHIHU_TEST_ROOT||'E:/Codex/work/zhihu-rpa-tests';await fs.mkdir(base,{recursive:true});const dir=await fs.mkdtemp(path.join(base,'scan-'));const cp=new Checkpoint(path.join(dir,'state.sqlite'));t.after(()=>cp.close());let flushes=0;
 const browser={search:{},startSearch:async()=>({sorted:true}),gate:async()=>{},candidates:async()=>[canonical('https://zhuanlan.zhihu.com/p/42')],detail:async()=>{if(detailError)throw new Error('PUBLISHED_DATE_UNKNOWN');return {raw:{url:'https://zhuanlan.zhihu.com/p/42',publishedDate:'2026-01-01',content:'正文',title:'标题',commentCount:2},page:{close:async()=>{}}};},searchEnd:async()=>!noGrowth,scrollSearch:async()=>{},comments:async()=>commentOK};
 const task={id:'fixture',keyword:'中海 住宅',projectName:'全国地产设计产品力监测',targetYear:2026,cutoff:'2026-01-01',topic,collectComments:topic==='专题二'};
 const result=await collect({browser,task,checkpoint:cp,config:{importBatchSize:20,detailDelayMs:[0,0],scrollDelayMs:[0,0],maxStagnantRounds:2,collectAuthors:false},guard:async()=>{},delay:async()=>{},flush:async()=>{flushes++;}});return {result,cp,flushes};
}
test('explicit end completes and checkpoint saves each full record',async t=>{const {result,cp}=await fixture(t);assert.equal(result.scanComplete,true);assert.equal(result.unresolved,0);assert.equal(cp.rows('post').length,1);});
test('lack of growth cannot certify full collection',async t=>{const {result}=await fixture(t,{noGrowth:true});assert.equal(result.scanComplete,false);assert.equal(result.stopReason,'platform_no_growth');});
test('unknown date prevents successful completion',async t=>{const {result}=await fixture(t,{detailError:true});assert.equal(result.unresolved,1);});
test('topic two partial comments remain unresolved',async t=>{const {result}=await fixture(t,{topic:'专题二',commentOK:false});assert.equal(result.commentsComplete,false);assert.equal(result.unresolved,1);});
