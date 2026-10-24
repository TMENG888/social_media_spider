"""New-process I/O and request reliability adapters; annotation core unchanged."""
import errno
import os
import threading
import time
import uuid
from pathlib import Path

_locks = {}
_guard = threading.Lock()


def atomic_save_json(path, value, *, dumps=None, replace=os.replace, sleep=time.sleep):
    if dumps is None:
        import voc_batch_v99 as v
        dumps = v.b.dumps
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _guard:
        lock = _locks.setdefault(str(path.resolve()).casefold(), threading.RLock())
    with lock:
        tmp = path.with_name(path.name + '.' + str(os.getpid()) + '.' + uuid.uuid4().hex + '.tmp')
        # Unique sibling avoids concurrent writers sharing path.json.tmp.
        with tmp.open('x', encoding='utf-8') as stream:
            stream.write(dumps(value))
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(9):
            try:
                replace(tmp, path)
                return
            except OSError as error:
                transient = getattr(error, 'winerror', None) in {5, 32, 33}
                if not transient or attempt == 8:
                    # Preserve failed temp; never report an unsuccessful write as saved.
                    raise
                sleep(min(.05 * 2**attempt, 1.0))


def retryable_failure(metric):
    if metric.get('status') != 'failed':
        return False
    attempts = metric.get('attempts') or []
    if not attempts:
        return False
    # Do not retry auth, invalid schemas, or other non-retryable HTTP errors.
    return all(a.get('network_error') in {'URLError', 'TimeoutError', 'ConnectionError', 'ConnectionResetError'}
               or a.get('http_status') in {408, 409, 429}
               or (isinstance(a.get('http_status'), int) and a['http_status'] >= 500)
               for a in attempts)


def reliable_runner_class(base, stop, sleep=time.sleep):
    class ReliableRunner(base):
        def call(self, system, payload, doc, phase, response_schema=None):
            raw, metric = super().call(system, payload, doc, phase, response_schema)
            if raw is None and retryable_failure(metric) and not self.fatal.is_set() and not stop():
                previous = {'request_key': metric['request_key'], 'status': metric['status'],
                            'attempts': len(metric.get('attempts') or [])}
                # One extra batch only. Existing base batch is at most 3 HTTP
                # attempts; existing JSON recovery is retained, never recursive.
                for _ in range(20):
                    if self.fatal.is_set() or stop():
                        return raw, metric
                    sleep(.1)
                raw, metric = super().call(system, payload, doc, phase, response_schema)
                metric = dict(metric, v9915_bounded_transport_retry=previous)
            return raw, metric
    return ReliableRunner


def install_io():
    import voc_batch_v99 as v
    v.b.save_json = atomic_save_json
