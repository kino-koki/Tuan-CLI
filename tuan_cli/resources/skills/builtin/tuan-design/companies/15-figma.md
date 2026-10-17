# 15. Figma — 多品牌设计系统的元工具

> **类型**：软件 | **领域**：设计工具 | **设计哲学**：Multi-Brand by Design, White-Label Core

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` / `#1E1E1E` |
| 强调色 | `#1ABCFE` |
| 字体策略 | Whyte / Whyte Inktrap |
| 记忆点 | 白牌多品牌核心 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## 设计规格（定本原文）

**领域标签**：设计工具 | **设计哲学**：Multi-Brand by Design, White-Label Core

Figma 本身是一个设计工具，其设计系统面临的挑战是“元级”的：如何在不倾向任何单一品牌的前提下，展示品牌的多样性？2025 年 Schema 大会发布的 Extended Collections 解决了多品牌设计系统的管理问题——设计团队先创建一个不带品牌色彩的“白牌”核心系统，变量只定义功能不定义颜色，子品牌通过主题切换适配。Figma Buzz 则提供模板级品牌管控。

**色彩**：Figma 界面以深色为默认（`#1E1E1E`），画布白色，UI 元素用中性灰。品牌色在界面中几乎不出现——Figma 的“品牌”是工具本身，色彩是用户的。Figma 官网使用白底黑字 + 鲜明蓝 `#1ABCFE` 作为品牌蓝。

**字体**：Figma 官网使用 `Whyte`（标题）和 `Whyte Inktrap`（代码/等宽场景），产品界面使用系统字体栈。

**间距**：产品界面极度紧凑（工具栏、面板），但官网营销页面慷慨留白。两个语境两套间距节奏。

**记忆点**：白牌核心 + 多品牌扩展集合 + 工具界面的中性化设计。

## CSS Token（可直接复现）

```
/* Figma — 可复现设计系统 Token（官网营销页面） */

/* 字体 */
--font-display: 'Whyte', 'Inter', sans-serif;
--font-body: 'Whyte', 'Inter', sans-serif;
--font-mono: 'Whyte Inktrap', ui-monospace, monospace;

/* 字号 */
--fs-display: clamp(2.5rem, 5vw, 4rem);
--fs-title: clamp(1.5rem, 2.5vw, 2rem);
--fs-body: 1rem;
--fw-regular: 400;
--fw-medium: 500;
--fw-semibold: 600;
--fw-bold: 700;

/* 色彩 */
--figma-blue: #1ABCFE;
--figma-black: #1E1E1E;
--figma-white: #FFFFFF;
--figma-gray-100: #F5F5F5;
--figma-gray-500: #888888;
--figma-purple: #A259FF;
--figma-green: #0ACF83;
--figma-orange: #FF7262;

/* 间距 */
--space-xs: 4px;
--space-sm: 8px;
--space-md: 16px;
--space-lg: 32px;
--space-xl: 64px;
--space-2xl: 96px;

/* 圆角 */
--radius-sm: 4px;
--radius-md: 8px;
--radius-lg: 16px;

/* 动效 */
--motion-hover: 150ms ease-out;
--motion-enter: 300ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：白牌核心 + 多品牌扩展 + 工具中性化 */
/* 应用方式：界面中性灰，品牌色仅在营销表达，核心系统无品牌色彩 */
```
