"""Export feeds as CSV or OPML."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from xml.etree.ElementTree import Element, SubElement, tostring


def export_csv(feeds: list[dict]) -> str:
    """Generate a CSV string with Channel Name and Channel URL columns."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Channel Name", "Channel URL"])
    for f in feeds:
        name = f.get("channel_name") or f.get("feed_id", "")
        writer.writerow([name, f.get("url", "")])
    return buf.getvalue()


def export_opml(feeds: list[dict], base_url: str = "http://localhost:8000") -> str:
    """Generate an OPML 2.0 document listing all RSS feeds."""
    opml = Element("opml", {"version": "2.0"})

    head = SubElement(opml, "head")
    SubElement(head, "title").text = "YouTube2Podcast Feeds"
    date_str = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    SubElement(head, "dateCreated").text = date_str

    body = SubElement(opml, "body")
    for f in feeds:
        name = f.get("channel_name") or f.get("feed_id", "")
        feed_id = f.get("feed_id", "")
        outline = SubElement(body, "outline")
        outline.set("text", name)
        outline.set("type", "rss")
        outline.set("xmlUrl", f"{base_url.rstrip('/')}/feeds/{feed_id}.xml")

    xml_str = tostring(opml, encoding="unicode", xml_declaration=False)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str
