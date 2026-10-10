import fs from "node:fs/promises";
import path from "node:path";
import mysql from "mysql2/promise";
import { POST_FIELDS, COMMENT_FIELDS } from "./schema.mjs";
import { mysqlConnectionOptions } from "./import-mysql.mjs";
import { writeJsonAtomic } from "./checkpoint.mjs";

const PROJECTS = new Set(["全国地产设计产品力监测", "北京臻澐项目口碑"]);
const csvCell = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
const csv = (rows, fields) => `\uFEFF${fields.map(csvCell).join(",")}\n${rows.map((row) => fields.map((field) => csvCell(row[field])).join(",")).join("\n")}\n`;

async function filesBelow(root) {
  const found = [];
  async function visit(dir) {
    let entries = [];
    try { entries = await fs.readdir(dir, { withFileTypes: true }); } catch (error) { if (error.code === "ENOENT") return; throw error; }
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) await visit(full);
      else if (entry.name === "ods_social_media_post.jsonl" || entry.name === "ods_social_media_comment.jsonl") found.push(full);
    }
  }
  await visit(root);
  return found;
}

async function atomicWrite(file, content) {
  const temporary = `${file}.category-null-${process.pid}.tmp`;
  try {
    await fs.writeFile(temporary, content, "utf8");
    await fs.rename(temporary, file);
  } catch (error) {
    await fs.unlink(temporary).catch(() => {});
    throw error;
  }
}

export async function normalizeLocalCategoryFiles(runsRoot) {
  const postIds = new Map(), commentIds = new Map();
  const errors = [];
  let files = 0, normalizedRows = 0;
  for (const file of await filesBelow(runsRoot)) {
    const isPost = path.basename(file) === "ods_social_media_post.jsonl";
    const fields = isPost ? POST_FIELDS : COMMENT_FIELDS;
    const source = await fs.readFile(file, "utf8");
    const rows = source.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
    let changed = false;
    for (const row of rows) {
      if (row["平台"] !== "小红书" || !PROJECTS.has(row["项目"])) continue;
      const map = isPost ? postIds : commentIds;
      const id = isPost ? row["文章id"] : row["评论id"];
      if (id) {
        if (!map.has(row["项目"])) map.set(row["项目"], new Set());
        map.get(row["项目"]).add(String(id));
      }
      if (row["分类"] !== null) {
        row["分类"] = null;
        normalizedRows += 1;
        changed = true;
      }
    }
    if (changed) {
      try {
        await atomicWrite(file, rows.map(JSON.stringify).join("\n") + (rows.length ? "\n" : ""));
        files += 1;
      } catch (error) {
        errors.push({ file, error: String(error.message || error) });
      }
    }
    try {
      // 每次都让CSV与JSONL重新对齐；即使上一次因Excel占用失败，下次启动也会重试。
      await atomicWrite(file.replace(/\.jsonl$/i, ".csv"), csv(rows, fields));
    } catch (error) {
      // Excel占用CSV时不阻断精确ID的数据库修复。
      errors.push({ file: file.replace(/\.jsonl$/i, ".csv"), error: String(error.message || error) });
    }
  }
  return { files, normalizedRows, postIds, commentIds, errors };
}

async function updateExactIds(connection, table, idField, groupedIds) {
  let affectedRows = 0;
  for (const [project, idSet] of groupedIds) {
    const ids = [...idSet];
    for (let offset = 0; offset < ids.length; offset += 200) {
      const chunk = ids.slice(offset, offset + 200);
      const placeholders = chunk.map(() => "?").join(",");
      const [result] = await connection.execute(
        `UPDATE \`${table}\` SET \`分类\`=NULL WHERE \`平台\`='小红书' AND \`项目\`=? AND \`${idField}\` IN (${placeholders}) AND \`分类\` IS NOT NULL`,
        [project, ...chunk]
      );
      affectedRows += Number(result.affectedRows || 0);
    }
  }
  return affectedRows;
}

export async function repairCategoryNull({ runsRoot, stateRoot }) {
  const local = await normalizeLocalCategoryFiles(runsRoot);
  const connection = await mysql.createConnection(mysqlConnectionOptions());
  let postsUpdated = 0, commentsUpdated = 0;
  try {
    await connection.beginTransaction();
    postsUpdated = await updateExactIds(connection, "ods_social_media_post", "文章id", local.postIds);
    commentsUpdated = await updateExactIds(connection, "ods_social_media_comment", "评论id", local.commentIds);
    await connection.commit();
  } catch (error) {
    await connection.rollback().catch(() => {});
    throw error;
  } finally {
    await connection.end();
  }
  const status = { status: "success", scannedAt: new Date().toISOString(), localFilesNormalized: local.files, localRowsNormalized: local.normalizedRows, localFileErrors: local.errors, postsUpdated, commentsUpdated };
  await writeJsonAtomic(path.join(stateRoot, "category_null_repair.json"), status);
  return status;
}
