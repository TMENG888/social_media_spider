"""Read-only classification of the work currently being executed, not liveness."""


def leased_activity(attempt, recollection=None):
    if (recollection or {}).get('policy') == 'reset-once-20261016-v1' and (recollection or {}).get('state') == 'running':
        return 'retry', 'active_recollection_policy'
    try:
        if isinstance(attempt, bool):raise ValueError('boolean attempt')
        number = int(attempt)
        if str(number) != str(attempt).strip() or number < 1:raise ValueError('invalid active attempt')
    except (TypeError, ValueError):
        return 'unknown', 'active_attempt_unavailable'
    return ('new' if number == 1 else 'retry'), 'current_lease_attempt'


def annotate_video_activity(workers, statuses):
    for worker in workers:
        worker['taskActivity'] = 'unknown'
        worker['taskActivityEvidence'] = 'current_task_evidence_unavailable'
        if worker.get('observation') != 'executing':continue
        record = statuses.get(worker.get('taskId'), {})
        if worker.get('taskKind') == 'video_retry':
            worker.update(taskActivity='retry', taskActivityEvidence='active_video_retry_stream')
            continue
        # Never attach another process's current record to this heartbeat.
        if record.get('worker') and record['worker'] != worker.get('consumer'):continue
        if record.get('status') == 'running' and record.get('policy') == 'reset-once-20261016-v1':
            worker.update(taskActivity='retry', taskActivityEvidence='active_recollection_policy')
        elif record.get('status') == 'running' and record.get('previousStatus') in ('pending', 'queued', 'retry_pending', 'recollect_pending'):
            worker.update(taskActivity='new' if record['previousStatus'] in ('pending', 'queued') else 'retry',
                          taskActivityEvidence='explicit_preclaim_status')
        # A primary stream or single message delivery does not by itself prove
        # this keyword was never attempted before (e.g. a reset/recollection).
    return workers


def activity_text(counts):
    text = f"新任务 {counts.get('new', 0)} · 重试 {counts.get('retry', 0)}"
    if counts.get('unknown'):text += f" · 类型未确认 {counts['unknown']}"
    return text
