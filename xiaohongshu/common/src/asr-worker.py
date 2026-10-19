import argparse
import json
import os
import sys
import time
import traceback
import math
import re
from difflib import SequenceMatcher

SAMPLE_RATE = 16000


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def decode_mono_audio(media_path):
    """PyAV uses bundled FFmpeg libraries; no external ffmpeg.exe is required."""
    import av
    from faster_whisper.audio import decode_audio

    with av.open(media_path, mode="r", metadata_errors="ignore") as container:
        if not container.streams.audio:
            return None, "no_audio_track"
    audio = decode_audio(media_path, sampling_rate=SAMPLE_RATE)
    if not audio.size:
        return None, "empty_audio_track"
    return audio, None


def clean_asr_text(value):
    text = re.sub(r"[\r\n\t]+", "，", str(value or ""))
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"，{2,}", "，", text).strip("，")
    return text or None


def strip_known_hallucination_markers(value):
    text = clean_asr_text(value)
    if not text:
        return None, False
    original = text
    text = re.sub(r"(?:，|^)?字幕\s*(?:by|来自|制作人?|製作人?)\s*[^，。！？]{0,24}(?=[，。！？]|$)", "，", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:，|^)?(?:amara[.]org|优优独播剧场)(?=[，。！？]|$)", "，", text, flags=re.IGNORECASE)
    return clean_asr_text(text), text != original


def compare_key(value):
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", str(value or "")).lower()


def assess_text(value, prompt, capture_seconds, speech_seconds=None, fallback=False):
    if os.environ.get('SOCIAL_VOLUME_ENABLED') == '1':
        return clean_asr_text(value), {'accepted': None, 'reason': 'quality_check_disabled_by_volume_policy', 'qualityChecked': False}
    text, marker_removed = strip_known_hallucination_markers(value)
    if not text:
        return None, {"accepted": False, "reason": "known_whisper_hallucination" if marker_removed else "empty",
                      "hallucination_marker_removed": marker_removed}
    normalized = compare_key(text)
    prompt_key = compare_key(str(prompt or "")[:64])
    grams = [normalized[i:i + 4] for i in range(max(0, len(normalized) - 3))]
    repeat_ratio = 1.0 - len(set(grams)) / len(grams) if grams else 0.0
    speech_ratio = (float(speech_seconds) / max(1.0, float(capture_seconds))) if speech_seconds is not None else None
    prompt_echo = bool(len(prompt_key) >= 8 and prompt_key in normalized and
                       len(normalized) <= int(len(prompt_key) * 2.6) and
                       (speech_seconds is None or float(speech_seconds) < 0.8))
    known = any(marker in normalized.casefold() for marker in (
        "mingpaocanada", "mingpaotoronto",
        "请不吝点赞订阅转发打赏支持明镜与点点栏目",
    ))
    reason = "prompt_echo" if prompt_echo else "looping_repetition" if len(normalized) >= 40 and repeat_ratio >= 0.45 else "known_whisper_hallucination" if known else None
    return (text if reason is None else None), {
        "accepted": reason is None, "reason": reason,
        "repeat_ngram_ratio": round(repeat_ratio, 4), "prompt_echo": prompt_echo,
        "known_hallucination": known,
        "hallucination_marker_removed": marker_removed,
        "speech_ratio": round(speech_ratio, 4) if speech_ratio is not None else None,
        "fallback_without_vad": fallback,
    }


def needs_review(text, capture_seconds, speech_seconds=None):
    if os.environ.get('SOCIAL_VOLUME_ENABLED') == '1':
        return False
    capture = float(capture_seconds or 0)
    if capture < 10:
        return False
    if len(compare_key(text)) < max(8, int(math.ceil(capture * 0.65))):
        return True
    if speech_seconds is not None and float(speech_seconds or 0) / max(1.0, capture) < 0.05 and len(compare_key(text)) < max(30, int(capture * 0.8)):
        return True
    return False


def merge_text(left, right):
    left, right = clean_asr_text(left), clean_asr_text(right)
    if not left:
        return right
    if not right:
        return left
    if right in left[-max(80, len(right) * 2):]:
        return left
    maximum = min(len(left), len(right), 80)
    for size in range(maximum, 5, -1):
        if left[-size:] == right[:size]:
            return clean_asr_text(left + right[size:])
    return clean_asr_text(left + "，" + right)


def decode_pass(model, audio, request, args, use_vad, capture_seconds):
    options = {
        "language": request.get("language") or args.language,
        "initial_prompt": request.get("prompt") or None,
        "beam_size": args.beam_size, "best_of": 1, "temperature": 0.0,
        "vad_filter": use_vad, "condition_on_previous_text": False,
        "word_timestamps": False,
    }
    if use_vad:
        options["vad_parameters"] = {
            "threshold": 0.35, "min_speech_duration_ms": 100,
            "min_silence_duration_ms": 300, "speech_pad_ms": 800,
        }
    segments_iter, info = model.transcribe(audio, **options)
    segments = list(segments_iter)
    parts = []
    for segment in segments:
        value = clean_asr_text(getattr(segment, "text", None))
        if value and (not parts or compare_key(value) != compare_key(parts[-1])):
            parts.append(value)
    raw = clean_asr_text("，".join(parts))
    accepted, quality = assess_text(raw, request.get("prompt"), capture_seconds,
                                    getattr(info, "duration_after_vad", None), not use_vad)
    return accepted, info, segments, quality


def transcribe_media(model, request, args):
    import numpy as np

    started = time.monotonic()
    media_path = request["path"]
    if not os.path.isfile(media_path):
        raise FileNotFoundError(media_path)
    audio, empty_reason = decode_mono_audio(media_path)
    result = {
        "type": "result", "id": request.get("id"), "text": None,
        "status": empty_reason or "no_speech", "sample_rate": SAMPLE_RATE,
        "channels": 1, "duration": 0, "duration_after_vad": 0, "segments": 0,
    }
    if audio is None:
        # A silent/no-audio video still needs real container duration evidence;
        # never substitute the expected page duration to make it pass.
        import av
        with av.open(media_path, mode="r", metadata_errors="ignore") as container:
            result["duration"] = float(container.duration or 0) / float(av.time_base)
            result["duration_source"] = "decoded_container"
        return result
    result["duration"] = round(len(audio) / SAMPLE_RATE, 3)
    if not np.isfinite(audio).all():
        raise ValueError("Audio contains non-finite samples")
    if not audio.size or float(np.max(np.abs(audio))) <= 1e-5:
        result["status"] = "silent_audio"
        return result
    passes, candidates = [], []
    for use_vad in (True, False):
        text, info, segments, quality = decode_pass(model, audio, request, args, use_vad, result["duration"])
        passes.append({"pass": "vad" if use_vad else "no_vad", "segments": len(segments), "text_length": len(text or ""), "quality": quality})
        if text:
            candidates.append((text, info, segments, not use_vad))
            if not needs_review(text, result["duration"], getattr(info, "duration_after_vad", None)):
                break
    text, info, segments, fallback = max(candidates, key=lambda item: len(compare_key(item[0]))) if candidates else (None, None, [], True)
    if needs_review(text, result["duration"], getattr(info, "duration_after_vad", None) if info else None):
        chunk_seconds, overlap, offset, chunk_texts, chunk_audits = 30.0, 1.0, 0.0, [], []
        while offset < result["duration"]:
            start, end = int(offset * SAMPLE_RATE), min(len(audio), int((offset + chunk_seconds) * SAMPLE_RATE))
            if end <= start:
                break
            chunk = audio[start:end]
            ctext, cinfo, csegments, cquality = decode_pass(model, chunk, request, args, True, len(chunk) / SAMPLE_RATE)
            if not ctext:
                ctext, cinfo, csegments, cquality = decode_pass(model, chunk, request, args, False, len(chunk) / SAMPLE_RATE)
            if ctext:
                chunk_texts.append(ctext)
            chunk_audits.append({"offset_seconds": round(offset, 2), "text_length": len(ctext or ""), "segments": len(csegments), "quality": cquality})
            offset += chunk_seconds - overlap
        merged = None
        for value in chunk_texts:
            merged = merge_text(merged, value)
        passes.append({"pass": "chunked_recovery", "chunks": chunk_audits, "text_length": len(merged or "")})
        if len(compare_key(merged)) > len(compare_key(text)):
            text, fallback = merged, True
    head_seconds = min(8.0, result["duration"])
    if text and head_seconds > 0:
        head, _hinfo, _hsegments, hquality = decode_pass(model, audio[:int(head_seconds * SAMPLE_RATE)], request, args, False, head_seconds)
        before = text
        if head and compare_key(head) not in compare_key(text)[:max(24, len(compare_key(head)) * 2)]:
            key_head, key_full = compare_key(head), compare_key(text)
            prefix = key_full[:len(key_head)]
            if not prefix or SequenceMatcher(None, key_head, prefix).ratio() < 0.72:
                text = merge_text(head, text)
        passes.append({"pass": "head_prefix", "text_length": len(head or ""), "added_chars": max(0, len(text or "") - len(before or "")), "quality": hquality})
    had_candidate = bool(text)
    final_quality = None
    if text:
        text, final_quality = assess_text(
            text, request.get("prompt"), result["duration"],
            getattr(info, "duration_after_vad", None) if info else None, fallback,
        )
        if text and needs_review(text, result["duration"], getattr(info, "duration_after_vad", None) if info else None):
            final_quality = {
                **(final_quality or {}), "accepted": False,
                "reason": "insufficient_transcript_coverage",
                "minimum_characters": max(8, int(math.ceil(result["duration"] * 0.65))),
                "actual_characters": len(compare_key(text)),
            }
            text = None
    rejected_during_passes = any(
        item.get("quality", {}).get("reason") not in (None, "empty")
        for item in passes if isinstance(item, dict)
    )
    quality_rejected = os.environ.get('SOCIAL_VOLUME_ENABLED') != '1' and ((had_candidate and not text) or (not text and rejected_during_passes))
    result.update({
        "text": text,
        "status": "ok" if text else "quality_rejected" if quality_rejected else "no_speech",
        "language": getattr(info, "language", None) if info else None,
        "language_probability": getattr(info, "language_probability", None) if info else None,
        "duration_after_vad": getattr(info, "duration_after_vad", 0) if info else 0,
        "segments": len(segments), "fallback_without_vad": fallback, "passes": passes,
        "quality": final_quality,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    })
    return result


def main():
    parser = argparse.ArgumentParser(description="Persistent Faster-Whisper worker")
    parser.add_argument("--model", default="small")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--download-root", default=None)
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--cpu-threads", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument("--beam-size", type=int, default=1)
    args = parser.parse_args()
    if args.cpu_threads < 1 or args.beam_size < 1:
        parser.error("cpu-threads and beam-size must be positive")

    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(
            args.model, device=args.device, compute_type=args.compute_type,
            download_root=args.download_root, local_files_only=args.local_files_only,
            cpu_threads=args.cpu_threads, num_workers=1,
        )
        emit({"type": "ready", "model": args.model, "device": args.device,
              "compute_type": args.compute_type, "cpu_threads": args.cpu_threads,
              "beam_size": args.beam_size})
    except Exception as exc:
        emit({"type": "fatal", "error": str(exc), "trace": traceback.format_exc(limit=3)})
        return 2

    for line in sys.stdin:
        request = {}
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("Request must be a JSON object")
            if request.get("type") == "close":
                emit({"type": "closed"})
                return 0
            emit(transcribe_media(model, request, args))
        except Exception as exc:
            emit({"type": "error", "id": request.get("id") if isinstance(request, dict) else None,
                  "error": str(exc), "trace": traceback.format_exc(limit=3)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
