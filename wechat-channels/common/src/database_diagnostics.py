"""Sanitized database readback diagnostics; writes monitoring state only.

No task claim, reset, acknowledgement, SQL write, or collector restart.
Redis failures leave the local monitoring outbox for the next observation.
"""
import hashlib
import json
import os
import re
import socket
import tempfile
from datetime import datetime, timezone
from pathlib import Path

CODES = {
    'ECONNREFUSED', 'ETIMEDOUT', 'ENOTFOUND', 'EAI_AGAIN', 'ECONNRESET',
    'EHOSTUNREACH', 'ENETUNREACH', 'PROTOCOL_CONNECTION_LOST',
    'ER_ACCESS_DENIED_ERROR', 'ER_DBACCESS_DENIED_ERROR',
    'ER_BAD_DB_ERROR', 'ER_NO_SUCH_TABLE', 'ER_TABLEACCESS_DENIED_ERROR',
    'ER_BAD_FIELD_ERROR', 'ER_CON_COUNT_ERROR', 'ER_TOO_MANY_USER_CONNECTIONS',
    'ER_LOCK_WAIT_TIMEOUT', 'ER_QUERY_TIMEOUT', 'HANDSHAKE_SSL_ERROR',
    'MYSQL_CREDENTIALS_MISSING', 'MYSQL_TARGET_INVALID',
    'VOLUME_READBACK_FAILED', 'VOLUME_DATABASE_READBACK_TIMEOUT',
    'VOLUME_READBACK_INVALID_RESPONSE', 'VOLUME_NODE_MISSING',
    'VOLUME_NODE_EXEC_FAILED', 'VOLUME_VALIDATION_FAILED',
    'NODE_DEPENDENCY_MISSING', 'NODE_MODULE_LOAD_FAILED',
}
STAGES = {'connect', 'query', 'validation', 'runtime', 'response', 'unknown'}


def safe_code(value):
    return value if isinstance(value, str) and value in CODES else 'VOLUME_READBACK_FAILED'


def advice(code):
    if code == 'ECONNREFUSED':
        return '数据库端口拒绝连接；核对 MySQL 地址与端口，Redis 正常不代表 MySQL 正常。'
    if code in {'ETIMEDOUT', 'ENOTFOUND', 'EAI_AGAIN', 'EHOSTUNREACH', 'ENETUNREACH'}:
        return '检查数据库域名、网络、白名单和端口；不要重置采集任务。'
    if code in {'ER_ACCESS_DENIED_ERROR', 'ER_DBACCESS_DENIED_ERROR', 'MYSQL_CREDENTIALS_MISSING'}:
        return '在对应机器核对数据库账号和授权；密码仅通过本机安全输入。'
    if code in {'ER_BAD_DB_ERROR', 'ER_NO_SUCH_TABLE', 'ER_BAD_FIELD_ERROR', 'ER_TABLEACCESS_DENIED_ERROR'}:
        return '核对目标库、表结构和读取权限；不要把回读失败当成零数据或成功结案。'
    if code in {'NODE_DEPENDENCY_MISSING', 'NODE_MODULE_LOAD_FAILED', 'VOLUME_NODE_MISSING', 'VOLUME_NODE_EXEC_FAILED'}:
        return '核对 Node 运行时及配套模块是否同步完整；不要重置任务。'
    return '检查该节点数据库回读诊断日志；修复后以真实数据库查询确认恢复。'


def _token(value, fallback='unknown'):
    value = str(value or '')
    return value if re.fullmatch(r'[A-Za-z0-9_.:\-]{1,160}', value) else fallback


def target(common, env):
    try:
        defaults = json.loads((Path(common)/'src/mysql-defaults.json').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        defaults = {}
    host = env.get('MYSQL_HOST') or defaults.get('host')
    port = str(env.get('MYSQL_PORT') or defaults.get('port') or '')
    return {'host': _token(host), 'port': int(port) if port.isdigit() and 0 < int(port) < 65536 else None,
            'database': _token(env.get('MYSQL_DATABASE') or defaults.get('database')),
            'hostSource': 'environment' if env.get('MYSQL_HOST') else 'mysql-defaults.json',
            'loopbackTarget': str(host).lower() in {'127.0.0.1', 'localhost', '::1'}}


def _load(path, default):
    if not path.exists():
        return default
    # Corrupt monitoring state must not be silently overwritten or discarded.
    return json.loads(path.read_text(encoding='utf-8'))


def _atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, suffix='.tmp', delete=False) as stream:
            name = stream.name
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(name, path)
        name = None
    finally:
        if name:
            Path(name).unlink(missing_ok=True)


def observe(common, payload, code=None, stage='unknown', *, env=None, command=None):
    """Return a safe diagnostic. Successful validation alone NEVER resolves SQL faults."""
    env = os.environ if env is None else env
    operation = payload.get('operation') if payload.get('operation') in {'task', 'snapshot', 'annual', 'validate'} else 'unknown'
    if code is None and operation not in {'task', 'snapshot', 'annual'}:
        return None
    configured = env.get('WECHAT_WORKER_ROOT')
    if not configured:
        # Offline imports/fixtures without a worker context must not create state.
        return None
    root = Path(configured)/'.state'
    latest, pending_file = root/'database-readback-status.json', root/'database-monitor-outbox.json'
    previous = _load(latest, {})
    pending = _load(pending_file, [])
    if not isinstance(previous, dict) or not isinstance(pending, list):
        raise ValueError('MONITOR_STATE_INVALID')
    failed = code is not None
    detail = {'kind': 'database', 'platform': '视频号',
              'machine': _token(socket.gethostname()), 'workerId': _token(Path(configured).name),
              'operation': operation, 'stage': stage if stage in STAGES else 'unknown',
              'errorCode': safe_code(code) if failed else None, 'target': target(common, env),
              'taskId': _token(payload.get('taskId'), '')}
    detail['signature'] = hashlib.sha256(json.dumps({k: v for k, v in detail.items() if k != 'taskId'}, sort_keys=True).encode()).hexdigest()
    detail.update(status='active' if failed else 'resolved', observedAt=datetime.now(timezone.utc).isoformat(),
                  databaseReadbackVerified=not failed, taskDispositionChanged=False)
    changed = failed and (previous.get('status') != 'active' or previous.get('signature') != detail['signature'])
    recovered = not failed and previous.get('status') == 'active'
    if changed or recovered:
        pending.append({'action': 'record' if failed else 'resolve', 'diagnostic': detail})
        root.mkdir(parents=True, exist_ok=True)
        with (root/'database-readback-events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(detail, ensure_ascii=False)+'\n')
        print(json.dumps({'event': 'database_readback_failed' if failed else 'database_readback_recovered', **detail}, ensure_ascii=False), flush=True)
    # Save locally before attempting monitoring Redis; never lose the primary error.
    _atomic(pending_file, pending)
    _atomic(latest, detail)
    if pending:
        try:
            run_id = env.get('WECHAT_REDIS_RUN_ID') or env.get('REDIS_RUN_ID')
            if not env.get('REDIS_URL') or not run_id or not re.fullmatch(r'[-_A-Za-z0-9]{1,100}', run_id):
                raise RuntimeError('MONITOR_REDIS_CONTEXT_UNAVAILABLE')
            if command is None:
                from redis_task_queue import redis_command
                command = lambda *parts: redis_command(env['REDIS_URL'], env.get('REDIS_PASSWORD'), *parts, timeout=5)
            script = Path(__file__).with_name('database-incident.lua').read_text(encoding='utf-8')
            prefix = 'wechat:channels:'+run_id
            field = hashlib.sha256(('database|'+detail['machine']+'|'+detail['workerId']).encode()).hexdigest()
            for event in pending:
                command('EVAL', script, 2, prefix+':monitor:database-incidents', prefix+':monitor:outbox',
                        event['action'], field, json.dumps(event['diagnostic'], ensure_ascii=False))
            _atomic(pending_file, [])
            detail['monitorQueued'] = True
        except Exception:
            detail['monitorQueued'] = False
            # No raw exception: Redis messages may contain credentials/URLs.
            detail['monitorErrorCode'] = 'MONITOR_REDIS_DEFERRED'
        _atomic(latest, detail)
    return detail
