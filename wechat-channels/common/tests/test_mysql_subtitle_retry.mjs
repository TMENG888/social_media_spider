import assert from 'node:assert/strict';
import {selector,lookup,updateSubtitle,textHash} from '../src/mysql-subtitle-retry.mjs';
const row={id:'123456789012345678',平台:'微信视频号',项目:'专题一',文章id:'finder123',文章链接:'https://weixin.qq.com/sph/Test123',作者名字:'作者甲',文章标题:'真实标题',文章视频内容:'旧字幕',文章点赞数:9};
function database() {
  const db={row:{...row},commits:0,rollbacks:0,updates:0};
  db.beginTransaction=async()=>{db.original={...db.row};};
  db.commit=async()=>{db.commits++;};
  db.rollback=async()=>{db.row=db.original;db.rollbacks++;};
  db.execute=async(sql,args)=>{
    if(sql.startsWith('SELECT')) return [[{...db.row}]];
    assert.ok(sql.startsWith('UPDATE'));assert.ok(!sql.includes('INSERT'));db.updates++;
    db.row['文章视频内容']=args[0];return [{affectedRows:1}];
  };return db;
}
const request={platform:'微信视频号',project:'专题一',articleId:'finder123',expectedAuthor:'作者甲',approved:true,subtitle:'新的正常字幕',expectedOldHash:textHash('旧字幕')};
assert.throws(()=>selector({platform:'微信视频号',project:'专题一',title:'真实标题'}),/forbidden/);
assert.throws(()=>selector({...request,platform:'公众号'}),/platform/);
let db=database();await assert.rejects(lookup(db,{...request,expectedAuthor:'作者乙'}),/mismatch/);
db=database();await assert.rejects(updateSubtitle(db,{...request,expectedOldHash:'outdated'},async()=>{}),/changed/);assert.equal(db.updates,0);
db=database();await assert.rejects(updateSubtitle(db,request,async()=>{throw Error('disk failed');}),/disk failed/);assert.equal(db.updates,0);
db=database();await assert.rejects(updateSubtitle(db,{...request,subtitle:''},async()=>{}),/nonempty/);
db=database();const backups=[];const result=await updateSubtitle(db,request,async old=>backups.push(old));
assert.equal(result.committed,true);assert.equal(result.readbackVerified,true);assert.equal(db.commits,1);
assert.equal(backups[0].oldSubtitle,'旧字幕');assert.equal(db.row['文章点赞数'],9);assert.equal(db.row['文章视频内容'],'新的正常字幕');
console.log('7 mocked DB boundary scenarios passed; not a live MySQL test.');
