from __future__ import annotations

import asyncio
import importlib.resources

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from .config import settings
from .export import export_csv, export_opml
from .models import Feed
from .proxy import (
    ensure_media_file,
    find_media_file,
    get_media_info,
    media_mime,
    stream_media,
)
from .rss import generate_rss
from .scheduler import scheduler
from .takeout import parse_takeout_csv, parse_takeout_zip_bytes
from .youtube import fetch_feed, normalize_media_type

app = FastAPI(
    title="YouTube2Podcast",
    version="0.1.0",
    root_path=settings.root_path,
)

_templates_dir = str(importlib.resources.files("yt2pod").parent.parent / "templates")
templates = Jinja2Templates(directory=_templates_dir)


@app.on_event("startup")
async def startup():
    scheduler._load_index()
    scheduler.start()


@app.on_event("shutdown")
async def shutdown():
    scheduler.stop()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    feeds = scheduler.list_feeds()
    return templates.TemplateResponse(
        request, "index.html",
        {"feeds": feeds, "root_path": settings.root_path},
    )


@app.post("/api/feeds")
async def add_feed(request: Request):
    body = await request.json()
    url = body.get("url", "").strip()
    if not url:
        raise HTTPException(400, "URL is required")
    media_type = normalize_media_type(body.get("media_type") or settings.default_media_type)

    try:
        feed = await asyncio.to_thread(
            fetch_feed, url, None, settings.recent_days, media_type
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Failed to fetch feed: {e}")

    feed_id = scheduler.add_feed(
        url, feed_id=feed.feed_id, channel_name=feed.channel_name, media_type=media_type
    )
    scheduler.save_feed(feed_id, feed)

    rss_url = str(request.url_for("get_feed", feed_id=feed_id))
    return {
        "feed_id": feed_id,
        "channel_name": feed.channel_name,
        "media_type": feed.media_type,
        "video_count": len(feed.videos),
        "rss_url": rss_url,
    }


@app.get("/api/feeds")
async def list_feeds():
    return scheduler.list_feeds()


@app.patch("/api/feeds/{feed_id}")
async def update_feed(feed_id: str, request: Request):
    body = await request.json()
    if "media_type" in body:
        if not scheduler.set_media_type(feed_id, body["media_type"]):
            raise HTTPException(404, "Feed not found")
    else:
        raise HTTPException(400, "No supported fields to update")

    feed = await asyncio.to_thread(scheduler.refresh_feed, feed_id)
    if not feed:
        raise HTTPException(500, "Updated but refresh failed")
    return {"ok": True, "media_type": feed.media_type, "video_count": len(feed.videos)}


@app.delete("/api/feeds/{feed_id}")
async def delete_feed(feed_id: str):
    if not scheduler.remove_feed(feed_id):
        raise HTTPException(404, "Feed not found")
    feed_path = settings.feeds_dir / f"{feed_id}.xml"
    if feed_path.exists():
        feed_path.unlink()
    return {"ok": True}


@app.post("/api/feeds/{feed_id}/refresh")
async def refresh_feed(feed_id: str):
    feed = await asyncio.to_thread(scheduler.refresh_feed, feed_id)
    if not feed:
        raise HTTPException(404, "Feed not found or refresh failed")
    return {"ok": True, "channel_name": feed.channel_name, "video_count": len(feed.videos)}


@app.get("/feeds/{feed_id}.xml")
async def get_feed(feed_id: str, request: Request):
    feed_path = settings.feeds_dir / f"{feed_id}.xml"
    if feed_path.exists():
        content = feed_path.read_text(encoding="utf-8")
        return Response(content=content, media_type="application/rss+xml")

    with scheduler._lock:
        if feed_id not in scheduler._feeds:
            raise HTTPException(404, "Feed not found")

    feed = await asyncio.to_thread(scheduler.refresh_feed, feed_id)
    if not feed:
        raise HTTPException(500, "Failed to generate feed")
    if feed_path.exists():
        content = feed_path.read_text(encoding="utf-8")
        return Response(content=content, media_type="application/rss+xml")
    return Response(content=generate_rss(feed, settings.base_url), media_type="application/rss+xml")


@app.api_route("/proxy/{video_id}", methods=["GET", "HEAD"])
async def proxy_stream(video_id: str, request: Request, type: str = "audio"):
    """Serve an episode, either from the local cache or by streaming on demand.

    In ``disk`` mode the episode is downloaded once and served as a local file
    (``FileResponse`` handles HEAD and Range). In ``stream`` mode it is relayed
    from YouTube without touching disk.
    """
    media_type = normalize_media_type(type)

    cached = find_media_file(video_id, media_type)
    if cached:
        return FileResponse(cached, media_type=media_mime(cached, media_type))

    if request.method == "HEAD":
        # Avoid downloading/relaying just to answer a size probe.
        try:
            info = await get_media_info(video_id, media_type)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"Cannot resolve media: {e}")
        headers = {"Accept-Ranges": "bytes", "Content-Type": info.mime}
        if info.filesize:
            headers["Content-Length"] = str(info.filesize)
        return Response(status_code=200, headers=headers)

    if settings.media_cache_mode.lower().strip() == "stream":
        try:
            status, headers, chunks = await stream_media(
                video_id, media_type, request.headers.get("range")
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"Cannot stream media: {e}")
        content_type = headers.pop("Content-Type", None)
        return StreamingResponse(
            chunks, status_code=status, media_type=content_type, headers=headers
        )

    try:
        path = await asyncio.to_thread(ensure_media_file, video_id, media_type)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Cannot fetch media: {e}")
    return FileResponse(path, media_type=media_mime(path, media_type))


@app.post("/api/import/preview")
async def import_preview(file: UploadFile = File(...)):  # noqa: B008
    """Parse a Takeout CSV/ZIP and return the channel list for selection."""
    if not file.filename or not file.filename.lower().endswith((".csv", ".zip")):
        raise HTTPException(400, "Please upload a CSV or ZIP file from Google Takeout")

    content = await file.read()
    if file.filename and file.filename.lower().endswith(".zip"):
        channels = parse_takeout_zip_bytes(content)
    else:
        text = content.decode("utf-8-sig")
        channels = parse_takeout_csv(text)

    if not channels:
        raise HTTPException(400, "No valid channels found in file")

    return {"channels": channels, "total": len(channels)}


@app.post("/api/import/takeout")
async def import_takeout(request: Request):
    """Import selected channels from a Takeout preview."""
    body = await request.json()
    channels = body.get("channels", [])
    if not channels or not isinstance(channels, list):
        raise HTTPException(400, "channels list is required")
    media_type = normalize_media_type(body.get("media_type") or settings.default_media_type)

    added = []
    skipped = []
    for ch in channels:
        url = ch.get("url", "")
        name = ch.get("name", "")
        if not url:
            continue
        with scheduler._lock:
            if url in [f.get("url") for f in scheduler._feeds.values()]:
                skipped.append(name or url)
                continue
        feed_id = scheduler.add_feed(url, channel_name=name, media_type=media_type)
        added.append(name or feed_id)

    return {"added": len(added), "skipped": len(skipped), "channels": added, "duplicates": skipped}


@app.get("/api/export/csv")
async def export_feeds_csv():
    """Download all registered feeds as a CSV file."""
    feeds = scheduler.list_feeds()
    if not feeds:
        raise HTTPException(404, "No feeds registered")
    csv_content = export_csv(feeds)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=feeds.csv"},
    )


@app.get("/api/export/opml")
async def export_feeds_opml(request: Request, base_url: str | None = None):
    """Download all registered feeds as an OPML file.

    Returns a valid (possibly empty) OPML document, and accepts an optional
    ``?base_url=`` override for the feed URLs (useful behind a reverse proxy).
    """
    feeds = scheduler.list_feeds()
    resolved = (base_url or str(request.base_url)).rstrip("/")
    opml_content = export_opml(feeds, resolved)
    return Response(
        content=opml_content,
        media_type="text/x-opml",
        headers={"Content-Disposition": "attachment; filename=feeds.opml"},
    )


@app.get("/api/preview")
async def preview_feed(url: str, media_type: str = "audio"):
    try:
        feed = await _fetch_feed_async(url, media_type)
        return {
            "feed_id": feed.feed_id,
            "channel_name": feed.channel_name,
            "channel_description": feed.channel_description,
            "media_type": feed.media_type,
            "video_count": len(feed.videos),
            "videos": [
                {
                    "id": v.id,
                    "title": v.title,
                    "published_at": v.published_at.isoformat() if v.published_at else None,
                    "duration": v.duration,
                }
                for v in feed.videos[:10]
            ],
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))


async def _fetch_feed_async(url: str, media_type: str = "audio") -> Feed:
    return await asyncio.to_thread(fetch_feed, url, None, settings.recent_days, media_type)
