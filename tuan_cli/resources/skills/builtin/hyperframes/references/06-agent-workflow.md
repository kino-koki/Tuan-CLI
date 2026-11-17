# 06 — Agent 工作流优化指南

## 自然语言到视频的分步流程

### Step 1: 意图理解

```
用户: "做一个 30 秒的 AI 产品发布视频，Anthropic 风格"
Agent: 理解 → 提取关键信息:
  - 时长: 30 秒
  - 主题: AI 产品发布
  - 风格: Anthropic (珊瑚色, 奶油底色)
  - 类型: 产品发布视频
```

### Step 2: 分镜规划

```
Agent 输出分镜 JSON → 用户确认
```

```json
{
  "title": "AI 产品发布",
  "duration_sec": 30,
  "design_system": "anthropic",
  "scenes": [
    {"id": "intro", "duration": 5, "title": "品牌开场"},
    {"id": "problem", "duration": 8, "title": "问题陈述"},
    {"id": "solution", "duration": 10, "title": "解决方案"},
    {"id": "cta", "duration": 7, "title": "行动号召"}
  ]
}
```

### Step 3: HTML 合成

```
Agent 写 HTML → 每场景一个 .html 文件
Agent 写时间轴 → composition.json
```

### Step 4: 配音生成

```
Agent 调用 ListenHub → 获取音频 + 时间轴
Agent 注入字幕 → HTML 字幕层
```

### Step 5: Doctor 自检

```
Agent 运行 hyperframes doctor → 检查环境
Agent 修正缺失依赖 → 确保可渲染
```

### Step 6: 渲染输出

```
Agent 运行 hyperframes render → 输出 MP4
Agent 验证输出 → 检查时长/分辨率/音频
```

## Agent 命令清单

| 命令 | 用途 | 输入 | 输出 |
|------|------|------|------|
| `hyperframes plan` | 生成分镜 JSON | 自然语言描述 | composition.json |
| `hyperframes compose` | 生成 HTML 合成 | composition.json | scenes/*.html |
| `hyperframes doctor` | 环境自检 | 无 | 诊断报告 |
| `hyperframes narration` | 生成配音 | composition.json | audio/*.mp3 + timeline.json |
| `hyperframes preview` | 预览单场景 | 场景 ID | preview.gif |
| `hyperframes render` | 渲染最终视频 | composition.json | output.mp4 |
| `hyperframes subtitles` | 导出字幕 | timeline.json | subtitles.srt |

## 自校正循环

```
渲染失败 → Agent 读取错误日志 → 修正 HTML/CSS → 重新渲染
渲染成功但效果不对 → Agent 截图预览 → 对比预期 → 修正动画 → 重新渲染
配音不同步 → Agent 调整时间轴 → 重新渲染
```

## 与 Tuan-Code 联动

HyperFrames 的 HTML 生成遵循 `code-architect` 的工程方法论：

1. **先定义问题**：视频要解决什么沟通问题
2. **简单性优先**：场景数不超过 5 个，动画不超过 3 种
3. **接口稳定**：composition.json 格式固定，版本化
4. **可观测性**：doctor 命令提供完整诊断
5. **测试**：每步输出结构化结果，可自动校验
