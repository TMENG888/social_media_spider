"""Read a growing PCM WAV without trusting its unfinished RIFF length."""
import struct
from pathlib import Path


def growing_wav_peak(path, maximum_bytes=262144):
    """Return None until a supported PCM16 data chunk exists; never guess silence."""
    try:
        with Path(path).open('rb') as stream:
            if stream.read(4) != b'RIFF':
                return None
            stream.read(4)
            if stream.read(4) != b'WAVE':
                return None
            pcm16 = False
            for _ in range(32):
                header = stream.read(8)
                if len(header) != 8:
                    return None
                name, size = struct.unpack('<4sI', header)
                if name == b'fmt ':
                    fmt = stream.read(size)
                    if len(fmt) < 16:
                        return None
                    tag, _, _, _, _, bits = struct.unpack('<HHIIHH', fmt[:16])
                    pcm16 = bits == 16 and (tag == 1 or (
                        tag == 65534 and len(fmt) >= 40 and fmt[24:26] == b'\x01\x00'
                    ))
                    if size & 1:
                        stream.read(1)
                elif name == b'data':
                    if not pcm16:
                        return None
                    # The native helper patches data size only on close.
                    data_start = stream.tell()
                    file_size = stream.seek(0, 2)
                    start = max(data_start, file_size - maximum_bytes)
                    start += (start - data_start) % 2
                    stream.seek(start)
                    data = stream.read(maximum_bytes)
                    data = data[:len(data) // 2 * 2]
                    if not data:
                        return None
                    return max(abs(v[0]) for v in struct.iter_unpack('<h', data)) / 32767.0
                else:
                    stream.seek(size + (size & 1), 1)
    except (OSError, ValueError, struct.error):
        return None
    return None
