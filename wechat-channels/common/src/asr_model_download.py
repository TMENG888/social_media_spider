"""Pinned small-model downloader with TLS, checksums and atomic publication."""
import hashlib
import json
import time
from pathlib import Path
from urllib.request import urlopen
from filelock import FileLock

REVISION = '536b0662742c02347bc0e980a01041f333bce120'
FILES = {
    'config.json': (2370, 'e5047537059bd8f182d9ca64c470201585015187'),
    'model.bin': (483546902, '3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671'),
    'tokenizer.json': (2203239, '7818adb6de9fa3064d3ff81226fdd675be1f6344'),
    'vocabulary.txt': (459861, 'c9074644d9d1205686f16d411564729461324b75'),
}

def valid_file(path, name):
    size, digest = FILES[name]
    if not path.is_file() or path.stat().st_size != size:
        return False
    h = hashlib.sha256() if name == 'model.bin' else hashlib.sha1()
    if name != 'model.bin':
        h.update(f'blob {size}\0'.encode())
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest() == digest

def emit(event, **values):
    print(json.dumps(dict(event=event, **values), ensure_ascii=False), flush=True)

def portable_small(cache):
    path = Path(cache) / ('small-' + REVISION)
    if all(valid_file(path/name, name) for name in FILES):
        return str(path)
    return None

def download_small(cache, config):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    with FileLock(str(cache/'small-download.lock'), timeout=900):
        ready = portable_small(cache)
        if ready:
            return ready
        failure = cache/'small-download-failure.json'
        if failure.exists() and time.time() - failure.stat().st_mtime < 300:
            raise RuntimeError('Model download cooling down for 5 minutes after network failure')
        folder = cache/('small-' + REVISION)
        folder.mkdir(exist_ok=True)
        endpoints = config.get('client_asr_download_endpoints', ['https://huggingface.co', 'https://hf-mirror.com'])
        try:
            for name in FILES:
                target = folder/name
                if valid_file(target, name):
                    continue
                errors = []
                for endpoint in endpoints:
                    if not endpoint.startswith('https://'):
                        raise ValueError('Model download requires HTTPS')
                    temporary = target.with_suffix(target.suffix+'.part')
                    try:
                        emit('asr_model_file_download_start', file=name, endpoint=endpoint)
                        url = f'{endpoint.rstrip("/")}/Systran/faster-whisper-small/resolve/{REVISION}/{name}'
                        started = time.monotonic()
                        with urlopen(url, timeout=15) as response:
                            with temporary.open('wb') as output:
                                for chunk in iter(lambda: response.read(1024*1024), b''):
                                    if time.monotonic()-started > 900:
                                        raise TimeoutError('Model file download exceeded 15 minutes')
                                    output.write(chunk)
                        if not valid_file(temporary, name):
                            raise ValueError('Downloaded model checksum/size mismatch')
                        temporary.replace(target)
                        emit('asr_model_file_download_complete', file=name, seconds=round(time.monotonic()-started, 2), bytes=target.stat().st_size)
                        break
                    except Exception as error:
                        errors.append(str(error))
                        emit('asr_model_download_source_failed', file=name, endpoint=endpoint, error=str(error))
                else:
                    raise RuntimeError('; '.join(errors))
            failure.unlink(missing_ok=True)
            return str(folder)
        except Exception as error:
            temp = failure.with_suffix('.tmp')
            temp.write_text(json.dumps({'error':str(error), 'time':time.time()}), encoding='utf-8')
            temp.replace(failure)
            raise
