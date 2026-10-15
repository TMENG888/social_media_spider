"""Read-only, whole-database sampled growth; never infer commits from capture dates."""
import json
from datetime import timedelta
from worker_metrics import stamp
from collect import atomic_json

FIELDS = ('posts', 'videoContentNonempty')


def sample(db):
    at = stamp(db.get('generatedAt'))
    if db.get('source') != 'ok' or not at:
        return None
    rows = [('视频号', r) for r in db.get('posts', [])]
    rows += [(r['platform'], r) for r in db.get('otherPlatforms', [])]
    result = {}
    for platform, row in rows:
        group = result.setdefault(platform, {'projects': [], 'posts': 0, 'videoContentNonempty': 0})
        group['projects'].append(row['project'])
        group['posts'] += int(row.get('posts') or 0)
        # Old snapshots have this same column under a misleading legacy alias.
        group['videoContentNonempty'] += int(row.get('videoContentNonempty', row.get('subtitleNonempty', row.get('contentNonempty', 0))) or 0)
    for group in result.values():
        group['projects'] = sorted(group['projects'])
    return {'at': at.isoformat(), 'platforms': result}


def measured_growth(history, current):
    if current is None:
        return {}
    now = stamp(current['at'])
    measured = {}
    for platform, latest in current['platforms'].items():
        eligible = [s for s in history if stamp(s.get('at')) and now-timedelta(hours=1) <= stamp(s['at']) <= now-timedelta(seconds=60)
                    and s.get('platforms', {}).get(platform, {}).get('projects') == latest['projects']]
        if not eligible:
            measured[platform] = {'source': 'warming_up', 'windowSeconds': None}
            continue
        base = min(eligible, key=lambda s: stamp(s['at']))
        duration = (now-stamp(base['at'])).total_seconds()
        deltas = {field: latest[field]-base['platforms'][platform][field] for field in FIELDS}
        measured[platform] = {'source': 'sampled_net_growth', 'windowSeconds': duration,
                              'windowStart': base['at'], 'windowEnd': current['at'],
                              'netPosts': deltas['posts'], 'netVideoContent': deltas['videoContentNonempty'],
                              'netPostsPerHour': round(deltas['posts']*3600/duration, 1),
                              'negativeDelta': any(v < 0 for v in deltas.values()),
                              'definition': 'Configured project cumulative-row deltas across all machines; net growth is not gross inserts or verified commit events. No capture-time inference.'}
    return measured


def observe_efficiency(out, db):
    path = out/'database-growth-history.json'
    try:
        history = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(history, list): history = []
    except (OSError, ValueError): history = []
    # Seed only from a prior real read-only DB snapshot, not delivery or capture time.
    if not history:
        try:
            prior = sample(json.loads((out/'snapshot.json').read_text(encoding='utf-8'))['database'])
            if prior: history.append(prior)
        except (OSError, ValueError, KeyError): pass
    current = sample(db)
    result = measured_growth(history, current)
    if current:
        now = stamp(current['at'])
        history = [s for s in history if stamp(s.get('at')) and now-timedelta(hours=2) <= stamp(s['at']) < now]
        history.append(current)
        atomic_json(path, history[-500:])
    return result
