from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "YT2POD_"}

    host: str = "0.0.0.0"
    port: int = 14732
    data_dir: Path = Path("data")
    cache_ttl: int = 3600
    update_interval: int = 3600
    max_videos: int = 50
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


settings = Settings()
