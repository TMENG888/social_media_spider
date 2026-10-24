"""Recover terminal reset-once imports from the original node, never replay UI.

No task claim/ACK/reset is performed. Import receipts are durable before the
Redis compare-and-set, so a lost Redis reply does not cause a second import.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

POLICY = 'channels-import-only-recovery-20261021-v1'
CONFIRM_IMPORT = """
local old=redis.call('HGET',KEYS[1],ARGV[1])
local ledger=redis.call('HGET',KEYS[2],ARGV[1])
if old~=ARGV[2] or ledger~=ARGV[3] then return 'changed' end
redis.call('HGET',KEYS[3],'__probe__')
local r=cjson.decode(old);local s=cjson.decode(ledger)
if r.status~='completed' or r.acceptedBy~='reset_once_recollection'
 or r.pendingImport~=true or s.state~='completed' or s.result~=old then
 return redis.error_reply('IMPORT_RECOVERY_STATE_MISMATCH') end
local receipt=cjson.decode(ARGV[4])
if receipt.policy~='channels-import-only-recovery-20261021-v1'
 or receipt.taskId~=ARGV[1] or receipt.importConfirmed~=true then
 return redis.error_reply('IMPORT_RECOVERY_RECEIPT_INVALID') end
r.pendingImport=false;r.dataImported=true;r.importRecovery=receipt
local value=cjson.encode(r)
s.result=value;s.importRecovery=receipt
local next_ledger=cjson.encode(s)
local archive=cjson.encode({statusBefore=old,ledgerBefore=ledger,receipt=receipt})
redis.call('HSET',KEYS[3],ARGV[1]..'|import-recovery|'..receipt.requestId,archive)
redis.call('HSET',KEYS[1],ARGV[1],value)
redis.call('HSET',KEYS[2],ARGV[1],next_ledger)
return 'confirmed'
"""


def decode(raw):
    value = json.loads(raw) if raw else {}
    if not isinstance(value, dict):
        raise ValueError('IMPORT_RECOVERY_INVALID_RECORD')
    return value


def fields(raw):
    return dict(zip(raw[::2], raw[1::2]))


def completion_snapshot(runtime):
    states = fields(runtime.command('HGETALL', runtime.args.status_key) or [])
    selected = runtime.selected
    records = [decode(states.get(t['task_id'])) for t in selected]
    closed = sum(r.get('status') == 'completed' for r in records)
    pending = sum(r.get('pendingImport') is True for r in records)
    return {'selectedCount': len(selected), 'businessCompleted': closed,
            'pendingImport': pending, 'businessKeywordsComplete': closed == len(selected),
            'allKeywordsComplete': closed == len(selected) and pending == 0}


def safe_component(value):
    return re.sub(r'[^A-Za-z0-9_-]+', '_', str(value)).strip('_')


def keyword_component(value):
    # Equivalent to PowerShell's Unicode letters/numbers whitelist.
    return re.sub(r'[^\w-]+', '_', value, flags=re.UNICODE).strip('_')


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def local_lock(path):
    """OS-held lock is released on crash; never delete somebody else's lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            # A persistent single-byte file is harmless; the lock lives on the FD.
            if path.stat().st_size == 0:
                stream.write(b'0'); stream.flush(); stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def recover_local(runtime, task, request_id, stopped):
    """Launch offline export/postprocess/import only, with fresh bound receipt."""
    a = runtime.args
    work = a.worker_root / '.state' / 'pending-import-recovery' / safe_component(task['task_id']) / request_id
    receipt_file = work / 'result.json'
    started_file = work / 'attempt-started.json'
    if receipt_file.exists():
        prior = decode(receipt_file.read_text(encoding='utf-8-sig'))
        if prior.get('requestId') != request_id or prior.get('taskId') != task['task_id']:
            return {'status': 'receipt_mismatch'}
        if prior.get('importConfirmed') is True or prior.get('requiresCommitReconciliation') is True:
            return prior
    elif started_file.exists():
        # Parent/OS crash during an import has an unknown transaction outcome.
        return {'status': 'commit_confirmation_required', 'requiresCommitReconciliation': True}
    if stopped():
        return {'status': 'stopped'}
    scope = safe_component(safe_component(a.run_id) + '-' + safe_component(a.run_generation))
    scope += '-reset-once-20261016-v1'
    topic = task['topic']
    if topic not in ('topic1', 'topic2'):
        return {'status': 'identity_mismatch'}
    state_db = a.worker_root / '.state' / 'redis-runs' / scope / (topic + '.sqlite')
    original = a.worker_root / 'runs' / 'redis-runs' / scope / topic / keyword_component(task['keyword'])
    if not state_db.is_file():
        return {'status': 'local_checkpoint_missing'}
    output = work / 'export'
    request = {'requestId': request_id, 'taskId': task['task_id'], 'keyword': task['keyword'],
               'stateDb': str(state_db), 'originalOutput': str(original), 'outputDir': str(output),
               'stopFile': str(a.worker_root / '.state' / 'stop.requested'),
               'collectComments': bool(task.get('queue', {}).get('tasks', [{}])[0].get('collectComments'))}
    request_file = work / 'request.json'
    atomic_json(request_file, request)
    atomic_json(started_file, {'requestId': request_id, 'taskId': task['task_id']})
    env = os.environ.copy()
    # Never publish collection output telemetry from a maintenance-only import.
    for name in list(env):
        if name.startswith('WECHAT_REDIS_') or name in ('REDIS_URL', 'REDIS_PASSWORD'):
            env.pop(name, None)
    try:
        process = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', str(a.common / 'recover-pending-import.ps1'), '-RequestFile', str(request_file),
            '-ResultFile', str(receipt_file)], env=env, capture_output=True, timeout=600,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired:
        result = {'requestId': request_id, 'taskId': task['task_id'], 'status': 'commit_confirmation_required',
                  'requiresCommitReconciliation': True, 'success': False, 'importConfirmed': False}
        atomic_json(receipt_file, result)
        return result
    # Raw child output is intentionally not logged (driver messages may be sensitive).
    if not receipt_file.exists():
        return {'status': 'recovery_receipt_missing'}
    result = decode(receipt_file.read_text(encoding='utf-8-sig'))
    if process.returncode != 0 and result.get('importConfirmed') is True:
        return {'status': 'recovery_exit_unconfirmed'}
    return result


def recover_pending_imports(runtime, stopped, *, recover=None, machine=None):
    recover = recover or recover_local
    machine = machine or socket.gethostname()
    a = runtime.args
    statuses = fields(runtime.command('HGETALL', a.status_key) or [])
    ledgers = fields(runtime.command('HGETALL', a.prefix + ':recollection-once') or [])
    summary = {'pending': 0, 'confirmed': 0, 'awaitingSource': 0, 'unresolved': 0, 'failed': 0}
    for task in runtime.selected:
        raw = statuses.get(task['task_id'])
        record = decode(raw)
        if record.get('pendingImport') is not True:
            continue
        summary['pending'] += 1
        if stopped():
            break
        ledger_raw = ledgers.get(task['task_id'])
        ledger = decode(ledger_raw)
        if (record.get('status') != 'completed' or record.get('acceptedBy') != 'reset_once_recollection'
                or ledger.get('state') != 'completed' or ledger.get('result') != raw):
            summary['unresolved'] += 1
            print(json.dumps({'event': 'pending_import_recovery', 'taskId': task['task_id'],
                              'status': 'ledger_mismatch'}), flush=True)
            continue
        owner = str(ledger.get('owner') or '')
        if not owner.upper().startswith((machine + '-' + a.worker_root.name + '-').upper()):
            summary['awaitingSource'] += 1
            continue
        request_id = hashlib.sha256((raw + '\n' + ledger_raw).encode('utf-8')).hexdigest()
        lock = a.worker_root / '.state' / 'pending-import-recovery' / (safe_component(task['task_id']) + '.lock')
        try:
            with local_lock(lock):
                result = recover(runtime, task, request_id, stopped)
                valid = (result.get('importConfirmed') is True and result.get('success') is True
                         and result.get('requestId') == request_id and result.get('taskId') == task['task_id']
                         and result.get('mysql', {}).get('status') == 'success'
                         and isinstance(result.get('mysql', {}).get('posts'), int)
                         and not isinstance(result['mysql']['posts'], bool)
                         and result['mysql']['posts'] > 0)
                if valid:
                    receipt = {'policy': POLICY, 'taskId': task['task_id'], 'requestId': request_id,
                               'machine': machine, 'workerId': a.worker_root.name, 'importConfirmed': True,
                               'posts': result['mysql']['posts'], 'confirmedAt': datetime.now(timezone.utc).isoformat()}
                    changed = runtime.command('EVAL', CONFIRM_IMPORT, 3, a.status_key,
                        a.prefix + ':recollection-once', a.prefix + ':recollection-history',
                        task['task_id'], raw, ledger_raw, json.dumps(receipt))
                    status = 'confirmed' if changed == 'confirmed' else 'state_changed_receipt_retained'
                    summary['confirmed' if changed == 'confirmed' else 'unresolved'] += 1
                else:
                    status = result.get('status', 'import_unconfirmed')
                    summary['unresolved'] += 1
                    if status not in ('local_checkpoint_missing', 'stopped'):
                        summary['failed'] += 1
        except (OSError, subprocess.TimeoutExpired, ValueError):
            status = 'local_recovery_failed_or_busy'
            summary['unresolved'] += 1
            summary['failed'] += 1
        print(json.dumps({'event': 'pending_import_recovery', 'taskId': task['task_id'],
                          'status': status, 'collectionReplayed': False}), flush=True)
        if summary['failed']:
            break  # bounded import retry exhausted: stop, never retry the video/UI
    print(json.dumps({'event': 'pending_import_recovery_summary', **summary,
                      'collectionReplayed': False}), flush=True)
    return summary
