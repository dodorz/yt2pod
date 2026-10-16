from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Video:
    id: str
    title: str
    description: str
    channel_name: str
    channel_id: str
    thumbnail_url: str
    published_at: datetime | None = None
    duration: int | None = None
    audio_url: str | None = None


@dataclass
class Feed:
    # ``feed_id`` is the stable identifier used in the feed URL and filenames
    # (a YouTube channel id or playlist id). ``channel_id`` may be the uploader
    # channel for playlist feeds, hence the two are tracked separately.
    feed_id: str
    channel_id: str
    channel_name: str
    channel_description: str
    channel_thumbnail: str
    link: str
    media_type: str = "audio"
    videos: list[Video] = field(default_factory=list)
