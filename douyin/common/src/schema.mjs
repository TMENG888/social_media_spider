import crypto from "node:crypto";

export const POST_FIELDS = [
  "id", "文章图片链接", "文章图片信息", "作者名字", "文章标题", "文章内容", "文章标签",
  "文章时间地点", "文章点赞数", "文章收藏数", "文章评论数", "文章链接", "文章id", "作者主页链接",
  "文章视频链接", "文章视频内容", "关键词", "作者id", "作者粉丝数", "作者点赞数", "文章分享数",
  "文章视频时长", "平台", "文章获取时间", "文章标注", "分类", "清洗标注", "项目", "地点",
  "内容类型", "是否广告", "广告关键词"
];

export const COMMENT_FIELDS = [
  "id", "评论id", "评论用户链接", "评论用户id", "评论用户名字", "评论内容", "评论时间", "评论IP",
  "评论点赞数", "评论回复数", "文章链接", "文章id", "关键词", "评论获取时间", "平台", "分类", "项目", "清洗标注"
];

export function blankRecord(fields) {
  return Object.fromEntries(fields.map((field) => [field, null]));
}

export function stableId(text) {
  return crypto.createHash("sha256").update(String(text)).digest("hex").slice(0, 24);
}

export function normalizeDouyinUrl(value) {
  if (!value) return null;
  const url = new URL(value, "https://www.douyin.com");
  if(url.hostname!=='www.douyin.com') throw new Error('DOUYIN_URL_HOST_MISMATCH');
  url.search=''; url.hash='';
  return url.toString();
}

/** A canonical detail URL must match the decimal Douyin aweme_id. */
export function canonicalDouyinPostUrl(articleId, candidateUrl = null) {
  const id = String(articleId || extractId(candidateUrl) || "").trim();
  if (!/^\d{15,22}$/.test(id)) throw new Error(`DOUYIN_ARTICLE_ID_INVALID: ${id}`);
  return `https://www.douyin.com/video/${id}`;
}

export function extractId(value, type = "note") {
  const text = String(value || "");
  if (type === "user") return text.match(/\/user\/([^/?#]+)/i)?.[1] || null;
  return text.match(/\/(?:video|note)\/(\d{15,22})/i)?.[1] || text.match(/[?&]modal_id=(\d{15,22})/)?.[1] || null;
}

