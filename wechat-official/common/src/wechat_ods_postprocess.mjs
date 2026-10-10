import fs from "node:fs";
import crypto from "node:crypto";
import { cleanText, extractHashtags, normalizeTags } from "./text-cleaner.mjs";
import { dedupePostsGlobal, relinkAndDedupeComments } from "./wechat-dedupe.mjs";

const inputPath = process.argv[2] || "outputs/wechat_20260918_test/ods_social_media_post_wechat.jsonl";
const enrichmentPath = process.argv[3] || inputPath.replace(/\.jsonl$/i, "_browser_enrichment.jsonl");
const outputPath = process.argv[4] || inputPath.replace(/\.jsonl$/i, "_cleaned.jsonl");
const collectComments = process.argv.includes("--comments");
let records = fs.readFileSync(inputPath, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
const enrichment = new Map(fs.readFileSync(enrichmentPath, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse).map((item) => [item.url, item]));
const odsFields = ["id","文章图片链接","文章图片信息","作者名字","文章标题","文章内容","文章标签","文章时间地点","文章点赞数","文章收藏数","文章评论数","文章链接","文章id","作者主页链接","文章视频链接","文章视频内容","关键词","作者id","作者粉丝数","作者点赞数","文章分享数","文章视频时长","平台","文章获取时间","文章标注","分类","清洗标注","项目","地点","内容类型","是否广告","广告关键词"];

const hashtagPattern = /(?<![A-Za-z0-9_])#((?:[\p{L}_][^#\s,，;；.!！?？、]{0,49})|(?:\d{2,}[\p{L}\p{N}_·-]{0,48}))/gu;
const cpLength = (value) => [...String(value ?? "")].length;
const commentFields = ["id", "评论id", "评论用户链接", "评论用户id", "评论用户名字", "评论内容", "评论时间", "评论IP", "评论点赞数", "评论回复数", "文章链接", "文章id", "关键词", "评论获取时间", "平台", "分类", "项目", "清洗标注"];
const parseCount = (value) => {
  const text = String(value ?? "").replaceAll(",", "").trim();
  if (!text || /^(赞|回复|评论|-)$/.test(text)) return text === "赞" ? 0 : null;
  const match = text.match(/([\d.]+)\s*([万wWkK])?/);
  if (!match) return null;
  const factor = /万/i.test(match[2] || "") ? 10000 : /k/i.test(match[2] || "") ? 1000 : 1;
  return Math.round(Number(match[1]) * factor);
};
const cleanComment = (raw) => {
  const source = String(raw || "");
  const cleaned = cleanText(source, { removeEmoji: true });
  const compact = cleaned.text.replace(/[\t ]+/g, " ").split(/\r?\n/).map((x) => x.trim()).filter(Boolean).join("，").replace(/，{2,}/g, "，").trim();
  return { text: compact || null, stats: { ...cleaned.stats, 清理后文字数: cpLength(compact) } };
};

function cleanCompactContent(raw) {
  // Remove only WeChat's own UI text. Publisher-authored calls to action,
  // disclaimers and contact details are genuine source content and must stay.
  const source = String(raw || "")
    .replace(/，?\s*时长\s*\n?\s*\d{1,2}:\d{2}(?::\d{2})?/gu, "")
    .split(/\r?\n/)
    .filter((line) => !/^\s*(?:继续滑动看下一个|向上滑动看下一个|阅读原文|写留言|暂无留言)\s*$/u.test(line))
    .join("\n");
  const tags = normalizeTags(extractHashtags(source));
  // Keep the extracted tag text in the article body, but remove hashtag marks.
  // This also handles paired forms such as “#标签#”: the regex consumes the
  // opening mark and the final replace removes the closing (and any other)
  // hash marks left in the visible article text.
  const body = source.replace(hashtagPattern, "$1").replace(/#/gu, "");
  const cleaned = cleanText(body, { removeEmoji: true });
  const compact = cleaned.text.replace(/[\t\r\n]+/g, "").replace(/ {2,}/g, " ").trim();
  const compactRemoved = cpLength(cleaned.text) - cpLength(compact);
  return {
    content: compact || null,
    tags,
    stats: {
      ...cleaned.stats,
      清理后文字数: cpLength(compact),
      其他字符个数: cleaned.stats.其他字符个数 + Math.max(0, compactRemoved),
    },
  };
}

function isArticleImageUrl(value) {
  if (!value || /^(?:data:|blob:|javascript:|about:)/i.test(value)) return false;
  try {
    const parsed = new URL(value);
    if (!/^https?:$/.test(parsed.protocol)) return false;
    if (parsed.hostname === "mp.weixin.qq.com" && /^\/s(?:\/|$)/.test(parsed.pathname)) return false;
    return /(?:^|\.)(?:[^.]*_)?(?:mmbiz|mmecoa)\.qpic\.cn$/i.test(parsed.hostname)
      || /\.(?:avif|bmp|gif|jpe?g|png|svg|webp)(?:$|[?#])/i.test(parsed.href);
  } catch {
    return false;
  }
}

function chooseCleanedContent(browserContent, collectorContent) {
  const browser = cleanCompactContent(browserContent);
  const collector = cleanCompactContent(collectorContent);
  // Prefer the browser DOM, but never replace a useful collector body with a
  // transiently empty/short browser result. No text is fabricated.
  if (!browser.content) return collector;
  if (collector.content && cpLength(browser.content) < 40 && cpLength(collector.content) > cpLength(browser.content) * 2) return collector;
  return browser;
}

for (const record of records) {
  const extra = enrichment.get(record["文章链接"]);
  // Clean the collector fallback too. A transient browser failure must not
  // leave one anomalous row with line breaks or stale auxiliary fields.
  const cleaned = extra?.ok
    ? chooseCleanedContent(extra.content, record["文章内容"])
    : cleanCompactContent(record["文章内容"]);
  if (!extra?.ok) {
    record["文章内容"] = cleaned.content;
    record["文章标签"] = cleaned.tags;
    record["文章图片信息"] = null;
    record["文章视频内容"] = null;
    record["清洗标注"] = JSON.stringify(cleaned.stats);
    record["内容类型"] = record["文章视频链接"] ? "视频" : "纯文本";
    if (collectComments && extra?.commentCountVisible != null) record["文章评论数"] = extra.commentCountVisible;
    continue;
  }
  const images = [...new Map((extra.images || []).filter((item) => isArticleImageUrl(item.url)).map((item) => [item.url, item])).values()];
  const videoKey = (item) => {
    try {
      const parsed = new URL(item.url);
      return parsed.searchParams.get("vid") || `${parsed.origin}${parsed.pathname}`;
    } catch {
      return item.url;
    }
  };
  const videos = [...new Map((extra.videos || []).filter((item) => item.url && Number(item.duration) > 0).map((item) => [videoKey(item), item])).values()];
  record["作者名字"] = extra.author || record["作者名字"];
  record["文章标题"] = extra.title || record["文章标题"];
  record["文章内容"] = cleaned.content;
  record["文章标签"] = cleaned.tags;
  record["文章图片链接"] = images.length ? JSON.stringify(images.map((item) => item.url)) : null;
  // ODS requirement: keep the image-detail field empty. Image URLs remain
  // available in 文章图片链接; the auxiliary metadata is intentionally not
  // exported to avoid mixing DOM dimensions/alt text with business data.
  record["文章图片信息"] = null;
  record["作者主页链接"] = extra.authorUrl || null;
  record["文章视频链接"] = videos.length ? JSON.stringify(videos.map((item) => item.url)) : null;
  record["文章视频内容"] = extra.videoContent || null;
  record["文章视频时长"] = videos.some((item) => item.duration != null) ? JSON.stringify(videos.map((item) => item.duration)) : null;
  record["清洗标注"] = JSON.stringify(cleaned.stats);
  record["内容类型"] = videos.length ? "视频" : images.length ? "图文" : "纯文本";
  if (collectComments && extra.commentCountVisible != null) record["文章评论数"] = extra.commentCountVisible;
}

const sourceRecords = records;
const deduped = dedupePostsGlobal(sourceRecords);
records = deduped.records;
const dedupeAuditPath = outputPath.replace(/\.jsonl$/i, "_dedupe_audit.jsonl");
fs.writeFileSync(dedupeAuditPath, deduped.audit.map((item) => JSON.stringify(item)).join("\n") + (deduped.audit.length ? "\n" : ""));

const comments = [];
const commentAudits = [];
let exportedCommentCount = 0;
if (collectComments) {
  for (const record of sourceRecords) {
    const extra = enrichment.get(record["文章链接"]);
    commentAudits.push({
      article_url: record["文章链接"],
      article_id: record["文章id"] || null,
      visible_comment_count: extra?.commentCountVisible ?? null,
      extracted_comment_count: extra?.comments?.length || 0,
      status: extra?.comments?.length ? "visible_comments_extracted" : (extra?.commentCountVisible ? "count_visible_detail_unavailable" : "no_visible_comments"),
      reason: extra?.commentCountVisible && !extra?.comments?.length ? "公众号页面仅返回留言数量，留言明细未在公开DOM中展开" : null,
    });
    for (const item of extra?.comments || []) {
      const cleaned = cleanComment(item.content);
      if (!cleaned.text) continue;
      comments.push({
        id: null,
        评论id: item.commentId || null,
        评论用户链接: item.userUrl || null,
        评论用户id: item.userId || null,
        评论用户名字: item.userName || null,
        评论内容: cleaned.text,
        评论时间: item.time || null,
        评论IP: item.ip || null,
        评论点赞数: parseCount(item.likeCount),
        评论回复数: parseCount(item.replyCount),
        文章链接: record["文章链接"],
        文章id: record["文章id"] || null,
        关键词: record["关键词"] || null,
        评论获取时间: new Date().toISOString(),
        平台: "微信公众号",
        分类: record["分类"] || null,
        项目: record["项目"] || null,
        清洗标注: JSON.stringify(cleaned.stats),
      });
    }
  }
  const commentDedupe = relinkAndDedupeComments(comments, deduped);
  const uniqueComments = commentDedupe.records;
  exportedCommentCount = uniqueComments.length;
  const commentJsonl = outputPath.replace(/\.jsonl$/i, "_comments.jsonl");
  const commentCsv = outputPath.replace(/\.jsonl$/i, "_comments.csv");
  const commentAuditPath = outputPath.replace(/\.jsonl$/i, "_comment_audit.jsonl");
  const quoteComment = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  fs.writeFileSync(commentJsonl, uniqueComments.map((item) => JSON.stringify(item)).join("\n") + (uniqueComments.length ? "\n" : ""));
  fs.writeFileSync(commentCsv, "\uFEFF" + commentFields.map(quoteComment).join(",") + "\n" + uniqueComments.map((row) => commentFields.map((field) => quoteComment(row[field])).join(",")).join("\n") + (uniqueComments.length ? "\n" : ""));
  fs.writeFileSync(commentAuditPath, commentAudits.map((item) => JSON.stringify(item)).join("\n") + (commentAudits.length ? "\n" : ""));
}

const headers = records.length ? Object.keys(records[0]) : odsFields;
const quote = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
const csvPath = outputPath.replace(/\.jsonl$/i, ".csv");
// On Windows, Excel or a file preview may keep the CSV locked. Check both
// outputs before writing either one so JSONL and CSV can never become a
// mismatched half-update.
for (const target of [outputPath, csvPath]) {
  if (!fs.existsSync(target)) continue;
  const handle = fs.openSync(target, "r+");
  fs.closeSync(handle);
}
fs.writeFileSync(outputPath, records.map((item) => JSON.stringify(item)).join("\n") + (records.length ? "\n" : ""));
fs.writeFileSync(csvPath, "\uFEFF" + headers.map(quote).join(",") + "\n" + records.map((record) => headers.map((field) => quote(record[field])).join(",")).join("\n") + (records.length ? "\n" : ""));
console.log(JSON.stringify({ records: records.length, duplicatesRemoved: deduped.audit.length, dedupeAuditPath, tagged: records.filter((r) => r["文章标签"]).length, images: records.filter((r) => r["文章图片链接"]).length, videos: records.filter((r) => r["文章视频链接"]).length, videoContent: records.filter((r) => r["文章视频内容"]).length, comments: exportedCommentCount, authorUrls: records.filter((r) => r["作者主页链接"]).length, outputPath, csvPath }, null, 2));
