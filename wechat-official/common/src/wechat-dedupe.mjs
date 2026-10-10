const SHINGLE_SIZE = 5;
export const BODY_SIMILARITY_THRESHOLD = 0.8;

const text = (value) => String(value ?? "").trim();
const present = (value) => value !== null && value !== undefined && text(value) !== "";
const platformOf = (row) => text(row?.["平台"]) || "微信公众号";

export function normalizeWechatBody(value) {
  return text(value)
    .toLowerCase()
    .replace(/[\u0000-\u001f\s]+/gu, "")
    .replace(/[，。！？；：、“”‘’（）()【】［］《》<>「」,.!?;:'"`~·—–_\-#]/gu, "");
}

function makeShingles(normalized, size = SHINGLE_SIZE) {
  const chars = [...normalized];
  const result = new Set();
  for (let index = 0; index + size <= chars.length; index += 1) {
    result.add(chars.slice(index, index + size).join(""));
  }
  return result;
}

export function bodySimilarity(left, right) {
  const a = normalizeWechatBody(left);
  const b = normalizeWechatBody(right);
  if (!a || !b) return 0;
  if (a === b) return 1;
  if ([...a].length < SHINGLE_SIZE || [...b].length < SHINGLE_SIZE) return 0;
  const leftShingles = makeShingles(a);
  const rightShingles = makeShingles(b);
  if (!leftShingles.size || !rightShingles.size) return 0;
  let intersection = 0;
  for (const shingle of leftShingles) if (rightShingles.has(shingle)) intersection += 1;
  // Both texts must be at least 80% covered. Dividing by the larger shingle
  // set prevents a short excerpt contained in a long article being deleted.
  return intersection / Math.max(leftShingles.size, rightShingles.size);
}

export function canonicalWechatUrl(value) {
  let raw = text(value).replace(/^[[(<\s]+|[\])>，。,；;！!？?\s]+$/gu, "");
  if (!raw) return "";
  try {
    const parsed = new URL(raw);
    parsed.hash = "";
    parsed.protocol = "https:";
    parsed.hostname = parsed.hostname.toLowerCase();
    if (/^\/s\/[^/]+\/?$/u.test(parsed.pathname)) {
      parsed.pathname = parsed.pathname.replace(/\/$/u, "");
      parsed.search = "";
    } else if (parsed.hostname === "mp.weixin.qq.com" && parsed.pathname === "/s") {
      const core = new URLSearchParams();
      for (const key of ["__biz", "mid", "idx", "sn"]) {
        if (parsed.searchParams.has(key)) core.set(key, parsed.searchParams.get(key));
      }
      if ([...core].length) parsed.search = core.toString();
    }
    return parsed.toString().replace(/\/$/u, "");
  } catch {
    return raw;
  }
}

export function articleIdentityKeys(row) {
  const platform = platformOf(row);
  const articleId = text(row?.["文章id"]);
  const url = canonicalWechatUrl(row?.["文章链接"]);
  return [
    articleId ? `${platform}|id|${articleId}` : "",
    url ? `${platform}|url|${url}` : "",
  ].filter(Boolean);
}

export function canonicalArticleKey(row) {
  return articleIdentityKeys(row)[0] || `${platformOf(row)}|unkeyed|`;
}

function dateValue(value) {
  const raw = text(value);
  if (!raw) return Number.POSITIVE_INFINITY;
  const match = raw.match(/(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})(?:日)?(?:[ T](\d{1,2}):?(\d{2})?:?(\d{2})?)?/u);
  if (!match) return Number.POSITIVE_INFINITY;
  return Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(match[4] || 0), Number(match[5] || 0), Number(match[6] || 0));
}

export function comparePostSurvivors(left, right) {
  const published = dateValue(left?.["文章时间地点"]) - dateValue(right?.["文章时间地点"]);
  if (published) return published;
  const acquired = dateValue(left?.["文章获取时间"]) - dateValue(right?.["文章获取时间"]);
  if (acquired) return acquired;
  const leftId = text(left?.id), rightId = text(right?.id);
  if (leftId && rightId && /^\d+$/u.test(leftId) && /^\d+$/u.test(rightId)) {
    const a = BigInt(leftId), b = BigInt(rightId);
    if (a !== b) return a < b ? -1 : 1;
  }
  return leftId.localeCompare(rightId, "zh-CN");
}

const MAX_FIELDS = new Set(["文章点赞数", "文章收藏数", "文章评论数", "作者粉丝数", "作者点赞数", "文章分享数"]);
const RICH_FIELDS = new Set(["文章内容", "文章标签", "文章图片链接", "文章视频链接", "文章视频内容", "文章视频时长", "清洗标注", "文章标注"]);

const numberOrNull = (value) => {
  if (!present(value)) return null;
  const parsed = Number(String(value).replaceAll(",", ""));
  return Number.isFinite(parsed) ? parsed : null;
};

export function mergePostFields(survivor, duplicate) {
  const merged = { ...survivor };
  const fields = new Set([...Object.keys(survivor || {}), ...Object.keys(duplicate || {})]);
  for (const field of fields) {
    if (field === "id" || field === "文章id" || field === "文章链接" || field === "文章时间地点" || field === "关键词" || field === "项目") continue;
    if (field === "文章图片信息") {
      merged[field] = null;
      continue;
    }
    if (field === "文章获取时间") {
      if (dateValue(duplicate[field]) < dateValue(merged[field])) merged[field] = duplicate[field];
      continue;
    }
    if (MAX_FIELDS.has(field)) {
      const a = numberOrNull(merged[field]);
      const b = numberOrNull(duplicate[field]);
      merged[field] = a === null ? b : b === null ? a : Math.max(a, b);
      continue;
    }
    if (!present(merged[field]) && present(duplicate[field])) {
      merged[field] = duplicate[field];
    } else if (RICH_FIELDS.has(field) && text(duplicate[field]).length > text(merged[field]).length) {
      merged[field] = duplicate[field];
    }
  }
  merged["文章图片信息"] = null;
  return merged;
}

function makeSignature(row, survivorIndex) {
  const normalized = normalizeWechatBody(row?.["文章内容"]);
  return { survivorIndex, normalized, shingles: normalized ? makeShingles(normalized) : new Set() };
}

export function dedupePostsGlobal(rows, { threshold = BODY_SIMILARITY_THRESHOLD } = {}) {
  const ordered = rows.map((row, inputIndex) => ({ row: { ...row }, inputIndex }))
    .sort((a, b) => comparePostSurvivors(a.row, b.row) || a.inputIndex - b.inputIndex);
  const records = [];
  const audit = [];
  const identity = new Map();
  const exactBodies = new Map();
  const signatures = [];
  const postings = new Map();
  const aliasToSurvivor = new Map();

  const addSignature = (row, survivorIndex) => {
    const signature = makeSignature(row, survivorIndex);
    if (!signature.normalized) return;
    const signatureIndex = signatures.length;
    signatures.push(signature);
    if (!exactBodies.has(signature.normalized)) exactBodies.set(signature.normalized, survivorIndex);
    for (const shingle of signature.shingles) {
      if (!postings.has(shingle)) postings.set(shingle, []);
      postings.get(shingle).push(signatureIndex);
    }
  };

  const findBodyDuplicate = (row) => {
    const signature = makeSignature(row, -1);
    if (!signature.normalized) return null;
    if (exactBodies.has(signature.normalized)) return { survivorIndex: exactBodies.get(signature.normalized), reason: "body_exact", similarity: 1 };
    if (signature.shingles.size === 0) return null;
    // Counting through the inverted index gives the exact intersection for
    // every candidate without materializing all prior body pairs.
    const candidateCounts = new Map();
    for (const shingle of signature.shingles) {
      for (const signatureIndex of postings.get(shingle) || []) {
        candidateCounts.set(signatureIndex, (candidateCounts.get(signatureIndex) || 0) + 1);
      }
    }
    let best = null;
    for (const [signatureIndex, intersection] of candidateCounts) {
      const prior = signatures[signatureIndex];
      if (Math.min(signature.shingles.size, prior.shingles.size) / Math.max(signature.shingles.size, prior.shingles.size) < threshold) continue;
      const similarity = intersection / Math.max(signature.shingles.size, prior.shingles.size);
      if (similarity >= threshold && (!best || similarity > best.similarity)) {
        best = { survivorIndex: prior.survivorIndex, reason: "body_similarity", similarity };
      }
    }
    return best;
  };

  for (const { row, inputIndex } of ordered) {
    const keys = articleIdentityKeys(row);
    const identityTargets = keys.map((key) => identity.get(key)).filter((value) => value !== undefined);
    let match = identityTargets.length ? { survivorIndex: Math.min(...identityTargets), reason: keys.find((key) => identity.has(key))?.includes("|id|") ? "article_id" : "article_url", similarity: 1 } : null;
    if (!match) match = findBodyDuplicate(row);
    if (match) {
      const survivorBefore = records[match.survivorIndex];
      records[match.survivorIndex] = mergePostFields(survivorBefore, row);
      audit.push({
        duplicateId: row.id ?? null,
        survivorId: survivorBefore.id ?? null,
        duplicateArticleId: row["文章id"] || null,
        survivorArticleId: survivorBefore["文章id"] || null,
        duplicateUrl: row["文章链接"] || null,
        survivorUrl: survivorBefore["文章链接"] || null,
        duplicateKeyword: row["关键词"] || null,
        duplicateProject: row["项目"] || null,
        survivorKeyword: survivorBefore["关键词"] || null,
        survivorProject: survivorBefore["项目"] || null,
        duplicateSource: row.__dedupeSource || null,
        survivorSource: survivorBefore.__dedupeSource || null,
        reason: match.reason,
        similarity: Number(match.similarity.toFixed(6)),
        inputIndex,
      });
      for (const key of keys) {
        identity.set(key, match.survivorIndex);
        aliasToSurvivor.set(key, match.survivorIndex);
      }
      addSignature(row, match.survivorIndex);
      continue;
    }
    const survivorIndex = records.length;
    row["文章图片信息"] = null;
    records.push(row);
    for (const key of keys) {
      identity.set(key, survivorIndex);
      aliasToSurvivor.set(key, survivorIndex);
    }
    addSignature(row, survivorIndex);
  }
  // Resolve every survivor's own keys after all merges.
  records.forEach((row, survivorIndex) => {
    for (const key of articleIdentityKeys(row)) aliasToSurvivor.set(key, survivorIndex);
  });
  return { records, audit, aliases: aliasToSurvivor };
}

function mergeCommentFields(survivor, duplicate) {
  const merged = { ...survivor };
  for (const field of new Set([...Object.keys(survivor || {}), ...Object.keys(duplicate || {})])) {
    if (field === "id") continue;
    if (["评论点赞数", "评论回复数"].includes(field)) {
      const a = numberOrNull(merged[field]), b = numberOrNull(duplicate[field]);
      merged[field] = a === null ? b : b === null ? a : Math.max(a, b);
    } else if (!present(merged[field]) && present(duplicate[field])) {
      merged[field] = duplicate[field];
    }
  }
  return merged;
}

export function relinkAndDedupeComments(rows, postDedupeResult = null) {
  const aliases = postDedupeResult?.aliases || new Map();
  const posts = postDedupeResult?.records || [];
  const records = [];
  const audit = [];
  const keys = new Map();
  for (const source of rows) {
    const row = { ...source };
    const lookupKeys = articleIdentityKeys(row);
    const survivorIndex = lookupKeys.map((key) => aliases.get(key)).find((value) => value !== undefined);
    if (survivorIndex !== undefined) {
      const post = posts[survivorIndex];
      row["文章id"] = post?.["文章id"] || row["文章id"] || null;
      row["文章链接"] = post?.["文章链接"] || row["文章链接"] || null;
      if (!present(row["关键词"])) row["关键词"] = post?.["关键词"] || null;
      if (!present(row["项目"])) row["项目"] = post?.["项目"] || null;
    }
    const platform = platformOf(row);
    const commentId = text(row["评论id"]);
    const articleKey = articleIdentityKeys(row)[0] || `${platform}|unkeyed`;
    const naturalKey = commentId
      ? `${platform}|comment-id|${commentId}`
      : `${articleKey}|fallback|${normalizeWechatBody(row["评论内容"])}|${text(row["评论时间"])}`;
    const priorIndex = keys.get(naturalKey);
    if (priorIndex !== undefined) {
      records[priorIndex] = mergeCommentFields(records[priorIndex], row);
      audit.push({ duplicateId: row.id ?? null, survivorId: records[priorIndex].id ?? null, reason: commentId ? "comment_id" : "comment_fallback" });
    } else {
      keys.set(naturalKey, records.length);
      records.push(row);
    }
  }
  return { records, audit };
}
