import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { AsrService } from "./asr.mjs";
import { atomicWriteFileSync } from "./atomic-file.mjs";

const inputPath = process.argv[2] || "outputs/channels_test/ods_social_media_post_channels.jsonl";
const outputPath = process.argv[3] || inputPath.replace(/\.jsonl$/i, "_browser_enrichment.jsonl");
const collectComments = process.argv.includes("--comments");
const enableAsr = process.argv.includes("--asr");
const records = fs.readFileSync(inputPath, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const bundledPython = path.join(packageRoot, "runtime/python/python.exe");
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
let asrStartPromise = null;

function compactTranscript(value) {
  const lines = String(value || "")
    .replace(/^\uFEFF/, "")
    .replace(/\\N/gi, "\n")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line
      && !/^WEBVTT(?:\s|$)/i.test(line)
      && !/^\d+$/.test(line)
      && !/^(?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{2,3}\s*-->/i.test(line)
      && !/^(?:NOTE|STYLE|REGION)(?:\s|$)/i.test(line))
    .map((line) => {
      if (/^Dialogue:/i.test(line)) {
        const fields = line.split(",");
        return fields.length >= 10 ? fields.slice(9).join(",") : line;
      }
      return line;
    })
    .map((line) => line.replace(/<[^>]+>|\{\\[^}]+\}/g, "").replace(/\s+/g, " ").trim())
    .filter(Boolean);
  const uniqueAdjacent = lines.filter((line, index) => index === 0 || line !== lines[index - 1]);
  return uniqueAdjacent.join("，").replace(/，{2,}/g, "，").replace(/^，|，$/g, "").trim() || null;
}

async function readSubtitleTrack(url, referer) {
  try {
    const response = await fetch(url, {
      headers: {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36",
        Referer: referer,
      },
      signal: AbortSignal.timeout(30000),
    });
    if (!response.ok) return null;
    return compactTranscript(await response.text());
  } catch {
    return null;
  }
}

function extractFeedAssets(payload) {
  const videos = [];
  const tracks = [];
  const walk = (value, pathParts = []) => {
    if (Array.isArray(value)) {
      value.forEach((item, index) => walk(item, [...pathParts, String(index)]));
      return;
    }
    if (!value || typeof value !== "object") return;
    for (const [key, child] of Object.entries(value)) {
      const nextPath = [...pathParts, key];
      const field = nextPath.join(".").toLowerCase();
      if (typeof child === "string" && /^https?:\/\//i.test(child)) {
        const isCover = /cover|thumb|avatar|headimg|qlogo|picurl|image/i.test(field)
          || /[?&](?:picformat|wxampicformat)=/i.test(child);
        const isTrack = /subtitle|caption|transcript|suburl|vtt|srt/i.test(field)
          || /\.(?:vtt|srt|ass)(?:$|[?#])/i.test(child);
        const isVideo = !isCover && (
          /video|media|playurl|downloadurl|urlinfo|spec/i.test(field)
          || /\.(?:mp4|m4v|mov|m3u8)(?:$|[?#])/i.test(child)
        );
        if (isTrack) tracks.push({ url: child, kind: "subtitles", source: `feed_api:${field}` });
        else if (isVideo) videos.push({ url: child, duration: null, tracks: [], source: `feed_api:${field}` });
      }
      walk(child, nextPath);
    }
  };
  walk(payload);
  return { videos, tracks };
}

async function ensureAsr() {
  if (!enableAsr) return null;
  if (asrService) return asrService;
  if (!asrStartPromise) {
    asrStartPromise = (async () => {
      const service = new AsrService({
        model: process.env.WECHAT_ASR_MODEL || "small",
        device: process.env.WECHAT_ASR_DEVICE || "cpu",
        computeType: process.env.WECHAT_ASR_COMPUTE_TYPE || "int8",
        language: "zh",
        pythonExecutable: process.env.WECHAT_ASR_PYTHON || bundledPython,
        modelDir: process.env.WECHAT_ASR_MODEL_DIR || path.join(packageRoot, ".state/asr-models"),
        tempDir: process.env.WECHAT_ASR_TEMP_DIR || path.join(packageRoot, ".state/asr-temp"),
        keepMedia: false,
        startupTimeoutMs: 180000,
        downloadTimeoutMs: 120000,
        transcriptionTimeoutMs: 900000,
      });
      await service.start();
      asrService = service;
      return service;
    })();
  }
  return asrStartPromise;
}

async function enrich(record, index) {
  const page = await context.newPage();
  const networkVideos = [];
  const feedPayloads = [];
  const responseTasks = [];
  page.on("response", (response) => {
    responseTasks.push((async () => {
    try {
      const headers = await response.allHeaders();
      const contentType = String(headers["content-type"] || "").toLowerCase();
      const url = response.url();
      const isVideo = contentType.startsWith("video/")
        || /application\/(?:vnd\.apple\.mpegurl|x-mpegurl)/i.test(contentType)
        || /\.(?:mp4|m4v|mov)(?:$|[?#])/i.test(url);
      if (isVideo && /^https?:/i.test(url)) networkVideos.push({ url, duration: null, tracks: [], source: "network" });
      if (/\/api\/feed\/get_feed_info/i.test(url)) {
        const payload = await response.json().catch(() => null);
        if (payload) feedPayloads.push(payload);
      }
    } catch {}
    })());
  });
  try {
    await page.goto(record["文章链接"], { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForTimeout(1800);
    // `.video-player` is the poster IMG on the public preview page. Clicking
    // it does not start media, so no `<video>` or media response is created.
    // Click the explicit play overlay first and only then inspect resources.
    const previewPlayer = page.locator(".play-button-container, .play-button, .video-interaction-layer, video").first();
    if (await previewPlayer.isVisible().catch(() => false)) {
      await previewPlayer.click({ timeout: 5000 }).catch(() => {});
      await page.waitForTimeout(2500);
    }
    if (collectComments) {
      const commentButton = page.getByText(/^评论\s*\d*$/).last();
      if (await commentButton.isVisible().catch(() => false)) {
        await commentButton.click().catch(() => {});
        await page.waitForTimeout(1200);
      }
    }
    await Promise.allSettled(responseTasks);
    const data = await page.evaluate((shouldCollectComments) => {
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
      const description = document.querySelector('meta[property="og:description"]')?.content
        || first(document, [".finder-desc", ".feed-desc", ".description", ".video-desc", "[class*='desc']"]);
      const title = document.querySelector('meta[property="og:title"]')?.content
        || first(document, [".finder-title", ".video-title", "h1"])
        || description?.split(/\r?\n/)[0]?.slice(0, 120)
        || document.title;
      const authorNode = document.querySelector(".author-name, [class*='nickname'], [class*='profile'] a");
      const imageUrl = (node) => node?.dataset?.src || node?.currentSrc || node?.getAttribute?.("src") || null;
      const images = [...document.querySelectorAll("img")]
        .map((node) => ({ url: imageUrl(node), alt: node.alt || null, width: node.naturalWidth || null, height: node.naturalHeight || null }))
        .filter((item) => item.url && !/avatar|headimg/i.test(item.url));
      const videos = [...document.querySelectorAll("video")].flatMap((video) => {
        const url = video.currentSrc || video.src || video.querySelector("source")?.src || null;
        const duration = Number.isFinite(video.duration) && video.duration > 0 ? Math.round(video.duration * 1000) / 1000 : null;
        const tracks = [...video.querySelectorAll("track")].map((track) => ({ url: track.src || null, kind: track.kind || null, language: track.srclang || null, label: track.label || null })).filter((item) => item.url);
        return url ? [{ url, duration, tracks }] : [];
      });
      const metricText = document.body.innerText;
      const operationCounts = [...document.querySelectorAll(".operate-item")]
        .map((node) => node.textContent?.trim() || null);
      const metric = (labels) => {
        for (const label of labels) {
          const match = metricText.match(new RegExp(`${label}\\s*[:：]?\\s*(\\d+(?:\\.\\d+)?\\s*[万wW]?)`));
          if (match) return match[1];
        }
        return null;
      };
      const commentSelectors = [
        ".comment-list .comment-item", ".comment_list .comment_item", ".comment-item",
        "[class*='commentItem']", "[class*='comment-item']", "[data-comment-id]"
      ];
      const commentNodes = shouldCollectComments ? [...new Set(commentSelectors.flatMap((selector) => [...document.querySelectorAll(selector)]))] : [];
      const comments = commentNodes.map((node, index) => ({
        index: index + 1,
        commentId: node.dataset.commentId || node.getAttribute("data-comment-id") || node.id?.match(/(?:comment|cmt)[-_]?([\w-]+)/i)?.[1] || null,
        userUrl: attrFirst(node, ['a[href*="channels.weixin.qq.com"]', 'a[href*="weixin"]', 'a'], "href"),
        userId: node.dataset.userId || node.getAttribute("data-userid") || null,
        userName: first(node, [".user_name", ".comment_name", ".nickname", "[class*='name']", "a.name", "a"]),
        content: first(node, [".comment_content", ".comment-text", ".content", "[class*='content']"]),
        time: first(node, [".comment_time", ".time", ".date", "[class*='time']"]),
        ip: first(node, [".ip", ".comment_ip", ".location"]),
        likeCount: first(node, [".like_num", ".comment_like", ".js_comment_like_num", ".like-count"]),
        replyCount: first(node, [".reply_num", ".comment_reply", ".js_comment_reply_num", ".reply-count"]),
        rawText: node.innerText?.trim() || null,
      })).filter((item) => item.content);
      const captcha = /验证码|访问过于频繁/.test(document.body.innerText);
      const area = document.querySelector(".comment-list, .comment_list, [class*='commentPanel'], [class*='comment-panel']");
      const isVisible = (node) => {
        if (!node) return false;
        const style = getComputedStyle(node);
        return style.display !== "none" && style.visibility !== "hidden" && node.getClientRects().length > 0;
      };
      const visibleArea = isVisible(area);
      const visibleTexts = [...(area ? area.querySelectorAll("*") : [])].filter(isVisible).map((node) => node.textContent?.trim() || "").filter(Boolean);
      const visibleCountText = visibleTexts.find((value) => /评论\s*\d+|\d+\s*条评论/.test(value));
      const commentCountMatch = visibleArea && visibleCountText ? visibleCountText.match(/(?:评论\s*|)(\d+)\s*(?:条评论|)/) : null;
      const noCommentVisible = visibleArea && visibleTexts.some((value) => /暂无评论|还没有评论/.test(value));
      const listCount = visibleArea ? commentNodes.filter(isVisible).length : 0;
      const publishedAt = first(document, ["[class*='publish']", "[class*='date']", "time"])
        || metricText.match(/20\d{2}年\d{1,2}月\d{1,2}日/)?.[0]
        || null;
      const visibleSubtitleText = [...document.querySelectorAll(
        "track, .caption, .subtitle, .xgplayer-texttrack, [class*='caption'], [class*='subtitle']"
      )].map((node) => node.textContent?.trim() || "").filter(Boolean).join("\n") || null;
      return {
        finalUrl: location.href,
        title,
        author: authorNode?.textContent?.trim() || null,
        authorUrl: authorNode?.href || authorNode?.closest("a")?.href || null,
        publishedAt,
        location: first(document, [".feed-location", ".publish-location", "[data-location]"]),
        content: description,
        images,
        videos,
        comments,
        commentAreaFound: visibleArea,
        likeCount: operationCounts[0] || metric(["点赞", "赞"]),
        shareCount: operationCounts[1] || metric(["转发", "分享"]),
        recommendCount: operationCounts[2] || metric(["推荐", "收藏"]),
        commentCountVisible: operationCounts[3] ? Number(String(operationCounts[3]).replace(/[^\d.]/g, "")) : (!visibleArea ? 0 : (commentCountMatch ? Number(commentCountMatch[1]) : (noCommentVisible ? 0 : (listCount || 0)))),
        visibleSubtitleText,
        captcha,
      };
    }, collectComments);
    if (data.captcha) throw new Error("微信访问验证或环境异常");
    const feedAssets = feedPayloads.map(extractFeedAssets);
    const feedVideos = feedAssets.flatMap((item) => item.videos);
    const feedTracks = feedAssets.flatMap((item) => item.tracks);
    // The API timestamp is authoritative. Searching arbitrary page text can
    // pick up a price-validity/contract date embedded in the description.
    const feedData = feedPayloads.map((payload) => payload?.data).find((item) => item?.feedInfo) || null;
    const feedInfo = feedData?.feedInfo || null;
    const authorInfo = feedData?.authorInfo || null;
    if (feedInfo) {
      data.title = feedInfo.description || data.title;
      data.author = authorInfo?.nickname || data.author;
      data.location = feedInfo.jumpInfo?.wording || data.location;
      if (Number(feedInfo.createtime) > 0) {
        data.publishedAt = new Date(Number(feedInfo.createtime) * 1000).toLocaleString("sv-SE", {
          timeZone: "Asia/Shanghai", hour12: false,
        });
      }
      if (feedInfo.likeCountFmt != null) data.likeCount = feedInfo.likeCountFmt;
      if (feedInfo.favCountFmt != null) data.recommendCount = feedInfo.favCountFmt;
      if (feedInfo.forwardCountFmt != null) data.shareCount = feedInfo.forwardCountFmt;
      if (feedInfo.commentCountFmt != null) data.commentCountVisible = Number(String(feedInfo.commentCountFmt).replace(/[^\d.]/g, "")) || 0;
    }
    data.videos = [...new Map([...(data.videos || []), ...networkVideos, ...feedVideos].map((item) => [item.url, item])).values()];
    data.platformSubtitleTracks = [...new Map(feedTracks.map((item) => [item.url, item])).values()];
    data.mediaResolution = data.videos.length
      ? "direct_media_found"
      : (feedPayloads.length ? "feed_api_without_media" : "feed_api_unavailable");
    if (enableAsr) {
      const subtitleTexts = [];
      for (const track of data.platformSubtitleTracks || []) {
        if (!track.url) continue;
        const text = await readSubtitleTrack(track.url, record["文章链接"]);
        if (text) subtitleTexts.push(text);
      }
      const visibleSubtitle = compactTranscript(data.visibleSubtitleText);
      if (visibleSubtitle) subtitleTexts.push(visibleSubtitle);
      const uniqueSubtitleTexts = [...new Set(subtitleTexts)];
      if (uniqueSubtitleTexts.length) {
        data.videoContent = uniqueSubtitleTexts.join("，");
        data.videoContentSource = data.platformSubtitleTracks?.length
          ? "platform_subtitle_track"
          : "visible_subtitle";
      } else if (data.videos?.length) {
        const service = await ensureAsr();
        const texts = [];
        const seenVideoUrls = new Set();
        for (const video of data.videos) {
          if (!video.url || seenVideoUrls.has(video.url)) continue;
          seenVideoUrls.add(video.url);
          try {
            const asrPrompt = [record["文章标题"], record["文章标签"], record["作者名字"], record["关键词"], record["项目"]].filter(Boolean).join(" ");
            const asr = await service.transcribeUrl(video.url, record["文章id"] || index, asrPrompt, record["文章链接"]);
            if (asr.text) texts.push(compactTranscript(asr.text));
          } catch (error) {
            console.warn(JSON.stringify({ index, asrError: String(error?.message || error) }));
          }
        }
        data.videoContent = texts.filter(Boolean).join("，") || null;
        data.videoContentSource = data.videoContent ? "audio_asr" : null;
      } else {
        data.videoContent = null;
        data.videoContentSource = null;
      }
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
atomicWriteFileSync(outputPath, results.map((item) => JSON.stringify(item)).join("\n") + "\n");
console.log(JSON.stringify({ records: records.length, success: results.filter((item) => item.ok).length, failed: results.filter((item) => !item.ok).length, outputPath }, null, 2));
