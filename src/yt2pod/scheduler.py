from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .config import settings
from .models import Feed
from .rss import generate_rss
from .youtube import fetch_feed


class FeedScheduler:
    """Background scheduler that periodically refreshes feeds."""

    def __init__(self) -> None:
        self._feeds: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._running = False
        self._timer: threading.Timer | None = None

    def add_feed(self, url: str, feed_id: str | None = None) -> str:
        with self._lock:
            if feed_id is None:
                feed_id = url.rsplit("/", 1)[-1] or url.rsplit("/", 2)[-2]
            self._feeds[feed_id] = {"url": url, "last_update": None, "feed_id": feed_id}
            self._save_index()
            return feed_id

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

    def refresh_feed(self, feed_id: str) -> Feed | None:
        with self._lock:
            if feed_id not in self._feeds:
                return None
            url = self._feeds[feed_id]["url"]

        try:
            feed = fetch_feed(url)
            rss_xml = generate_rss(feed)
            feed_path = settings.feeds_dir / f"{feed_id}.xml"
            feed_path.write_text(rss_xml, encoding="utf-8")

            with self._lock:
                self._feeds[feed_id]["last_update"] = datetime.now(timezone.utc).isoformat()
                self._feeds[feed_id]["channel_name"] = feed.channel_name
                self._save_index()

            return feed
        except Exception as e:
            print(f"Error refreshing feed {feed_id}: {e}")
            return None

    def refresh_all(self) -> dict[str, bool]:
        results = {}
        with self._lock:
            feed_ids = list(self._feeds.keys())

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
        if index_path.exists():
            try:
                self._feeds = json.loads(index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._feeds = {}


scheduler = FeedScheduler()
