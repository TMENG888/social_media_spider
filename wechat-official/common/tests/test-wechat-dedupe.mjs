import test from 'node:test';
import assert from 'node:assert/strict';
import {
  bodySimilarity,
  canonicalWechatUrl,
  dedupePostsGlobal,
  relinkAndDedupeComments,
} from '../src/wechat-dedupe.mjs';

const base = (overrides = {}) => ({
  id: overrides.id ?? null,
  平台: '微信公众号',
  文章id: null,
  文章链接: null,
  文章标题: '标题',
  文章内容: '这里是一段用于测试去重机制的公众号文章正文内容',
  文章时间地点: '2026-06-01 12:00:00',
  文章获取时间: '2026-09-24 10:00:00',
  关键词: '关键词A',
  项目: '专题一',
  ...overrides,
});

test('相同文章id跨项目只保留一条', () => {
  const result = dedupePostsGlobal([
    base({id:'1',文章id:'wx-1',项目:'专题一'}),
    base({id:'2',文章id:'wx-1',项目:'专题二'}),
  ]);
  assert.equal(result.records.length, 1);
  assert.equal(result.audit[0].reason, 'article_id');
});

test('相同标准链接跨关键词只保留一条', () => {
  const result = dedupePostsGlobal([
    base({id:'1',文章链接:'https://mp.weixin.qq.com/s/abc?from=timeline',关键词:'A'}),
    base({id:'2',文章链接:'http://mp.weixin.qq.com/s/abc',关键词:'B'}),
  ]);
  assert.equal(canonicalWechatUrl('http://mp.weixin.qq.com/s/abc?x=1'), 'https://mp.weixin.qq.com/s/abc');
  assert.equal(result.records.length, 1);
  assert.equal(result.audit[0].reason, 'article_url');
});

test('不同链接和作者但正文双向相似度超过80%时去重', () => {
  const content = Array.from({length:220}, (_, index) => String.fromCodePoint(0x4e00 + index)).join('');
  const changed = `${content.slice(0, 205)}这里替换十五字符内容`;
  const result = dedupePostsGlobal([
    base({id:'1',文章链接:'https://mp.weixin.qq.com/s/a',作者名字:'甲',文章内容:content}),
    base({id:'2',文章链接:'https://mp.weixin.qq.com/s/b',作者名字:'乙',文章内容:changed}),
  ]);
  assert.ok(bodySimilarity(content, changed) >= 0.8);
  assert.equal(result.records.length, 1);
  assert.equal(result.audit[0].reason, 'body_similarity');
});

test('短摘要包含于长正文不误删', () => {
  const longBody = Array.from({length:2820}, (_, index) => String.fromCodePoint(0x4e00 + (index % 2000))).join('');
  const excerpt = longBody.slice(500, 726);
  assert.ok(bodySimilarity(excerpt, longBody) < 0.8);
  assert.equal(dedupePostsGlobal([
    base({文章链接:'https://mp.weixin.qq.com/s/a',文章内容:excerpt}),
    base({文章链接:'https://mp.weixin.qq.com/s/b',文章内容:longBody}),
  ]).records.length, 2);
});

test('完全相同的极短正文仍会去重', () => {
  const result = dedupePostsGlobal([
    base({文章链接:'https://mp.weixin.qq.com/s/a',文章内容:'好房'}),
    base({文章链接:'https://mp.weixin.qq.com/s/b',文章内容:'好房'}),
  ]);
  assert.equal(result.records.length, 1);
  assert.equal(result.audit[0].reason, 'body_exact');
});

test('不同公众号相同标题但正文不同不会删除', () => {
  const result = dedupePostsGlobal([
    base({文章链接:'https://mp.weixin.qq.com/s/a',文章标题:'同名标题',文章内容:'甲方发布的正文完全不同一二三四五六'}),
    base({文章链接:'https://mp.weixin.qq.com/s/b',文章标题:'同名标题',文章内容:'乙方文章另有内容七八九十甲乙丙丁'}),
  ]);
  assert.equal(result.records.length, 2);
});

test('空正文只能按文章id或链接去重', () => {
  const result = dedupePostsGlobal([
    base({文章链接:'https://mp.weixin.qq.com/s/a',文章内容:null}),
    base({文章链接:'https://mp.weixin.qq.com/s/a?from=x',文章内容:''}),
    base({文章链接:'https://mp.weixin.qq.com/s/b',文章内容:null,文章标题:'相同标题'}),
  ]);
  assert.equal(result.records.length, 2);
});

test('保留发布时间最早的记录', () => {
  const result = dedupePostsGlobal([
    base({id:'20',文章链接:'https://mp.weixin.qq.com/s/a',文章内容:'完全相同正文',文章时间地点:'2026-08-01'}),
    base({id:'10',文章链接:'https://mp.weixin.qq.com/s/b',文章内容:'完全相同正文',文章时间地点:'2026-05-01'}),
  ]);
  assert.equal(result.records[0].id, '10');
  assert.equal(result.records[0].文章时间地点, '2026-05-01');
});

test('合并时补齐完整字段、互动数取最大且图片信息为空', () => {
  const result = dedupePostsGlobal([
    base({id:'1',文章id:'same',文章点赞数:2,文章评论数:0,文章视频内容:null,文章图片信息:'错误值'}),
    base({id:'2',文章id:'same',文章点赞数:8,文章评论数:3,文章视频内容:'ASR字幕',文章图片信息:'仍是错误值'}),
  ]);
  assert.equal(result.records[0].文章点赞数, 8);
  assert.equal(result.records[0].文章评论数, 3);
  assert.equal(result.records[0].文章视频内容, 'ASR字幕');
  assert.equal(result.records[0].文章图片信息, null);
});

test('评论跟随保留文章并按评论id去重', () => {
  const posts = dedupePostsGlobal([
    base({id:'1',文章id:'old',文章链接:'https://mp.weixin.qq.com/s/a',文章内容:'相同正文',文章时间地点:'2026-01-01'}),
    base({id:'2',文章id:'dup',文章链接:'https://mp.weixin.qq.com/s/b',文章内容:'相同正文',文章时间地点:'2026-02-01'}),
  ]);
  const comments = relinkAndDedupeComments([
    {id:'11',平台:'微信公众号',评论id:'c1',文章id:'old',文章链接:'https://mp.weixin.qq.com/s/a',评论内容:'支持',评论点赞数:1},
    {id:'12',平台:'微信公众号',评论id:'c1',文章id:'dup',文章链接:'https://mp.weixin.qq.com/s/b',评论内容:'支持',评论点赞数:9},
  ], posts);
  assert.equal(comments.records.length, 1);
  assert.equal(comments.records[0].文章id, 'old');
  assert.equal(comments.records[0].文章链接, 'https://mp.weixin.qq.com/s/a');
  assert.equal(comments.records[0].评论点赞数, 9);
});

