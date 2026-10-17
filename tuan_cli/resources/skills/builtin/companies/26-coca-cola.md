# 26. Coca-Cola — 红色系统的全球统一

> **类型**：品牌 | **领域**：饮料快消 | **设计哲学**：One Iconic Brand, One Iconic Look

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` |
| 强调色 | `#F40009` 红 |
| 字体策略 | Spencerian Script |
| 记忆点 | 红白高对比 |

## 设计规格（定本原文）

**领域标签**：饮料快消 | **设计哲学**：One Iconic Brand, One Iconic Look

Coca-Cola 2026 年全球视觉身份刷新统一了 200 个市场的品牌表达，核心是强化四个品牌资产：红白配色、Dynamic Ribbon（动态丝带）、Arden Square（雅顿方块）和 Spencerian 手写体。更新不是重新发明，而是让每个元素更突出、更一致。Coke Zero Sugar 去掉了大部分黑色，Logo 改为白色，加大 “Zero Sugar” 衬线字。

**色彩**：Coca-Cola Red `#F40009` 是绝对主色，白色 `#FFFFFF` 是唯一辅助色，黑色仅作为少量强调。红白配色占据 90% 以上的品牌表达面积。

**字体**：Spencerian Script 是标志性手写体，经过调整以增强识别度和适用性。Coke Zero 使用衬线字体设置 “Zero Sugar”。正文使用简洁无衬线。

**间距**：品牌系统的间距逻辑围绕“让红色说话”——红色块面大量、连续，白色作为呼吸空间。没有复杂的间距系统，但红白交替的节奏本身就是空间语言。

**记忆点**：Coca-Cola Red + Spencerian Script + Dynamic Ribbon + 红白高对比系统。

## CSS Token（可直接复现）

```
/* Coca-Cola — 可复现设计系统 Token */

/* 字体 */
--font-display: 'Spencerian Script', cursive;
--font-body: 'Helvetica Neue', Arial, sans-serif;
--font-serif: Georgia, serif;

/* 字号 */
--fs-display: clamp(2.5rem, 5vw, 4rem);
--fs-title: clamp(1.5rem, 2.5vw, 2rem);
--fs-body: 1rem;
--fw-regular: 400;
--fw-bold: 700;

/* 色彩 */
--coke-red: #F40009;
--coke-red-dark: #CC0008;
--coke-white: #FFFFFF;
--coke-black: #000000;
--coke-cream: #F5F0E8;

/* 间距 */
--space-xs: 8px;
--space-sm: 16px;
--space-md: 24px;
--space-lg: 48px;
--space-xl: 96px;

/* 圆角 */
--radius-sm: 0px;
--radius-md: 4px;
--radius-lg: 8px;

/* 动效 */
--motion-hover: 150ms ease-out;
--motion-enter: 300ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：#F40009 + Spencerian Script + 红白高对比 */
/* 应用方式：红色为主，白色为唯一辅助，Spencerian 仅品牌表达 */
```
