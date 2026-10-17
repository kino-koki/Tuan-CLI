# 19. BMW — 减法美学与 Neue Klasse

> **类型**：品牌 | **领域**：汽车/豪华 | **设计哲学**：Clear, Reduced, Characterful

| 规格总览 | 值 |
|---|---|
| 画布色 | `#000000`/`#FFFFFF` |
| 强调色 | `#0066B1` BMW蓝 |
| 字体策略 | BMW Type Next |
| 记忆点 | 减法美学 |

## 设计规格（定本原文）

**领域标签**：汽车/豪华 | **设计哲学**：Clear, Reduced, Characterful

BMW 2025 年推出的 Neue Klasse 设计语言标志着品牌设计的世代级转变。核心理念是“清晰、减法、有个性”——清晰线条、无镀铬、减少装饰元素、格栅缩小。BMW 设计总监强调未来车型将避免“俄罗斯套娃”式设计，每款车都将有独特设计，而非简单缩放。

**色彩**：黑白为主基调。Neue Klasse 的内饰设计强调“现代体验”——数字仪表盘取代传统仪表，但保留驾驶聚焦。品牌色为 BMW 蓝 `#0066B1`，但在产品设计中克制使用。

**字体**：BMW Type Next 是品牌字体，几何无衬线，干净锐利。数字仪表使用定制字体，等宽数字。

**间距**：汽车设计语境下的“间距”是物理空间——车内空间、仪表盘布局、按钮间距。数字界面遵循清晰网格，操作按钮有明确的触控目标。

**记忆点**：减法美学 + 无镀铬 + 缩小格栅 + 每款车独特设计。

## CSS Token（可直接复现）

```
/* BMW Neue Klasse — 可复现设计系统 Token（数字界面参考） */

/* 字体 */
--font-display: 'BMW Type Next', 'Inter', sans-serif;
--font-body: 'BMW Type Next', 'Inter', sans-serif;
--font-mono: 'BMW Type Next Mono', ui-monospace, monospace;

/* 字号 */
--fs-display: clamp(2rem, 4vw, 3rem);
--fs-title: clamp(1.25rem, 2vw, 1.5rem);
--fs-body: 0.875rem;
--fw-regular: 400;
--fw-medium: 500;
--fw-bold: 700;

/* 色彩 */
--bmw-black: #000000;
--bmw-white: #FFFFFF;
--bmw-blue: #0066B1;
--bmw-gray-100: #F5F5F5;
--bmw-gray-500: #7A7A7A;
--bmw-gray-900: #1A1A1A;

/* 间距 */
--space-xs: 4px;
--space-sm: 8px;
--space-md: 16px;
--space-lg: 32px;
--space-xl: 48px;

/* 圆角 */
--radius-sm: 2px;
--radius-md: 4px;

/* 动效 */
--motion-hover: 150ms ease-out;
--motion-enter: 300ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：减法美学 + 无镀铬 + 缩小格栅 */
/* 应用方式：黑白为主，#0066B1 克制使用，零镀铬质感 */
```
