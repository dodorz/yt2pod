from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

import httpx
import yt_dlp

from .config import settings
from .models import Feed, Video

logger = logging.getLogger(__name__)

ATOM_NS = "{http://www.w3.org/2005/Atom}"
YT_NS = "{http://www.youtube.com/xml/schemas/2015}"
MEDIA_NS = "{http://search.yahoo.com/mrss/}"

def build_ydl_opts(**overrides) -> dict:
    """Build yt-dlp options from settings, then apply per-call overrides."""
    opts: dict = {"quiet": True, "no_warnings": True, "skip_download": True}
    if settings.cookies_file:
        opts["cookiefile"] = settings.cookies_file
    if settings.ytdlp_player_client:
        opts["extractor_args"] = {
            "youtube": {"player_client": [settings.ytdlp_player_client]}
        }
    opts.update(settings.ytdlp_opts or {})
    opts.update(overrides)
    return opts


@dataclass
class MediaInfo:
    """Resolved, directly streamable media for a single video."""

    video_id: str
    media_type: str
    url: str
    ext: str
    mime: str
    filesize: int | None = None
    duration: int | None = None
    title: str | None = None
    upload_date: str | None = None
    description: str | None = None


def is_playlist_url(url: str) -> bool:
    """Return True for YouTube playlist URLs (including watch?list=...)."""
    parsed = urlparse(url)
    if "/playlist" in parsed.path:
        return True
    params = parse_qs(parsed.query)
    return "list" in params and "/watch" in parsed.path


def normalize_url(url: str) -> str:
    """Canonicalize a YouTube URL so yt-dlp returns actual videos.

    A bare channel URL (``/@handle`` or ``/channel/ID``) makes yt-dlp return the
    channel *tabs* (Videos, Shorts, ...) as entries instead of the videos
    themselves. Pointing at the ``/videos`` tab fixes that. Playlists and
    watch URLs that reference a playlist are canonicalized to the playlist URL.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if "youtube.com" not in host and "youtu.be" not in host:
        return url

    params = parse_qs(parsed.query)
    if "list" in params and "/watch" in parsed.path:
        return f"https://www.youtube.com/playlist?list={params['list'][0]}"

    path = parsed.path.rstrip("/")
    if path.endswith(("/videos", "/streams", "/shorts", "/playlists")):
        return url

    if "/channel/" in path or "/user/" in path or "/c/" in path or "/@" in path:
        return parsed._replace(path=path + "/videos", query="", fragment="").geturl()

    return url


def extract_channel_id(url: str) -> str:
    """Extract a stable feed id (channel id or playlist id) from a YouTube URL."""
    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    path = parsed.path.rstrip("/")

    if "/channel/" in path:
        return path.split("/channel/")[1].split("/")[0]

    params = parse_qs(parsed.query)
    if "list" in params:
        return params["list"][0]

    return _resolve_channel_id_from_page(normalized)


def _resolve_channel_id_from_page(url: str) -> str:
    """Resolve a feed id by fetching the page and parsing metadata."""
    with yt_dlp.YoutubeDL(build_ydl_opts(extract_flat=True)) as ydl:
        info = ydl.extract_info(url, download=False)
    if info is None:
        raise ValueError(f"Cannot resolve channel ID from: {url}")
    if is_playlist_url(url):
        return info.get("id") or info.get("channel_id") or ""
    return info.get("channel_id") or info.get("id") or ""


def fetch_feed(
    url: str,
    max_videos: int | None = None,
    recent_days: int | None = None,
    media_type: str | None = None,
) -> Feed:
    """Fetch channel/playlist metadata and build a :class:`Feed`.

    Metadata comes from a fast flat extraction, then the latest episodes are
    enriched with accurate publish dates/descriptions from YouTube's Atom feed
    (for channels). Videos published within *recent_days* additionally have
    their streamable media resolved and warmed into the proxy cache.
    """
    max_videos = max_videos or settings.max_videos
    recent_days = settings.recent_days if recent_days is None else recent_days
    media_type = normalize_media_type(media_type or settings.default_media_type)

    normalized = normalize_url(url)
    playlist = is_playlist_url(normalized)

    opts = build_ydl_opts(extract_flat=True, playlistend=max_videos)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(normalized, download=False)

    if info is None:
        raise ValueError(f"Could not extract info from: {url}")

    channel_name = info.get("uploader") or info.get("channel") or info.get("title") or "Unknown"
    channel_id = info.get("channel_id") or info.get("id") or ""
    feed_id = (info.get("id") if playlist else channel_id) or channel_id
    channel_desc = info.get("description") or ""
    channel_thumb = _pick_thumbnail(info)
    channel_url = info.get("channel_url") or info.get("webpage_url") or url

    videos: list[Video] = []
    for entry in (info.get("entries") or [])[:max_videos]:
        if not entry:
            continue
        video_id = entry.get("id")
        if not video_id:
            continue
        videos.append(
            Video(
                id=video_id,
                title=entry.get("title") or "",
                description=entry.get("description") or "",
                channel_name=channel_name,
                channel_id=channel_id,
                thumbnail_url=_pick_thumbnail(entry),
                published_at=_parse_entry_date(entry),
                duration=_as_int(entry.get("duration")),
            )
        )

    if not playlist and channel_id:
        _enrich_from_channel_feed(channel_id, videos)

    _assign_fallback_dates(videos)

    if recent_days > 0:
        _resolve_recent(videos, recent_days, media_type)

    return Feed(
        feed_id=feed_id,
        channel_id=channel_id,
        channel_name=channel_name,
        channel_description=channel_desc,
        channel_thumbnail=channel_thumb,
        link=channel_url,
        media_type=media_type,
        videos=videos,
    )


def normalize_media_type(media_type: str) -> str:
    """Coerce an arbitrary value to ``"audio"`` or ``"video"``."""
    return "video" if str(media_type).lower().strip() == "video" else "audio"


def mime_for(media_type: str, ext: str) -> str:
    """Return the MIME type advertised for a resolved stream."""
    ext = (ext or "").lower()
    if normalize_media_type(media_type) == "video":
        return "video/webm" if ext in ("webm", "mkv") else "video/mp4"
    return {
        "m4a": "audio/mp4",
        "mp4": "audio/mp4",
        "mp3": "audio/mpeg",
        "webm": "audio/webm",
        "opus": "audio/ogg",
        "ogg": "audio/ogg",
    }.get(ext, "audio/mpeg")


def resolve_media(video_id: str, media_type: str = "audio") -> MediaInfo:
    """Resolve a directly streamable URL for a video.

    The returned URL is signed and expires within hours. It is suitable for
    relaying through the proxy, never for storing in an RSS enclosure.
    """
    media_type = normalize_media_type(media_type)
    fmt = settings.video_format if media_type == "video" else settings.audio_format
    url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(build_ydl_opts(format=fmt)) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info or not info.get("url"):
        raise ValueError(f"Cannot resolve media for video {video_id}")

    ext = info.get("ext") or ("mp4" if media_type == "video" else "m4a")
    return MediaInfo(
        video_id=video_id,
        media_type=media_type,
        url=info["url"],
        ext=ext,
        mime=mime_for(media_type, ext),
        filesize=_as_int(info.get("filesize") or info.get("filesize_approx")),
        duration=_as_int(info.get("duration")),
        title=info.get("title"),
        upload_date=info.get("upload_date"),
        description=info.get("description"),
    )


def get_audio_url(video_id: str) -> str | None:
    """Backwards-compatible helper returning only the audio stream URL."""
    try:
        return resolve_media(video_id, "audio").url
    except Exception:
        logger.debug("Could not resolve audio URL for %s", video_id, exc_info=True)
        return None


def pre_resolve_media_urls(video_ids: list[str], media_type: str = "audio") -> None:
    """Resolve media URLs and warm the proxy cache (called during refresh)."""
    from .proxy import cache_media

    for video_id in video_ids:
        try:
            cache_media(video_id, resolve_media(video_id, media_type), media_type)
        except Exception:
            logger.debug("Could not warm media cache for %s", video_id, exc_info=True)


def pre_resolve_audio_urls(video_ids: list[str]) -> None:
    """Backwards-compatible alias for :func:`pre_resolve_media_urls`."""
    pre_resolve_media_urls(video_ids, "audio")


def _resolve_recent(videos: list[Video], recent_days: int, media_type: str) -> None:
    """Warm the proxy cache and fill gaps for recently published videos."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)
    for video in videos:
        if video.published_at is None or video.published_at < cutoff:
            continue
        try:
            info = resolve_media(video.id, media_type)
        except Exception:
            logger.debug("Could not resolve media for %s", video.id, exc_info=True)
            continue
        try:
            from .proxy import cache_media

            cache_media(video.id, info, media_type)
        except Exception:
            logger.debug("Could not cache media info for %s", video.id, exc_info=True)
        if info.upload_date:
            parsed = _parse_upload_date(info.upload_date)
            if parsed:
                video.published_at = parsed
        if not video.description and info.description:
            video.description = info.description
        if video.duration is None and info.duration:
            video.duration = info.duration


def _enrich_from_channel_feed(channel_id: str, videos: list[Video]) -> None:
    """Fill publish dates/descriptions/thumbnails from YouTube's Atom feed.

    The flat playlist extraction used for speed omits these fields. A single
    request to YouTube's native feed covers the channel's latest ~15 videos.
    """
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        response = httpx.get(
            url,
            timeout=20,
            headers={"User-Agent": settings.user_agent},
            follow_redirects=True,
        )
        if response.status_code != 200:
            return
        root = ElementTree.fromstring(response.content)
    except (httpx.HTTPError, ElementTree.ParseError, ValueError):
        return

    by_id: dict[str, Video] = {v.id: v for v in videos}
    for entry in root.findall(f"{ATOM_NS}entry"):
        video_id = entry.findtext(f"{YT_NS}videoId")
        if not video_id or video_id not in by_id:
            continue
        video = by_id[video_id]

        published = _parse_iso(entry.findtext(f"{ATOM_NS}published"))
        if published:
            video.published_at = published

        group = entry.find(f"{MEDIA_NS}group")
        if group is not None:
            desc = group.findtext(f"{MEDIA_NS}description")
            if desc and not video.description:
                video.description = html.unescape(desc)
            thumb = group.find(f"{MEDIA_NS}thumbnail")
            if thumb is not None and thumb.get("url") and not video.thumbnail_url:
                video.thumbnail_url = thumb.get("url")


def _assign_fallback_dates(videos: list[Video]) -> None:
    """Give undated entries a stable, descending timestamp.

    Playlist entries are ordered newest-first, so unknown dates are estimated
    from the nearest known (or current) date so podcast clients keep ordering.
    """
    anchor: datetime | None = None
    for index, video in enumerate(videos):
        if video.published_at is None:
            if anchor is None:
                anchor = datetime.now(timezone.utc) - timedelta(minutes=index)
            else:
                anchor = anchor - timedelta(hours=1)
            video.published_at = anchor
        else:
            anchor = video.published_at


def _pick_thumbnail(info: dict) -> str:
    """Choose a reasonably sized thumbnail from a yt-dlp info/entry dict."""
    thumb = info.get("thumbnail")
    if thumb:
        return thumb
    thumbnails = info.get("thumbnails") or []
    if not thumbnails:
        return ""
    for candidate in reversed(thumbnails):
        if candidate.get("url"):
            return candidate["url"]
    return ""


def _parse_entry_date(entry: dict) -> datetime | None:
    upload_date = entry.get("upload_date")
    if upload_date:
        parsed = _parse_upload_date(str(upload_date))
        if parsed:
            return parsed
    for key in ("timestamp", "release_timestamp"):
        value = entry.get(key)
        if value:
            try:
                return datetime.fromtimestamp(int(value), tz=timezone.utc)
            except (ValueError, TypeError, OSError):
                pass
    return None


def _parse_upload_date(date_str: str) -> datetime | None:
    try:
        return datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _parse_iso(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except ValueError:
        return None


def _as_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
