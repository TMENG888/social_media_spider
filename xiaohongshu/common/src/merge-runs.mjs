import fs from "node:fs/promises";
import path from "node:path";
import { POST_FIELDS, COMMENT_FIELDS } from "./schema.mjs";
const [outputArg, ...inputArgs] = process.argv.slice(2);
if (!outputArg || !inputArgs.length) throw new Error("用法：node src/merge-runs.mjs 输出目录 输入目录...");
const output = path.resolve(outputArg);
async function merge(file, keyOf) {
  const map = new Map();
  for (const dir of inputArgs) {
    const source = await fs.readFile(path.join(path.resolve(dir), file), "utf8");
    for (const line of source.split(/\r?\n/).filter(Boolean)) {
      const row = JSON.parse(line), key = keyOf(row);
      if (!map.has(key)) map.set(key, row);
    }
  }
  return [...map.values()];
}
const posts = await merge("ods_social_media_post.jsonl", (r) => `${r["平台"]}:${r["文章id"]}:${r["项目"]}`);
const comments = await merge("ods_social_media_comment.jsonl", (r) => `${r["平台"]}:${r["文章id"]}:${r["评论id"]}:${r["项目"]}`);
const cell = (v) => `"${String(v ?? "").replaceAll('"', '""')}"`;
const csv = (rows, fields) => `\uFEFF${fields.map(cell).join(",")}\n${rows.map((r) => fields.map((f) => cell(r[f])).join(",")).join("\n")}\n`;
await fs.mkdir(output, { recursive: true });
await fs.writeFile(path.join(output, "ods_social_media_post.jsonl"), posts.map(JSON.stringify).join("\n") + "\n");
await fs.writeFile(path.join(output, "ods_social_media_comment.jsonl"), comments.map(JSON.stringify).join("\n") + (comments.length ? "\n" : ""));
await fs.writeFile(path.join(output, "ods_social_media_post.csv"), csv(posts, POST_FIELDS));
await fs.writeFile(path.join(output, "ods_social_media_comment.csv"), csv(comments, COMMENT_FIELDS));
await fs.writeFile(path.join(output, "run_summary.json"), JSON.stringify({ sourceRuns: inputArgs.map((item) => path.resolve(item)), posts: posts.length, commentThreads: comments.length, requiresHumanReview: true, databaseImported: false }, null, 2));
console.log(JSON.stringify({ output, posts: posts.length, commentThreads: comments.length }, null, 2));
