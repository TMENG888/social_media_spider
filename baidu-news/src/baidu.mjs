export function buildBaiduNewsUrl(query, pageIndex = 0) {
  const url = new URL("https://www.baidu.com/s");
  url.search = new URLSearchParams({ tn: "news", rtt: "4", bsst: "1", cl: "2", wd: query, medium: "0", pn: String(pageIndex * 10) }).toString();
  return url.href;
}

export const SECURITY_CHALLENGE_PATTERN = /百度安全验证|安全验证|请输入验证码|访问过于频繁|系统检测到您的请求存在异常|完成验证后即可继续使用|wappass\.baidu\.com/i;

export async function discoverPage(page, query, pageIndex, options = {}) {
  const url = buildBaiduNewsUrl(query, pageIndex);
  const response = options.reuseCurrentPage ? null : await page.goto(url, { waitUntil: "domcontentloaded" });
  if ([403, 429].includes(response?.status())) throw new Error(`STOP_RATE_LIMIT:${response.status()}`);
  const title = await page.title().catch(() => "");
  const bodyText = await page.locator("body").innerText({ timeout: 5000 }).catch(() => "");
  if (SECURITY_CHALLENGE_PATTERN.test(`${title}\n${page.url()}\n${bodyText}`)) throw new Error("STOP_CAPTCHA:BAIDU_SECURITY_CHALLENGE");
  await page.waitForSelector("#content_left", { timeout: 20000 });
  return page.evaluate(({ query, pageIndex }) => {
    const cards = [...document.querySelectorAll("#content_left > div")].filter((node) => node.querySelector("h3 a"));
    return cards.map((card, index) => {
      const titleLink = card.querySelector("h3 a");
      const text = card.innerText || "";
      const lines = text.split(/\n+/).map((line) => line.trim()).filter(Boolean);
      const otherLinks = [...card.querySelectorAll("a")].filter((a) => a !== titleLink).map((a) => (a.innerText || "").trim()).filter(Boolean);
      const source = otherLinks.at(-1) || lines.at(-1) || null;
      const date = text.match(/发布于[:：]?\s*([^\n]+)/)?.[1]?.trim() || text.match(/\b(\d{1,2}月\d{1,2}日)\b/)?.[1] || null;
      return {
        query,
        pageIndex,
        rank: pageIndex * 10 + index + 1,
        title: (titleLink?.innerText || "").replace(/^标题[:：]/, "").trim(),
        url: titleLink?.href || "",
        source: String(source || "").replace(/^新闻来源[:：]?/, "").trim() || null,
        cardDate: date,
        snippet: text.replace(/\n+/g, " ").slice(0, 800)
      };
    }).filter((item) => item.url && item.title);
  }, { query, pageIndex });
}
