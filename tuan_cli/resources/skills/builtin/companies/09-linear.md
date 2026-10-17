# 9. Linear — 暗色原生设计

> **类型**：软件 | **领域**：开发者工具 | **设计哲学**：Darkness as Native Medium

| 规格总览 | 值 |
|---|---|
| 画布色 | `#08090A` 近黑 |
| 强调色 | `#5E6AD2` 淡紫 |
| 字体策略 | Inter Variable + Tiempos |
| 记忆点 | 六级暗色层级 |

## 设计规格（定本原文）

**领域标签**：开发者工具 | **设计哲学**：Darkness as Native Medium

Linear 将暗色视为原生媒介——不是“切换到暗色模式”，而是每个元素被刻意放置其上的基础画布。近黑画布 `#08090a` 上，内容如同星光从黑暗中浮现。这不是一个应用到亮色设计上的暗色主题——**黑暗就是原生媒介本身**。

**背景层级**：`#08090A`（最深背景）→ `#0F1011` → `#141516` → `#1C1C1F` → `#232326` → `#28282C`（最浅层级）。六级背景层级创造空间深度感。

**字体**：`Inter Variable` 用于 UI，`Tiempos Headline` 用于展示标题。4px 网格系统。

**状态色**：一组精选的状态色，在暗色画布上保持鲜艳但不刺眼。

**记忆点**：近黑画布 #08090A + 六级背景层级 + Inter Variable + 内容如星光浮现。

## CSS Token（可直接复现）

```
/* Linear — 可复现设计系统 Token */

/* 字体 */
--font-display: 'Tiempos Headline', Georgia, serif;
--font-body: 'Inter Variable', 'Inter', sans-serif;

/* 字号 */
--fs-display: clamp(2rem, 4vw, 3rem);
--fs-title: clamp(1.125rem, 1.5vw, 1.375rem);
--fs-body: 0.875rem;
--fw-regular: 400;
--fw-medium: 500;

/* 色彩 — 暗色原生 */
--bg-level-0: #08090A;
--bg-level-1: #0F1011;
--bg-level-2: #141516;
--bg-level-3: #1C1C1F;
--bg-level-4: #232326;
--bg-level-5: #28282C;
--text-primary: #F7F8F8;
--text-secondary: #8A8F98;
--text-tertiary: #6E7178;
--accent-primary: #5E6AD2;
--accent-success: #4CB782;
--accent-warning: #F2C94C;
--accent-error: #EB5757;
--border-subtle: rgba(255,255,255,0.08);
--border-default: rgba(255,255,255,0.12);

/* 间距 — 4px 基准 */
--space-xs: 4px;
--space-sm: 8px;
--space-md: 12px;
--space-lg: 16px;
--space-xl: 24px;
--space-2xl: 32px;

/* 圆角 */
--radius-sm: 4px;
--radius-md: 6px;
--radius-lg: 8px;

/* 动效 */
--motion-hover: 120ms ease-out;
--motion-enter: 250ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：近黑画布 #08090A + 六级背景层级 + 内容如星光浮现 */
/* 应用方式：body 背景 #08090A，通过 bg-level 1-5 建立空间层级 */
```
