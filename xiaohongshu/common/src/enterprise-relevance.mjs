// Compatibility export for existing callers. Collection no longer judges
// semantic relevance using brand aliases, housing words, or query substrings.
export const RELEVANCE_POLICY='20261114-lexical-relevance-disabled-v1';
export function entityRelevance(){
 return {policy:RELEVANCE_POLICY,enabled:false,accepted:true,matches:[],housingMatches:[],
  requiredQualifier:null,qualifierMatches:[],reason:'lexical_relevance_disabled'};
}
