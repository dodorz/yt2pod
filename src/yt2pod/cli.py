from __future__ import annotations

import argparse
from pathlib import Path

from .config import settings
from .export import export_csv, export_opml
from .rss import generate_rss
from .scheduler import scheduler
from .takeout import parse_takeout_file
from .youtube import fetch_feed, normalize_media_type


def main():
    parser = argparse.ArgumentParser(
        prog="yt2pod",
        description="Convert YouTube channels to podcast RSS feeds",
    )
    sub = parser.add_subparsers(dest="command")

    cmd_serve = sub.add_parser("serve", help="Start the web server")
    cmd_serve.add_argument("--host", default=settings.host)
    cmd_serve.add_argument("--port", type=int, default=settings.port)
    cmd_serve.add_argument("--root-path", default=settings.root_path,
                           help="URL path prefix for reverse proxy (e.g. /yt2pod)")

    cmd_gen = sub.add_parser("generate", help="Generate RSS feed to a file")
    cmd_gen.add_argument("url", help="YouTube channel or playlist URL")
    cmd_gen.add_argument("-o", "--output", default="feed.xml", help="Output file path")
    cmd_gen.add_argument("-n", "--max-videos", type=int, default=settings.max_videos)
    cmd_gen.add_argument("--recent-days", type=int, default=settings.recent_days,
                         help="Enrich/resolve videos within this many days (0 to disable)")
    cmd_gen.add_argument("--base-url", default=settings.base_url,
                         help=f"Base URL for enclosure links (default: {settings.base_url})")
    cmd_gen.add_argument("--type", dest="media_type", choices=["audio", "video"],
                         default=settings.default_media_type,
                         help="Publish as an audio or video podcast (default: %(default)s)")

    cmd_add = sub.add_parser("add", help="Add a feed to the scheduler")
    cmd_add.add_argument("url", help="YouTube channel or playlist URL")
    cmd_add.add_argument("--type", dest="media_type", choices=["audio", "video"],
                         default=settings.default_media_type,
                         help="Publish as an audio or video podcast (default: %(default)s)")

    cmd_import = sub.add_parser("import-takeout", help="Import subscriptions from Google Takeout CSV")
    cmd_import.add_argument("csv_file", help="Path to subscriptions.csv from Google Takeout")
    cmd_import.add_argument("-a", "--all", action="store_true", help="Import all channels without prompting")

    cmd_export_csv = sub.add_parser("export-csv", help="Export feeds as CSV")
    cmd_export_csv.add_argument("-o", "--output", default="feeds.csv", help="Output file path")

    cmd_export_opml = sub.add_parser("export-opml", help="Export feeds as OPML")
    cmd_export_opml.add_argument("-o", "--output", default="feeds.opml", help="Output file path")
    cmd_export_opml.add_argument("--base-url", default="http://localhost:8000",
                                 help="Base URL for RSS feed links (default: http://localhost:8000)")

    sub.add_parser("list", help="List scheduled feeds")
    sub.add_parser("refresh", help="Refresh all feeds")

    args = parser.parse_args()

    if args.command == "serve":
        _run_server(args.host, args.port, root_path=getattr(args, "root_path", ""))
    elif args.command == "generate":
        _generate_feed(args.url, args.output, args.max_videos, args.recent_days,
                       args.base_url, args.media_type)
    elif args.command == "add":
        _add_feed(args.url, args.media_type)
    elif args.command == "import-takeout":
        _import_takeout(args.csv_file, import_all=args.all)
    elif args.command == "export-csv":
        _export_csv_cmd(args.output)
    elif args.command == "export-opml":
        _export_opml_cmd(args.output, args.base_url)
    elif args.command == "list":
        _list_feeds()
    elif args.command == "refresh":
        _refresh_all()
    else:
        parser.print_help()


def _run_server(host: str, port: int, root_path: str = ""):
    import uvicorn
    # Update the settings singleton so uvicorn's fresh import reads the correct value
    settings.root_path = root_path
    uvicorn.run(
        "yt2pod.app:app",
        host=host,
        port=port,
        reload=False,
        proxy_headers=bool(root_path),
    )


def _generate_feed(url: str, output: str, max_videos: int, recent_days: int = 30,
                   base_url: str = "", media_type: str = "audio"):
    base_url = base_url or settings.base_url
    media_type = normalize_media_type(media_type)
    print(f"Fetching feed from: {url} ({media_type})")
    feed = fetch_feed(url, max_videos, recent_days=recent_days, media_type=media_type)
    rss_xml = generate_rss(feed, base_url=base_url)
    Path(output).write_text(rss_xml, encoding="utf-8")
    print(f"Feed generated: {output} ({len(feed.videos)} videos)")
    print(f"Channel: {feed.channel_name}")


def _add_feed(url: str, media_type: str = "audio"):
    media_type = normalize_media_type(media_type)
    feed = fetch_feed(url, recent_days=settings.recent_days, media_type=media_type)
    feed_id = scheduler.add_feed(
        url, feed_id=feed.feed_id, channel_name=feed.channel_name, media_type=media_type
    )
    scheduler.save_feed(feed_id, feed)
    print(f"Added feed: {feed.channel_name} (id: {feed_id}, type: {feed.media_type})")


def _import_takeout(csv_path: str, import_all: bool = False):
    path = Path(csv_path)
    if not path.exists():
        print(f"Error: File not found: {csv_path}")
        return

    channels = parse_takeout_file(path)
    if not channels:
        print("No valid channels found in CSV file.")
        return

    print(f"Found {len(channels)} channels in CSV.\n")

    if import_all:
        selected = list(range(len(channels)))
    else:
        selected = _interactive_select(channels)

    if not selected:
        print("No channels selected. Aborting.")
        return

    print()
    added = 0
    skipped = 0
    for idx in selected:
        ch = channels[idx]
        with scheduler._lock:
            if ch["url"] in [f.get("url") for f in scheduler._feeds.values()]:
                print(f"  Skip (duplicate): {ch['name'] or ch['url']}")
                skipped += 1
                continue
        feed_id = scheduler.add_feed(ch["url"], channel_name=ch["name"])
        print(f"  Added: {ch['name'] or feed_id} (id: {feed_id})")
        added += 1

    print(f"\nDone: {added} added, {skipped} skipped (duplicates).")


def _interactive_select(channels: list[dict[str, str]]) -> list[int]:
    """Show channel list and let user select which to import."""
    for i, ch in enumerate(channels, 1):
        name = ch["name"] or "(no title)"
        url = ch["url"]
        # Keep display compact
        if len(url) > 60:
            url = url[:57] + "..."
        print(f"  {i:3d}. {name[:40]:40s}  {url}")

    print()
    print("Enter numbers to select (e.g. 1,3,5-8), 'all', or 'none': ", end="")
    try:
        raw = input().strip()
    except (EOFError, KeyboardInterrupt):
        return []

    if raw.lower() in ("", "none", "n"):
        return []
    if raw.lower() in ("all", "a"):
        return list(range(len(channels)))

    selected = []
    for part in raw.replace(" ", "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                selected.extend(range(int(a) - 1, int(b)))
            except (ValueError, IndexError):
                print(f"  Warning: invalid range '{part}', skipping")
        else:
            try:
                selected.append(int(part) - 1)
            except ValueError:
                print(f"  Warning: invalid number '{part}', skipping")

    # Deduplicate, sort, and clamp to valid range
    return sorted({i for i in selected if 0 <= i < len(channels)})


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


def _export_csv_cmd(output: str):
    feeds = scheduler.list_feeds()
    if not feeds:
        print("No feeds registered.")
        return
    csv_content = export_csv(feeds)
    Path(output).write_text(csv_content, encoding="utf-8")
    print(f"Exported {len(feeds)} feeds to {output}")


def _export_opml_cmd(output: str, base_url: str):
    feeds = scheduler.list_feeds()
    if not feeds:
        print("No feeds registered.")
        return
    opml_content = export_opml(feeds, base_url)
    Path(output).write_text(opml_content, encoding="utf-8")
    print(f"Exported {len(feeds)} feeds to {output}")


if __name__ == "__main__":
    main()
