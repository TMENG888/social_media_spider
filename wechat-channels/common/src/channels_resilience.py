"""Durable/atomic helpers shared by the WeChat Channels production worker."""

from __future__ import annotations

import json
import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write a same-volume temporary file and atomically replace the target."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _safe_token(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_-]+", "_", value or "").strip("_") or "default"


class RedisVideoCheckpointStore:
    """Cross-machine video checkpoints for one Redis keyword task.

    Every completed checkpoint contains the full locally committed row and its
    comments.  A reclaimed task can therefore hydrate a new worker's SQLite
    database before it scans the WeChat cards and can skip completed details.
    """

    def __init__(self) -> None:
        self.url = os.environ.get("REDIS_URL", "").strip()
        self.password = os.environ.get("REDIS_PASSWORD") or None
        self.run_id = _safe_token(os.environ.get("REDIS_RUN_ID", ""))
        self.task_id = _safe_token(os.environ.get("WECHAT_REDIS_TASK_ID", ""))
        self.enabled = bool(self.url and os.environ.get("WECHAT_REDIS_TASK_ID"))
        prefix = f"wechat:channels:{self.run_id}"
        self.state_key = f"{prefix}:video-state:{self.task_id}"
        self.dead_key = f"{prefix}:video-dead-letter:{self.task_id}"
        # This index is shared by all keyword tasks in the same run.  The
        # project is part of the key so a video may legitimately exist once in
        # each business topic, while repeated hits from several keywords in the
        # same topic are opened only once.
        self.global_key = f"{prefix}:video-global"

    @staticmethod
    def _command(url: str, password: str | None, *parts):
        # Imported lazily so local/static mode does not couple collector startup
        # to the Redis scheduler module.
        from redis_task_queue import redis_command

        return redis_command(url, password, *parts)

    @staticmethod
    def _pairs(reply: Any) -> dict[str, str]:
        if not reply:
            return {}
        if not isinstance(reply, list) or len(reply) % 2:
            raise RuntimeError(f"Redis HGETALL returned invalid data: {reply!r}")
        return {str(reply[index]): str(reply[index + 1]) for index in range(0, len(reply), 2)}

    def load_all(self) -> dict[str, dict[str, Any]]:
        if not self.enabled:
            return {}
        values = self._pairs(self._command(self.url, self.password, "HGETALL", self.state_key))
        return {key: json.loads(value) for key, value in values.items()}

    def put(self, fingerprint: str, payload: dict[str, Any]) -> None:
        if not self.enabled or not fingerprint:
            return
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self._command(self.url, self.password, "HSET", self.state_key, fingerprint, encoded)
        if payload.get("status") == "dead_letter":
            self._command(self.url, self.password, "HSET", self.dead_key, fingerprint, encoded)

    def remove_dead_letter(self, fingerprint: str) -> None:
        if self.enabled and fingerprint:
            self._command(self.url, self.password, "HDEL", self.dead_key, fingerprint)

    @staticmethod
    def _global_field(project: str, article_key: str) -> str:
        material = f"{project or ''}|{article_key or ''}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def get_global(self, project: str, article_key: str) -> dict[str, Any] | None:
        """Return an already committed cross-keyword video in this project."""
        if not self.enabled or not article_key:
            return None
        encoded = self._command(
            self.url, self.password, "HGET", self.global_key,
            self._global_field(project, article_key),
        )
        if not encoded:
            return None
        value = json.loads(encoded)
        return value if isinstance(value, dict) else None

    def put_global(
        self, project: str, article_key: str, payload: dict[str, Any],
    ) -> None:
        """Publish a committed video identity for other keyword workers."""
        if not self.enabled or not article_key:
            return
        value = {
            "project": project,
            "article_key": article_key,
            "task_id": self.task_id,
            **payload,
        }
        self._command(
            self.url, self.password, "HSET", self.global_key,
            self._global_field(project, article_key),
            json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        )
