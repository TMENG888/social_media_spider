import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { AsrService } from "./asr.mjs";

const inputPath = process.argv[2] || "outputs/wechat_20260918_test/ods_social_media_post_wechat.jsonl";
const outputPath = process.argv[3] || inputPath.replace(/\.jsonl$/i, "_browser_enrichment.jsonl");
const collectComments = process.argv.includes("--comments");
const enableAsr = process.argv.includes("--asr");
const records = fs.readFileSync(inputPath, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const browserCandidates = [
  process.env.WECHAT_BROWSER_EXECUTABLE,
  path.join(packageRoot, "runtime/browsers/chrome-win64/chrome.exe"),
  path.join(process.env['ProgramFiles(x86)'] || '', 'Microsoft/Edge/Application/msedge.exe'),
  path.join(process.env.ProgramFiles || '', 'Microsoft/Edge/Application/msedge.exe'),
  path.join(process.env.ProgramFiles || '', 'Google/Chrome/Application/chrome.exe'),
].filter((value) => value && fs.existsSync(value));
const browser = await chromium.launch({ headless: true, ...(browserCandidates[0] ? { executablePath: browserCandidates[0] } : {}) });
const context = await browser.newContext({ locale: "zh-CN", userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36" });
const results = new Array(records.length);
let cursor = 0;
let asrService = null;

async function ensureAsr() {
  if (!enableAsr) return null;
  if (asrService) return asrService;
  asrService = new AsrService({
    model: process.env.WECHAT_ASR_MODEL || "small",
    device: process.env.WECHAT_ASR_DEVICE || "cpu",
    computeType: process.env.WECHAT_ASR_COMPUTE_TYPE || "int8",
    language: "zh",
    pythonExecutable: process.env.WECHAT_ASR_PYTHON || path.resolve("work/.venv/Scripts/python.exe"),
    modelDir: process.env.WECHAT_ASR_MODEL_DIR || path.resolve("work/asr-models"),
    tempDir: process.env.WECHAT_ASR_TEMP_DIR || path.resolve("work/asr-temp"),
    keepMedia: false,
    startupTimeoutMs: 180000,
    downloadTimeoutMs: 120000,
    transcriptionTimeoutMs: 900000,
  });
  await asrService.start();
  return asrService;
}

async function enrich(record, index) {
  const page = await context.newPage();
  try {
    await page.goto(record["文章链接"], { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForTimeout(1800);
    const moreComments = page.locator("#js_cmt_area .fold-show-more, #js_cmt_area [role='option']").filter({ hasText: /条留言|查看更多|更多留言/ }).first();
    if (await moreComments.isVisible().catch(() => false)) {
      await moreComments.click().catch(() => {});
      await page.waitForTimeout(1200);
    }
      const data = await page.evaluate((shouldCollectComments) => {
      const text = (selector) => document.querySelector(selector)?.textContent?.trim() || null;
      const contentRoot = document.querySelector("#js_content");
      const playerSelector = [
        ".wx_video_iframe", ".video_iframe", "[id^='js_mp_video_container_']",
        ".js_mpvedio", ".page_video_wrapper", ".wx_video_play_opr",
        "mp-common-mpaudio", ".js_audio_frame"
      ].join(",");
      const imageUrl = (node) => node?.dataset?.src || node?.currentSrc || node?.getAttribute?.("src") || null;
      const isArticleImageUrl = (value) => {
        if (!value || /^(?:data:|blob:|javascript:|about:)/i.test(value)) return false;
        try {
          const parsed = new URL(value, location.href);
          if (!/^https?:$/.test(parsed.protocol)) return false;
          if (parsed.hostname === "mp.weixin.qq.com" && /^\/s(?:\/|$)/.test(parsed.pathname)) return false;
          return /(?:^|\.)(?:[^.]*_)?(?:mmbiz|mmecoa)\.qpic\.cn$/i.test(parsed.hostname)
            || /\.(?:avif|bmp|gif|jpe?g|png|svg|webp)(?:$|[?#])/i.test(parsed.href);
        } catch {
          return false;
        }
      };
      const attrs = (node) => ({
        url: imageUrl(node),
        alt: node?.getAttribute?.("alt") || null,
        width: node?.naturalWidth || node?.width || null,
        height: node?.naturalHeight || node?.height || null,
      });
      // WeChat mounts a same-origin video player inside #js_content. Its
      // placeholder <img> can resolve to the article URL itself, which must
      // never be exported as an article image.
      const images = [...(contentRoot?.querySelectorAll("img") || [])]
        .filter((node) => !node.closest(playerSelector))
        .map(attrs)
        .filter((item) => isArticleImageUrl(item.url));
      const videoNodes = [...document.querySelectorAll("#js_content video")];
      const videos = videoNodes.flatMap((video) => {
        const url = video.currentSrc || video.src || video.querySelector("source")?.src || null;
        const duration = Number.isFinite(video.duration) && video.duration > 0 ? Math.round(video.duration * 1000) / 1000 : null;
        const tracks = [...video.querySelectorAll("track")].map((track) => ({
          url: track.src || null,
          kind: track.kind || null,
          language: track.srclang || null,
          label: track.label || null,
        })).filter((item) => item.url);
        return url ? [{ url, duration, tracks }] : [];
      });
      const authorNode = document.querySelector("#js_name");
      const first = (root, selectors) => {
        for (const selector of selectors) {
          const node = root.querySelector(selector);
          if (node?.textContent?.trim()) return node.textContent.trim();
        }
        return null;
      };
      const attrFirst = (root, selectors, name) => {
        for (const selector of selectors) {
          const node = root.querySelector(selector);
          const value = node?.getAttribute(name);
          if (value) return value;
        }
        return null;
      };
      const commentSelectors = [
        "#js_cmt_area .discuss_item", "#js_cmt_area .comment_item",
        "#js_cmt_area .js_comment", ".discuss_list .discuss_item",
        ".comment-list .comment-item", ".weui-comment-item"
      ];
      const commentNodes = shouldCollectComments ? [...new Set(commentSelectors.flatMap((selector) => [...document.querySelectorAll(selector)]))] : [];
      const comments = commentNodes.map((node, index) => ({
        index: index + 1,
        commentId: node.dataset.commentId || node.getAttribute("data-comment-id") || node.id?.match(/(?:comment|cmt)[-_]?([\w-]+)/i)?.[1] || null,
        userUrl: attrFirst(node, ['a[href*="mp.weixin.qq.com"]', 'a[href*="weixin"]', 'a'], "href"),
        userId: node.dataset.userId || node.getAttribute("data-userid") || null,
        userName: first(node, [".user_name", ".comment_name", ".nickname", ".js_comment_name", "a.name", "a"]),
        content: first(node, [".comment_content", ".comment-text", ".js_comment_content", ".content", ".discuss_message", ".weui-comment-text"]),
        time: first(node, [".comment_time", ".js_comment_time", ".time", ".date"]),
        ip: first(node, [".ip", ".comment_ip", ".location"]),
        likeCount: first(node, [".like_num", ".comment_like", ".js_comment_like_num", ".like-count"]),
        replyCount: first(node, [".reply_num", ".comment_reply", ".js_comment_reply_num", ".reply-count"]),
        rawText: node.innerText?.trim() || null,
      })).filter((item) => item.content);
      const captcha = /验证码|访问过于频繁/.test(document.body.innerText);
      const area = document.querySelector("#js_cmt_area, #js_cmt_container");
      const isVisible = (node) => {
        if (!node) return false;
        const style = getComputedStyle(node);
        return style.display !== "none" && style.visibility !== "hidden" && node.getClientRects().length > 0;
      };
      const visibleArea = isVisible(area);
      const visibleTexts = [...(area ? area.querySelectorAll("*") : [])].filter(isVisible).map((node) => node.textContent?.trim() || "").filter(Boolean);
      const visibleCountText = visibleTexts.find((value) => /\d+\s*条留言/.test(value));
      const commentCountMatch = visibleArea && visibleCountText ? visibleCountText.match(/(\d+)\s*条留言/) : null;
      const noCommentVisible = visibleArea && visibleTexts.some((value) => value.includes("暂无留言"));
      const listCount = visibleArea ? [...(area?.querySelectorAll(".discuss_list > li, .discuss_item, .comment_item") || [])].filter(isVisible).length : 0;
      // Clone before reading innerText so dynamically mounted player controls
      // (for example “，时长 00:15”) do not contaminate the article body.
      const contentClone = contentRoot?.cloneNode(true) || null;
      contentClone?.querySelectorAll(`${playerSelector},script,style,noscript,template`).forEach((node) => node.remove());
      const articleContent = contentClone?.innerText || contentClone?.textContent || null;
      return {
        finalUrl: location.href,
        title: text("#activity-name") || document.querySelector('meta[property="og:title"]')?.content || document.title,
        author: text("#js_name"),
        authorUrl: authorNode?.href || authorNode?.closest("a")?.href || null,
        publishedAt: text("#publish_time"),
        location: text("#js_ip_wording"),
        content: articleContent,
        images,
        videos,
        comments,
        // Hidden Vue template nodes contain a stale “1条留言” label even when
        // the public comment area is not rendered. Only visible DOM counts are
        // valid; a hidden/empty area is treated as zero, never as one.
        commentCountVisible: !visibleArea ? 0 : (commentCountMatch ? Number(commentCountMatch[1]) : (noCommentVisible ? 0 : (listCount || 0))),
        commentAreaFound: visibleArea,
        biz: globalThis.biz || globalThis.__biz || null,
        mid: globalThis.mid || globalThis.appmsgid || null,
        idx: globalThis.idx || globalThis.itemidx || null,
        captcha,
      };
    }, collectComments);
    if (data.captcha) throw new Error("微信访问验证或环境异常");
    if (enableAsr && data.videos?.length) {
      const service = await ensureAsr();
      const texts = [];
      for (const video of data.videos) {
        if (!video.url) continue;
        try {
          const asr = await service.transcribeUrl(video.url, record["文章id"] || index, `${record["文章标题"] || ""} ${record["关键词"] || ""}`, record["文章链接"]);
          if (asr.text) texts.push(asr.text);
        } catch (error) {
          console.warn(JSON.stringify({ index, asrError: String(error?.message || error) }));
        }
      }
      data.videoContent = texts.join("，") || null;
      data.videoContentSource = data.videoContent ? "audio_asr" : null;
    } else {
      data.videoContent = null;
      data.videoContentSource = null;
    }
    return { index, url: record["文章链接"], ok: true, ...data };
  } catch (error) {
    return { index, url: record["文章链接"], ok: false, error: String(error?.message || error) };
  } finally {
    await page.close();
  }
}

async function worker() {
  while (true) {
    const index = cursor++;
    if (index >= records.length) return;
    results[index] = await enrich(records[index], index);
    console.log(JSON.stringify({ index, ok: results[index].ok, url: results[index].url, images: results[index].images?.length || 0, videos: results[index].videos?.length || 0, error: results[index].error || null }, null, 0));
  }
}

await Promise.all([worker(), worker(), worker()]);
await browser.close();
if (asrService) await asrService.close().catch(() => {});
fs.writeFileSync(outputPath, results.map((item) => JSON.stringify(item)).join("\n") + "\n");
console.log(JSON.stringify({ records: records.length, success: results.filter((item) => item.ok).length, failed: results.filter((item) => !item.ok).length, outputPath }, null, 2));
