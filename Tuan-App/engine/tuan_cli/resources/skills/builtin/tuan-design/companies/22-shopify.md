# 22. Shopify Polaris — 商家优先的精密工具

> **类型**：软件 | **领域**：电商平台 | **设计哲学**：Merchant-First, Pro Design Language

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` |
| 强调色 | `#5c6ac4` Indigo |
| 字体策略 | Inter |
| 记忆点 | Indigo+Green 双交互色 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## 设计规格（定本原文）

**领域标签**：电商平台 | **设计哲学**：Merchant-First, Pro Design Language

Shopify Polaris 的设计语言在 v12 中引入了 “Pro” 概念——优先考虑效率和直觉交互，服务于商家日常任务。设计系统使用 primitive token 和 semantic token 两层结构。v12 的显著变化是引入新 Web 字体 Inter，同时建立更清晰的 token 意图传达体系。

**色彩**：Polaris Indigo `#5c6ac4` 是通用 CTA 色，Polaris Green `#008060` 用于推荐层级的 CTA 和关键操作（Save、Confirm）。两种交互色需有纪律地使用。中性色以灰阶为主，背景白色或浅灰。

**字体**：Inter 是 v12 引入的新 Web 字体，用于所有界面文本。字体系统强调清晰度和可读性，适合数据密集型管理界面。

**间距**：4px 基准网格，管理界面密度适中偏高。组件内间距紧凑（4–8px），区块间距 16–24px。

**记忆点**：Indigo + Green 双交互色 + Inter 字体 + 商家效率优先的精密密度。

## CSS Token（可直接复现）

```
/* Shopify Polaris — 可复现设计系统 Token */

/* 字体 */
--font-display: 'Inter', -apple-system, sans-serif;
--font-body: 'Inter', -apple-system, sans-serif;

/* 字号 */
--fs-display: clamp(1.75rem, 3vw, 2.25rem);
--fs-title: clamp(1.125rem, 1.8vw, 1.375rem);
--fs-body: 0.875rem;
--fs-note: 0.75rem;
--fw-regular: 400;
--fw-medium: 500;
--fw-semibold: 600;

/* 色彩 */
--polaris-indigo: #5c6ac4;
--polaris-indigo-hover: #4a5aa8;
--polaris-green: #008060;
--polaris-green-hover: #006e52;
--polaris-text-primary: #1a1a1a;
--polaris-text-secondary: #6b6b6b;
--polaris-surface: #FFFFFF;
--polaris-surface-hover: #F7F7F7;
--polaris-border: #E1E1E1;
--polaris-border-focus: #5c6ac4;

/* 间距 — 4px 基准 */
--space-100: 4px;
--space-200: 8px;
--space-300: 12px;
--space-400: 16px;
--space-500: 20px;
--space-600: 24px;

/* 圆角 */
--radius-sm: 4px;
--radius-md: 8px;
--radius-lg: 12px;

/* 动效 */
--motion-hover: 100ms ease-out;
--motion-enter: 200ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：Indigo #5c6ac4 + Green #008060 双交互色 + Inter */
/* 应用方式：通用 CTA 用 Indigo，推荐/确认动作用 Green */
```
