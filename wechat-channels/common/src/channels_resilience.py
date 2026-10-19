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


class RedisCheckpointUnavailable(RuntimeError):
    """Infrastructure outage, never a content failure or successful completion."""


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
        from redis_task_queue import redis_command, RedisError

        try:
            return redis_command(url, password, *parts, timeout=5)
        except OSError as error:
            raise RedisCheckpointUnavailable(type(error).__name__) from None
        except RedisError as error:
            if 'closed the connection' in str(error):
                raise RedisCheckpointUnavailable('ConnectionClosed') from None
            raise

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
        effective=self._command(self.url,self.password,"EVAL","""
local new=cjson.decode(ARGV[2])
local raw=redis.call('HGET',KEYS[1],ARGV[1])
if raw then
 local old=cjson.decode(raw)
 if old.status=='skipped_unresolved' then return raw end
 local function filled(v) return v~=nil and v~=cjson.null and v~='' end
 if filled(old.article_key) and filled(new.article_key) and old.article_key~=new.article_key then
  return redis.error_reply('CHECKPOINT_IDENTITY_CONFLICT')
 end
 if type(old.row)=='table' and type(new.row)=='table' then
  if filled(old.row.url) and filled(new.row.url) and old.row.url~=new.row.url then
   return redis.error_reply('CHECKPOINT_IDENTITY_CONFLICT')
  end
  for _,field in ipairs({'url','title','author_name','video_duration','文章链接','文章标题','文章作者','文章视频时长'}) do
   if not filled(new.row[field]) then new.row[field]=old.row[field] end
  end
 end
 if type(old.retry_count)=='number' and old.retry_count>(type(new.retry_count)=='number' and new.retry_count or 0) then
  new.retry_count=old.retry_count
 end
 for _,field in ipairs({'row','article_key','published_at','asr_status','title','author_name'}) do
  if not filled(new[field]) then new[field]=old[field] end
 end
end
local encoded=cjson.encode(new)
redis.call('HSET',KEYS[1],ARGV[1],encoded)
return encoded
""",1,self.state_key,fingerprint,encoded)
        payload.update(json.loads(effective))
        if payload.get("status") == "dead_letter":
            self._command(self.url, self.password, "HSET", self.dead_key, fingerprint,
                          json.dumps(payload,ensure_ascii=False,separators=(",",":")))

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
