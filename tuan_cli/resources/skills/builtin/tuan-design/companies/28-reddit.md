# 28. Reddit — 对话气泡的品牌语言

> **类型**：软件 | **领域**：社交社区 | **设计哲学**：Conversation-First, Accessible Expression

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` |
| 强调色 | `#FF4500` OrangeRed |
| 字体策略 | Reddit Display/Sans |
| 记忆点 | 对话气泡字体 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## 设计规格（定本原文）

**领域标签**：社交社区 | **设计哲学**：Conversation-First, Accessible Expression

Reddit 2023 年品牌刷新围绕“对话”这一核心概念展开。新定制字体 Reddit Display 的计数器形状直接设计成对话气泡的形状，Reddit Sans 以高 x-height 和消歧字母形式保证可读性和无障碍性。品牌色从 OrangeRed 扩展到 GuavaPink、LimeGreen、BananaYellow、JuniperBlue，以表达 Reddit 社区的多样性。

**色彩**：OrangeRed `#FF4500` 是签名色（upvote 箭头、CTA、Logo），新增 GuavaPink、LimeGreen、BananaYellow、JuniperBlue 四色代表社区多样性。画布白色，文字深灰。

**字体**：Reddit Display（标题，对话气泡计数形状）和 Reddit Sans（正文，高 x-height 可读性）。Reddit Sans 已开源，可在 GitHub 和 Google Fonts 获取。

**间距**：社区内容密度较高，卡片间距 12–16px，区块间距 24–32px。

**记忆点**：OrangeRed #FF4500 + 对话气泡计数形状 + 五色社区表达 + Reddit Sans 开源。

## CSS Token（可直接复现）

```
/* Reddit — 可复现设计系统 Token */

/* 字体 */
--font-display: 'Reddit Display', 'Reddit Sans', sans-serif;
--font-body: 'Reddit Sans', 'Helvetica Neue', sans-serif;

/* 字号 */
--fs-display: clamp(1.75rem, 3.5vw, 2.5rem);
--fs-title: clamp(1.125rem, 2vw, 1.375rem);
--fs-body: 0.875rem;
--fs-note: 0.75rem;
--fw-regular: 400;
--fw-medium: 500;
--fw-bold: 700;

/* 色彩 */
--reddit-orangered: #FF4500;
--reddit-guava-pink: #FF6B9D;
--reddit-lime-green: #A3D977;
--reddit-banana-yellow: #FFD93D;
--reddit-juniper-blue: #4A90D9;
--reddit-white: #FFFFFF;
--reddit-dark: #1A1A1B;
--reddit-gray-500: #7C7C7C;

/* 间距 */
--space-xs: 4px;
--space-sm: 8px;
--space-md: 12px;
--space-lg: 16px;
--space-xl: 24px;
--space-2xl: 32px;

/* 圆角 */
--radius-sm: 4px;
--radius-md: 8px;
--radius-lg: 12px;
--radius-full: 9999px;

/* 动效 */
--motion-hover: 120ms ease-out;
--motion-enter: 250ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：#FF4500 + 对话气泡字体 + 五色社区表达 */
/* 应用方式：主色 #FF4500，社区色用于标签和身份表达 */
```
