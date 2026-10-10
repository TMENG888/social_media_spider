from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path


MEDIA_URL_PATTERN = re.compile(
    rb"https://(?:findermp\.video\.qq\.com|finder\.video\.qq\.com|wxapp\.tc\.qq\.com)/"
    rb"[A-Za-z0-9_~:/?#\[\]@!$&'()*+,;=.%\-]{10,4096}"
)
MEDIA_URL_TEXT_PATTERN = re.compile(
    r"https://(?:findermp\.video\.qq\.com|finder\.video\.qq\.com|wxapp\.tc\.qq\.com)/"
    r"[A-Za-z0-9_~:/?#\[\]@!$&'()*+,;=.%\-]{10,4096}"
)


@dataclass(frozen=True)
class CacheFileState:
    size: int
    mtime_ns: int


@dataclass
class MediaProbe:
    path: str
    size: int
    duration_seconds: float | None
    audio_streams: int
    video_streams: int
    format_name: str | None
    complete: bool
    error: str | None = None


@dataclass
class CacheMatch:
    status: str
    target_duration_seconds: float | None
    elapsed_seconds: float
    changed_files: int
    candidates: list[MediaProbe]
    selected_source: str | None = None
    copied_media: str | None = None
    reason: str | None = None


def discover_cache_dirs(configured: list[str] | None = None) -> list[Path]:
    """Locate WeChat Chromium Cache_Data directories without changing them."""
    roots: list[Path] = []
    for value in configured or []:
        candidate = Path(os.path.expandvars(value)).expanduser()
        if candidate.is_dir():
            roots.append(candidate.resolve())

    appdata = os.environ.get("APPDATA")
    if appdata:
        profile_root = Path(appdata) / "Tencent" / "xwechat" / "radium" / "web" / "profiles"
        if profile_root.is_dir():
            roots.extend(path.resolve() for path in profile_root.glob("*/Cache/Cache_Data") if path.is_dir())

    # Preserve order while collapsing duplicate configured/auto-discovered paths.
    return list(dict.fromkeys(roots))


def find_xplayer_pids() -> list[int]:
    """Return only Weixin processes whose command line declares xplayer."""
    command = (
        "$items=Get-CimInstance Win32_Process | Where-Object "
        "{ $_.Name -eq 'Weixin.exe' -and $_.CommandLine -like '*--type=xplayer*' };"
        "$items | Select-Object -ExpandProperty ProcessId | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return []
        value = json.loads(completed.stdout)
        values = value if isinstance(value, list) else [value]
        return [int(item) for item in values if int(item) > 0]
    except Exception:
        return []


def _extract_media_urls(data: bytes) -> set[str]:
    urls = set()
    for match in MEDIA_URL_PATTERN.finditer(data):
        raw = match.group(0)
        # Process memory often stores a valid ASCII URL followed by another
        # printable object. Query values used by WeChat are limited to this
        # conservative set; trim any accidental tail at the first anomaly.
        try:
            value = raw.decode("ascii")
        except UnicodeDecodeError:
            continue
        if "stodownload" in value:
            urls.add(value)
    # V8/CEF may retain the request as a UTF-16 string instead of an ASCII
    # network buffer. Check both possible byte alignments.
    for offset in (0, 1):
        try:
            text = data[offset:].decode("utf-16-le", errors="ignore")
        except Exception:
            continue
        for match in MEDIA_URL_TEXT_PATTERN.finditer(text):
            value = match.group(0)
            if "stodownload" in value:
                urls.add(value)
    return urls


def scan_process_media_urls(pid: int, max_region_bytes: int = 64 * 1024 * 1024) -> set[str]:
    """Read only accessible committed pages and extract current media URLs."""
    if os.name != "nt":
        return set()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010
    MEM_COMMIT = 0x1000
    PAGE_GUARD = 0x100
    PAGE_NOACCESS = 0x01

    class MEMORY_BASIC_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BaseAddress", ctypes.c_void_p),
            ("AllocationBase", ctypes.c_void_p),
            ("AllocationProtect", ctypes.c_ulong),
            ("PartitionId", ctypes.c_ushort),
            ("RegionSize", ctypes.c_size_t),
            ("State", ctypes.c_ulong),
            ("Protect", ctypes.c_ulong),
            ("Type", ctypes.c_ulong),
        ]

    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.VirtualQueryEx.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t,
    ]
    kernel32.VirtualQueryEx.restype = ctypes.c_size_t
    kernel32.ReadProcessMemory.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.ReadProcessMemory.restype = ctypes.c_int

    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, int(pid))
    if not handle:
        return set()
    urls: set[str] = set()
    address = 0
    mbi = MEMORY_BASIC_INFORMATION()
    chunk_size = 4 * 1024 * 1024
    overlap = 4096
    try:
        while kernel32.VirtualQueryEx(
            handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)
        ):
            base = int(mbi.BaseAddress or 0)
            region_size = int(mbi.RegionSize or 0)
            next_address = base + max(region_size, 0x1000)
            readable = (
                mbi.State == MEM_COMMIT
                and not (mbi.Protect & PAGE_GUARD)
                and not (mbi.Protect & PAGE_NOACCESS)
                and region_size <= max_region_bytes
            )
            if readable:
                offset = 0
                carry = b""
                while offset < region_size:
                    requested = min(chunk_size, region_size - offset)
                    buffer = ctypes.create_string_buffer(requested)
                    read = ctypes.c_size_t()
                    ok = kernel32.ReadProcessMemory(
                        handle, ctypes.c_void_p(base + offset), buffer,
                        requested, ctypes.byref(read),
                    )
                    if ok and read.value:
                        block = carry + buffer.raw[:read.value]
                        urls.update(_extract_media_urls(block))
                        carry = block[-overlap:]
                    else:
                        carry = b""
                    offset += requested
            if next_address <= address:
                break
            address = next_address
    finally:
        kernel32.CloseHandle(handle)
    return urls


def scan_xplayer_media_urls() -> dict[int, set[str]]:
    return {pid: scan_process_media_urls(pid) for pid in find_xplayer_pids()}


def snapshot_cache(cache_dirs: list[Path] | None = None) -> dict[str, CacheFileState]:
    snapshot: dict[str, CacheFileState] = {}
    for cache_dir in cache_dirs or discover_cache_dirs():
        try:
            files = cache_dir.glob("f_*")
        except OSError:
            continue
        for path in files:
            try:
                stat = path.stat()
                if path.is_file():
                    snapshot[str(path.resolve())] = CacheFileState(stat.st_size, stat.st_mtime_ns)
            except OSError:
                continue
    return snapshot


def changed_cache_files(
    before: dict[str, CacheFileState], cache_dirs: list[Path] | None = None,
) -> list[Path]:
    after = snapshot_cache(cache_dirs)
    changed = []
    for path, state in after.items():
        old = before.get(path)
        if old is None or old.size != state.size or old.mtime_ns != state.mtime_ns:
            changed.append(Path(path))
    return changed


def _stream_duration_seconds(stream) -> float | None:
    try:
        if stream.duration is not None and stream.time_base is not None:
            return float(stream.duration * stream.time_base)
    except Exception:
        pass
    return None


def probe_media(path: Path, *, verify_packets: bool = True) -> MediaProbe:
    """Inspect a cache object as media; never writes to the cache file."""
    try:
        import av

        size = path.stat().st_size
        with path.open("rb") as handle:
            signature = handle.read(32)
        if b"ftyp" not in signature:
            return MediaProbe(
                str(path), size, None, 0, 0, None, False, "missing_mp4_ftyp",
            )

        with av.open(str(path), mode="r") as container:
            audio_streams = [stream for stream in container.streams if stream.type == "audio"]
            video_streams = [stream for stream in container.streams if stream.type == "video"]
            durations = [
                value for value in (
                    (float(container.duration) / float(av.time_base)) if container.duration else None,
                    *(_stream_duration_seconds(stream) for stream in container.streams),
                ) if value and value > 0
            ]
            duration = max(durations) if durations else None
            last_packet_end = 0.0
            packet_count = 0
            if verify_packets:
                for packet in container.demux():
                    packet_count += 1
                    try:
                        timestamp = packet.dts if packet.dts is not None else packet.pts
                        if timestamp is not None and packet.time_base is not None:
                            end = float(timestamp * packet.time_base)
                            if packet.duration:
                                end += float(packet.duration * packet.time_base)
                            last_packet_end = max(last_packet_end, end)
                    except Exception:
                        continue
            complete = bool(audio_streams and video_streams and duration and duration > 0)
            if verify_packets:
                # A truncated growing file often exposes ftyp/moov and a nominal
                # duration but cannot be demuxed through its final timestamps.
                complete = complete and packet_count > 0 and last_packet_end >= max(0.5, duration - 2.0)
            return MediaProbe(
                path=str(path), size=size, duration_seconds=round(duration, 3) if duration else None,
                audio_streams=len(audio_streams), video_streams=len(video_streams),
                format_name=getattr(container.format, "name", None), complete=complete,
                error=None if complete else "incomplete_or_missing_stream",
            )
    except Exception as exc:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        return MediaProbe(str(path), size, None, 0, 0, None, False, str(exc))


def duration_matches(actual: float | None, target: float | None, tolerance_seconds: float = 2.0,
                     tolerance_ratio: float = 0.06) -> bool:
    if actual is None or target is None or target <= 0:
        return False
    tolerance = max(float(tolerance_seconds), float(target) * float(tolerance_ratio))
    return abs(float(actual) - float(target)) <= tolerance


def wait_for_unique_media(
    before: dict[str, CacheFileState], target_duration_seconds: float | None,
    destination_dir: Path, *, cache_dirs: list[Path] | None = None,
    timeout_seconds: float = 6.0, poll_seconds: float = 0.35,
    stable_polls: int = 2, min_bytes: int = 65536,
    tolerance_seconds: float = 2.0, tolerance_ratio: float = 0.06,
) -> CacheMatch:
    """Return a copied MP4 only when one stable, duration-matched candidate exists."""
    started = time.monotonic()
    cache_dirs = cache_dirs or discover_cache_dirs()
    stability: dict[str, tuple[int, int]] = {}
    last_probes: list[MediaProbe] = []
    last_changed_count = 0
    while time.monotonic() - started <= timeout_seconds:
        changed = changed_cache_files(before, cache_dirs)
        last_changed_count = len(changed)
        stable_paths: list[Path] = []
        for path in changed:
            try:
                size = path.stat().st_size
            except OSError:
                continue
            previous_size, count = stability.get(str(path), (-1, 0))
            count = count + 1 if size == previous_size else 1
            stability[str(path)] = (size, count)
            if size >= min_bytes and count >= max(1, stable_polls):
                stable_paths.append(path)

        probes = [probe_media(path) for path in stable_paths]
        last_probes = probes
        eligible = [
            probe for probe in probes
            if probe.complete and duration_matches(
                probe.duration_seconds, target_duration_seconds,
                tolerance_seconds=tolerance_seconds, tolerance_ratio=tolerance_ratio,
            )
        ]
        if len(eligible) == 1:
            selected = eligible[0]
            destination_dir.mkdir(parents=True, exist_ok=True)
            handle, name = tempfile.mkstemp(prefix="channels-cache-", suffix=".mp4", dir=destination_dir)
            os.close(handle)
            copied = Path(name)
            try:
                shutil.copy2(selected.path, copied)
                copied_probe = probe_media(copied)
                if not copied_probe.complete or not duration_matches(
                    copied_probe.duration_seconds, target_duration_seconds,
                    tolerance_seconds=tolerance_seconds, tolerance_ratio=tolerance_ratio,
                ):
                    copied.unlink(missing_ok=True)
                    raise RuntimeError("copied_media_failed_validation")
            except Exception:
                copied.unlink(missing_ok=True)
                raise
            return CacheMatch(
                status="matched", target_duration_seconds=target_duration_seconds,
                elapsed_seconds=round(time.monotonic() - started, 3),
                changed_files=len(changed), candidates=eligible,
                selected_source=selected.path, copied_media=str(copied), reason="unique_duration_match",
            )
        if len(eligible) > 1:
            return CacheMatch(
                status="ambiguous", target_duration_seconds=target_duration_seconds,
                elapsed_seconds=round(time.monotonic() - started, 3),
                changed_files=len(changed), candidates=eligible,
                reason="multiple_duration_matches",
            )
        time.sleep(max(0.05, poll_seconds))

    return CacheMatch(
        status="not_found", target_duration_seconds=target_duration_seconds,
        elapsed_seconds=round(time.monotonic() - started, 3),
        changed_files=last_changed_count, candidates=last_probes,
        reason="no_unique_complete_duration_match",
    )


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, CacheFileState):
        return asdict(value)
    raise TypeError(type(value).__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="只读探测微信 Chromium 媒体缓存")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("snapshot")
    probe = sub.add_parser("probe")
    probe.add_argument("path")
    sub.add_parser("scan-xplayer")
    args = parser.parse_args()
    if args.command == "snapshot":
        result = {key: asdict(value) for key, value in snapshot_cache().items()}
    elif args.command == "probe":
        result = asdict(probe_media(Path(args.path)))
    else:
        result = {str(pid): sorted(urls) for pid, urls in scan_xplayer_media_urls().items()}
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
