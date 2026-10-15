// Content exhaustion may be skipped. An unhealthy node is not missing content.
export function maySkipExhausted(result) {
  if (!result || typeof result !== 'object') return false;
  // A content gap must not hide a simultaneous persistence/runtime failure.
  if(result.importError || result.asr?.runtimeUnavailable) return false;
  const message=[result.error,result.asrError].filter(Boolean).join(' | ');
  if (/LEASE|LOGIN|SECURITY|RESTRICTION|COOLDOWN|SORT|CONTEXT|BROWSER|MYSQL|IMPORT|RESOURCE|MEMORY|STOP_REQUESTED|ECONN|ETIMEDOUT|ER_LOCK|LOCK.*TIMEOUT|DATABASE OR DISK IS FULL|节点未确认/i.test(message)) return false;
  return ['partial_error','incomplete','failure_threshold','asr_review_required'].includes(result.status)
    && /DETAILS_INCOMPLETE|DETAIL_DATA_NOT_OBSERVED|KNOWN_CANDIDATES_INCOMPLETE|COMMENTS_INCOMPLETE|SEARCH_STAGNANT_INCOMPLETE|SEARCH_LIMIT_REACHED|STOP_FAILURE_THRESHOLD|ASR_QUALITY_REJECTED|ASR_QUALITY_REVIEW_REQUIRED/.test(message);
}
