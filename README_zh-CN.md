# YouTube2Podcast

将YouTube频道和播放列表转换为播客RSS订阅源。

## 功能特点

- **命令行界面 (CLI)**：直接从命令行生成RSS订阅源文件
- **Web服务**：基于FastAPI的服务器，提供简洁的Web界面来管理订阅源
- **音频代理**：通过服务器流式传输音频（RSS中不包含直接的YouTube链接）
- **定时更新**：在可配置的时间间隔内自动刷新订阅源

## 使用方法

所有命令都在项目根目录使用 `uv run` 执行。

### Web 服务器

```bash
uv run --directory . yt2pod serve
# or with custom host/port
uv run --directory . yt2pod serve --host 0.0.0.0 --port 8000
```

打开 http://localhost:8000 以添加和管理订阅源。

### CLI - 生成 RSS 文件

```bash
uv run --directory . yt2pod generate https://www.youtube.com/@channelname -o feed.xml
uv run --directory . yt2pod generate https://www.youtube.com/playlist?list=PLxxx -o playlist.xml -n 20
```

### CLI - 管理定时订阅源

```bash
uv run --directory . yt2pod add https://www.youtube.com/@channelname
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

## 工作原理

1. 提供 YouTube 频道 URL 或播放列表 URL
2. `yt-dlp` 从 YouTube 提取视频元数据
3. 生成兼容播客的 RSS 2.0 订阅源，包含 `<itunes>` 标签
4. 音频按需通过服务器代理（无需预下载）
5. 将 RSS URL 添加到任何播客应用（Apple Podcasts、Overcast 等）

## RSS 订阅源 URL

注册后，你的播客订阅源 URL 如下：

```
http://localhost:8000/feeds/{feed_id}.xml
```

音频代理（推荐用于播客应用）：

```
http://localhost:8000/proxy/{video_id}
```

## 要求

- Python 3.10+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)（作为依赖安装）