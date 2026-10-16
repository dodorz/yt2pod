from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from .config import settings
from .models import Feed
from .rss import generate_rss
from .youtube import extract_channel_id, fetch_feed, normalize_media_type


class FeedScheduler:
    """Background scheduler that periodically refreshes feeds."""

    def __init__(self) -> None:
        self._feeds: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._running = False
        self._timer: threading.Timer | None = None

    def add_feed(
        self,
        url: str,
        feed_id: str | None = None,
        channel_name: str = "",
        media_type: str | None = None,
    ) -> str:
        if feed_id is None:
            feed_id = extract_channel_id(url)
        with self._lock:
            existing = self._feeds.get(feed_id, {})
            self._feeds[feed_id] = {
                "url": url,
                "last_update": existing.get("last_update"),
                "feed_id": feed_id,
                "channel_name": channel_name or existing.get("channel_name", ""),
                "media_type": normalize_media_type(
                    media_type or existing.get("media_type") or settings.default_media_type
                ),
            }
            self._save_index()
        return feed_id

    def set_media_type(self, feed_id: str, media_type: str) -> bool:
        with self._lock:
            if feed_id not in self._feeds:
                return False
            self._feeds[feed_id]["media_type"] = normalize_media_type(media_type)
            self._save_index()
        return True

    def remove_feed(self, feed_id: str) -> bool:
        with self._lock:
            if feed_id in self._feeds:
                del self._feeds[feed_id]
                self._save_index()
                return True
            return False

    def list_feeds(self) -> list[dict]:
        with self._lock:
            return list(self._feeds.values())

    def get_feed(self, feed_id: str) -> dict | None:
        with self._lock:
            feed = self._feeds.get(feed_id)
            return dict(feed) if feed else None

    def save_feed(self, feed_id: str, feed: Feed) -> None:
        """Write the generated RSS for *feed* and update the index entry."""
        rss_xml = generate_rss(feed, base_url=settings.base_url)
        feed_path = settings.feeds_dir / f"{feed_id}.xml"
        feed_path.write_text(rss_xml, encoding="utf-8")

        with self._lock:
            entry = self._feeds.setdefault(
                feed_id,
                {
                    "url": feed.link,
                    "feed_id": feed_id,
                    "channel_name": feed.channel_name,
                    "media_type": feed.media_type,
                },
            )
            entry["last_update"] = datetime.now(timezone.utc).isoformat()
            entry["channel_name"] = feed.channel_name
            entry["media_type"] = feed.media_type
            self._save_index()

    def refresh_feed(self, feed_id: str) -> Feed | None:
        with self._lock:
            if feed_id not in self._feeds:
                return None
            url = self._feeds[feed_id]["url"]
            media_type = self._feeds[feed_id].get("media_type") or settings.default_media_type

        try:
            feed = fetch_feed(url, recent_days=settings.recent_days, media_type=media_type)
            self.save_feed(feed_id, feed)
            return feed
        except Exception as e:  # noqa: BLE001 - keep scheduler alive on any failure
            print(f"Error refreshing feed {feed_id}: {e}")
            return None

    def refresh_all(self) -> dict[str, bool]:
        with self._lock:
            feed_ids = list(self._feeds.keys())

        results = {}
        for feed_id in feed_ids:
            result = self.refresh_feed(feed_id)
            results[feed_id] = result is not None
        return results

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._schedule_next()

    def stop(self) -> None:
        self._running = False
        if self._timer:
            self._timer.cancel()

    def _schedule_next(self) -> None:
        if not self._running:
            return
        self._timer = threading.Timer(settings.update_interval, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def _tick(self) -> None:
        self.refresh_all()
        self._schedule_next()

    def _save_index(self) -> None:
        index_path = settings.data_dir / "feeds_index.json"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(json.dumps(self._feeds, indent=2, ensure_ascii=False), encoding="utf-8")

    def _load_index(self) -> None:
        index_path = settings.data_dir / "feeds_index.json"
        if not index_path.exists():
            return
        try:
            loaded = json.loads(index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return

        # Migrate older index files that predate per-feed media types.
        for feed_id, entry in loaded.items():
            entry.setdefault("feed_id", feed_id)
            entry.setdefault("media_type", settings.default_media_type)
        self._feeds = loaded


scheduler = FeedScheduler()
