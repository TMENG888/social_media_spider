import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";
import { POST_FIELDS, COMMENT_FIELDS, blankRecord, canonicalXhsNoteUrl, extractId, normalizeXhsUrl, stableId } from "./schema.mjs";
import { beijingDateTime, buildThreadContent, dedupeUrls, parseCount, parsePublishedText, threadLikeCount } from "./xhs-utils.mjs";
import { cleanText, removeEmoji, splitDescriptionAndTags } from "./text-cleaner.mjs";
import { AsrService } from "./asr.mjs";
import { AsrJobProcessor } from "./asr-jobs.mjs";
import {finalizeAsr} from './asr-finalization.mjs';
import { incompleteCandidates } from "./candidate-acceptance.mjs";
import {attachScopeAudits,verifiedScopeExclusion} from './coverage-scope.mjs';
import {retrySnapshot} from './retry-no-change.mjs';
import {assessKeywordScope,SearchExhaustion,assessSearchAcceptance,SCOPE_POLICY} from './search-acceptance.mjs';
import {auditExistingScope,recordScope,scopeSummary} from './scope-audit.mjs';
import { openCheckpoint, setMeta, saveCandidates, checkpointCandidates, markCompleted, markSkipped, markFailed, markNoteDeadLetter, markImported, importedStats, exportCheckpoint, repairCheckpointDataQuality, writeJsonAtomic,detailAttemptLimit,asrJobStats } from "./checkpoint.mjs";
import {currentMediaSnapshot,bindCurrentMedia} from './media-provenance.mjs';
import { assessAsrAcceptance } from "./acceptance-gate.mjs";
import { importRows,mysqlConnectionOptions } from "./import-mysql.mjs";
import mysql from 'mysql2/promise';
import {readTaskVolume,validateVolumeSnapshot} from './volume-acceptance.mjs';
import { POLICY_VERSION, ACCEPTANCE_VERSION, YearBoundary, inTargetYear, validDate, scrollBudget } from "./collection-policy.mjs";
import { assertLocalLease } from "./lease-guard.mjs";
import { captureSearchState, closeDetailToSearch, ensureLatestSort, isKeywordSearchUrl, renderedControl, visibleAny, searchEndpointSnapshot, advanceSearchScroll } from "./xhs-browser-state.mjs";
import { collectionFailurePolicy } from "./collection-failure.mjs";
import { assertWebNoteAccessible, recoverWebUnavailableToSearch, WebUnavailableStreak, WEB_NOTE_UNAVAILABLE_PATTERN } from "./web-access-state.mjs";
import { itemPause, waitForPacing } from "./collection-pacing.mjs";
import { RateLimitCooldown, restrictionKind } from "./rate-limit-cooldown.mjs";
import {createPageDiagnostics} from './page-diagnostics.mjs';

function argsOf(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i += 1) {
    if (!argv[i].startsWith("--")) continue;
    const key = argv[i].slice(2), next = argv[i + 1];
    out[key] = !next || next.startsWith("--") ? true : next;
    if (out[key] !== true) i += 1;
  }
  return out;
}

const cli = argsOf(process.argv);
const volumeMode=process.env.SOCIAL_VOLUME_ENABLED==='1';
const volumeSnapshot=volumeMode?validateVolumeSnapshot(JSON.parse(await fs.readFile(process.env.SOCIAL_VOLUME_SNAPSHOT,'utf8')),{platform:'小红书'}):null;
const volumeRead=()=>readTaskVolume({connect:()=>mysql.createConnection(mysqlConnectionOptions()),snapshot:volumeSnapshot,taskId:process.env.XHS_LEASE_TASK_ID});
const configPath = path.resolve(String(cli.config || "config.json"));
let fileConfig = {};
try { fileConfig = JSON.parse(await fs.readFile(configPath, "utf8")); } catch {}
let keywordConfig = { keywords: fileConfig.keywords || [] };
try { keywordConfig = JSON.parse(await fs.readFile(path.resolve(String(cli.keywords || "keywords.json")), "utf8")); } catch {}
const entries = (Array.isArray(keywordConfig) ? keywordConfig : keywordConfig.keywords || []).map((item, index) =>
  typeof item === "string" ? { id: `XHS-${index + 1}`, keyword: item, enabled: true } : item
).filter((item) => item.enabled !== false && item.keyword);
if (cli.query) entries.splice(0, entries.length, { id: "XHS-SINGLE", keyword: String(cli.query), enabled: true });
if (!entries.length) throw new Error("没有可执行的小红书检索词");
const directNoteUrl = cli["note-url"] ? String(cli["note-url"]) : null;
const delayRange = (value, fallback) => Array.isArray(value) && value.length === 2 && value.every(Number.isFinite)
  ? [Math.max(0, Number(value[0])), Math.max(Number(value[0]), Number(value[1]))]
  : fallback;

const cfg = {
  scopeExcludedEntitiesByKeyword: fileConfig.scopeExcludedEntitiesByKeyword || {},
  projectName: String(cli["project-name"] || keywordConfig.projectName || fileConfig.projectName || "北京臻澐项目口碑"),
  // 两个专题的需求表均未定义分类。固定为数据库 NULL，禁止命令行、配置或任务清单覆盖。
  category: null,
  maxNotesPerKeyword: Number(cli["max-notes"] || fileConfig.maxNotesPerKeyword || 3),
  maxSearchScrolls: Number(cli["max-search-scrolls"] ?? fileConfig.maxSearchScrolls ?? 20),
  maxCommentScrolls: Number(fileConfig.maxCommentScrolls || 8),
  timeout: Number(fileConfig.navigationTimeoutMs || 45000),
  loginWaitSeconds: Number(cli["login-wait-seconds"] || fileConfig.loginWaitSeconds || 300),
  cdpUrl: String(cli["cdp-url"] || process.env.XHS_CDP_URL || fileConfig.cdpUrl || "http://127.0.0.1:9222"),
  headless: String(cli.headless ?? fileConfig.headless ?? false) === "true",
  detailInteractionMode: String(cli["detail-interaction-mode"] || fileConfig.detailInteractionMode || "click"),
  browserExecutable: String(cli["browser-executable"] || fileConfig.browserExecutable || "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
  visitAuthorProfile: false, // Author profile navigation belongs exclusively to phase two.
  outputDir: path.resolve(String(cli["output-dir"] || `runs/pilot-${new Date().toISOString().replace(/[:.]/g, "-")}`)),
  profileDir: path.resolve(String(cli["profile-dir"] || ".state/xhs-browser-profile")),
  checkpointDb: path.resolve(String(cli["checkpoint-db"] || path.join(String(cli["output-dir"] || "."), "checkpoint.sqlite"))),
  stopFile: cli["stop-file"] ? path.resolve(String(cli["stop-file"])) : null,
  actionDelayMs: delayRange(fileConfig.actionDelayMs, [1500, 3000]),
  detailDelayMs: delayRange(fileConfig.detailDelayMs, [3000, 6000]),
  keywordDelayMs: delayRange(fileConfig.keywordDelayMs, [8000, 15000]),
  batchSize: Math.max(1, Number(fileConfig.batchSize || 8)),
  batchCooldownMs: delayRange(fileConfig.batchCooldownMs, [45000, 90000]),
  maxConsecutiveFailures: Math.max(1, Number(fileConfig.maxConsecutiveFailures || 3)),
  asrEnabled: String(cli["asr-enabled"] ?? fileConfig.asrEnabled ?? true) !== "false",
  asrPythonExecutable: String(cli["asr-python"] || process.env.XHS_ASR_PYTHON || fileConfig.asrPythonExecutable || "python"),
  asrModel: String(process.env.XHS_ASR_MODEL_PATH || cli["asr-model"] || fileConfig.asrModel || "small"),
  asrLocalFilesOnly: Boolean(process.env.XHS_ASR_MODEL_PATH) || String(fileConfig.asrLocalFilesOnly ?? false) === "true",
  asrDevice: String(fileConfig.asrDevice || "cpu"),
  asrComputeType: String(fileConfig.asrComputeType || "int8"),
  asrLanguage: String(fileConfig.asrLanguage || "zh"),
  asrStartupTimeoutMs: Number(fileConfig.asrStartupTimeoutMs || 900000),
  asrDownloadTimeoutMs: Number(fileConfig.asrDownloadTimeoutMs || 600000),
  asrTranscriptionTimeoutMs: Number(fileConfig.asrTranscriptionTimeoutMs || 1800000),
  asrKeepMedia: Boolean(fileConfig.asrKeepMedia || false),
  asrCpuThreads: Math.max(1,Number(process.env.XHS_ASR_CPU_THREADS || fileConfig.asrCpuThreads || 4)),
  asrBeamSize: Number(fileConfig.asrBeamSize || 1),
  asrJobMaxAttempts: Math.max(1, Number(fileConfig.asrJobMaxAttempts || 3)),
  asrJobRetryDelayMs: Math.max(0, Number(fileConfig.asrJobRetryDelayMs || 3000)),
  minPublishedDate: String(cli.cutoff || cli["min-date"] || fileConfig.cutoff || fileConfig.minPublishedDate || ""),
  maxPublishedDate: "",
  collectAllCurrentYear: String(cli["collect-all-current-year"] ?? fileConfig.collectAllCurrentYear ?? false) === "true"
  ,collectComments: String(cli["collect-comments"] ?? fileConfig.collectComments ?? true) !== "false"
  ,searchStopWindow: Math.max(1, Number(cli["search-stop-window"] || fileConfig.searchStopWindow || 8))
  ,importBatchSize: Math.max(1, Number(cli["import-batch-size"] || fileConfig.importBatchSize || 20))
  ,skipImport: String(cli["skip-import"] ?? process.env.XHS_SKIP_IMPORT ?? false) === "true"
  ,runId: String(cli["run-id"] || `${Date.now()}-${process.pid}`)
  ,maxStagnantRounds: Math.max(2, Number(fileConfig.maxStagnantRounds || 15))
};
// Target dates filter content, never prove exhaustion of a nonmonotonic search.
cfg.targetYear = cfg.minPublishedDate ? Number(cfg.minPublishedDate.slice(0, 4)) : Number(beijingDateTime().slice(0, 4));
if (!["click", "navigate"].includes(cfg.detailInteractionMode)) throw new Error("detailInteractionMode只允许click或navigate");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const rand = async (min = 1200, max = 2500) => waitForPacing(Math.floor(min + Math.random() * (max - min + 1)), {shouldStop: stopRequested});
const randRange = async ([min, max]) => rand(min, max);
             const isOnOrAfter = (value, minDate) => {
  if (!minDate) return true;
  const parsed = String(value || "").slice(0, 10);
               return /^\d{4}-\d{2}-\d{2}$/.test(parsed) && parsed >= minDate;
             };
const isOnOrBefore = (value, maxDate) => {
               if (!maxDate) return true;
               const parsed = String(value || "").slice(0, 10);
               return /^\d{4}-\d{2}-\d{2}$/.test(parsed) && parsed <= maxDate;
             };
const text = async (root, selectors) => {
  for (const selector of selectors) {
    const locator = root.locator(selector);
    if (!(await locator.count().catch(() => 0))) continue;
    const value = await locator.first().textContent({ timeout: 2000 }).catch(() => null);
    if (value?.trim()) return value.trim();
  }
  return null;
};
const attr = async (root, selectors, name) => {
  for (const selector of selectors) {
    const locator = root.locator(selector);
    if (!(await locator.count().catch(() => 0))) continue;
    const value = await locator.first().getAttribute(name, { timeout: 2000 }).catch(() => null);
    if (value) return value;
  }
  return null;
};
const csvCell = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
const csv = (rows, fields) => `\uFEFF${fields.map(csvCell).join(",")}\n${rows.map((row) => fields.map((field) => csvCell(row[field])).join(",")).join("\n")}\n`;

let signalStopRequested = false;
let signalCount = 0;
const requestGracefulStop = (signal) => {
  signalCount += 1;
  if (signalCount > 1) process.exit(130);
  signalStopRequested = true;
  console.warn(`[安全停止] 收到${signal}，完成当前笔记并保存后停止；再次按Ctrl+C将强制退出`);
};
process.on("SIGINT", () => requestGracefulStop("SIGINT"));
if (process.platform === "win32") process.on("SIGBREAK", () => requestGracefulStop("SIGBREAK"));
const stopRequested = async () => {
  await assertLocalLease();
  return signalStopRequested || Boolean(cfg.stopFile && await fs.access(cfg.stopFile).then(() => true).catch(() => false));
};

async function connectBrowser() {
  try {
    const browser = await chromium.connectOverCDP(cfg.cdpUrl, { timeout: 5000 });
    const context = browser.contexts()[0];
    if (!context) throw new Error("CDP浏览器没有可用上下文");
    return { browser, context, owned: false, mode: "cdp" };
  } catch (error) {
    const context = await chromium.launchPersistentContext(cfg.profileDir, {
      headless: cfg.headless, executablePath: cfg.browserExecutable, viewport: { width: 1440, height: 1000 },
      locale: "zh-CN", timezoneId: "Asia/Shanghai", slowMo: 80
    });
    return { browser: null, context, owned: true, mode: `persistent (${error.message})` };
  }
}

const SECURITY_CHALLENGE_PATTERN = /安全验证|安全限制|访问频繁|操作频繁|请完成验证|网络环境存在风险|300013/;

async function securityChallengeMessage(page) {
  const bodyText = await page.locator("body").innerText({ timeout: 2000 }).catch(() => "");
  const match = SECURITY_CHALLENGE_PATTERN.exec(bodyText);
  if (!match) return null;
  // Report the actual warning, not the footer at the start of the page.
  return bodyText.slice(Math.max(0, match.index - 30), match.index + 170).replace(/\s+/g, " ").trim()
    || "检测到平台安全限制";
}

async function ensureLogin(page) {
  if (!page.url().includes("xiaohongshu.com")) {
    await page.goto("https://www.xiaohongshu.com/explore", { waitUntil: "domcontentloaded", timeout: cfg.timeout });
  }
  await page.waitForTimeout(1200);
  await assertNoSecurityChallenge(page);
  const deadline = Date.now() + cfg.loginWaitSeconds * 1000;
  while (true) {
    const loginVisible = await page.getByText(/登录后推荐更懂你的笔记|登录后查看搜索结果|扫码登录/).first().isVisible().catch(() => false);
    if (!loginVisible) return;
    await publishRestriction('STOP_LOGIN_REQUIRED：请在本机完成登录');
    if (Date.now() >= deadline) throw new Error("STOP_LOGIN_REQUIRED：等待人工登录超时，请登录后重新运行");
    await page.waitForTimeout(1000);
  }
}

let cooldownPublication=null, cooldownPublicationPromise=null;
async function publishRestriction(message){
  if(!process.env.XHS_COOLDOWN_CAMPAIGN || !restrictionKind(message))return;
  if(!cooldownPublicationPromise)cooldownPublicationPromise=(async()=>{
    let controller;
    try{
      controller=await RateLimitCooldown.open({root:process.env.XHS_WORKER_ROOT || process.cwd(),
        workerId:process.env.XHS_COOLDOWN_WORKER_ID,campaign:process.env.XHS_COOLDOWN_CAMPAIGN});
      cooldownPublication={state:await controller.record(message,'post:'+cfg.runId),published:true};
    }catch(error){
      cooldownPublication={published:false,error:error.code || 'COOLDOWN_STATE_UNAVAILABLE'};
      console.warn('[共享冷却] 发布失败；本节点停止，禁止盲目自动恢复');
    }finally{await controller?.close();}
  })();
  await cooldownPublicationPromise;
}
async function assertNoSecurityChallenge(page,{allowWebUnavailable=false}={}) {
  if (page.isClosed()) throw new Error("STOP_BROWSER_CLOSED：浏览器页签已关闭，保留断点后停止本节点");
  const message = await securityChallengeMessage(page);
  if (message) {
    await publishRestriction(`STOP_SECURITY_CHALLENGE：${message}`);
    await page.screenshot({ path: path.join(cfg.outputDir, `安全限制-${Date.now()}.png`), fullPage: false }).catch(() => {});
    throw new Error(`STOP_SECURITY_CHALLENGE：${message}`);
  }
  if(!allowWebUnavailable) await assertWebNoteAccessible(page).catch(async error => {
    await page.screenshot({path:path.join(cfg.outputDir, `网页不可访问-${Date.now()}.png`),fullPage:false}).catch(()=>{});
    throw error;
  });
}

async function waitForDetailOrSecurityChallenge(page) {
  const detailSelector = "#detail-title,#detail-desc";
  // 安全限制页会替代详情 DOM。等待两种结果中的任意一种，避免先空等完整
  // navigation timeout，再把风控误记为普通帖子失败并继续消耗其它任务。
  await assertNoSecurityChallenge(page);
  await page.waitForFunction(({ selector, securityPattern, unavailablePattern }) => {
    const bodyText = document.body?.innerText || "";
    const visible = [...document.querySelectorAll(selector)].some(node => {
      const box = node.getBoundingClientRect(), style = getComputedStyle(node);
      return box.width > 0 && box.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    });
    return visible || new RegExp(securityPattern).test(bodyText) || new RegExp(unavailablePattern).test(bodyText);
  }, { selector: detailSelector, securityPattern: SECURITY_CHALLENGE_PATTERN.source, unavailablePattern: WEB_NOTE_UNAVAILABLE_PATTERN.source }, { timeout: cfg.timeout });
  await assertNoSecurityChallenge(page);
  if (!await visibleAny(page, detailSelector)) {
    throw new Error("DETAIL_NOT_RENDERED：详情页主体未显示");
  }
}

async function* collectSearchLinks(page, keyword, progress) {
  progress.startedAt=new Date().toISOString();
  // URL参数不是排序已生效的证据；必须操作并核验页面的排序控件。
  const searchUrl = `https://www.xiaohongshu.com/search_result?keyword=${encodeURIComponent(keyword)}&source=web_explore_feed&type=51`;
  const input = page.locator('input#search-input:visible,input.search-input:visible,input[placeholder*="搜索"]:visible').first();
  if (await input.isVisible().catch(() => false)) {
    await input.fill(keyword);
    await input.press("Enter");
    await page.waitForURL(url => isKeywordSearchUrl(url.toString(), keyword), { timeout: 10000 }).catch(() => {});
    if (!isKeywordSearchUrl(page.url(), keyword)) {
      await assertNoSecurityChallenge(page);
      await page.goto(searchUrl, { waitUntil: "domcontentloaded", timeout: cfg.timeout });
    }
  } else {
    await page.goto(searchUrl, { waitUntil: "domcontentloaded", timeout: cfg.timeout });
  }
  await page.waitForTimeout(800);
  await ensureLogin(page);
  // Use the same tab/search box. The actual filter controls prove sorting;
  // redundant reloads discard SPA state and add unnecessary navigation.
  // 搜索结果默认排序可能不是最新；每个关键词搜索后优先切换到“最新”。
  await ensureLatestSort(page, keyword, { assertSafe: assertNoSecurityChallenge });
  progress.latestConfirmed=true;
  console.log(`[结果等待] ${keyword}：等待最新筛选后的帖子列表`);
  const resultSelector = 'section.note-item, .note-item, [data-note-id]';
  let resultsVisible = await page.waitForSelector(resultSelector, { timeout: 12000 }).then(() => true).catch(() => false);
  if (!resultsVisible) {
    console.warn(`[结果等待] ${keyword}：列表尚未渲染，保留已验证的最新排序再等待一次`);
    await ensureLogin(page);
    resultsVisible = await page.waitForSelector(resultSelector, { timeout: 15000 }).then(() => true).catch(() => false);
  }
  if (!resultsVisible) throw new Error(`SEARCH_RESULTS_NOT_RENDERED：${keyword}`);
  progress.origin={...await searchEndpointSnapshot(page,keyword,0),capturedAt:new Date().toISOString()};
  const links = new Map();
  const maxRounds = scrollBudget(cfg.collectAllCurrentYear, cfg.maxSearchScrolls);
  // 先多取候选，再由文章发布时间过滤，避免最新结果中混入旧帖导致今年数据不足。
  const candidateLimit = cfg.collectAllCurrentYear ? Number.MAX_SAFE_INTEGER : Math.max(cfg.maxNotesPerKeyword, cfg.maxNotesPerKeyword * 5);
  const yielded = new Set();
  const exhaustion=new SearchExhaustion({stableRounds:cfg.maxStagnantRounds});
  let stagnantRounds = 0;
  for (let round = 0; round < maxRounds && yielded.size < candidateLimit; round += 1) {
    const roundStartCount = links.size;
    let cards = null;
    // 每采集完一篇，作者页返回和详情遮罩关闭都可能令瀑布流局部重绘。
    // 因此不继续使用首次扫描的旧批次，而是重新读取当前DOM并点击仍然存在的下一张卡片。
    while (yielded.size < candidateLimit) {
      if (await stopRequested()) throw new Error("STOP_REQUESTED：搜索加载已安全停止");
      await assertNoSecurityChallenge(page);
      if (!isKeywordSearchUrl(page.url(), keyword)) {
        const error = new Error("STOP_SEARCH_CONTEXT_LOST：当前页面已不是本关键词结果页");
        error.observedAt = new Date().toISOString();
        error.pageDiagnostic = await pageDiagnostics?.capture('search_context_lost', error,
          {round:round+1,discovered:links.size,lastExamined:progress.examined});
        throw error;
      }
      const scanStartCount = links.size;
      const discoveredNow = [];
      const currentNotes = [];
      cards = page.locator(resultSelector).filter({ has: page.locator('a[href*="/search_result/"], a[href*="/explore/"]') });
      const visibleCards = await cards.evaluateAll(nodes => nodes.map(card => ({
        href: (card.querySelector('a[href*="/search_result/"]') || card.querySelector('a[href*="/explore/"]'))?.getAttribute("href"),
        noteId: card.getAttribute("data-note-id"),
        dateText: card.querySelector('.name-time-wrapper .time,.card-bottom-wrapper .time,.footer .date')?.textContent?.trim() || null
      })));
      for (const item of visibleCards) {
        const href = item.href;
        const noteId = item.noteId || extractId(href);
        if (!href || !noteId) continue;
        const note = links.get(noteId) || { noteId, url: normalizeXhsUrl(href), dateText: item.dateText };
        if (!links.has(noteId) && links.size < candidateLimit) {
          links.set(noteId, note);
          discoveredNow.push(note);
        }
        if (links.has(noteId) && !yielded.has(noteId)) currentNotes.push(note);
      }
      if (discoveredNow.length) saveCandidates(checkpoint, keyword, discoveredNow, scanStartCount);
      progress.rounds = round + 1;
      progress.discovered = links.size;
      const next = currentNotes[0];
      if (!next) break;
      yielded.add(next.noteId);
      console.log(`[搜索进度] ${keyword}：加载第${round + 1}轮${Number.isFinite(maxRounds) ? `/${maxRounds}` : "（年度连续采集）"}，本次新增${discoveredNow.length}篇，累计发现${links.size}篇；重新扫描后点击${next.noteId}`);
      yield next;
    }
    stagnantRounds = links.size === roundStartCount ? stagnantRounds + 1 : 0;
    const endState=await searchEndpointSnapshot(page,keyword,links.size);
    endState.capturedAt=new Date().toISOString();
    const endEvidence=exhaustion.observe(endState);
    progress.exhaustion=endEvidence;
    if (endEvidence.ok) {
      console.log(`[搜索完成] ${keyword}：已核验搜索终点，连续${endEvidence.stableRounds}次健康扫描无新增结果；范围为平台当前可见搜索结果`);
      progress.reason = "platform_exhausted";
      progress.finishedAt=new Date().toISOString();
      return;
    }
    if(stagnantRounds>=cfg.maxStagnantRounds*3)throw new Error('SEARCH_EXHAUSTION_UNCONFIRMED：长期无新增但未核验健康搜索终点，不得冒充年度完成');
    // 使用页面级滚动并将最后一张卡片带入视口，兼容瀑布流虚拟列表和懒加载。
    await cards?.last().scrollIntoViewIfNeeded().catch(() => {});
    await advanceSearchScroll(page);
    await page.mouse.wheel(0, Math.floor(900 + Math.random() * 700));
    await randRange(cfg.actionDelayMs);
  }
  progress.reason = "search_limit";
}

async function expandComments(page) {
  for (let round = 0; round < cfg.maxCommentScrolls; round += 1) {
    const expanders = page.getByText(/展开.*回复|查看更多回复|展开更多/, { exact: false });
    const count = await expanders.count().catch(() => 0);
    for (let i = 0; i < Math.min(count, 10); i += 1) {
      const button = expanders.nth(i);
      if (await button.isVisible().catch(() => false)) await button.click().catch(() => {});
    }
    const list = page.locator(".comments-container,.list-container").last();
    if (await list.count()) await list.evaluate((node) => node.scrollBy(0, node.scrollHeight)).catch(() => {});
    else await page.mouse.wheel(0, 800);
    await rand(Math.max(700, Math.floor(cfg.actionDelayMs[0] / 2)), Math.max(1400, Math.floor(cfg.actionDelayMs[1] / 2)));
  }
}

async function parseCommentItem(item) {
  const idAttr = await item.getAttribute("id");
  const userLink = await attr(item, ['a.name[href*="/user/profile/"]', 'a[href*="/user/profile/"]'], "href");
  const dateText = await text(item, [".info .date", ".date"]);
  const location = await text(item, [".info .location", ".location"]);
  const likeText = await text(item, [".info .like .count", ".like-wrapper .count"]);
  const content = removeEmoji(await text(item, [".content .note-text", ".content"]));
  const author = removeEmoji(await text(item, [".author .name", "a.name"]));
  const replyTarget = content?.match(/^回复\s*([^：:]+)[：:]/)?.[1] || null;
  return {
    commentId: extractId(idAttr, "comment"), userLink: userLink ? new URL(userLink, "https://www.xiaohongshu.com").toString() : null,
    userId: extractId(userLink, "user"), author, content, dateText, location,
    likeCount: likeText?.trim() === "赞" ? 0 : parseCount(likeText), replyTarget
  };
}

async function parseThreads(page, post, context) {
  await expandComments(page);
  const rows = [], audits = [];
  const containers = page.locator(".list-container .parent-comment");
  for (let i = 0; i < await containers.count(); i += 1) {
    const items = containers.nth(i).locator(".comment-item");
    if (!(await items.count())) continue;
    const root = await parseCommentItem(items.nth(0));
    if (!root.commentId || !root.content) continue;
    const replies = [];
    for (let j = 1; j < await items.count(); j += 1) {
      const reply = await parseCommentItem(items.nth(j));
      if (reply.content) replies.push(reply);
    }
    const displayedReplyText = await text(containers.nth(i), [".show-more", ".reply-container .show-more", ".reply-container [class*=more]"]);
    const displayedReplyCount = parseCount(displayedReplyText?.match(/(?:展开|共|查看)\s*([\d.]+\s*[万wWkK]?)\s*条?回复/)?.[1]);
    const threadAudit = {
      aggregation_mode: "comment_thread", root_comment_id: root.commentId,
      displayed_reply_count: displayedReplyCount, captured_reply_count: replies.length,
      root_like_count: root.likeCount, child_like_count: threadLikeCount({ likeCount: 0 }, replies),
      thread_like_count: threadLikeCount(root, replies),
      thread_complete: displayedReplyCount == null ? null : replies.length >= displayedReplyCount,
      child_comments: replies.map((r) => ({ comment_id: r.commentId, user_id: r.userId, user_name: r.author, reply_target: r.replyTarget, time_raw: r.dateText, location: r.location, like_count: r.likeCount }))
    };
    const rawThreadContent = buildThreadContent(root, replies);
    const cleanedThread = cleanText(rawThreadContent, { removeEmoji: true, singleParagraph: true });
    const row = blankRecord(COMMENT_FIELDS);
    Object.assign(row, {
      id: null, 评论id: root.commentId, 评论用户链接: root.userLink, 评论用户id: root.userId,
      评论用户名字: root.author, 评论内容: cleanedThread.text, 评论时间: parsePublishedText(root.dateText, new Date(`${context.capturedAt.replace(" ", "T")}+08:00`)) || root.dateText,
      评论IP: root.location, 评论点赞数: threadLikeCount(root, replies), 评论回复数: displayedReplyCount ?? replies.length,
      文章链接: post["文章链接"], 文章id: post["文章id"], 关键词: context.keyword, 评论获取时间: context.capturedAt,
      平台: "小红书", 分类: null, 项目: context.projectName || cfg.projectName, 清洗标注: JSON.stringify(cleanedThread.stats)
    });
    rows.push(row);
    audits.push({
      article_id: post["文章id"], comment_id: root.commentId,
      raw_text: rawThreadContent, cleaned_text: cleanedThread.text,
      cleaning_stats: cleanedThread.stats, ...threadAudit
    });
  }
  return { rows, audits };
}

async function returnFromAuthorToDetail(page, recovery) {
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    await page.goBack({ waitUntil: "domcontentloaded", timeout: cfg.timeout }).catch(() => {});
    await page.waitForTimeout(900);
    await assertNoSecurityChallenge(page);
    if (await visibleAny(page, "#detail-title,#detail-desc")) return attempt;
    const currentUrl = page.url();
    if (currentUrl.includes("/user/profile/")) continue;
    const detailRendered = await page.waitForSelector("#detail-title,#detail-desc", { state: "visible", timeout: 8000 }).then(() => true).catch(() => false);
    if (detailRendered) return attempt;
    if (recovery?.searchState && recovery?.note) {
      console.warn(`[作者返回恢复] 历史项没有保留帖子弹层；恢复“${recovery.searchState.keyword}”原搜索页并重新点击原帖`);
      await closePostToSearch(page, recovery.searchState);
      // Do not navigate directly to a detail URL or consume home recommendations.
      // Only reopen the exact original note from the verified keyword list.
      for (let scan = 0; scan < 4; scan += 1) {
        await assertNoSecurityChallenge(page);
        if (!isKeywordSearchUrl(page.url(), recovery.searchState.keyword)) break;
        const original = await renderedControl(page.locator(`a[href*="/search_result/${recovery.note.noteId}"],a[href*="/explore/${recovery.note.noteId}"]`));
        console.log(`[作者返回恢复] 原帖${recovery.note.noteId}：定位第${scan + 1}/4轮，搜索卡片${await page.locator('section.note-item,.note-item').count()}张，原帖入口${original ? '存在' : '未加载'}`);
        if (original) {
          await openPostFromSearch(page, recovery.note, recovery.searchState.keyword);
          await waitForDetailOrSecurityChallenge(page);
          return attempt;
        }
        await page.mouse.wheel(0, 700);
        await page.waitForTimeout(1500);
      }
      throw new Error('STOP_DETAIL_CONTEXT_LOST：已恢复最新搜索页，但有限扫描仍找不到原帖；保留断点停止');
    }
    throw new Error(`STOP_DETAIL_CONTEXT_LOST：作者页返回后既不是作者页也没有帖子详情，当前页面=${currentUrl}`);
  }
  throw new Error("STOP_DETAIL_CONTEXT_LOST：连续三个作者历史项后仍未返回帖子详情");
}

async function authorStats(page, authorUrl, recovery) {
  if (!cfg.visitAuthorProfile || !authorUrl) return {};
  const authorId = extractId(authorUrl, "user");
  const detail = await renderedControl(page.locator('#noteContainer,.note-container'));
  // The same author link also exists on the search card behind the overlay.
  // Never force-click that background card or a hidden duplicate control.
  const candidates = detail?.locator(authorId ? `a[href*="/user/profile/${authorId}"]` : 'a[href*="/user/profile/"]');
  const link = candidates ? await renderedControl(candidates) : null;
  if (!link) {
    console.warn(`[作者主页] ${authorUrl}：详情弹层未找到可见作者入口，作者统计保持空值`);
    return {};
  }
  const pagesBefore = new Set(page.context().pages());
  let profileOpened = false;
  let profileRouteChanged = false;
  let profileError = null;
  let clickMethod = "mouse";
  try {
    await link.scrollIntoViewIfNeeded().catch(() => {});
    await link.evaluate((node) => node.removeAttribute("target")).catch(() => {});
    await link.click({ timeout: 8000 });
    await page.waitForURL((url) => url.pathname.includes("/user/profile/"), { timeout: 8000 }).catch(() => {});
    const unexpectedPages = page.context().pages().filter((candidate) => !pagesBefore.has(candidate));
    for (const unexpected of unexpectedPages) await unexpected.close().catch(() => {});
    const profileBody = await page.locator("body").innerText({ timeout: 3000 }).catch(() => "");
    profileRouteChanged = page.url().includes("/user/profile/");
    profileOpened = profileRouteChanged || (/获赞与收藏/.test(profileBody) && /粉丝/.test(profileBody));
    if (!profileOpened) {
      console.warn(`[作者主页] ${authorUrl}：页内点击未进入作者页，作者统计保持空值`);
      return {};
    }
    await page.waitForTimeout(1800);
    await assertNoSecurityChallenge(page);
    const all = await page.locator("body").innerText();
    const fans = all.match(/([\d.]+\s*[万亿wWkK]?)\s*粉丝/);
    const likes = all.match(/([\d.]+\s*[万亿wWkK]?)\s*获赞与收藏/);
    console.log(`[作者主页] 页内点击完成(${clickMethod})：${authorUrl}，浏览器页签数=${page.context().pages().length}`);
    return { followerCount: parseCount(fans?.[1]), likeCount: parseCount(likes?.[1]) };
  } catch (error) {
    profileError = error;
    if (String(error?.message || error).startsWith("STOP_")) throw error;
    console.warn(`[作者主页] ${authorUrl}：页内点击或读取失败，作者统计保持空值：${String(error?.message || error).split("\n")[0]}`);
    return {};
  } finally {
    if (profileOpened && !page.isClosed() && !String(profileError?.message || "").startsWith("STOP_")) {
      let backSteps = 0;
      if (profileRouteChanged) backSteps = await returnFromAuthorToDetail(page, recovery);
      else {
        await page.keyboard.press("Escape").catch(() => {});
        await waitForDetailOrSecurityChallenge(page);
      }
      console.log(`[作者主页] 已返回当前帖子详情，回退${backSteps || 1}层，继续采集，浏览器页签数=${page.context().pages().length}`);
    }
  }
}

async function openPostFromSearch(page, note, keyword) {
  const state = await captureSearchState(page, keyword);
  await page.evaluate(() => performance.clearResourceTimings()).catch(() => {});
  const candidates = page.locator(`a[href*="/search_result/${note.noteId}"],a[href*="/explore/${note.noteId}"]`);
  const link = await renderedControl(candidates);
  if (!link) throw new Error(`DETAIL_CARD_NOT_VISIBLE：搜索结果中无法页内点击${note.noteId}`);
  const pagesBefore = new Set(page.context().pages());
  await link.scrollIntoViewIfNeeded().catch(() => {});
  await link.evaluate((node) => node.removeAttribute("target")).catch(() => {});
  await link.click({ timeout: 10000 });
  await waitForDetailOrSecurityChallenge(page);
  const unexpectedPages = page.context().pages().filter((candidate) => !pagesBefore.has(candidate));
  if (unexpectedPages.length) {
    for (const unexpected of unexpectedPages) await unexpected.close().catch(() => {});
    throw new Error("DETAIL_OPENED_NEW_PAGE：帖子未按预期在当前搜索页打开");
  }
  console.log(`[详情打开] ${keyword} / ${note.noteId}：已在搜索结果页内点击打开，浏览器页签数=${page.context().pages().length}`);
  return state;
}

async function closePostToSearch(page, state,{allowWebUnavailable=false}={}) {
  pageDiagnostics?.mark('detail_close_started',{expectedSearchUrl:state.searchUrl,keyword:state.keyword});
  try {
    const result = allowWebUnavailable
      ? await recoverWebUnavailableToSearch(page,state,{timeout:cfg.timeout,assertSafe:p=>assertNoSecurityChallenge(p,{allowWebUnavailable:true}),assertStrict:assertNoSecurityChallenge})
      : await closeDetailToSearch(page, state, { timeout: cfg.timeout, assertSafe: assertNoSecurityChallenge });
    pageDiagnostics?.mark('detail_close_verified',{method:result?.method});
    return result;
  } catch(error) {
    pageDiagnostics?.mark('detail_close_failed',{error:String(error.message||error)});
    throw error;
  }
}
async function parsePost(page, note, context, { navigate = true } = {}) {
  if (navigate) await page.goto(note.url, { waitUntil: "domcontentloaded", timeout: cfg.timeout });
  await waitForDetailOrSecurityChallenge(page);
  await page.waitForTimeout(1800);
  await assertNoSecurityChallenge(page);
  // Capture the immutable article URL before visiting the author profile. The
  // detail is an overlay, so page.url() can legitimately become the search URL
  // again after returning from the profile.
  const detailUrl = canonicalXhsNoteUrl(note.noteId || extractId(page.url()), note.url || page.url());
  const detailRoot = page.locator('#noteContainer:visible,.note-container:visible,[class*="note-container"]:visible').first();
  const root = await detailRoot.count() ? detailRoot : page;
  const title = removeEmoji(await text(root, ["#detail-title", "h1.title"]));
  const rawContent = await text(root, ["#detail-desc", ".desc"]);
  const domTags = await page.locator('#detail-desc a[href*="/search_result"],#detail-desc .tag').allTextContents().catch(() => []);
  const parsedDescription = splitDescriptionAndTags(rawContent, domTags);
  const authorUrlRaw = await attr(root, ['.author-container a[href*="/user/profile/"]', '.author a[href*="/user/profile/"]', 'a[href*="/user/profile/"]'], "href");
  const authorUrl = authorUrlRaw ? new URL(authorUrlRaw, "https://www.xiaohongshu.com").toString() : null;
  const authorName = removeEmoji(await text(root, [".author-container .name", ".info .username", 'a[href*="/user/profile/"] .name']));
  const dateRaw = await text(root, [".bottom-container .date", ".note-content .date"]);
  const publishedAt = parsePublishedText(dateRaw);
  // Validate the visible detail date before downloading video, visiting authors,
  // or expanding comments. No ID-derived timestamp is used for acceptance.
  if (!validDate(publishedAt)) throw new Error(`DATE_UNRESOLVED：详情页发布时间无法解析：${dateRaw || "空"}`);
  if (!inTargetYear(publishedAt, cfg.targetYear, cfg.minPublishedDate || `${cfg.targetYear}-01-01`)) {
    return { outsideYear: true, publishedAt, dateRaw, comments: [] };
  }
  const scopeEvidence={title,body:parsedDescription.content,tags:parsedDescription.tags};
  const scopeAssessment=assessKeywordScope(context.keyword,{scopeEvidence},{excludedEntities:cfg.scopeExcludedEntitiesByKeyword[context.keyword]||[]});
  if(scopeAssessment.status==='unobserved')throw new Error('SCOPE_DETAIL_CONTENT_NOT_OBSERVED：未读取到相关性核验正文，不可自动跳过');
  if(scopeAssessment.status==='out_of_scope')return {outsideScope:true,publishedAt,scopeEvidence,scopeAssessment,comments:[]};
  const location = await text(root, [".bottom-container .location", ".note-content .location"]);
  const countValue = async (selectors, zeroLabel) => {
    const value = await text(root, selectors);
    return value?.trim() === zeroLabel ? 0 : parseCount(value);
  };
  const likeCount = await countValue([".engage-bar-container .like-wrapper .count", ".engage-bar .like-wrapper .count"], "赞");
  const favoriteCount = await countValue([".engage-bar-container .collect-wrapper .count", ".engage-bar .collect-wrapper .count"], "收藏");
  const commentCount = await countValue([".engage-bar-container .chat-wrapper .count", ".engage-bar .chat-wrapper .count"], "评论");
  const shareCount = await countValue([".engage-bar-container .share-wrapper .count", ".engage-bar .share-wrapper .count"], "分享");
  const images = dedupeUrls(await root.locator('.swiper-slide img[src*="xhscdn.com"],.note-slider-img img[src*="xhscdn.com"]').evaluateAll((nodes) => nodes.map((n) => n.currentSrc || n.src)).catch(() => []));
  const hasVideo = await root.locator("video").count() > 0;
  const videoInfo = hasVideo ? await root.locator("video").first().evaluate((v) => ({ src: v.currentSrc || v.src || v.querySelector('source')?.src || null, duration: Number.isFinite(v.duration) ? Math.round(v.duration) : null })).catch(() => ({})) : {};
  let media={ok:false},mediaSnapshot=null;
  if(hasVideo)for(let probe=0;probe<20;probe++){
    if(await stopRequested())throw new Error('STOP_REQUESTED：媒体加载期间收到安全停止');
    mediaSnapshot=await detailRoot.evaluate(currentMediaSnapshot,note.noteId).catch(()=>null);
    media=bindCurrentMedia(mediaSnapshot);
    if(media.ok)break;
    if(probe%5===0)await assertNoSecurityChallenge(page);
    await page.waitForTimeout(400);
  }
  if(media.ok&&String(removeEmoji(mediaSnapshot.visibleTitle)||'').replace(/\s+/g,'')!==String(title||'').replace(/\s+/g,''))throw new Error('DETAIL_CHANGED_DURING_MEDIA_LOAD：媒体加载期间帖子标题发生切换');
  const actualVideoUrl = media.ok ? media.url : null;
  const asrMediaUrl = actualVideoUrl;
  // Live Photos also render short <video> elements beside an image carousel.
  // Only treat a note as a video post when a real stream is found or no image
  // carousel exists; otherwise retain it as image-text content.
  const isVideoPost = Boolean(actualVideoUrl) || (hasVideo && images.length === 0);
  // The DOM player may still hold the previous video's tracks during SPA
  // transitions. Decode only the note-bound file; never accept a single
  // currently visible caption as the full transcript.
  let subtitle = { text: null, source: null };
  let asrJob = null;
  if (isVideoPost && !subtitle.text && asrMediaUrl && cfg.asrEnabled) {
    const articleId = note.noteId || extractId(detailUrl);
    asrJob = { keyword: context.keyword, noteId: articleId, articleId, mediaUrl: asrMediaUrl, mediaBinding:media.binding,
      referer: detailUrl, prompt: [context.keyword, title, parsedDescription.tags].filter(Boolean).join("，") };
    subtitle = { text: null, source: null, audit: { status: "pending" } };
  }
  if (subtitle.text) subtitle.text = cleanText(subtitle.text, { removeEmoji: true, singleParagraph: true, paragraphSeparator: "，" }).text || null;
  if (isVideoPost) console.log(`[字幕/ASR] ${note.noteId}：${subtitle.text ? `成功（${subtitle.source || "subtitle"}）` : !asrMediaUrl ? "视频媒体地址缺失，ASR未执行" : asrJob ? "待详情保存后进入后台ASR队列" : subtitle.audit?.status === "no_speech" ? "音轨未识别到口播" : "ASR未完成"}`);
  const stats = {}; // Save the post/comments/ASR job without leaving the detail.
  const url = detailUrl;
  const post = blankRecord(POST_FIELDS);
  Object.assign(post, {
    id: null, 文章图片链接: images.length ? JSON.stringify(images) : null, 文章图片信息: null,
    作者名字: authorName, 文章标题: title, 文章内容: parsedDescription.content, 文章标签: parsedDescription.tags,
    文章时间地点: publishedAt, 文章点赞数: likeCount,
    文章收藏数: favoriteCount, 文章评论数: commentCount,
    文章链接: url, 文章id: note.noteId || extractId(url), 作者主页链接: authorUrl,
    文章视频链接: actualVideoUrl ? JSON.stringify([actualVideoUrl]) : null, 文章视频内容: subtitle.text,
    关键词: context.keyword, 作者id: extractId(authorUrl, "user"), 作者粉丝数: stats.followerCount ?? null,
    作者点赞数: stats.likeCount ?? null, 文章分享数: shareCount, 文章视频时长: isVideoPost ? (media.ok?Math.round(media.binding.expectedDuration):videoInfo.duration??null) : null,
    平台: "小红书", 文章获取时间: context.capturedAt, 文章标注: null, 分类: null, 清洗标注: JSON.stringify(parsedDescription.stats),
    项目: context.projectName || cfg.projectName, 地点: location || dateRaw?.match(/\s(北京|天津|上海|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|海南|四川|贵州|云南|陕西|甘肃|青海|台湾|内蒙古|广西|西藏|宁夏|新疆|香港|澳门|海外)$/)?.[1] || null, 内容类型: isVideoPost ? "视频" : images.length ? "图文" : "纯文本",
    是否广告: null, 广告关键词: null
  });
  const comments = cfg.collectComments ? await parseThreads(page, post, context) : { rows: [], audits: [] };
  return {
    post, comments: comments.rows, commentAudits: comments.audits,
    postTextAudit: { article_id: post["文章id"], date_source: "detail_page", date_raw: dateRaw, raw_text: rawContent || "", body_before_cleaning: parsedDescription.bodyBeforeCleaning, cleaned_text: parsedDescription.content, tags: parsedDescription.tags, cleaning_stats: parsedDescription.stats, subtitle_source: subtitle.source, subtitle_status: !isVideoPost ? "not_video" : subtitle.text ? "extracted" : !asrMediaUrl ? "media_url_missing" : asrJob ? "pending" : subtitle.audit?.status === "no_speech" ? "no_speech" : "asr_failed", subtitle_error: subtitle.error || null, subtitle_audit: subtitle.audit || null },
    asrJob,
    mediaProvenance:media.ok?media.binding:{verified:false,reason:media.reason||'not_video'}
  };
}

await fs.mkdir(cfg.outputDir, { recursive: true });
await fs.mkdir(path.dirname(cfg.checkpointDb), { recursive: true });
const checkpoint = openCheckpoint(cfg.checkpointDb);
const retryBefore = entries.length===1 ? retrySnapshot(checkpoint,entries[0].keyword) : null;
const repairedQuality = repairCheckpointDataQuality(checkpoint);
if (repairedQuality.links || repairedQuality.asr) console.log(`[数据质量修复] 文章链接${repairedQuality.links}条，低质量ASR${repairedQuality.asr}条已标记重采`);
for(const task of entries){
  const audit=auditExistingScope(checkpoint,task.keyword,{excludedEntities:cfg.scopeExcludedEntitiesByKeyword[task.keyword]||[]});
  console.log(`[范围复核] ${task.keyword}：相关${audit.accepted}，明确范围外${audit.out_of_scope}，相关性不确定${audit.uncertain}，待重新读取${audit.unobserved}；旧库范围外记录保留${audit.legacyImportedExcluded}篇`);
}
// 增量入库：每累计 importBatchSize 篇文章触发一次异步 MySQL 入库并登记断点表，异常终止后恢复时可避免重复入库与漏库。
let importSeq = 0, incrementalBatches = 0, incrementalPosts = 0, incrementalComments = 0;
let importQueue = Promise.resolve();
function enqueueImport(keyword, batch) {
  if (!batch.length || cfg.skipImport) return;
  importSeq += 1;
  const batchId = `${stableId(keyword)}-${cfg.runId}-${String(importSeq).padStart(3, "0")}`;
  importQueue = importQueue.then(() => runIncrementalImport(keyword, batchId, batch)).catch((error) => {
    console.warn(`[增量入库] 批次${batchId}失败，任务收尾时仍会全量兜底入库：${String(error?.message || error).split("\n")[0]}`);
  });
}
async function runIncrementalImport(keyword, batchId, batch) {
  const posts = batch.map((item) => item.post).filter(Boolean);
  const comments = batch.flatMap((item) => item.comments || []);
  if (!posts.length) return;
  const batchDir = path.join(cfg.outputDir, "import-batches", batchId);
  await fs.mkdir(batchDir, { recursive: true });
  await fs.writeFile(path.join(batchDir, "ods_social_media_post.jsonl"), posts.map(JSON.stringify).join("\n") + "\n", "utf8");
  await fs.writeFile(path.join(batchDir, "ods_social_media_comment.jsonl"), comments.map(JSON.stringify).join("\n") + (comments.length ? "\n" : ""), "utf8");
  if (!process.env.MYSQL_USER || !process.env.MYSQL_PASSWORD) {
    console.warn(`[增量入库] 批次${batchId}：未提供 MySQL 凭据，跳过增量入库，批次文件已保留，待任务收尾全量入库`);
    return;
  }
  const startedAt = beijingDateTime();
  try {
    const result = await importRows({ posts, comments });
    incrementalBatches += 1;
    incrementalPosts += result.postResult.inserted + result.postResult.updated;
    incrementalComments += result.commentResult.inserted + result.commentResult.updated;
    markImported(checkpoint, keyword, batchId, batch.flatMap((item) => [
      { table: "ods_social_media_post", key: item.post["文章id"], noteId: item.noteId },
      ...(item.comments || []).map((comment) => ({ table: "ods_social_media_comment", key: comment["评论id"], noteId: item.noteId }))
    ]));
    await writeJsonAtomic(path.join(batchDir, "mysql_import_status.json"), { status: "success", postResult: result.postResult, commentResult: result.commentResult, batchId, keyword, committedAt: startedAt });
    console.log(`[增量入库] 批次${batchId}：${posts.length}篇帖子、${comments.length}条评论讨论串已入库（累计${incrementalBatches}批次 / ${incrementalPosts}篇）`);
  } catch (error) {
    await writeJsonAtomic(path.join(batchDir, "mysql_import_status.json"), { status: "failed", error: String(error?.message || error), batchId, keyword, committedAt: startedAt }).catch(() => {});
    throw error;
  }
}
setMeta(checkpoint, "configuration", { projectName: cfg.projectName, minPublishedDate: cfg.minPublishedDate, targetYear: cfg.targetYear, searchStopWindow: cfg.searchStopWindow, policyVersion: POLICY_VERSION, collectComments: cfg.collectComments });
let asrService = null;
const getAsrService = () => {
  if (!asrService) asrService = new AsrService({
    pythonExecutable: cfg.asrPythonExecutable, model: cfg.asrModel, device: cfg.asrDevice,
    computeType: cfg.asrComputeType, language: cfg.asrLanguage, cpuThreads: cfg.asrCpuThreads, beamSize: cfg.asrBeamSize,
    cacheDir: path.join(cfg.profileDir, "asr-models", "transcripts"),
    modelDir: path.join(cfg.profileDir, "asr-models"), tempDir: path.join(cfg.outputDir, ".asr-temp"),
    startupTimeoutMs: cfg.asrStartupTimeoutMs, downloadTimeoutMs: cfg.asrDownloadTimeoutMs,
    transcriptionTimeoutMs: cfg.asrTranscriptionTimeoutMs, keepMedia: cfg.asrKeepMedia,
    localFilesOnly: cfg.asrLocalFilesOnly
  });
  return asrService;
};
const asrJobs = cfg.asrEnabled ? new AsrJobProcessor({
  db: checkpoint, service: getAsrService(),
  mediaDir: path.join(path.dirname(cfg.checkpointDb), "asr-media"),
  maxAttempts: cfg.asrJobMaxAttempts, retryDelayMs: cfg.asrJobRetryDelayMs,
  keepMedia: cfg.asrKeepMedia,
  shouldStop: async () => signalStopRequested || Boolean(cfg.stopFile && await fs.access(cfg.stopFile).then(() => true).catch(() => false)),
  onCompleted: async (_job, _output, updated) => {
    if (cfg.skipImport || !process.env.MYSQL_USER || !process.env.MYSQL_PASSWORD) return;
    await importRows({ posts: [updated.post], comments: [] });
  }
}) : null;
asrJobs?.start();
let session = null;
let searchPage = null;
let pageDiagnostics = null, failureDiagnostic = null, firstFailureAt = null;
let completedDetails = 0, consecutiveFailures = 0, runError = null, runStatus = "running";
const searchSummaries = [];
try {
  session = await connectBrowser();
  searchPage = session.context.pages()[0] || await session.context.newPage();
  searchPage.setDefaultTimeout(cfg.timeout);
  await ensureLogin(searchPage);
  for (const task of entries) {
    if (await stopRequested()) throw new Error("STOP_REQUESTED：已在进入下一个关键词前安全停止");
    pageDiagnostics?.dispose();
    pageDiagnostics = createPageDiagnostics({page:searchPage,platform:'小红书',keyword:task.keyword,
      outputDir:cfg.outputDir,workerId:process.env.XHS_COOLDOWN_WORKER_ID||'',runId:cfg.runId});
    pageDiagnostics.mark('keyword_started');
    console.log(`[检索开始] ${task.keyword}`);
    const progress = { keyword: task.keyword, rounds: 0, discovered: 0, examined: 0, accepted: 0, skipped: 0, excludedScope:0, failed: 0, reason: null };
    searchSummaries.push(progress);
    const saved = new Map(attachScopeAudits(checkpoint,checkpointCandidates(checkpoint, task.keyword),task.keyword).map(item => [item.noteId, item]));
    const boundary = new YearBoundary(cfg.targetYear, cfg.searchStopWindow);
    const unavailableStreak=new WebUnavailableStreak();
    const failedNotes = new Set();
    const importBuffer = [];
    const projectName = task.projectName || cfg.projectName;
    async function processNote(note, trackBoundary = true, recoverSaved = false) {
      if (await stopRequested()) throw new Error("STOP_REQUESTED：已在打开下一篇笔记前安全停止");
      const cached = saved.get(note.noteId);
      if(cached?.status==='skipped_irrelevant'&&verifiedScopeExclusion(cached,task.keyword)){
        progress.examined++;progress.excludedScope++;
        console.log(`[范围排除] ${note.noteId}：已留存关键词锚点缺失证据，不重新采集、不计有效帖子`);
        return;
      }
      // A parent-keyword reset may revisit a naturally encountered old detail
      // gap once in this scan. Keep its cumulative attempts and old evidence;
      // do not spawn an individual-note recovery task or reset its history.
      if(!volumeMode&&cached?.status==='dead_letter'){
        if(trackBoundary)boundary.observe(note.noteId,null);
        progress.deadLetters=(progress.deadLetters||0)+1;
        console.log(`[明确跳过] ${note.noteId}：已保留不可采证据，不自动复活，不计采集成功`);
        return;
      }
      const retryFailedAsr = !volumeMode && cached?.status === "completed" && cached.attempts < detailAttemptLimit(checkpoint,task.keyword,note.noteId) &&
        cached.result?.post?.["内容类型"] === "视频" && !cached.result?.post?.["文章视频内容"] &&
        ['asr_failed','media_url_missing','source_recheck_required'].includes(cached.result?.postTextAudit?.subtitle_status);
      if (retryFailedAsr) console.log(`[ASR重试] ${task.keyword} / ${note.noteId}：旧断点为ASR失败，使用本地模型重新解析（第${cached.attempts + 1}次）`);
      if (cached?.status === "completed" && !retryFailedAsr && cached.projectName === projectName && inTargetYear(cached.publishedAt, cfg.targetYear, cfg.minPublishedDate)) {
        if (trackBoundary) boundary.observe(note.noteId, cached.publishedAt);
        progress.examined += 1;
        progress.accepted += 1;
        console.log(`[断点跳过] ${task.keyword} / ${note.noteId}：已核验${cached.publishedAt}`);
        return;
      }
      if (cached?.status === "skipped_old" && validDate(cached.publishedAt) && !inTargetYear(cached.publishedAt, cfg.targetYear, cfg.minPublishedDate)) {
        if (trackBoundary) boundary.observe(note.noteId, cached.publishedAt);
        progress.examined += 1;
        progress.skipped += 1;
        return;
      }
      console.log(`[详情开始] ${task.keyword} / ${note.noteId}`);
      // A saved candidate may no longer have a clickable card in the current
      // virtual search list. Verify its original detail URL in a temporary tab
      // instead of repeatedly treating the missing card as a content failure.
      const detail = recoverSaved ? await session.context.newPage() : searchPage;
      detail.setDefaultTimeout(cfg.timeout);
      let inPlaceState = null;
      let primaryError = null;
      let handledUnavailable=false;
      try {
        const useInPlaceClick = !recoverSaved && cfg.detailInteractionMode === "click" && !directNoteUrl;
        if (useInPlaceClick) {
          // Capture before opening: even a partially opened/missing detail must
          // be restored, otherwise the next iteration may consume home cards.
          inPlaceState = await captureSearchState(detail, task.keyword);
          pageDiagnostics?.mark('detail_open_started',{noteId:note.noteId});
          await openPostFromSearch(detail, note, task.keyword);
          pageDiagnostics?.mark('detail_opened',{noteId:note.noteId});
        }
        if (recoverSaved) {
          await detail.goto(note.url, { waitUntil: 'domcontentloaded', timeout: cfg.timeout });
          await ensureLogin(detail);
        }
        const result = await parsePost(detail, note, { keyword: task.keyword, projectName, capturedAt: beijingDateTime(), searchState:inPlaceState }, { navigate: !useInPlaceClick && !recoverSaved });
        const publishedAt = result.publishedAt || result.post["文章时间地点"];
        unavailableStreak.observe(null);
        if (trackBoundary) boundary.observe(note.noteId, publishedAt);
        consecutiveFailures = 0;
        progress.examined += 1;
        if(result.outsideScope){
          recordScope(checkpoint,task.keyword,note,result,result.scopeAssessment,{fresh:true});
          progress.excludedScope++;
          console.log(`[范围排除] ${note.noteId}：详情明确命中已配置的范围外实体，已留证；不计采集成功`);
        } else if (result.outsideYear) {
          markSkipped(checkpoint, task.keyword, note, `详情发布时间${publishedAt}不在目标${cfg.targetYear}年`, publishedAt);
          progress.skipped += 1;
          console.log(`[日期跳过] ${note.noteId}：${publishedAt}；最近窗口${boundary.recent.length}/${cfg.searchStopWindow}`);
        } else {
          recordScope(checkpoint,task.keyword,note,result,assessKeywordScope(task.keyword,result,{excludedEntities:cfg.scopeExcludedEntitiesByKeyword[task.keyword]||[]}));
          const { asrJob, ...storedResult } = result;
          const audit = { keyword: task.keyword, articleId: result.post["文章id"], title: result.post["文章标题"], status: "已持久化", commentThreads: result.comments.length, missing: POST_FIELDS.filter(f => !["id", "文章图片信息", "文章标注", "分类", "清洗标注", "是否广告", "广告关键词"].includes(f) && result.post[f] == null) };
          markCompleted(checkpoint, task.keyword, note, { ...storedResult, audit },{asrJob,asrMaxAttempts:cfg.asrJobMaxAttempts});
          progress.accepted += 1;
          importBuffer.push({ noteId: note.noteId, post: result.post, comments: result.comments });
          if (asrJob) {
            // Ensure the base article exists before a fast ASR completion can upsert its transcript.
            enqueueImport(task.keyword, importBuffer.splice(0));
            await importQueue;
            asrJobs?.enqueue(asrJob);
          } else if (importBuffer.length >= cfg.importBatchSize) enqueueImport(task.keyword, importBuffer.splice(0, cfg.importBatchSize));
          console.log(`[详情完成] ${result.post["文章标题"] || note.noteId}，评论讨论串${result.comments.length}条（已写入断点库）`);
        }
        failedNotes.delete(note.noteId);
      } catch (error) {
        primaryError = error;
        if (detail.isClosed() || /Target page, context or browser has been closed/.test(String(error.message))) {
          throw new Error("STOP_BROWSER_CLOSED：浏览器已关闭；当前数据保留，停止本节点", { cause: error });
        }
        if(String(error.message||error).startsWith('STOP_WEB_NOTE_UNAVAILABLE')){
          consecutiveFailures=0;
          const inaccessibleStatus=markNoteDeadLetter(checkpoint,task.keyword,note,error,detailAttemptLimit(checkpoint,task.keyword,note.noteId));
          if(inaccessibleStatus!=='dead_letter')failedNotes.add(note.noteId);
          if(trackBoundary)boundary.observe(note.noteId,null);
          progress.deadLetters=(progress.deadLetters||0)+1;
          const count=unavailableStreak.observe(error);
          console.warn(`[帖子死信] ${note.noteId}：网页暂时无法浏览，已持久化；连续${count}/3篇（不计为非今年）`);
          if(unavailableStreak.reached)throw new Error('STOP_WEB_UNAVAILABLE_STREAK：连续3篇帖子暂时无法浏览，保全数据并停止本节点');
          if(!inPlaceState&&!recoverSaved)throw error;
          handledUnavailable=true;
        }else{
        unavailableStreak.observe(null);
        if (String(error.message || error).startsWith("STOP_")) throw error;
        if (trackBoundary) boundary.observe(note.noteId, null);
        consecutiveFailures += 1;
        failedNotes.add(note.noteId);
        progress.failed = failedNotes.size;
        const detailStatus=markFailed(checkpoint, task.keyword, note, error,detailAttemptLimit(checkpoint,task.keyword,note.noteId));
        if(detailStatus==='dead_letter'){failedNotes.delete(note.noteId);progress.deadLetters=(progress.deadLetters||0)+1;}
        console.warn(`[详情失败] ${note.noteId}：${String(error.message || error).split("\n")[0]}（不计为非目标年份）`);
        await detail.screenshot({ path: path.join(cfg.outputDir, `详情失败-${note.noteId}.png`), fullPage: false }).catch(() => {});
        }
      } finally {
        // Do not overwrite security/login/lease/browser failures with a close
        // error, nor perform additional navigation after a stop signal.
        if(recoverSaved){await detail.close().catch(()=>{});}
        else if (inPlaceState && !detail.isClosed() && (handledUnavailable || !String(primaryError?.message || "").startsWith("STOP_"))) {
          await closePostToSearch(detail, inPlaceState,{allowWebUnavailable:handledUnavailable}).catch((error) => {
            if (String(error.message || error).startsWith("STOP_")) throw error;
            throw new Error(`STOP_SEARCH_CONTEXT_LOST：详情关闭后未能恢复搜索页：${String(error.message || error).split("\n")[0]}`);
          });
        }
      }
      completedDetails += 1;
      if (await stopRequested()) throw new Error("STOP_REQUESTED：当前笔记已保存，执行安全停止");
      if (consecutiveFailures >= cfg.maxConsecutiveFailures) throw new Error(`STOP_FAILURE_THRESHOLD：连续失败${consecutiveFailures}篇，已保留断点`);
      console.log(`[采集进度] ${task.keyword}：已核验${progress.examined}篇，今年${progress.accepted}篇，非今年${progress.skipped}篇，失败${failedNotes.size}篇`);
      {
        const pause = itemPause(cfg, 'posts', completedDetails);
        if (pause.kind === 'batch') console.log(`[帖子批次休息] 已处理${completedDetails}篇，休息${Math.ceil(pause.ms / 1000)}秒；可安全停止`);
        await waitForPacing(pause.ms, {shouldStop: stopRequested});
      }
    }
    try {
      let source;
      if (directNoteUrl) {
        source = [{ noteId: extractId(directNoteUrl), url: normalizeXhsUrl(directNoteUrl) }];
        saveCandidates(checkpoint, task.keyword, source);
        progress.reason = "direct_note";
        progress.discovered = 1;
      } else source = collectSearchLinks(searchPage, task.keyword, progress);
      for await (const note of source) {
        progress.freshSearch = true;
        await processNote(note);
        if(volumeMode){
          if(importBuffer.length)enqueueImport(task.keyword,importBuffer.splice(0));
          await importQueue;
          const decision=await volumeRead();
          if(decision.ok&&!process.env.SOCIAL_RECOLLECT_ONCE){progress.reason='volume_threshold';progress.volumeAcceptance=decision;break;}
        }
        if(boundary.reached)progress.oldDateWindowObserved=true; // Diagnostic only, never terminate a live search.
        if (!cfg.collectAllCurrentYear && progress.accepted >= cfg.maxNotesPerKeyword) { progress.reason = "sample_limit"; break; }
      }
      // A visit is not a disposition: recover both omitted old candidates and
      // cards that failed this run, once via their saved URL after the verified
      // search endpoint. Existing per-note attempt limits remain authoritative.
      if (!volumeMode && progress.reason === "platform_exhausted") {
        const remaining = incompleteCandidates(attachScopeAudits(checkpoint,checkpointCandidates(checkpoint,task.keyword),task.keyword),{keyword:task.keyword});
        for (const note of remaining) await processNote(note, false, true);
      }
      const knownGaps=incompleteCandidates(attachScopeAudits(checkpoint,checkpointCandidates(checkpoint,task.keyword),task.keyword),{keyword:task.keyword});
      progress.knownIncomplete=knownGaps.map(n=>n.noteId);
      if(knownGaps.length)console.warn(`[详情缺口保留] ${knownGaps.length}篇未完成，全部保留在80%入库验收分母，不中断已验证搜索终点后的保全入库`);
      if (progress.reason === "search_limit") throw new Error("SEARCH_LIMIT_REACHED：样本滚动上限已达到，不能声明年度采集完成");
      const searchCheck=assessSearchAcceptance([progress],{annual:cfg.collectAllCurrentYear,direct:Boolean(directNoteUrl)});
      if(!volumeMode&&!searchCheck.ok)throw new Error('SEARCH_END_UNVERIFIED：未验证搜索终点');
    } finally {
      if (importBuffer.length) enqueueImport(task.keyword, importBuffer.splice(0));
      await importQueue;
      setMeta(checkpoint, `search:${task.keyword}`, { ...progress, policyVersion: POLICY_VERSION, finishedAt: beijingDateTime() });
    }
    const stats = importedStats(checkpoint, task.keyword);
    console.log(`[入库统计] ${task.keyword}：断点表已登记 帖子${stats["ods_social_media_post"] || 0} 篇、评论${stats["ods_social_media_comment"] || 0} 条`);
    if (task !== entries.at(-1)) await randRange(cfg.keywordDelayMs);
  }
  runStatus = "completed";
} catch (error) {
  runError = error;
  firstFailureAt = error.observedAt || new Date().toISOString();
  const message = String(error?.message || error);
  await publishRestriction(message);
  failureDiagnostic = error.pageDiagnostic || await pageDiagnostics?.capture('collector_failure',error,{firstFailureAt});
  runStatus = collectionFailurePolicy(message).status;
  console.warn(`[采集收尾] ${runStatus}：${message.split("\n")[0]}`);
} finally {
  await importQueue.catch(() => {});
  const asrSummary = await finalizeAsr(asrJobs,{volumeMode,readStats:()=>asrJobStats(checkpoint)}).catch((error) => {
    console.warn(`[ASR队列] 收尾异常，未完成任务仍保存在asr_job：${String(error.message || error).split("\n")[0]}`);
    return null;
  });
  const asrAcceptance=assessAsrAcceptance(asrSummary,{required:!volumeMode&&Boolean(asrJobs),allowExhaustedSkip:true});
  const skippedDetails=Number(checkpoint.prepare("SELECT COUNT(*) AS n FROM note_dead_letter WHERE status='dead_letter'").get().n);
  if(runStatus==='completed' && asrAcceptance.status==='accepted_with_skips'){
    runStatus='completed_with_skips';
    asrSummary.skippedExhausted=asrAcceptance.skipped;
    console.warn(`[明确跳过] 字幕重试耗尽${asrAcceptance.skipped}条；保留死信及原错误，不冒充字幕成功`);
  }
  if (!asrAcceptance.ok && ["completed","completed_with_skips"].includes(runStatus)) {
    runStatus = asrAcceptance.status;
    runError = new Error(`${asrAcceptance.reason}：字幕待处理${asrAcceptance.pending||0}、待审核${asrAcceptance.review||0}；保留证据，禁止冒充完成`);
    console.warn("[ASR任务保留] 文章采集结果已保存；关键词任务不会确认完成，待ASR环境恢复后重新领取并补齐字幕");
  }
  if(runStatus==='completed' && skippedDetails>0)runStatus='completed_with_skips';
  const searchAcceptance=assessSearchAcceptance(searchSummaries,{annual:cfg.collectAllCurrentYear,direct:Boolean(directNoteUrl)});
  const scopeAcceptance={ok:true,unknownCountedAsFailure:true,acceptanceVersion:ACCEPTANCE_VERSION,
    policy:SCOPE_POLICY,tasks:entries.map(task=>({keyword:task.keyword,...scopeSummary(checkpoint,task.keyword)}))};
  if(!volumeMode&&['completed','completed_with_skips'].includes(runStatus)&&!searchAcceptance.ok){
    runStatus='incomplete';runError=new Error('SEARCH_END_UNVERIFIED');
  }
  setMeta(checkpoint, "last_run", { status: runStatus, error: runError ? String(runError.message || runError) : null, finishedAt: beijingDateTime() });
  const retryObservation=retryBefore ? {before:retryBefore,after:retrySnapshot(checkpoint,entries[0].keyword),freshSearch:searchSummaries.some(s=>s.freshSearch),boundedRecoverySearch:false,asrDrainConfirmed:Boolean(!asrJobs||(asrSummary&&!volumeMode))} : null;
  const exported = await exportCheckpoint(checkpoint, cfg.outputDir, { browserMode: session?.mode || null, status: runStatus, policyVersion: POLICY_VERSION, searchSummaries, targetYear: cfg.targetYear, cutoff: cfg.minPublishedDate, projectName: cfg.projectName, category: null, keywords: entries.map((x) => x.keyword), collectComments: cfg.collectComments, outputDir: cfg.outputDir, requiresHumanReview: false, databaseImported: false, finishedAt: beijingDateTime(), error: runError ? String(runError.message || runError) : null });
  await writeJsonAtomic(path.join(cfg.outputDir, "collector_status.json"), { searchAcceptance,scopeAcceptance,retryObservation, cooldownPublication, runId: cfg.runId, policyVersion: POLICY_VERSION, status: runStatus, searchSummaries, error: runError ? String(runError.message || runError) : null, firstFailureAt,pageDiagnostics:failureDiagnostic,posts: exported.posts.length, commentThreads: exported.comments.length, deadLetterNotes:exported.summary.deadLetterNotes,collectionCompleteness:exported.summary.collectionCompleteness,asrJobs: asrSummary, incrementalImports: { batches: incrementalBatches, posts: incrementalPosts, comments: incrementalComments }, checkpointDb: cfg.checkpointDb, finishedAt: beijingDateTime() });
  pageDiagnostics?.dispose();
  await asrJobs?.close().catch(() => {});
  await asrService?.close().catch(() => {});
  if (session?.owned) await session.context.close().catch(() => {});
  else await session?.browser?.close().catch(() => {});
  checkpoint.close();
}
if (runError) process.exitCode = runStatus === "partial_stopped" ? 4 : 3;
else console.log(JSON.stringify({ outputDir: cfg.outputDir, status: runStatus, humanReviewRequired: false, collectComments: cfg.collectComments, next: cfg.skipImport ? "纯采集导出完成" : "run-worker 将自动执行 MySQL 入库" }, null, 2));
