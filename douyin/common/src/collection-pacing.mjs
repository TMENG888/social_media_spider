// Load shedding only: these pauses do not bypass platform restrictions.
export function pacingRange(value, fallback) {
  return Array.isArray(value) && value.length === 2 && value.every(v => Number.isFinite(v) && v >= 0) && value[1] >= value[0]
    ? value : fallback;
}

export function itemPause(config, phase, completed, random = Math.random) {
  const author = phase === 'authors';
  const size = author ? config.authorBatchSize : config.batchSize;
  const batchSize = Number.isInteger(size) && size > 0 ? size : author ? 6 : 8;
  const batch = completed > 0 && completed % batchSize === 0;
  const range = batch
    ? pacingRange(author ? config.authorBatchCooldownMs : config.batchCooldownMs, [120000, 240000])
    : pacingRange(author ? config.authorDelayMs : config.detailDelayMs, author ? [15000, 30000] : [12000, 25000]);
  return {kind: batch ? 'batch' : 'item', ms: randomDuration(range, random)};
}

function randomDuration(range, random) {
  const value=Number(random()), fraction=Number.isFinite(value)?Math.min(1,Math.max(0,value)):0.5;
  return Math.min(range[1],Math.floor(range[0]+fraction*(range[1]-range[0]+1)));
}

export function keywordPause(config, random = Math.random) {
  return {kind:'keyword',ms:randomDuration(pacingRange(config.keywordDelayMs,[45000,90000]),random)};
}

export function commentPause(config, completed, random = Math.random) {
  const size=Number.isInteger(config.commentBatchSize)&&config.commentBatchSize>0?config.commentBatchSize:20;
  const batch=completed>0&&completed%size===0;
  return {kind:batch?'comment_batch':'comment_item',ms:randomDuration(batch
    ? pacingRange(config.commentBatchCooldownMs,[30000,60000])
    : pacingRange(config.commentDelayMs,[2000,4000]),random)};
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
