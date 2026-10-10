import argparse
import json
import os
import sys
import traceback


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description="Persistent Faster-Whisper worker")
    parser.add_argument("--model", default="small")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--download-root", default=None)
    args = parser.parse_args()

    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(
            args.model,
            device=args.device,
            compute_type=args.compute_type,
            download_root=args.download_root,
        )
        emit({"type": "ready", "model": args.model, "device": args.device, "compute_type": args.compute_type})
    except Exception as exc:
        emit({"type": "fatal", "error": str(exc), "trace": traceback.format_exc(limit=3)})
        return 2

    for line in sys.stdin:
        try:
            request = json.loads(line)
            if request.get("type") == "close":
                emit({"type": "closed"})
                return 0
            request_id = request.get("id")
            media_path = request["path"]
            if not os.path.isfile(media_path):
                raise FileNotFoundError(media_path)
            segments, info = model.transcribe(
                media_path,
                language=request.get("language") or args.language,
                initial_prompt=request.get("prompt") or None,
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                condition_on_previous_text=False,
                word_timestamps=False,
            )
            texts = []
            segment_count = 0
            for segment in segments:
                text = (segment.text or "").strip()
                if text and (not texts or texts[-1] != text):
                    texts.append(text)
                segment_count += 1
            emit({
                "type": "result",
                "id": request_id,
                "text": "\n".join(texts) or None,
                "language": getattr(info, "language", None),
                "language_probability": getattr(info, "language_probability", None),
                "duration": getattr(info, "duration", None),
                "duration_after_vad": getattr(info, "duration_after_vad", None),
                "segments": segment_count,
            })
        except Exception as exc:
            emit({"type": "error", "id": request.get("id") if "request" in locals() else None, "error": str(exc), "trace": traceback.format_exc(limit=3)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
