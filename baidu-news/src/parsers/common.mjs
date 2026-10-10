const DATE_PATTERNS = [
  /(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?/,
  /(20\d{2})(\d{2})(\d{2})/
];

export function normalizeText(text) {
  return String(text || "").replace(/[\u200B-\u200D\uFEFF]/g, "").replace(/\u00a0/g, " ").replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();
}

export function cleanArticleText(text, options = {}) {
  let value = normalizeText(text);
  for (const marker of options.endMarkers || []) {
    const index = value.search(marker);
    if (index >= Math.max(120, Number(options.minimumBeforeCut || 120))) value = value.slice(0, index);
  }
  const removeLines = options.removeLines || [];
  value = value.split("\n").map((line) => {
    const trimmed = line.trim();
    return removeLines.some((pattern) => pattern.test(trimmed)) ? "" : line;
  }).join("\n");
  return normalizeText(value);
}

export function stripLeadingTitle(text, title) {
  const value = normalizeText(text);
  const normalizedTitle = normalizeText(title);
  if (!value || !normalizedTitle) return value;
  const key = (input) => normalizeText(input).replace(/\s+/g, "").replace(/[|｜_-](?:[^|｜_-]{1,30})$/, "");
  const titleKeys = new Set([key(normalizedTitle), key(normalizedTitle.replace(/\s*(?:[_|｜]|——).{1,40}$/, ""))].filter(Boolean));
  const lines = value.split("\n");
  const first = lines.findIndex((line) => line.trim());
  if (first >= 0 && titleKeys.has(key(lines[first]))) lines.splice(first, 1);
  return normalizeText(lines.join("\n"));
}

export function cleanArticleTitle(title) {
  return normalizeText(title)
    .replace(/_房产家居_青岛大众网$/i, "")
    .replace(/_商讯_产经频道首页_财经网\s*-\s*CAIJING\.COM\.CN$/i, "")
    .replace(/\s*_\s*东方财富网$/i, "")
    .replace(/\s*——\s*凤凰网房产.*$/i, "")
    .trim();
}

export function looksLikePageChrome(text) {
  const lines = normalizeText(text).split("\n").slice(0, 30).map((line) => line.trim());
  const navigation = /^(?:首页|新闻|资讯|财经|教育|健康|消费|旅游|房产|品牌|汽车|家居|区县|更多|登录|注册|无障碍|移动客户端|联系我们)$/;
  const navigationCount = lines.filter((line) => navigation.test(line)).length;
  return navigationCount >= 6 || /(?:网站地图|ICP备|All Rights Reserved|违法不良信息举报)[\s\S]{0,200}$/i.test(normalizeText(text));
}

export function parseDate(value) {
  if (!value) return null;
  const text = String(value).trim();
  const iso = Date.parse(text);
  if (Number.isFinite(iso) && /20\d{2}/.test(text)) return new Date(iso).toISOString().slice(0, 19).replace("T", " ");
  for (const pattern of DATE_PATTERNS) {
    const match = text.match(pattern);
    if (!match) continue;
    const [, y, m, d, hh = "00", mm = "00", ss = "00"] = match;
    return `${y}-${m.padStart(2, "0")}-${d.padStart(2, "0")} ${hh.padStart(2, "0")}:${mm}:${ss}`;
  }
  return null;
}

export function inDateWindow(value, startDate, endDate) {
  const normalized = parseDate(value);
  if (!normalized) return false;
  const day = normalized.slice(0, 10);
  return day >= startDate && day <= endDate;
}

export async function extractGeneric(page, parser = "generic", options = {}) {
  return page.evaluate(({ parser, options }) => {
    const clean = (value) => String(value || "").replace(/\u00a0/g, " ").replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();
    const meta = (selector, attribute = "content") => document.querySelector(selector)?.getAttribute(attribute) || "";
    const jsonLd = [];
    for (const node of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const value = JSON.parse(node.textContent || "null");
        jsonLd.push(...(Array.isArray(value) ? value : value?.["@graph"] || [value]));
      } catch {}
    }
    const articleLd = jsonLd.find((item) => /Article|NewsArticle|ReportageNewsArticle/.test(String(item?.["@type"]))) || {};
    const defaultContentSelectors = [
      "[itemprop=articleBody]", "#article-content", "#articleContent", "#ContentBody", "#articleBody",
      "#post_content", ".news-body-content", ".news-con", ".zwinfos", ".article-content",
      ".article_content", ".article-body", ".article_body", ".post_body", ".post_content", "article"
    ];
    const contentSelectors = options.contentSelectors?.length ? options.contentSelectors : defaultContentSelectors;
    let contentNode = null;
    let bestLength = 0;
    for (const selector of contentSelectors) {
      let selectorNode = null;
      let selectorLength = 0;
      for (const node of document.querySelectorAll(selector)) {
        const length = clean(node.innerText).length;
        if (length > selectorLength) { selectorNode = node; selectorLength = length; }
      }
      if (selectorNode && options.preferFirstSelector) { contentNode = selectorNode; bestLength = selectorLength; break; }
      if (selectorLength > bestLength) { contentNode = selectorNode; bestLength = selectorLength; }
    }
    const root = contentNode || (options.strictContentSelectors ? null : document.body);
    if (root && options.excludeSelectors?.length) {
      for (const selector of options.excludeSelectors) {
        for (const node of root.querySelectorAll(selector)) node.remove();
      }
    }
    const images = root ? [...root.querySelectorAll("img")].map((img) => img.currentSrc || img.src || img.dataset.src || img.dataset.original)
      .filter((url) => url && !url.startsWith("data:") && !/logo|avatar|icon|qrcode|wechat|psstatic\.cdn\.bcebos\.com\/basics|mbdp01\.bdstatic\.com\/static\/landing-pc\/img\/(?:like|degrade)/i.test(url))
      .filter((url) => /\.(?:jpe?g|png|webp|gif)(?:[?@]|$)/i.test(url)) : [];
    const ogImage = meta('meta[property="og:image"]');
    if (ogImage && !/logo|avatar|icon|qrcode|wechat|mbdp01\.bdstatic\.com\/static\/landing-pc\/img\/(?:like|degrade)/i.test(ogImage)) images.unshift(ogImage);
    const videos = root ? [...root.querySelectorAll("video, video source")].map((node) => node.currentSrc || node.src).filter(Boolean) : [];
    const canonicalUrl = document.querySelector('link[rel="canonical"]')?.href || location.href;
    const title = meta('meta[property="og:title"]') || articleLd.headline || document.querySelector("h1")?.innerText || document.title;
    const authorObject = Array.isArray(articleLd.author) ? articleLd.author[0] : articleLd.author;
    const author = meta('meta[name="author"]') || meta('meta[property="article:author"]') || authorObject?.name || "";
    const publishedAt = meta('meta[property="article:published_time"]') || meta('meta[name="publishdate"]') || meta('meta[name="PubDate"]') || articleLd.datePublished || document.querySelector("time")?.dateTime || document.querySelector("time")?.innerText || "";
    const keywords = meta('meta[name="keywords"]') || articleLd.keywords || "";
    return {
      parser,
      canonicalUrl,
      title: clean(title),
      author: clean(author),
      authorUrl: authorObject?.url || null,
      publishedAt: clean(publishedAt),
      content: clean(root?.innerText || ""),
      tags: [],
      images: [...new Set(images)].slice(0, 80),
      videos: [...new Set(videos)].slice(0, 20),
      articleId: articleLd.identifier?.value || articleLd.identifier || null
    };
  }, { parser, options });
}
