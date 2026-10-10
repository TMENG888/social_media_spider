export function collectionFailurePolicy(error) {
  const message = String(error?.message || error || '');
  if (message.startsWith('STOP_REQUESTED')) return {status:'partial_stopped',stopNode:true,release:true};
  if (message.startsWith('STOP_SECURITY_CHALLENGE')) return {status:'risk_controlled',stopNode:true,release:true};
  if (message.startsWith('STOP_WEB_NOTE_UNAVAILABLE')) return {status:'web_unavailable',stopNode:true,release:true};
  if (message.startsWith('STOP_WEB_UNAVAILABLE_STREAK')) return {status:'web_unavailable',stopNode:true,release:true};
  if (message.startsWith('STOP_LOGIN_REQUIRED')) return {status:'login_required',stopNode:true,release:true};
  if (message.startsWith('STOP_LEASE_LOST')) return {status:'lease_lost',stopNode:true,release:false};
  if (message.startsWith('STOP_SORT_NOT_CONFIRMED')) return {status:'sort_unconfirmed',stopNode:true,release:false};
  if (/^STOP_(?:SEARCH|DETAIL)_CONTEXT_LOST/.test(message)) return {status:'context_lost',stopNode:true,release:false};
  if (message.startsWith('STOP_BROWSER_CLOSED') || /Target page, context or browser has been closed/.test(message)) {
    return {status:'browser_closed',stopNode:true,release:false};
  }
  if (/^STOP_FAILURE_THRESHOLD/.test(message)) return {status:'failure_threshold',stopNode:true,release:false};
  return {status:'partial_error',stopNode:false,release:false};
}
