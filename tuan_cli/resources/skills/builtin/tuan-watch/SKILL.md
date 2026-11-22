---
name: tuan-watch
description: >
  视频观看技能——给 Agent 一双"看视频的眼睛"。当用户要求「看视频」「看这个视频」
  「视频讲了什么」「总结视频」「看片段」「视频里他说了什么」「抽帧」「看 vlog」
  「分析视频内容」时使用。tuan-watch 能力链: 本地/URL → ffprobe 元数据 →
  字幕优先转写 (sidecar → 内嵌轨 → Whisper) → 档位抽帧 (16x16 灰度去重) →
  观看包落盘。零强制依赖: ffmpeg/yt-dlp/whisper 均可选, 缺失如实上报。
activation: proactive
priority: 85
provides:
  - video-watching
  - video-transcript
  - frame-sampling
triggers:
  - 看视频
  - 视频内容
  - 总结视频
  - 视频讲了什么
  - 看片段
  - 字幕
  - 抽帧
  - 关键帧
  - watch video
  - video summary
  - 转写
  - whisper
license: MIT
metadata:
  version: "1.0.0"
  changelog: |
    v1.0 定本: claude-video 理念的完全自研实现 (字幕优先/帧预算/帧去重)。
---

# tuan-watch — 视频观看能力

> **口号**: 字幕优先, 预算抽帧, 去重省 token, 缺依赖必如实上报。

## 何时用

| 场景 | 建议档位 |
|------|----------|
| 只想知道视频说了什么 | `transcript` (只看字幕, 不抽帧不下载) |
| 快速浏览内容 | `swift` (约 24 帧封顶) |
| 常规观看 | `balanced` (约 48 帧, 默认) |
| 逐镜分析 | `deep` (约 96 帧封顶) |

## 用法

斜杠命令 (TUI / REPL):

```
/watch <视频路径或URL> [问题] [--detail transcript|swift|balanced|deep] [--start 秒] [--end 秒] [--no-dedup]
```

模型工具调用:

```
video_watch(source, question?, detail?, start?, end?, no_dedup?)
```

## 能力链 (自动执行)

1. **源解析**: 本地文件直接用; URL 优先 yt-dlp (数百站点), 未安装则尝试直链下载 (300MB 上限)。
2. **元数据**: ffprobe 读取时长/分辨率/帧率/音轨/字幕轨。
3. **字幕优先转写** (省时省钱的核心):
   - 同目录同名 `.srt` / `.vtt` 旁挂字幕 → 直接解析, 不碰视频;
   - 内嵌字幕轨 → `ffmpeg -map 0:s:0` 抽取;
   - 都没有 → 本地 Whisper (faster-whisper 优先) 转写 16kHz 单声道音轨;
   - 全无 → 如实报告, 绝不编造。
4. **帧预算抽帧**: 视频越长单位时间帧数越少, 且每档有硬上限;
   每帧缩成 16x16 灰度图与**上一张被保留帧**比平均亮度差, 低于阈值判为
   近重复丢弃 (静态画面不重复烧 token)。
5. **观看包**: 帧图 + `pack.json` 清单落盘到 `<workspace>/.tuan/watch/<digest>/`, 可复看可二次提问。

## 依赖 (全部可选)

| 依赖 | 缺失时行为 |
|------|-----------|
| ffmpeg / ffprobe | 抽帧/元数据不可用; 字幕旁挂仍可用 |
| yt-dlp | URL 只支持直链媒体 |
| faster-whisper / openai-whisper | 无字幕视频无法转写 (明确提示) |

## 设计原则 (与上游理念的对应, 实现为全新自研)

- transcript-first: 能不下载就不下载;
- 帧预算: token 成本闸门, 长视频自动降密度;
- 帧去重: 捕捉缓慢渐变, 静态帧不重复;
- fail-closed: 依赖缺失/源不可用 → 明确错误, 不假成功。
