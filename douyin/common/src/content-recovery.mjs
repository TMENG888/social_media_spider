// Only explicitly recognized per-item gaps may be isolated. Browser, login,
// restriction, database, lease, unknown programming errors still stop the node.
export function recoverableContentGap(error){
 if(error?.code||error?.importPending)return false;
 return /^(DETAIL_DATA_NOT_OBSERVED|DOUYIN_(?:VIDEO_MEDIA_MISSING|DATE_UNKNOWN|AUTHOR_ID_MISSING)|SEARCH_CARD_NOT_VISIBLE|COMMENTS_(?:INCOMPLETE|CONTROL_OBSCURED|CONTROL_NOT_FOUND|PANEL_NOT_VISIBLE))\b/.test(String(error?.message||error));
}
export function boundedRecoveryDisposition(ids){
 return {boundedRecoverySearch:true,unlocatedCandidates:[...ids].map(String),restartFreshScan:true,deletedConfirmed:false};
}

// Advancing a large/infinite feed is not proof that an old target can still
// be located. Bound recovery separately from the fresh annual search, retaining
// every unresolved ID. Only actual search time is counted, not detail pacing.
export function recoverySearchBudget({rounds,elapsedMs}){
 if(!Number.isSafeInteger(rounds)||rounds<0||!Number.isFinite(elapsedMs)||elapsedMs<0)throw new Error('RECOVERY_SEARCH_BUDGET_INVALID');
 return {rounds,elapsedMs,maxRounds:30,maxMs:120000,
  exhausted:rounds>=30||elapsedMs>=120000};
}
