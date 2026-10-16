from __future__ import annotations

import asyncio
import io
import json
import os
import zipfile
from datetime import datetime, timezone
from xml.etree import ElementTree

from yt2pod.export import export_csv, export_opml
from yt2pod.models import Feed, Video
from yt2pod.rss import generate_rss
from yt2pod.takeout import parse_takeout_csv, parse_takeout_zip_bytes
from yt2pod.youtube import (
    is_playlist_url,
    mime_for,
    normalize_media_type,
    normalize_url,
)


def _sample_feed(media_type: str = "audio") -> Feed:
    return Feed(
        feed_id="UCabc",
        channel_id="UCabc",
        channel_name="Test Channel",
        channel_description="A channel",
        channel_thumbnail="https://img/cover.jpg",
        link="https://www.youtube.com/channel/UCabc",
        media_type=media_type,
        videos=[
            Video(
                id="vid1",
                title="Episode 1",
                description="Hello & goodbye",
                channel_name="Test Channel",
                channel_id="UCabc",
                thumbnail_url="https://img/1.jpg",
                published_at=datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
                duration=3725,
            )
        ],
    )


class TestNormalizeUrl:
    def test_channel_gets_videos_tab(self):
        assert normalize_url("https://www.youtube.com/@Foo") == (
            "https://www.youtube.com/@Foo/videos"
        )
        assert normalize_url("https://www.youtube.com/channel/UCabc") == (
            "https://www.youtube.com/channel/UCabc/videos"
        )

    def test_existing_tab_untouched(self):
        url = "https://www.youtube.com/@Foo/videos"
        assert normalize_url(url) == url

    def test_watch_with_playlist_becomes_playlist(self):
        assert normalize_url("https://www.youtube.com/watch?v=x&list=PL1") == (
            "https://www.youtube.com/playlist?list=PL1"
        )
        assert is_playlist_url("https://www.youtube.com/watch?v=x&list=PL1")

    def test_plain_playlist(self):
        url = "https://www.youtube.com/playlist?list=PL1"
        assert normalize_url(url) == url
        assert is_playlist_url(url)

    def test_non_youtube_untouched(self):
        assert normalize_url("https://example.com/feed") == "https://example.com/feed"


class TestMime:
    def test_audio_mime(self):
        assert mime_for("audio", "m4a") == "audio/mp4"
        assert mime_for("audio", "mp3") == "audio/mpeg"

    def test_video_mime(self):
        assert mime_for("video", "mp4") == "video/mp4"
        assert mime_for("video", "webm") == "video/webm"

    def test_normalize_media_type(self):
        assert normalize_media_type("VIDEO") == "video"
        assert normalize_media_type("audio") == "audio"
        assert normalize_media_type("") == "audio"


class TestRss:
    def _root(self, media_type="audio"):
        xml = generate_rss(_sample_feed(media_type), base_url="http://feed.test/")
        return ElementTree.fromstring(xml)

    def test_enclosure_audio(self):
        root = self._root("audio")
        ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
        enclosure = root.find(".//item/enclosure")
        assert enclosure.get("url") == "http://feed.test/proxy/vid1?type=audio"
        assert enclosure.get("type") == "audio/mp4"
        duration = root.find(".//item/itunes:duration", ns)
        assert duration.text == "01:02:05"

    def test_enclosure_video(self):
        root = self._root("video")
        enclosure = root.find(".//item/enclosure")
        assert enclosure.get("url") == "http://feed.test/proxy/vid1?type=video"
        assert enclosure.get("type") == "video/mp4"

    def test_channel_metadata(self):
        root = self._root()
        ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
        assert root.findtext(".//channel/title") == "Test Channel"
        assert root.findtext(".//channel/lastBuildDate")
        assert root.findtext(".//channel/itunes:type", namespaces=ns) == "episodic"

    def test_xml_is_well_formed_with_ampersand(self):
        xml = generate_rss(_sample_feed(), base_url="http://feed.test")
        ElementTree.fromstring(xml)


class TestTakeout:
    def test_csv_parsing(self):
        content = (
            "Channel ID,Channel URL,Channel Title\n"
            "UC1,https://www.youtube.com/channel/UC1,Alpha\n"
        )
        channels = parse_takeout_csv(content)
        assert channels == [{"url": "https://www.youtube.com/channel/UC1", "name": "Alpha"}]

    def test_zip_parsing_deduplicates(self):
        csv_bytes = (
            b"Channel ID,Channel URL,Channel Title\nUC1,https://www.youtube.com/channel/UC1,Alpha\n"
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("Takeout/YouTube and YouTube Music/subscriptions/subscriptions.csv", csv_bytes)
            zf.writestr("Takeout/YouTube and YouTube Music/playlists/playlists.csv", csv_bytes)
        channels = parse_takeout_zip_bytes(buffer.getvalue())
        assert len(channels) == 1
        assert channels[0]["name"] == "Alpha"


class TestExport:
    def test_csv_has_type_column(self):
        feeds = [{"channel_name": "A", "url": "u", "media_type": "video"}]
        out = export_csv(feeds)
        assert "Channel Name" in out and "Type" in out and "video" in out

    def test_opml(self):
        feeds = [{"feed_id": "UC1", "channel_name": "A"}]
        out = export_opml(feeds, "http://x")
        assert 'xmlUrl="http://x/feeds/UC1.xml"' in out

    def test_opml_empty_is_valid(self):
        root = ElementTree.fromstring(export_opml([], "http://x"))
        assert root.tag == "opml"
        assert root.find("body") is not None

    def test_opml_groups_audio_and_video(self):
        feeds = [
            {"feed_id": "A", "channel_name": "A", "media_type": "audio", "url": "https://yt/a"},
            {"feed_id": "V", "channel_name": "V", "media_type": "video", "url": "https://yt/v"},
        ]
        out = export_opml(feeds, "http://x")
        root = ElementTree.fromstring(out)
        folders = {o.get("text") for o in root.find("body").findall("outline")}
        assert folders == {"Audio", "Video"}
        assert 'htmlUrl="https://yt/a"' in out
        assert 'type="rss"' in out

    def test_opml_single_type_is_flat(self):
        feeds = [
            {"feed_id": "A", "channel_name": "A", "media_type": "audio"},
            {"feed_id": "B", "channel_name": "B", "media_type": "audio"},
        ]
        root = ElementTree.fromstring(export_opml(feeds, "http://x"))
        body = root.find("body")
        outlines = body.findall("outline")
        assert len(outlines) == 2
        assert all(o.get("type") == "rss" for o in outlines)


class TestSchedulerIndexMigration:
    def test_scheduler_migrates_old_index(self, tmp_path, monkeypatch):
        from yt2pod import config
        from yt2pod.scheduler import FeedScheduler

        monkeypatch.setattr(config.settings, "data_dir", tmp_path)
        (tmp_path / "feeds_index.json").write_text(
            json.dumps({"UC1": {"url": "u", "last_update": None, "feed_id": "UC1"}})
        )
        sched = FeedScheduler()
        sched._load_index()
        feed = sched.get_feed("UC1")
        assert feed["media_type"] == config.settings.default_media_type


class TestProxyFileLookup:
    def test_find_media_file(self, tmp_path, monkeypatch):
        from yt2pod import config
        from yt2pod.proxy import find_media_file

        monkeypatch.setattr(config.settings, "data_dir", tmp_path)
        audio_dir = tmp_path / "media" / "audio"
        audio_dir.mkdir(parents=True)
        (audio_dir / "vid1.m4a").write_bytes(b"x")
        (audio_dir / "vid1.part").write_bytes(b"x")
        found = find_media_file("vid1", "audio")
        assert found is not None and found.suffix == ".m4a"


class TestRangeParsing:
    def test_open_ended(self):
        from yt2pod.proxy import _parse_range

        assert _parse_range("bytes=100-", 1000) == (100, 999)

    def test_closed(self):
        from yt2pod.proxy import _parse_range

        assert _parse_range("bytes=0-99", 1000) == (0, 99)

    def test_suffix(self):
        from yt2pod.proxy import _parse_range

        assert _parse_range("bytes=-100", 1000) == (900, 999)

    def test_clamped_and_missing(self):
        from yt2pod.proxy import _parse_range

        assert _parse_range("bytes=500-2000", 1000) == (500, 999)
        assert _parse_range(None, 1000) == (0, 999)
        assert _parse_range("garbage", 1000) == (0, 999)


class TestStreamHeaders:
    def _info(self):
        from yt2pod.proxy import MediaInfo

        return MediaInfo(
            video_id="v", media_type="audio", url="http://upstream", ext="m4a",
            mime="audio/mp4", filesize=1000,
        )

    def _run(self, monkeypatch, range_header):
        from yt2pod import proxy

        async def fake_info(*_args, **_kwargs):
            return self._info()

        async def fake_iter(*_args, **_kwargs):
            if False:  # pragma: no cover - empty async generator
                yield b""

        monkeypatch.setattr(proxy, "get_media_info", fake_info)
        monkeypatch.setattr(proxy, "_iter_ranges", fake_iter)
        return asyncio.run(proxy.stream_media("v", "audio", range_header))

    def test_full_request_has_content_length(self, monkeypatch):
        status, headers, _body = self._run(monkeypatch, None)
        assert status == 200
        assert headers["Content-Length"] == "1000"
        assert "Content-Range" not in headers

    def test_range_request_is_206(self, monkeypatch):
        status, headers, _body = self._run(monkeypatch, "bytes=0-99")
        assert status == 206
        assert headers["Content-Range"] == "bytes 0-99/1000"
        assert headers["Content-Length"] == "100"


class TestSafeChunkSize:
    def test_never_covers_whole_file(self):
        from yt2pod.proxy import _safe_chunk_size

        # A 3 MiB file with a 4 MiB chunk must be split, not requested whole.
        total = 3 * 1024 * 1024
        assert _safe_chunk_size(4 * 1024 * 1024, total) < total

    def test_small_file_split_in_two(self):
        from yt2pod.proxy import _safe_chunk_size

        assert _safe_chunk_size(1000, 10) == 5

    def test_large_file_uses_requested(self):
        from yt2pod.proxy import _safe_chunk_size

        assert _safe_chunk_size(1000, 10000) == 1000


class TestCacheEviction:
    def test_lru_eviction(self, tmp_path, monkeypatch):
        from yt2pod import config, proxy

        monkeypatch.setattr(config.settings, "data_dir", tmp_path)
        monkeypatch.setattr(config.settings, "media_cache_max_bytes", 10)
        audio_dir = tmp_path / "media" / "audio"
        audio_dir.mkdir(parents=True)
        old = audio_dir / "old.m4a"
        old.write_bytes(b"x" * 10)
        os.utime(old, (1, 1))
        new = audio_dir / "new.m4a"
        new.write_bytes(b"y" * 10)
        os.utime(new, (2, 2))

        proxy._enforce_cache_limit(keep=new)
        assert new.exists()
        assert not old.exists()
