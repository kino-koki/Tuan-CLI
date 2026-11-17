# 12. Atlassian — 企业级清晰结构

> **类型**：软件 | **领域**：企业协作 | **设计哲学**：Sharp Enterprise Clarity, Accessible by Default

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` |
| 强调色 | `#0052CC` Atlassian蓝 |
| 字体策略 | Charlie Display/Text |
| 记忆点 | 无障碍内建 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## 设计规格（定本原文）

**领域标签**：企业协作 | **设计哲学**：Sharp Enterprise Clarity, Accessible by Default

Atlassian Design System（ADS）服务于超过 18 款产品（Jira、Confluence 等），其核心是“清晰、现代、一致”。2025 年品牌刷新将无障碍作为设计系统的基础层——超过 6,000 个无障碍问题在 2024–2025 年间得到解决。排版系统在 2025 年 Q3 进入 GA，提供更清晰的视觉层级。

**色彩**：以白色表面为主，浅蓝支撑背景，深海军蓝文字，锚定在 Atlassian Blue `#0052CC` 附近。色彩 token 以 CSS Custom Properties 管理，主题切换高效。

**字体**：Charlie Display 用于标题，Charlie Text 用于正文。字体系统提供更清晰的层级与无障碍改进。

**间距**：企业级 4px 网格。组件密度较高（适合信息密集型界面），但区块间距保持呼吸感。

**记忆点**：Atlassian Blue 的强锚定 + Charlie 字体对 + 无障碍作为系统基础设施。

## CSS Token（可直接复现）

```
/* Atlassian ADS — 可复现设计系统 Token */

/* 字体 */
--font-display: 'Charlie Display', 'Inter', sans-serif;
--font-body: 'Charlie Text', 'Inter', sans-serif;

/* 字号 */
--fs-display: clamp(2rem, 4vw, 3rem);
--fs-title: clamp(1.25rem, 2vw, 1.5rem);
--fs-body: 0.875rem;
--fs-note: 0.75rem;
--fw-regular: 400;
--fw-medium: 500;
--fw-semibold: 600;

/* 色彩 */
--ads-blue: #0052CC;
--ads-blue-hover: #0747A6;
--ads-blue-light: #DEEBFF;
--ads-text-primary: #172B4D;
--ads-text-secondary: #6B778C;
--ads-surface: #FFFFFF;
--ads-surface-hover: #F4F5F7;
--ads-border: #DFE1E6;
--ads-border-focus: #4C9AFF;

/* 间距 — 4px 基准 */
--space-xs: 2px;
--space-sm: 4px;
--space-md: 8px;
--space-lg: 16px;
--space-xl: 24px;
--space-2xl: 32px;

/* 圆角 */
--radius-sm: 3px;
--radius-md: 6px;

/* 动效 */
--motion-fast: 100ms ease-out;
--motion-enter: 250ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：#0052CC 强锚定 + Charlie 字体对 + 无障碍内建 */
/* 应用方式：交互元素统一 #0052CC，标题 Charlie Display，正文 Charlie Text */
```
