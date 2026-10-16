from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "YT2POD_"}

    host: str = "0.0.0.0"
    port: int = 14732
    root_path: str = ""
    base_url: str = "http://localhost:8000"
    data_dir: Path = Path("data")
    cache_ttl: int = 3600
    update_interval: int = 3600
    max_videos: int = 50
    recent_days: int = 30
    # Default enclosure kind for newly added feeds: "audio" or "video".
    default_media_type: str = "audio"
    # yt-dlp format selectors. Audio uses a single m4a stream so the proxy can
    # relay it without ffmpeg merging. Video uses a progressive mp4 stream for
    # the same reason (bestvideo+bestaudio would require a merge step).
    audio_format: str = "bestaudio[ext=m4a]/bestaudio/best"
    video_format: str = "best[ext=mp4]/best"
    # Optional Netscape-format cookies file. YouTube throttles/blocks datacenter
    # IPs and unauthenticated downloads; supplying cookies (or a working player
    # client) is often required for reliable media downloads.
    cookies_file: str = ""
    # Force a specific yt-dlp YouTube player client, e.g. "web", "ios", "tv".
    ytdlp_player_client: str = ""
    # Arbitrary extra yt-dlp options merged last, e.g.
    # YT2POD_YTDLP_OPTS='{"http_chunk_size": 1048576}'
    ytdlp_opts: dict = {}
    # How episode media is delivered:
    #   "disk"   - download each episode once into media_cache_dir, then serve the
    #              local file (fast, seekable, offline-friendly, uses disk space)
    #   "stream" - relay YouTube's stream on demand with no disk usage (best when
    #              storage is very limited; every play uses bandwidth)
    media_cache_mode: str = "disk"
    # Override where downloaded media is stored. Point this at tmpfs (e.g.
    # /dev/shm/yt2pod) or a remote mount (rclone/S3) when local disk is scarce.
    media_cache_dir: str = ""
    # In "disk" mode, delete least-recently-used episodes once the cache exceeds
    # this many bytes (0 = unlimited).
    media_cache_max_bytes: int = 0
    # In "stream" mode, size of each upstream Range request. Larger chunks mean
    # fewer requests; smaller chunks are gentler on throttled connections.
    stream_chunk_size: int = 4 * 1024 * 1024
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )

    @property
    def feeds_dir(self) -> Path:
        d = self.data_dir / "feeds"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def cache_dir(self) -> Path:
        d = self.data_dir / "cache"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def media_dir(self) -> Path:
        """Directory holding downloaded episode media, served via Range requests."""
        d = Path(self.media_cache_dir) if self.media_cache_dir else self.data_dir / "media"
        d.mkdir(parents=True, exist_ok=True)
        return d


settings = Settings()
