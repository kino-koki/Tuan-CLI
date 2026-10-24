# 3. Stripe — 技术奢华主义

> **类型**：软件 | **领域**：金融科技 | **设计哲学**：Vibrant Minimalism（活力极简）

| 规格总览 | 值 |
|---|---|
| 画布色 | 白/近白 |
| 强调色 | `#533AFD` 紫 |
| 字体策略 | sohne-var 字重300 |
| 记忆点 | 技术奢华低语 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## 设计规格（定本原文）

**领域标签**：金融科技 | **设计哲学**：Vibrant Minimalism（活力极简）

Stripe 的视觉身份是“技术奢华”的典范——工程精确性与编辑优雅的罕见交集。当大多数金融科技公司通过企业蓝和粗字重来传递可信度时，Stripe 选择“低语”。整个排版系统基于 `font-weight 300` 的标题，这一刻意反常规的选择成为品牌签名。轻盈字体配合慷慨留白，传达出 Dieter Rams 式的安静自信。

**色彩**：最深色不是黑色，而是午夜海军蓝 `rgb(6, 27, 49)`，柔化对比度而不牺牲可读性。品牌紫 `#533AFD` 仅出现在交互元素上，绝不用作装饰。背景保持白色或近白 `rgb(248, 250, 253)` 。渐变（橙 `#ff6118` → 粉 → 紫 `#533afd`）仅用于英雄区域的装饰性氛围，**绝不用于按钮或链接**。

**字体**：`sohne-var` 独家使用，标题字重 300（即使 56px 大标题也是 300）。代码块使用 SourceCodePro。

**零阴影、零媒体查询断点**：CSS 层面无阴影检测、无媒体查询。响应式逻辑由 JavaScript 驱动（Next.js），保持 CSS 层极致干净。

**记忆点**：字重 300 的大标题 + 午夜海军蓝正文 + 单一电光紫交互色 + 装饰性渐变仅限英雄区域。

## CSS Token（可直接复现）

```
/* Stripe — 可复现设计系统 Token */

/* 字体 */
--font-display: 'sohne-var', 'SF Pro Display', -apple-system, sans-serif;
--font-mono: 'SourceCodePro', ui-monospace, monospace;

/* 字号 */
--fs-display: clamp(3rem, 6vw, 3.5rem);
--fs-title: clamp(1.5rem, 3vw, 2rem);
--fs-body: 1rem;
--fw-display: 300;
--fw-body: 300;

/* 色彩 */
--stripe-purple: #533AFD;
--stripe-purple-hover: #2E2B8C;
--stripe-purple-tint: #E2E4FF;
--stripe-navy: #061B31;
--stripe-dark-bg: #0D1738;
--stripe-white: #FFFFFF;
--stripe-off-white: #F8FAFD;
--stripe-card-border: #E5EDF5;

/* 渐变（仅英雄区域） */
--gradient-hero: linear-gradient(135deg, #ff6118, #ffe0ef, #533afd);

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

/* 动效 */
--motion-hover: 150ms ease-out;
--motion-enter: 300ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：字重 300 大标题 + 电光紫 #533AFD 交互色 + 无阴影设计 */
/* 应用方式：所有标题 font-weight 300，交互色仅 #533AFD，无 box-shadow */
```
