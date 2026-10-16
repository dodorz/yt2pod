# YouTube2Podcast

Convert YouTube channels and playlists into podcast RSS feeds.

## Features

- **CLI**: Generate RSS feed files directly from the command line
- **Web Service**: FastAPI server with a simple web UI for managing feeds
- **Audio or video podcasts**: Publish each feed as an audio-only or video podcast
- **Range-capable media delivery**: Either download each episode once into a local
  cache (disk mode) or relay it on demand with **zero disk usage** (stream mode).
  Both support HTTP Range/HEAD (seeking, resumable playback), and RSS never
  contains expiring YouTube URLs
- **Scheduled Updates**: Auto-refresh feeds at configurable intervals
- **Google Takeout import / CSV + OPML export**

## Usage

All commands use `uv run` from the project root.

### Web Server

```bash
uv run yt2pod serve
# or with custom host/port
uv run yt2pod serve --host 0.0.0.0 --port 8000
```

Open http://localhost:14732 to add and manage feeds.

### CLI - Generate RSS File

```bash
uv run yt2pod generate https://www.youtube.com/@channelname -o feed.xml
uv run yt2pod generate https://www.youtube.com/playlist?list=PLxxx -o playlist.xml -n 20
# Video podcast
uv run yt2pod generate https://www.youtube.com/@channelname -o feed.xml --type video
```

### CLI - Manage Scheduled Feeds

```bash
uv run yt2pod add https://www.youtube.com/@channelname
uv run yt2pod add https://www.youtube.com/@channelname --type video
uv run yt2pod list
uv run yt2pod refresh
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
| `YT2POD_DEFAULT_MEDIA_TYPE` | `audio` | Default podcast format (`audio` or `video`) |
| `YT2POD_COOKIES_FILE` | - | Netscape cookies file for yt-dlp (helps with YouTube throttling) |
| `YT2POD_YTDLP_PLAYER_CLIENT` | - | Force a yt-dlp YouTube player client (e.g. `web`, `ios`, `tv`) |
| `YT2POD_YTDLP_OPTS` | `{}` | Extra yt-dlp options as JSON, e.g. `{"http_chunk_size": 1048576}` |
| `YT2POD_MEDIA_CACHE_MODE` | `disk` | `disk` (cache locally) or `stream` (no disk usage) |
| `YT2POD_MEDIA_CACHE_DIR` | `<data>/media` | Media location; point at tmpfs or a remote mount |
| `YT2POD_MEDIA_CACHE_MAX_BYTES` | `0` | In disk mode, evict least-recently-used episodes above this size (0 = unlimited) |
| `YT2POD_STREAM_CHUNK_SIZE` | `4194304` | In stream mode, bytes per upstream Range request |

## How It Works

1. Provide a YouTube channel URL or playlist URL (choose audio or video)
2. `yt-dlp` extracts metadata; recent publish dates/descriptions are enriched from
   YouTube's native Atom feed
3. A podcast-compatible RSS 2.0 feed is generated with `<itunes>` tags
4. Media is delivered by the proxy with HTTP Range support, in one of two modes:
   - `disk` (default): the episode is downloaded once into `data/media/` and served
     locally, so repeat plays and seeking are instant.
   - `stream`: the episode is relayed from YouTube on demand and **nothing is
     written to disk** — ideal on very small disks. Add `YT2POD_MEDIA_CACHE_MAX_BYTES`
     to cap the disk cache, or set `YT2POD_MEDIA_CACHE_DIR=/dev/shm/yt2pod` to keep
     it entirely in RAM.
5. Add the RSS URL to any podcast app (Apple Podcasts, Overcast, etc.)

> YouTube throttles or blocks downloads from datacenter/VPN IPs. If downloads fail
> with HTTP 403, set `YT2POD_COOKIES_FILE` to a logged-in cookies file and/or
> `YT2POD_YTDLP_PLAYER_CLIENT`.

## RSS Feed URL

Once registered, your podcast feed URL is:

```
http://localhost:8000/feeds/{feed_id}.xml
```

Media proxy (used by the RSS enclosure; `type` is `audio` or `video`):

```
http://localhost:8000/proxy/{video_id}?type=audio
```

## Requirements

- Python 3.10+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) (installed as dependency)
