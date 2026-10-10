import argparse
import concurrent.futures
import json
import queue
import subprocess
import sys
import threading
import time
import tempfile
import os
import wave
from pathlib import Path

import numpy as np
import soundcard as sc
sys.path.insert(0, str(Path(__file__).resolve().parent))
from audio_capture_guard import growing_wav_peak


MIN_AUDIBLE_PEAK = 0.0005


class ProcessLoopbackUnavailable(RuntimeError):
    """The current Windows build cannot initialize process loopback."""


def analyze_and_normalize_wav(path: Path, expected_duration: int) -> dict:
    """Select the loudest native channel and rewrite a mono PCM WAV."""
    with wave.open(str(path), "rb") as source:
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        sample_rate = source.getframerate()
        frames = source.readframes(source.getnframes())
    if sample_width != 2:
        raise RuntimeError(f"进程音频回采返回不支持的采样宽度：{sample_width}")
    raw = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32767.0
    if channels > 1:
        frame_array = raw.reshape(-1, channels)
    else:
        frame_array = raw.reshape(-1, 1)
    channel_audit = []
    for index in range(frame_array.shape[1]):
        channel = frame_array[:, index].reshape(-1)
        channel_audit.append({
            "channel": index,
            "peak": float(np.max(np.abs(channel))) if channel.size else 0.0,
            "rms": float(np.sqrt(np.mean(np.square(channel)))) if channel.size else 0.0,
        })
    selected = max(channel_audit, key=lambda item: (item["rms"], item["peak"]))
    samples = frame_array[:, selected["channel"]].reshape(-1)
    peak = selected["peak"]
    if not samples.size or peak < MIN_AUDIBLE_PEAK:
        raise RuntimeError(
            "微信进程音频回采为空："
            + json.dumps({"channels": channel_audit, "sampleRate": sample_rate}, ensure_ascii=False)
        )
    per_second_rms = []
    for start in range(0, samples.size, sample_rate):
        chunk = samples[start:start + sample_rate]
        per_second_rms.append(
            float(np.sqrt(np.mean(np.square(chunk)))) if chunk.size else 0.0
        )
    activity_threshold = max(0.00035, min(0.01, peak * 0.015))
    active_seconds = [
        index for index, value in enumerate(per_second_rms)
        if value >= activity_threshold
    ]
    first_active_second = active_seconds[0] if active_seconds else None
    last_active_second = active_seconds[-1] if active_seconds else None
    silent_tail_seconds = (
        max(0, len(per_second_rms) - 1 - last_active_second)
        if last_active_second is not None else len(per_second_rms)
    )
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes())
    return {
        "duration": expected_duration,
        "sampleRate": sample_rate,
        "peak": peak,
        "rms": selected["rms"],
        "selectedChannel": selected["channel"],
        "channels": channel_audit,
        "activityThreshold": activity_threshold,
        "activeSecondCount": len(active_seconds),
        "firstActiveSecond": first_active_second,
        "lastActiveSecond": last_active_second,
        "silentTailSeconds": silent_tail_seconds,
        "output": str(path),
    }


def record_process_loopback(args) -> int:
    """Capture the WeChat render process independent of its output endpoint."""
    helper = Path(__file__).with_name("process-loopback-recorder.exe")
    if not helper.exists():
        raise ProcessLoopbackUnavailable(f"缺少微信进程音频回采组件：{helper}")
    command = [
        str(helper), str(args.process_id), "includetree", str(Path(args.output).resolve()),
        str(max(1, args.duration) * 1000),
    ]
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    ready_line = process.stdout.readline() if process.stdout else ""
    try:
        ready_payload = json.loads((ready_line or "").strip())
    except Exception as exc:
        process.terminate()
        stderr = process.stderr.read() if process.stderr else ""
        raise ProcessLoopbackUnavailable(
            f"微信进程音频回采组件未就绪：{ready_line!r}; {stderr[-1000:]}"
        ) from exc
    if not ready_payload.get("ready"):
        process.terminate()
        raise ProcessLoopbackUnavailable(f"微信进程音频回采组件初始化失败：{ready_payload}")
    print(json.dumps({
        "event": "loopback_recorder_ready",
        "ready": True,
        "source": "windows_process_loopback",
        "processId": args.process_id,
    }, ensure_ascii=False), flush=True)
    # Detect a wholly silent opening while the native helper is still writing.
    # A long silent tail after real sound is NOT grounds for early abortion.
    started = time.monotonic()
    audible = False
    probe = None
    probe_path = None
    limit = max(0, float(args.initial_silence_seconds))
    try:
        # The bundled native writer opens WAV exclusively, so a growing-file
        # read may be unavailable until close. Use a bounded parallel capture
        # of the SAME process tree; do not use a different system endpoint.
        if limit and args.duration > limit:
            fd, probe_name = tempfile.mkstemp(prefix='audio-watchdog-', suffix='.wav', dir=Path(args.output).parent)
            os.close(fd)
            probe_path = Path(probe_name)
            probe = subprocess.Popen(
                [str(helper), str(args.process_id), 'includetree', str(probe_path.resolve()), str(int(limit * 1000))],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        while process.poll() is None:
            peak = growing_wav_peak(args.output)
            if probe is not None and probe.poll() == 0:
                peak = growing_wav_peak(probe_path)
            audible = audible or (peak is not None and peak >= MIN_AUDIBLE_PEAK)
            elapsed = time.monotonic() - started
            if limit and elapsed >= limit and peak is not None and not audible:
                print(json.dumps({
                    'event': 'client_audio_initial_silence_abort',
                    'elapsedSeconds': round(elapsed, 2), 'peak': peak,
                    'processId': args.process_id,
                }), file=sys.stderr, flush=True)
                raise RuntimeError('微信录音开头持续静音，提前停止；请重新预检音量/音频路由')
            if elapsed > max(30, args.duration + 30):
                raise RuntimeError('微信进程录音超时')
            time.sleep(0.25)
        stdout, stderr = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=3)
        if probe is not None and probe.poll() is None:
            probe.terminate()
            probe.wait(timeout=3)
        if probe_path is not None:
            probe_path.unlink(missing_ok=True)
    if process.returncode != 0:
        raise RuntimeError(
            "微信进程音频回采失败："
            + (stderr or stdout or f"exitCode={process.returncode}")[-2000:]
        )
    audit = analyze_and_normalize_wav(Path(args.output), args.duration)
    print(json.dumps({
        "ok": True,
        "source": "windows_process_loopback",
        "processId": args.process_id,
        **audit,
    }, ensure_ascii=False))
    return 0


def record_output(
    speaker, sample_rate: int, duration: int,
    ready_queue: queue.Queue, start_event: threading.Event,
    initial_silence_seconds: float = 12,
) -> dict:
    """Capture one WASAPI render endpoint and return an audibility score."""
    name = str(speaker.name)
    try:
        microphone = sc.get_microphone(name, include_loopback=True)
        # Open every WASAPI stream first, then notify the parent process.  The
        # collector does not start WeChat playback until it receives this
        # readiness event, so the first 2-3 seconds are no longer lost while
        # soundcard enumerates/opens render endpoints.
        with microphone.recorder(samplerate=sample_rate) as recorder:
            ready_queue.put({"speaker": name, "ready": True, "error": None})
            if not start_event.wait(timeout=30):
                raise RuntimeError("等待统一录音开始信号超时")
            chunks = []
            audible = False
            for second in range(duration):
                chunk = recorder.record(numframes=sample_rate)
                chunks.append(chunk)
                audible = audible or bool(np.size(chunk) and np.max(np.abs(chunk)) >= MIN_AUDIBLE_PEAK)
                if initial_silence_seconds > 0 and second + 1 >= initial_silence_seconds and not audible:
                    raise RuntimeError('音频端点开头持续静音，提前停止')
            frames = np.concatenate(chunks, axis=0)
        frame_array = np.asarray(frames)
        # Never average stereo channels before measuring audibility. Some
        # render drivers expose channels with opposite polarity; averaging can
        # cancel valid speech and made WeChat playback look completely silent.
        # SoundCard also documents unreliable Windows WASAPI mono capture, so
        # keep the native multichannel stream and select its loudest channel.
        channel_audit = []
        if frame_array.ndim > 1 and frame_array.shape[1] > 1:
            for index in range(frame_array.shape[1]):
                channel = frame_array[:, index].reshape(-1)
                channel_audit.append({
                    "channel": index,
                    "peak": float(np.max(np.abs(channel))) if channel.size else 0.0,
                    "rms": float(np.sqrt(np.mean(np.square(channel)))) if channel.size else 0.0,
                })
            selected_channel = max(
                channel_audit, key=lambda item: (item["rms"], item["peak"])
            )["channel"]
            samples = frame_array[:, selected_channel].reshape(-1)
        else:
            selected_channel = 0
            samples = frame_array.reshape(-1)
            channel_audit = [{
                "channel": 0,
                "peak": float(np.max(np.abs(samples))) if samples.size else 0.0,
                "rms": float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0,
            }]
        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
        return {
            "speaker": name, "samples": samples, "peak": peak, "rms": rms,
            "selectedChannel": selected_channel,
            "channels": channel_audit,
            "error": None,
        }
    except Exception as error:
        ready_queue.put({"speaker": name, "ready": False, "error": str(error)})
        return {
            "speaker": name,
            "samples": np.asarray([], dtype=np.float32),
            "peak": 0.0,
            "rms": 0.0,
            "selectedChannel": None,
            "channels": [],
            "error": str(error),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Record the default Windows output through WASAPI loopback")
    parser.add_argument("--duration", type=int, required=True)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--output", required=True)
    parser.add_argument("--process-id", type=int)
    parser.add_argument("--initial-silence-seconds", type=float, default=12)
    args = parser.parse_args()

    if args.process_id:
        try:
            return record_process_loopback(args)
        except ProcessLoopbackUnavailable as error:
            # Windows builds before 10.0.20348 do not support application
            # loopback. Fall back before playback begins; never fall back after
            # a ready capture consumed the video timeline.
            print(json.dumps({
                "event": "process_loopback_unavailable",
                "processId": args.process_id,
                "fallback": "windows_wasapi_loopback",
                "error": str(error),
            }, ensure_ascii=False), file=sys.stderr, flush=True)

    default_name = str(sc.default_speaker().name)
    speakers = list(sc.all_speakers())
    if not speakers:
        raise RuntimeError("Windows 没有返回可用的音频输出设备")
    # Different PCs route WeChat through HDMI, USB, virtual audio or Realtek.
    # Listen to all render endpoints during the same playback window and keep
    # the endpoint that actually contains speech. Sequential probing would
    # consume the video before the correct device is reached.
    ready_queue = queue.Queue()
    start_event = threading.Event()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(speakers)) as executor:
        futures = [
            executor.submit(
                record_output, speaker, args.sample_rate, args.duration,
                ready_queue, start_event,
                args.initial_silence_seconds,
            )
            for speaker in speakers
        ]
        readiness = [ready_queue.get(timeout=30) for _ in speakers]
        ready_count = sum(1 for item in readiness if item["ready"])
        if ready_count == 0:
            start_event.set()
            raise RuntimeError(
                "所有Windows音频回采端点均初始化失败："
                + json.dumps(readiness, ensure_ascii=False)
            )
        print(json.dumps({
            "event": "loopback_recorder_ready",
            "ready": True,
            "readyEndpoints": ready_count,
            "totalEndpoints": len(speakers),
            "endpoints": readiness,
        }, ensure_ascii=False), flush=True)
        start_event.set()
        captures = [future.result() for future in futures]
    selected = max(captures, key=lambda item: (item["rms"], item["peak"]))
    samples = selected["samples"]
    peak = selected["peak"]
    if not samples.size or peak < MIN_AUDIBLE_PEAK:
        audit = [
            {key: item[key] for key in ("speaker", "peak", "rms", "error")}
            for item in captures
        ]
        raise RuntimeError(
            "系统音频回采为空；已并行检查全部输出设备："
            + json.dumps(audit, ensure_ascii=False)
        )
    # A non-zero peak only proves that *some* audio was captured.  We also
    # need temporal coverage to distinguish a complete video from a player
    # that produced four seconds of sound and then stalled for three minutes.
    per_second_rms = []
    for start in range(0, samples.size, args.sample_rate):
        chunk = samples[start:start + args.sample_rate]
        per_second_rms.append(
            float(np.sqrt(np.mean(np.square(chunk)))) if chunk.size else 0.0
        )
    activity_threshold = max(0.00035, min(0.01, peak * 0.015))
    active_seconds = [
        index for index, value in enumerate(per_second_rms)
        if value >= activity_threshold
    ]
    first_active_second = active_seconds[0] if active_seconds else None
    last_active_second = active_seconds[-1] if active_seconds else None
    silent_tail_seconds = (
        max(0, len(per_second_rms) - 1 - last_active_second)
        if last_active_second is not None else len(per_second_rms)
    )
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(args.output, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(args.sample_rate)
        output.writeframes(pcm.tobytes())
    print(json.dumps({
        "ok": True,
        "speaker": selected["speaker"],
        "defaultSpeaker": default_name,
        "duration": args.duration,
        "sampleRate": args.sample_rate,
        "peak": peak,
        "rms": selected["rms"],
        "selectedChannel": selected.get("selectedChannel"),
        "channels": selected.get("channels", []),
        "activityThreshold": activity_threshold,
        "activeSecondCount": len(active_seconds),
        "firstActiveSecond": first_active_second,
        "lastActiveSecond": last_active_second,
        "silentTailSeconds": silent_tail_seconds,
        "candidates": [
            {key: item[key] for key in ("speaker", "peak", "rms", "error")}
            for item in captures
        ],
        "output": args.output,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
