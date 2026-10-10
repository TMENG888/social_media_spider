import fs from "node:fs/promises";
import path from "node:path";

const argv = process.argv.slice(2);
const get = (name, fallback) => { const i = argv.indexOf(`--${name}`); return i >= 0 ? argv[i + 1] : fallback; };
const inputRoot = path.resolve(get("input-root", "distributed"));
const outputDir = path.resolve(get("output-dir", path.join(inputRoot, "merged")));
await fs.mkdir(outputDir, { recursive: true });
const postMap = new Map(), commentMap = new Map(), sources = [];
async function walk(dir) {
  for (const entry of await fs.readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory() && !["node_modules", "runtime", ".state"].includes(entry.name)) await walk(full);
    else if (entry.isFile() && ["ods_social_media_post.jsonl", "ods_social_media_comment.jsonl"].includes(entry.name)) {
      const lines = (await fs.readFile(full, "utf8")).split(/\r?\n/).filter(Boolean);
      for (const line of lines) {
        const row = JSON.parse(line);
        if (entry.name.includes("post")) {
          const key = `${row["平台"] || "小红书"}:${row["文章id"]}:${row["项目"] || ""}`;
          const old = postMap.get(key);
          if (!old) postMap.set(key, row);
          else if (row["关键词"] && old["关键词"] && !String(old["关键词"]).split(",").includes(row["关键词"])) old["关键词"] = `${old["关键词"]},${row["关键词"]}`;
        } else {
          const key = `${row["平台"] || "小红书"}:${row["文章id"]}:${row["评论id"]}:${row["项目"] || ""}`;
          if (!commentMap.has(key)) commentMap.set(key, row);
        }
      }
      sources.push(full);
    }
  }
}
await walk(inputRoot);
const posts = [...postMap.values()], comments = [...commentMap.values()];
const fields = (row) => Object.keys(row);
const csv = (rows) => {
  const all = rows.flatMap(fields), headers = [...new Set(all)];
  const cell = (v) => `"${String(v ?? "").replaceAll('"', '""')}"`;
  return `\uFEFF${headers.map(cell).join(",")}\n${rows.map((r) => headers.map((h) => cell(r[h])).join(",")).join("\n")}\n`;
};
await fs.writeFile(path.join(outputDir, "ods_social_media_post.jsonl"), posts.map(JSON.stringify).join("\n") + (posts.length ? "\n" : ""), "utf8");
await fs.writeFile(path.join(outputDir, "ods_social_media_comment.jsonl"), comments.map(JSON.stringify).join("\n") + (comments.length ? "\n" : ""), "utf8");
await fs.writeFile(path.join(outputDir, "ods_social_media_post.csv"), csv(posts), "utf8");
await fs.writeFile(path.join(outputDir, "ods_social_media_comment.csv"), csv(comments), "utf8");
await fs.writeFile(path.join(outputDir, "merge_summary.json"), JSON.stringify({ generatedAt: new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", dateStyle: "short", timeStyle: "medium", hourCycle: "h23" }).format(new Date()), sources, posts: posts.length, comments: comments.length, duplicateSafe: true, requiresHumanReview: false, databaseImported: false }, null, 2), "utf8");
console.log(JSON.stringify({ outputDir, posts: posts.length, comments: comments.length, sources: sources.length }, null, 2));
