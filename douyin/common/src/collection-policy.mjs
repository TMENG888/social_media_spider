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
// details occupy a slot. This is diagnostic evidence only: even latest-sorted
// searches can interleave old posts before current-year results.
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
// until a verified search endpoint; stagnation is an incomplete scan.
export function scrollBudget(collectAll, configured) {
  return collectAll ? Infinity : Math.max(1, Number(configured) || 20);
}

// Exhaustion is separate from the eight-older-post diagnostic. A short result
// set (including zero current-year posts) can be complete, but stagnation alone
// can never establish that fact.
export function searchExhaustionEvidence({keyword,after,sortConfirmed,pages=[],failures=[],uiEnd,candidates=[]}={}){
 const reject=reason=>({confirmed:false,reason});
 if(!sortConfirmed)return reject('latest_sort_not_confirmed');
 if(!uiEnd?.visible)return reject('no_visible_search_end');
 const relevant=pages.filter(p=>p.keyword===keyword&&p.at>=after);
 if(!relevant.length)return reject('no_current_search_response');
 const last=relevant.at(-1);
 if(!last.latest)return reject('sort_changed');
 if(last.hasMore!==false)return reject('pagination_not_exhausted');
 if(failures.some(p=>p.keyword===keyword&&p.at>=after))return reject('search_response_failure');
 const latest=relevant.filter(p=>p.latest),returned=[...new Set(latest.flatMap(p=>p.noteIds||[]))];
 if(String(latest[0].offset??'0')!=='0')return reject('missing_initial_page');
 const indexed=new Map(candidates.map(c=>[c.noteId,c]));
 const gaps=[];
 for(const id of new Set([...returned,...indexed.keys()])){
  const c=indexed.get(id);
  if(!c||!['completed','skipped_old'].includes(c.status)||!validDate(c.publishedAt)||(c.status==='completed'&&c.result?.audit?.commentsComplete===false))gaps.push(id);
 }
 // Pagination completion is not proof of detail completeness. The independent
 // DB coverage gate counts every unresolved candidate in its denominator.
 return {confirmed:true,reason:'search_exhausted',gaps,keyword,sortConfirmed:true,hasMore:false,returnedCount:returned.length,checkpointCount:candidates.length,lastResponseAt:last.at,offset:last.offset??null,uiText:uiEnd.text};
}

export function verifiedAnnualSearchEnd(summary){
 const evidence=summary?.searchExhaustion;
 return summary?.sortConfirmed===true&&summary.stopReason==='search_exhausted'
  &&evidence?.confirmed===true&&evidence.reason==='search_exhausted'
  &&evidence.keyword===summary.keyword&&evidence.sortConfirmed===true
  &&evidence.hasMore===false&&Number.isInteger(evidence.stableChecks)
  &&evidence.stableChecks>=2;
}
