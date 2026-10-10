#!/usr/bin/env python3
"""Persist distributed Channels worker logs from Redis onto the dispatcher PC."""

from __future__ import annotations

import argparse
import json
import msvcrt
import os
import re
import socket
import ssl
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


class RedisError(RuntimeError):
    pass


class RedisConnection:
    """Small RESP client kept self-contained for the portable Python runtime."""

    def __init__(self, url: str, password: str | None = None, timeout: float = 15.0):
        parsed = urlparse(url)
        if parsed.scheme not in {"redis", "rediss"}:
            raise ValueError("REDIS_URL must start with redis:// or rediss://")
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 6379
        self.db = int((parsed.path or "/0").strip("/") or 0)
        self.username = unquote(parsed.username) if parsed.username else None
        self.password = password or (unquote(parsed.password) if parsed.password else None)
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
            self._command("AUTH", self.username, self.password) if self.username else self._command("AUTH", self.password)
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
            return None if count < 0 else [self._read() for _ in range(count)]
        raise RedisError(f"Unsupported Redis RESP marker: {marker!r}")

    def _command(self, *parts):
        self.sock.sendall(self._encode(parts))
        return self._read()


def redis_command(url: str, password: str | None, *parts, timeout: float = 15.0):
    with RedisConnection(url, password, timeout=timeout) as client:
        return client._command(*parts)


def fields_to_dict(values) -> dict[str, str]:
    return {str(values[index]): str(values[index + 1]) for index in range(0, len(values), 2)}


def safe_token(value: Any) -> str:
    token = re.sub(r"[^0-9A-Za-z._-]+", "_", str(value or "")).strip("._-")
    return token or "default"


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def append_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(text)


def event_day(fields: dict[str, str]) -> str:
    timestamp = str(fields.get("timestamp") or "")
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", timestamp)
    return match.group(1) if match else datetime.now().astimezone().strftime("%Y-%m-%d")


def write_event(output_root: Path, run_id: str, redis_id: str, fields: dict[str, str]) -> None:
    day = event_day(fields)
    worker = safe_token(fields.get("consumer") or fields.get("worker") or "unknown-worker")
    destination = output_root / safe_token(run_id) / day
    record = {"redisId": redis_id, **fields}
    json_line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    append_text(destination / "all.jsonl", json_line)
    append_text(destination / f"{worker}.jsonl", json_line)
    readable = (
        f"[{fields.get('timestamp', '')}] "
        f"[{fields.get('consumer', '')}] "
        f"[{fields.get('event', '')}] "
        f"[{fields.get('topic', '')}/{fields.get('keyword', '')}] "
        f"{fields.get('message', '')}\n"
    )
    append_text(destination / "all.log", readable)
    append_text(destination / f"{worker}.log", readable)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Receive Channels worker logs from Redis")
    result.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
    result.add_argument("--run-id", default=os.environ.get("REDIS_RUN_ID", "20260926-prod-01"))
    result.add_argument("--output-root", type=Path, required=True)
    result.add_argument("--state", type=Path, required=True)
    result.add_argument("--block-ms", type=int, default=5000)
    result.add_argument("--once", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    password = os.environ.get("REDIS_PASSWORD") or None
    stream = f"wechat:channels:{safe_token(args.run_id)}:logs"
    lock_path = args.state.with_suffix(args.state.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = lock_path.open("a+b")
    if lock_handle.seek(0, os.SEEK_END) == 0:
        lock_handle.write(b"0")
        lock_handle.flush()
    lock_handle.seek(0)
    try:
        msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print(json.dumps({
            "event": "central_log_sink_already_running",
            "stream": stream,
            "lock": str(lock_path.resolve()),
        }, ensure_ascii=False), flush=True)
        lock_handle.close()
        return 0
    cursor = "0-0"
    if args.state.exists():
        try:
            state = json.loads(args.state.read_text(encoding="utf-8-sig"))
            if state.get("stream") == stream:
                cursor = str(state.get("cursor") or cursor)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    print(json.dumps({
        "event": "central_log_sink_started",
        "stream": stream,
        "cursor": cursor,
        "outputRoot": str(args.output_root.resolve()),
    }, ensure_ascii=False), flush=True)
    try:
        while True:
            reply = redis_command(
                args.redis_url, password,
                "XREAD", "COUNT", 200, "BLOCK", max(1, args.block_ms),
                "STREAMS", stream, cursor,
                timeout=max(15.0, args.block_ms / 1000 + 10),
            )
            delivered = 0
            for _stream_name, entries in (reply or []):
                for redis_id, raw_fields in entries:
                    fields = fields_to_dict(raw_fields)
                    write_event(args.output_root, args.run_id, str(redis_id), fields)
                    cursor = str(redis_id)
                    delivered += 1
            if delivered:
                atomic_json(args.state, {
                    "stream": stream,
                    "cursor": cursor,
                    "updatedAt": datetime.now().astimezone().isoformat(),
                })
                print(json.dumps({
                    "event": "central_logs_persisted",
                    "count": delivered,
                    "cursor": cursor,
                }, ensure_ascii=False), flush=True)
            if args.once:
                return 0
    except KeyboardInterrupt:
        print(json.dumps({"event": "central_log_sink_stopped", "cursor": cursor}), flush=True)
        return 130
    finally:
        try:
            lock_handle.seek(0)
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            lock_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
