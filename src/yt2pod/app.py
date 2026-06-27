from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import importlib.resources

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from .config import settings
from .models import Feed
from .proxy import proxy_audio
from .rss import generate_rss
from .scheduler import scheduler
from .takeout import parse_takeout_csv
from .youtube import fetch_feed

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

    feed_id = scheduler.add_feed(url)
    feed = await asyncio.to_thread(scheduler.refresh_feed, feed_id)
    if not feed:
        raise HTTPException(500, "Failed to fetch feed")

    rss_url = str(request.url_for("get_feed", feed_id=feed_id))
    return {
        "feed_id": feed_id,
        "channel_name": feed.channel_name,
        "rss_url": rss_url,
    }


@app.get("/api/feeds")
async def list_feeds():
    return scheduler.list_feeds()


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

    feed = scheduler.refresh_feed(feed_id)
    if not feed:
        raise HTTPException(500, "Failed to generate feed")

    base_url = str(request.url_for("index")).rstrip("/")
    rss_xml = generate_rss(feed, base_url)
    return Response(content=rss_xml, media_type="application/rss+xml")


@app.get("/proxy/{video_id}")
async def proxy_stream(video_id: str):
    async def audio_stream():
        async for chunk in proxy_audio(video_id):
            yield chunk

    return StreamingResponse(
        audio_stream(),
        media_type="audio/mpeg",
        headers={"Content-Disposition": f'attachment; filename="{video_id}.mp3"'},
    )


@app.post("/api/import/takeout")
async def import_takeout(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith((".csv", ".zip")):
        raise HTTPException(400, "Please upload a CSV or ZIP file from Google Takeout")

    content = await file.read()
    text = content.decode("utf-8-sig")
    channels = parse_takeout_csv(text)

    if not channels:
        raise HTTPException(400, "No valid channels found in CSV")

    added = []
    skipped = []
    for ch in channels:
        with scheduler._lock:
            if ch["url"] in [f.get("url") for f in scheduler._feeds.values()]:
                skipped.append(ch["name"] or ch["url"])
                continue
        feed_id = scheduler.add_feed(ch["url"])
        added.append(ch["name"] or feed_id)

    return {"added": len(added), "skipped": len(skipped), "channels": added, "duplicates": skipped}


@app.get("/api/preview")
async def preview_feed(url: str):
    try:
        feed = await _fetch_feed_async(url)
        return {
            "channel_name": feed.channel_name,
            "channel_description": feed.channel_description,
            "video_count": len(feed.videos),
            "videos": [
                {
                    "id": v.id,
                    "title": v.title,
                    "published_at": v.published_at.isoformat(),
                    "duration": v.duration,
                }
                for v in feed.videos[:10]
            ],
        }
    except Exception as e:
        raise HTTPException(400, str(e))


async def _fetch_feed_async(url: str) -> Feed:
    import asyncio
    return await asyncio.to_thread(fetch_feed, url)
