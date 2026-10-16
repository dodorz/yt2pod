"""Export feeds as CSV or OPML."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from xml.etree.ElementTree import Element, SubElement, tostring


def export_csv(feeds: list[dict]) -> str:
    """Generate a CSV string with Channel Name, Channel URL and type columns."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Channel Name", "Channel URL", "Type"])
    for f in feeds:
        name = f.get("channel_name") or f.get("feed_id", "")
        writer.writerow([name, f.get("url", ""), f.get("media_type", "audio")])
    return buf.getvalue()


_MEDIA_GROUP_LABELS = {"audio": "Audio", "video": "Video"}


def export_opml(feeds: list[dict], base_url: str = "http://localhost:8000") -> str:
    """Generate an OPML 2.0 document listing all RSS feeds.

    When a mix of audio and video feeds is present they are grouped into
    ``Audio``/``Video`` folders so podcast clients that support OPML folders
    keep the two kinds separate. Each entry also carries the original YouTube
    URL as ``htmlUrl``.
    """
    opml = Element("opml", {"version": "2.0"})

    head = SubElement(opml, "head")
    SubElement(head, "title").text = "YouTube2Podcast Feeds"
    date_str = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    SubElement(head, "dateCreated").text = date_str

    body = SubElement(opml, "body")
    base = base_url.rstrip("/")

    grouped: dict[str, list[dict]] = {}
    for feed in feeds:
        grouped.setdefault(normalize_group(feed), []).append(feed)

    if len(grouped) > 1:
        for media_type in _ordered_groups(grouped):
            folder = SubElement(body, "outline")
            folder.set("text", _MEDIA_GROUP_LABELS.get(media_type, media_type.title()))
            for feed in grouped[media_type]:
                _add_outline(folder, feed, base)
    else:
        for feed in feeds:
            _add_outline(body, feed, base)

    xml_str = tostring(opml, encoding="unicode", xml_declaration=False)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str


def normalize_group(feed: dict) -> str:
    """Return the grouping key (media type) for a feed."""
    return str(feed.get("media_type") or "audio").lower().strip() or "audio"


def _ordered_groups(grouped: dict[str, list[dict]]) -> list[str]:
    known = [m for m in ("audio", "video") if m in grouped]
    extra = sorted(set(grouped) - set(known))
    return known + extra


def _add_outline(parent, feed: dict, base_url: str) -> None:
    name = feed.get("channel_name") or feed.get("feed_id", "")
    feed_id = feed.get("feed_id", "")
    outline = SubElement(parent, "outline")
    outline.set("text", name)
    outline.set("title", name)
    outline.set("type", "rss")
    outline.set("xmlUrl", f"{base_url}/feeds/{feed_id}.xml")
    html_url = feed.get("url")
    if html_url:
        outline.set("htmlUrl", html_url)
