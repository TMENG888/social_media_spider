"""Node-local persistent Faster-Whisper service.

The Redis scheduler owns one instance of this process. A video collection
child records audio while the matching WeChat detail is open, then submits the
durable media path over a loopback-only TCP socket. The large model therefore
survives the end of one Redis video-retry and is reused by the next one.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import socketserver
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


class AsrRuntime:
    def __init__(self, config_path: Path, token: str) -> None:
        self.config_path = config_path
        self.config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        self.token = token
        self.lock = threading.Lock()
        self.requests = 0

        # Import the production recovery/quality implementation so the
        # persistent and legacy fallback paths cannot drift apart.
        import channels_pc_collector as collector
        from asr_model_loader import load_asr_model

        self.collector = collector
        self.model = load_asr_model(self.config)

    def transcribe(self, request: dict) -> dict:
        if request.get("token") != self.token:
            raise PermissionError("invalid persistent ASR service token")
        media_path = Path(str(request.get("path") or ""))
        if not media_path.is_file():
            raise FileNotFoundError(str(media_path))
        prompt = str(request.get("prompt") or "") or None
        capture_seconds = float(request.get("capture_seconds") or 0) or None
        started = time.monotonic()
        # CTranslate2 model calls are serialized. Redis currently runs one UI
        # child per node, but the lock keeps future concurrent callers safe.
        with self.lock:
            text, info, segments, fallback_used, audits = (
                self.collector.transcribe_audio_with_recovery(
                    self.model,
                    media_path,
                    self.config,
                    prompt,
                    capture_seconds,
                )
            )
            self.requests += 1
        return {
            "type": "result",
            "id": request.get("id"),
            "text": text,
            "language": getattr(info, "language", None),
            "language_probability": getattr(info, "language_probability", None),
            "duration": getattr(info, "duration", None),
            "duration_after_vad": getattr(info, "duration_after_vad", None),
            "segments": len(segments),
            "fallback_without_vad": fallback_used,
            "passes": audits,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "service_request_count": self.requests,
            "service_pid": os.getpid(),
        }


class AsrRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        request = None
        try:
            raw = self.rfile.readline(8 * 1024 * 1024)
            if not raw:
                return
            request = json.loads(raw.decode("utf-8"))
            if request.get("type") == "ping":
                if request.get("token") != self.server.runtime.token:
                    raise PermissionError("invalid persistent ASR service token")
                response = {
                    "type": "pong",
                    "id": request.get("id"),
                    "service_pid": os.getpid(),
                    "service_request_count": self.server.runtime.requests,
                }
            else:
                response = self.server.runtime.transcribe(request)
        except Exception as exc:
            response = {
                "type": "error",
                "id": request.get("id") if isinstance(request, dict) else None,
                "error": str(exc),
                "trace": traceback.format_exc(limit=4),
                "service_pid": os.getpid(),
            }
        try:
            self.wfile.write(
                (json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8")
            )
            self.wfile.flush()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            # The caller may time out or stop after the durable ASR result has
            # already been produced.  Do not emit a misleading server traceback;
            # the persisted job/checkpoint remains authoritative.
            return


class LoopbackAsrServer(socketserver.TCPServer):
    allow_reuse_address = True

    def __init__(self, address, runtime: AsrRuntime):
        super().__init__(address, AsrRequestHandler)
        self.runtime = runtime


def _windows_process_is_alive(process_id: int) -> bool:
    """Probe a Windows PID without sending a console control signal."""
    process_query_limited_information = 0x1000
    still_active = 259
    handle = ctypes.windll.kernel32.OpenProcess(
        process_query_limited_information, False, int(process_id),
    )
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetExitCodeProcess(
            handle, ctypes.byref(exit_code),
        ):
            return False
        return int(exit_code.value) == still_active
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def process_is_alive(process_id: int) -> bool:
    if os.name == "nt":
        return _windows_process_is_alive(process_id)
    try:
        os.kill(process_id, 0)
        return True
    except OSError:
        return False


def parent_watchdog(server: LoopbackAsrServer, parent_pid: int) -> None:
    if parent_pid <= 0:
        return
    while True:
        time.sleep(5)
        if not process_is_alive(parent_pid):
            server.shutdown()
            return


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Persistent node-local Faster-Whisper service"
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument(
        "--token", default=os.environ.get("WECHAT_PERSISTENT_ASR_TOKEN", "")
    )
    parser.add_argument("--parent-pid", type=int, default=0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.token:
        emit({"type": "fatal", "error": "persistent ASR token is required"})
        return 2
    try:
        runtime = AsrRuntime(args.config.resolve(), args.token)
        server = LoopbackAsrServer((args.host, args.port), runtime)
    except Exception as exc:
        emit({
            "type": "fatal",
            "error": str(exc),
            "trace": traceback.format_exc(limit=5),
        })
        return 2
    host, port = server.server_address
    emit({
        "type": "ready",
        "host": host,
        "port": port,
        "pid": os.getpid(),
        "model": runtime.config.get("client_asr_model", "small"),
        "device": runtime.config.get("client_asr_device", "cpu"),
        "compute_type": runtime.config.get("client_asr_compute_type", "int8"),
        "instance": uuid.uuid4().hex,
    })
    watcher = threading.Thread(
        target=parent_watchdog,
        args=(server, args.parent_pid),
        name="asr-parent-watchdog",
        daemon=True,
    )
    watcher.start()
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
