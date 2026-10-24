// Session-scoped shared ODS lock. Keep the production name: removing it would
// allow older XHS/Channels writers to race while inserting natural keys.
export const IMPORT_LOCK_NAME = 'social_xhs_distributed_import';
export const DEFAULT_IMPORT_LOCK_WAIT_SECONDS = 60;
export async function acquireImportLock(connection, {timeoutSeconds = DEFAULT_IMPORT_LOCK_WAIT_SECONDS,
  verifyLease = async () => {}, onObservation = () => {}} = {}) {
  if (!Number.isFinite(timeoutSeconds) || timeoutSeconds < 0 || timeoutSeconds > 120)
    throw new Error('IMPORT_LOCK_TIMEOUT_INVALID');
  await verifyLease();
  const observe = evidence => { try { onObservation(evidence); } catch { /* Logging cannot own the business lock. */ } };
  const started = Date.now();
  const [rows] = await connection.query('SELECT GET_LOCK(?, ?) AS acquired', [IMPORT_LOCK_NAME, timeoutSeconds]);
  const waitedMs = Date.now() - started;
  if (Number(rows[0]?.acquired) !== 1) {
    let ownerConnectionId = null;
    try {
      const [owners] = await connection.query('SELECT IS_USED_LOCK(?) AS owner', [IMPORT_LOCK_NAME]);
      const value = String(owners[0]?.owner ?? '');
      if (/^\d+$/.test(value)) ownerConnectionId = value;
    } catch { /* Diagnostic permissions must not mask the original timeout. */ }
    const evidence = {event: 'mysql_import_lock_timeout', lockName: IMPORT_LOCK_NAME,
      waitedMs, timeoutSeconds, ownerConnectionId};
    observe(evidence);
    throw Object.assign(new Error('等待跨平台共享入库锁超时；保留本地数据并有限重试'),
      {code: 'MYSQL_IMPORT_LOCK_TIMEOUT', lockEvidence: evidence});
  }
  let released = false;
  const release = async () => {
    if (released) return;
    await connection.query('SELECT RELEASE_LOCK(?) AS released', [IMPORT_LOCK_NAME]);
    released = true;
  };
  try { await verifyLease(); }
  catch (error) { await release().catch(() => {}); throw error; }
  if (waitedMs >= 1000) observe({event: 'mysql_import_lock_acquired_after_wait',
    lockName: IMPORT_LOCK_NAME, waitedMs, timeoutSeconds});
  return release;
}
