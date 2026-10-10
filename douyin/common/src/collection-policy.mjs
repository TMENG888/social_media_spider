export const POLICY_VERSION = "20260928-streaming-year-window-v1";
export const PROJECTS = Object.freeze({
  专题一: "全国地产设计产品力监测",
  专题二: "北京臻澐项目口碑"
});

export function projectForTopic(topic, fallback) {
  const project = PROJECTS[topic] || fallback;
  if (!project) throw new Error(`任务未配置项目：${topic || "未知专题"}`);
  return project;
}

export function validDate(value) {
  const day = String(value || "").slice(0, 10);
  if (!/^20\d{2}-\d{2}-\d{2}$/.test(day)) return null;
  const parsed = new Date(`${day}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === day ? day : null;
}

export function inTargetYear(value, year, cutoff = `${year}-01-01`) {
  const day = validDate(value);
  return Boolean(day && day.slice(0, 4) === String(year) && day >= cutoff);
}

// Only distinct, consecutive detail-page observations count. Unknown or failed
// details occupy a slot, so eight older observations separated by an unknown
// cannot accidentally satisfy the stopping rule.
export class YearBoundary {
  constructor(year, size = 8) {
    this.year = Number(year);
    this.size = Math.max(1, Number(size));
    this.recent = [];
    this.seen = new Set();
  }
  observe(noteId, publishedAt) {
    if (this.seen.has(noteId)) return this.reached;
    this.seen.add(noteId);
    this.recent.push({ noteId, date: validDate(publishedAt) });
    if (this.recent.length > this.size) this.recent.shift();
    return this.reached;
  }
  get reached() {
    return this.recent.length === this.size && this.recent.every(x => x.date && Number(x.date.slice(0, 4)) < this.year);
  }
}

// A cap is meaningful only for explicit sampling. Annual collection continues
// until the verified date boundary or repeated no-growth is observed.
export function scrollBudget(collectAll, configured) {
  return collectAll ? Infinity : Math.max(1, Number(configured) || 20);
}
