# 10. Vercel — 黑白几何 + 网格渐变

> **类型**：软件 | **领域**：开发者平台 | **设计哲学**：Stark Black-and-Ink Duet

| 规格总览 | 值 |
|---|---|
| 画布色 | 白/近白 |
| 强调色 | `#0072F5` 蓝 |
| 字体策略 | Geist Sans/Mono |
| 记忆点 | 黑白二重奏+网格渐变 |

## 设计规格（定本原文）

**领域标签**：开发者平台 | **设计哲学**：Stark Black-and-Ink Duet

Vercel 的表面是近白画布上的鲜明黑墨二重奏，在英雄区域被一个多色网格渐变（青/蓝/品红/琥珀）打破——这个渐变充当整个装饰系统。页面以压倒性的白色 `#ffffff` 和近黑 `#171717` 文字为主。

**字体**：Geist 字体系列——专为开发者工具界面设计的专有字体，包含 Geist Sans 和 Geist Mono。

**色彩**：Vercel Black `#171717`（主文字）、Vercel Blue `#0072F5`（交互强调、链接、焦点环）。Ship Red `#ff5b4f`、Preview Pink `#de1d8d`、Develop Blue `#0a72ef` 作为产品线标识色。

**网格系统**：网格是 Vercel 新美学的核心部分。

**记忆点**：黑白二重奏 + Geist 字体 + 英雄区域网格渐变 + 网格作为结构骨架。

## CSS Token（可直接复现）

```
/* Vercel — 可复现设计系统 Token */

/* 字体 */
--font-display: 'Geist Sans', 'Geist', sans-serif;
--font-body: 'Geist Sans', 'Geist', sans-serif;
--font-mono: 'Geist Mono', ui-monospace, monospace;

/* 字号 */
--fs-display: clamp(2.5rem, 5vw, 4rem);
--fs-title: clamp(1.25rem, 2vw, 1.5rem);
--fs-body: 0.9375rem;
--fw-regular: 400;
--fw-medium: 500;
--fw-semibold: 600;

/* 色彩 */
--vercel-black: #171717;
--vercel-white: #FAFAFA;
--vercel-blue: #0072F5;
--vercel-dark-blue: #0070F3;
--ship-red: #ff5b4f;
--preview-pink: #de1d8d;
--develop-blue: #0a72ef;
--gray-100: #EBEBEB;
--gray-500: #4D4D4D;

/* 网格渐变（仅英雄区域） */
--gradient-mesh: radial-gradient(ellipse at 20% 50%, #00D4FF, transparent),
                 radial-gradient(ellipse at 60% 30%, #7B61FF, transparent),
                 radial-gradient(ellipse at 80% 70%, #FF6B9D, transparent);

/* 间距 */
--space-xs: 4px;
--space-sm: 8px;
--space-md: 16px;
--space-lg: 32px;
--space-xl: 64px;
--space-2xl: 128px;

/* 圆角 */
--radius-sm: 6px;
--radius-md: 8px;
--radius-lg: 12px;
--radius-full: 9999px;

/* 动效 */
--motion-hover: 150ms ease-out;
--motion-enter: 300ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：黑白二重奏 + Geist 字体 + 英雄区域网格渐变 */
/* 应用方式：页面主体白底黑字，英雄区域叠加网格渐变背景 */
```
