from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Video:
    id: str
    title: str
    description: str
    channel_name: str
    channel_id: str
    thumbnail_url: str
    published_at: datetime
    duration: Optional[int] = None
    audio_url: Optional[str] = None


@dataclass
class Feed:
    channel_id: str
    channel_name: str
    channel_description: str
    channel_thumbnail: str
    link: str
    videos: list[Video] = field(default_factory=list)
