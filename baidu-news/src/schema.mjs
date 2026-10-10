import crypto from "node:crypto";

export const ODS_FIELDS = [
  "id", "文章图片链接", "文章图片信息", "作者名字", "文章标题", "文章内容", "文章标签",
  "文章时间地点", "文章点赞数", "文章收藏数", "文章评论数", "文章链接", "文章id", "作者主页链接",
  "文章视频链接", "文章视频内容", "关键词", "作者id", "作者粉丝数", "作者点赞数", "文章分享数",
  "文章视频时长", "平台", "文章获取时间", "文章标注", "分类", "清洗标注", "项目", "地点",
  "内容类型", "是否广告", "广告关键词"
];

export const ZERO_DEFAULT_FIELDS = [
  "文章点赞数", "文章收藏数", "文章评论数", "作者粉丝数", "作者点赞数", "文章分享数"
];

export function applyNumericDefaults(record) {
  for (const field of ZERO_DEFAULT_FIELDS) if (record[field] == null || record[field] === "") record[field] = 0;
  return record;
}

export function legacyStableBigInt(text) {
  const hex = crypto.createHash("sha256").update(text).digest("hex").slice(0, 15);
  return (BigInt(`0x${hex}`) % 9000000000000000n + 1000000000000000n).toString();
}

export function urlId(url) {
  return crypto.createHash("sha256").update(url).digest("hex").slice(0, 24);
}

export function toOdsRecord(parsed, context) {
  const canonicalUrl = parsed.canonicalUrl || context.url;
  const imageInfo = (parsed.images || []).map((url, index) => ({ index: index + 1, url }));
  const videos = parsed.videos || [];
  const contentType = videos.length ? "视频" : imageInfo.length ? "图文" : "纯文本";
  const record = Object.fromEntries(ODS_FIELDS.map((field) => [field, null]));
  Object.assign(record, {
    // 数据库表没有 AUTO_INCREMENT；id 在入库事务中按当前有效最大值 + 1 分配。
    id: null,
    文章图片链接: imageInfo.length ? JSON.stringify(imageInfo.map((item) => item.url)) : null,
    文章图片信息: null,
    作者名字: parsed.author || context.source || null,
    文章标题: parsed.title || context.title || null,
    文章内容: parsed.content || null,
    文章标签: null,
    文章时间地点: parsed.publishedAt || null,
    文章点赞数: parsed.likeCount ?? null,
    文章收藏数: parsed.favoriteCount ?? null,
    文章评论数: parsed.commentCount ?? null,
    文章链接: canonicalUrl,
    文章id: parsed.articleId || urlId(canonicalUrl),
    作者主页链接: parsed.authorUrl || null,
    文章视频链接: videos.length ? JSON.stringify(videos) : null,
    文章视频内容: null,
    关键词: context.query,
    作者id: parsed.authorId || null,
    作者粉丝数: parsed.authorFollowerCount ?? null,
    作者点赞数: parsed.authorLikeCount ?? null,
    文章分享数: parsed.shareCount ?? null,
    文章视频时长: parsed.videoDuration || null,
    平台: parsed.platform || context.source || new URL(canonicalUrl).hostname,
    文章获取时间: context.capturedAt,
    文章标注: null,
    分类: null,
    清洗标注: null,
    项目: context.projectName || "全国地产设计产品力监测",
    地点: null,
    内容类型: contentType,
    是否广告: null,
    广告关键词: null
  });
  return applyNumericDefaults(record);
}
