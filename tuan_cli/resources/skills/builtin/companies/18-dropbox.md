# 18. Dropbox — 编辑自信的云协作

> **类型**：软件 | **领域**：云存储/协作 | **设计哲学**：Editorial Confidence, Functional Delight

| 规格总览 | 值 |
|---|---|
| 画布色 | `#F7F5F2` 暖白 |
| 强调色 | `#0061FF` Dropbox蓝 |
| 字体策略 | Sharp/Atlas Grotesk |
| 记忆点 | 编辑自信 |

## 设计规格（定本原文）

**领域标签**：云存储/协作 | **设计哲学**：Editorial Confidence, Functional Delight

Dropbox 2025 年重新设计了品牌指南微站，将其从“过时的参考文档”转变为“互动视觉游乐场”。设计策略围绕四个关键词：humanity、clarity、action、delight——温暖、有灵魂、可亲近。品牌指南的核心理念从“设计天花板”变为“设计地板”，任何人都可以在此基础上构建。

**色彩**：Dropbox Blue `#0061FF` 是核心，搭配 Coconut（暖白）、Graphite（石墨灰）。强调色从品牌色中派生，用于图表、插图和数据可视化。色彩使用有意图——创建和谐与焦点，引导用户并强化品牌。

**字体**：Sharp Grotesk 风格的展示字体 + Atlas Grotesk 风格的正文。展示字体有编辑自信，正文字体清晰可读。

**间距**：编辑排版节奏——区块间距大（64–96px），条目间距中等（24–32px），形成阅读节奏。

**记忆点**：Dropbox Blue #0061FF + 编辑自信的字体对 + 品牌指南即互动游乐场。

## CSS Token（可直接复现）

```
/* Dropbox — 可复现设计系统 Token */

/* 字体 */
--font-display: 'Sharp Grotesk', 'Inter', sans-serif;
--font-body: 'Atlas Grotesk', 'Inter', sans-serif;

/* 字号 */
--fs-display: clamp(2.25rem, 4.5vw, 3.5rem);
--fs-title: clamp(1.375rem, 2.5vw, 1.75rem);
--fs-body: 1rem;
--fs-note: 0.875rem;
--fw-regular: 400;
--fw-medium: 500;
--fw-semibold: 600;

/* 色彩 */
--dropbox-blue: #0061FF;
--dropbox-coconut: #F7F5F2;
--dropbox-graphite: #1E1919;
--dropbox-text-primary: #1E1919;
--dropbox-text-secondary: #736C64;
--dropbox-border: #E0DCD7;

/* 间距 */
--space-xs: 4px;
--space-sm: 8px;
--space-md: 24px;
--space-lg: 48px;
--space-xl: 64px;
--space-2xl: 96px;

/* 圆角 */
--radius-sm: 4px;
--radius-md: 8px;
--radius-lg: 12px;

/* 动效 */
--motion-hover: 150ms ease-out;
--motion-enter: 300ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：#0061FF + 编辑自信字体对 + 温暖功能主义 */
/* 应用方式：主色 #0061FF，背景 #F7F5F2，标题 Sharp Grotesk，正文 Atlas Grotesk */
```
