export function parseCount(value) {
  const text = String(value ?? "").trim().replaceAll(",", "");
  if (!text || /^(赞|收藏|评论|分享|回复|—|-)$/.test(text)) return null;
  const match = text.match(/([\d.]+)\s*([万亿wWkK]?)/);
  if (!match) return null;
  const factor = /万|w/i.test(match[2]) ? 10_000 : /亿/.test(match[2]) ? 100_000_000 : /k/i.test(match[2]) ? 1_000 : 1;
  return Math.round(Number(match[1]) * factor);
}

export function dedupeUrls(values) {
  const seen = new Set();
  return values.filter(Boolean).filter((value) => {
    const key = String(value).replace(/^http:/, "https:");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function buildThreadContent(root, replies) {
  const blocks = [`【父评论｜${root.author || "未知用户"}】\n${root.content || ""}`];
  replies.forEach((reply, index) => {
    const target = reply.replyTarget ? `｜回复${reply.replyTarget}` : "";
    blocks.push(`【子评论${index + 1}｜${reply.author || "未知用户"}${target}】\n${reply.content || ""}`);
  });
  return blocks.join("\n\n");
}

export function threadLikeCount(root, replies) {
  return [root, ...replies].reduce((sum, item) => sum + (Number.isFinite(item.likeCount) ? item.likeCount : 0), 0);
}

/** 统一按北京时间（Asia/Shanghai，UTC+8）格式化采集时间。 */
export function beijingDateTime(date = new Date()) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23"
  }).formatToParts(date).filter((part) => part.type !== "literal").map((part) => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}

// 兼容旧调用方；业务字段统一使用 beijingDateTime。
export const shanghaiDateTime = beijingDateTime;

export function parsePublishedText(value, capturedAt = new Date()) {
  const text = String(value || "").trim();
  const exact = text.match(/(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})/);
  if (exact) return `${exact[1]}-${exact[2].padStart(2, "0")}-${exact[3].padStart(2, "0")} 00:00:00`;
  const md = text.match(/(?:^|\s)(\d{1,2})[-/.月](\d{1,2})(?:日)?/);
  if (md) {
    const year = Number(beijingDateTime(capturedAt).slice(0, 4));
    let day = `${year}-${md[1].padStart(2, "0")}-${md[2].padStart(2, "0")}`;
    if (day > beijingDateTime(capturedAt).slice(0, 10)) day = `${year - 1}-${md[1].padStart(2, "0")}-${md[2].padStart(2, "0")}`;
    return `${day} 00:00:00`;
  }
  const relative = text.match(/(\d+)\s*(分钟|小时|天)前/);
  if (relative) {
    const unit = relative[2] === "分钟" ? 60_000 : relative[2] === "小时" ? 3_600_000 : 86_400_000;
    return beijingDateTime(new Date(capturedAt.getTime() - Number(relative[1]) * unit));
  }
  if (/昨天/.test(text)) return beijingDateTime(new Date(capturedAt.getTime() - 86_400_000));
  if (/刚刚|今天/.test(text)) return beijingDateTime(capturedAt);
  return null;
}

export function parseSubtitleText(value) {
  const raw = String(value ?? "").replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n");
  const lines = raw.split("\n");
  const output = [];
  for (let line of lines) {
    line = line.trim();
    if (!line || /^WEBVTT(?:\s|$)/i.test(line) || /^(NOTE|STYLE|REGION)(?:\s|$)/i.test(line)) continue;
    if (/^\d+$/.test(line) || /-->/.test(line) || /^\d{1,2}:\d{2}(?::\d{2})?[,.]\d{3}/.test(line)) continue;
    line = line.replace(/<[^>]+>/g, "").replace(/\{\\[^}]+\}/g, "").trim();
    if (line && output.at(-1) !== line) output.push(line);
  }
  return output.join("\n") || null;
}
