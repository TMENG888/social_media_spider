// Only rolled-back/import-lock contention is eligible for automatic continuation.
// Access restrictions, lost leases, authentication and schema failures stay fatal.
export function transientImportError(error) {
  return ['ER_LOCK_WAIT_TIMEOUT','ER_LOCK_DEADLOCK','MYSQL_IMPORT_LOCK_WAIT_TIMEOUT'].includes(error?.code) ||
    [1205,1213].includes(Number(error?.errno));
}

export function collectionFailureAction(error, {test = false} = {}) {
  if (error?.code === 'LEASE_LOST' || /STOP_(?:LEASE_LOST|PLATFORM_RESTRICTION|LOGIN_REQUIRED)/.test(String(error?.message || ''))) return 'fatal';
  if (/STOP_REQUESTED/.test(String(error?.message || ''))) return 'stop';
  if (!test && error?.recoverableImport === true && !error?.recoveryExhausted) return 'rest_retry';
  return 'fatal';
}
