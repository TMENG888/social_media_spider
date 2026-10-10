const TRANSIENT_CODES = new Set([
  'MYSQL_IMPORT_LOCK_TIMEOUT', 'ER_LOCK_DEADLOCK', 'ER_LOCK_WAIT_TIMEOUT',
  'ECONNRESET', 'ECONNREFUSED', 'ETIMEDOUT', 'EPIPE',
  'PROTOCOL_CONNECTION_LOST', 'PROTOCOL_SEQUENCE_TIMEOUT',
]);
export const IMPORT_PENDING_EXIT_CODE = 75;
export const isRetryableImportError = error => TRANSIENT_CODES.has(error?.code);
export function importTaskState(collectorStatus, importExitCode, { stopNode = false } = {}) {
  if (importExitCode === 0) return collectorStatus;
  if (stopNode || ['login_required', 'risk_controlled', 'web_unavailable', 'lease_lost', 'confirmation_failed', 'context_lost'].includes(collectorStatus)) return collectorStatus;
  return importExitCode === IMPORT_PENDING_EXIT_CODE ? 'import_pending' : 'import_failed';
}

export function createImportBatches(posts, comments, batchRows = 10) {
  if (!Number.isInteger(batchRows) || batchRows < 1 || batchRows > 100) throw new Error('入库分批行数必须在1至100之间');
  const batches = [];
  // Posts precede comments, including when a transaction is retried.
  let batch = { posts: [], comments: [] };
  for (const [kind, rows] of [['posts', posts], ['comments', comments]]) {
    for (const row of rows) {
      batch[kind].push(row);
      if (batch.posts.length + batch.comments.length === batchRows) {
        batches.push(batch); batch = { posts: [], comments: [] };
      }
    }
  }
  if (batch.posts.length || batch.comments.length) batches.push(batch);
  return batches;
}

export async function retryImportBatch(operation, {
  maxAttempts = 4, retryDelayMs = 2000, verifyLease = async () => {},
  sleep = ms => new Promise(resolve => setTimeout(resolve, ms)),
  random = Math.random, onRetry = () => {},
} = {}) {
  if (!Number.isInteger(maxAttempts) || maxAttempts < 1 || maxAttempts > 10 ||
      !Number.isFinite(retryDelayMs) || retryDelayMs < 0 || retryDelayMs > 60000) throw new Error('入库重试参数无效');
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    await verifyLease();
    try { return await operation(attempt); }
    catch (error) {
      if (!isRetryableImportError(error)) throw error;
      if (attempt === maxAttempts) throw Object.assign(new Error('入库暂时繁忙，有限重试已用尽；数据保留本地，等待下轮补入', { cause: error }), {
        code: 'IMPORT_RETRY_PENDING', lastErrorCode: error.code, attempts: attempt,
      });
      const delayMs = Math.min(30000, retryDelayMs * 2 ** (attempt - 1)) + Math.floor(random() * 1000);
      onRetry({ attempt, maxAttempts, delayMs, code: error.code });
      // Wait without holding a DB lock; stop immediately if ownership is lost.
      for (let elapsed = 0; elapsed < delayMs; elapsed += 1000) {
        await verifyLease(); await sleep(Math.min(1000, delayMs - elapsed));
      }
    }
  }
}
