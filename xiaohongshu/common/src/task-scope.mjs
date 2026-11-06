import fs from 'node:fs/promises';
import path from 'node:path';

// Scheduling is separate from immutable manifests and acceptance evidence.
export async function scopedTasks(root, tasks) {
  let config;
  try { config = JSON.parse((await fs.readFile(path.join(root, 'task-scope.json'), 'utf8')).replace(/^\uFEFF/, '')); }
  catch (error) { if (error.code === 'ENOENT') return tasks; throw error; }
  if (config.enabled === false) return tasks;
  if (config.version !== 1 || !Array.isArray(config.allowedTopics) || !config.allowedTopics.length ||
      config.allowedTopics.some(topic => !['专题一', '专题二'].includes(topic))) {
    throw new Error('TASK_SCOPE_INVALID');
  }
  const selected = tasks.filter(task => config.allowedTopics.includes(task.topic));
  if (!selected.length) throw new Error('TASK_SCOPE_EMPTY');
  return selected;
}
