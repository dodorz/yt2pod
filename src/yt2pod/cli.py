from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .config import settings
from .rss import generate_rss
from .scheduler import scheduler
from .youtube import fetch_feed


def main():
    parser = argparse.ArgumentParser(
        prog="yt2pod",
        description="Convert YouTube channels to podcast RSS feeds",
    )
    sub = parser.add_subparsers(dest="command")

    cmd_serve = sub.add_parser("serve", help="Start the web server")
    cmd_serve.add_argument("--host", default=settings.host)
    cmd_serve.add_argument("--port", type=int, default=settings.port)

    cmd_gen = sub.add_parser("generate", help="Generate RSS feed to a file")
    cmd_gen.add_argument("url", help="YouTube channel or playlist URL")
    cmd_gen.add_argument("-o", "--output", default="feed.xml", help="Output file path")
    cmd_gen.add_argument("-n", "--max-videos", type=int, default=settings.max_videos)

    cmd_add = sub.add_parser("add", help="Add a feed to the scheduler")
    cmd_add.add_argument("url", help="YouTube channel or playlist URL")

    cmd_list = sub.add_parser("list", help="List scheduled feeds")
    cmd_refresh = sub.add_parser("refresh", help="Refresh all feeds")

    args = parser.parse_args()

    if args.command == "serve":
        _run_server(args.host, args.port)
    elif args.command == "generate":
        _generate_feed(args.url, args.output, args.max_videos)
    elif args.command == "add":
        _add_feed(args.url)
    elif args.command == "list":
        _list_feeds()
    elif args.command == "refresh":
        _refresh_all()
    else:
        parser.print_help()


def _run_server(host: str, port: int):
    import uvicorn
    uvicorn.run("yt2pod.app:app", host=host, port=port, reload=False)


def _generate_feed(url: str, output: str, max_videos: int):
    print(f"Fetching feed from: {url}")
    feed = fetch_feed(url, max_videos)
    rss_xml = generate_rss(feed)
    Path(output).write_text(rss_xml, encoding="utf-8")
    print(f"Feed generated: {output} ({len(feed.videos)} videos)")
    print(f"Channel: {feed.channel_name}")


def _add_feed(url: str):
    feed_id = scheduler.add_feed(url)
    feed = scheduler.refresh_feed(feed_id)
    if feed:
        print(f"Added feed: {feed.channel_name} (id: {feed_id})")
    else:
        print(f"Added feed with id: {feed_id} (refresh pending)")


def _list_feeds():
    feeds = scheduler.list_feeds()
    if not feeds:
        print("No feeds registered.")
        return
    for f in feeds:
        last = f.get("last_update", "never")
        print(f"  {f['feed_id']:30s}  {f.get('channel_name', ''):30s}  last: {last}")


def _refresh_all():
    print("Refreshing all feeds...")
    results = scheduler.refresh_all()
    for feed_id, ok in results.items():
        status = "OK" if ok else "FAILED"
        print(f"  {feed_id}: {status}")


if __name__ == "__main__":
    main()
