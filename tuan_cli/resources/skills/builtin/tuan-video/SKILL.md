---
name: tuan-video
description: >
  视频设计技能——桥接 tuan-design 与 hyperframes 的视频制作流水线。当用户要求
  「设计视频」「做品牌视频」「制作宣传视频」「视频设计」「品牌视觉视频」
  「产品发布视频」「营销视频」「动态视觉」时使用。本技能整合 tuan-design 的
  71 家公司设计系统（色彩/字体/间距/动效）与 hyperframes 的 HTML→MP4 渲染
  引擎，确保视频产出与品牌视觉语言完全一致。流程：四问校准 → 选风格起点 →
  套用设计 Token → 分镜规划 → HTML 合成 → 动画编排 → ListenHub 配音 → 渲染。
activation: proactive
priority: 92
suggests:
  - tuan-design
  - hyperframes
requires:
  - design-system
provides:
  - video-design
  - brand-video
  - video-pipeline
triggers:
  - 视频设计
  - 品牌视频
  - 宣传视频
  - 产品视频
  - 营销视频
  - 动态视觉
  - 视频制作
  - 制作视频
  - 做个视频
  - 做一段视频
  - 视频 + 设计
  - 设计视频
  - brand video
  - video design
  - marketing video
  - product video
  - motion graphics
  - animation video
license: MIT
metadata:
  version: "1.0.0"
  changelog: |
    v1.0 定本：桥接 tuan-design + hyperframes 的视频设计流水线。
---

# TUAN Video — 视频设计流水线

> **口号**: 设计决定风格，HTML 决定实现，渲染决定交付。

本技能是 tuan-design 与 hyperframes 的桥接层：当用户要求「设计一个视频」时，
先走 tuan-design 的四问校准与风格选择，再将设计系统 Token 注入 hyperframes
的 HTML 合成，最终渲染为品牌一致的高质量 MP4。

## 适用场景

| 场景 | 说明 | 风格起点 |
|------|------|----------|
| 产品发布视频 | 30-60s 产品功能展示 | Apple / Anthropic / Linear |
| 品牌宣传视频 | 60-120s 品牌故事 | Stripe / Airbnb / Duolingo |
| 数据可视化视频 | 数据故事动画 | Google / IBM Carbon |
| 教程/教学视频 | 步骤演示 | Notion / Atlassian |
| 营销广告视频 | 转化驱动 | Meta / TikTok |

## 五步流水线

### Step 1: 四问校准（来自 tuan-design）

| 问题 | 回答方向 |
|------|----------|
| **这个视频像谁？** | 从 tuan-design 的 71 家公司中选择风格起点 |
| **为谁设计？** | 目标观众（开发者/消费者/企业） |
| **解决什么问题？** | 视频的传播目标（品牌认知/产品转化/知识传递） |
| **如何衡量成功？** | 完播率 / 点击率 / 转化率 |

### Step 2: 设计系统套用（来自 tuan-design）

从 `companies/index.md` 选择风格起点，提取设计 Token：

```css
/* 视频用设计 Token (注入到 HyperFrames HTML 中) */
:root {
  --surface-page: #faf9f5;
  --accent-primary: #d97757;
  --font-display: 'Poppins', 'Arial', sans-serif;
  --font-body: Georgia, 'Times New Roman', serif;
  --motion-ease: cubic-bezier(0.25, 0.1, 0.25, 1);
  --motion-duration: 400ms;
}
```

### Step 3: 分镜规划（来自 hyperframes）

```json
{
  "title": "产品发布视频",
  "duration_sec": 45,
  "resolution": "1920x1080",
  "fps": 30,
  "design_system": "anthropic",
  "scenes": [
    {"id": "intro", "duration": 5, "title": "品牌开场", "animation": "fade-slide-up"},
    {"id": "problem", "duration": 10, "title": "问题陈述", "animation": "stagger-reveal"},
    {"id": "solution", "duration": 15, "title": "解决方案", "animation": "scale-bounce"},
    {"id": "cta", "duration": 10, "title": "行动号召", "animation": "spring-pop"},
    {"id": "outro", "duration": 5, "title": "品牌收尾", "animation": "fade"}
  ],
  "narration": {
    "enabled": true,
    "language": "zh-CN",
    "voice": "neutral",
    "sync_mode": "timeline"
  }
}
```

### Step 4: HTML 合成 + 动画编排（来自 hyperframes）

每个场景生成 HTML，注入设计系统 Token，编排动画时间轴。

### Step 5: 配音 + 渲染（来自 hyperframes）

调用 ListenHub 生成配音，同步字幕时间轴，最终渲染 MP4。

## 设计一致性检查

| 检查项 | 标准 |
|--------|------|
| 色彩一致 | 视频色彩与 tuan-design 选定公司的 CSS Token 一致 |
| 字体一致 | 视频字体与网站字体一致（或有合理的 fallback） |
| 动效一致 | 动画缓动曲线与品牌的交互语言一致 |
| 品牌标志 | 视频片头/片尾包含品牌 Logo |
| 对比度 | 文字对比度 ≥ 4.5:1 |
| 无 emoji | 零 emoji，用 Lucide 图标或文字标签替代 |

## 快速开始

```bash
# 1. 确认依赖技能已加载
hyperframes doctor

# 2. 选择风格起点 (来自 tuan-design)
# 读取 companies/index.md，选择最匹配的公司

# 3. 提取设计 Token
# 从选中的公司 md 文件中复制 CSS Token

# 4. 生成分镜 (参考上方分镜 JSON 模板)
hyperframes plan --title "产品发布" --duration 45 --design anthropic

# 5. 合成 HTML + 动画
hyperframes compose --input composition.json

# 6. 生成配音
hyperframes narration --input composition.json

# 7. 渲染输出
hyperframes render --output release.mp4
```

## 参考文件

- `tuan-design/companies/index.md` — 71 家公司设计系统检索表
- `tuan-design/companies/NN-公司.md` — 各公司完整设计规格
- `hyperframes/references/01-composition-spec.md` — HTML 合成规范
- `hyperframes/references/02-animation-patterns.md` — 动画模式库
- `hyperframes/references/03-listenhub-integration.md` — 配音集成协议
- `hyperframes/references/04-design-system-integration.md` — 设计系统套用规范
