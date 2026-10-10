import fs from "node:fs";
import crypto from "node:crypto";
import { cleanText, extractHashtags, normalizeTags } from "./text-cleaner.mjs";
import { atomicWriteFileSync } from "./atomic-file.mjs";

const inputPath = process.argv[2] || "outputs/channels_test/ods_social_media_post_channels.jsonl";
const enrichmentPath = process.argv[3] || inputPath.replace(/\.jsonl$/i, "_browser_enrichment.jsonl");
const outputPath = process.argv[4] || inputPath.replace(/\.jsonl$/i, "_cleaned.jsonl");
const collectComments = process.argv.includes("--comments");
let records = fs.readFileSync(inputPath, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
const inputRecordCount = records.length;
const isChannelsShareUrl = (value) => {
  try {
    const parsed = new URL(String(value || ""));
    return (parsed.hostname === "weixin.qq.com" && parsed.pathname.startsWith("/sph/"))
      || (parsed.hostname === "channels.weixin.qq.com" && parsed.pathname.startsWith("/finder-preview/"));
  } catch { return false; }
};
records = records.filter((record) => isChannelsShareUrl(record["文章链接"]));
const invalidLinksRemoved = inputRecordCount - records.length;
const enrichment = new Map(fs.readFileSync(enrichmentPath, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse).map((item) => [item.url, item]));
const odsFields = ["id","文章图片链接","文章图片信息","作者名字","文章标题","文章内容","文章标签","文章时间地点","文章点赞数","文章收藏数","文章评论数","文章链接","文章id","作者主页链接","文章视频链接","文章视频内容","关键词","作者id","作者粉丝数","作者点赞数","文章分享数","文章视频时长","平台","文章获取时间","文章标注","分类","清洗标注","项目","地点","内容类型","是否广告","广告关键词"];

const hashtagPattern = /(?<![A-Za-z0-9_])#((?:[\p{L}_][^#\s,，;；.!！?？、]{0,49})|(?:\d{2,}[\p{L}\p{N}_·-]{0,48}))/gu;
const cpLength = (value) => [...String(value ?? "")].length;
const commentFields = ["id", "评论id", "评论用户链接", "评论用户id", "评论用户名字", "评论内容", "评论时间", "评论IP", "评论点赞数", "评论回复数", "文章链接", "文章id", "关键词", "评论获取时间", "平台", "分类", "项目", "清洗标注"];
const collectorCommentPath = inputPath.replace(/ods_social_media_post_channels\.jsonl$/i, "ods_social_media_comment_channels.jsonl");
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
const cleanVideoContent = (raw) => {
  const source = String(raw || "");
  const withoutBoilerplate = source.replace(/请(?:不吝)?点赞订阅转发打赏支持明镜与点点(?:栏目)?/gu, "");
  let deduped = withoutBoilerplate;
  for (let index = 0; index < 3; index += 1) {
    const collapsed = deduped.replace(/(.{6,}?[，。！？；])(?:\1)+/gu, "$1");
    if (collapsed === deduped) break;
    deduped = collapsed;
  }
  const clauses = deduped.split(/[，。！？；]+/gu).map((value) => value.trim()).filter(Boolean);
  const originalClauseCount = clauses.length;
  let changed = true;
  while (changed && clauses.length >= 2) {
    changed = false;
    for (let width = Math.floor(clauses.length / 2); width >= 1 && !changed; width -= 1) {
      for (let start = 0; start + width * 2 <= clauses.length; start += 1) {
        const left = clauses.slice(start, start + width).join("\u0000");
        const right = clauses.slice(start + width, start + width * 2).join("\u0000");
        if (left === right) {
          clauses.splice(start + width, width);
          changed = true;
          break;
        }
      }
    }
  }
  if (clauses.length !== originalClauseCount) deduped = clauses.join("，");
  const removedCount = Math.max(0, cpLength(source) - cpLength(deduped));
  const cleaned = cleanText(deduped, {
    removeEmoji: true,
    singleParagraph: true,
    paragraphSeparator: "，",
  });
  const text = cleaned.text.replace(/，{2,}/gu, "，").replace(/^，|，$/gu, "").trim();
  return {
    text: text || null,
    stats: {
      ...cleaned.stats,
      原始文字数: cpLength(source),
      清理后文字数: cpLength(text),
      其他字符个数: Number(cleaned.stats.其他字符个数 || 0) + removedCount,
      重复字符个数: Number(cleaned.stats.重复字符个数 || 0) + removedCount,
    },
  };
};
const emptyStats = () => ({ 原始文字数: 0, 清理后文字数: 0, 表情个数: 0, 其他字符个数: 0, 重复字符个数: 0 });
const aggregateCleaningStats = (...values) => values.reduce((total, value) => {
  const stats = value || emptyStats();
  for (const key of Object.keys(total)) total[key] += Number(stats[key] || 0);
  return total;
}, emptyStats());
const normalizePublishedAt = (raw) => {
  const text = String(raw || "").trim();
  const match = text.match(/^(20\d{2})年(\d{1,2})月(\d{1,2})日$/u);
  if (match) return `${match[1]}-${match[2].padStart(2, "0")}-${match[3].padStart(2, "0")} 00:00:00`;
  const iso = text.match(/^(20\d{2}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})/u);
  return iso ? `${iso[1]} ${iso[2]}` : null;
};
const usablePreviewTitle = (raw) => {
  const text = String(raw || "").trim();
  if (!text || /^(?:视频号|微信|搜一搜)$/u.test(text)) return null;
  return cleanCompactContent(text).content;
};

const normalizedBody = (value) => String(value || "")
  .toLowerCase()
  .replace(/[\u0000-\u001f\s]+/gu, "")
  .replace(/[，。！？；：、“”‘’（）()【】［］《》<>「」,.!?;:'"`~·—–_\-]/gu, "");
const shingles = (value, size = 5) => {
  const set = new Set();
  for (let i = 0; i + size <= value.length; i += 1) set.add(value.slice(i, i + size));
  return set;
};
function bodySimilarity(left, right) {
  const a = normalizedBody(left), b = normalizedBody(right);
  // There is no business-length threshold: every non-empty body is eligible.
  // Exact equality handles very short articles; shingle similarity is used
  // for longer bodies where an 80% overlap is measurable.
  if (!a || !b) return 0;
  if (a === b) return 1;
  if (Math.min(a.length, b.length) < 5) return 0;
  const sa = shingles(a), sb = shingles(b);
  if (!sa.size || !sb.size) return 0;
  let intersection = 0;
  for (const item of sa) if (sb.has(item)) intersection += 1;
  // Containment catches reposts with a short author intro or outro while the
  // small-length guard only excludes nearly empty bodies.
  return intersection / Math.min(sa.size, sb.size);
}

function dedupeByVideoContent(items) {
  // Keep the earliest published copy.  Empty ASR/subtitle text is never used
  // as a duplicate signal; finder/link identity remains the fallback for it.
  const ranked = items.map((item, originalIndex) => ({
    item,
    originalIndex,
    publishedAt: Date.parse(String(item["文章时间地点"] || "").replace(" ", "T")),
  })).sort((left, right) => {
    const leftTime = Number.isFinite(left.publishedAt) ? left.publishedAt : Number.MAX_SAFE_INTEGER;
    const rightTime = Number.isFinite(right.publishedAt) ? right.publishedAt : Number.MAX_SAFE_INTEGER;
    return leftTime - rightTime || left.originalIndex - right.originalIndex;
  });
  const survivors = [];
  const duplicates = [];
  for (const candidate of ranked) {
    const content = candidate.item["文章视频内容"];
    const duplicate = content
      ? survivors.find((prior) => bodySimilarity(prior.item["文章视频内容"], content) >= 0.8)
      : null;
    if (!duplicate) {
      survivors.push(candidate);
      continue;
    }
    duplicates.push({
      duplicateUrl: candidate.item["文章链接"] || null,
      duplicateArticleId: candidate.item["文章id"] || null,
      survivorUrl: duplicate.item["文章链接"] || null,
      survivorArticleId: duplicate.item["文章id"] || null,
      similarity: bodySimilarity(duplicate.item["文章视频内容"], content),
      reason: "video_content_similarity",
    });
  }
  const survivorIndexes = new Set(survivors.map((entry) => entry.originalIndex));
  return {
    kept: items.filter((_item, index) => survivorIndexes.has(index)),
    removed: duplicates.length,
    duplicates,
  };
}

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
    if (/qlogo\.cn$|checkresupdate/i.test(parsed.hostname + parsed.pathname)) return false;
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
  // 视频号的业务口径中“文章内容”固定为空；卡片描述属于标题，语音
  // 转写只进入“文章视频内容”。清洗标注因此统计清洗后的标题文本。
  let titleSource = record["文章标题"];
  const articleContentCleaned = cleanCompactContent(record["文章内容"]);
  let videoContentCleaned = cleanVideoContent(record["文章视频内容"]);
  record["文章内容"] = null;
  record["作者id"] = null;
  if (extra?.ok) {
    const previewSource = String(extra.title || "");
    const previewTags = extractHashtags(previewSource);
    const previewWithoutTags = previewSource.replace(hashtagPattern, "").replace(/#/gu, "").trim();
    const previewTitle = usablePreviewTitle(previewWithoutTags);
    if (previewTitle && (!titleSource || titleSource.startsWith("...") || previewTitle.length >= titleSource.length)) {
      titleSource = previewTitle;
    }
    if (previewTags.length) {
      record["文章标签"] = normalizeTags([
        ...String(record["文章标签"] || "").split(",").filter(Boolean),
        ...previewTags,
      ]);
    }
    record["文章时间地点"] = normalizePublishedAt(extra.publishedAt) || record["文章时间地点"];
  }
  const titleCleaned = cleanCompactContent(titleSource);
  record["文章标题"] = titleCleaned.content;
  record["文章标签"] = record["文章标签"] || titleCleaned.tags;
  if (!extra?.ok) {
    record["文章图片信息"] = null;
    record["文章视频内容"] = videoContentCleaned.text;
    record["清洗标注"] = JSON.stringify(aggregateCleaningStats(
      titleCleaned.stats, articleContentCleaned.stats, videoContentCleaned.stats,
    ));
    record["内容类型"] = "视频";
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
  record["作者名字"] = record["作者名字"] || extra.author || null;
  record["文章图片链接"] = images.length ? JSON.stringify(images.map((item) => item.url)) : null;
  // ODS requirement: keep the image-detail field empty. Image URLs remain
  // available in 文章图片链接; the auxiliary metadata is intentionally not
  // exported to avoid mixing DOM dimensions/alt text with business data.
  record["文章图片信息"] = null;
  record["作者主页链接"] = extra.authorUrl || null;
  record["文章视频链接"] = videos.length ? JSON.stringify(videos.map((item) => item.url)) : null;
  videoContentCleaned = cleanVideoContent(extra.videoContent || record["文章视频内容"]);
  record["文章视频内容"] = videoContentCleaned.text;
  record["文章视频时长"] = videos.some((item) => item.duration != null)
    ? JSON.stringify(videos.map((item) => item.duration))
    : (record["文章视频时长"] ?? null);
  if (extra.likeCount != null) record["文章点赞数"] = parseCount(extra.likeCount);
  if (extra.recommendCount != null) record["文章收藏数"] = parseCount(extra.recommendCount);
  if (extra.shareCount != null) record["文章分享数"] = parseCount(extra.shareCount);
  if (extra.commentCountVisible != null) record["文章评论数"] = extra.commentCountVisible;
  record["清洗标注"] = JSON.stringify(aggregateCleaningStats(
    titleCleaned.stats, articleContentCleaned.stats, videoContentCleaned.stats,
  ));
  record["内容类型"] = "视频";
}

// 视频号以字幕/ASR文本作为核心去重字段。达到80%相似度时保留发布时间
// 最早的一条；无字幕的视频不参与文本查重，继续依赖finder/link身份。
const deduped = dedupeByVideoContent(records);
records = deduped.kept;
const keptPostUrls = new Set(records.map((row) => row["文章链接"]).filter(Boolean));
const dedupeAuditPath = outputPath.replace(/\.jsonl$/i, "_dedupe_audit.jsonl");
atomicWriteFileSync(
  dedupeAuditPath,
  deduped.duplicates.map((item) => JSON.stringify(item)).join("\n") + (deduped.duplicates.length ? "\n" : ""),
);

const comments = collectComments && fs.existsSync(collectorCommentPath)
  ? fs.readFileSync(collectorCommentPath, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse)
    .filter((row) => keptPostUrls.has(row["文章链接"]))
    .map((row) => {
      const cleaned = cleanComment(row["评论内容"]);
      return cleaned.text ? {
        ...row,
        评论内容: cleaned.text,
        清洗标注: JSON.stringify(cleaned.stats),
      } : null;
    }).filter(Boolean)
  : [];
if (collectComments) {
  for (const record of records) {
    const extra = enrichment.get(record["文章链接"]);
    if (extra?.commentCountVisible != null) record["文章评论数"] = extra.commentCountVisible;
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
        平台: "微信视频号",
        分类: record["分类"] || null,
        项目: record["项目"] || null,
        清洗标注: JSON.stringify(cleaned.stats),
      });
    }
  }
  const uniqueComments = [...new Map(comments.map((row, index) => [
    `${row["平台"]}:${row["文章链接"]}:${row["评论id"] || `index-${index}`}:${row["评论内容"]}`,
    row,
  ])).values()];
  const extractedCounts = new Map();
  for (const row of uniqueComments) {
    const url = row["文章链接"];
    extractedCounts.set(url, (extractedCounts.get(url) || 0) + 1);
  }
  const commentAudits = records.map((record) => {
    const extra = enrichment.get(record["文章链接"]);
    const visibleCount = extra?.commentCountVisible ?? record["文章评论数"] ?? null;
    const extractedCount = extractedCounts.get(record["文章链接"]) || 0;
    return {
      article_url: record["文章链接"],
      article_id: record["文章id"] || null,
      visible_comment_count: visibleCount,
      extracted_comment_count: extractedCount,
      status: extractedCount > 0 ? "visible_comments_extracted" : (visibleCount ? "count_visible_detail_unavailable" : "no_visible_comments"),
      reason: visibleCount && extractedCount === 0 ? "视频号页面仅返回评论数量，评论明细未在公开DOM中展开" : null,
    };
  });
  const commentJsonl = outputPath.replace(/ods_social_media_post_channels_final\.jsonl$/i, "ods_social_media_comment_channels_final.jsonl");
  const commentCsv = outputPath.replace(/ods_social_media_post_channels_final\.jsonl$/i, "ods_social_media_comment_channels_final.csv");
  const commentAuditPath = outputPath.replace(/\.jsonl$/i, "_comment_audit.jsonl");
  const quoteComment = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  atomicWriteFileSync(commentJsonl, uniqueComments.map((item) => JSON.stringify(item)).join("\n") + (uniqueComments.length ? "\n" : ""));
  atomicWriteFileSync(commentCsv, "\uFEFF" + commentFields.map(quoteComment).join(",") + "\n" + uniqueComments.map((row) => commentFields.map((field) => quoteComment(row[field])).join(",")).join("\n") + (uniqueComments.length ? "\n" : ""));
  atomicWriteFileSync(commentAuditPath, commentAudits.map((item) => JSON.stringify(item)).join("\n") + (commentAudits.length ? "\n" : ""));
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
atomicWriteFileSync(outputPath, records.map((item) => JSON.stringify(item)).join("\n") + (records.length ? "\n" : ""));
atomicWriteFileSync(csvPath, "\uFEFF" + headers.map(quote).join(",") + "\n" + records.map((record) => headers.map((field) => quote(record[field])).join(",")).join("\n") + (records.length ? "\n" : ""));
console.log(JSON.stringify({ records: records.length, invalidLinksRemoved, duplicatesRemoved: deduped.removed, tagged: records.filter((r) => r["文章标签"]).length, images: records.filter((r) => r["文章图片链接"]).length, videos: records.filter((r) => r["文章视频链接"]).length, videoContent: records.filter((r) => r["文章视频内容"]).length, comments: collectComments ? comments.length : 0, authorUrls: records.filter((r) => r["作者主页链接"]).length, dedupeAuditPath, outputPath, csvPath }, null, 2));
