"""Persistent, exact-host Redis safe-stop controls. No task ACKs or process kills."""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

# The embedded runtime can omit the script directory from sys.path.
SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def now():
    return datetime.now().astimezone().isoformat()


def target_key(computer, worker):
    computer, worker = str(computer).strip().upper(), str(worker).strip().lower()
    if not computer or not worker or any(c in computer + worker for c in "|*\r\n"):
        raise ValueError("An exact computer name and worker ID are required; wildcards are forbidden")
    return computer + "|" + worker


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class WorkerControl:
    def __init__(self, args, stop_event, command=None, computer=None, interval=3):
        if command is None:
            from redis_task_queue import redis_command
            command = redis_command
        self.args, self.command, self.stop_event = args, command, stop_event
        self.prefix = getattr(args, "prefix", args.stream.rsplit(":", 1)[0])
        self.computer = computer or socket.gethostname()
        self.target = target_key(self.computer, args.worker_root.name)
        self.stop_file = args.worker_root / ".state" / "stop.requested"
        self.receipt = args.worker_root / ".state" / "redis-control-stop.json"
        self.request = None
        self.interval = interval
        self.closed = threading.Event()
        self.lock = threading.RLock()
        self.thread = None
        self.last_error = None
        self.finalized = False

    def redis(self, *parts):
        return self.command(self.args.redis_url, self.args.redis_password, *parts, timeout=3)

    def ack(self, status):
        if not self.request:
            return
        value = {**self.request, "status": status, "consumer": self.args.consumer,
                 "observedAt": now(), "computer": self.computer,
                 "worker": self.args.worker_root.name}
        # A local receipt survives Redis failure, without falsely claiming delivery.
        atomic_json(self.receipt, value)
        self.redis("HSET", self.prefix + ":worker-control-acks", self.args.consumer,
                   json.dumps(value, ensure_ascii=False))

    def registry(self, status):
        task = {}
        try:
            task = json.loads((self.args.worker_root / ".state" / "redis_worker_status.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        value = {"target": self.target, "computer": self.computer,
                 "worker": self.args.worker_root.name, "consumer": self.args.consumer,
                 "pid": os.getpid(), "lastSeenAt": now(), "controlStatus": status,
                 "taskId": task.get("taskId"), "keyword": task.get("keyword"),
                 "taskStatus": task.get("status"),
                 "generation": getattr(self.args, "run_generation", None),
                 "workerRole": getattr(self.args, "worker_role", None),
                 "messageId": task.get("messageId"), "startedAt": task.get("startedAt"),
                 "taskKind": task.get("taskKind"),
                 "leaseStream": task.get("leaseStream"), "leaseGroup": task.get("leaseGroup"),
                 "heartbeatIntervalSeconds": self.interval,
                 "leaseHeartbeatIntervalSeconds": getattr(self.args, "heartbeat_seconds", None),
                 "leaseReclaimSeconds": getattr(self.args, "reclaim_idle_seconds", None)}
        self.redis("HSET", self.prefix + ":worker-registry", self.args.consumer,
                   json.dumps(value, ensure_ascii=False))

    def poll(self):
        with self.lock:
            raw = self.redis("HGET", self.prefix + ":worker-control", self.target)
            if raw:
                request = json.loads(raw)
                if request.get("action") != "safe_stop" or request.get("target") != self.target or not request.get("commandId"):
                    raise ValueError("Invalid worker control command; refusing task claims")
                new = not self.request or self.request["commandId"] != request["commandId"]
                self.request = request
                # Persist before publishing acknowledgement. Never send Ctrl+C.
                atomic_json(self.stop_file, {"source": "redis", **request})
                self.stop_event.set()
                if new:
                    print(json.dumps({"event": "redis_remote_safe_stop_received",
                                      "target": self.target, "commandId": request["commandId"]}, ensure_ascii=False), flush=True)
                self.ack("draining")
            self.registry("draining" if self.stop_event.is_set() else "running")
            self.last_error = None
            return self.stop_event.is_set()

    def start(self):
        # Fail closed on startup: cannot bypass a persisted remote stop by relaunch.
        # A successful empty HGET means the master has released the hold.
        self.poll()
        if not self.request:
            self.receipt.unlink(missing_ok=True)
        self.thread = threading.Thread(target=self.watch, name="redis-worker-control", daemon=True)
        self.thread.start()

    def watch(self):
        while not self.closed.wait(self.interval):
            try:
                self.poll()
            except Exception as error:
                error_type = type(error).__name__
                if error_type != self.last_error:
                    print(json.dumps({"event": "redis_worker_control_poll_failed", "errorType": error_type}, ensure_ascii=False), flush=True)
                self.last_error = error_type
                # LeaseHeartbeat separately protects task ownership on network loss.

    def close(self, orderly=False):
        if self.finalized:
            return
        self.finalized = True
        self.closed.set()
        if self.thread:
            # Each Redis call has a bounded timeout. Wait for the poller to
            # finish so a late draining ACK cannot overwrite stopped.
            self.thread.join()
        try:
            self.ack("stopped" if orderly else "exit_unconfirmed")
            self.registry("stopped" if orderly else "exit_unconfirmed")
        except Exception as error:
            print(json.dumps({"event": "redis_worker_control_final_ack_deferred", "errorType": type(error).__name__}), flush=True)


def send_stop(command, url, password, prefix, computer, worker, reason="operator requested safe stop"):
    target = target_key(computer, worker)
    request = {"commandId": uuid.uuid4().hex, "action": "safe_stop", "target": target,
               "requestedAt": now(), "reason": reason[:300]}
    command(url, password, "HSET", prefix + ":worker-control", target, json.dumps(request, ensure_ascii=False))
    return request


def resume(command, url, password, prefix, computer, worker, command_id):
    # Compare-and-delete so a stale resume cannot erase a newer stop.
    script = "local v=redis.call('HGET',KEYS[1],ARGV[1]); if not v then return 0 end; local c=cjson.decode(v); if c.commandId~=ARGV[2] then return -1 end; return redis.call('HDEL',KEYS[1],ARGV[1])"
    result = command(url, password, "EVAL", script, 1, prefix + ":worker-control",
                     target_key(computer, worker), command_id)
    if result == -1:
        raise ValueError("Command changed; inspect status before releasing the hold")
    return result


def main():
    from redis_task_queue import redis_command, safe_token
    parser = argparse.ArgumentParser(description="Master Redis targeted worker safe stop (no forced termination)")
    parser.add_argument("action", choices=("status", "stop", "resume"))
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
    parser.add_argument("--run-id", default=os.environ.get("REDIS_RUN_ID", "20260926-prod-01"))
    parser.add_argument("--password-file", type=Path)
    parser.add_argument("--computer")
    parser.add_argument("--worker")
    parser.add_argument("--reason", default="operator requested safe stop")
    parser.add_argument("--command-id")
    args = parser.parse_args()
    password = os.environ.get("REDIS_PASSWORD") or None
    if not password and args.password_file:
        password = args.password_file.read_text(encoding="utf-8-sig").strip() or None
    prefix = "wechat:channels:" + safe_token(args.run_id)
    if args.action == "status":
        result = {}
        for suffix in ("worker-registry", "worker-control", "worker-control-acks"):
            flat = redis_command(args.redis_url, password, "HGETALL", prefix + ":" + suffix) or []
            result[suffix] = {flat[i]: json.loads(flat[i+1]) for i in range(0, len(flat), 2)}
    else:
        if not args.computer or not args.worker:
            parser.error("--computer and --worker are required (exact target)")
        if args.action == "stop":
            result = send_stop(redis_command, args.redis_url, password, prefix, args.computer, args.worker, args.reason)
            result["delivery"] = "requested_only; inspect acknowledgements for stopped"
        else:
            if not args.command_id:
                parser.error("resume requires --command-id from status")
            result = {"released": resume(redis_command, args.redis_url, password, prefix, args.computer, args.worker, args.command_id),
                      "note": "Hold release does not launch a worker; restart it manually after safe stop"}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
