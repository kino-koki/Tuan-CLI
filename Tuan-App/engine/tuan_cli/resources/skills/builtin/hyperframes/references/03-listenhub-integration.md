# 03 — ListenHub 配音集成协议

## 配音闭环流程

```
分镜脚本 → 提取旁白文本 → ListenHub API 生成音频 → 获取时间轴 → 注入 HTML → 渲染同步
```

## 1. 提取旁白文本

从 `composition.json` 的每个场景的 `narration.text` 字段提取。

## 2. ListenHub API 调用

```python
import requests

# 生成配音
response = requests.post(
    "https://listenhub.ai/api/v1/tts",
    json={
        "text": "你好，今天介绍一个新产品",
        "voice": "neutral",
        "language": "zh-CN",
        "speed": 1.0,
        "pitch": 1.0,
        "format": "mp3"
    },
    headers={"Authorization": f"Bearer {API_KEY}"}
)

# 返回
# {
#   "audio_url": "https://...",
#   "duration_sec": 3.5,
#   "timeline": [
#     {"start": 0.0, "end": 1.8, "text": "你好"},
#     {"start": 1.9, "end": 3.5, "text": "今天介绍一个新产品"}
#   ]
# }
```

## 3. 时间轴注入

将 ListenHub 返回的时间轴注入 HTML 字幕层：

```javascript
// HTML 中的字幕时间轴
const narrationTimeline = [
  { start: 0.0, end: 1.8, text: "你好" },
  { start: 1.9, end: 3.5, text: "今天介绍一个新产品" }
];
```

## 4. 渲染同步

渲染时，Puppeteer 根据当前帧时间查找对应字幕文本：

```javascript
function getCurrentSubtitle(currentTime, timeline) {
  return timeline.find(s => currentTime >= s.start && currentTime < s.end);
}
```

## 5. 多语言支持

| 语言 | 代码 | 默认声音 | 速度调整 |
|------|------|----------|----------|
| 中文 | zh-CN | neutral | 1.0x |
| 英文 | en-US | professional | 0.95x |
| 日文 | ja-JP | warm | 0.9x |
| 韩文 | ko-KR | clear | 0.95x |

## 6. 字幕样式

```css
/* 字幕容器 */
.subtitle-container {
  position: absolute;
  bottom: 80px;
  left: 50%;
  transform: translateX(-50%);
  padding: 12px 24px;
  background: rgba(0, 0, 0, 0.7);
  border-radius: 8px;
  color: #fff;
  font-size: 28px;
  font-family: var(--font-body);
  max-width: 80%;
  text-align: center;
  line-height: 1.4;
}

/* 字幕动画 */
.subtitle-enter {
  animation: subtitle-fade-in 0.3s ease-out;
}

@keyframes subtitle-fade-in {
  from { opacity: 0; transform: translateX(-50%) translateY(10px); }
  to { opacity: 1; transform: translateX(-50%) translateY(0); }
}
```

## 7. SRT 导出

```srt
1
00:00:00,000 --> 00:00:01,800
你好

2
00:00:01,900 --> 00:00:03,500
今天介绍一个新产品
```
