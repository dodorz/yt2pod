from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qs, urlparse

import yt_dlp

from .config import settings
from .models import Feed, Video


def extract_channel_id(url: str) -> str:
    """Extract channel ID from various YouTube URL formats."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")

    if "/channel/" in path:
        return path.split("/channel/")[1].split("/")[0]

    if "/user/" in path or "/c/" in path or path.count("/") <= 1:
        return _resolve_channel_id_from_page(url)

    if parsed.query:
        params = parse_qs(parsed.query)
        if "channel" in params:
            return params["channel"][0]

    return _resolve_channel_id_from_page(url)


def _resolve_channel_id_from_page(url: str) -> str:
    """Resolve channel ID by fetching the page and parsing metadata."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info and "channel_id" in info:
            return info["channel_id"]
        if info and "id" in info:
            return info["id"]
    raise ValueError(f"Cannot resolve channel ID from: {url}")


def fetch_feed(url: str, max_videos: int | None = None) -> Feed:
    """Fetch channel/playlist info and recent videos."""
    max_videos = max_videos or settings.max_videos

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if info is None:
        raise ValueError(f"Could not extract info from: {url}")

    channel_name = info.get("uploader") or info.get("channel") or "Unknown"
    channel_id = info.get("channel_id") or info.get("id") or ""
    channel_desc = info.get("description") or ""
    channel_thumb = info.get("thumbnail") or ""
    channel_url = info.get("channel_url") or info.get("webpage_url") or url

    videos = []
    entries = info.get("entries") or []
    for entry in entries[:max_videos]:
        if entry is None:
            continue
        vid = Video(
            id=entry.get("id", ""),
            title=entry.get("title", ""),
            description=entry.get("description") or "",
            channel_name=channel_name,
            channel_id=channel_id,
            thumbnail_url=entry.get("thumbnail") or entry.get("thumbnails", [{}])[0].get("url", "") if entry.get("thumbnails") else "",
            published_at=_parse_date(entry.get("upload_date")),
            duration=entry.get("duration"),
        )
        videos.append(vid)

    return Feed(
        channel_id=channel_id,
        channel_name=channel_name,
        channel_description=channel_desc,
        channel_thumbnail=channel_thumb,
        link=channel_url,
        videos=videos,
    )


def get_audio_url(video_id: str) -> Optional[str]:
    """Extract direct audio stream URL for a video."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio/best",
        "skip_download": True,
    }
    url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info:
            return info.get("url") or info.get("webpage_url")
    return None


def _parse_date(date_str: Optional[str]) -> datetime:
    if not date_str:
        return datetime.now(timezone.utc)
    try:
        return datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)
