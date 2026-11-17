# 21. Amazon — 功能至上的规模效率

> **类型**：软件 | **领域**：电商 | **设计哲学**：Information Density, Conversion-First

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF`/`#EAEDED` |
| 强调色 | `#FF9900` 橙 |
| 字体策略 | Amazon Ember + Arial |
| 记忆点 | 金黄渐变 Add to Cart |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## 设计规格（定本原文）

**领域标签**：电商 | **设计哲学**：Information Density, Conversion-First

Amazon 的设计系统是“规模效率”的极致体现。页面信息密度极高，每屏承载大量商品与信息，但通过严格的层级与间距规则保持可读性。设计目标不是美学愉悦，而是降低购买决策摩擦。

**色彩**：Amazon Orange `#FF9900` 是品牌主色，用于按钮、强调和链接。Amazon Dark Navy `#131921` 是页头/页脚背景。亮黄色 `#FFD814` 是“Add to Cart”按钮的专属色，橙黄 `#FFA41C` 是“Buy Now”按钮色。页面背景以白色 `#FFFFFF` 和浅灰 `#EAEDED` 为主，信息密度高但保持清晰。

**字体**：Amazon Ember 是品牌字体，等宽数字用于价格展示。小尺寸场景（13–14px）大量使用 Arial，强化数据密度。字体层级紧凑，正文与标题的字号差不大，靠字重区分层级。

**间距**：4px 基准网格，但信息密集场景下间距紧凑（8–16px）。卡片间距 12–16px，区块间距 24–32px。

**记忆点**：金黄到琥珀渐变的“Add to Cart”胶囊按钮 + 深海军蓝页头 + 极高信息密度。

## CSS Token（可直接复现）

```
/* Amazon — 可复现设计系统 Token */

/* 字体 */
--font-display: 'Amazon Ember Display', 'Amazon Ember', Arial, sans-serif;
--font-body: 'Amazon Ember', Arial, sans-serif;
--font-mono: 'Amazon Ember Mono', Consolas, monospace;

/* 字号 */
--fs-display: clamp(1.75rem, 3.5vw, 2.5rem);
--fs-title: clamp(1.125rem, 2vw, 1.375rem);
--fs-body: 0.875rem;
--fs-note: 0.75rem;
--fw-regular: 400;
--fw-medium: 500;
--fw-bold: 700;

/* 色彩 */
--amazon-orange: #FF9900;
--amazon-dark-navy: #131921;
--amazon-navy: #232F3E;
--amazon-white: #FFFFFF;
--amazon-light-gray: #EAEDED;
--amazon-soft-gray: #F3F3F3;
--amazon-text-primary: #0F1111;
--amazon-text-secondary: #565959;
--amazon-link: #007185;
--amazon-link-hover: #C7511F;
--amazon-button-yellow: #FFD814;
--amazon-button-yellow-hover: #F7CA00;
--amazon-button-orange: #FFA41C;
--amazon-button-orange-hover: #FA8900;
--amazon-success: #067D62;
--amazon-error: #B12704;
--amazon-deal-red: #CC0C39;
--amazon-star-gold: #FFA41C;
--amazon-prime-blue: #00A8E1;

/* 间距 — 4px 基准 */
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

/* 动效 */
--motion-hover: 120ms ease-out;
--motion-enter: 250ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：金黄渐变 Add to Cart + 深海军蓝页头 + 极高信息密度 */
/* 应用方式：CTA 用 #FFD814 渐变，页头 #131921，信息密集排列 */
```
