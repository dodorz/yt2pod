from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path


_SUBSCRIPTION_KEYWORDS = {"subscriptions", "订阅"}
_PLAYLIST_KEYWORDS = {"playlists", "播放列表"}
_YOUTUBE_KEYWORDS = {"youtube", "youtube music", "youtube 和 youtube music", "youtube and youtube music"}


def parse_takeout_csv(csv_content: str) -> list[dict[str, str]]:
    """Parse Google Takeout subscriptions.csv and return list of channels."""
    reader = csv.DictReader(io.StringIO(csv_content))
    channels = []
    for row in reader:
        channel_url = ""
        channel_name = ""
        for key in row:
            lower = key.lower().strip()
            if "url" in lower:
                channel_url = row[key].strip()
            elif "name" in lower or "title" in lower or "channel" in lower:
                channel_name = row[key].strip()

        if not channel_url:
            for key in row:
                val = row[key].strip()
                if "youtube.com" in val or "youtu.be" in val:
                    channel_url = val
                    break

        if not channel_url:
            continue

        if not channel_url.startswith("http"):
            channel_url = f"https://www.youtube.com/channel/{channel_url}"

        channels.append({"url": channel_url, "name": channel_name})
    return channels


def parse_takeout_file(file_path: Path) -> list[dict[str, str]]:
    """Parse a Google Takeout CSV or ZIP file."""
    if file_path.suffix.lower() == ".zip":
        return parse_takeout_zip(file_path)
    content = file_path.read_text(encoding="utf-8-sig")
    return parse_takeout_csv(content)


def parse_takeout_zip(zip_path: Path) -> list[dict[str, str]]:
    """Extract and parse subscription CSVs from a Google Takeout ZIP."""
    all_channels = []
    seen_urls: set[str] = set()

    with zipfile.ZipFile(zip_path, "r") as zf:
        csv_files = _find_subscription_csvs(zf)
        if not csv_files:
            csv_files = _find_any_youtube_csvs(zf)

        for csv_name in csv_files:
            content = zf.read(csv_name).decode("utf-8-sig")
            channels = parse_takeout_csv(content)
            for ch in channels:
                if ch["url"] not in seen_urls:
                    seen_urls.add(ch["url"])
                    all_channels.append(ch)

    return all_channels


def _find_subscription_csvs(zf: zipfile.ZipFile) -> list[str]:
    """Find CSV files in subscription directories."""
    results = []
    for name in zf.namelist():
        parts = Path(name).parts
        lower_parts = [p.lower() for p in parts]
        if not any(kw in lp for lp in lower_parts for kw in _SUBSCRIPTION_KEYWORDS):
            continue
        if not name.lower().endswith(".csv"):
            continue
        if any(lp.endswith(".json") for lp in lower_parts):
            continue
        results.append(name)
    return results


def _find_any_youtube_csvs(zf: zipfile.ZipFile) -> list[str]:
    """Fallback: find any CSV under a YouTube directory."""
    results = []
    for name in zf.namelist():
        parts = Path(name).parts
        lower_parts = [p.lower() for p in parts]
        if not any(kw in lp for lp in lower_parts for kw in _YOUTUBE_KEYWORDS):
            continue
        if not name.lower().endswith(".csv"):
            continue
        if any(lp.endswith(".json") for lp in lower_parts):
            continue
        results.append(name)
    return results
