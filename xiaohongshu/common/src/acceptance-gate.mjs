// Never confuse collection/import success with subtitle quality acceptance.
export function assessAsrAcceptance(summary, {required = true,allowExhaustedSkip = false} = {}) {
  if (!required) return {ok:true, status:'disabled', pending:0, review:0};
  if (!summary || typeof summary !== 'object') return {ok:false,status:'asr_deferred',reason:'ASR_SUMMARY_MISSING'};
  const counters=['completed','dead_letter','pendingTotal','partial_review'];
  if(counters.some(k => summary[k] != null && (!Number.isSafeInteger(summary[k]) || summary[k]<0)))
    return {ok:false,status:'asr_deferred',reason:'ASR_SUMMARY_INVALID'};
  const review=(summary.dead_letter||0)+(summary.partial_review||0);
  const pending=summary.pendingTotal||0;
  if(pending || summary.runtimeUnavailable) return {ok:false,status:'asr_deferred',reason:'ASR_PENDING',pending,review};
  // Skip only exhausted content jobs, never unfinished work or a missing audit.
  if(allowExhaustedSkip && summary.dead_letter>0 && !summary.partial_review && !pending && !summary.runtimeUnavailable)
    return {ok:true,status:'accepted_with_skips',pending:0,review:0,skipped:summary.dead_letter};
  if(review) return {ok:false,status:'asr_review_required',reason:'ASR_REVIEW_REQUIRED',pending,review};
  return {ok:true,status:'accepted',pending,review};
}
