"""Independent machine heartbeat and verified commits, never inferred from leases."""
from datetime import datetime, timezone, timedelta
from platform_tasks import decode
from worker_metrics import stamp


def machine_states(records, campaign, now_ms, stale_seconds=30):
    latest = {}
    for record in records:
        dt = stamp(record.get('lastSeenAt'))
        if record.get('campaign') != campaign or record.get('deploymentTest') or not dt:
            continue
        identity = (record.get('computer'), record.get('worker'))
        if not all(identity): continue
        if identity not in latest or dt > stamp(latest[identity]['lastSeenAt']):
            latest[identity] = record
    rows = []
    for (computer, worker), record in sorted(latest.items()):
        age = now_ms/1000-stamp(record['lastSeenAt']).timestamp()
        state = record.get('state')
        observation = 'clock_skew' if age < -10 else 'heartbeat_stale' if age > stale_seconds else {
            'collecting': 'executing', 'resting': 'resting', 'cooldown': 'cooldown',
            'waiting': 'online_waiting', 'starting': 'online_waiting', 'stopped': 'stopped',
        }.get(state, 'unknown')
        rows.append({'computer': computer, 'worker': worker, 'observation': observation,
                     'lastHeartbeatAt': record['lastSeenAt'], 'heartbeatAgeSeconds': age,
                     'heartbeatIntervalSeconds': record.get('heartbeatIntervalSeconds'),
                     'resumeAt': record.get('resumeAt'), 'supervisorPid': record.get('supervisorPid'),
                     'evidence': 'independent_supervisor_heartbeat'})
    return rows


def verified_output(events, campaign, now_ms):
    accepted = []
    seen = set()
    for event in events:
        dt = stamp(event.get('committedAt'))
        if (event.get('campaign') != campaign or event.get('deploymentTest') or not event.get('readbackVerified')
                or not dt or not now_ms/1000-3600 <= dt.timestamp() <= now_ms/1000
                or not event.get('eventId') or event['eventId'] in seen): continue
        if any(not isinstance(event.get(k),int) or isinstance(event.get(k),bool) or event[k]<0 for k in ('newPosts','videoContentWrites')):continue
        seen.add(event['eventId']); accepted.append(event)
    # An empty ledger does not prove telemetry is deployed or no output occurred.
    if not accepted: return None
    return {'newPosts': sum(int(e.get('newPosts', 0)) for e in accepted),
            'videoContentWrites': sum(int(e.get('videoContentWrites', 0)) for e in accepted),
            'verifiedBatches': len(accepted), 'scope': 'Only loaded, verified-commit telemetry; missing machines may be uninstrumented.'}


def read_telemetry(c, namespace, campaign):
    seconds, micros = c.command('TIME')
    now_ms = int(seconds)*1000 + int(micros)/1000
    result = {'source': 'unobserved', 'machines': [], 'hourly': None}
    try:
        records = [decode(v) for v in c.command('HVALS', namespace+':monitor:workers') or []]
        result['machines'] = machine_states(records, campaign, now_ms)
        result['source'] = 'ok' if result['machines'] else 'unobserved'
    except Exception as error:
        result['source'] = 'unavailable'; result['errorType'] = type(error).__name__
    try:
        now = datetime.fromtimestamp(now_ms/1000, timezone.utc)
        events = []
        for bucket in (now.strftime('%Y%m%d%H'), (now-timedelta(hours=1)).strftime('%Y%m%d%H')):
            events += [decode(v) for v in c.command('HVALS', namespace+':monitor:commits:'+bucket) or []]
        result['hourly'] = verified_output(events, campaign, now_ms)
        result['outputSource'] = 'ok' if result['hourly'] else 'unobserved'
    except Exception as error:
        result['outputSource'] = 'unavailable'; result['outputErrorType'] = type(error).__name__
    result['sampledAt'] = datetime.fromtimestamp(now_ms/1000, timezone.utc).isoformat()
    return result
