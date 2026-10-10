function hostname(url) {
  try { return new URL(url).hostname.toLowerCase(); } catch { return ""; }
}

export function evaluateArticleEligibility({ url, title = "", content = "" }) {
  const host = hostname(url);
  const pathname = (() => { try { return new URL(url).pathname.toLowerCase(); } catch { return ""; } })();
  const text = `${title}\n${String(content).slice(0, 20000)}`;

  // 房天下同时包含新闻和楼盘交易页。只排除明确的楼盘/房源产品页，保留 news.fang.com 等资讯页。
  const fangHost = /(^|\.)(fang\.com|soufun\.com)$/.test(host);
  const fangPropertyUrl = fangHost && (
    /^newhouse\./.test(host) || /^esf\./.test(host) || /^zu\./.test(host) ||
    /\/(?:loupan|house|newhouse|esf|zu|xf)(?:\/|$)/.test(pathname)
  );
  if (fangPropertyUrl) {
    return { eligible: false, code: "NON_NEWS_PROPERTY_PAGE", reason: "非资讯页面：房天下楼盘/房源详情页" };
  }

  const propertySignals = ["楼盘首页", "楼盘详情", "主力户型", "项目地址", "预售证", "一房一价", "房价走势", "贷款计算器", "售楼电话", "楼栋信息"];
  const matchedSignals = propertySignals.filter((signal) => text.includes(signal));
  if (matchedSignals.length >= 4) {
    return { eligible: false, code: "NON_NEWS_PROPERTY_CONTENT", reason: `非资讯页面：检测到楼盘产品页特征（${matchedSignals.slice(0, 5).join("、")}）` };
  }

  return { eligible: true, code: "NEWS_ARTICLE_CANDIDATE", reason: null };
}
