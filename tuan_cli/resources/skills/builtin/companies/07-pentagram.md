# 7. Pentagram — 纯粹画廊目录

> **类型**：品牌 | **领域**：设计咨询 | **设计哲学**：Work Speaks for Itself

| 规格总览 | 值 |
|---|---|
| 画布色 | 白/近黑 |
| 强调色 | 无（作品即色） |
| 字体策略 | 纯排版 |
| 记忆点 | 零装饰画廊目录 |

## 设计规格（定本原文）

**领域标签**：设计咨询 | **设计哲学**：Work Speaks for Itself

Pentagram 的界面像一本精心策划的画廊目录：纯消色差画布，唯一出现的颜色是作品本身。每个结构决策都是排版性的——没有图标、没有徽章、没有填充按钮、没有装饰性 chrome。网站在白与近黑之间交替，使用大量压缩字体，然后将项目呈现为超大的实色块，在解析成实际作品之前读起来像色卡。

**排版**：导航是一行文字链接。卡片无边框或使用发丝边框。52px 的展示标题和 13px 的说明文字一样从容。

**色彩**：纯消色差——白色 + 近黑色。唯一的颜色来自作品本身。

**记忆点**：零装饰 + 排版即界面 + 作品即色彩。

## CSS Token（可直接复现）

```
/* Pentagram — 可复现设计系统 Token */

/* 字体 */
--font-display: 'Helvetica Neue', 'Aktiv Grotesk', sans-serif;
--font-body: 'Helvetica Neue', 'Aktiv Grotesk', sans-serif;

/* 字号 — 极端对比 */
--fs-display: clamp(2.5rem, 5vw, 3.25rem);
--fs-caption: 0.8125rem;
--fw-regular: 400;

/* 色彩 — 纯消色差 */
--canvas-white: #ffffff;
--canvas-near-black: #111111;
--text-primary: #111111;
--text-secondary: #666666;
--border-hairline: #e0e0e0;

/* 间距 */
--space-xs: 4px;
--space-sm: 8px;
--space-md: 24px;
--space-lg: 48px;
--space-xl: 96px;

/* 圆角 — 零 */
--radius: 0px;

/* 动效 — 最小 */
--motion-hover: 200ms ease-out;

/* 记忆点：零装饰 + 排版即界面 + 纯消色差 */
/* 应用方式：无按钮填充、无图标、无阴影，导航为纯文字链接 */
```
