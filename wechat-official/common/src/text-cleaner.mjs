const NAMED_ENTITIES = new Map([
  ["nbsp", " "], ["amp", "&"], ["lt", "<"], ["gt", ">"],
  ["quot", '"'], ["apos", "'"], ["ensp", " "], ["emsp", " "]
]);

function decodeHtmlEntities(value) {
  return String(value ?? "").replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (whole, entity) => {
    if (entity[0] === "#") {
      const hex = entity[1]?.toLowerCase() === "x";
      const point = Number.parseInt(entity.slice(hex ? 2 : 1), hex ? 16 : 10);
      try { return Number.isFinite(point) ? String.fromCodePoint(point) : whole; } catch { return whole; }
    }
    return NAMED_ENTITIES.get(entity.toLowerCase()) ?? whole;
  });
}

const codePointLength = (value) => [...String(value ?? "")].length;

function emojiCount(value) {
  const segments = graphemes(value);
  return segments.filter((segment) => /\p{Extended_Pictographic}|\p{Regional_Indicator}|[0-9#*]\uFE0F?\u20E3/u.test(segment)).length;
}

function graphemes(value) {
  return typeof Intl.Segmenter === "function"
    ? [...new Intl.Segmenter("zh-CN", { granularity: "grapheme" }).segment(value)].map((item) => item.segment)
    : [...value];
}

/**
 * 确定性文本清洗：保留正常中文、字母、数字、标点、换行与 emoji；
 * 去除控制/零宽/私用区字符，压缩空白，并把同一字符连续 4 次以上缩至 3 次。
 */
export function cleanText(value, options = {}) {
  const raw = String(value ?? "");
  const decoded = decodeHtmlEntities(raw);
  const originalLength = codePointLength(decoded);
  let text = decoded.normalize("NFC").replace(/\r\n?/g, "\n");

  text = [...text].filter((char) => {
    const remove = /[\p{Cc}\p{Cf}\p{Co}\uFFFD]/u.test(char) && char !== "\n" && char !== "\t";
    return !remove;
  }).join("");

  text = text.replace(/[\t\v\f ]+/g, " ");
  text = text.replace(/ *\n */g, "\n").replace(/\n{3,}/g, "\n\n").trim();

  let duplicateCount = 0;
  text = text.replace(/([^\s])\1{3,}/gu, (run, char) => {
    const kept = char.repeat(3);
    duplicateCount += codePointLength(run) - codePointLength(kept);
    return kept;
  });
  const emojiTotal = emojiCount(text);
  if (options.removeEmoji) text = graphemes(text).filter((segment) => !/\p{Extended_Pictographic}|\p{Regional_Indicator}|[0-9#*]\uFE0F?\u20E3/u.test(segment)).join("");
  if (options.singleParagraph) {
    if (options.paragraphSeparator) text = text.replace(/\s*\n\s*/gu, options.paragraphSeparator);
    text = text.replace(/\s+/gu, "");
    if (options.paragraphSeparator) {
      const escaped = String(options.paragraphSeparator).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      text = text.replace(new RegExp(`${escaped}{2,}`, "gu"), options.paragraphSeparator);
    }
  }
  const cleanedLength = codePointLength(text);
  const otherCount = Math.max(0, originalLength - cleanedLength - duplicateCount - (options.removeEmoji ? emojiTotal : 0));

  return {
    text,
    stats: {
      原始文字数: originalLength,
      清理后文字数: cleanedLength,
      表情个数: emojiTotal,
      其他字符个数: otherCount,
      重复字符个数: duplicateCount
    }
  };
}

export function removeEmoji(value) {
  return value == null ? value : cleanText(value, { removeEmoji: true }).text;
}

const HASHTAG_PATTERN = /(?<![A-Za-z0-9_])#((?:[\p{L}_][^#\s,，;；.!！?？、]{0,49})|(?:\d{2,}[\p{L}\p{N}_·-]{0,48}))/gu;

export function extractHashtags(content = "") {
  return [...String(content || "").matchAll(HASHTAG_PATTERN)].map((match) => match[1]);
}

export function normalizeTags(values, content = "") {
  const candidates = [...(values || []), ...extractHashtags(content)];
  const seen = new Set();
  const result = [];
  for (const candidate of candidates) {
    const tag = removeEmoji(String(candidate ?? "").replace(/^#+/, "").replace(/(?:\[话题\])?#?$/u, "").replace(/[\s,，;；]+$/g, "").trim());
    if (!tag || seen.has(tag)) continue;
    seen.add(tag);
    result.push(tag);
  }
  return result.join(",") || null;
}

/**
 * 将小红书简介中的话题标签与正文分离。清洗统计以“剥离标签后的正文原文”为口径，
 * 标签解析属于字段拆分，不计入“其他字符个数”。
 */
export function splitDescriptionAndTags(value, domTags = []) {
  const rawText = String(value ?? "");
  const extractedTags = extractHashtags(rawText);
  const bodyBeforeCleaning = rawText.replace(HASHTAG_PATTERN, "")
    .replace(/[\t ]+/g, " ").replace(/ *\n */g, "\n").replace(/\n{3,}/g, "\n\n").trim();
  const cleaned = cleanText(bodyBeforeCleaning, { removeEmoji: true, singleParagraph: true });
  return {
    rawText,
    bodyBeforeCleaning,
    content: cleaned.text || null,
    tags: normalizeTags([...(domTags || []), ...extractedTags]),
    stats: cleaned.stats
  };
}
