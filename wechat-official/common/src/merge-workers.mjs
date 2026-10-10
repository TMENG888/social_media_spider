import fs from 'node:fs';
import path from 'node:path';
import { dedupePostsGlobal, relinkAndDedupeComments } from './wechat-dedupe.mjs';

const inputRoot = path.resolve(process.argv[2] || '..');
const outputDir = path.resolve(process.argv[3] || path.join(inputRoot, 'merged'));
fs.mkdirSync(outputDir, { recursive: true });
const workers = fs.readdirSync(inputRoot, { withFileTypes: true }).filter((x) => x.isDirectory() && /^worker-\d+$/.test(x.name));
const readJsonl = (file) => fs.existsSync(file) ? fs.readFileSync(file, 'utf8').split(/\r?\n/).filter(Boolean).map(JSON.parse) : [];
const posts = [], comments = [], workerSummary = [];
for (const worker of workers) {
  const workerDir = path.join(inputRoot, worker.name);
  const statusFile = path.join(workerDir, '.state', 'worker_status.json');
  workerSummary.push({ workerId: worker.name, status: fs.existsSync(statusFile) ? JSON.parse(fs.readFileSync(statusFile, 'utf8')) : null });
  for (const topic of ['topic1', 'topic2']) {
    const runDir = path.join(workerDir, 'runs', topic);
    posts.push(...readJsonl(path.join(runDir, 'ods_social_media_post_wechat_final.jsonl')));
    comments.push(...readJsonl(path.join(runDir, 'ods_social_media_post_wechat_final_comments.jsonl')));
  }
}
const writeJsonl = (file, rows) => fs.writeFileSync(file, rows.map((r) => JSON.stringify(r)).join('\n') + (rows.length ? '\n' : ''), 'utf8');
const writeCsv = (file, rows) => {
  const headers = rows.length ? Object.keys(rows[0]) : [];
  const q = (v) => `"${String(v ?? '').replaceAll('"', '""')}"`;
  fs.writeFileSync(file, '\uFEFF' + headers.map(q).join(',') + '\n' + rows.map((r) => headers.map((h) => q(r[h])).join(',')).join('\n') + (rows.length ? '\n' : ''), 'utf8');
};
const postDedupe = dedupePostsGlobal(posts);
const commentDedupe = relinkAndDedupeComments(comments, postDedupe);
const mergedPosts = postDedupe.records, mergedComments = commentDedupe.records;
writeJsonl(path.join(outputDir, 'ods_social_media_post.jsonl'), mergedPosts);
writeJsonl(path.join(outputDir, 'ods_social_media_comment.jsonl'), mergedComments);
writeJsonl(path.join(outputDir, 'wechat_post_dedupe_audit.jsonl'), postDedupe.audit);
writeJsonl(path.join(outputDir, 'wechat_comment_dedupe_audit.jsonl'), commentDedupe.audit);
writeCsv(path.join(outputDir, 'ods_social_media_post.csv'), mergedPosts);
writeCsv(path.join(outputDir, 'ods_social_media_comment.csv'), mergedComments);
const summary = { generatedAt: new Date().toISOString(), dedupeRule: 'article id / canonical URL / bidirectional 5-character shingle similarity >= 0.80', workers: workerSummary, sourcePostRows: posts.length, mergedPostRows: mergedPosts.length, sourceCommentRows: comments.length, mergedCommentRows: mergedComments.length, duplicatePostsRemoved: posts.length - mergedPosts.length, duplicateCommentsRemoved: comments.length - mergedComments.length };
fs.writeFileSync(path.join(outputDir, 'distributed_summary.json'), JSON.stringify(summary, null, 2), 'utf8');
console.log(JSON.stringify(summary, null, 2));
