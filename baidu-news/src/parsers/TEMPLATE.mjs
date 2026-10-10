import { extractGeneric, normalizeText } from "./common.mjs";

// 复制本文件并在 registry.mjs 中注册域名。只覆盖站点特有字段，其余交给通用解析器。
export async function parseExample(page) {
  const base = await extractGeneric(page, "example.com");
  const site = await page.evaluate(() => ({
    title: document.querySelector("h1.article-title")?.textContent || "",
    content: document.querySelector(".article-body")?.innerText || "",
    publishedAt: document.querySelector("time")?.getAttribute("datetime") || "",
    author: document.querySelector(".author-name")?.textContent || ""
  }));
  return {
    ...base,
    title: normalizeText(site.title) || base.title,
    content: normalizeText(site.content) || base.content,
    publishedAt: site.publishedAt || base.publishedAt,
    author: normalizeText(site.author) || base.author,
    platform: "示例平台"
  };
}
