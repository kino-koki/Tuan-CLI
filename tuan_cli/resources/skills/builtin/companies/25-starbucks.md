# 25. Starbucks — 四层绿的咖啡馆温暖

> **类型**：品牌 | **领域**：餐饮零售 | **设计哲学**：Warm Retail Flagship, Craft Materiality

| 规格总览 | 值 |
|---|---|
| 画布色 | `#f2f0eb` 奶油 |
| 强调色 | `#006241` 绿 |
| 字体策略 | SoDoSans |
| 记忆点 | 四层绿系统 |

## 设计规格（定本原文）

**领域标签**：餐饮零售 | **设计哲学**：Warm Retail Flagship, Craft Materiality

Starbucks 的设计系统是“温暖的零售旗舰店”——将咖啡馆的材质感搬到数字界面。暖奶油色画布（`#f2f0eb`）和陶瓷米白（`#edebe9`）参考了实际店铺材料：纸巾、墙面、木饰面。标志性的 Starbucks Green `#006241` 锚定品牌时刻。绿色不是一个色，而是四个校准过的色阶，每个映射到特定表面角色。金色 `#cba258` 仅用于 Rewards 等级仪式感，绝不作为通用强调色。

**字体**：SoDoSans（定制字体）以 -0.16px 字距贯穿几乎所有表面，读起来自信友好而非时尚杂志的冷峻。Rewards 页面切换到暖衬线（Lander Tall）唤起咖啡店黑板的怀旧感。Careers 页面使用手写体（Kalam）做个人杯名点缀。三种字体，三种语境，纪律严明。

**间距**：以 1.6rem（约 16px）为锚点的 rem 间距尺度，步进到 6.4rem（约 64px）。按钮一律 50px 全胶囊圆角，卡片 12px 圆角。

**记忆点**：四层绿系统 + 暖奶油画布 + SoDoSans 紧字距 + 全胶囊按钮 + 浮动圆形 Frap CTA。

## CSS Token（可直接复现）

```
/* Starbucks — 可复现设计系统 Token */

/* 字体 */
--font-display: 'SoDoSans', 'Helvetica Neue', sans-serif;
--font-body: 'SoDoSans', 'Helvetica Neue', sans-serif;
--font-serif: 'Lander Tall', 'Iowan Old Style', Georgia, serif;
--font-script: 'Kalam', 'Comic Sans MS', cursive;

/* 字号 */
--fs-display: clamp(2rem, 4vw, 3rem);
--fs-title: clamp(1.25rem, 2vw, 1.5rem);
--fs-body: 1rem;
--fs-note: 0.8125rem;
--fw-regular: 400;
--fw-medium: 500;
--fw-bold: 700;
--tracking-body: -0.16px;

/* 色彩 — 四层绿系统 */
--sb-green-starbucks: #006241;   /* H1 标题、品牌锚点 */
--sb-green-accent: #00754A;      /* CTA、Frap 浮动按钮 */
--sb-green-house: #1E3932;       /* 深色 feature band、页脚 */
--sb-green-uplift: #D4E9E2;      /* 装饰性、浅色背景 */

/* 画布 */
--sb-cream: #f2f0eb;
--sb-ceramic: #edebe9;
--sb-white: #FFFFFF;
--sb-dark: #1E3932;

/* 文字 */
--sb-text-primary: #1E3932;
--sb-text-secondary: #6B6B6B;

/* 仪式金 — 仅 Rewards */
--sb-gold: #cba258;

/* 间距 — rem 基准，锚定 16px */
--space-1: 0.4rem;    /* 6.4px */
--space-2: 0.8rem;    /* 12.8px */
--space-3: 1.6rem;    /* 25.6px — 锚点 */
--space-4: 3.2rem;    /* 51.2px */
--space-5: 6.4rem;    /* 102.4px */

/* 圆角 */
--radius-button: 50px;
--radius-card: 12px;
--radius-full: 9999px;

/* 阴影 */
--shadow-card: 0 2px 6px rgba(0,0,0,0.14);
--shadow-frap: 0 0 6px rgba(0,0,0,0.24), 0 8px 12px rgba(0,0,0,0.14);

/* 动效 */
--motion-press: 100ms ease-out;
--motion-enter: 300ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：四层绿 + 暖奶油 + SoDoSans + 全胶囊按钮 + Frap 浮动 CTA */
/* 应用方式：CTA 用 #00754A，H1 用 #006241，深色带 #1E3932，金色仅 Rewards */
```
