# 4. IBM Carbon — 4px 网格的精密工程

> **类型**：软件 | **领域**：企业科技 | **设计哲学**：Precision, Accessibility, Consistency

| 规格总览 | 值 |
|---|---|
| 画布色 | 白 |
| 强调色 | `#0f62fe` 蓝 |
| 字体策略 | IBM Plex |
| 记忆点 | 4px网格零圆角 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## 设计规格（定本原文）

**领域标签**：企业科技 | **设计哲学**：Precision, Accessibility, Consistency

IBM Carbon 以精确的 4px 网格对齐作为其间距系统。Carbon v11 引入了 CSS Grid 在 2x 网格之上构建稳健布局，桌面端使用 16 列网格，平板缩放到 8 列，移动端缩放到 4 列。IBM Plex 是唯一字体。**营销网站几乎不使用阴影**——阴影 token 仅存在于产品/应用界面。

**色彩**：Carbon v11 将所有颜色 token 以 CSS Custom Properties 形式发布，使得亮/暗模式切换极其简单和高效。任何使用颜色 token 的组件都能自动适应页面主题。

**Token 分层**：`@carbon/themes` 提供颜色 token（如 `$interactive-01`），`@carbon/type` 提供类型 token。

**记忆点**：4px 网格的绝对忠诚 + IBM Plex 单一字体 + 营销网站零阴影 + CSS Grid 16列系统。

## CSS Token（可直接复现）

```
/* IBM Carbon — 可复现设计系统 Token */

/* 字体 */
--font-display: 'IBM Plex Sans', sans-serif;
--font-mono: 'IBM Plex Mono', monospace;

/* 字号 */
--fs-display: clamp(2.625rem, 5vw, 3.375rem);
--fs-title: clamp(1.75rem, 3vw, 2.25rem);
--fs-body: 0.875rem;
--fs-note: 0.75rem;
--fw-regular: 400;
--fw-semibold: 600;

/* 色彩 */
--cds-interactive-01: #0f62fe;
--cds-interactive-hover: #0353e9;
--cds-text-primary: #161616;
--cds-text-secondary: #525252;
--cds-background: #ffffff;
--cds-layer-01: #f4f4f4;
--cds-layer-02: #e0e0e0;
--cds-border-subtle: #e0e0e0;
--cds-support-error: #da1e28;
--cds-support-success: #24a148;

/* 间距 — 4px 基准 */
--spacing-01: 2px;
--spacing-02: 4px;
--spacing-03: 8px;
--spacing-04: 12px;
--spacing-05: 16px;
--spacing-06: 24px;
--spacing-07: 32px;
--spacing-08: 40px;
--spacing-09: 48px;

/* 网格 */
--grid-columns-desktop: 16;
--grid-columns-tablet: 8;
--grid-columns-mobile: 4;
--grid-gutter: 32px;

/* 圆角 */
--radius-sm: 0px;
--radius-md: 0px;
--radius-lg: 0px;

/* 动效 */
--motion-fast: 110ms cubic-bezier(0, 0, 0.38, 0.9);
--motion-moderate: 240ms cubic-bezier(0.2, 0, 0.38, 0.9);

/* 记忆点：4px 网格 + 零圆角 + 营销零阴影 + IBM Plex */
/* 应用方式：所有间距为 4 的倍数，border-radius 全部为 0，营销页无 box-shadow */
```
