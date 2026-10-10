// Load shedding only: these pauses do not bypass platform restrictions.
export function pacingRange(value, fallback) {
  return Array.isArray(value) && value.length === 2 && value.every(v => Number.isFinite(v) && v >= 0) && value[1] >= value[0]
    ? value : fallback;
}

export function itemPause(config, phase, completed, random = Math.random) {
  const author = phase === 'authors';
  const size = author ? config.authorBatchSize : config.batchSize;
  const batchSize = Number.isInteger(size) && size > 0 ? size : 8;
  const batch = completed > 0 && completed % batchSize === 0;
  const range = batch
    ? pacingRange(author ? config.authorBatchCooldownMs : config.batchCooldownMs, [45000, 90000])
    : pacingRange(author ? config.authorDelayMs : config.detailDelayMs, author ? [8000, 15000] : [3000, 6000]);
  return {kind: batch ? 'batch' : 'item', ms: Math.floor(range[0] + random() * (range[1] - range[0] + 1))};
}

export async function waitForPacing(ms, {shouldStop = async () => false, sleep = n => new Promise(resolve => setTimeout(resolve, n)), now = Date.now} = {}) {
  const deadline = now() + Math.max(0, ms);
  while (true) {
    if (await shouldStop()) throw new Error('STOP_REQUESTED：休息期间收到安全停止请求');
    const remaining = deadline - now();
    if (remaining <= 0) return;
    await sleep(Math.min(500, remaining));
  }
}
