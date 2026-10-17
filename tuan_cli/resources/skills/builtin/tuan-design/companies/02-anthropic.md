# 2. Anthropic — 温暖研究文档风

> **类型**：软件 | **领域**：科技/AI 研究 | **设计哲学**：Warm, trustworthy, thoughtfully restrained

| 规格总览 | 值 |
|---|---|
| 画布色 | `#faf9f5` 奶油 |
| 强调色 | `#d97757` 赤陶 |
| 字体策略 | Poppins + 衬线正文（2024 年后官方品牌字体已迭代为 Styrene / Copernicus 系，本项目录为早期快照） |
| 记忆点 | 研究文档温暖感 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## 设计规格（定本原文）

**领域标签**：科技/AI 研究 | **设计哲学**：Warm, trustworthy, thoughtfully restrained

Anthropic 刻意避开 AI 品牌常见的冷峻审美，转而采用有机的棕褐色调 + 编辑排版（衬线正文）+ 微妙的赤陶色强调，传达安全聚焦、以人为本的 AI 研究气质。设计参考点不是“产品页面”，而是“研究文档”——温暖奶油底色让页面读起来像一本深思熟虑的杂志，而非交易终端。

**色彩**：权威十六进制色码。基础色：Dark `#141413`（近黑，有温度）、Light `#faf9f5`（标志性奶油/棕褐色）、Mid Gray `#b0aea5`、Light Gray `#e8e6dc`。强调色：橙色/赤陶 `#d97757`（主强调）、蓝色 `#6a9bcc`（次级强调）、绿色/鼠尾草 `#788c5d`（三级强调）。**绝不使用纯黑 `#000` 或纯白 `#fff`** 。

**字体**：双字体系统。标题使用 Poppins（Arial fallback），正文使用衬线字体（editorial serif）。Geist Studio 描述这对组合为“技术精致与迷人古怪并存”。注：2024 年后 Anthropic 官方品牌字体已迭代为 Styrene（标题）/ Copernicus（正文）系列，本项目记录为早期快照，落地时以官网现行字体为准。

**色彩使用规则**：多个非文字形状循环使用强调色时，按橙 → 蓝 → 绿 → 橙的顺序循环，相邻两个不使用同色。每个卡片/区域只使用一个大胆强调色，其余降为柔和。

**记忆点**：温暖的奶油色画布 + 衬线正文 + 单一赤陶强调色——让 AI 产品读起来像人文研究论文，而非技术工具。

## CSS Token（可直接复现）

```
/* Anthropic — 可复现设计系统 Token */

/* 字体（早期快照：Poppins + Georgia；2024 年后官方为 Styrene + Copernicus，落地以官网为准） */
--font-display: 'Poppins', 'Arial', sans-serif;
--font-body: Georgia, 'Times New Roman', serif;

/* 字号 */
--fs-display: clamp(2.5rem, 5vw, 4rem);
--fs-title: clamp(1.5rem, 3vw, 2rem);
--fs-body: 1.0625rem;
--fs-note: 0.875rem;

/* 色彩 — 基础层（90%） */
--anthropic-dark: #141413;
--anthropic-light: #faf9f5;
--anthropic-mid-gray: #b0aea5;
--anthropic-light-gray: #e8e6dc;

/* 色彩 — 强调层（10%） */
--anthropic-orange: #d97757;
--anthropic-blue: #6a9bcc;
--anthropic-sage: #788c5d;

/* 语义映射 */
--surface-page: var(--anthropic-light);
--text-primary: var(--anthropic-dark);
--text-secondary: var(--anthropic-mid-gray);
--accent-primary: var(--anthropic-orange);
--border-default: var(--anthropic-light-gray);

/* 间距 */
--space-xs: 4px;
--space-sm: 8px;
--space-md: 16px;
--space-lg: 32px;
--space-xl: 64px;
--space-2xl: 96px;

/* 动效 */
--motion-enter: 400ms cubic-bezier(0.25, 0.1, 0.25, 1);
--motion-hover: 150ms ease-out;

/* 记忆点：奶油画布 + 衬线正文 + 赤陶强调 */
/* 应用方式：body 背景 #faf9f5，标题 Poppins，正文 Georgia，CTA 用 #d97757 */
```
