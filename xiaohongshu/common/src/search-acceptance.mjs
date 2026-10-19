import {entityRelevance} from './enterprise-relevance.mjs';
export const SCOPE_POLICY = '20261015-positive-scope-evidence-v2';
const normalized = value => String(value || '').normalize('NFKC').toLowerCase().replace(/[\s\p{P}\p{S}]/gu, '');

// An explicit lexical scope, not an LLM guess. The entity is the first query
// term; intent terms such as 看房 need not occur verbatim in a relevant note.
export function assessKeywordScope(keyword, result, {anchors,excludedEntities=[]} = {}) {
  const terms = anchors || [String(keyword || '').trim().split(/\s+/)[0]];
  if (!Array.isArray(terms) || !terms.length || terms.some(t => normalized(t).length < 2))
    throw new Error('SCOPE_ANCHOR_INVALID: configure a nonempty entity anchor');
  const post = result?.post || result?.scopeEvidence || {};
  const relevance=!anchors?entityRelevance(keyword,post):null;
  const fields = {title:post['文章标题'] ?? post.title, body:post['文章内容'] ?? post.body,
    tags:post['文章标签'] ?? post.tags, subtitle:post['文章视频内容'] ?? post.subtitle};
  const values = Object.entries(fields).map(([field,value]) => [field,normalized(Array.isArray(value)?value.join(' '):value)]);
  const matches = terms.flatMap(anchor => values.filter(([,value])=>value.includes(normalized(anchor))).map(([field])=>({anchor,field})));
  const detailObserved=values.some(([field,v])=>['title','body'].includes(field)&&v);
  const accepted=relevance?relevance.accepted:matches.length>0;
  const exclusion=!accepted&&!matches.length&&Array.isArray(excludedEntities)?excludedEntities.flatMap(entity=>
    normalized(entity).length>=2&&!terms.some(term=>normalized(term).includes(normalized(entity))||normalized(entity).includes(normalized(term)))
    ?values.filter(([field,value])=>['title','body'].includes(field)&&value.includes(normalized(entity)))
      .map(([field])=>({kind:'configured_entity',entity,field})):[])[0]:null;
  return {policy:SCOPE_POLICY, anchors:terms,
    status:accepted?'accepted':exclusion?'out_of_scope':detailObserved?'uncertain':'unobserved',
    matches,...(relevance?{relevance}:{}),...(exclusion?{exclusion}:{}),
    reason:accepted?(relevance?.enterprise?relevance.reason:'entity_anchor_observed'):exclusion?'configured_other_entity_observed':detailObserved?'entity_relevance_uncertain':'detail_content_not_observed'};
}

// Old-date windows are diagnostic only. Even Latest search can be interleaved.
// Completion requires repeated healthy scans at the actual scroll endpoint.
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
  const ok=Boolean(summaries?.length)&&summaries.every(s=>s.reason==='platform_exhausted'&&s.exhaustion?.ok===true);
  // Candidate disposition is checked separately; endpoint evidence alone
  // must not claim that every known note was successfully handled.
  return {ok,scope:'platform_current_visible_results',reason:ok?'verified_search_endpoint':'SEARCH_END_UNVERIFIED'};
}
