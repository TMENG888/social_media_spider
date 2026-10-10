import fs from "node:fs/promises";
import path from "node:path";
import { POST_FIELDS, COMMENT_FIELDS } from "./schema.mjs";

const CLEANING_KEYS = ["原始文字数", "清理后文字数", "表情个数", "其他字符个数", "重复字符个数"];

function validateCleaningStats(value) {
  try {
    const parsed = JSON.parse(value);
    return Object.keys(parsed).length === CLEANING_KEYS.length && CLEANING_KEYS.every((key) => Number.isInteger(parsed[key]) && parsed[key] >= 0);
  } catch { return false; }
}

const dir = path.resolve(process.argv[2] || "runs/latest");
async function load(name, fields) {
  const file = path.join(dir, name);
  const rows = (await fs.readFile(file, "utf8")).split(/\r?\n/).filter(Boolean).map(JSON.parse);
  const errors = [];
  rows.forEach((row, i) => {
    if (JSON.stringify(Object.keys(row)) !== JSON.stringify(fields)) errors.push(`${name} 第${i + 1}行字段或顺序不符`);
    if (name.includes("post") && (!row["文章id"] || !row["文章链接"] || !row["关键词"] || !row["项目"])) errors.push(`${name} 第${i + 1}行缺少业务主键字段`);
    if (name.includes("comment") && (!row["评论id"] || !row["文章id"] || !row["评论内容"])) errors.push(`${name} 第${i + 1}行缺少评论关键字段`);
    if (name.includes("comment") && row["评论id"] === row["评论用户id"]) errors.push(`${name} 第${i + 1}行评论ID疑似误取成用户ID`);
    if (!validateCleaningStats(row["清洗标注"])) errors.push(`${name} 第${i + 1}行清洗标注不是固定五项非负整数JSON`);
    if (name.includes("post") && /#|，/.test(row["文章标签"] || "")) errors.push(`${name} 第${i + 1}行文章标签未按英文逗号规范化`);
    if (name.includes("post") && /(^|\s)#[^\s#]+/.test(row["文章内容"] || "")) errors.push(`${name} 第${i + 1}行文章内容仍含话题标签`);
    if (name.includes("post") && row["内容类型"] === "视频" && row["文章视频内容"] && row["文章视频内容"] === row["文章标题"]) errors.push(`${name} 第${i + 1}行视频内容疑似误取标题或播放器UI`);
  });
  return { file, rows: rows.length, errors };
}
const result = { posts: await load("ods_social_media_post.jsonl", POST_FIELDS), comments: await load("ods_social_media_comment.jsonl", COMMENT_FIELDS) };
result.valid = !result.posts.errors.length && !result.comments.errors.length;
console.log(JSON.stringify(result, null, 2));
if (!result.valid) process.exitCode = 2;
