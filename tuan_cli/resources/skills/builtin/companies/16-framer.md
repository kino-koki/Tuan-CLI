# 16. Framer — 设计原生建站平台

> **类型**：软件 | **领域**：建站工具 | **设计哲学**：Design-Native Sharpness

| 规格总览 | 值 |
|---|---|
| 画布色 | `#000000`/`#FFFFFF` |
| 强调色 | `#0055FF` 信号蓝 |
| 字体策略 | GT Walsheim / Inter |
| 记忆点 | 设计即品牌 |

## 设计规格（定本原文）

**领域标签**：建站工具 | **设计哲学**：Design-Native Sharpness

Framer 的公开站点使用干净锐利的无衬线系统，以黑白为基底，鲜明蓝色 `#0055FF` 作为强调，产品框架感“快速、高级、面向创作者”。Framer 的设计语言核心是“设计原生的锋利感”——它不掩饰自己是设计工具，而是用设计品质本身证明价值。

**色彩**：纯黑 `#000000` 作为主色，白色画布，鲜明蓝 `#0055FF` 作为唯一信号色。品牌渐变为蓝紫到品红的微妙过渡，仅用于产品展示和装饰区域。

**字体**：GT Walsheim 用于标题（几何无衬线，圆润但有锐利边缘），Inter 或系统字体用于正文。标题字重 700，干净利落。

**间距**：4px 网格。营销页面慷慨留白（区块间距 96–128px），产品展示区域紧凑。

**记忆点**：黑白基底 + 信号蓝 #0055FF + GT Walsheim 标题 + 设计品质即品牌。

## CSS Token（可直接复现）

```
/* Framer — 可复现设计系统 Token */

/* 字体 */
--font-display: 'GT Walsheim', 'Inter', sans-serif;
--font-body: 'Inter', system-ui, sans-serif;

/* 字号 */
--fs-display: clamp(2.5rem, 5vw, 4rem);
--fs-title: clamp(1.5rem, 2.5vw, 2rem);
--fs-body: 1rem;
--fw-regular: 400;
--fw-medium: 500;
--fw-bold: 700;

/* 色彩 */
--framer-black: #000000;
--framer-white: #FFFFFF;
--framer-blue: #0055FF;
--framer-gray-100: #F3F3F3;
--framer-gray-500: #999999;
--framer-gray-900: #1A1A1A;

/* 渐变（产品展示区域） */
--gradient-framer: linear-gradient(135deg, #0055FF, #8B5CF6, #EC4899);

/* 间距 */
--space-xs: 4px;
--space-sm: 8px;
--space-md: 16px;
--space-lg: 32px;
--space-xl: 64px;
--space-2xl: 128px;

/* 圆角 */
--radius-sm: 6px;
--radius-md: 10px;
--radius-lg: 16px;

/* 动效 */
--motion-hover: 150ms ease-out;
--motion-enter: 350ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：黑白 + 信号蓝 #0055FF + GT Walsheim + 设计即品牌 */
/* 应用方式：页面黑白为主，#0055FF 仅用于 CTA 和链接 */
```
