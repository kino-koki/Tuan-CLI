# 13. Spotify — 沉浸式暗色音乐宇宙

> **类型**：软件 | **领域**：音乐流媒体 | **设计哲学**：Content-First Dark Immersion

| 规格总览 | 值 |
|---|---|
| 画布色 | `#121212` 近黑 |
| 强调色 | `#1ED760` Spotify绿 |
| 字体策略 | SpotifyMixUI/Circular |
| 记忆点 | 内容即色彩 |

## 设计规格（定本原文）

**领域标签**：音乐流媒体 | **设计哲学**：Content-First Dark Immersion

Spotify 的 Web 界面是一个暗色沉浸式音乐播放器，将听众包裹在近黑茧房（`#121212`、`#181818`、`#1f1f1f`）中，专辑封面和内容成为唯一色彩来源。设计哲学是“content-first”——让音乐、播客和播放列表发光。排版围绕“有冲击力的标题”和“紧凑的可扫描性”构建。

**色彩**：暗色层级从 `#121212` 到 `#1f1f1f`，内容（专辑封面）提供全部色彩。品牌绿 `#1ed760` 仅用于播放控件和品牌标记，绝不用于装饰。暗色品牌色 `#191414` 用于深色背景。

**字体**：SpotifyMixUI / Spotify Circular——专有字体，标题粗重有力，正文紧凑清晰。标题与正文的字重差拉大（700 vs 400），在暗色背景上保持可读性。

**间距**：暗色界面中 spacing 需要更慷慨以创造呼吸感。区块间距大（48–64px），卡片间距中等（16–24px），因为暗色吸光，元素容易“沉没”。

**记忆点**：近黑茧房 + 内容即色彩 + Spotify 绿仅用于播放 + 粗重标题的暗色冲击力。

## CSS Token（可直接复现）

```
/* Spotify — 可复现设计系统 Token */

/* 字体 */
--font-display: 'SpotifyMixUI', 'Spotify Circular', 'Circular', sans-serif;
--font-body: 'SpotifyMixUI', 'Spotify Circular', 'Circular', sans-serif;

/* 字号 */
--fs-display: clamp(2rem, 4.5vw, 3.5rem);
--fs-title: clamp(1.125rem, 2vw, 1.5rem);
--fs-body: 0.875rem;
--fs-note: 0.75rem;
--fw-regular: 400;
--fw-bold: 700;

/* 色彩 — 暗色层级 */
--sp-bg-base: #121212;
--sp-bg-elevated-1: #181818;
--sp-bg-elevated-2: #1f1f1f;
--sp-bg-highlight: #2a2a2a;
--sp-text-primary: #FFFFFF;
--sp-text-secondary: #B3B3B3;
--sp-text-subdued: #6A6A6A;
--sp-brand-green: #1ED760;
--sp-brand-dark: #191414;

/* 间距 */
--space-xs: 4px;
--space-sm: 8px;
--space-md: 16px;
--space-lg: 24px;
--space-xl: 48px;
--space-2xl: 64px;

/* 圆角 */
--radius-sm: 4px;
--radius-md: 8px;
--radius-full: 9999px;

/* 动效 */
--motion-hover: 150ms ease-out;
--motion-enter: 300ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：近黑茧房 #121212 + 内容即色彩 + 绿 #1ED760 仅播放 */
/* 应用方式：body 背景 #121212，卡片 #181818，播放按钮 #1ED760 */
```
