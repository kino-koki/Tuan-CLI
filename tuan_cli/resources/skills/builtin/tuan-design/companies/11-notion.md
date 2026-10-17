# 11. Notion — 温暖极简的内容容器

> **类型**：软件 | **领域**：生产力/知识管理 | **设计哲学**：Warm Minimalism, Content-First

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFDF9` 暖白 |
| 强调色 | `#0F172A` 海军蓝 |
| 字体策略 | 系统字体栈 |
| 记忆点 | 内容即主角 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## 设计规格（定本原文）

**领域标签**：生产力/知识管理 | **设计哲学**：Warm Minimalism, Content-First

Notion 的视觉语言是“温暖极简，内容优先”。暖白底面托举内容，排版清晰，留白充足，交互克制。不靠装饰吸引眼球，而是让用户创造的内容成为页面的主角。品牌导航用深海军蓝条带搭配品牌色便签点和网格线插图，传达“一体式工作空间”的丰富性而不喧闹。

**色彩**：深海军蓝作为品牌锚点，暖白画布承载内容。便签点使用品牌色（黄、蓝、红、紫）作为视觉标记，但仅在插图与品牌区域出现，不用于功能 UI。正文与界面使用深灰而非纯黑，保持温度。

**字体**：系统字体栈（`-apple-system, BlinkMacSystemFont, 'Segoe UI'`）保证跨平台一致性，在编辑场景下尤为关键。字号层级紧凑但清晰，正文 16px 起，标题字重 600–700，不过度拉大层级差。

**间距**：4px 基准网格，但实际使用中偏向 8px 的倍数。内容区块间距慷慨（48–64px），条目间距紧凑（12–16px），形成“阅读节奏而非浏览节奏”的密度。

**记忆点**：暖白画布 + 深海军蓝品牌条带 + 系统字体的低调精致 + 内容本身即视觉主角。

## CSS Token（可直接复现）

```
/* Notion — 可复现设计系统 Token */

/* 字体 */
--font-display: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, sans-serif;
--font-body: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, sans-serif;

/* 字号 */
--fs-display: clamp(2.25rem, 4.5vw, 3.5rem);
--fs-title: clamp(1.375rem, 2.5vw, 1.75rem);
--fs-body: 1rem;
--fs-note: 0.875rem;
--fw-regular: 400;
--fw-medium: 500;
--fw-semibold: 600;
--fw-bold: 700;

/* 色彩 */
--notion-navy: #0F172A;
--notion-warm-white: #FFFDF9;
--notion-warm-gray: #F7F6F3;
--notion-text-primary: #37352F;
--notion-text-secondary: #787774;
--notion-text-tertiary: #9B9A97;
--notion-border: #E9E9E7;
--notion-accent-yellow: #FDEB9E;
--notion-accent-blue: #D3E5EF;
--notion-accent-red: #FFE2DD;
--notion-accent-purple: #E8DEEE;

/* 间距 — 4px 基准，实用偏 8px */
--space-xs: 4px;
--space-sm: 8px;
--space-md: 16px;
--space-lg: 32px;
--space-xl: 48px;
--space-2xl: 64px;

/* 圆角 */
--radius-sm: 4px;
--radius-md: 8px;
--radius-lg: 12px;

/* 动效 */
--motion-hover: 120ms ease-out;
--motion-enter: 250ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：暖白画布 + 深海军蓝品牌 + 内容即主角 */
/* 应用方式：body 背景 #FFFDF9，品牌区域使用 #0F172A，便签点仅在插图出现 */
```
