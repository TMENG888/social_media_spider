import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const browserPath = process.env.PLAYWRIGHT_BROWSERS_PATH;
const browserExecutable = process.env.BROWSER_EXECUTABLE;
if (!browserPath) throw new Error("PLAYWRIGHT_BROWSERS_PATH 未设置");
if (!browserExecutable) throw new Error("BROWSER_EXECUTABLE 未设置");
await fs.access(browserPath);
await fs.access(browserExecutable);
const browser = await chromium.launch({ headless: true, executablePath: browserExecutable });
try {
  const page = await browser.newPage();
  await page.setContent("<!doctype html><meta charset=utf-8><title>portable-ok</title><h1>OK</h1>");
  const title = await page.title();
  if (title !== "portable-ok") throw new Error("Chromium 页面验证失败");
  console.log(JSON.stringify({ ok: true, node: process.version, chromium: browser.version(), browserPath: path.resolve(browserPath) }, null, 2));
} finally {
  await browser.close();
}
