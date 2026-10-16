from __future__ import annotations

from datetime import datetime, timezone
from xml.dom.minidom import parseString
from xml.etree.ElementTree import Element, SubElement, register_namespace, tostring

from .models import Feed, Video
from .youtube import mime_for, normalize_media_type

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ATOM_NS = "http://www.w3.org/2005/Atom"
CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"

register_namespace("itunes", ITUNES_NS)
register_namespace("atom", ATOM_NS)
register_namespace("content", CONTENT_NS)

_DEFAULT_CATEGORY = "Technology"


def generate_rss(feed: Feed, base_url: str = "http://localhost:8000") -> str:
    """Generate a podcast-compatible RSS 2.0 XML feed.

    Enclosures point at the local proxy (``/proxy/{id}?type=...``) so the feed
    never exposes expiring YouTube URLs. The MIME type follows the feed's
    ``media_type`` (audio or video).
    """
    base_url = base_url.rstrip("/")
    media_type = normalize_media_type(feed.media_type)
    enclosure_mime = mime_for(media_type, "mp4" if media_type == "video" else "m4a")
    build_date = datetime.now(timezone.utc)

    rss = Element("rss", {"version": "2.0"})
    channel = SubElement(rss, "channel")

    _sub(channel, "title", feed.channel_name)
    _sub(channel, "link", feed.link)
    _sub(channel, "description", feed.channel_description or feed.channel_name)
    _sub(channel, "language", "en")
    _sub(channel, "generator", "yt2pod")
    _sub(channel, "lastBuildDate", _rfc2822(build_date))

    atom_link = SubElement(channel, f"{{{ATOM_NS}}}link")
    atom_link.set("href", f"{base_url}/feeds/{feed.feed_id}.xml")
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    _sub(channel, f"{{{ITUNES_NS}}}author", feed.channel_name)
    _sub(channel, f"{{{ITUNES_NS}}}summary", feed.channel_description or feed.channel_name)
    _sub(channel, f"{{{ITUNES_NS}}}explicit", "false")
    _sub(channel, f"{{{ITUNES_NS}}}type", "episodic")
    category = SubElement(channel, f"{{{ITUNES_NS}}}category")
    category.set("text", _DEFAULT_CATEGORY)
    if feed.channel_thumbnail:
        img = SubElement(channel, f"{{{ITUNES_NS}}}image")
        img.set("href", feed.channel_thumbnail)

    for index, video in enumerate(feed.videos):
        _add_item(channel, video, feed, base_url, enclosure_mime, len(feed.videos) - index - 1)

    xml_str = tostring(rss, encoding="unicode", xml_declaration=False)
    raw = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str

    try:
        dom = parseString(raw)
        raw = dom.toprettyxml(indent="  ")
        lines = raw.split("\n")
        if lines[0].startswith("<?xml"):
            lines[0] = '<?xml version="1.0" encoding="UTF-8"?>'
        raw = "\n".join(line for line in lines if line.strip())
    except Exception:  # noqa: BLE001, S110 - pretty printing is cosmetic
        pass

    return raw


def _add_item(channel, video: Video, feed: Feed, base_url: str, enclosure_mime: str, episode: int):
    item = SubElement(channel, "item")
    _sub(item, "title", video.title)
    _sub(item, "link", f"https://www.youtube.com/watch?v={video.id}")

    guid = SubElement(item, "guid")
    guid.set("isPermaLink", "false")
    guid.text = video.id

    if video.published_at is not None:
        _sub(item, "pubDate", _rfc2822(video.published_at))

    description = video.description or video.title
    _sub(item, "description", description[:1000])
    _sub(item, f"{{{CONTENT_NS}}}encoded", description)

    enclosure = SubElement(item, "enclosure")
    enclosure.set("url", f"{base_url}/proxy/{video.id}?type={feed.media_type}")
    enclosure.set("type", enclosure_mime)
    # Unknown until the proxy resolves the stream; podcast clients rely on the
    # proxy's Content-Length/Range headers for seeking.
    enclosure.set("length", "0")

    if video.duration:
        _sub(item, f"{{{ITUNES_NS}}}duration", _format_duration(video.duration))

    _sub(item, f"{{{ITUNES_NS}}}explicit", "false")
    _sub(item, f"{{{ITUNES_NS}}}episode", str(episode))

    if video.thumbnail_url:
        thumb = SubElement(item, f"{{{ITUNES_NS}}}image")
        thumb.set("href", video.thumbnail_url)


def _format_duration(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _rfc2822(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")


def _sub(parent, tag, text=None):
    el = SubElement(parent, tag)
    if text is not None:
        el.text = text
    return el
