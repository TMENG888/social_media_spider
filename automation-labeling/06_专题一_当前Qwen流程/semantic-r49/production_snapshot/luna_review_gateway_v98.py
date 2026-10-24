"""Isolated strictly serial Luna proxy client for post-Qwen reference labeling.

Never reads the Qwen key, never silently falls back to Qwen, and never calls
machine output a human gold standard. Proxy usage and user-reported free access
are distinct from a verified provider bill. All attempt records go to the
explicit output directory, including failures and unknown usage.
"""
import copy
import hashlib
import http.client
import json
import os
import random
import socket
import threading
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

import delivery_v4 as b
from structured_response_validation_v58 import issues as schema_issues

BASE_URL = 'https://in.aquria.cn:13003/v1'
MODEL = 'gpt-6-luna'
VERSION = 'luna-post-qwen-reference-v98-serial-20261013'
_PROCESS_SERIAL_GATE = threading.BoundedSemaphore(1)


@contextmanager
def exclusive_proxy_call():
    """Reject another local process using this adapter; never overlap HTTP calls.

    The OS releases the advisory lock after exit/crash. The persistent empty
    marker is not a checkpoint and contains no credentials or source content.
    All callers acquire the shared in-process gate before this OS-level lock.
    """
    path = Path(tempfile.gettempdir())/'codex-luna-aquria-13003-serial.lock'
    with path.open('a+b') as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError('Another Luna adapter process is active; no HTTP call made') from None
            try:
                yield
            finally:
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError('Another Luna adapter process is active; no HTTP call made') from None
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@dataclass
class Reply:
    status_code: int
    content: bytes
    headers: dict

    def json(self):
        return json.loads(self.content.decode('utf-8'))


def transport(url, body, key, timeout):
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('HTTPS API endpoint required')
    conn = http.client.HTTPSConnection(parts.hostname, parts.port, timeout=timeout)
    active_socket = None
    deadline = time.monotonic()+timeout
    def expire():
        sock = active_socket or conn.sock
        if sock is not None:
            try: sock.shutdown(socket.SHUT_RDWR)
            except OSError: pass
    timer = threading.Timer(timeout, expire); timer.daemon = True; timer.start()
    try:
        conn.request('POST', parts.path, body=json.dumps(body, ensure_ascii=False).encode('utf-8'),
                     headers={'Authorization': 'Bearer '+key, 'Content-Type': 'application/json'})
        active_socket = conn.sock
        response = conn.getresponse(); content = []; size = 0
        while True:
            remaining = deadline-time.monotonic()
            if remaining <= 0: raise TimeoutError('Attempt deadline exceeded')
            active_socket.settimeout(remaining)
            chunk = response.read1(65536)
            if not chunk: break
            size += len(chunk)
            if size > 16*1024*1024: raise ValueError('Proxy response too large')
            content.append(chunk)
        return Reply(response.status, b''.join(content), {k.lower(): v for k, v in response.getheaders()})
    except http.client.HTTPException as exc:
        raise OSError('Proxy transport failed') from exc
    finally:
        timer.cancel(); conn.close()


def retry_after(value, now=None):
    if value is None: return None
    try: return max(0., float(value))
    except (ValueError, TypeError):
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None: when = when.replace(tzinfo=timezone.utc)
            return max(0., when.timestamp()-(time.time() if now is None else now))
        except (ValueError, TypeError, OverflowError): return None


def usage_fields(usage):
    # Keep absent fields absent. Cached tokens are a subset, not extra tokens.
    if not isinstance(usage, dict): usage = {}
    return {'prompt_tokens': usage.get('input_tokens', usage.get('prompt_tokens')),
            'completion_tokens': usage.get('output_tokens', usage.get('completion_tokens')),
            'total_tokens': usage.get('total_tokens'),
            'cached_input_tokens': (usage.get('input_tokens_details') or usage.get('prompt_tokens_details') or {}).get('cached_tokens')}


class LunaReviewRunner:
    supports_response_schema = True

    def __init__(self, output, *, key=None, base=BASE_URL, model=MODEL, concurrency=1,
                 api_style='responses', max_attempts=4, timeout=120, min_interval=5,
                 reasoning_effort='high', max_output_tokens=16384,
                 post=transport, sleep=time.sleep, jitter=random.random):
        if concurrency != 1: raise ValueError('Luna must run strictly serially; concurrency must be 1')
        if not 1 <= max_attempts <= 4: raise ValueError('Bounded attempts required')
        if not 1 <= timeout <= 180: raise ValueError('Bounded attempt deadline required')
        if api_style not in ('responses', 'chat'): raise ValueError('Unknown API style')
        parsed = urlsplit(base)
        if (parsed.scheme != 'https' or parsed.hostname != 'in.aquria.cn' or parsed.port != 13003
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('Explicitly authorized Luna endpoint required')
        self.key = key if key is not None else os.getenv('LUNA_API_KEY', '')
        if not self.key: raise ValueError('Missing dedicated LUNA_API_KEY; no call made; Qwen key not read')
        self.base = base.rstrip('/')
        if not self.base.endswith('/v1'): self.base += '/v1'
        self.model = model; self.api_style = api_style; self.output = Path(output)
        self.gate = _PROCESS_SERIAL_GATE; self.fatal = threading.Event()
        self.lock = threading.Lock(); self.next_start = 0.; self.calls = []
        self.max_attempts = max_attempts; self.timeout = timeout; self.min_interval = min_interval
        self.reasoning_effort = reasoning_effort; self.max_output_tokens = max_output_tokens
        self.post = post; self.sleep = sleep; self.jitter = jitter

    def body(self, system, payload, schema):
        messages = [{'role': 'system', 'content': system},
                    {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
        if self.api_style == 'responses':
            body = {'model': self.model, 'input': messages, 'stream': False,
                    'max_output_tokens': self.max_output_tokens,
                    'reasoning': {'effort': self.reasoning_effort}}
            if schema is not None:
                body['text'] = {'format': {'type': 'json_schema', 'name': 'reference_annotation',
                                           'strict': True, 'schema': schema}}
        else:
            body = {'model': self.model, 'messages': messages, 'stream': False,
                    'max_completion_tokens': self.max_output_tokens,
                    'reasoning_effort': self.reasoning_effort}
            if schema is not None:
                body['response_format'] = {'type': 'json_schema', 'json_schema':
                                          {'name': 'reference_annotation', 'strict': True, 'schema': schema}}
        return body

    def wait_for_start(self):
        with self.lock:
            wait = max(0, self.next_start-time.monotonic())
            self.next_start = max(time.monotonic(), self.next_start)+self.min_interval
        if wait: self.sleep(wait)

    def decode(self, raw):
        if self.api_style == 'chat':
            choice = raw['choices'][0]
            if choice.get('finish_reason') in ('length', 'content_filter'): raise ValueError('Incomplete response')
            text = choice['message']['content']
        else:
            if raw.get('status') != 'completed': raise ValueError('Response not completed')
            text = ''.join(c['text'] for item in raw.get('output', []) if item.get('type') == 'message'
                           for c in item.get('content', []) if c.get('type') == 'output_text')
        # Strict whole JSON object. Do not discard a preamble to fake compliance.
        value = json.loads(text)
        if not isinstance(value, dict): raise ValueError('Expected JSON object')
        return value

    def call(self, system, payload, doc, phase, response_schema=None):
        body = self.body(system, payload, response_schema)
        description = {'version': VERSION, 'base': self.base, 'api_style': self.api_style,
                       'body': body, 'record_id': doc['record_id'], 'phase': phase}
        request_key = hashlib.sha256(json.dumps(description, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        cache = self.output/'calls'/(request_key+'.json')
        with self.gate, exclusive_proxy_call():
            if cache.exists():
                saved = json.loads(cache.read_text(encoding='utf-8'))
                if saved['metrics']['status'] == 'success':
                    metrics = dict(saved['metrics'], cache_hit=True)
                    with self.lock: self.calls.append(metrics)
                    return saved['response'], metrics
                b.save_json(self.output/'call_attempt_history'/(request_key+'_'+str(time.time_ns())+'.json'), saved)
            started = time.monotonic(); attempts = []; result = None; status = 'failed'; error = ''; usage = {}; reported_model = None
            for number in range(1, self.max_attempts+1):
                if self.fatal.is_set(): error = 'Authentication failure; runner stopped'; break
                self.wait_for_start()
                if self.fatal.is_set(): error = 'Authentication failure; runner stopped'; break
                attempt = {'number': number, 'started_at': datetime.now(timezone.utc).isoformat(), 'state': 'started'}
                attempts.append(attempt)
                path = self.output/'http_attempts'/(request_key+'_'+str(time.time_ns())+'.json')
                b.save_json(path, attempt)
                delay = None
                try:
                    reply = self.post(self.base+('/responses' if self.api_style == 'responses' else '/chat/completions'),
                                      body, self.key, self.timeout)
                    code = reply.status_code; attempt['http_status'] = code
                    if code in (401, 403): self.fatal.set(); error = 'Authentication failed'; break
                    if code in (408, 409, 429) or code >= 500:
                        error = 'Transient HTTP failure'; delay = retry_after(reply.headers.get('retry-after'))
                        # Large Retry-After is not shortened to hammer the proxy.
                        if delay is not None and delay > 60:
                            error = 'Retry-After exceeds local retry window'; break
                    elif code >= 300: error = 'Non-retryable HTTP failure'; break
                    else:
                        raw = reply.json(); usage = raw.get('usage') or {}; attempt['usage'] = usage
                        reported_model = raw.get('model'); result = self.decode(raw)
                        issues = schema_issues(result, response_schema) if response_schema is not None else []
                        if issues:
                            status = 'failed_schema'; error = 'Structured response contract not satisfied'; result = None
                        else: status = 'success'
                        # Schema/semantic errors belong to explicit repair/evaluation,
                        # not transport resampling until a desired label appears.
                        break
                except (TimeoutError, OSError, http.client.HTTPException) as exc:
                    error = type(exc).__name__; attempt['network_error'] = error
                except (ValueError, KeyError, TypeError) as exc:
                    error = 'Invalid proxy response: '+type(exc).__name__; attempt['response_error'] = type(exc).__name__
                finally:
                    attempt['state'] = 'finished'; b.save_json(path, attempt)
                if number < self.max_attempts:
                    delay = max(delay or 0., min(30., 2**number+self.jitter()))
                    with self.lock: self.next_start = max(self.next_start, time.monotonic()+delay)
                    self.sleep(delay)
            metrics = {'request_key': request_key, 'record_id': doc['record_id'], 'topic': doc.get('topic'),
                'source_type': doc.get('kind'), 'phase': phase, 'status': status, 'cache_hit': False,
                'model': self.model, 'reported_model': reported_model, 'api_style': self.api_style,
                'model_role': 'reference_candidate', 'reference_is_human_gold': False, 'fallback_used': False,
                'attempts': attempts, 'seconds': round(time.monotonic()-started, 3), 'error': error,
                'unknown_attempt_usage': sum(not a.get('usage') for a in attempts), **usage_fields(usage),
                'estimated_yuan': None, 'user_reported_proxy_cash_fee_yuan': 0,
                'pricing_note': 'User reports no proxy charge; underlying provider bill and unreported usage not verified'}
            b.save_json(cache, {'response': result, 'metrics': metrics})
            with self.lock: self.calls.append(metrics)
            return result, metrics
