# 17. Netflix — 极致克制的红色张力

> **类型**：软件 | **领域**：流媒体娱乐 | **设计哲学**：Cinematic Contrast, Red Restraint

| 规格总览 | 值 |
|---|---|
| 画布色 | `#141414` |
| 强调色 | `#E50914` 红（极克制） |
| 字体策略 | Netflix Sans |
| 记忆点 | 红色极致克制 |

## 设计规格（定本原文）

**领域标签**：流媒体娱乐 | **设计哲学**：Cinematic Contrast, Red Restraint

Netflix 的品牌系统建立在两个常量上：Netflix Red 在黑色上，以及 Netflix Sans 的粗犷声音。红色被使用得极度克制——仅保留给品牌标记和主要 CTA，作为唯一的视觉紧迫点。自定义字体 Netflix Sans 由 Dalton Maag 铸造，取代了此前的 Gotham，据报道每年节省数百万授权费。

**色彩**：Netflix Red `#E50914` 是唯一强调色，仅用于品牌 logo 和主 CTA。黑色 `#000000` 或近黑是画布，白色文字。界面中的内容（海报、剧照）提供色彩。绝不给每个标签上色。

**字体**：Netflix Sans（Dalton Maag 铸造），粗犷 grotesque 风格。标题用 Bold，正文用 Regular。字距紧凑，大标题有轻微负字距。

**间距**：暗色沉浸界面，内容排布密集（多行卡片），但区块间距保持清晰。卡片间距 12–16px，行间距 8–12px。

**记忆点**：Netflix Red #E50914 的极度克制 + 黑色画布 + Netflix Sans 粗犷声音。

## CSS Token（可直接复现）

```
/* Netflix — 可复现设计系统 Token */

/* 字体 */
--font-display: 'Netflix Sans', 'Helvetica Neue', sans-serif;
--font-body: 'Netflix Sans', 'Helvetica Neue', sans-serif;

/* 字号 */
--fs-display: clamp(2rem, 4vw, 3.5rem);
--fs-title: clamp(1.125rem, 2vw, 1.5rem);
--fs-body: 0.875rem;
--fs-note: 0.75rem;
--fw-regular: 400;
--fw-bold: 700;

/* 色彩 */
--netflix-red: #E50914;
--netflix-black: #000000;
--netflix-dark: #141414;
--netflix-white: #FFFFFF;
--netflix-gray-500: #808080;
--netflix-gray-700: #B3B3B3;

/* 间距 */
--space-xs: 4px;
--space-sm: 8px;
--space-md: 16px;
--space-lg: 24px;
--space-xl: 48px;

/* 圆角 */
--radius-sm: 4px;
--radius-md: 8px;

/* 动效 */
--motion-hover: 200ms ease-out;
--motion-enter: 300ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：#E50914 极度克制 + 黑画布 + Netflix Sans */
/* 应用方式：红色仅 logo 和主 CTA，背景 #141414，内容提供色彩 */
```
