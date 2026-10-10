import fs from "node:fs/promises";
import path from "node:path";
import { projectForTopic } from "./collection-policy.mjs";

const dir = path.resolve(process.argv[2] || "runs/test-all-20260917");
const queuePath = process.argv[3];
if (!queuePath) throw new Error("需要指定输出目录和对应task-queue.json；禁止按有限关键词白名单猜测项目");
const queue = JSON.parse(await fs.readFile(path.resolve(queuePath), "utf8"));
const projects = new Map();
for (const task of queue.tasks || []) {
  const name = projectForTopic(task.topic, task.projectName);
  const values = projects.get(task.keyword) || new Set();
  values.add(name);
  projects.set(task.keyword, values);
}
const label = (row) => {
  const candidates = projects.get(String(row["关键词"] || ""));
  if (!candidates?.size) throw new Error(`队列中没有关键词：${row["关键词"]}`);
  if (candidates.has(row["项目"])) return row["项目"];
  if (candidates.size !== 1) throw new Error(`关键词跨专题，无法自动推断项目：${row["关键词"]}`);
  return [...candidates][0];
};
const prepared = [];
for (const file of ["ods_social_media_post.jsonl", "ods_social_media_comment.jsonl"]) {
  const target = path.join(dir, file);
  const text = await fs.readFile(target, "utf8");
  const rows = text.split(/\r?\n/).filter(Boolean).map((line) => {
    const row = JSON.parse(line);
    row["项目"] = label(row);
    return JSON.stringify(row);
  });
  prepared.push({ target, content: rows.join("\n") + (rows.length ? "\n" : "") });
}
for (const {target, content} of prepared) await fs.writeFile(target, content, "utf8");
console.log(JSON.stringify({ dir, status: "project_labels_applied" }));
