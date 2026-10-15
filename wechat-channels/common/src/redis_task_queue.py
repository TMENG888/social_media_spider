#!/usr/bin/env python3
"""Redis Streams scheduler for the three-machine WeChat Channels RPA.

Only the Python standard library is used so the portable runtime does not
need redis-py.  A task is one (topic, keyword) pair.  Consumer-group delivery
prevents two healthy workers from running the same task, periodic XCLAIM
heartbeats protect long videos, and XAUTOCLAIM lets another PC recover work
after a crash or network/power loss.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import queue as thread_queue
import signal
import secrets
import socket
import ssl
import subprocess
import sys
from types import SimpleNamespace
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

# Embedded Python may omit the executed script's directory from sys.path.
SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
from subtitle_review import has_internal_prompt


class RedisError(RuntimeError):
    pass


class RedisConnection:
    def __init__(self, url: str, password: str | None = None, timeout: float = 15.0):
        parsed = urlparse(url)
        if parsed.scheme not in {"redis", "rediss"}:
            raise ValueError("REDIS_URL must start with redis:// or rediss://")
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 6379
        self.db = int((parsed.path or "/0").strip("/") or 0)
        self.username = unquote(parsed.username) if parsed.username else None
        url_password = unquote(parsed.password) if parsed.password else None
        self.password = password or url_password
        self.use_tls = parsed.scheme == "rediss"
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.reader = None

    def __enter__(self):
        raw = socket.create_connection((self.host, self.port), timeout=self.timeout)
        raw.settimeout(self.timeout)
        if self.use_tls:
            raw = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host)
        self.sock = raw
        self.reader = raw.makefile("rb")
        if self.password:
            if self.username:
                self._command("AUTH", self.username, self.password)
            else:
                self._command("AUTH", self.password)
        if self.db:
            self._command("SELECT", self.db)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.reader:
                self.reader.close()
        finally:
            if self.sock:
                self.sock.close()

    @staticmethod
    def _encode(parts: tuple[Any, ...]) -> bytes:
        chunks = [f"*{len(parts)}\r\n".encode()]
        for part in parts:
            data = str(part).encode("utf-8")
            chunks.extend((f"${len(data)}\r\n".encode(), data, b"\r\n"))
        return b"".join(chunks)

    def _read(self):
        line = self.reader.readline()
        if not line:
            raise RedisError("Redis closed the connection")
        marker, payload = line[:1], line[1:-2]
        if marker == b"+":
            return payload.decode("utf-8", "replace")
        if marker == b"-":
            raise RedisError(payload.decode("utf-8", "replace"))
        if marker == b":":
            return int(payload)
        if marker == b"$":
            length = int(payload)
            if length < 0:
                return None
            data = self.reader.read(length)
            if self.reader.read(2) != b"\r\n":
                raise RedisError("Invalid Redis bulk-string terminator")
            return data.decode("utf-8", "replace")
        if marker == b"*":
            count = int(payload)
            if count < 0:
                return None
            return [self._read() for _ in range(count)]
        raise RedisError(f"Unsupported Redis RESP marker: {marker!r}")

    def _command(self, *parts):
        self.sock.sendall(self._encode(parts))
        return self._read()

    def command(self, *parts):
        return self._command(*parts)


def redis_command(url: str, password: str | None, *parts, timeout: float = 15.0):
    with RedisConnection(url, password, timeout=timeout) as client:
        return client.command(*parts)


def flatten_queue(queue: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    for task in queue.get("tasks", []):
        for keyword in task.get("keywordAllowList", []):
            task_id = f"{task['id']}:{hashlib.sha256(keyword.encode('utf-8')).hexdigest()[:20]}"
            one_task = {key: value for key, value in task.items() if key != "keywordAllowList"}
            one_task["keywordAllowList"] = [keyword]
            output.append({
                "task_id": task_id,
                "topic": task["id"],
                "keyword": keyword,
                "queue": {
                    "version": queue.get("version", 1),
                    "cutoff": queue.get("cutoff", "2026-01-01"),
                    "maxResultsPerKeyword": 0,
                    "tasks": [one_task],
                },
            })
    return output


def ensure_group(url: str, password: str | None, stream: str, group: str):
    try:
        redis_command(url, password, "XGROUP", "CREATE", stream, group, "0", "MKSTREAM")
    except RedisError as error:
        if "BUSYGROUP" not in str(error):
            raise


SEED_LUA = """
if redis.call('SADD', KEYS[1], ARGV[1]) == 1 then
  return redis.call('XADD', KEYS[2], '*', 'task_id', ARGV[1], 'payload', ARGV[2])
end
return ''
""".strip()


def seed_tasks(url: str, password: str | None, stream: str, seeded_key: str, tasks: list[dict[str, Any]]):
    inserted = 0
    for item in tasks:
        payload = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        result = redis_command(
            url, password, "EVAL", SEED_LUA, 2, seeded_key, stream, item["task_id"], payload
        )
        if result:
            inserted += 1
    return inserted


def ensure_run_generation(url: str, password: str | None, prefix: str) -> str:
    """Return one Redis-owned generation token for local state isolation.

    Deleting a run namespace removes this key. The first worker after a reset
    creates a new token atomically, so stale SQLite/runs directories from the
    previous generation cannot make freshly seeded tasks look completed.
    """
    generation_key = f"{prefix}:generation"
    current = redis_command(url, password, "GET", generation_key)
    if current:
        return str(current)
    candidate = (
        datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
        + "-" + os.urandom(4).hex()
    )
    redis_command(url, password, "SET", generation_key, candidate, "NX")
    current = redis_command(url, password, "GET", generation_key)
    if not current:
        raise RedisError("Unable to initialize Redis run generation")
    return str(current)


def fields_to_dict(fields) -> dict[str, str]:
    if not isinstance(fields, list):
        raise RedisError(f"Invalid stream field list: {fields!r}")
    return {str(fields[index]): str(fields[index + 1]) for index in range(0, len(fields), 2)}


def safe_token(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in str(value or "")
    ).strip("_") or "default"


TERMINAL_VIDEO_CHECKPOINT_STATUSES = {
    "completed", "dead_letter", "no_content", "not_applicable",
    "skipped_unresolved",
}
DEFERRED_VIDEO_CHECKPOINT_STATUSES = {
    "completed_metadata", "retry_pending", "pending", "running", "partial_review",
}

DEFER_VIDEO_RETRY_LUA = """
if redis.call('SADD', KEYS[1], ARGV[1]) == 1 then
  return redis.call('XADD', KEYS[2], '*', 'retry_id', ARGV[1], 'payload', ARGV[2])
end
return 'already-staged'
""".strip()


def retry_payload_has_identity(payload: dict[str, Any]) -> bool:
    """Reject synthetic index-only failures from the durable video queue."""
    row = payload.get("row") or {}
    return bool(
        str(payload.get("article_key") or "").strip()
        or str(row.get("url") or "").strip()
        or str(row.get("title") or payload.get("title") or "").strip()
        or str(payload.get("raw_card_text") or "").strip()
    )


def stage_video_retry(
    args, item: dict[str, Any], fingerprint: str, checkpoint: dict[str, Any],
) -> str:
    """Persist one child-video retry before acknowledging its keyword scan."""
    retry_id = hashlib.sha256(
        f"{item.get('task_id', '')}|{fingerprint}".encode("utf-8")
    ).hexdigest()
    payload = {
        "retry_id": retry_id,
        "task_id": item.get("task_id"),
        "source_task_id": item.get("task_id"),
        "topic": item.get("topic"),
        "keyword": item.get("keyword"),
        "fingerprint": fingerprint,
        "queue": item.get("queue"),
        "checkpoint": checkpoint,
        "stagedAt": datetime.now().astimezone().isoformat(),
    }
    retry_seeded_key = getattr(args, "retry_seeded_key", f"{args.prefix}:video-retry-seeded")
    retry_stream = getattr(args, "retry_stream", f"{args.prefix}:video-retry")
    return str(redis_command(
        args.redis_url, args.redis_password,
        "EVAL", DEFER_VIDEO_RETRY_LUA, 2,
        retry_seeded_key, retry_stream, retry_id,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    ))


def checkpoint_completion_guard(args, item: dict[str, Any]) -> dict[str, Any]:
    """Stage child retries durably before allowing the keyword-level XACK.

    A finished annual scan and an incomplete child video are different units
    of work.  The former belongs to the primary keyword stream; the latter is
    atomically de-duplicated into ``video-retry``.  Only after every recognized
    child state has been persisted may the primary message be acknowledged.

    An empty hash remains valid: a correctly exhausted keyword may genuinely
    have no matching videos. Unknown/malformed non-empty states fail closed.
    """
    task_token = safe_token(item.get("task_id", ""))
    state_key = f"{args.prefix}:video-state:{task_token}"
    raw = redis_command(
        args.redis_url, args.redis_password, "HGETALL", state_key,
    ) or []
    values = fields_to_dict(raw)
    statuses: Counter[str] = Counter()
    malformed = 0
    invalid_deferred_identity = 0
    deferred: list[tuple[str, dict[str, Any]]] = []
    for fingerprint, encoded in values.items():
        try:
            payload = json.loads(encoded)
            status = str(payload.get("status") or "unknown")
            statuses[status] += 1
            if status in DEFERRED_VIDEO_CHECKPOINT_STATUSES:
                if retry_payload_has_identity(payload):
                    deferred.append((fingerprint, payload))
                else:
                    # This is an unreachable UI index, not a video. Do not
                    # consume ASR retries or create an empty dead-letter row.
                    invalid_deferred_identity += 1
        except (TypeError, ValueError, json.JSONDecodeError):
            malformed += 1
    blocking = {
        status: count for status, count in statuses.items()
        if status not in TERMINAL_VIDEO_CHECKPOINT_STATUSES
        and status not in DEFERRED_VIDEO_CHECKPOINT_STATUSES
    }
    if malformed:
        blocking["invalid_json"] = malformed
    staged = []
    if not blocking:
        for fingerprint, payload in deferred:
            stage_video_retry(args, item, fingerprint, payload)
            staged.append(fingerprint)
    return {
        "ok": not blocking,
        "checkpointCount": len(values),
        "statuses": dict(statuses),
        "blocking": blocking,
        "deferredCount": len(deferred),
        "deferredStaged": len(staged),
        "invalidDeferredIdentitySkipped": invalid_deferred_identity,
    }


def video_retry_completion_guard(args, item: dict[str, Any]) -> dict[str, Any]:
    """A child retry is complete only when its exact fingerprint is terminal."""
    task_token = safe_token(item.get("source_task_id") or item.get("task_id", ""))
    state_key = f"{args.prefix}:video-state:{task_token}"
    fingerprint = str(item.get("fingerprint") or "")
    if not fingerprint:
        return {"ok": False, "status": "missing_fingerprint"}
    encoded = redis_command(
        args.redis_url, args.redis_password, "HGET", state_key, fingerprint,
    )
    if not encoded:
        return {"ok": False, "status": "missing_checkpoint"}
    try:
        payload = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {"ok": False, "status": "invalid_json"}
    status = str(payload.get("status") or "unknown")
    contaminated = has_internal_prompt((payload.get('row') or {}).get('video_content'))
    return {
        # A dead letter is evidence of failure, not a disposition. It must
        # pass the shared finite-budget/evidence gate before acknowledgment.
        "ok": status == "skipped_unresolved" or (
            status in TERMINAL_VIDEO_CHECKPOINT_STATUSES and status != "dead_letter" and not contaminated
        ),
        "status": status,
        "retryCount": int(payload.get("retry_count") or 0),
        "asrStatus": payload.get("asr_status"),
        "reason": payload.get("last_error"),
        "checkpointUpdatedAt": payload.get("updated_at"),
        "accepted": status=="completed" and not contaminated,
        "skipped": status in {"dead_letter","skipped_unresolved"},
        "disposition": payload.get("disposition"),
    }


def refresh_parent_keyword_status(args, item: dict[str, Any]) -> dict[str, Any]:
    """Recompute a keyword's final state after one exact-video retry.

    The primary stream may be acknowledged after every incomplete child has
    been durably staged, but that is not the same as business completion.  Keep
    the parent visibly non-final while any child is pending/running, and expose
    dead letters instead of silently converting them into ``completed``.
    """
    task_token = safe_token(item.get("source_task_id") or item.get("task_id", ""))
    state_key = f"{args.prefix}:video-state:{task_token}"
    raw = redis_command(
        args.redis_url, args.redis_password, "HGETALL", state_key,
    ) or []
    values = fields_to_dict(raw)
    statuses: Counter[str] = Counter()
    malformed = 0
    for encoded in values.values():
        try:
            payload = json.loads(encoded)
            statuses[str(payload.get("status") or "unknown")] += 1
        except (TypeError, ValueError, json.JSONDecodeError):
            malformed += 1
    unresolved = malformed + sum(
        count for status, count in statuses.items()
        if status not in TERMINAL_VIDEO_CHECKPOINT_STATUSES
    )
    dead_letters = int(statuses.get("dead_letter", 0))
    parent_raw=redis_command(args.redis_url,args.redis_password,"HGET",
        getattr(args,"status_key",args.prefix+":status"),item.get("source_task_id") or item["task_id"])
    try:
        prior=json.loads(parent_raw) if parent_raw else {}
    except (TypeError,ValueError):
        prior={}
    # Legacy aggregate status is not proof that the annual scan finished.
    scan_complete=prior.get("scanCompleted") is True
    if not scan_complete:
        parent_status="retry_pending"
    elif unresolved:
        parent_status = "completed_with_deferred_retries"
    elif statuses.get("skipped_unresolved"):
        parent_status = "completed_with_skips"
    elif dead_letters:
        parent_status = "completed_with_dead_letters"
    else:
        parent_status = "completed"
    detail = {
        "videoCheckpointCount": len(values),
        "videoCheckpointStatuses": dict(statuses),
        "unresolvedVideoCount": int(unresolved),
        "deadLetterCount": dead_letters,
        "skippedVideoCount": int(statuses.get("skipped_unresolved",0)),
        "scanCompleted": scan_complete,
    }
    update_remote_status(args, item, parent_status, detail)
    return {"status": parent_status, **detail}


def decode_message(entry):
    message_id, fields = entry
    values = fields_to_dict(fields)
    return str(message_id), json.loads(values["payload"])


def auto_claim(url: str, password: str | None, stream: str, group: str, consumer: str, idle_ms: int):
    reply = redis_command(
        url, password, "XAUTOCLAIM", stream, group, consumer, idle_ms, "0-0", "COUNT", 1
    )
    entries = reply[1] if isinstance(reply, list) and len(reply) > 1 else []
    return decode_message(entries[0]) if entries else None


def read_new(url: str, password: str | None, stream: str, group: str, consumer: str, block_ms: int):
    reply = redis_command(
        url,
        password,
        "XREADGROUP",
        "GROUP",
        group,
        consumer,
        "COUNT",
        1,
        "BLOCK",
        block_ms,
        "STREAMS",
        stream,
        ">",
        timeout=max(15.0, block_ms / 1000 + 10),
    )
    if not reply:
        return None
    entries = reply[0][1]
    return decode_message(entries[0]) if entries else None


def pending_count(url: str, password: str | None, stream: str, group: str) -> int:
    reply = redis_command(url, password, "XPENDING", stream, group)
    return int(reply[0]) if reply else 0


def group_lag(url: str, password: str | None, stream: str, group: str) -> int:
    """Return unread group lag; unknown/missing lag fails closed as one item."""
    reply = redis_command(url, password, "XINFO", "GROUPS", stream) or []
    for raw_group in reply:
        values = fields_to_dict(raw_group)
        if values.get("name") != group:
            continue
        lag = values.get("lag")
        if lag in (None, 'None', 'null'):
            # Redis can lose entries-read/lag after historical group changes.
            # Probe actual entries after the last delivered ID, read-only.
            # Do not let unknown lag permanently block a drained retry queue.
            last_id = values.get('last-delivered-id')
            if not last_id:
                return 1
            unread = redis_command(url, password, 'XRANGE', stream, '(' + str(last_id), '+', 'COUNT', 1)
            return 1 if unread else 0
        return max(0, int(lag))
    return 1


def write_json(path: Path, value: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def redact_log_text(args, value: Any) -> str:
    """Remove credentials before a worker line is copied to central Redis."""
    text = str(value or "").rstrip("\r\n")
    secrets = {
        str(getattr(args, "redis_password", "") or ""),
        str(os.environ.get("MYSQL_PASSWORD") or ""),
    }
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        text = text.replace(secret, "***")
    return text


def publish_remote_log(
    args,
    event: str,
    *,
    level: str = "info",
    message: str = "",
    item: dict[str, Any] | None = None,
    task_kind: str = "",
    message_id: str = "",
    extra: dict[str, Any] | None = None,
) -> bool:
    """Append one bounded, credential-redacted event to the run log stream.

    Central logging is deliberately best-effort: a temporary logging failure
    must never stop collection or invalidate a task lease.
    """
    stream = str(getattr(args, "log_stream", "") or "")
    if not stream:
        return False
    task = item or {}
    fields: dict[str, Any] = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "consumer": str(getattr(args, "consumer", "") or ""),
        "computer": socket.gethostname(),
        "worker": str(getattr(args, "worker_root", Path("worker")).name),
        "event": event,
        "level": level,
        "taskKind": task_kind,
        "messageId": message_id,
        "taskId": str(task.get("task_id") or ""),
        "topic": str(task.get("topic") or ""),
        "keyword": str(task.get("keyword") or ""),
        "message": redact_log_text(args, message),
    }
    for key, value in (extra or {}).items():
        fields[str(key)] = redact_log_text(args, value)
    command: list[Any] = [
        "XADD", stream, "MAXLEN", "~",
        max(1000, int(getattr(args, "log_maxlen", 200000))), "*",
    ]
    for key, value in fields.items():
        command.extend((key, value))
    try:
        redis_command(args.redis_url, args.redis_password, *command, timeout=5.0)
        return True
    except Exception:
        return False


def decode_child_log_line(raw: bytes) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding).rstrip("\r\n")
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace").rstrip("\r\n")


def forward_child_output(
    process: subprocess.Popen,
    log_lines: thread_queue.Queue,
) -> None:
    """Drain child output immediately; remote logging must never block RPA."""
    try:
        assert process.stdout is not None
        for raw in iter(process.stdout.readline, b""):
            line = decode_child_log_line(raw)
            print(line, flush=True)
            if line:
                try:
                    log_lines.put_nowait(line)
                except thread_queue.Full:
                    # Local transcript remains authoritative if Redis logging
                    # cannot keep up; never back-pressure the collector pipe.
                    pass
    except Exception:
        pass


def publish_child_output(
    log_lines: thread_queue.Queue,
    args,
    item: dict[str, Any],
    task_kind: str,
    message_id: str,
) -> None:
    while True:
        line = log_lines.get()
        if line is None:
            return
        publish_remote_log(
            args, "worker_output", message=line, item=item,
            task_kind=task_kind, message_id=message_id,
        )


def stop_child_log_publisher(log_lines: thread_queue.Queue) -> None:
    try:
        log_lines.put_nowait(None)
    except thread_queue.Full:
        try:
            log_lines.get_nowait()
        except thread_queue.Empty:
            pass
        try:
            log_lines.put_nowait(None)
        except thread_queue.Full:
            pass


def worker_script_for_task_kind(task_kind: str) -> str:
    if task_kind == "video_retry":
        return "run-asr-backfill.ps1"
    if task_kind == "primary":
        return "run-worker.ps1"
    raise ValueError(f"Unsupported Redis task kind: {task_kind}")


class PersistentAsrService:
    """One node-local model process reused by all video-retry children."""

    def __init__(self, args) -> None:
        self.args = args
        self.process: subprocess.Popen | None = None
        self.host = "127.0.0.1"
        self.port: int | None = None
        self.token = secrets.token_urlsafe(32)
        self.instance: str | None = None
        self.lock = threading.Lock()
        self.output_thread: threading.Thread | None = None
        self.start_count = 0
        atexit.register(self.stop)

    def _drain_output(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        for raw in process.stdout:
            line = raw.rstrip("\r\n")
            if line:
                print(json.dumps({
                    "event": "persistent_asr_service_output",
                    "message": line,
                }, ensure_ascii=False), flush=True)

    def _wait_ready(self, timeout_seconds: float) -> dict[str, Any]:
        process = self.process
        if process is None or process.stdout is None:
            raise RuntimeError("persistent ASR service process was not created")
        results: thread_queue.Queue = thread_queue.Queue()

        def read_first_line() -> None:
            try:
                # Download/cache diagnostics may precede the ready handshake.
                for raw in process.stdout:
                    try:
                        payload = json.loads(raw.strip())
                    except json.JSONDecodeError:
                        payload = {}
                    if payload.get("type") in ("ready", "fatal"):
                        results.put(raw)
                        return
                    if raw.strip():
                        print(json.dumps({
                            "event": "persistent_asr_service_output",
                            "message": raw.strip(),
                        }, ensure_ascii=False), flush=True)
                results.put("")
            except Exception as error:
                results.put(error)

        reader = threading.Thread(target=read_first_line, daemon=True)
        reader.start()
        try:
            value = results.get(timeout=timeout_seconds)
        except thread_queue.Empty as exc:
            raise TimeoutError(
                f"persistent ASR model did not become ready within {timeout_seconds:.0f}s"
            ) from exc
        if isinstance(value, Exception):
            raise value
        if not value:
            raise RuntimeError(
                f"persistent ASR service exited before ready; exitCode={process.poll()}"
            )
        try:
            payload = json.loads(str(value).strip())
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"persistent ASR service returned invalid startup data: {value!r}"
            ) from exc
        if payload.get("type") != "ready":
            raise RuntimeError(
                str(payload.get("error") or f"persistent ASR startup failed: {payload}")
            )
        return payload

    def ensure_started(self) -> dict[str, str]:
        with self.lock:
            if self.process is not None and self.process.poll() is None and self.port:
                return self.environment()
            self.stop()
            config = self.args.common / "collector_config.json"
            worker = self.args.common / "src" / "asr-worker.py"
            child_env = os.environ.copy()
            child_env["PYTHONUTF8"] = "1"
            child_env["PYTHONIOENCODING"] = "utf-8"
            child_env["WECHAT_PERSISTENT_ASR_TOKEN"] = self.token
            command = [
                sys.executable,
                str(worker),
                "--config", str(config),
                "--host", self.host,
                "--port", "0",
                "--parent-pid", str(os.getpid()),
            ]
            print(json.dumps({
                "event": "persistent_asr_service_starting",
                "model": json.loads(config.read_text(encoding="utf-8-sig")).get("client_asr_model", "small"),
                "worker": str(worker),
                "startCount": self.start_count + 1,
            }, ensure_ascii=False), flush=True)
            self.process = subprocess.Popen(
                command,
                env=child_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            timeout = max(
                60.0,
                float(os.environ.get("PERSISTENT_ASR_STARTUP_TIMEOUT_SECONDS", "900")),
            )
            try:
                ready = self._wait_ready(timeout)
            except Exception:
                self.stop()
                raise
            self.host = str(ready.get("host") or self.host)
            self.port = int(ready["port"])
            self.instance = str(ready.get("instance") or "")
            self.start_count += 1
            print(json.dumps({
                "event": "persistent_asr_service_ready",
                "host": self.host,
                "port": self.port,
                "pid": ready.get("pid"),
                "model": ready.get("model"),
                "device": ready.get("device"),
                "computeType": ready.get("compute_type"),
                "startCount": self.start_count,
            }, ensure_ascii=False), flush=True)
            self.output_thread = threading.Thread(
                target=self._drain_output,
                name="persistent-asr-output",
                daemon=True,
            )
            self.output_thread.start()
            return self.environment()

    def environment(self) -> dict[str, str]:
        if not self.port:
            return {}
        return {
            "WECHAT_PERSISTENT_ASR_HOST": self.host,
            "WECHAT_PERSISTENT_ASR_PORT": str(self.port),
            "WECHAT_PERSISTENT_ASR_TOKEN": self.token,
            "WECHAT_PERSISTENT_ASR_INSTANCE": str(self.instance or ""),
        }

    def stop(self) -> None:
        process = self.process
        self.process = None
        self.port = None
        self.instance = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


class LeaseHeartbeat(threading.Thread):
    def __init__(
        self, url, password, stream, group, consumer, message_id,
        interval_seconds, failure_limit,
    ):
        super().__init__(daemon=True)
        self.url = url
        self.password = password
        self.stream = stream
        self.group = group
        self.consumer = consumer
        self.message_id = message_id
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()
        self.lease_lost = threading.Event()
        self.last_error: str | None = None
        self.failure_limit = max(1, int(failure_limit))
        self.consecutive_failures = 0

    def run(self):
        while not self.stop_event.wait(self.interval_seconds):
            try:
                redis_command(
                    self.url,
                    self.password,
                    "XCLAIM",
                    self.stream,
                    self.group,
                    self.consumer,
                    0,
                    self.message_id,
                    "JUSTID",
                )
                self.consecutive_failures = 0
                self.last_error = None
            except Exception as error:  # collection should not be killed by a brief Redis outage
                self.last_error = str(error)
                self.consecutive_failures += 1
                print(json.dumps({
                    "event": "redis_heartbeat_failed",
                    "error": self.last_error,
                    "consecutiveFailures": self.consecutive_failures,
                    "failureLimit": self.failure_limit,
                }, ensure_ascii=False), flush=True)
                if self.consecutive_failures >= self.failure_limit:
                    self.lease_lost.set()
                    return

    def stop(self):
        self.stop_event.set()


def run_task(
    args, message_id: str, item: dict[str, Any], state_path: Path,
    *, lease_stream: str | None = None, lease_group: str | None = None,
    task_kind: str = "primary",
    asr_service: PersistentAsrService | None = None,
) -> int:
    task_queue_path = state_path.parent / "redis-current-task.json"
    write_json(task_queue_path, item["queue"])
    write_json(state_path, {
        "status": "running",
        "messageId": message_id,
        "taskId": item["task_id"],
        "topic": item["topic"],
        "keyword": item["keyword"],
        "consumer": args.consumer,
        "startedAt": datetime.now().astimezone().isoformat(),
        "taskKind": task_kind,
        "leaseStream": lease_stream or args.stream,
        "leaseGroup": lease_group or args.group,
    })
    env = os.environ.copy()
    env["WECHAT_QUEUE_FILE"] = str(task_queue_path)
    env["WECHAT_WORKER_ROOT"] = str(args.worker_root)
    env["WECHAT_REDIS_TASK_ID"] = str(item.get("source_task_id") or item["task_id"])
    env["WECHAT_REDIS_TOPIC"] = str(item["topic"])
    env["WECHAT_REDIS_KEYWORD"] = str(item["keyword"])
    env["WECHAT_REDIS_RUN_ID"] = str(args.run_id)
    env["WECHAT_REDIS_CONSUMER"] = str(args.consumer)
    env["WECHAT_WORKER_ID"] = str(args.worker_root.name)
    env["WECHAT_REDIS_GENERATION"] = str(args.run_generation)
    # The scheduler accepts Redis connectivity through command-line options,
    # while the collector/checkpoint store reads environment variables.  Always
    # bridge the resolved values into the child so dedicated ASR nodes can
    # hydrate cross-machine checkpoints even when REDIS_URL was not defined in
    # the parent shell.
    env["REDIS_URL"] = str(args.redis_url)
    if args.redis_password:
        env["REDIS_PASSWORD"] = str(args.redis_password)
    else:
        env.pop("REDIS_PASSWORD", None)
    # RedisVideoCheckpointStore reads REDIS_RUN_ID.  Passing only the
    # WECHAT_-prefixed audit variable made an ASR consumer hydrate a different
    # namespace whenever the scheduler --run-id was not already present in
    # its parent environment.
    env["REDIS_RUN_ID"] = str(args.run_id)
    env["WECHAT_REDIS_STATE_SCOPE"] = f"{safe_token(args.run_id)}-{safe_token(args.run_generation)}"
    if task_kind == "video_retry":
        env['WECHAT_FORCE_ASR'] = '1'
        env['WECHAT_RETRY_OBSERVATION_RUN_ID'] = str(item.get('retryObservationRunId') or '')
        env["WECHAT_REDIS_VIDEO_FINGERPRINT"] = str(item.get("fingerprint") or "")
        checkpoint = item.get("checkpoint") or {}
        env["WECHAT_REDIS_VIDEO_ARTICLE_KEY"] = str(
            checkpoint.get("article_key") or ""
        )
        env["WECHAT_REDIS_VIDEO_RESULT_INDEX"] = str(
            checkpoint.get("result_index")
            if checkpoint.get("result_index") is not None else ""
        )
    else:
        env.pop('WECHAT_FORCE_ASR', None)
        env.pop("WECHAT_REDIS_VIDEO_FINGERPRINT", None)
        env.pop("WECHAT_REDIS_VIDEO_ARTICLE_KEY", None)
        env.pop("WECHAT_REDIS_VIDEO_RESULT_INDEX", None)
    # Primary work records complete audio during the first detail visit and
    # transcribes through the node-local persistent service.  The independent
    # retry stream is reserved for exact videos whose recording/transcript did
    # not reach a terminal checkpoint.
    script = worker_script_for_task_kind(task_kind)
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(args.common / script),
        "-Mode",
        "run",
    ]
    heartbeat = LeaseHeartbeat(
        args.redis_url,
        args.redis_password,
        lease_stream or args.stream,
        lease_group or args.group,
        args.consumer,
        message_id,
        args.heartbeat_seconds,
        args.heartbeat_failure_limit,
    )
    heartbeat.start()
    publish_remote_log(
        args, "task_started", item=item, task_kind=task_kind,
        message_id=message_id,
    )
    log_lines: thread_queue.Queue = thread_queue.Queue(maxsize=2000)
    output_thread: threading.Thread | None = None
    publisher_thread: threading.Thread | None = None
    exit_code = 1
    try:
        if (args.worker_root / ".state" / "stop.requested").exists():
            return 130
        if task_kind in {"primary", "video_retry"} and asr_service is not None:
            try:
                service_environment = asr_service.ensure_started()
                env.update(service_environment)
                print(json.dumps({
                    "event": "persistent_asr_service_attached_to_task",
                    "taskId": item["task_id"],
                    "taskKind": task_kind,
                    "instance": service_environment.get(
                        "WECHAT_PERSISTENT_ASR_INSTANCE", ""
                    ),
                    "port": service_environment.get(
                        "WECHAT_PERSISTENT_ASR_PORT", ""
                    ),
                }, ensure_ascii=False), flush=True)
            except Exception as service_error:
                # The child keeps the configured in-process ASR fallback.
                # A service startup failure may cost one cold load, but cannot
                # prevent this Redis task from completing.
                print(json.dumps({
                    "event": "persistent_asr_service_unavailable_fallback_local",
                    "taskId": item["task_id"],
                    "error": str(service_error),
                }, ensure_ascii=False), flush=True)
        if (args.worker_root / ".state" / "stop.requested").exists():
            return 130
        process = subprocess.Popen(
            command,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
        output_thread = threading.Thread(
            target=forward_child_output,
            args=(process, log_lines),
            daemon=True,
        )
        publisher_thread = threading.Thread(
            target=publish_child_output,
            args=(log_lines, args, item, task_kind, message_id),
            daemon=True,
        )
        output_thread.start()
        publisher_thread.start()
        while process.poll() is None:
            if heartbeat.lease_lost.is_set():
                stop_file = args.worker_root / ".state" / "stop.requested"
                stop_file.parent.mkdir(parents=True, exist_ok=True)
                if not stop_file.exists():
                    stop_file.write_text(
                        datetime.now().astimezone().isoformat(), encoding="utf-8"
                    )
                    print(json.dumps({
                        "event": "redis_lease_lost_safe_stop_requested",
                        "taskId": item["task_id"],
                        "error": heartbeat.last_error,
                    }, ensure_ascii=False), flush=True)
            time.sleep(1)
        if output_thread is not None:
            output_thread.join(timeout=10)
        stop_child_log_publisher(log_lines)
        if publisher_thread is not None:
            publisher_thread.join(timeout=2)
        exit_code = int(process.returncode or 0)
        publish_remote_log(
            args,
            "task_finished",
            level="info" if exit_code == 0 else "error",
            message=f"exitCode={exit_code}",
            item=item,
            task_kind=task_kind,
            message_id=message_id,
            extra={"exitCode": exit_code},
        )
        return 75 if heartbeat.lease_lost.is_set() and exit_code == 0 else exit_code
    finally:
        if output_thread is not None and output_thread.is_alive():
            output_thread.join(timeout=2)
        if publisher_thread is not None and publisher_thread.is_alive():
            stop_child_log_publisher(log_lines)
        heartbeat.stop()
        heartbeat.join(timeout=5)


def update_remote_status(args, item, status: str, detail: dict[str, Any]):
    value = {
        "status": status,
        "worker": getattr(args, "consumer", "status-reconciler"),
        "topic": item["topic"],
        "keyword": item["keyword"],
        "updatedAt": datetime.now().astimezone().isoformat(),
        **detail,
    }
    redis_command(
        args.redis_url,
        args.redis_password,
        "HSET",
        getattr(args, "status_key", f"{args.prefix}:status"),
        item["task_id"],
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
    )


def claim_primary_message(args, *, recover_stale_pending: bool):
    """Claim at most one expired pending keyword before reading new work.

    XAUTOCLAIM still honours the lease idle threshold, so a healthy worker's
    active keyword is never stolen.  After one recovery the caller disables
    this branch and continues with never-read keywords.
    """
    if recover_stale_pending:
        message = auto_claim(
            args.redis_url,
            args.redis_password,
            args.stream,
            args.group,
            args.consumer,
            args.reclaim_idle_seconds * 1000,
        )
        if message:
            return message, True
    message = read_new(
        args.redis_url,
        args.redis_password,
        args.stream,
        args.group,
        args.consumer,
        args.block_seconds * 1000,
    )
    if message:
        return message, False
    return auto_claim(
        args.redis_url,
        args.redis_password,
        args.stream,
        args.group,
        args.consumer,
        args.reclaim_idle_seconds * 1000,
    ), False


def run_worker(args) -> int:
    from redis_worker_control import WorkerControl
    stop_requested = threading.Event()
    stop_file = args.worker_root / ".state" / "stop.requested"
    # Clear only the consumed local marker; persistent Redis holds are checked
    # immediately afterwards, before seeding/claiming any task.
    stop_file.parent.mkdir(parents=True, exist_ok=True)
    stop_file.unlink(missing_ok=True)
    control = WorkerControl(args, stop_requested)
    orderly = False
    try:
        control.start()
        if stop_requested.is_set():
            write_json(args.worker_root / ".state" / "redis_worker_status.json", {
                "status": "stopped", "consumer": args.consumer,
                "reason": "redis_remote_stop_hold", "stoppedAt": datetime.now().astimezone().isoformat(),
            })
            orderly = True
            return 130
        result = _run_worker(args, stop_requested, control)
        orderly = True
        return result
    finally:
        control.close(orderly=orderly)


def _run_worker(args, stop_requested, control) -> int:
    # Replay verified telemetry from previous runs, without claiming tasks.
    try:
        from production_output_publisher import flush as flush_output
        output_replay=flush_output(args.worker_root / '.state' / 'production-output', args.redis_url, args.redis_password)
        if output_replay.get('sent') or output_replay.get('deferred'):
            print(json.dumps(output_replay,ensure_ascii=False),flush=True)
    except Exception as output_error:
        print(json.dumps({'event':'production_output_upload_deferred','errorType':type(output_error).__name__},ensure_ascii=False),flush=True)
    queue = json.loads(args.queue.read_text(encoding="utf-8-sig"))
    tasks = flatten_queue(queue)
    ensure_group(args.redis_url, args.redis_password, args.stream, args.group)
    ensure_group(args.redis_url, args.redis_password, args.retry_stream, args.retry_group)
    inserted = seed_tasks(args.redis_url, args.redis_password, args.stream, args.seeded_key, tasks)
    print(json.dumps({
        "event": "redis_queue_ready",
        "stream": args.stream,
        "group": args.group,
        "planned": len(tasks),
        "newlySeeded": inserted,
        "consumer": args.consumer,
    }, ensure_ascii=False), flush=True)
    publish_remote_log(
        args,
        "redis_queue_ready",
        message=f"planned={len(tasks)} newlySeeded={inserted}",
        extra={"planned": len(tasks), "newlySeeded": inserted},
    )

    def request_stop(signum, frame):
        stop_requested.set()
        stop_file = args.worker_root / ".state" / "stop.requested"
        stop_file.parent.mkdir(parents=True, exist_ok=True)
        stop_file.write_text(datetime.now().astimezone().isoformat(), encoding="utf-8")
        print(json.dumps({"event": "redis_worker_safe_stop_requested", "signal": signum}), flush=True)

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    state_path = args.worker_root / ".state" / "redis_worker_status.json"
    stop_file = args.worker_root / ".state" / "stop.requested"
    # The outer wrapper has cleared a consumed local marker and checked the
    # persistent remote hold. Never clear it again here: the control watcher
    # may already have written a new request while the queue was initializing.
    stop_file.parent.mkdir(parents=True, exist_ok=True)
    # Keep programmatic callers/tests created before the role options backward
    # compatible; command-line invocations always receive these from argparse.
    worker_role = getattr(args, "worker_role", "mixed")
    primary_burst = max(1, int(getattr(args, "primary_burst", 3)))
    startup_primary_recovery_remaining = max(
        0, int(getattr(args, "startup_primary_recovery_count", 1))
    )
    asr_service = PersistentAsrService(args)
    # Also release the model if an unexpected scheduler exception occurs.
    try:
        return _worker_loop(args, stop_requested, control, stop_file, state_path,
                            asr_service, worker_role, primary_burst,
                            startup_primary_recovery_remaining)
    finally:
        asr_service.stop()


def _worker_loop(args, stop_requested, control, stop_file, state_path,
                 asr_service, worker_role, primary_burst,
                 startup_primary_recovery_remaining):
    completed = failed = primary_since_retry = skipped = 0

    while not stop_requested.is_set():
        if stop_file.exists():
            stop_requested.set()
            print(json.dumps({
                "event": "redis_worker_safe_stop_observed_before_claim",
                "stopFile": str(stop_file),
            }, ensure_ascii=False), flush=True)
            publish_remote_log(
                args,
                "redis_worker_safe_stop_observed_before_claim",
                message="Safe-stop marker found; no new Redis task will be claimed",
                extra={"stopFile": str(stop_file)},
            )
            break
        task_kind = "primary"
        round_active = False
        retry_stream_in_use, retry_group_in_use = args.retry_stream, args.retry_group
        try:
            # Recheck the durable hold immediately before attempting a claim.
            if control.poll():
                break
            message = None
            from retry_round import claim_round
            round_active, message, round_stream, round_group = claim_round(SimpleNamespace(**globals()), args)
            if round_active:
                task_kind = 'video_retry'
                retry_stream_in_use, retry_group_in_use = round_stream, round_group
                if not message:
                    print(json.dumps({'event':'retry_round_waiting_for_other_workers'}, ensure_ascii=False), flush=True)
                    stop_requested.wait(args.block_seconds)
                    continue
            if (not round_active and worker_role == 'mixed'
                    and getattr(args, 'task_priority', 'balanced') == 'retry_first'):
                from retry_priority import claim_retry_first
                message, hold_primary, priority_detail = claim_retry_first(SimpleNamespace(**globals()), args)
                if message:
                    task_kind = 'video_retry'
                elif hold_primary:
                    write_json(state_path, {
                        'status': 'waiting_retry_backlog', 'consumer': args.consumer,
                        'taskPriority': 'retry_first', 'detail': priority_detail,
                        'updatedAt': datetime.now().astimezone().isoformat(),
                    })
                    # Human-actionable failure, not a fake successful keyword.
                    if getattr(args, '_last_priority_detail', None) != priority_detail:
                        print(json.dumps({'event': 'redis_retry_priority_holding_new_keywords',
                                          **priority_detail}, ensure_ascii=False), flush=True)
                        publish_remote_log(args, 'redis_retry_priority_holding_new_keywords',
                                           extra=priority_detail)
                        args._last_priority_detail = priority_detail
                    stop_requested.wait(max(1, args.block_seconds))
                    continue
            prefer_retry = (
                worker_role == "asr"
                or (
                    worker_role == "mixed"
                    and primary_since_retry >= primary_burst
                )
            )
            # In mixed mode, periodically probe video-retry before the primary
            # stream.  The previous strict primary-first policy starved every
            # ASR task while any unread annual keyword remained.  An operator
            # may also dedicate a machine with REDIS_WORKER_ROLE=asr.
            if prefer_retry and not round_active and not message:
                task_kind = "video_retry"
                message = read_new(
                    args.redis_url, args.redis_password,
                    args.retry_stream, args.retry_group, args.consumer,
                    args.block_seconds * 1000 if worker_role == "asr" else 1,
                )
                if not message:
                    message = auto_claim(
                        args.redis_url, args.redis_password,
                        args.retry_stream, args.retry_group, args.consumer,
                        args.reclaim_idle_seconds * 1000,
                    )
            if not message and worker_role != "asr" and not round_active:
                task_kind = "primary"
                # On startup recover one expired keyword-level retry, then
                # return to never-read keywords.  This gives old failures a
                # bounded chance without letting one bad keyword monopolize
                # all three machines.
                message, recovered_pending = claim_primary_message(
                    args,
                    recover_stale_pending=(startup_primary_recovery_remaining > 0),
                )
                if recovered_pending:
                    startup_primary_recovery_remaining -= 1
                    publish_remote_log(
                        args,
                        "startup_pending_recovered",
                        message="Recovered one expired primary pending task before new work",
                        item=message[1],
                        task_kind="primary",
                        message_id=message[0],
                    )
            if not message and worker_role != "primary" and not prefer_retry and not round_active:
                task_kind = "video_retry"
                message = read_new(
                    args.redis_url, args.redis_password,
                    args.retry_stream, args.retry_group, args.consumer,
                    min(1000, args.block_seconds * 1000),
                )
                if not message:
                    message = auto_claim(
                        args.redis_url, args.redis_password,
                        args.retry_stream, args.retry_group, args.consumer,
                        args.reclaim_idle_seconds * 1000,
                    )
            if not message:
                primary_pending = pending_count(
                    args.redis_url, args.redis_password, args.stream, args.group,
                )
                retry_pending = pending_count(
                    args.redis_url, args.redis_password, args.retry_stream, args.retry_group,
                )
                primary_lag = group_lag(
                    args.redis_url, args.redis_password, args.stream, args.group,
                )
                retry_lag = group_lag(
                    args.redis_url, args.redis_password, args.retry_stream, args.retry_group,
                )
                if (
                    primary_pending == 0 and retry_pending == 0
                    and primary_lag == 0 and retry_lag == 0
                ):
                    write_json(state_path, {
                        "status": "completed",
                        "consumer": args.consumer,
                        "completed": completed,
                        "failedAttempts": failed,
                        "finishedAt": datetime.now().astimezone().isoformat(),
                    })
                    print(json.dumps({
                        "event": "redis_queue_completed",
                        "completed": completed,
                        "failedAttempts": failed,
                    }, ensure_ascii=False), flush=True)
                    asr_service.stop()
                    return 0
                print(json.dumps({
                    "event": "redis_queue_waiting_for_available_task",
                    "primaryPending": primary_pending,
                    "primaryLag": primary_lag,
                    "retryPending": retry_pending,
                    "retryLag": retry_lag,
                }, ensure_ascii=False), flush=True)
                continue
        except Exception as error:
            write_json(state_path, {
                "status": "redis_reconnecting",
                "consumer": args.consumer,
                "error": str(error),
                "updatedAt": datetime.now().astimezone().isoformat(),
            })
            print(json.dumps({
                "event": "redis_scheduler_retry",
                "error": str(error),
                "retryAfterSeconds": args.block_seconds,
            }, ensure_ascii=False), flush=True)
            stop_requested.wait(args.block_seconds)
            continue

        message_id, item = message
        # A command may arrive while XREADGROUP blocks. Preserve ownership as
        # pending; do not launch GUI work or ACK an unfinished claimed message.
        try:
            if control.poll() or stop_file.exists():
                stop_requested.set()
                print(json.dumps({"event": "redis_remote_stop_claim_left_pending",
                                  "messageId": message_id, "taskId": item["task_id"]}), flush=True)
                break
        except Exception as error:
            print(json.dumps({"event": "redis_control_prelaunch_unavailable_left_pending",
                              "errorType": type(error).__name__, "messageId": message_id}), flush=True)
            stop_requested.wait(args.block_seconds)
            continue
        if task_kind == 'video_retry' and not item.get('force_asr'):
            try:
                current_guard = video_retry_completion_guard(args, item)
            except Exception as guard_error:
                print(json.dumps({'event':'retry_preclaim_guard_error_left_pending', 'error':str(guard_error)}, ensure_ascii=False), flush=True)
                stop_requested.wait(args.block_seconds)
                continue
            if current_guard['ok']:
                if round_active:
                    from retry_round import finish_attempt
                    finish_attempt(SimpleNamespace(**globals()), args, message_id, item,
                                   current_guard, retry_stream_in_use, retry_group_in_use)
                else:
                    from video_retry_budget import acknowledge_terminal
                    acknowledge_terminal(SimpleNamespace(**globals()),args,
                        args.retry_stream,args.retry_group,message_id,item)
                print(json.dumps({'event':'retry_terminal_checkpoint_skipped',
                    'taskId':item['task_id'], 'fingerprint':item.get('fingerprint'),
                    'checkpointGuard':current_guard}, ensure_ascii=False), flush=True)
                if current_guard.get("skipped"):
                    skipped+=1
                else:
                    completed+=1
                if args.once:
                    asr_service.stop()
                    return 0
                continue
        if task_kind == "video_retry":
            primary_since_retry = 0
            # Budget is independent of checkpoint retry_count and shared by
            # all nodes. A quality failure remains pending for explicit review,
            # never acknowledged merely to make the queue look empty.
            from video_retry_budget import begin as begin_video_attempt, restore_retry_identity
            try:
                restore_retry_identity(SimpleNamespace(**globals()),args,
                    retry_stream_in_use,retry_group_in_use,message_id,item)
                budget_before_guard=video_retry_completion_guard(args,item)
                from video_no_change import read_checkpoint
                no_change_before=read_checkpoint(SimpleNamespace(**globals()),args,item)
                item['retryObservationRunId']=str(time.time_ns())+'-'+message_id
                video_attempt=begin_video_attempt(SimpleNamespace(**globals()),args,
                    retry_stream_in_use,retry_group_in_use,message_id,item)
            except Exception as error:
                print(json.dumps({"event":"retry_budget_unavailable_left_pending",
                                  "errorType":type(error).__name__}),flush=True)
                asr_service.stop()
                return 4
            if not video_attempt.get("allowed"):
                if video_attempt.get("state")=="blocked":
                    print(json.dumps({"event":"retry_no_progress_blocked_requires_action",
                        "taskId":item["task_id"],"fingerprint":item.get("fingerprint"),
                        "budget":video_attempt},ensure_ascii=False),flush=True)
                    asr_service.stop()
                    return 4
                disposed=False
                try:
                    from video_retry_budget import skip_exhausted
                    skip_exhausted(SimpleNamespace(**globals()),args,retry_stream_in_use,
                        retry_group_in_use,message_id,item)
                    current_guard=video_retry_completion_guard(args,item)
                    if current_guard["ok"]:
                        if round_active:
                            from retry_round import finish_attempt
                            finish_attempt(SimpleNamespace(**globals()),args,message_id,item,
                                current_guard,retry_stream_in_use,retry_group_in_use)
                        else:
                            from video_retry_budget import acknowledge_terminal
                            acknowledge_terminal(SimpleNamespace(**globals()),args,
                                retry_stream_in_use,retry_group_in_use,message_id,item)
                        refresh_parent_keyword_status(args,item)
                        disposed=True
                        skipped+=int(current_guard.get("skipped",False))
                except Exception as error:
                    print(json.dumps({"event":"retry_skip_blocked_left_pending","errorType":type(error).__name__}),flush=True)
                print(json.dumps({"event":"retry_budget_terminal_disposition" if disposed else "retry_skip_blocked_not_completed",
                    "taskId":item["task_id"],"fingerprint":item.get("fingerprint"),
                    "budget":video_attempt},ensure_ascii=False),flush=True)
                if args.once:
                    asr_service.stop()
                    return 0 if disposed else 4
                if not disposed:
                    asr_service.stop()
                    return 4
                stop_requested.wait(args.block_seconds)
                continue
        else:
            primary_since_retry += 1
        print(json.dumps({
            "event": "redis_video_retry_claimed" if task_kind == "video_retry" else "redis_task_claimed",
            "messageId": message_id,
            "taskId": item["task_id"],
            "topic": item["topic"],
            "keyword": item["keyword"],
            "fingerprint": item.get("fingerprint"),
        }, ensure_ascii=False), flush=True)
        publish_remote_log(
            args,
            "redis_video_retry_claimed" if task_kind == "video_retry" else "redis_task_claimed",
            item=item,
            task_kind=task_kind,
            message_id=message_id,
            extra={"fingerprint": item.get("fingerprint") or ""},
        )
        exit_code = run_task(
            args, message_id, item, state_path,
            lease_stream=retry_stream_in_use if task_kind == "video_retry" else args.stream,
            lease_group=retry_group_in_use if task_kind == "video_retry" else args.group,
            task_kind=task_kind,
            asr_service=asr_service,
        )
        safe_stop_observed = stop_file.exists()
        if safe_stop_observed:
            # Finish the current task's checkpoint/retry persistence below,
            # then leave the outer loop.  Do not claim a fresh keyword.
            stop_requested.set()
            print(json.dumps({
                "event": "redis_worker_safe_stop_observed_after_child",
                "taskId": item["task_id"],
                "childExitCode": exit_code,
                "stopFile": str(stop_file),
            }, ensure_ascii=False), flush=True)
            publish_remote_log(
                args,
                "redis_worker_safe_stop_observed_after_child",
                message="Current task returned after safe stop; checkpoints will be finalized before exit",
                item=item,
                task_kind=task_kind,
                message_id=message_id,
                extra={"childExitCode": exit_code, "stopFile": str(stop_file)},
            )
        if task_kind == "video_retry":
            try:
                retry_guard = video_retry_completion_guard(args, item)
            except Exception as error:
                retry_guard = {"ok": False, "status": "guard_error", "error": str(error)}
            from video_retry_budget import finish as finish_video_attempt
            try:
                from video_no_change import seal_no_change, import_confirmed
                no_change=seal_no_change(SimpleNamespace(**globals()),args,
                    retry_stream_in_use,retry_group_in_use,message_id,item,video_attempt,no_change_before,
                    import_ok=import_confirmed(args.worker_root,item),
                    stopped=bool(safe_stop_observed or stop_requested.is_set()))
                if no_change:
                    retry_guard=video_retry_completion_guard(args,item)
                    print(json.dumps({'event':'retry_completed_no_change','taskId':item['task_id'],
                        'fingerprint':item['fingerprint'],'accepted':False},ensure_ascii=False),flush=True)
                if not retry_guard.get("ok") and (
                    safe_stop_observed or stop_requested.is_set()
                    or retry_guard.get("status") in {"guard_error","missing_checkpoint","invalid_json","missing_fingerprint"}
                    or retry_guard.get("checkpointUpdatedAt")==budget_before_guard.get("checkpointUpdatedAt")
                ):
                    retry_guard.update(deferred=True,deferReason="STOP_OR_NO_FRESH_CONTENT_EVIDENCE",
                        cooperativeStop=bool(safe_stop_observed or stop_requested.is_set()))
                retry_budget=finish_video_attempt(SimpleNamespace(**globals()),args,
                    retry_stream_in_use,retry_group_in_use,message_id,item,video_attempt,retry_guard)
                if retry_budget.get("state")=="blocked":
                    print(json.dumps({"event":"retry_no_progress_blocked_requires_action",
                        "taskId":item["task_id"],"fingerprint":item.get("fingerprint"),
                        "budget":retry_budget},ensure_ascii=False),flush=True)
                    asr_service.stop()
                    return 4
                if retry_budget.get("state")=="exhausted":
                    from video_retry_budget import skip_exhausted
                    disposition=skip_exhausted(SimpleNamespace(**globals()),args,
                        retry_stream_in_use,retry_group_in_use,message_id,item)
                    retry_guard=video_retry_completion_guard(args,item)
                    print(json.dumps({"event":"retry_exhausted_skipped_not_success",
                        "taskId":item["task_id"],"fingerprint":item.get("fingerprint"),
                        "disposition":disposition},ensure_ascii=False),flush=True)
            except Exception as error:
                # Fail closed even if the child reports success: replacement
                # ownership must not ACK another node's pending message.
                retry_guard={"ok":False,"status":"budget_finalize_failed","errorType":type(error).__name__}
                retry_budget=None
            if round_active and not safe_stop_observed and not stop_requested.is_set():
                from retry_round import finish_attempt
                finish_attempt(SimpleNamespace(**globals()), args, message_id, item,
                               retry_guard, retry_stream_in_use, retry_group_in_use)
            if retry_guard["ok"]:
                try:
                    if not round_active:
                        from video_retry_budget import acknowledge_terminal
                        acknowledge_terminal(SimpleNamespace(**globals()),args,
                            args.retry_stream,args.retry_group,message_id,item)
                    if retry_guard.get("skipped"):
                        skipped+=1
                    else:
                        completed += 1
                    try:
                        parent_status = refresh_parent_keyword_status(args, item)
                    except Exception as status_error:
                        # The exact video is already terminal and acknowledged.
                        # Leave the previous non-final parent marker intact; a
                        # transient status refresh failure must not replay the
                        # successfully completed video.
                        parent_status = {
                            "status": "refresh_failed",
                            "error": str(status_error),
                        }
                        print(json.dumps({
                            "event": "redis_parent_status_refresh_failed",
                            "taskId": item["task_id"],
                            "error": str(status_error),
                        }, ensure_ascii=False), flush=True)
                    print(json.dumps({
                        "event": "redis_video_retry_acked",
                        "taskId": item["task_id"],
                        "fingerprint": item.get("fingerprint"),
                        "checkpointGuard": retry_guard,
                        "parentStatus": parent_status,
                        "childExitCode": exit_code,
                    }, ensure_ascii=False), flush=True)
                except Exception as error:
                    failed += 1
                    print(json.dumps({
                        "event": "redis_video_retry_ack_failed_left_pending",
                        "taskId": item["task_id"],
                        "error": str(error),
                    }, ensure_ascii=False), flush=True)
            else:
                failed += 1
                print(json.dumps({
                    "event": "redis_video_retry_left_pending",
                    "taskId": item["task_id"],
                    "fingerprint": item.get("fingerprint"),
                    "childExitCode": exit_code,
                    "checkpointGuard": retry_guard,
                    "reclaimAfterSeconds": args.reclaim_idle_seconds,
                }, ensure_ascii=False), flush=True)
            if args.once:
                once_exit = 0 if retry_guard["ok"] else (exit_code or 4)
                write_json(state_path, {
                    "status": "disposed_with_skip_once" if retry_guard.get("skipped") else "completed_once" if retry_guard["ok"] else "retry_pending",
                    "skipped": skipped,
                    "consumer": args.consumer,
                    "completed": completed,
                    "failedAttempts": failed,
                    "taskId": item["task_id"],
                    "fingerprint": item.get("fingerprint"),
                    "checkpointGuard": retry_guard,
                    "finishedAt": datetime.now().astimezone().isoformat(),
                })
                asr_service.stop()
                return once_exit
            continue
        checkpoint_guard = None
        # Persist every already-committed video's follow-up work even when the
        # keyword scan ends partial/failed (most importantly, safe stop).  The
        # old exit-code gate staged ASR only after a fully successful annual
        # scan: salvaged metadata was imported into MySQL with an empty
        # transcript, while no durable video-retry task existed to fill it.
        # The Lua-backed retry seed is idempotent, so later resumes cannot
        # duplicate the child work.  A non-zero child exit still keeps the
        # primary keyword pending; this change does not incorrectly XACK it.
        try:
            checkpoint_guard = checkpoint_completion_guard(args, item)
        except Exception as error:
            # A Redis read failure at the exact commit boundary must never
            # degrade to XACK. Leave the task pending for safe reclamation.
            checkpoint_guard = {
                "ok": False,
                "checkpointCount": None,
                "statuses": {},
                "blocking": {"guard_error": str(error)},
                "deferredCount": 0,
                "deferredStaged": 0,
            }
        if exit_code != 0:
            print(json.dumps({
                "event": "redis_partial_task_video_retries_persisted",
                "taskId": item["task_id"],
                "keyword": item["keyword"],
                "childExitCode": exit_code,
                "checkpointGuard": checkpoint_guard,
                "safeStop": safe_stop_observed,
            }, ensure_ascii=False), flush=True)
        if exit_code == 0:
            if not checkpoint_guard["ok"]:
                exit_code = 4
                print(json.dumps({
                    "event": "redis_task_xack_blocked_incomplete_checkpoints",
                    "taskId": item["task_id"],
                    "keyword": item["keyword"],
                    "checkpointGuard": checkpoint_guard,
                }, ensure_ascii=False), flush=True)
        if exit_code == 0:
            try:
                redis_command(args.redis_url, args.redis_password, "XACK", args.stream, args.group, message_id)
                deferred_count = int((checkpoint_guard or {}).get("deferredCount") or 0)
                completion_status = (
                    "completed_with_deferred_retries" if deferred_count else "completed"
                )
                if not deferred_count and any((checkpoint_guard or {}).get("statuses",{}).get(s) for s in ("dead_letter","skipped_unresolved")):
                    completion_status="completed_with_skips"
                update_remote_status(args, item, completion_status, {
                    "scanCompleted": True,
                    "messageId": message_id,
                    "checkpointGuard": checkpoint_guard,
                })
                if completion_status=="completed_with_skips":
                    skipped+=1
                else:
                    completed += 1
                print(json.dumps({
                    "event": "redis_task_acked",
                    "taskId": item["task_id"],
                    "deferredVideoRetries": deferred_count,
                }, ensure_ascii=False), flush=True)
            except Exception as error:
                failed += 1
                print(json.dumps({
                    "event": "redis_task_ack_failed_left_pending",
                    "taskId": item["task_id"],
                    "error": str(error),
                }, ensure_ascii=False), flush=True)
        else:
            failed += 1
            try:
                update_remote_status(args, item, "retry_pending", {
                    "scanCompleted": False,
                    "messageId": message_id,
                    "exitCode": exit_code,
                    "checkpointGuard": checkpoint_guard,
                })
            except Exception as error:
                print(json.dumps({
                    "event": "redis_retry_status_update_failed",
                    "taskId": item["task_id"],
                    "error": str(error),
                }, ensure_ascii=False), flush=True)
            print(json.dumps({
                "event": "redis_task_left_pending",
                "taskId": item["task_id"],
                "exitCode": exit_code,
                "reclaimAfterSeconds": args.reclaim_idle_seconds,
            }, ensure_ascii=False), flush=True)
        if args.once:
            write_json(state_path, {
                "status": "completed_once" if exit_code == 0 else "retry_pending",
                "consumer": args.consumer,
                "completed": completed,
                "failedAttempts": failed,
                "taskId": item["task_id"],
                "exitCode": exit_code,
                "finishedAt": datetime.now().astimezone().isoformat(),
            })
            asr_service.stop()
            return exit_code

    write_json(state_path, {
        "status": "stopped",
        "consumer": args.consumer,
        "completed": completed,
        "skipped": skipped,
        "failedAttempts": failed,
        "stoppedAt": datetime.now().astimezone().isoformat(),
    })
    publish_remote_log(
        args,
        "redis_worker_stopped",
        message="Redis worker stopped safely",
        extra={"completed": completed, "failedAttempts": failed},
    )
    asr_service.stop()
    return 130


def build_parser():
    parser = argparse.ArgumentParser(description="Redis Streams scheduler for WeChat Channels RPA")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="validate and print the flattened queue without Redis")
    plan.add_argument("--queue", type=Path, required=True)

    run = sub.add_parser("run", help="seed, claim and execute tasks")
    run.add_argument("--queue", type=Path, required=True)
    run.add_argument("--common", type=Path, required=True)
    run.add_argument("--worker-root", type=Path, required=True)
    run.add_argument("--redis-url", default=os.environ.get("REDIS_URL", ""))
    run.add_argument("--run-id", default=os.environ.get("REDIS_RUN_ID", "20260926-prod-01"))
    run.add_argument("--group", default=os.environ.get("REDIS_GROUP", "channels-workers"))
    run.add_argument("--consumer", default=os.environ.get("REDIS_CONSUMER", ""))
    run.add_argument("--reclaim-idle-seconds", type=int, default=int(os.environ.get("REDIS_RECLAIM_IDLE_SECONDS", "300")))
    run.add_argument("--video-retry-max-attempts",type=int,default=3)
    run.add_argument("--heartbeat-seconds", type=int, default=int(os.environ.get("REDIS_HEARTBEAT_SECONDS", "30")))
    run.add_argument("--heartbeat-failure-limit", type=int, default=int(os.environ.get("REDIS_HEARTBEAT_FAILURE_LIMIT", "3")))
    run.add_argument("--block-seconds", type=int, default=5)
    run.add_argument('--task-priority', choices=('retry_first', 'balanced'),
                     default=os.environ.get('REDIS_TASK_PRIORITY', 'retry_first'),
                     help='mixed: retry_first blocks new keywords while retries/checkpoint exceptions remain')
    run.add_argument(
        "--worker-role", choices=("mixed", "primary", "asr"),
        default=os.environ.get("REDIS_WORKER_ROLE", "mixed"),
        help="mixed=fair primary/ASR scheduling; primary=keyword only; asr=video-retry only",
    )
    run.add_argument(
        "--primary-burst", type=int,
        default=max(1, int(os.environ.get("REDIS_PRIMARY_BURST", "3"))),
        help="mixed mode: process at most this many primary tasks before probing video-retry",
    )
    run.add_argument(
        "--startup-primary-recovery-count", type=int,
        default=max(0, int(os.environ.get("REDIS_STARTUP_PRIMARY_RECOVERY_COUNT", "1"))),
        help="recover this many expired primary pending tasks before continuing new keywords",
    )
    run.add_argument(
        "--log-maxlen", type=int,
        default=max(1000, int(os.environ.get("REDIS_LOG_MAXLEN", "200000"))),
        help="approximate maximum number of centralized Redis log events retained per run",
    )
    run.add_argument("--once", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    queue = json.loads(args.queue.read_text(encoding="utf-8-sig"))
    tasks = flatten_queue(queue)
    if args.command == "plan":
        pairs = [(item["topic"], item["keyword"]) for item in tasks]
        duplicates = len(pairs) - len(set(pairs))
        print(json.dumps({
            "tasks": len(tasks),
            "duplicates": duplicates,
            "topics": {topic: sum(1 for item in tasks if item["topic"] == topic) for topic in sorted({item["topic"] for item in tasks})},
        }, ensure_ascii=False, indent=2))
        return 0 if duplicates == 0 else 2

    if not args.redis_url:
        raise SystemExit("REDIS_URL is required, for example redis://127.0.0.1:6379/0")
    if args.video_retry_max_attempts < 1:
        raise SystemExit("--video-retry-max-attempts must be positive")
    args.redis_password = os.environ.get("REDIS_PASSWORD") or None
    args.common = args.common.resolve()
    args.worker_root = args.worker_root.resolve()
    safe_run_id = safe_token(args.run_id)
    prefix = f"wechat:channels:{safe_run_id}"
    args.prefix = prefix
    args.stream = f"{prefix}:tasks"
    args.seeded_key = f"{prefix}:seeded"
    args.status_key = f"{prefix}:status"
    args.log_stream = f"{prefix}:logs"
    args.retry_stream = f"{prefix}:video-retry"
    args.retry_seeded_key = f"{prefix}:video-retry-seeded"
    args.retry_group = f"{args.group}-video-retry"
    args.run_generation = ensure_run_generation(
        args.redis_url, args.redis_password, prefix,
    )
    if not args.consumer:
        args.consumer = f"{socket.gethostname()}-{args.worker_root.name}-{os.getpid()}"
    return run_worker(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RedisError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"event": "redis_worker_error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
