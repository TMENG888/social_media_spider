import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const rootCandidates = process.argv[2]
  ? [path.resolve(process.argv[2])]
  : [path.resolve(scriptDir, '..'), path.resolve(scriptDir, '..', '..')];
const root = rootCandidates.find((candidate) =>
  fs.existsSync(path.join(candidate, 'common', 'task-queue.json'))
);
if (!root) {
  throw new Error(`Package root not found. Checked: ${rootCandidates.join(', ')}`);
}
const queue = JSON.parse(fs.readFileSync(path.join(root, 'common', 'task-queue.json'), 'utf8'));
const all = [];
const expected = [];
for (const task of queue.tasks || []) {
  const file = path.join(root, task.keywordsFile);
  if (!fs.existsSync(file)) continue;
  const data = JSON.parse(fs.readFileSync(file, 'utf8'));
  for (const item of data.keywords || []) expected.push(`${task.id}|${item.keyword}`);
}
for (const name of fs.readdirSync(root).filter((x) => /^worker-\d+$/.test(x))) {
  const file = path.join(root, name, 'task-queue.json');
  if (!fs.existsSync(file)) continue;
  const data = JSON.parse(fs.readFileSync(file, 'utf8'));
  for (const task of data.tasks || []) for (const keyword of task.keywordAllowList || []) all.push({ worker: name, task: task.id, keyword });
}
const keys = all.map((x) => `${x.task}|${x.keyword}`);
const duplicates = keys.filter((x, i) => keys.indexOf(x) !== i);
const assignedSet = new Set(keys);
const result = { checkedAt: new Date().toISOString(), configuredTasks: queue.tasks.length, expectedKeywords: expected.length, assignments: all.length, duplicateAssignments: [...new Set(duplicates)], unassigned: expected.filter((key) => !assignedSet.has(key)) };
result.ok = result.duplicateAssignments.length === 0 && result.unassigned.length === 0;
console.log(JSON.stringify(result, null, 2));
process.exit(result.ok ? 0 : 2);
