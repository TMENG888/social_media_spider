import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { buildBaiduNewsUrl, discoverPage, SECURITY_CHALLENGE_PATTERN } from "./baidu.mjs";
import { cleanArticleTitle, looksLikePageChrome, parseDate, stripLeadingTitle } from "./parsers/common.mjs";
import { selectParser } from "./parsers/registry.mjs";
import { ODS_FIELDS, toOdsRecord } from "./schema.mjs";
import { buildCrawlTaskWorkbook } from "./build-crawl-tasks.mjs";
import { evaluateArticleEligibility } from "./article-policy.mjs";

async function loadPlaywright() {
  try { return await import("playwright"); }
  catch (error) {
    if (!process.env.PLAYWRIGHT_MODULE) throw error;
    return import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
  }
}

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    if (!argv[i].startsWith("--")) continue;
    const key = argv[i].slice(2);
    const next = argv[i + 1];
    args[key] = !next || next.startsWith("--") ? true : next;
    if (args[key] !== true) i += 1;
  }
  return args;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const randomDelay = ([min, max]) => sleep(Math.floor(min + Math.random() * (max - min + 1)));
let securityCooldownCount = 0;
let securityExhaustedCount = 0;
const csvCell = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
const toCsv = (rows, fields) => `\uFEFF${fields.map(csvCell).join(",")}\n${rows.map((row) => fields.map((field) => csvCell(row[field])).join(",")).join("\n")}\n`;

async function atomicWrite(file, value) {
  const temporary = `${file}.${process.pid}.tmp`;
  await fs.writeFile(temporary, value);
  await fs.rename(temporary, file);
}

function shanghaiDateTime(date = new Date()) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23"
  }).formatToParts(date).filter((part) => part.type !== "literal").map((part) => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}

function dateStatus(value, startDate, endDate) {
  if (!value) return "unknown";
  const day = value.slice(0, 10);
  if (day < startDate) return "older_than_start";
  if (day > endDate) return "newer_than_end";
  return "in_window";
}

function inferBaiduDate(item) {
  const text = `${item.cardDate || ""} ${item.snippet || ""}`;
  const explicit = parseDate(item.cardDate) || parseDate(item.snippet);
  if (explicit) return explicit;
  const relative = text.match(/(\d+)\s*(分钟|小时|天)前/);
  if (relative) {
    const unitMs = relative[2] === "分钟" ? 60_000 : relative[2] === "小时" ? 3_600_000 : 86_400_000;
    return shanghaiDateTime(new Date(Date.now() - Number(relative[1]) * unitMs));
  }
  if (/刚刚|今天/.test(text)) return shanghaiDateTime();
  const monthDay = text.match(/(\d{1,2})月(\d{1,2})日/);
  if (monthDay) {
    const currentYear = Number(shanghaiDateTime().slice(0, 4));
    const tail = `${monthDay[1].padStart(2, "0")}-${monthDay[2].padStart(2, "0")}`;
    let candidate = `${currentYear}-${tail}`;
    if (candidate > shanghaiDateTime().slice(0, 10)) candidate = `${currentYear - 1}-${tail}`;
    return `${candidate} 00:00:00`;
  }
  return null;
}

async function retry(task, maxRetries, delayRange) {
  let lastError;
  for (let attempt = 0; attempt <= maxRetries; attempt += 1) {
    try { return await task(); }
    catch (error) {
      lastError = error;
      if (/STOP_CAPTCHA|STOP_RATE_LIMIT/.test(String(error))) throw error;
      if (attempt < maxRetries) await randomDelay([delayRange[0] * (attempt + 1), delayRange[1] * (attempt + 1)]);
    }
  }
  throw lastError;
}

function isSecurityChallenge(value) {
  return /STOP_CAPTCHA|STOP_RATE_LIMIT|SECURITY_CHALLENGE_EXHAUSTED|\b403\b|\b429\b/i.test(String(value || ""));
}

function randomMilliseconds([min, max]) {
  const safeMin = Math.max(0, Number(min) || 0);
  const safeMax = Math.max(safeMin, Number(max) || safeMin);
  return Math.floor(safeMin + Math.random() * (safeMax - safeMin + 1));
}

async function coolDownSecurityChallenge(page, config, scope, attempt) {
  const delayMs = randomMilliseconds(config.securityCooldownMs);
  securityCooldownCount += 1;
  console.warn(`[安全验证] ${scope}触发访问限制，第${attempt}/${config.maxSecurityRetries}次自动冷却，休眠${Math.ceil(delayMs / 1000)}秒后重试。`);
  await page.goto("about:blank", { waitUntil: "commit", timeout: 10000 }).catch(() => {});
  await sleep(delayMs);
}

async function discoverPageWithCooldown(page, config, pageIndex) {
  for (let securityAttempt = 0; securityAttempt <= config.maxSecurityRetries; securityAttempt += 1) {
    try {
      return await retry(() => discoverPage(page, config.query, pageIndex), config.maxRetries, config.listDelayMs);
    } catch (error) {
      if (!isSecurityChallenge(error)) throw error;
      if (securityAttempt >= config.maxSecurityRetries) {
        securityExhaustedCount += 1;
        throw new Error(`SECURITY_CHALLENGE_EXHAUSTED:百度列表页冷却${config.maxSecurityRetries}次后仍受限`);
      }
      await coolDownSecurityChallenge(page, config, "百度列表页", securityAttempt + 1);
    }
  }
  throw new Error("SECURITY_CHALLENGE_EXHAUSTED:百度列表页");
}

async function openDetailWithCooldown(page, requestUrl, config) {
  for (let securityAttempt = 0; securityAttempt <= config.maxSecurityRetries; securityAttempt += 1) {
    const response = await retry(() => page.goto(requestUrl, { waitUntil: "domcontentloaded", timeout: config.navigationTimeoutMs }), config.maxRetries, config.detailDelayMs);
    const visible = await page.locator("body").innerText({ timeout: config.navigationTimeoutMs }).catch(() => "");
    const title = await page.title().catch(() => "");
    const challenged = [403, 429].includes(response?.status()) || SECURITY_CHALLENGE_PATTERN.test(`${title}\n${page.url()}\n${visible}`);
    if (!challenged) return { response, visible };
    if (securityAttempt >= config.maxSecurityRetries) {
      securityExhaustedCount += 1;
      throw new Error(`SECURITY_CHALLENGE_EXHAUSTED:详情页冷却${config.maxSecurityRetries}次后仍受限`);
    }
    await coolDownSecurityChallenge(page, config, "文章详情页", securityAttempt + 1);
  }
  throw new Error("SECURITY_CHALLENGE_EXHAUSTED:文章详情页");
}

const args = parseArgs(process.argv);
const shanghaiToday = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
const defaults = {
  query: "中国海外集团 住宅", startDate: "2026-01-01", endDate: shanghaiToday,
  projectName: "全国地产设计产品力监测",
  maxPages: 20, maxItems: 200, batchSize: 10, minContentLength: 100, headless: false,
  browserExecutable: process.env.BROWSER_EXECUTABLE || null,
  navigationTimeoutMs: 30000, listDelayMs: [8000, 15000], detailDelayMs: [6000, 12000],
  maxRetries: 2, saveHtml: false,
  maxSecurityRetries: 2, securityCooldownMs: [120000, 300000]
};
let fileConfig = {};
try { fileConfig = JSON.parse(await fs.readFile(args.config || "config.json", "utf8")); } catch {}
const cliHeadless = args.headless === undefined ? undefined : (args.headless === true || args.headless === "true");
const config = {
  ...defaults, ...fileConfig,
  query: args.query || fileConfig.query || defaults.query,
  projectName: args["project-name"] || fileConfig.projectName || defaults.projectName,
  keywordTaskId: args["keyword-task-id"] || null,
  startDate: args["start-date"] || fileConfig.startDate || defaults.startDate,
  endDate: args["end-date"] || fileConfig.endDate || defaults.endDate,
  maxPages: Number(args["max-pages"] || fileConfig.maxPages || defaults.maxPages),
  maxItems: Number(args["max-items"] || fileConfig.maxItems || defaults.maxItems),
  batchSize: Number(args["batch-size"] || fileConfig.batchSize || defaults.batchSize),
  minContentLength: Number(args["min-content-length"] || fileConfig.minContentLength || defaults.minContentLength),
  headless: cliHeadless ?? fileConfig.headless ?? defaults.headless,
  browserExecutable: args["browser-executable"] || process.env.BROWSER_EXECUTABLE || fileConfig.browserExecutable || defaults.browserExecutable,
  maxSecurityRetries: Math.max(0, Number(args["max-security-retries"] ?? fileConfig.maxSecurityRetries ?? defaults.maxSecurityRetries)),
  securityCooldownMs: [
    Number(args["security-cooldown-min-ms"] ?? fileConfig.securityCooldownMs?.[0] ?? defaults.securityCooldownMs[0]),
    Number(args["security-cooldown-max-ms"] ?? fileConfig.securityCooldownMs?.[1] ?? defaults.securityCooldownMs[1])
  ]
};
const mode = args.mode || "crawl";
const resume = args.resume === true || args.resume === "true";
const outputDir = path.resolve(args["output-dir"] || "data");
const stateDir = path.resolve(args["state-dir"] || ".state");
await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(stateDir, { recursive: true });

const { chromium } = await loadPlaywright();
const launchOptions = {
  headless: config.headless, locale: "zh-CN",
  timezoneId: "Asia/Shanghai", viewport: { width: 1440, height: 1000 }
};
if (config.browserExecutable) launchOptions.executablePath = config.browserExecutable;
const context = await chromium.launchPersistentContext(path.join(stateDir, "browser-profile"), launchOptions);
context.setDefaultTimeout(config.navigationTimeoutMs);
await context.route("**/*", async (route) => {
  if (["font", "media"].includes(route.request().resourceType())) return route.abort();
  return route.continue();
});

const listPage = context.pages()[0] || await context.newPage();
const detailPage = mode === "discover" ? null : await context.newPage();
const discovered = [];
const records = [];
const audit = [];
const CURRENT_CLEANING_VERSIONS = new Set(["platform-dom-v3", "generic-strict-v3", "baijiahao-v3"]);
const seen = new Set();
let stopReason = null;
let completionReason = null;
let olderDateCount = 0;
let batchesProcessed = 0;

if (resume) {
  try { records.push(...(await fs.readFile(path.join(outputDir, "ods_social_media_post.jsonl"), "utf8")).split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line))); } catch {}
  try { audit.push(...(await fs.readFile(path.join(outputDir, "crawl_tasks.jsonl"), "utf8")).split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line))); } catch {
    try { audit.push(...(await fs.readFile(path.join(outputDir, "crawl_audit.jsonl"), "utf8")).split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line))); } catch {}
  }
  // Always repair fields whose target representation is deterministic. Older
  // accepted rows are removed below and fetched again with the strict DOM
  // parser, so a failed reparse cannot silently preserve dirty page chrome.
  for (const record of records) {
    record["文章标签"] = null;
    record["文章标题"] = cleanArticleTitle(record["文章标题"]);
    record["文章内容"] = stripLeadingTitle(record["文章内容"], record["文章标题"]);
  }
  const staleAcceptedUrls = new Set(audit
    .filter((item) => item.accepted && !CURRENT_CLEANING_VERSIONS.has(item.contentCleaningVersion))
    .flatMap((item) => [item.finalUrl, item.url]).filter(Boolean));
  if (staleAcceptedUrls.size) {
    const retained = records.filter((record) => !staleAcceptedUrls.has(record["文章链接"]));
    records.splice(0, records.length, ...retained);
  }
  const excludedUrls = new Set();
  for (const record of records) {
    const eligibility = evaluateArticleEligibility({ url: record["文章链接"], title: record["文章标题"], content: record["文章内容"] });
    if (!eligibility.eligible) excludedUrls.add(record["文章链接"]);
  }
  if (excludedUrls.size) {
    const retained = records.filter((record) => !excludedUrls.has(record["文章链接"]));
    records.splice(0, records.length, ...retained);
    for (const item of audit) {
      if (!excludedUrls.has(item.finalUrl || item.url)) continue;
      const eligibility = evaluateArticleEligibility({ url: item.finalUrl || item.url, title: item.title, content: "" });
      Object.assign(item, { accepted: false, status: "excluded", eligibilityCode: eligibility.code, error: eligibility.reason || "非资讯页面" });
    }
  }
}
const auditIndex = new Map(audit.map((item, index) => [item.url, index]));
const recordIndex = new Map(records.map((item, index) => [item["文章链接"] || item.id, index]));
function upsertAudit(item) {
  const position = auditIndex.get(item.url);
  if (position == null) { auditIndex.set(item.url, audit.length); audit.push(item); }
  else audit[position] = item;
}
function upsertRecord(record) {
  const key = record["文章链接"] || record.id;
  const position = recordIndex.get(key);
  if (position == null) { recordIndex.set(key, records.length); records.push(record); }
  else records[position] = record;
}
async function persistProgress() {
  await Promise.all([
    atomicWrite(path.join(outputDir, "ods_social_media_post.jsonl"), records.map((record) => JSON.stringify(record)).join("\n") + (records.length ? "\n" : "")),
    atomicWrite(path.join(outputDir, "crawl_audit.jsonl"), audit.map((item) => JSON.stringify(item)).join("\n") + (audit.length ? "\n" : "")),
    atomicWrite(path.join(outputDir, "crawl_tasks.jsonl"), audit.map((item) => JSON.stringify(item)).join("\n") + (audit.length ? "\n" : ""))
  ]);
}

try {
  for (let pageIndex = 0; pageIndex < config.maxPages && discovered.length < config.maxItems; pageIndex += 1) {
    let items;
    try {
      items = await discoverPageWithCooldown(listPage, config, pageIndex);
    } catch (error) {
      stopReason = String(error.message || error);
      break;
    }

    const batch = [];
    for (const item of items) {
      item.keywordTaskId = config.keywordTaskId;
      item.foundAt = shanghaiDateTime();
      const key = item.url.replace(/#.*$/, "");
      if (seen.has(key)) continue;
      seen.add(key);
      discovered.push(item);
      batch.push(item);
      if (batch.length >= config.batchSize || discovered.length >= config.maxItems) break;
    }
    if (!batch.length) {
      completionReason = "no_new_results";
      break;
    }

    if (mode === "discover") {
      batchesProcessed += 1;
    } else {
      let olderFoundInBatch = false;
      for (const item of batch) {
        const previous = auditIndex.has(item.url) ? audit[auditIndex.get(item.url)] : null;
        const alreadyStrictlyCleaned = previous?.accepted && CURRENT_CLEANING_VERSIONS.has(previous.contentCleaningVersion);
        if (resume && previous && (alreadyStrictlyCleaned || previous.status === "excluded" || ["older_than_start", "newer_than_end"].includes(previous.dateStatus))) {
          if (previous.dateStatus === "older_than_start") olderFoundInBatch = true;
          continue;
        }
        const attemptCount = Number(previous?.attemptCount || 0) + 1;
        const capturedAt = shanghaiDateTime();
        let finalUrl = item.url;
        let parserName = null;
        let platform = item.source || null;
        let visible = "";
        try {
          const requestUrl = item.url.replace(/^http:\/\/(sc\.stock\.cnfol\.com)/i, "https://$1");
          ({ visible } = await openDetailWithCooldown(detailPage, requestUrl, config));
          finalUrl = detailPage.url();
          const parser = selectParser(finalUrl, item.source);
          parserName = parser.name;
          platform = parser.name || platform;
          const parsed = await parser.parse(detailPage);
          if (!parsed.title?.trim() || /^(?:频道导航|首页|新闻|资讯|正文|详情|无标题)$/i.test(parsed.title.trim())) parsed.title = item.title || parsed.title;
          parsed.title = cleanArticleTitle(parsed.title || item.title);
          parsed.content = stripLeadingTitle(parsed.content, parsed.title || item.title);
          parsed.tags = [];
          parsed.author ||= item.source;
          parsed.canonicalUrl ||= finalUrl;
          parsed.publishedAt = parseDate(parsed.publishedAt) || parseDate(visible.slice(0, 5000)) || inferBaiduDate(item);
          const isOlder = Boolean(parsed.publishedAt && parsed.publishedAt.slice(0, 10) < config.startDate);
          const parsedDateStatus = dateStatus(parsed.publishedAt, config.startDate, config.endDate);
          const eligibility = evaluateArticleEligibility({ url: parsed.canonicalUrl || finalUrl, title: parsed.title || item.title, content: parsed.content });
          const missingFields = [];
          if (!(parsed.title || item.title)?.trim()) missingFields.push("文章标题");
          if (!parsed.content?.trim() || parsed.content.trim().length < config.minContentLength) missingFields.push(`文章内容（少于${config.minContentLength}字）`);
          else if (looksLikePageChrome(parsed.content)) missingFields.push("文章内容（疑似抓取到整页导航或页脚）");
          if (!parsed.canonicalUrl) missingFields.push("文章链接");
          const accepted = eligibility.eligible && parsedDateStatus === "in_window" && missingFields.length === 0;
          if (isOlder) { olderFoundInBatch = true; olderDateCount += 1; }
          const odsRecord = accepted ? toOdsRecord(parsed, { ...item, url: finalUrl, capturedAt, dateStatus: parsedDateStatus, projectName: config.projectName }) : null;
          const taskStatus = !eligibility.eligible ? "excluded" : missingFields.length ? "incomplete" : "parsed";
          const taskError = !eligibility.eligible ? eligibility.reason : missingFields.length ? `缺少字段：${missingFields.join("、")}` : null;
          upsertAudit({ ...item, batch: pageIndex + 1, finalUrl, parser: parsed.parser || parserName, platform: parsed.platform || platform, publishedAt: parsed.publishedAt, dateStatus: parsedDateStatus, eligibilityCode: eligibility.code, rawContentLength: parsed.rawContentLength ?? parsed.content?.length ?? 0, contentLength: parsed.content?.length || 0, contentCleaningVersion: parsed.contentCleaningVersion || "legacy", status: taskStatus, accepted, odsRecordId: odsRecord?.id || null, missingFields, attemptCount, lastAttemptAt: capturedAt, error: taskError });
          if (odsRecord) upsertRecord(odsRecord);
          await persistProgress();
          await fs.writeFile(path.join(stateDir, "checkpoint.json"), JSON.stringify({ query: config.query, pageIndex, batch: pageIndex + 1, processed: audit.length, accepted: records.length, olderFoundInBatch, lastUrl: finalUrl, updatedAt: new Date().toISOString() }, null, 2));
          await randomDelay(config.detailDelayMs);
        } catch (error) {
          const message = String(error.message || error);
          const fallbackDate = parseDate(visible.slice(0, 5000)) || inferBaiduDate(item);
          const fallbackStatus = dateStatus(fallbackDate, config.startDate, config.endDate);
          if (fallbackStatus === "older_than_start") { olderFoundInBatch = true; olderDateCount += 1; }
          try { platform ||= new URL(finalUrl).hostname.replace(/^www\./, ""); } catch {}
          upsertAudit({ ...item, batch: pageIndex + 1, finalUrl, parser: parserName, platform, publishedAt: fallbackDate, dateStatus: fallbackStatus, contentLength: 0, status: "failed", accepted: false, missingFields: [], attemptCount, lastAttemptAt: capturedAt, error: message });
          await persistProgress();
          if (isSecurityChallenge(message)) console.warn(`[安全验证] 当前文章已记录为失败，继续下一篇：${item.title}`);
        }
      }
      batchesProcessed += 1;
      if (stopReason) break;
      if (olderFoundInBatch) {
        completionReason = "older_than_start_date_found";
        break;
      }
    }

    await fs.writeFile(path.join(stateDir, "checkpoint.json"), JSON.stringify({ query: config.query, pageIndex, batchesProcessed, discovered: discovered.length, processed: audit.length, accepted: records.length, lastUrl: buildBaiduNewsUrl(config.query, pageIndex), updatedAt: new Date().toISOString() }, null, 2));
    await randomDelay(config.listDelayMs);
  }
} finally {
  if (!completionReason && !stopReason) completionReason = discovered.length >= config.maxItems ? "max_items_reached" : "max_pages_reached";
  await fs.writeFile(path.join(outputDir, "discovered_links.jsonl"), discovered.map((item) => JSON.stringify(item)).join("\n") + (discovered.length ? "\n" : ""));
  await fs.writeFile(path.join(outputDir, "discovered_links.csv"), toCsv(discovered, ["query", "pageIndex", "rank", "title", "url", "source", "cardDate", "snippet"]));
  await fs.writeFile(path.join(outputDir, "ods_social_media_post.jsonl"), records.map((record) => JSON.stringify(record)).join("\n") + (records.length ? "\n" : ""));
  await fs.writeFile(path.join(outputDir, "ods_social_media_post.csv"), toCsv(records, ODS_FIELDS));
  await fs.writeFile(path.join(outputDir, "crawl_audit.jsonl"), audit.map((item) => JSON.stringify(item)).join("\n") + (audit.length ? "\n" : ""));
  await fs.writeFile(path.join(outputDir, "crawl_tasks.jsonl"), audit.map((item) => JSON.stringify(item)).join("\n") + (audit.length ? "\n" : ""));
  await fs.writeFile(path.join(outputDir, "run_summary.json"), JSON.stringify({ keywordTaskId: config.keywordTaskId, query: config.query, projectName: config.projectName, dateWindow: [config.startDate, config.endDate], batchSize: config.batchSize, minContentLength: config.minContentLength, batchesProcessed, discovered: discovered.length, processed: audit.length, accepted: records.length, excludedNonNewsCount: audit.filter((item) => item.status === "excluded").length, olderDateCount, completionReason, stopReason, securityCooldownCount, securityExhaustedCount, maxSecurityRetries: config.maxSecurityRetries, securityCooldownMs: config.securityCooldownMs, resumed: resume, finishedAt: shanghaiDateTime(), timezone: "Asia/Shanghai" }, null, 2));
  await context.close();
}

let acceptanceReport = null;
if (!(args["skip-acceptance"] === true || args["skip-acceptance"] === "true") && mode !== "discover") {
  acceptanceReport = path.join(outputDir, "爬虫任务表.xlsx");
  await buildCrawlTaskWorkbook(outputDir, acceptanceReport);
}
const failedOrIncomplete = audit.filter((item) => item.status !== "excluded" && (["failed", "incomplete", "pending"].includes(item.status) || item.dateStatus === "unknown")).length;
const excludedNonNews = audit.filter((item) => item.status === "excluded").length;
console.log(JSON.stringify({ outputDir, batchesProcessed, discovered: discovered.length, processed: audit.length, accepted: records.length, excludedNonNews, failedOrIncomplete, olderDateCount, completionReason, stopReason, acceptanceReport }, null, 2));
