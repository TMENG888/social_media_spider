// Collection stops and durable-data writes have different lifetimes. This gate
// never permits platform requests; ownership/control failures still fail closed.
export function createPersistenceGate({stopCollecting = async () => false,
  verifyLease = async () => {}, verifyControl = async () => {},
  readStop = async () => '', now = Date.now, drainMs = 300000} = {}) {
  if (!Number.isFinite(drainMs) || drainMs <= 0 || drainMs > 300000) throw new Error('PERSISTENCE_BUDGET_INVALID');
  let deadline = null;
  const fail = code => Object.assign(new Error(code + '：数据保留本地待入库'), {code});
  const beginDrain = () => { deadline ??= now() + drainMs; };
  const remainingMs = () => deadline === null ? drainMs : Math.max(0, deadline - now());
  const checkBudget = () => { if (remainingMs() <= 0) throw fail('PERSISTENCE_DRAIN_TIMEOUT'); };
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
    let timer;
    try {
      await Promise.race([(async()=>{await verifyLease();await verifyControl();})(),new Promise((_,reject)=>{
        timer=setTimeout(()=>reject(fail('PERSISTENCE_DRAIN_TIMEOUT')),Math.max(1,remainingMs()));
      })]);
    } finally { clearTimeout(timer); }
    checkBudget();
  }
  async function shouldAbort() { await assert(); return false; }
  return {assert, shouldAbort, beginDrain, remainingMs,
    status: () => ({mode: deadline === null ? 'collecting' : 'draining', deadline, remainingMs: remainingMs()})};
}

// Bound each SQL operation by the remaining drain budget. A timed-out commit
// remains unconfirmed and pending locally; it is never marked imported.
export function persistenceConnection(connection, gate) {
  if (!gate) return connection;
  return new Proxy(connection, {get(target, name) {
    if (!['query','execute','beginTransaction','commit'].includes(name)) {
      const value = target[name]; return typeof value === 'function' ? value.bind(target) : value;
    }
    return async (...args) => {
      await gate.assert();
      let timer;
      try {
        return await Promise.race([target[name](...args), new Promise((_, reject) => {
          timer = setTimeout(() => {
            target.destroy();
            reject(Object.assign(new Error('PERSISTENCE_SQL_TIMEOUT：SQL结果未确认，保留本地待入库'), {code: 'PERSISTENCE_SQL_TIMEOUT'}));
          }, Math.max(1, Math.min(30000, gate.remainingMs())));
        })]);
      } finally { clearTimeout(timer); }
    };
  }});
}
