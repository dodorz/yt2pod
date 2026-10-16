from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import yt_dlp

from .config import settings
from .youtube import MediaInfo, build_ydl_opts, mime_for, normalize_media_type, resolve_media

logger = logging.getLogger(__name__)

# Signed YouTube stream URLs are short-lived and googlevideo rejects full-file
# GETs, so we download each episode once into a disk cache and serve the local
# file. That gives podcast clients correct Content-Length, ETag and Range
# support, and makes seeking instant. ``_info_cache`` memoises yt-dlp metadata
# resolution used for HEAD probes and feed warm-up.
_info_cache: dict[str, tuple[MediaInfo, float]] = {}
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _key(video_id: str, media_type: str) -> str:
    return f"{normalize_media_type(media_type)}:{video_id}"


def cache_media(video_id: str, info: MediaInfo, media_type: str | None = None) -> None:
    """Memoise resolved media metadata (called during feed refresh)."""
    _info_cache[_key(video_id, media_type or info.media_type)] = (info, time.time())


def invalidate(video_id: str, media_type: str = "audio") -> None:
    _info_cache.pop(_key(video_id, media_type), None)


async def get_media_info(
    video_id: str, media_type: str = "audio", force: bool = False
) -> MediaInfo:
    """Return cached media metadata, resolving it on demand if needed."""
    key = _key(video_id, media_type)
    entry = _info_cache.get(key)
    if not force and entry and time.time() - entry[1] < settings.cache_ttl:
        return entry[0]

    info = await asyncio.to_thread(resolve_media, video_id, media_type)
    _info_cache[key] = (info, time.time())
    return info


def find_media_file(video_id: str, media_type: str = "audio") -> Path | None:
    """Return the cached media file for a video, if it has been downloaded."""
    directory = settings.media_dir / normalize_media_type(media_type)
    if not directory.exists():
        return None
    for candidate in sorted(directory.glob(f"{video_id}.*")):
        if candidate.suffix not in (".part", ".ytdl") and candidate.is_file():
            # Touch to keep this episode recent for the LRU eviction policy.
            try:
                candidate.touch()
            except OSError:
                pass
            return candidate
    return None


def ensure_media_file(video_id: str, media_type: str = "audio") -> Path:
    """Return the cached media file, downloading it first if necessary.

    Blocking; call via ``asyncio.to_thread``. A per-video lock prevents
    duplicate concurrent downloads (e.g. several Range requests racing).
    """
    media_type = normalize_media_type(media_type)
    existing = find_media_file(video_id, media_type)
    if existing:
        return existing

    with _get_lock(_key(video_id, media_type)):
        existing = find_media_file(video_id, media_type)
        if existing:
            return existing
        return _download(video_id, media_type)


def _download(video_id: str, media_type: str) -> Path:
    fmt = settings.video_format if media_type == "video" else settings.audio_format
    directory = settings.media_dir / media_type
    directory.mkdir(parents=True, exist_ok=True)

    ydl_opts = build_ydl_opts(
        format=fmt,
        outtmpl=str(directory / f"{video_id}.%(ext)s"),
        noplaylist=True,
    )
    ydl_opts.pop("skip_download", None)
    url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if not info:
            raise ValueError(f"Could not download video {video_id}")
        path = Path(ydl.prepare_filename(info))

    if not path.exists():
        # Some post-processing paths can change the extension; fall back to glob.
        found = find_media_file(video_id, media_type)
        if not found:
            raise ValueError(f"Downloaded file missing for video {video_id}")
        path = found
    _enforce_cache_limit(keep=path)
    return path


def _enforce_cache_limit(keep: Path | None = None) -> None:
    """Evict least-recently-used media files above ``media_cache_max_bytes``."""
    limit = settings.media_cache_max_bytes
    if limit <= 0:
        return

    entries: list[tuple[float, int, Path]] = []
    total = 0
    for path in settings.media_dir.rglob("*"):
        if not path.is_file() or path.suffix in (".part", ".ytdl"):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((stat.st_mtime, stat.st_size, path))
        total += stat.st_size

    if total <= limit:
        return

    entries.sort()
    for _mtime, size, path in entries:
        if total <= limit:
            break
        if keep is not None and path == keep:
            continue
        try:
            path.unlink()
            total -= size
        except OSError:
            continue


async def stream_media(
    video_id: str, media_type: str = "audio", range_header: str | None = None
) -> tuple[int, dict[str, str], AsyncIterator[bytes]]:
    """Relay a YouTube stream on demand without writing to disk.

    Returns ``(status, headers, body)``. The client's Range request is mapped
    onto upstream byte ranges, fetched in ``stream_chunk_size`` slices so a
    throttled connection is never asked for the whole file at once.
    """
    media_type = normalize_media_type(media_type)
    info = await get_media_info(video_id, media_type)
    total = info.filesize

    if total is None:
        return await _passthrough(info, media_type, range_header)

    wants_range = bool(range_header)
    start, end = _parse_range(range_header, total)
    length = end - start + 1

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": info.mime,
        "Content-Length": str(length),
    }
    if wants_range:
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    status = 206 if wants_range else 200
    chunk_size = _safe_chunk_size(settings.stream_chunk_size, total)
    return status, headers, _iter_ranges(video_id, media_type, info, start, end, chunk_size)


def _safe_chunk_size(requested: int, total: int | None) -> int:
    """Clamp the upstream Range size so it never covers the entire file.

    googlevideo returns HTTP 403 for a Range that spans the whole media file,
    so small episodes (smaller than the configured chunk size) are split in two.
    """
    requested = max(1, int(requested))
    if total is None or total <= 1:
        return requested
    if requested >= total:
        return max(1, (total + 1) // 2)
    return requested


async def _iter_ranges(
    video_id: str,
    media_type: str,
    info: MediaInfo,
    start: int,
    end: int,
    chunk_size: int,
) -> AsyncIterator[bytes]:
    client = httpx.AsyncClient(timeout=60, follow_redirects=True)
    current = info
    position = start
    try:
        while position <= end:
            chunk_end = min(position + chunk_size - 1, end)
            response = None
            for attempt in range(2):
                request = client.build_request(
                    "GET",
                    current.url,
                    headers={
                        "User-Agent": settings.user_agent,
                        "Range": f"bytes={position}-{chunk_end}",
                    },
                )
                response = await client.send(request, stream=True)
                if response.status_code in (403, 410) and attempt == 0:
                    await response.aclose()
                    current = await get_media_info(video_id, media_type, force=True)
                    continue
                break

            if response is None:
                return
            if response.status_code not in (200, 206):
                await response.aclose()
                raise httpx.HTTPStatusError(
                    f"Upstream returned {response.status_code}",
                    request=response.request,
                    response=response,
                )
            async for chunk in response.aiter_bytes(chunk_size=65536):
                yield chunk
            await response.aclose()
            position = chunk_end + 1
    finally:
        await client.aclose()


async def _passthrough(
    info: MediaInfo, media_type: str, range_header: str | None
) -> tuple[int, dict[str, str], AsyncIterator[bytes]]:
    """Fallback when the total size is unknown: forward a single upstream request."""
    client = httpx.AsyncClient(timeout=60, follow_redirects=True)
    request_headers = {"User-Agent": settings.user_agent}
    request_headers["Range"] = range_header or "bytes=0-"
    request = client.build_request("GET", info.url, headers=request_headers)
    response = await client.send(request, stream=True)

    headers = {"Accept-Ranges": "bytes", "Content-Type": info.mime}
    for header in ("content-range", "content-length"):
        value = response.headers.get(header)
        if value:
            headers[header] = value

    status = response.status_code
    if not range_header and status == 206:
        status = 200
        headers.pop("content-range", None)

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_bytes(chunk_size=65536):
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return status, headers, body()


def _parse_range(range_header: str | None, total: int) -> tuple[int, int]:
    """Parse a single-range ``bytes=`` header into an inclusive (start, end)."""
    fallback = (0, total - 1)
    if not range_header or not range_header.startswith("bytes="):
        return fallback
    spec = range_header.split("=", 1)[1].split(",", 1)[0].strip()
    if "-" not in spec:
        return fallback
    first, last = spec.split("-", 1)
    try:
        if first == "":
            suffix = max(0, min(int(last), total))
            return total - suffix, total - 1
        start = int(first)
        end = int(last) if last else total - 1
    except ValueError:
        return fallback
    start = max(0, min(start, total - 1))
    end = max(start, min(end, total - 1))
    return start, end


def _get_lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def media_mime(path: Path, media_type: str) -> str:
    return mime_for(media_type, path.suffix.lstrip("."))
