"""Observe configured production queues only; never call a dispatcher or Lua script."""
import argparse
import collections
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse, quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect import ROOT, RedisConnection, atomic_json, pairs
from monitor_paths import platform_path
from task_activity import leased_activity

PLATFORMS = {'小红书': 'xhs', '抖音': 'xhs:douyin'}
QUEUE_STATES = ('pending', 'leased', 'completed', 'completed_with_skips', 'skipped_unresolved', 'failed')
READ_COMMANDS = {'HVALS', 'HGET', 'TIME', 'ZRANGE', 'ZCOUNT', 'XRANGE'}


def platform_root(platform):
    config = load_json(ROOT / 'config.json') if (ROOT / 'config.json').exists() else {}
    return platform_path(platform,config=config,package=ROOT.parent)


class ReadOnlyRedis:
    def __init__(self, connection):
        self.connection = connection

    def command(self, *parts):
        if parts[0] not in READ_COMMANDS:
            raise ValueError('Non-observation command rejected')
        try:
            return self.connection.command(*parts)
        except Exception as error:
            if 'NOPERM' in str(error):
                raise PermissionError('Observation command denied: ' + parts[0]) from None
            raise


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def decode(raw):
    try:
        result = json.loads(raw)
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError):
        return {}


def queue_observation(c, namespace, campaign, tasks=()):
    all_states = c.command('HVALS', namespace + ':statuses') or []
    if not all_states:
        return {'campaign': campaign, 'source': 'not_published', 'counts': None}
    lease_values = c.command('ZRANGE', namespace + ':leases', 0, -1, 'WITHSCORES') or []
    leases = {k: float(v) for k, v in pairs(lease_values).items()}
    seconds, micros = c.command('TIME')
    now_ms = int(seconds) * 1000 + int(micros) / 1000
    counts = collections.Counter()
    for state in all_states:
        if state == 'excluded':
            counts['excluded'] += 1
        else:
            counts['total'] += 1
            counts[state if state in QUEUE_STATES else 'unknown'] += 1
    topics = {}
    workers = collections.defaultdict(lambda: {'validLeases': 0, 'expiredLeases': 0, 'keywords': [], 'taskActivity': collections.Counter(), 'currentTasks': []})
    activity = collections.Counter()
    result_states = collections.Counter()
    projects = set()
    missing_payloads = 0
    matched = collections.Counter()
    pending_values = c.command('ZRANGE', namespace + ':pending', 0, -1) or []
    task_ids = {task['redisTaskId'] for task in tasks} | set(leases) | set(pending_values)
    for task_id in sorted(task_ids):
        state = c.command('HGET', namespace + ':statuses', task_id)
        if state is None:
            continue
        if state == 'excluded':
            continue
        matched[state if state in QUEUE_STATES else 'unknown'] += 1
        payload = decode(c.command('HGET', namespace + ':payloads', task_id))
        if not payload:
            missing_payloads += 1
        topic = payload.get('topic') or '专题未确认'
        row = topics.setdefault(topic, collections.Counter())
        row['total'] += 1
        row[state if state in QUEUE_STATES else 'unknown'] += 1
        if state == 'pending':
            raw_attempt = c.command('HGET', namespace + ':attempts', task_id)
            try:
                attempt = int(raw_attempt)
                if attempt < 0: raise ValueError('negative attempt')
                kind = 'retryPending' if attempt > 0 else 'pendingNew'
            except (TypeError, ValueError):
                kind = 'pendingUnclassified'
            counts[kind] += 1
            row[kind] += 1
        if payload.get('projectName'):
            projects.add(payload['projectName'])
        if state in ('completed', 'completed_with_skips', 'skipped_unresolved'):
            result=decode(c.command('HGET', namespace + ':results', task_id))
            result_states[result.get('status') or '未提供结果状态'] += 1
            if result.get('disposition')=='no_change':counts['noChangeCompleted']+=1
            if result.get('acceptedBy')=='retry_exhausted_completion':counts['retryExhaustedCompleted']+=1
            if result.get('acceptedBy')=='reset_once_recollection':counts['resetOnceCompleted']+=1
            if result.get('pendingImport') is True:counts['completedPendingImport']+=1
        if state == 'leased':
            expiry = leases.get(task_id)
            if expiry is None:
                counts['missingLeaseEvidence'] += 1
            else:
                kind = 'validLeases' if expiry > now_ms else 'expiredLeases'
                counts[kind] += 1
                # Remove process UUID; never expose lease tokens or raw task results.
                raw_owner = c.command('HGET', namespace + ':owners', task_id)
                owner = re.sub(r'-[0-9a-f]{8}-[0-9a-f-]{27}$', '', raw_owner or '归属未确认')
                workers[owner][kind] += 1
                if kind == 'validLeases' and payload.get('keyword'):
                    workers[owner]['keywords'].append(payload['keyword'])
                if kind == 'validLeases':
                    # Read only the current attempt and policy; never export tokens
                    # or use a lease to claim a computer is online.
                    task_kind, evidence = 'unknown', 'lease_changed_during_read'
                    try:
                        attempt = c.command('HGET', namespace + ':attempts', task_id)
                        recollection = decode(c.command('HGET', namespace + ':recollection-once', task_id))
                        if (c.command('HGET', namespace + ':statuses', task_id) == 'leased'
                                and c.command('HGET', namespace + ':owners', task_id) == raw_owner):
                            task_kind, evidence = leased_activity(attempt, recollection)
                    except Exception:
                        task_kind, evidence = 'unknown', 'lease_type_observation_unavailable'
                    activity[task_kind] += 1
                    workers[owner]['taskActivity'][task_kind] += 1
                    workers[owner]['currentTasks'].append({'taskId': task_id, 'keyword': payload.get('keyword'),
                                                          'activity': task_kind, 'evidence': evidence})
    unmatched = max(0, counts['total'] - sum(matched.values()))
    if unmatched:
        topics['清单外/读取期间变化'] = {'total': unmatched}
    classified = counts['pendingNew'] + counts['retryPending'] + counts['pendingUnclassified']
    if classified > counts['pending']:
        # The pool changed while reading. Never publish an inconsistent split.
        counts['pendingNew'] = counts['retryPending'] = 0
        counts['pendingUnclassified'] = counts['pending']
    else:
        counts['pendingUnclassified'] += counts['pending'] - classified
    return {'campaign': campaign, 'source': 'ok',
            'counts': {k: counts[k] for k in ('total', 'pending', 'pendingNew', 'retryPending', 'pendingUnclassified', 'leased', 'completed', 'completed_with_skips', 'skipped_unresolved', 'noChangeCompleted', 'failed', 'unknown', 'excluded', 'validLeases', 'expiredLeases', 'missingLeaseEvidence')},
            'disposedCount': counts['completed'] + counts['completed_with_skips'] + counts['skipped_unresolved'],
            'topics': {k: dict(v) for k, v in sorted(topics.items())},
            'workers': [{'worker': owner, **row} for owner, row in sorted(workers.items())],
            'activeLeaseActivity': dict(activity),
            'completedResultStates': dict(result_states), 'retryExhaustedCompleted':counts['retryExhaustedCompleted'],
            'resetOnceCompleted':counts['resetOnceCompleted'],'completedPendingImport':counts['completedPendingImport'],'projects': sorted(projects),
            'missingPayloadCount': missing_payloads,
            'unmatchedManifestTasks': unmatched,
            'definition': '完成、含跳过完成、整词跳过分别统计；最终处置不等于成功采集。待领=pending且attempts=0；重试=pending且attempts>0；缺失计数不默认0。租约非心跳；非事务快照。'}


def collect_platform(platform):
    common = platform_root(platform) / 'common'
    result = {'platform': platform, 'generatedAt': datetime.now(timezone.utc).isoformat(), 'source': 'unavailable'}
    try:
        config = load_json(common / 'redis-config.json')
        manifest = load_json(common / 'tasks/redis-tasks.json')
        campaign = config.get('taskPoolCampaign') or config['campaign'] + '-mysql-' + manifest['manifestHash'][:16]
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', campaign):
            raise ValueError('Invalid production campaign')
        namespace = PLATFORMS[platform] + ':{' + campaign + '}'
        url = urlparse(config['url'])
        if url.username or url.password or url.query or url.fragment:
            raise ValueError('Credential-bearing Redis URL rejected')
        username = config.get('username')
        if username:
            url = url._replace(netloc=quote(username, safe='') + '@' + url.netloc)
        password = os.environ.get('MONITOR_PLATFORM_REDIS_PASSWORD')
        if not password:
            raise ValueError('Existing encrypted credential unavailable')
        with RedisConnection(urlunparse(url), password, timeout=8) as connection:
            c = ReadOnlyRedis(connection)
            result.update(queue_observation(c, namespace, campaign, manifest['tasks']))
            from platform_telemetry import read_telemetry
            result['telemetry'] = read_telemetry(c, namespace, campaign)
        result['localManifestTaskCount'] = manifest['taskCount']
        result['configuredWorkers'] = sorted(p.name for p in common.parent.iterdir() if p.is_dir() and re.fullmatch(r'worker-[0-9]{2}',p.name))
        result['scope'] = '配置指定的当前生产任务池；不包含旧批次、export、测试或未配置的作者队列。'
    except Exception as error:
        # Error text may contain usernames/connection details. Publish type only.
        result['errorType'] = type(error).__name__
        if isinstance(error, PermissionError):
            result['reason'] = str(error)
        result['counts'] = None
    result['localProcesses'] = local_processes(platform)
    return result


def local_processes(platform):
    try:
        evidence = load_json(ROOT/'output/local-supervisors.json')
        sampled = datetime.fromisoformat(evidence['sampledAt'].replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc)-sampled).total_seconds()
        if not 0 <= age < 60: return []
        rows = []
        for process in evidence['supervisors']:
            if process['platform'] != platform or not re.fullmatch(r'worker-[0-9]{2}', process['worker']): continue
            state = 'executing' if process.get('collectorCount') else 'waiting'
            # Absence of child Node is insufficient. A recent successful cycle
            # end plus a live supervisor supports normal rest/wait, not a fault.
            worker = platform_root(platform) / process['worker']
            try:
                status = load_json(worker/'runs/worker_status.json')
                finished = datetime.fromisoformat(status['finishedAt'].replace('Z', '+00:00'))
                rest_age = (sampled-finished).total_seconds()
                if not process.get('collectorCount') and 0 <= rest_age <= 3660 and not status.get('fatalError') and status.get('status') in ('partial_stopped', 'retry_after_rest', 'completed') and not (worker/'.state/supervisor.stop').exists():
                    state = 'resting_or_waiting'
            except (OSError, ValueError, KeyError, AttributeError, TypeError): pass
            rows.append({'worker': process['worker'], 'computer': evidence['computer'],
                         'state': state, 'supervisorPid': process['supervisorPid'],
                         'sampledAt': evidence['sampledAt'], 'evidence': 'live_local_process_snapshot_not_heartbeat'})
        return rows
    except (OSError, ValueError, KeyError): return []


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--platform', choices=PLATFORMS, required=True)
    args = parser.parse_args()
    result = collect_platform(args.platform)
    atomic_json(ROOT / 'output' / ('platform-' + args.platform + '.json'), result)
    print(json.dumps({'platform': args.platform, 'source': result['source'], 'errorType': result.get('errorType')}, ensure_ascii=False))
