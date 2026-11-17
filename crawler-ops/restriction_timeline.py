"""Independent, read-only restriction observations; never writes crawler state.

Redis only retains the last incident per worker. Keep observations in a separate
SQLite database and backfill explicit rate-limit records from bounded logs.
No codes, cookies, account details, QR images or arbitrary errors are retained.
"""
import hashlib
import json
import math
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from settings import OUTPUT, MACHINES, PLATFORMS, worker, worker_root, read_json

BJ = timezone(timedelta(hours=8))
DB = OUTPUT / 'restriction-timeline.sqlite3'
KINDS = {'login', 'captcha', 'security', 'sms', 'slider', 'click', 'gateway'}


def stamp(value):
    try:
        if isinstance(value, bool):return None
        if isinstance(value, (float, int)):
            result = value / 1000 if value > 1e12 else value
        else:
            date = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            result = (date.replace(tzinfo=BJ) if date.tzinfo is None else date).timestamp()
        return result if math.isfinite(result) and result > 0 else None
    except (ValueError, TypeError, OverflowError):return None


@contextmanager
def connection(path=DB):
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=5)
    c.row_factory = sqlite3.Row
    try:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
      CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY, platform TEXT, machine TEXT, kind TEXT,
        started REAL, last_seen REAL, resolved REAL, cooldown REAL,
        keyword TEXT, precision TEXT, source TEXT);
      CREATE INDEX IF NOT EXISTS events_time ON events(platform,machine,started);
      CREATE TABLE IF NOT EXISTS aliases (alias TEXT PRIMARY KEY, event_id TEXT);
      CREATE TABLE IF NOT EXISTS steps (id TEXT PRIMARY KEY, event_id TEXT, kind TEXT, observed REAL);
      CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
        ''')
        with c:yield c
    finally:c.close()


def safe_session(s):
    auth = s.get('auth') or {}
    challenge = s.get('challenge') or {}
    # Fixed fields only. In particular, never copy sms, image, evidence or ack.
    return dict(sessionId=str(s.get('sessionId') or '')[:100], phase=str(s.get('phase') or '')[:40],
                updatedAt=stamp(s.get('updatedAt')), verifiedAt=stamp(s.get('verifiedAt')),
                challengeType=str(challenge.get('type') or '')[:30],
                proof=auth.get('version') == 'login-proof-20261111-v1' and
                      auth.get('credentialPresent') is True and auth.get('verified') is True)


def collect_files(label, now=None):
    """Executed in a bounded child process, so inaccessible SMB cannot hang UI."""
    now = now or time.time()
    m = next(m for m in MACHINES if m['label'] == label)
    result = dict(machine=label, records=[], sessions=[], coverage=[])
    for platform in PLATFORMS:
        root = worker_root(m, platform)
        coverage = dict(platform=platform, machine=label, source='ok', files=0, earliestLogAt=None)
        try:
            # A successful directory listing distinguishes empty history from SMB failure.
            names = {p.name:p for p in (root/'runs').iterdir() if p.is_file()}
            for days in (range(8) if platform=='xhs' else ()):
                date = datetime.fromtimestamp(now-days*86400, BJ).strftime('%Y-%m-%d')
                for suffix in ('.jsonl.1', '.jsonl'):
                    p = names.get('cooldown-diagnostics-'+date+suffix)
                    if not p:continue
                    if p.stat().st_size > 2_300_000:
                        coverage['source'] = 'partial';continue
                    coverage['files'] += 1
                    for line in p.read_text(encoding='utf-8-sig').splitlines():
                        try:r = json.loads(line)
                        except (ValueError, TypeError):continue
                        at = stamp(r.get('at'))
                        if not at or not now-8*86400 <= at <= now+10:continue
                        if r.get('machine','').upper()!=m['computer'].upper() or r.get('workerId')!=worker(m,platform):continue
                        coverage['earliestLogAt'] = min(coverage['earliestLogAt'] or at, at)
                        # Redis/network errors and repeated reads are NOT platform restrictions.
                        if r.get('stage')!='record_rate_limit' or r.get('event') not in ('operation_ok','operation_recovered'):continue
                        protection = r.get('protection') or {}
                        if protection.get('active') is not True:continue
                        until = stamp(protection.get('untilMs'))
                        if not until:continue
                        result['records'].append(dict(id=f'rate:{platform}:{label}:{until}',platform=platform,
                          machine=label,kind='security',started=at,last_seen=at,cooldown=until,
                          keyword=str(r.get('keyword') or '')[:160],precision='recorded',source='cooldown_log'))
            copy = read_json(root/'.state/ops/login-v2.json', {}) or {}
            s = copy.get('data') or {}
            if (copy.get('projectionVersion')=='login-auth-copy-20261111-v2' and
                copy.get('kind')=='login' and s.get('machine')==label and
                s.get('platform')==PLATFORMS[platform] and s.get('workerId')==worker(m,platform)):
                result['sessions'].append(dict(platform=platform,machine=label,**safe_session(s)))
        except OSError:coverage['source']='unavailable'
        result['coverage'].append(coverage)
    return result


def incident_record(platform, raw):
    if raw.get('deploymentTest') or raw.get('test') or raw.get('kind') not in ('login','captcha','security'):return None
    m = next((m for m in MACHINES if m['computer'].upper()==str(raw.get('machine','')).upper()
              and worker(m,platform)==raw.get('workerId')), None)
    at = stamp(raw.get('startedAt'))
    if not m or not at or not raw.get('incidentId'):return None
    return dict(id='incident:'+platform+':'+str(raw['incidentId'])[:240],platform=platform,machine=m['label'],
                kind=raw['kind'],started=at,last_seen=stamp(raw.get('lastSeenAt')) or at,
                resolved=stamp(raw.get('resolvedAt')) if raw.get('status')=='resolved' else None,
                cooldown=stamp(raw.get('cooldownUntil')),
                keyword=str(raw.get('keyword') or '')[:160],precision='triggered',source='redis_incident')


def upsert(c, r):
    if r.get('kind') not in KINDS or r.get('platform') not in PLATFORMS:return
    c.execute('''INSERT INTO events VALUES (:id,:platform,:machine,:kind,:started,:last_seen,:resolved,:cooldown,:keyword,:precision,:source)
      ON CONFLICT(id) DO UPDATE SET
        started=MIN(events.started,excluded.started),
        last_seen=MAX(events.last_seen,excluded.last_seen),
        resolved=COALESCE(excluded.resolved,events.resolved),
        cooldown=COALESCE(excluded.cooldown,events.cooldown),
        keyword=CASE WHEN excluded.keyword<>'' THEN excluded.keyword ELSE events.keyword END
    ''', {'resolved':None,'cooldown':None,'keyword':'',**r})


def update(redis, file_results, now=None, path=DB):
    now = now or time.time()
    coverage=[]
    with connection(path) as c:
        # Earliest available record is not a guarantee of uninterrupted monitoring.
        c.execute("INSERT OR IGNORE INTO metadata VALUES ('trackingSince',?)",(str(now),))
        for platform, name in PLATFORMS.items():
            data=redis.get(name,{})
            coverage.append(dict(platform=platform,source=data.get('restrictionsSource','unavailable'),channel='redis'))
            for raw in data.get('incidents',[]):
                r=incident_record(platform,raw)
                if r and now-8*86400<=r['started']<=now+10:upsert(c,r)
        for label,result in file_results.items():
            if not isinstance(result,dict):continue
            coverage.extend(result.get('coverage') or [dict(platform=p,machine=label,source='unavailable',channel='files') for p in PLATFORMS])
            for r in result.get('records',[]):
                # Link a log to Redis only with matching cooldown or actual active interval.
                match=c.execute('''SELECT id FROM events WHERE platform=? AND machine=? AND kind='security'
                  AND source='redis_incident' AND (ABS(cooldown-?)<1 OR (started<=? AND last_seen>=?)) LIMIT 1''',
                  (r['platform'],r['machine'],r['cooldown'],r['started']+5,r['started']-5)).fetchone()
                if match:
                    if r.get('keyword'):c.execute("UPDATE events SET keyword=? WHERE id=? AND keyword=''",(r['keyword'],match['id']))
                else:upsert(c,r)
            for s in result.get('sessions',[]):observe_session(c,s,now)
        c.execute("INSERT OR REPLACE INTO metadata VALUES ('sampledAt',?)",(str(now),))
        c.execute("INSERT OR REPLACE INTO metadata VALUES ('coverage',?)",(json.dumps(coverage),))
        # Retain an extra day so the first visible event may have a previous trigger.
        c.execute('DELETE FROM events WHERE started<?',(now-9*86400,))
        c.execute('DELETE FROM aliases WHERE event_id NOT IN (SELECT id FROM events)')
        c.execute('DELETE FROM steps WHERE event_id NOT IN (SELECT id FROM events)')
    return dict(sampledAt=now,source='ok')


def observe_session(c,s,now):
    if not s.get('sessionId'):return
    alias='session:'+s['platform']+':'+s['machine']+':'+s['sessionId']
    linked=c.execute('SELECT event_id FROM aliases WHERE alias=?',(alias,)).fetchone()
    phase=s['phase'];updated=s.get('updatedAt')
    if phase=='verified':
        if linked and s.get('proof') and s.get('verifiedAt'):
            c.execute('UPDATE events SET resolved=COALESCE(resolved,?) WHERE id=?',(s['verifiedAt'],linked['event_id']))
        return
    # Stale sessions and QR refresh generations never become new events.
    if not updated or not -10<=now-updated<=45:return
    if phase in ('waiting_scan','qr_expired','qr_rejected','qr_unavailable'):kind='login'
    elif phase.startswith('sms_') or phase=='waiting_sms':kind='sms'
    elif phase=='manual_captcha':
        t=s.get('challengeType','');kind='slider' if t=='slider' else 'click' if any(x in t for x in ('click','select','point')) else 'captcha'
    elif phase=='manual_security':kind='security'
    elif phase=='manual_gateway':kind='gateway'
    else:return
    if not linked:
        match=c.execute('''SELECT id FROM events WHERE platform=? AND machine=? AND resolved IS NULL
          AND started<=? AND last_seen>=? AND source='redis_incident' ORDER BY started DESC LIMIT 1''',
          (s['platform'],s['machine'],now+10,now-300)).fetchone()
        event_id=match['id'] if match else alias
        if not match:upsert(c,dict(id=event_id,platform=s['platform'],machine=s['machine'],kind=kind,
                                 started=now,last_seen=now,precision='observed',source='login_session'))
        c.execute('INSERT OR REPLACE INTO aliases VALUES (?,?)',(alias,event_id))
    else:event_id=linked['event_id']
    # A later SMS/slider observation must not rewrite the original trigger type
    # and falsely backdate the later step to the initial login trigger time.
    if kind in ('sms','slider','click'):
        c.execute('INSERT OR IGNORE INTO steps VALUES (?,?,?,?)',(alias+':'+kind,event_id,kind,now))
    c.execute('UPDATE events SET last_seen=MAX(last_seen,?) WHERE id=?',(updated,event_id))


def query(days=1,platform='xhs',machine='all',page=1,now=None,path=DB):
    if days not in (1,7) or platform not in PLATFORMS or machine not in ['all']+[m['label'] for m in MACHINES] or not 1<=page<=10000:
        raise ValueError('INVALID_FILTER')
    now=now or time.time()
    with connection(path) as c:
        meta={r['key']:r['value'] for r in c.execute('SELECT * FROM metadata')}
        values=list(c.execute('SELECT * FROM events WHERE platform=? AND started<=? ORDER BY machine,started,id',(platform,now)))
        steps={}
        for s in c.execute('SELECT event_id,kind,MIN(observed) AS observed FROM steps GROUP BY event_id,kind ORDER BY observed'):
            steps.setdefault(s['event_id'],[]).append(dict(kind=s['kind'],observedAt=s['observed']))
    previous={};rows=[]
    for raw in values:
        r=dict(raw);old=previous.get(r['machine']);previous[r['machine']]=r
        if r['started']<now-days*86400 or machine!='all' and r['machine']!=machine:continue
        r['intervalSeconds']=r['started']-old['started'] if old else None
        r['verificationSteps']=steps.get(r['id'],[])
        r['intervalApproximate']=r['precision']=='observed' or bool(old and old['precision']=='observed')
        r['status']='resolved' if r['resolved'] else 'cooling' if r['kind']=='security' and (r['cooldown'] or 0)>now else 'unconfirmed'
        rows.append(r)
    rows.sort(key=lambda r:(r['started'],r['id']),reverse=True)
    total=len(rows);size=20;pages=max(1,(total+size-1)//size);page=min(page,pages)
    return dict(rows=rows[(page-1)*size:page*size],total=total,page=page,pages=pages,
                days=days,platform=platform,machine=machine,serverAt=now,
                sampledAt=float(meta.get('sampledAt',0)),trackingSince=float(meta.get('trackingSince',0)),
                coverage=json.loads(meta.get('coverage','[]')),historyComplete=False)
