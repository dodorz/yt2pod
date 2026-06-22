from __future__ import annotations

import asyncio
from typing import AsyncIterator

import httpx

from .youtube import get_audio_url

_cache: dict[str, str] = {}
_cache_ttl: dict[str, float] = {}


async def proxy_audio(video_id: str) -> AsyncIterator[bytes]:
    """Stream audio for a video through our proxy."""
    url = await _get_or_resolve_url(video_id)
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream("GET", url) as response:
            async for chunk in response.aiter_bytes(chunk_size=65536):
                yield chunk


async def _get_or_resolve_url(video_id: str) -> str:
    import time

    now = time.time()
    if video_id in _cache and now - _cache_ttl.get(video_id, 0) < 3600:
        return _cache[video_id]

    url = await asyncio.to_thread(get_audio_url, video_id)
    if not url:
        raise ValueError(f"Cannot resolve audio URL for video {video_id}")

    _cache[video_id] = url
    _cache_ttl[video_id] = now
    return url
