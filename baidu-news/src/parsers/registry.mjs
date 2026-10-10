import { cleanArticleText, extractGeneric, normalizeText, stripLeadingTitle } from "./common.mjs";

const COMMON_REMOVE_LINES = [
  /^(?:分享|收藏|关注|举报|纠错|打印|关闭|返回顶部|全文复制|上一篇|下一篇|评论|暂无评论|点击加载更多)$/,
  /^(?:时刻新闻|—分享—)$/,
  /^图片(?:来源[:：]?|由).{0,80}$/,
  /^(?:资料图|效果图|实景图|示意图)(?:[:：].*)?$/,
  /^[（(].{0,40}(?:图|图片|效果图|实景图|示意图)[）)]$/,
  /^.{1,40}(?:效果图|实景图|示意图|现场图)$/,
  /^(?:责任编辑|编辑)[:：].{0,20}$/
];

const COMMON_EXCLUDE_SELECTORS = [
  "script", "style", "nav", "aside", "footer",
  "[class*=recommend]", "[class*=related]", "[class*=comment]",
  "[class*=advert]", "[class*=ad-wrap]", "[class*=share]"
];

function lineKey(value) {
  return normalizeText(value).replace(/\s+/g, "").replace(/[|｜_-](?:百度|百家号).*$/i, "");
}

export function cleanBaijiahaoText(rawContent, metadata = {}) {
  let lines = normalizeText(rawContent).split("\n");
  while (lines.length && /^(?:百度一下|百度首页|登录)$/.test(lines[0].trim())) lines.shift();

  const titleKey = lineKey(metadata.title || "");
  if (titleKey && lineKey(lines[0] || "") === titleKey) lines.shift();

  // Some Baijiahao layouts expose no stable author/date selectors. In that
  // case the header still has a reliable sequence: source, date, location,
  // official-account label. Remove that whole sequence before body cleaning.
  const accountIndex = lines.findIndex((line, index) => index < 12 && /官方(?:账号|帐号)$/.test(line.trim()));
  const hasHeaderDate = accountIndex > 0 && lines.slice(0, accountIndex).some((line) => /^20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?\s+\d{1,2}:\d{2}/.test(line.trim()));
  if (hasHeaderDate) lines.splice(0, accountIndex + 1);

  const authorKey = lineKey(metadata.author || "");
  for (let removed = 0; lines.length && removed < 8;) {
    const line = lines[0].trim();
    const nextLine = lines[1]?.trim() || "";
    const isMetadata = !line ||
      (authorKey && lineKey(line) === authorKey) ||
      /^20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?\s+\d{1,2}:\d{2}/.test(line) ||
      /^(?:北京|上海|天津|重庆|广州|深圳|杭州|成都|南京|武汉|西安)$/.test(line) ||
      (/^[\u4e00-\u9fa5]{2,8}$/.test(line) && /官方(?:账号|帐号)$/.test(nextLine)) ||
      /官方(?:账号|帐号)$/.test(line) || line === "关注";
    if (!isMetadata) break;
    lines.shift();
    removed += 1;
  }

  const aiStart = lines.findIndex((line, index) => index < 15 && line.trim() === "AI导读");
  if (aiStart >= 0) {
    let aiEnd = lines.findIndex((line, index) => index >= aiStart && /^(?:有用|内容由AI智能生成)$/.test(line.trim()));
    if (aiEnd >= 0 && lines[aiEnd].trim() === "内容由AI智能生成" && /^(?:有用|没用)$/.test(lines[aiEnd + 1]?.trim() || "")) aiEnd += 1;
    if (aiEnd < 0) aiEnd = aiStart;
    lines.splice(aiStart, aiEnd - aiStart + 1);
  }

  return cleanArticleText(lines.join("\n"), {
    removeLines: COMMON_REMOVE_LINES,
    endMarkers: [
      /^更多精彩资讯请在应用市场下载/m, /^更多内容请下载.*?APP/m,
      /^免责声明[:：]/m, /^特别声明[:：]/m, /^“?转载请注明出处/m,
      /^本资料声明[:：]?$/m, /^More$/m, /^举报\/反馈$/m,
      /^手机看$/m, /^设为首页$/m
    ]
  });
}

async function parseSelected(page, platform, selectors, cleaning = {}) {
  const result = await extractGeneric(page, platform, { contentSelectors: selectors, strictContentSelectors: true, preferFirstSelector: true, excludeSelectors: [...COMMON_EXCLUDE_SELECTORS, ...(cleaning.excludeSelectors || [])] });
  const cleaned = cleanArticleText(result.content, { removeLines: [...COMMON_REMOVE_LINES, ...(cleaning.removeLines || [])], endMarkers: cleaning.endMarkers || [], minimumBeforeCut: cleaning.minimumBeforeCut || 120 });
  const content = stripLeadingTitle(cleaned, result.title);
  return {
    ...result,
    content,
    rawContentLength: result.content.length,
    contentCleaningVersion: "platform-dom-v3",
    platform
  };
}

async function parseBaijiahao(page) {
  const result = await extractGeneric(page, "baijiahao", { contentSelectors: ["#article", ".article-content", ".bjh-article-content", ".mainContent"] });
  const extra = await page.evaluate(() => ({
    content: [...document.querySelectorAll(".bjh-p")].map((node) => node.innerText).join("\n\n") || document.querySelector("#article, #article-content, .article-content, [class*=articleContent]")?.innerText || "",
    author: document.querySelector("[class*=authorName], [class*=accountName], .author-name")?.textContent || "",
    date: document.querySelector("[class*=publishTime], .date")?.textContent || "",
    location: [...document.querySelectorAll("span, div")].map((node) => (node.children.length ? "" : node.textContent.trim())).find((text) => /^(北京|上海|天津|重庆|广州|深圳|杭州|成都|南京|武汉|西安)$/.test(text)) || null
  }));
  const rawContent = normalizeText(extra.content) || result.content;
  const content = cleanBaijiahaoText(rawContent, { title: result.title, author: normalizeText(extra.author) || result.author, publishedAt: extra.date || result.publishedAt });
  const id = new URL(result.canonicalUrl).searchParams.get("id");
  return { ...result, content, tags: [], rawContentLength: rawContent.length, contentCleaningVersion: "baijiahao-v3", author: normalizeText(extra.author) || result.author, publishedAt: extra.date || result.publishedAt, location: extra.location, articleId: id || result.articleId, platform: "百家号" };
}

async function parseThePaper(page) {
  return parseSelected(page, "澎湃新闻", ["[class*=news_txt]", ".news_txt", ".index_cententWrap__Jv8jK", "article"], {
    excludeSelectors: ["[class*=recommend]", "[class*=related]", "[class*=comment]"],
    endMarkers: [/^特别声明[:：]?/m, /^相关推荐/m, /^责任编辑[:：]/m]
  });
}

async function parseNetease(page) {
  return parseSelected(page, "网易", ["#content", ".post_body", ".post_content"], {
    excludeSelectors: [".post_recommends", ".relative_doc", ".post_statement", "[class*=recommend]"],
    endMarkers: [/^相关推荐/m, /^责任编辑[:：]/m, /^本文来源[:：]/m]
  });
}

const parseJiemian = (page) => parseSelected(page, "界面新闻", [".article-content", ".article-main"], { endMarkers: [/^来源[:：]推广/m, /^本文为转载内容/m, /^资讯\s*\n分享至/m] });
const parseYnet = (page) => parseSelected(page, "财经_YNET.com北青网", ["#articleAll", "#articleBox"], { endMarkers: [/^责任编辑[:：]/m, /^相关阅读/m, /^精华推荐/m] });
const parseChinaDaily = (page) => parseSelected(page, "中国日报网", ["#Content.article", "#Content"], { endMarkers: [/^免责声明[:：]/m, /^【责任编辑/m] });
const parseCet = (page) => parseSelected(page, "中国经济时报", [".article_content"]);
const parseIfeng = (page) => parseSelected(page, "凤凰网", [".content-info", "section.article", "#main_content", ".article-content", ".article_content", ".main_content"], { excludeSelectors: [".recommendNewsRead", ".RangeNews", ".sideNews", ".advDetail-content1", ".advDetail-content2"], endMarkers: [/^\s*[^\n]{0,30}相关资讯[:：]/m, /^\s*相关新闻[:：]?/m, /^\s*标签[:：]/m, /^\s*【责任编辑】/m, /^\s*免责声明[:：]/m, /^\s*点击查看完整内容/m] });
const parsePeople = (page) => parseSelected(page, "人民网", [".rm_txt_con", ".text_con", "#rwb_zw", ".box_con"], { endMarkers: [/^[（(]责编[:：]/m, /^责编[:：]/m, /^责任编辑[:：]/m, /^分享让更多人看到/m] });
const parseRednet = (page) => parseSelected(page, "红网", [".detail_article_content", "article.detail_article"], { endMarkers: [/^来源[:：]红网/m, /^推荐阅读/m, /^时刻新闻/m] });
const parseEastmoney = (page) => parseSelected(page, "东方财富网", [".zwinfos", "#ContentBody", ".articleBody", ".newsContent", ".Body"], { removeLines: [/^在东方财富看资讯行情.*开户交易.*$/i, /^AI妙想为你解读全文.*$/i, /^专业金融数据，下一代智能终端.*$/, /^全新妙想投研助理，立即体验$/], endMarkers: [/^想炒股，先开户/m, /^暗盘资金榜已更新/m, /^文章来源[:：]/m, /^免责声明[:：]/m, /^郑重声明[:：]/m] });
const parseShobserver = (page) => parseSelected(page, "上观新闻", [".article-content", ".article_content", "article", "#article"], { endMarkers: [/^特别声明[:：]/m] });
const parseFangNews = (page) => parseSelected(page, "房天下资讯", ["#news_body", ".article_cont", ".article-content", ".main_con", "#articleBody"], { endMarkers: [/^相关新闻/m, /^相关资讯/m, /^推荐阅读/m, /^更多>>/m] });
const parseCnr = (page) => parseSelected(page, "央广网", [".article-content", ".article-body", ".article-main"], { endMarkers: [/^（注[:：]/m, /^编辑[:：]/m, /^更多精彩资讯请在应用市场下载/m, /^版权声明[:：]/m] });
const parseStockstar = (page) => parseSelected(page, "证券之星", ["#article_content", ".article-content", ".article_cont", ".article-body"], { endMarkers: [/^广告$/m, /^相关股票[:：]/m, /^精彩推荐/m, /^内容精选/m] });
const parseCjrb = (page) => parseSelected(page, "长江日报", ["#articleContent", "#ozoom"], { endMarkers: [/^朗读\s+放大\s+缩小/m, /^长 江 日 报 社/m, /^更多内容[:：]/m] });
const parseChinaCom = (page) => parseSelected(page, "中国网中国四川", [".content_left.article", ".content_left", ".article"], { endMarkers: [/^【责任编辑[:：]?/m] });
const parseSanqin = (page) => parseSelected(page, "三秦网", [".article-content"]);
const parse10jqka = (page) => parseSelected(page, "同花顺", [".news-content.article-content", ".news-content-parsed"]);
const parseDzwww = (page) => parseSelected(page, "大众网", [".news-con", ".TRS_Editor", "#article-content"], { endMarkers: [/^相关新闻/m, /^推荐阅读/m, /^责任编辑[:：]/m] });
const parseZhitong = (page) => parseSelected(page, "智通财经", [".news-body-content"], { endMarkers: [/^智通声明[:：]/m, /^相关阅读/m, /^关于智通财经/m] });
const parseCnfol = (page) => parseSelected(page, "中金在线", ["#post_content", ".Article", ".artMain"], { removeLines: [/^\|$/], endMarkers: [/^相关事件/m, /^相关阅读/m, /^责任编辑[:：]/m] });
const parseXinhua = (page) => parseSelected(page, "新华网", ["#detailContent", "#p-detail", ".main-aticle", ".article-content"], { endMarkers: [/^【纠错】/m, /^【责任编辑/m, /^责任编辑[:：]/m, /^深度观察$/m, /^相关新闻/m, /^相关阅读/m] });
const parseWabei = (page) => parseSelected(page, "挖贝网", [".zixun_news_content"], { endMarkers: [/^相关阅读/m, /^相关推荐/m, /^免责声明[:：]/m] });
const parseCe = (page) => parseSelected(page, "中国经济网", ["#articleText", ".TRS_Editor"], { endMarkers: [/^\s*[（(]责任编辑/m, /^\s*免责声明[:：]/m, /^\s*凡本网注明/m, /^\s*其它问题需要同本网联系/m] });
const parseCaijing = (page) => parseSelected(page, "财经网", ["#the_content", "#article .article-content"], { endMarkers: [/^\s*【广告】/m, /^\s*[（(]免责声明[:：]/m, /^\s*关键字[:：]/m, /^\s*责任编辑[:：]/m, /^\s*相关新闻/m, /^\s*更多精彩/m] });
const parseTmtpost = (page) => parseSelected(page, "钛媒体", [".word_main_detail"], { endMarkers: [/^免责声明[:：]/m, /^相关推荐/m, /^请\s*登录后输入评论内容/m, /^投资日历$/m, /^发现钛媒体$/m] });

async function parseGeneric(page, platform) {
  const result = await extractGeneric(page, "generic", { strictContentSelectors: true, preferFirstSelector: true, excludeSelectors: COMMON_EXCLUDE_SELECTORS });
  const content = cleanArticleText(result.content, { removeLines: COMMON_REMOVE_LINES, endMarkers: [/^精彩推荐/m, /^相关推荐/m, /^热门推荐/m, /^评论区/m] });
  return { ...result, content: stripLeadingTitle(content, result.title), tags: [], rawContentLength: result.content.length, contentCleaningVersion: "generic-strict-v3", platform };
}

const RULES = [
  { test: /baijiahao\.baidu\.com$/, name: "百家号", parse: parseBaijiahao },
  { test: /(^|\.)jiemian\.com$/, name: "界面新闻", parse: parseJiemian },
  { test: /(^|\.)ynet\.com$/, name: "财经_YNET.com北青网", parse: parseYnet },
  { test: /(^|\.)chinadaily\.com\.cn$/, name: "中国日报网", parse: parseChinaDaily },
  { test: /(^|\.)cet\.com\.cn$/, name: "中国经济时报", parse: parseCet },
  { test: /(^|\.)ifeng\.com$/, name: "凤凰网", parse: parseIfeng },
  { test: /(^|\.)people\.com\.cn$/, name: "人民网", parse: parsePeople },
  { test: /(^|\.)rednet\.cn$/, name: "红网", parse: parseRednet },
  { test: /(^|\.)eastmoney\.com$/, name: "东方财富网", parse: parseEastmoney },
  { test: /(^|\.)shobserver\.cn$/, name: "上观新闻", parse: parseShobserver },
  { test: /(^|\.)news\.fang\.com$/, name: "房天下资讯", parse: parseFangNews },
  { test: /(^|\.)thepaper\.cn$/, name: "澎湃新闻", parse: parseThePaper },
  { test: /(^|\.)163\.com$/, name: "网易", parse: parseNetease },
  { test: /(^|\.)stockstar\.com$/, name: "证券之星", parse: parseStockstar },
  { test: /(^|\.)cnfol\.com$/, name: "中金在线", parse: parseCnfol },
  { test: /(^|\.)prnasia\.com$/, name: "美通社" },
  { test: /(^|\.)cir\.cn$/, name: "产业调研网" },
  { test: /(^|\.)10jqka\.com\.cn$/, name: "同花顺", parse: parse10jqka },
  { test: /(^|\.)dzwww\.com$/, name: "大众网", parse: parseDzwww },
  { test: /(^|\.)zhitongcaijing\.com$/, name: "智通财经", parse: parseZhitong },
  { test: /(^|\.)xinhuanet\.com$/, name: "新华网", parse: parseXinhua },
  { test: /(^|\.)wabei\.cn$/, name: "挖贝网", parse: parseWabei },
  { test: /(^|\.)ce\.cn$/, name: "中国经济网", parse: parseCe },
  { test: /(^|\.)caijing\.com\.cn$/, name: "财经网", parse: parseCaijing },
  { test: /(^|\.)tmtpost\.com$/, name: "钛媒体", parse: parseTmtpost },
  { test: /(^|\.)guandian\.cn$/, name: "观点网" },
  { test: /(^|\.)cnr\.cn$/, name: "央广网", parse: parseCnr },
  { test: /(^|\.)cjn\.cn$/, name: "长江日报", parse: parseCjrb },
  { test: /(^|\.)china\.com\.cn$/, name: "中国网中国四川", parse: parseChinaCom },
  { test: /(^|\.)sanqin\.com$/, name: "三秦网", parse: parseSanqin },
  { test: /(^|\.)news\.cn$/, name: "新华网", parse: parseXinhua }
];

export function selectParser(url, source) {
  const hostname = new URL(url).hostname.replace(/^www\./, "");
  const rule = RULES.find((item) => item.test.test(hostname));
  return {
    name: rule?.name || source || hostname,
    parse: rule?.parse || ((page) => parseGeneric(page, rule?.name || source || hostname))
  };
}
