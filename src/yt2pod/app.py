from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from .config import settings
from .models import Feed
from .proxy import proxy_audio
from .rss import generate_rss
from .scheduler import scheduler
from .youtube import fetch_feed

app = FastAPI(title="YouTube2Podcast", version="0.1.0")

templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


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
    return templates.TemplateResponse("index.html", {"request": request, "feeds": feeds})


@app.post("/api/feeds")
async def add_feed(request: Request):
    body = await request.json()
    url = body.get("url", "").strip()
    if not url:
        raise HTTPException(400, "URL is required")

    feed_id = scheduler.add_feed(url)
    feed = scheduler.refresh_feed(feed_id)
    if not feed:
        raise HTTPException(500, "Failed to fetch feed")

    base_url = str(request.base_url).rstrip("/")
    return {
        "feed_id": feed_id,
        "channel_name": feed.channel_name,
        "rss_url": f"{base_url}/feeds/{feed_id}.xml",
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
    feed = scheduler.refresh_feed(feed_id)
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

    base_url = str(request.base_url).rstrip("/")
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
