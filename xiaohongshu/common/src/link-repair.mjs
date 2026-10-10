import path from "node:path";
import mysql from "mysql2/promise";
import { mysqlConnectionOptions } from "./import-mysql.mjs";
import { writeJsonAtomic } from "./checkpoint.mjs";

const PROJECTS = ["全国地产设计产品力监测", "北京臻澐项目口碑"];

async function repairTable(connection, table) {
  const placeholders = PROJECTS.map(() => "?").join(",");
  const [result] = await connection.execute(`UPDATE \`${table}\`
    SET \`文章链接\`=CONCAT('https://www.xiaohongshu.com/explore/',\`文章id\`)
    WHERE \`平台\`='小红书' AND \`项目\` IN (${placeholders})
      AND \`文章id\` REGEXP '^[0-9A-Fa-f]{24}$'
      AND (\`文章链接\` IS NULL OR (
        \`文章链接\` NOT LIKE CONCAT('%/explore/',\`文章id\`,'%')
        AND \`文章链接\` NOT LIKE CONCAT('%/discovery/item/',\`文章id\`,'%')
      ))`, PROJECTS);
  return Number(result.affectedRows || 0);
}

export async function repairInvalidArticleLinks({ stateRoot }) {
  const connection = await mysql.createConnection(mysqlConnectionOptions());
  let postsUpdated = 0, commentsUpdated = 0;
  try {
    await connection.beginTransaction();
    postsUpdated = await repairTable(connection, "ods_social_media_post");
    commentsUpdated = await repairTable(connection, "ods_social_media_comment");
    await connection.commit();
  } catch (error) {
    await connection.rollback().catch(() => {});
    throw error;
  } finally {
    await connection.end();
  }
  const status = { status: "success", scannedAt: new Date().toISOString(), postsUpdated, commentsUpdated };
  await writeJsonAtomic(path.join(stateRoot, "article_link_repair.json"), status);
  return status;
}
