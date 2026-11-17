import {verifiedYearBoundary} from './year-boundary-stop.mjs';
export const SCOPE_POLICY='20261114-detail-observed-no-lexical-filter-v1';

// This checks whether actual detail text was observed, not topic relevance.
// Legacy anchors/excludedEntities options intentionally have no filtering effect.
export function assessKeywordScope(keyword,result){
 const post=result?.post||result?.scopeEvidence||{};
 const fields=[post.文章标题??post.title,post.文章内容??post.body,
  post.文章标签??post.tags,post.文章视频内容??post.subtitle];
 const observed=fields.some(v=>String(Array.isArray(v)?v.join(' '):v??'').trim());
 return {policy:SCOPE_POLICY,lexicalMatchEnabled:false,semanticRelevance:'not_evaluated',
  anchors:[],matches:[],status:observed?'accepted':'unobserved',
  reason:observed?'detail_observed_lexical_filter_disabled':'detail_content_not_observed'};
}

// Search exhaustion is the alternative when no verified old-date boundary occurs.
export class SearchExhaustion {
  constructor({stableRounds=15, terminalRounds=3}={}) {
    this.stableRounds=Math.max(2,stableRounds); this.terminalRounds=Math.max(2,terminalRounds);
    this.previous=null; this.streak=0; this.recent=[];
  }
  observe(snapshot) {
    const healthy=snapshot.contextValid&&snapshot.rendered&&!snapshot.loading&&!snapshot.loadFailed;
    const same=this.previous&&snapshot.count===this.previous.count&&snapshot.height===this.previous.height&&snapshot.lastId===this.previous.lastId;
    // A sidebar/other-section "no more" label cannot end the search while its
    // actual scrolling container still has an unscanned lower region.
    const end=snapshot.atBottom;
    this.streak=healthy&&end&&same?this.streak+1:0;
    this.previous={...snapshot}; this.recent.push({...snapshot,streak:this.streak});
    this.recent=this.recent.slice(-Math.max(this.stableRounds,this.terminalRounds)-1);
    const required=snapshot.terminal?this.terminalRounds:this.stableRounds;
    return {ok:Boolean(healthy&&end&&this.streak>=required),policy:'20261014-verified-search-end-v1',
      scope:'platform_current_visible_results',method:snapshot.terminal?'visible_terminal_marker':'stable_scroll_endpoint',
      stableRounds:this.streak,requiredRounds:required,observations:this.recent};
  }
}

export function assessSearchAcceptance(summaries,{annual=true,direct=false}={}) {
  if(!annual||direct)return {ok:true,scope:direct?'explicit_note':'explicit_sample'};
  const ok=Boolean(summaries?.length)&&summaries.every(s=>verifiedYearBoundary(s)||(s.reason==='platform_exhausted'&&s.exhaustion?.ok===true));
  const yearBoundary=ok&&summaries.some(s=>verifiedYearBoundary(s));
  // Candidate disposition is checked separately; endpoint evidence alone
  // must not claim that every known note was successfully handled.
  return {ok,scope:yearBoundary?'latest_search_through_year_boundary':'platform_current_visible_results',
    reason:ok?(yearBoundary?'verified_year_boundary':'verified_search_endpoint'):'SEARCH_END_UNVERIFIED'};
}
