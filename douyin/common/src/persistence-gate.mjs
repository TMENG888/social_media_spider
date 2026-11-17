// Collection stops and durable-data writes have different lifetimes. This gate
// never permits platform requests; ownership/control failures still fail closed.
export const PERSISTENCE_BUDGET_VERSION = 'douyin-lock-wait-drain-isolation-20261113-v2';
export function createPersistenceGate({stopCollecting = async () => false,
  verifyLease = async () => {}, verifyControl = async () => {},
  readStop = async () => '', now = Date.now, drainMs = 300000} = {}) {
  if (!Number.isFinite(drainMs) || drainMs <= 0 || drainMs > 300000) throw new Error('PERSISTENCE_BUDGET_INVALID');
  let deadline = null;
  let excludedMs = 0, exclusionDepth = 0, excludedSince = null, chargeDepth = 0;
  let lockWaitMs = 0, lockWaitDepth = 0, lockWaitSince = null;
  const currentExclusionMs = () => excludedSince !== null ? Math.max(0, now() - excludedSince) : 0;
  const currentLockWaitMs = () => lockWaitSince !== null ? Math.max(0, now() - lockWaitSince) : 0;
  const budgetNow = () => now() - excludedMs - currentExclusionMs();
  const fail = code => Object.assign(new Error(code + '：数据保留本地待入库'), {code});
  const beginDrain = () => { deadline ??= budgetNow() + drainMs; };
  const remainingMs = () => deadline === null ? drainMs : Math.max(0, deadline - budgetNow());
  const checkBudget = () => { if (remainingMs() <= 0) throw fail('PERSISTENCE_DRAIN_TIMEOUT'); };
  // ASR/lock queues pause the drain clock, but concurrent real database work
  // still spends its remaining budget. SQL keeps its independent 30-second cap.
  async function withoutDrainBudget(operation, {reason = 'asr_wait'} = {}) {
    if (exclusionDepth++ === 0 && chargeDepth === 0) excludedSince = now();
    if (reason === 'lock_wait' && lockWaitDepth++ === 0) lockWaitSince = now();
    try { return await operation(); }
    finally {
      if (reason === 'lock_wait' && --lockWaitDepth === 0) {
        lockWaitMs += currentLockWaitMs(); lockWaitSince = null;
      }
      if (--exclusionDepth === 0 && excludedSince !== null) {
        excludedMs += currentExclusionMs(); excludedSince = null;
      }
    }
  }
  async function withDrainBudget(operation) {
    if (chargeDepth++ === 0 && excludedSince !== null) {
      excludedMs += currentExclusionMs(); excludedSince = null;
    }
    try { return await operation(); }
    finally {
      if (--chargeDepth === 0 && exclusionDepth > 0) excludedSince = now();
    }
  }
  async function withinBudget(operation, {maxMs = Infinity, onTimeout = () => {},
    timeoutError = () => fail('PERSISTENCE_DRAIN_TIMEOUT')} = {}) {
    checkBudget();
    const started = now();
    let timer;
    const timeout = new Promise((_, reject) => {
      const poll = () => {
        const left = Math.min(remainingMs(), maxMs - Math.max(0, now() - started));
        if (left <= 0) { onTimeout(); reject(timeoutError()); return; }
        // Re-evaluate when a former deadline fires: an ASR wait may have
        // excluded time while this operation was already in flight.
        timer = setTimeout(poll, Math.max(1, left));
      };
      poll();
    });
    try { return await Promise.race([operation(), timeout]); }
    finally { clearTimeout(timer); }
  }
  async function assert() {
    if (await stopCollecting()) beginDrain();
    checkBudget();
    const raw = String(await readStop() || '').trim();
    if (raw) {
      let value;
      try { value = JSON.parse(raw); } catch {}
      const reason = value ? JSON.stringify(value) : raw;
      if (/REMOTE_CONTROL_UNAVAILABLE|CONTROL_(?:LOST|UNKNOWN|UNAVAILABLE)|LEASE_LOST|FORCE_STOP|force_stop|abort_persistence/i.test(reason) || value?.abortPersistence === true) throw fail('PERSISTENCE_PROTECTION_HOLD');
      // Existing ISO/manual safe-stop flags end collection, not local draining.
      beginDrain();
    }
    await withinBudget(async()=>{await verifyLease();await verifyControl();});
    checkBudget();
  }
  async function shouldAbort() { await assert(); return false; }
  return {assert, shouldAbort, beginDrain, remainingMs, withoutDrainBudget, withDrainBudget, withinBudget,
    status: () => ({mode: deadline === null ? 'collecting' : 'draining',
      deadline: deadline === null ? null : deadline + excludedMs + currentExclusionMs(),
      remainingMs: remainingMs(), excludedMs: excludedMs + currentExclusionMs(),
      budgetPaused: excludedSince !== null, lockWaitMs: lockWaitMs + currentLockWaitMs(),
      lockWaitActive: lockWaitDepth > 0, activeSql: chargeDepth, budgetVersion: PERSISTENCE_BUDGET_VERSION})};
}

// Bound each SQL operation by the remaining drain budget. A timed-out commit
// remains unconfirmed and pending locally; it is never marked imported.
export function persistenceConnection(connection, gate, {chargeDrainBudget = true} = {}) {
  if (!gate) return connection;
  return new Proxy(connection, {get(target, name) {
    if (!['query','execute','beginTransaction','commit'].includes(name)) {
      const value = target[name]; return typeof value === 'function' ? value.bind(target) : value;
    }
    return async (...args) => {
      await gate.assert();
      const execute = () => gate.withinBudget(() => target[name](...args), {maxMs: 30000,
        onTimeout: () => target.destroy(),
        timeoutError: () => Object.assign(new Error('PERSISTENCE_SQL_TIMEOUT：SQL结果未确认，保留本地待入库'), {code: 'PERSISTENCE_SQL_TIMEOUT'})});
      return chargeDrainBudget ? gate.withDrainBudget(execute) : execute();
    };
  }});
}
