---
name: tuan-reach
description: >
  多平台联网读取技能——给 Agent 的"上网能力层"。当用户要求「读这个链接」
  「看看这个 GitHub 仓库」「抓一下这个网页」「这个 YouTube/B站视频是什么」
  「读这个 RSS」「联网查一下」时使用。tuan-reach 统一路由 web / github /
  youtube / bilibili / rss 频道, 每频道有序 backend 回退链 (主用失效自动切
  备胎), 附 doctor 全频道健康自检。零强制第三方依赖 (stdlib urllib/xml)。
activation: proactive
priority: 85
provides:
  - internet-reach
  - multi-platform-fetch
  - channel-doctor
triggers:
  - 读链接
  - 打开这个网页
  - 抓取
  - GitHub 仓库
  - YouTube 视频
  - B站视频
  - RSS
  - 订阅源
  - 联网读取
  - reach
  - fetch url
license: MIT
metadata:
  version: "1.0.0"
  changelog: |
    v1.0 定本: Agent-Reach 理念的完全自研实现 (channel→backend 回退 + doctor)。
---

# tuan-reach — 多平台联网读取能力层

> **口号**: 一层路由, 多源可达, 后端回退, 健康可观测。

## 定位

能力层 (capability layer) 而非又一个抓取工具: 统一入口自动路由到平台频道,
每个频道是**有序后端链**——主用失效自动切备胎 (如 YouTube: yt-dlp → oembed)。

## 频道与回退链

| 频道 | 匹配 | 后端链 (有序回退) |
|------|------|-------------------|
| github | github.com 链接 | api (REST 免 key + README) → raw (README 兜底) |
| youtube | youtube / youtu.be | yt-dlp (需安装) → oembed (免 key 元数据) |
| bilibili | bilibili.com/video/BV… | 公开 API (免 key) → 页面 og 标签 |
| rss | .xml / /rss / /feed | 直接拉取解析 (RSS 2.0 + Atom) |
| web | 其余一切 | urllib 直读 (SSRF 防护 + 正文化) |

## 用法

斜杠命令 (TUI / REPL):

```
/reach <URL>        # 自动路由读取
/reach doctor       # 全频道健康自检 (可达性/耗时/失败原因)
/reach channels     # 列出频道与后端链
```

模型工具调用:

```
reach_fetch(target, channel?)   # channel 可强制指定
reach_doctor()
```

## 设计原则 (与上游理念的对应, 实现为全新自研)

- channel → 多 backend 有序回退, 对抗平台接口变动与反爬;
- doctor 自检: 哪个源坏了、坏在哪个后端、怎么修, 一次说清;
- 零配置优先: 全部频道免 API key 可用; 可选依赖 (yt-dlp) 缺失自动降级;
- fail-closed: 失败留痕 (attempts), 绝不静默假成功。
