import test from 'node:test';import assert from 'node:assert/strict';
import {verifyCheckpoints} from '../src/verify-keyword-coverage.mjs';
import {transcriptArtifact} from '../src/transcript-quality.mjs';
import {cleanCompactContent,cleanVideoContent} from '../src/channels-field-normalization.mjs';
import fs from 'node:fs/promises';import os from 'node:os';import path from 'node:path';
import {execFileSync} from 'node:child_process';import {fileURLToPath} from 'node:url';
const cp={status:'completed',article_key:'id',project:'test',asr_status:'completed',row:{title:'title',url:'https://weixin.qq.com/sph/test',author_name:'author',video_content:'verified',video_duration:120}};
const actual=()=>({文章标题:'title',文章链接:cp.row.url,作者名字:'author',文章视频内容:'verified',文章视频时长:120});

test('database equality cannot launder subtitle artifacts, even after export cleaning',async()=>{
 for(const subtitle of ['人大附近中海住宅，中文字幕志愿者刘娅中文字幕组，近中海环宇城',
  '真实楼盘信息，请不吝点赞订阅转发打赏支持明镜与点点栏目',
  '真实口播，AMARA.ORG','真实口播，字幕 BY 索兰娅']){
  assert.ok(transcriptArtifact(subtitle));
  for(const stored of [subtitle,cleanVideoContent(subtitle).text]){
   const connection={query:async()=>[[]],execute:async()=>[[{...actual(),文章视频内容:stored}]]};
   assert.deepEqual((await verifyCheckpoints(connection,{fp:{...cp,row:{...cp.row,video_content:subtitle}}})).verifiedFingerprints,[]);
  }
 }
 for(const subtitle of ['字幕展示的是户型尺寸，客厅面宽六米','欢迎观看样板间，感谢大家支持','项目名为ONE，包含TOD商业'])assert.equal(transcriptArtifact(subtitle),null);
});
test('only unique exact database rows with matching subtitles and duration pass',async()=>{
 const connection={query:async()=>[[]],execute:async()=>[[actual()]]};
 assert.deepEqual((await verifyCheckpoints(connection,{fp:cp})).verifiedFingerprints,['fp']);
 connection.execute=async()=>[[{...actual(),文章视频内容:'wrong source'}]];
 assert.deepEqual((await verifyCheckpoints(connection,{fp:cp})).verifiedFingerprints,[]);
 connection.execute=async()=>[[actual(),actual()]];
 assert.deepEqual((await verifyCheckpoints(connection,{fp:cp})).verifiedFingerprints,[]);
 assert.deepEqual((await verifyCheckpoints(connection,{fp:{...cp,status:'skipped_unresolved'}})).verifiedFingerprints,[]);
});

test('the exact task can waive only unrequested comments, not another missing field',async()=>{
 const connection={query:async()=>[[]],execute:async()=>[[actual()]]};
 const checkpoint={...cp,field_completeness:{title:true,comments:false,asr:true}};
 assert.deepEqual((await verifyCheckpoints(connection,{fp:checkpoint})).verifiedFingerprints,[]);
 assert.deepEqual((await verifyCheckpoints(connection,{fp:checkpoint},{collectComments:false})).verifiedFingerprints,['fp']);
 checkpoint.field_completeness.duration=false;
 assert.deepEqual((await verifyCheckpoints(connection,{fp:checkpoint},{collectComments:false})).verifiedFingerprints,[]);
});

test('export cleaning and schema-declared compatibility are exact, never fuzzy source acceptance',async()=>{
 const checkpoint={...cp,row:{...cp.row,title:'标题🌟 #住宅#\n继续滑动看下一个',video_content:'真实字幕，\n下一段内容。'}};
 const canonical={...actual(),文章标题:cleanCompactContent(checkpoint.row.title).content,文章视频内容:cleanVideoContent(checkpoint.row.video_content).text};
 const connection={query:async()=>[[]],execute:async()=>[[canonical]]};
 assert.deepEqual((await verifyCheckpoints(connection,{fp:checkpoint})).verifiedFingerprints,['fp']);
 connection.execute=async()=>[[{...canonical,文章视频内容:'另一个视频的字幕'}]];
 assert.deepEqual((await verifyCheckpoints(connection,{fp:checkpoint})).verifiedFingerprints,[]);
 connection.execute=async()=>[[{...canonical,文章标题:'相似但不是同一标题'}]];
 assert.deepEqual((await verifyCheckpoints(connection,{fp:checkpoint})).verifiedFingerprints,[]);
 const supplementary={...cp,row:{...cp.row,title:'标题𠀀',author_name:'作者𠀀'}};
 connection.execute=async()=>[[{...actual(),文章标题:'标题',作者名字:'作者'}]];
 assert.deepEqual((await verifyCheckpoints(connection,{fp:supplementary})).verifiedFingerprints,[]);
 connection.query=async()=>[[{Field:'文章标题',Collation:'utf8mb3_general_ci'},{Field:'作者名字',Collation:'utf8mb3_general_ci'}]];
 assert.deepEqual((await verifyCheckpoints(connection,{fp:supplementary})).verifiedFingerprints,['fp']);
});

test('shared cleaning preserves the complete shipped postprocess output and dedupe evidence',{
 skip:!process.env.CHANNELS_REFERENCE_POSTPROCESS},async()=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'channels-clean-equivalence-'));
 try{
  const corpus=['普通中文标题','标题🌟 #住宅#\n继续滑动看下一个','&amp; 原文\t  保留', 'AAAAAA重复字',
   '标题，时长\n01:23\n阅读原文','发布者真实电话 13800000000 请联系','罕见字𠀀和🏠'];
  const rows=corpus.map((title,i)=>({文章标题:title,文章内容:'正文 #内容#',文章视频内容:`视频${i}，真实字幕内容。\n真实字幕内容。请点赞订阅转发打赏支持明镜与点点栏目`,文章链接:`https://weixin.qq.com/sph/Test000${i}`,文章id:String(i),作者名字:'fixture',平台:'微信视频号',项目:'fixture',文章视频时长:120,文章时间地点:'2026-10-01 00:00:00'}));
  const input=path.join(dir,'ods_social_media_post_channels.jsonl'),enrichment=path.join(dir,'enrichment.jsonl'),old=path.join(dir,'old.jsonl'),current=path.join(dir,'new.jsonl');
  await fs.writeFile(input,rows.map(r=>JSON.stringify(r)).join('\n')+'\n');await fs.writeFile(enrichment,'');
  execFileSync(process.execPath,[process.env.CHANNELS_REFERENCE_POSTPROCESS,input,enrichment,old],{windowsHide:true,timeout:10000});
  execFileSync(process.execPath,[fileURLToPath(new URL('../src/channels_ods_postprocess.mjs',import.meta.url)),input,enrichment,current],{windowsHide:true,timeout:10000});
  assert.equal(await fs.readFile(current,'utf8'),await fs.readFile(old,'utf8'));
  assert.equal(await fs.readFile(current.replace('.jsonl','_dedupe_audit.jsonl'),'utf8'),await fs.readFile(old.replace('.jsonl','_dedupe_audit.jsonl'),'utf8'));
 }finally{await fs.rm(dir,{recursive:true,force:true});}
});
