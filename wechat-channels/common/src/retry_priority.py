"""Strict retry-first admission. Never marks failed videos complete or deletes data."""
import json
import time
from collections import Counter
from subtitle_review import has_internal_prompt


def iter_checkpoints(q, args):
    cursor = '0'
    seen = set()
    while True:
        cursor, keys = q.redis_command(args.redis_url, args.redis_password, 'SCAN', cursor,
                                      'MATCH', args.prefix + ':video-state:*', 'COUNT', 100)
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            fields = {}
            hcursor = '0'
            while True:
                hcursor, values = q.redis_command(args.redis_url, args.redis_password,
                                                'HSCAN', key, hcursor, 'COUNT', 300)
                fields.update(q.fields_to_dict(values))
                if str(hcursor) == '0':
                    break
            for fingerprint, encoded in fields.items():
                try:
                    cp = json.loads(encoded)
                    if not isinstance(cp, dict):
                        raise ValueError('checkpoint is not an object')
                except (ValueError, TypeError):
                    cp = {'status': 'invalid_json'}
                yield key, fingerprint, cp
        if str(cursor) == '0':
            break


def checkpoint_blocker(cp):
    # Dead letters are operationally terminal, NOT successfully collected.
    status = cp.get('status') or 'unknown'
    if status=='skipped_unresolved':
        return None
    try:
        attempt_count=int(cp.get('retry_count') or 0)
    except (TypeError,ValueError):
        return 'invalid_retry_count'
    if status=='dead_letter' and attempt_count>=3 and cp.get('last_error'):
        # The original bounded failure remains visible as dead_letter, not
        # successful collection. User-authorized terminal failures need not
        # hold the entire next-keyword queue forever.
        return None
    if has_internal_prompt((cp.get('row') or {}).get('video_content')):
        return 'polluted_subtitle'
    if cp.get('subtitle_review_required') or cp.get('asr_status') in ('review', 'partial_review'):
        return 'subtitle_review'
    if status not in ('completed', 'no_content', 'not_applicable','skipped_unresolved'):
        return status
    return None


def unresolved_checkpoints(q, args):
    counts = Counter()
    for _, _, cp in iter_checkpoints(q, args):
        reason = checkpoint_blocker(cp)
        if reason:
            counts[reason] += 1
    return dict(counts)


def claim_retry_first(q, args):
    """Returns (message, hold_new_keywords, details). Redis errors propagate closed."""
    message = q.read_new(args.redis_url, args.redis_password, args.retry_stream,
                         args.retry_group, args.consumer, 1)
    if not message:
        message = q.auto_claim(args.redis_url, args.redis_password, args.retry_stream,
                               args.retry_group, args.consumer, args.reclaim_idle_seconds * 1000)
    if message:
        # A changed checkpoint set invalidates a previous clean admission audit.
        args._retry_priority_audit = None
        return message, True, {'reason': 'retry_claimed'}
    pending = q.pending_count(args.redis_url, args.redis_password, args.retry_stream, args.retry_group)
    lag = q.group_lag(args.redis_url, args.redis_password, args.retry_stream, args.retry_group)
    if pending or lag:
        return None, True, {'reason': 'retry_messages_outstanding', 'pending': pending, 'unread': lag}
    cached = getattr(args, '_retry_priority_audit', None)
    now = time.monotonic()
    # Only cache a blocking result. A clean result must be read again before
    # admitting a new keyword; no waiting/poll loop can declare completion.
    if not cached or cached['expires'] <= now:
        counts = unresolved_checkpoints(q, args)
        cached = {'expires': now + 60, 'counts': counts}
        args._retry_priority_audit = cached if counts else None
    counts = cached['counts']
    if counts:
        return None, True, {'reason': 'checkpoint_backlog_requires_recovery',
                            'unresolved': counts, 'nextAuditSeconds': 60}
    return None, False, {'reason': 'retry_queue_and_checkpoints_clear'}
