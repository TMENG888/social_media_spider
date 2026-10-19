import {verifiedScopeExclusion} from './coverage-scope.mjs';

// An exclusion label is not a disposition without its keyed detail evidence.
// Uncertain exclusions need the same saved-URL recovery as other detail gaps.
export function incompleteCandidates(notes,{keyword}={}){
 return notes.filter(n=>n.status==='skipped_irrelevant'
  ? !verifiedScopeExclusion(n,keyword||n.scopeAudit?.keyword)
  : !['completed','skipped_old','dead_letter'].includes(n.status));
}
