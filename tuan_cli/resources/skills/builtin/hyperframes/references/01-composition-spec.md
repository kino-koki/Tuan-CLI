# 01 — HTML 合成规范与时间轴 API

## 合成文件结构

每个视频由一个 `composition.json` (分镜) 和多个 `.html` 场景文件组成。

```
project/
├── composition.json          # 分镜脚本
├── scenes/
│   ├── scene-1.html          # 开场
│   ├── scene-2.html          # 特性展示
│   └── scene-3.html          # CTA
├── audio/
│   └── narration.mp3         # 配音 (ListenHub 输出)
├── subtitles/
│   └── timeline.json         # 字幕时间轴
└── output/
    └── final.mp4             # 最终渲染
```

## composition.json 规范

```json
{
  "meta": {
    "title": "产品名称发布",
    "author": "Tuan-Chat",
    "created": "2026-01-01T00:00:00Z",
    "version": "1.0"
  },
  "settings": {
    "resolution": "1920x1080",
    "fps": 30,
    "duration": 30,
    "design_system": "anthropic",
    "color_scheme": "dark",
    "language": "zh-CN"
  },
  "scenes": [
    {
      "id": "scene-1",
      "title": "开场",
      "duration": 4.0,
      "start": 0,
      "end": 4,
      "html": "scenes/scene-1.html",
      "narration": {
        "text": "你好，今天介绍一个新产品",
        "voice": "neutral",
        "pitch": 1.0
      },
      "transitions": {
        "out": "fade",
        "duration": 0.5
      }
    }
  ],
  "audio": {
    "narration_file": "audio/narration.mp3",
    "background_music": null,
    "music_volume": 0.3
  },
  "subtitles": {
    "enabled": true,
    "style": "minimal",
    "position": "bottom-center"
  }
}
```

## 时间轴 API

在 HTML 场景文件中，使用 `<script>` 定义时间轴：

```html
<script>
window.HyperFrames = {
  timeline: {
    fps: 30,
    totalDuration: 30,
    scenes: [
      {
        id: "scene-1",
        start: 0,
        end: 4,
        elements: [
          {
            selector: "#title",
            type: "entrance",
            animation: "fade-slide-up",
            delay: 0.3,
            duration: 0.8,
            easing: "cubic-bezier(.34,1.56,.64,1)"
          },
          {
            selector: ".subtitle",
            type: "narration-sync",
            timeline: [
              { start: 0.5, end: 3.0, text: "你好" },
              { start: 3.0, end: 4.0, text: "今天介绍" }
            ]
          }
        ],
        background: {
          type: "gradient",
          colors: ["#141413", "#1a1a1a"],
          direction: "135deg"
        }
      }
    ]
  }
};
</script>
```

## 场景 HTML 模板

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=1920,initial-scale=1">
<style>
  /* 设计系统 Token */
  :root {
    --surface-page: #faf9f5;
    --accent-primary: #d97757;
    --font-display: 'Poppins', 'Arial', sans-serif;
    --font-body: Georgia, serif;
  }
  html, body {
    width: 1920px;
    height: 1080px;
    margin: 0;
    padding: 0;
    overflow: hidden;
    font-family: var(--font-body);
    background: var(--surface-page);
  }
</style>
</head>
<body>
  <div class="scene-container">
    <h1 id="title">标题文字</h1>
    <p class="subtitle" data-narration>旁白字幕</p>
  </div>
  
  <script>
    // 时间轴定义
    window.HyperFrames = {
      timeline: { /* ... */ }
    };
  </script>
</body>
</html>
```
