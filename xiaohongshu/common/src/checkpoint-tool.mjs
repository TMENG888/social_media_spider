import fs from "node:fs/promises";
import path from "node:path";
import { openCheckpoint, exportCheckpoint, repairCheckpointDataQuality } from "./checkpoint.mjs";
import {auditExistingScope} from './scope-audit.mjs';

const args = Object.fromEntries(process.argv.slice(2).reduce((out, value, index, all) => {
  if (value.startsWith("--")) out.push([value.slice(2), all[index + 1]?.startsWith("--") ? true : all[index + 1]]);
  return out;
}, []));
const dbPath = path.resolve(String(args.db || ""));
const outputDir = path.resolve(String(args["output-dir"] || ""));
if (!args.db || !args["output-dir"]) throw new Error("需要 --db 和 --output-dir");
await fs.access(dbPath);
const db = openCheckpoint(dbPath);
try {
  const repaired = repairCheckpointDataQuality(db);
  if (repaired.links || repaired.asr) console.log(`[断点质量修复] 文章链接${repaired.links}条，低质量ASR${repaired.asr}条已标记重采`);
  if(args.keyword){
    const scope=auditExistingScope(db,String(args.keyword));
    console.log(`[恢复范围复核] ${args.keyword}：相关${scope.accepted}，范围外${scope.out_of_scope}；旧库记录保留，不重新导出范围外数据`);
  }
  const cutoff = args.cutoff || null;
  const result = await exportCheckpoint(db, outputDir, { recoveryExport: true, projectName: args["project-name"] || null, category: null, cutoff, targetYear: cutoff ? Number(cutoff.slice(0, 4)) : null, collectComments: args["collect-comments"] !== "false" });
  console.log(JSON.stringify(result.summary, null, 2));
} finally {
  db.close();
}
