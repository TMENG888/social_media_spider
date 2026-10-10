"""Resolve cached ASR weights first, downloading only when unavailable."""
import json
from pathlib import Path


def emit(event, **details):
    print(json.dumps({'event': event, **details}, ensure_ascii=False), flush=True)


def validate_model_files(path):
    folder = Path(path)
    for name in ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt'):
        item = folder / name
        if not item.is_file() or item.stat().st_size <= 0:
            raise ValueError(f'ASR model file missing or empty: {item}')
    json.loads((folder / 'config.json').read_text(encoding='utf-8'))
    return str(folder)


def resolve_asr_model(config):
    from faster_whisper.utils import download_model
    model = config.get('client_asr_model', 'small')
    cache = Path(config.get('client_asr_model_dir') or
                 (Path(__file__).resolve().parents[1] / '.state' / 'asr-models'))
    cache.mkdir(parents=True, exist_ok=True)
    if model == 'small':
        from asr_model_download import portable_small
        ready = portable_small(cache)
        if ready:
            emit('asr_model_cache_ready', model=model, path=ready, source='verified_portable_cache')
            return ready
    if Path(model).is_dir():
        resolved = validate_model_files(model)
        emit('asr_model_cache_ready', model=model, path=resolved, source='explicit_directory')
        return resolved
    emit('asr_model_cache_check', model=model, cache=str(cache))
    try:
        resolved = validate_model_files(download_model(model, cache_dir=str(cache), local_files_only=True))
    except Exception as exc:
        emit('asr_model_download_start', model=model, cache=str(cache), reason=str(exc),
             message='Model unavailable locally; downloading online. Do not close the worker.')
        try:
            if model == 'small':
                from asr_model_download import download_small
                resolved = validate_model_files(download_small(cache, config))
            else:
                resolved = validate_model_files(download_model(model, cache_dir=str(cache), local_files_only=False))
        except Exception as download_error:
            emit('asr_model_download_failed', model=model, error=str(download_error))
            raise RuntimeError(f'ASR model {model} download failed. Check network, disk space and cache permissions; restart to retry. No other model was selected.') from download_error
        emit('asr_model_download_complete', model=model, path=resolved)
    else:
        emit('asr_model_cache_ready', model=model, path=resolved, source='local_cache')
    return resolved


def load_asr_model(config):
    from faster_whisper import WhisperModel
    return WhisperModel(resolve_asr_model(config),
                        device=config.get('client_asr_device', 'cpu'),
                        compute_type=config.get('client_asr_compute_type', 'int8'))
