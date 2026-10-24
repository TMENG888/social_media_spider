import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {canonical,dateValue,postRow,commentRow,Checkpoint,loadManifest} from './core.mjs';
import {fromEntity} from './browser.mjs';
const task={keyword:'中海 住宅',projectName:'全国地产设计产品力监测'};
test('answer/article IDs never collide and links reject external hosts',()=>{
 assert.equal(canonical('https://www.zhihu.com/question/1/answer/42?x=1').id,'answer-42');
 assert.equal(canonical('https://zhuanlan.zhihu.com/p/42').id,'article-42');
 assert.equal(canonical('https://evil.test/question/1/answer/42'),null);
 assert.equal(canonical('https://www.zhihu.com/question/1'),null);
 assert.equal(canonical('https://www.zhihu.com.evil.test/question/1/answer/42'),null);
});
test('creation dates are validated and edited-only dates cannot be invented',()=>{
 assert.equal(dateValue('发布于 2026-2-3'),'2026-02-03');assert.equal(dateValue('2026-02-30'),null);assert.equal(dateValue('2026-99-99'),null);assert.equal(dateValue('昨天'),null);
 const c=canonical('https://zhuanlan.zhihu.com/p/42');const r=fromEntity({id:42,type:'article',updated:1770000000,content:'text'},c);assert.equal(r.publishedDate,null);
 assert.equal(fromEntity({id:43,type:'article',created:1770000000},c),null);
});
test('mapping preserves full text, topic rules and null values',()=>{
 const row=postRow({url:'https://zhuanlan.zhihu.com/p/42',title:'标题😀',content:'住宅正文😀',publishedDate:'2026-02-03',voteCount:'1.2万'},task);
 assert.equal(row['平台'],'知乎');assert.equal(row['分类'],null);assert.equal(row['文章内容'],'住宅正文');assert.equal(row['文章点赞数'],12000);assert.equal(row['文章视频内容'],null);
 const comment=commentRow({id:'c7',content:'回复😀'},row,task);assert.equal(comment['评论内容'],'回复');assert.equal(comment['文章id'],'article-42');
});
test('SQLite restart preserves records, audit, export and import state',async()=>{
 const base=process.env.ZHIHU_TEST_ROOT||'E:/Codex/work/2026-10-19-zhihu-rpa/tests';await fs.mkdir(base,{recursive:true});const dir=await fs.mkdtemp(path.join(base,'cp-'));const file=path.join(dir,'checkpoint.sqlite');
 let cp=new Checkpoint(file);const row=postRow({url:'https://zhuanlan.zhihu.com/p/42',title:'a',content:'b',publishedDate:'2026-01-01'},task);cp.save('post','article-42',row,{source:'fixture'});cp.evidence('article-42',{status:'collected'});cp.close();
 cp=new Checkpoint(file);assert.equal(cp.rows('post').length,1);assert.equal(cp.observed('article-42').status,'collected');assert.equal(cp.rows('post',true).length,1);cp.markImported();assert.equal(cp.rows('post',true).length,0);await cp.export(path.join(dir,'export'));assert.match(await fs.readFile(path.join(dir,'export/ods_social_media_post.csv'),'utf8'),/文章内容/);cp.close();
});
test('deployment manifest exactly matches the selected four-project task scope',{skip:!process.env.ZHIHU_TEST_MANIFEST},async()=>{
 const m=await loadManifest(process.env.ZHIHU_TEST_MANIFEST);assert.equal(m.taskCount,56);assert.deepEqual(m.topicCounts,{'专题二':56});assert.equal(m.tasks[0].keyword,'建发海晏');assert(m.tasks.filter(t=>t.topic==='专题二').every(t=>t.collectComments));
});
