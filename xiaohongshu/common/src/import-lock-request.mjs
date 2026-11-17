export const IMPORT_LOCK_REQUEST_TIMEOUT_MS = 30000;

// The SQL lock timeout bounds server-side contention, not a missing response.
// Destroy the old connection before retrying so a late reply cannot be reused.
export async function queryImportLock(connection, {
  lockTimeoutSeconds = 15, requestTimeoutMs = IMPORT_LOCK_REQUEST_TIMEOUT_MS,
} = {}) {
  if (!Number.isFinite(lockTimeoutSeconds) || lockTimeoutSeconds < 0 || lockTimeoutSeconds > 120 ||
      !Number.isInteger(requestTimeoutMs) || requestTimeoutMs < 1 || requestTimeoutMs > IMPORT_LOCK_REQUEST_TIMEOUT_MS) {
    throw new Error('入库锁请求超时参数无效');
  }
  let timer;
  const destroy = () => { try { connection.destroy(); } catch {} };
  try {
    const deadline = new Promise((_, reject) => {
      timer = setTimeout(() => {
        const error = Object.assign(new Error('入库锁请求未在期限内返回，已关闭旧连接，保留数据并重连重试'), {
          code: 'MYSQL_IMPORT_REQUEST_TIMEOUT', requestTimeoutMs,
        });
        destroy();
        reject(error);
      }, requestTimeoutMs);
    });
    return await Promise.race([
      connection.query({
        sql: "SELECT GET_LOCK('social_xhs_distributed_import', ?) AS acquired",
        timeout: requestTimeoutMs,
      }, [lockTimeoutSeconds]),
      deadline,
    ]);
  } catch (error) {
    destroy();
    throw error;
  } finally {
    clearTimeout(timer);
  }
}
