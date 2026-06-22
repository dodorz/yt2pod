from __future__ import annotations

from xml.etree.ElementTree import Element, SubElement, tostring, register_namespace
from xml.dom.minidom import parseString

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ATOM_NS = "http://www.w3.org/2005/Atom"
CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"

register_namespace("itunes", ITUNES_NS)
register_namespace("atom", ATOM_NS)
register_namespace("content", CONTENT_NS)


def generate_rss(feed: Feed, base_url: str = "http://localhost:8000") -> str:
    """Generate a podcast-compatible RSS 2.0 XML feed."""
    rss = Element("rss", {"version": "2.0"})

    channel = SubElement(rss, "channel")
    _sub(channel, "title", feed.channel_name)
    _sub(channel, "link", feed.link)
    _sub(channel, "description", feed.channel_description)
    _sub(channel, "language", "en")
    _sub(channel, "generator", "yt2pod")

    atom_link = SubElement(channel, f"{{{ATOM_NS}}}link")
    atom_link.set("href", f"{base_url}/feeds/{feed.channel_id}.xml")
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    _sub(channel, f"{{{ITUNES_NS}}}author", feed.channel_name)
    _sub(channel, f"{{{ITUNES_NS}}}summary", feed.channel_description)
    if feed.channel_thumbnail:
        img = SubElement(channel, f"{{{ITUNES_NS}}}image")
        img.set("href", feed.channel_thumbnail)

    for video in feed.videos:
        item = SubElement(channel, "item")
        _sub(item, "title", video.title)
        _sub(item, "link", f"https://www.youtube.com/watch?v={video.id}")

        guid = SubElement(item, "guid")
        guid.set("isPermaLink", "false")
        guid.text = video.id

        _sub(item, "pubDate", video.published_at.strftime("%a, %d %b %Y %H:%M:%S +0000"))
        _sub(item, "description", video.description[:500] if video.description else video.title)

        audio_url = video.audio_url or f"{base_url}/proxy/{video.id}"
        enclosure = SubElement(item, "enclosure")
        enclosure.set("url", audio_url)
        enclosure.set("type", "audio/mpeg")
        enclosure.set("length", "0")

        if video.duration:
            _sub(item, f"{{{ITUNES_NS}}}duration", str(video.duration))

        _sub(item, f"{{{ITUNES_NS}}}explicit", "false")

        if video.thumbnail_url:
            thumb = SubElement(item, f"{{{ITUNES_NS}}}image")
            thumb.set("href", video.thumbnail_url)

    xml_str = tostring(rss, encoding="unicode", xml_declaration=False)
    raw = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str

    try:
        dom = parseString(raw)
        raw = dom.toprettyxml(indent="  ", encoding=None)
        lines = raw.split("\n")
        if lines[0].startswith("<?xml"):
            lines[0] = '<?xml version="1.0" encoding="UTF-8"?>'
        raw = "\n".join(lines)
    except Exception:
        pass

    return raw


def _sub(parent, tag, text=None):
    el = SubElement(parent, tag)
    if text is not None:
        el.text = text
    return el


from .models import Feed
