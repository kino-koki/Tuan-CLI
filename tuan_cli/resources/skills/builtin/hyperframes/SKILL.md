---
name: hyperframes
description: >
  HyperFrames 技能——「写 HTML，渲成视频，为 agent 而造」。把 HTML/CSS/JS 合成
  渲染为高质量 MP4 视频。当用户要求制作视频、动态 HTML、动画演示、信息图视频、
  数据可视化视频、营销视频、产品发布视频、教程视频时使用。核心能力: HTML→MP4
  渲染引擎、动画时间轴编排、配音同步 (ListenHub 音频+字幕时间轴)、设计系统套用、
  doctor 自检渲染环境。本技能是 skill 包形式，可被 Claude Code 等编程 agent 直接
  加载，用自然语言描述视频意图即可触发规划→HTML 合成→渲染全流程。
  口号: "写 HTML，渲成视频，为 agent 而造"。
  触发词: 视频、video、animation、渲染、render、HTML视频、动效视频、动画演示、
  营销视频、发布视频、教程视频、数据可视化视频、信息图视频、ListenHub、配音、
  字幕、时间轴、timeline、MP4、渲染视频、视频渲染、视频制作、制作视频、做个视频、
  做一段视频、hyperframes、hyper-frames。
activation: proactive
priority: 90
suggests:
  - tuan-design
  - tuan-video
provides:
  - video-render
  - html-to-video
  - animation-timeline
triggers:
  - 视频
  - video
  - animation
  - 渲染
  - render
  - HTML视频
  - 动效视频
  - 动画演示
  - 营销视频
  - 发布视频
  - 教程视频
  - 数据可视化视频
  - 信息图视频
  - ListenHub
  - 配音
  - 字幕
  - 时间轴
  - timeline
  - MP4
  - 渲染视频
  - 视频渲染
  - 视频制作
  - 制作视频
  - 做个视频
  - 做一段视频
  - hyperframes
  - hyper-frames
license: MIT
metadata:
  version: "1.0.0"
  slogan: "写 HTML，渲成视频，为 agent 而造"
  changelog: |
    v1.0 定本：完整技能包，含渲染引擎协议、动画时间轴规范、设计系统集成、
    配音闭环 (ListenHub)、doctor 自检、Tuan 系列专属优化。
---

# HyperFrames — 写 HTML，渲成视频，为 agent 而造

## 核心定位

HyperFrames 不是一个视频编辑工具——它是一个**为编程 agent 设计的 HTML→视频渲染引擎**。
它的哲学是：**你不需要学视频软件，你只需要会写 HTML**。

传统视频制作需要 After Effects / Premiere / CapCut——HyperFrames 把视频制作变成
"写 HTML + 写 CSS 动画 + 调用渲染命令"，让任何编程 agent (Claude Code、Codex、
DeepSeek Harness、Hermes、Kimi Code) 都能用自然语言理解视频意图，规划分镜，
写 HTML 合成，渲染出 MP4。

## 为什么底层选 HTML

1. **agent 最熟悉的语言**：编程 agent 天然理解 HTML/CSS/JS，不需要学习新的 DSL
2. **Web 生态复用**：动画库 (GSAP、Anime.js)、图表库 (D3、ECharts)、3D (Three.js)
   直接可用
3. **设计系统天然兼容**：Tuan-Design 的 71 家公司 CSS Token 可以直接用在视频里
4. **跨平台渲染**：基于 Puppeteer/Playwright 无头浏览器，macOS/Linux/Windows 全支持
5. **增量调试**：HTML 可以逐帧截图预览，agent 可以 self-correct

## 工作流程 (Agent 视角)

```
自然语言意图 → 规划分镜 → 写 HTML 合成 → 接动画 → doctor 自检 → render 出 MP4
     ↑                                                                                      ↓
     └──────────── ListenHub 配音 + 字幕时间轴 ←────────────────────────────────────────────┘
```

### 步骤 1: 规划分镜 (Script Planning)

agent 收到视频意图后，先输出分镜脚本：

```json
{
  "title": "视频标题",
  "duration_sec": 30,
  "resolution": "1920x1080",
  "fps": 30,
  "design_system": "anthropic",
  "scenes": [
    {
      "id": "scene-1",
      "duration": 4,
      "title": "开场",
      "layout": "centered",
      "content": {"headline": "产品名", "subhead": "一句话描述"},
      "animation": "fade-in + slide-up"
    },
    {
      "id": "scene-2",
      "duration": 8,
      "title": "特性展示",
      "layout": "grid-3",
      "content": {"items": [{"icon": "⚡", "text": "特性1"}, ...]},
      "animation": "stagger-fade-in"
    }
  ],
  "narration": {
    "enabled": true,
    "language": "zh-CN",
    "voice": "neutral",
    "sync_mode": "timeline"
  }
}
```

### 步骤 2: HTML 合成 (Composition)

每个场景生成一个 HTML 文件，包含：
- **结构层**：语义化 HTML 标签
- **样式层**：设计系统 CSS Token + 场景特定样式
- **动画层**：CSS `@keyframes` 或 GSAP 时间轴
- **字幕层**：`<div class="subtitle">` 带 `data-start` / `data-end` 时间戳

### 步骤 3: 动画时间轴 (Timeline)

```javascript
// HyperFrames 时间轴 API (嵌入在 HTML 中)
const timeline = {
  fps: 30,
  duration: 30, // 总时长 (秒)
  scenes: [
    {
      id: "scene-1",
      start: 0,
      end: 4,
      elements: [
        {
          target: "#headline",
          animation: "fade-in-up",
          delay: 0.5,
          duration: 0.8,
          easing: "cubic-bezier(.34,1.56,.64,1)"
        }
      ],
      narration: {
        text: "欢迎来到我们的新产品",
        start: 0.5,
        end: 3.5
      }
    }
  ]
};
```

### 步骤 4: Doctor 自检 (Environment Check)

```bash
# 检查渲染环境依赖
hyperframes doctor

# 输出示例:
# ✓ Node.js >= 18.0 (detected: v20.11.0)
# ✓ Chromium/Puppeteer (detected: headless chrome 120)
# ✓ FFmpeg (detected: 6.1)
# ✓ Fonts (detected: 42 system fonts)
# ✓ Canvas rendering (WebGL: enabled)
# ✓ Audio output (ListenHub: available)
# ⚠ Slow disk write speed (120 MB/s, recommended: 300+ MB/s)
```

### 步骤 5: 渲染输出 (Render)

```bash
# 渲染 HTML → MP4
hyperframes render \
  --input composition.html \
  --output output.mp4 \
  --resolution 1920x1080 \
  --fps 30 \
  --crf 18 \
  --audio narration.mp3

# 或渲染单场景为预览
hyperframes preview \
  --input composition.html \
  --scene scene-2 \
  --output preview.gif
```

## 配音闭环 (ListenHub 集成)

```
1. 从分镜脚本提取旁白文本
2. 调用 ListenHub API 生成音频 (支持 zh-CN/en-US/ja-JP)
3. 获取音频时间轴 (每句话的 start/end 时间戳)
4. 将时间轴注入 HTML 字幕层
5. 渲染时画面跟声音走 (字幕同步出现/消失)
```

```javascript
// 字幕时间轴示例 (ListenHub 输出)
const narrationTimeline = [
  { start: 0.5, end: 2.8, text: "欢迎来到我们的新产品" },
  { start: 3.2, end: 5.5, text: "它解决了三大痛点" },
  { start: 6.0, end: 9.2, text: "第一，效率提升三倍" },
];
```

## 设计系统套用

HyperFrames 天然兼容 Tuan-Design 的 71 家公司设计系统。渲染时自动应用：

```css
/* 在 HTML 中引用设计系统 */
<link rel="stylesheet" href="https://tuan.design/systems/anthropic.css">
/* 或内联 CSS Token */
:root {
  --surface-page: #faf9f5;
  --accent-primary: #d97757;
  --font-display: 'Poppins', 'Arial', sans-serif;
  --font-body: Georgia, 'Times New Roman', serif;
}
```

## Tuan 系列专属优化

### 1. 与 Tuan-Design 联动
- 自动检测当前项目的设计系统配置
- 如果存在 `tuan-design` 技能，自动套用对应公司的色彩/字体/间距
- 视频中的设计语言与网页保持一致

### 2. 与 Tuan-Code 联动
- HTML 合成复用 `code-architect` 的工程方法论
- 动画性能遵循性能可预测性原则
- 渲染流程遵循测试+可观测性设计

### 3. 渲染优化
- **分块渲染**：长视频按场景分块渲染再拼接，避免内存峰值
- **帧缓存**：相同元素的重复帧缓存复用，渲染速度提升 40%
- **并行场景**：独立场景可并行渲染，缩短总耗时

### 4. Agent 工作流优化
- `hyperframes plan`：输出分镜 JSON 供 agent 审阅
- `hyperframes compose`：生成 HTML 合成文件
- `hyperframes doctor`：环境自检
- `hyperframes render`：最终渲染
- 每步输出结构化结果，agent 可自动校验并修正

## 输出规格

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 分辨率 | 1920×1080 | 支持 720p / 1080p / 4K |
| 帧率 | 30 fps | 支持 24/25/30/60 fps |
| 编码 | H.264 | 兼容所有平台 |
| 音频 | AAC 128kbps | 支持 MP3/WAV 输入 |
| 字幕 | 内嵌 | 支持软字幕 (mov_text) |
| 文件 | MP4 | 兼容 YouTube/B 站/微信 |

## 快速开始 (Agent 命令)

```bash
# 1. 安装依赖
pip install hyperframes[all]

# 2. 环境自检
hyperframes doctor

# 3. 用自然语言创建视频
hyperframes create "做一个 30 秒的产品发布视频，Anthropic 风格，珊瑚色调"

# 4. 编辑分镜 (可选)
hyperframes edit composition.json

# 5. 渲染
hyperframes render --output release.mp4

# 6. 导出字幕
hyperframes subtitles --output subtitles.srt
```

## 参考文件

- `references/01-composition-spec.md` — HTML 合成规范与时间轴 API
- `references/02-animation-patterns.md` — 常用动画模式库 (20+ 种)
- `references/03-listenhub-integration.md` — 配音闭环详细协议
- `references/04-design-system-integration.md` — 设计系统套用规范
- `references/05-rendering-optimization.md` — 渲染性能优化策略
- `references/06-agent-workflow.md` — Agent 工作流优化指南
