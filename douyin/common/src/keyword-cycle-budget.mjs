// Legacy exit budgets stop at a keyword boundary; in-place posts pauses use beforeNext.
// No stop files or task acceptance changes belong in this policy.
export class KeywordCycleBudget {
  constructor({minutes = 0, now = Date.now, beforeNext = async () => {}} = {}) {
    this.beforeNext = beforeNext;
    if (!Number.isFinite(minutes) || minutes < 0) throw new Error('INVALID_CYCLE_MINUTES');
    this.now = now;
    this.deadline = minutes > 0 ? now() + Math.round(minutes * 60000) : null;
  }

  get expired() { return this.deadline !== null && this.now() >= this.deadline; }

  async *tasks(source) {
    const iterator = source[Symbol.asyncIterator]?.() || source[Symbol.iterator]();
    try {
      // Check before requesting the next item: a Redis iterator claims a lease
      // inside next(), so a check only in the worker's loop body is too late.
      while (!this.expired) {
        await this.beforeNext();
        if (this.expired) return;
        const item = await iterator.next();
        if (item.done) return;
        yield item.value;
      }
    } finally {
      await iterator.return?.();
    }
  }
}
