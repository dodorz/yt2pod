# YouTube2Podcast

将YouTube频道和播放列表转换为播客RSS订阅源。

## 功能特点

- **命令行界面 (CLI)**：直接从命令行生成RSS订阅源文件
- **Web服务**：基于FastAPI的服务器，提供简洁的Web界面来管理订阅源
- **音频或视频播客**：每个订阅源可发布为纯音频或视频播客
- **支持 Range 的媒体分发**：可选「磁盘缓存」模式（首次播放下载一次）或「流式」
  模式（**零磁盘占用**，按需转发）。两者都支持 HTTP Range/HEAD（拖拽进度、断点续传），
  RSS 中不包含会过期的 YouTube 链接
- **定时更新**：在可配置的时间间隔内自动刷新订阅源
- **支持 Google Takeout 导入 / CSV + OPML 导出**（OPML 按音频/视频分组）

## 使用方法

所有命令都在项目根目录使用 `uv run` 执行。

### Web 服务器

```bash
uv run --directory . yt2pod serve
# or with custom host/port
uv run --directory . yt2pod serve --host 0.0.0.0 --port 8000
```

打开 http://localhost:14732 以添加和管理订阅源。

### CLI - 生成 RSS 文件

```bash
uv run --directory . yt2pod generate https://www.youtube.com/@channelname -o feed.xml
uv run --directory . yt2pod generate https://www.youtube.com/playlist?list=PLxxx -o playlist.xml -n 20
# 视频播客
uv run --directory . yt2pod generate https://www.youtube.com/@channelname -o feed.xml --type video
```

### CLI - 管理定时订阅源

```bash
uv run --directory . yt2pod add https://www.youtube.com/@channelname
uv run --directory . yt2pod add https://www.youtube.com/@channelname --type video
uv run --directory . yt2pod list
uv run --directory . yt2pod refresh
```

## 配置

环境变量（前缀 `YT2POD_`）：

| 变量 | 默认值 | 描述 |
|---|---|---|
| `YT2POD_HOST` | `0.0.0.0` | 服务器绑定主机 |
| `YT2POD_PORT` | `8000` | 服务器绑定端口 |
| `YT2POD_DATA_DIR` | `data` | 数据存储目录 |
| `YT2POD_MAX_VIDEOS` | `50` | 每个订阅源的最大视频数 |
| `YT2POD_UPDATE_INTERVAL` | `3600` | 自动刷新间隔（秒） |
| `YT2POD_DEFAULT_MEDIA_TYPE` | `audio` | 新订阅源默认格式（`audio` 或 `video`） |
| `YT2POD_COOKIES_FILE` | - | yt-dlp 使用的 Netscape cookies 文件（应对 YouTube 限流） |
| `YT2POD_YTDLP_PLAYER_CLIENT` | - | 强制指定 yt-dlp YouTube 播放器客户端（如 `web`、`ios`、`tv`） |
| `YT2POD_YTDLP_OPTS` | `{}` | 额外 yt-dlp 选项（JSON），例如 `{"http_chunk_size": 1048576}` |
| `YT2POD_MEDIA_CACHE_MODE` | `disk` | `disk`（本地缓存）或 `stream`（零磁盘占用） |
| `YT2POD_MEDIA_CACHE_DIR` | `<data>/media` | 媒体存放位置，可指向 tmpfs 或远端挂载 |
| `YT2POD_MEDIA_CACHE_MAX_BYTES` | `0` | disk 模式下超过此大小按 LRU 淘汰最久未用（0 = 不限制） |
| `YT2POD_STREAM_CHUNK_SIZE` | `4194304` | stream 模式下每次上游 Range 请求的字节数 |

## 工作原理

1. 提供 YouTube 频道 URL 或播放列表 URL（选择音频或视频）
2. `yt-dlp` 提取元数据；最近视频的发布日期/简介来自 YouTube 原生 Atom feed
3. 生成兼容播客的 RSS 2.0 订阅源，包含 `<itunes>` 标签
4. 媒体由代理以支持 HTTP Range 的方式分发，两种模式：
   - `disk`（默认）：首次播放下载到 `data/media/`，后续播放与拖拽即时响应。
   - `stream`：按需从 YouTube 转发，**完全不写磁盘**，适合磁盘极小的情况。
     可用 `YT2POD_MEDIA_CACHE_MAX_BYTES` 限制磁盘缓存上限，或设
     `YT2POD_MEDIA_CACHE_DIR=/dev/shm/yt2pod` 把缓存放到内存。
5. 将 RSS URL 添加到任何播客应用（Apple Podcasts、Overcast 等）

> YouTube 会限制/封锁数据中心或 VPN IP 的下载。若下载出现 HTTP 403，请设置
> `YT2POD_COOKIES_FILE`（已登录的 cookies 文件）和/或
> `YT2POD_YTDLP_PLAYER_CLIENT`。

## RSS 订阅源 URL

注册后，你的播客订阅源 URL 如下：

```
http://localhost:8000/feeds/{feed_id}.xml
```

媒体代理（RSS enclosure 使用；`type` 为 `audio` 或 `video`）：

```
http://localhost:8000/proxy/{video_id}?type=audio
```

## 导出

```bash
uv run --directory . yt2pod export-csv -o feeds.csv
uv run --directory . yt2pod export-opml -o feeds.opml --base-url http://myhost:14732
```

Web UI 提供 `GET /api/export/csv` 和 `GET /api/export/opml`
（后者可加可选参数 `?base_url=` 覆盖订阅源链接）。
当同时存在音频和视频订阅源时，OPML 会分组为 `Audio`/`Video` 文件夹，
并为每个条目附带原始 YouTube 链接（`htmlUrl`）。

## 要求

- Python 3.10+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)（作为依赖安装）