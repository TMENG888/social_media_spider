// Shared by worker reporting and supervisor stop verification. A benign timer
// stop must never conceal an unsuccessful preservation import.
export const CYCLE_RESUME_POLICY_VERSION = 'xhs-import-resume-20261021-v1';
const unsafe = new Set(['failed', 'partial_error', 'import_failed', 'login_required',
  'risk_controlled', 'web_unavailable', 'lease_lost', 'confirmation_failed', 'context_lost',
  'sort_unconfirmed', 'browser_closed', 'failure_threshold']);
export function cycleResumeDecision(status) {
  const no = reason => ({eligible: false, reason, version: CYCLE_RESUME_POLICY_VERSION});
  if (status.manualStopRequested) return no('manual_stop');
  if (status.fatalError || status.exitCode !== 0) return no('worker_failure');
  if (status.cooldown?.active) return no('platform_hold');
  if (!Array.isArray(status.tasks)) return no('task_status_unavailable');
  if (status.tasks.some(task => task.pendingImport === true || task.status === 'import_pending'
      || task.importExitCode === 75)) return no('import_pending');
  if (status.tasks.some(task => task.importExitCode != null && task.importExitCode !== 0))
    return no('import_failed');
  if (status.tasks.some(task => unsafe.has(task.status) || unsafe.has(task.collectionStatus)
      || task.mustStopNode === true && task.collectionStatus !== 'partial_stopped')) return no('unsafe_task_state');
  return {eligible: true, reason: 'clean_cycle', version: CYCLE_RESUME_POLICY_VERSION};
}
