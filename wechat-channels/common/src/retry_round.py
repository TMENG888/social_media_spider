"""A bounded Redis-owned sweep, separate from final video completion.

Round stream messages acknowledge an ATTEMPT, never an unfinished video.
Original primary/video-retry streams and checkpoints are preserved.
"""
import json
import uuid
from datetime import datetime
from subtitle_review import has_internal_prompt

def start_round(q, args, tasks):
    key = args.prefix + ':retry-round'
    current = q.redis_command(args.redis_url, args.redis_password, 'HGETALL', key) or []
    info = q.fields_to_dict(current)
    if info.get('state') in {'building', 'active'}:
        raise RuntimeError('An existing retry round is active/building; do not create a duplicate')
    lock = key + ':building-lock'
    round_id = datetime.now().strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
    if not q.redis_command(args.redis_url, args.redis_password, 'SET', lock, round_id, 'NX', 'EX', 3600):
        raise RuntimeError('Another operator is preparing a retry round')
    info = q.fields_to_dict(q.redis_command(args.redis_url, args.redis_password, 'HGETALL', key) or [])
    if info.get('state') in {'building', 'active'}:
        q.redis_command(args.redis_url, args.redis_password, 'DEL', lock)
        raise RuntimeError('A retry round was started concurrently')
    stream = key + ':' + round_id + ':attempts'
    group = args.group + '-retry-round'
    q.redis_command(args.redis_url, args.redis_password, 'HSET', key,
                    'state', 'building', 'id', round_id, 'stream', stream, 'group', group)
    q.ensure_group(args.redis_url, args.redis_password, stream, group)
    count = 0
    for task in tasks:
        state_key = args.prefix + ':video-state:' + q.safe_token(task['task_id'])
        values = q.fields_to_dict(q.redis_command(args.redis_url, args.redis_password, 'HGETALL', state_key) or [])
        for fp, encoded in values.items():
            cp = json.loads(encoded)
            pollution = has_internal_prompt((cp.get('row') or {}).get('video_content'))
            if cp.get('status') not in q.DEFERRED_VIDEO_CHECKPOINT_STATUSES and not pollution:
                continue
            payload = {**task, 'source_task_id':task['task_id'], 'fingerprint':fp,
                       'checkpoint':cp, 'force_asr':pollution or bool(cp.get('force_asr')), 'retry_round':round_id}
            q.redis_command(args.redis_url, args.redis_password, 'XADD', stream, '*',
                            'payload', json.dumps(payload, ensure_ascii=False))
            count += 1
    q.redis_command(args.redis_url, args.redis_password, 'HSET', key,
                    'state', 'active', 'planned', count, 'startedAt', datetime.now().isoformat())
    q.redis_command(args.redis_url, args.redis_password, 'DEL', lock)
    return {'roundId':round_id, 'planned':count, 'stream':stream,
            'originalStreamsChanged':False}

def claim_round(q, args):
    if not getattr(args, 'prefix', None):
        return False, None, None, None
    key = args.prefix + ':retry-round'
    info = q.fields_to_dict(q.redis_command(args.redis_url, args.redis_password, 'HGETALL', key) or [])
    if info.get('state') == 'building':
        return True, None, None, None
    if info.get('state') != 'active':
        return False, None, None, None
    stream, group = info['stream'], info['group']
    message = q.read_new(args.redis_url, args.redis_password, stream, group, args.consumer, 1)
    if not message:
        message = q.auto_claim(args.redis_url, args.redis_password, stream, group,
                               args.consumer, args.reclaim_idle_seconds * 1000)
    if message:
        return True, message, stream, group
    pending = q.pending_count(args.redis_url, args.redis_password, stream, group)
    lag = q.group_lag(args.redis_url, args.redis_password, stream, group)
    if pending == 0 and lag == 0:
        q.redis_command(args.redis_url, args.redis_password, 'EVAL',
            "if redis.call('HGET',KEYS[1],'id')==ARGV[1] and redis.call('HGET',KEYS[1],'state')=='active' then "
            "return redis.call('HSET',KEYS[1],'state','finished','finishedAt',ARGV[2]) end return 0",
            1, key, info['id'], datetime.now().isoformat())
        return False, None, None, None
    return True, None, stream, group

def finish_attempt(q, args, message_id, item, guard, stream, group):
    if guard.get('status') in {'guard_error', 'missing_checkpoint', 'missing_fingerprint', 'invalid_json'}:
        return False
    # Persist the outcome before acknowledging only the round-attempt message.
    key = args.prefix + ':retry-round:' + item['retry_round'] + ':results'
    outcome = {'task_id':item['task_id'], 'fingerprint':item['fingerprint'],
               'completed':guard.get('status') == 'completed' and guard.get('ok', False), 'checkpoint':guard,
               'attemptedAt':datetime.now().isoformat()}
    q.redis_command(args.redis_url, args.redis_password, 'HSET', key,
                    item['task_id'] + '|' + item['fingerprint'], json.dumps(outcome, ensure_ascii=False))
    q.redis_command(args.redis_url, args.redis_password, 'XACK', stream, group, message_id)
    return True
