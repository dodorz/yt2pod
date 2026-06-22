# YouTube2Podcast

Convert YouTube channels and playlists into podcast RSS feeds.

## Features

- **CLI**: Generate RSS feed files directly from the command line
- **Web Service**: FastAPI server with a simple web UI for managing feeds
- **Audio Proxy**: Stream audio through the server (no direct YouTube links in RSS)
- **Scheduled Updates**: Auto-refresh feeds at configurable intervals

## Usage

All commands use `uv run` from the project root.

### Web Server

```bash
uv run --directory . yt2pod serve
# or with custom host/port
uv run --directory . yt2pod serve --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 to add and manage feeds.

### CLI - Generate RSS File

```bash
uv run --directory . yt2pod generate https://www.youtube.com/@channelname -o feed.xml
uv run --directory . yt2pod generate https://www.youtube.com/playlist?list=PLxxx -o playlist.xml -n 20
```

### CLI - Manage Scheduled Feeds

```bash
uv run --directory . yt2pod add https://www.youtube.com/@channelname
uv run --directory . yt2pod list
uv run --directory . yt2pod refresh
```

## Configuration

Environment variables (prefix `YT2POD_`):

| Variable | Default | Description |
|---|---|---|
| `YT2POD_HOST` | `0.0.0.0` | Server bind host |
| `YT2POD_PORT` | `8000` | Server bind port |
| `YT2POD_DATA_DIR` | `data` | Data storage directory |
| `YT2POD_MAX_VIDEOS` | `50` | Max videos per feed |
| `YT2POD_UPDATE_INTERVAL` | `3600` | Auto-refresh interval (seconds) |

## How It Works

1. Provide a YouTube channel URL or playlist URL
2. `yt-dlp` extracts video metadata from YouTube
3. A podcast-compatible RSS 2.0 feed is generated with `<itunes>` tags
4. Audio is proxied through the server on-demand (no pre-download needed)
5. Add the RSS URL to any podcast app (Apple Podcasts, Overcast, etc.)

## RSS Feed URL

Once registered, your podcast feed URL is:

```
http://localhost:8000/feeds/{feed_id}.xml
```

For audio proxy (recommended for podcast apps):

```
http://localhost:8000/proxy/{video_id}
```

## Requirements

- Python 3.10+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) (installed as dependency)
