# 5. Airbnb — 温暖的旅行杂志

> **类型**：软件 | **领域**：消费市场 | **设计哲学**：Belong Anywhere, Photography-First

| 规格总览 | 值 |
|---|---|
| 画布色 | `#ffffff` 纯白 |
| 强调色 | `#ff385c` Rausch红 |
| 字体策略 | Airbnb Cereal VF |
| 记忆点 | 三层阴影大圆角 |

## 设计规格（定本原文）

**领域标签**：消费市场 | **设计哲学**：Belong Anywhere, Photography-First

Airbnb 的设计基础是纯白画布 `#ffffff`，Rausch Red `#ff385c` 是唯一的品牌强调色——以 Airbnb 的第一个街道地址命名。摄影优先的列表卡片是核心内容，图片是英雄内容。

**字体**：Airbnb Cereal VF——自定义可变字体，温暖的圆润终端呼应“belong anywhere”的品牌哲学。字重范围紧凑：500（大多数 UI）、600（强调）、700（主标题）。标题使用轻微负字距（-0.18px 到 -0.44px），创造舒适亲密的阅读体验。

**阴影系统**：三层阴影堆叠（`rgba(0,0,0,0.02) 0px 0px 0px 1px` 边框环 + `rgba(0,0,0,0.04) 0px 2px 6px` 柔和模糊 + `rgba(0,0,0,0.1) 0px 4px 8px` 更强模糊），创造微妙温暖的悬浮感。

**圆角**：按钮 8px、徽章 14px、卡片 20px、大元素 32px、圆形导航控件 50%。

**记忆点**：纯白画布 + Rausch Red 单强调色 + 三层温暖阴影 + 大圆角 + 摄影优先。

## CSS Token（可直接复现）

```
/* Airbnb — 可复现设计系统 Token */

/* 字体 */
--font-display: 'DM Sans', 'Airbnb Cereal VF', system-ui, sans-serif;
--font-mono: ui-monospace, SFMono-Regular, Menlo, monospace;

/* 字号 */
--fs-display: clamp(2rem, 4vw, 3rem);
--fs-title: clamp(1.25rem, 2vw, 1.5rem);
--fs-body: 1rem;
--fw-medium: 500;
--fw-semibold: 600;
--fw-bold: 700;
--tracking-heading: -0.18px;
--tracking-display: -0.44px;

/* 色彩 */
--rausch-red: #ff385c;
--deep-rausch: #e00b41;
--near-black: #222222;
--pure-white: #ffffff;
--surface-base: #FEFEFE;
--luxe-purple: #460479;

/* 三层阴影 */
--shadow-card:
  rgba(0,0,0,0.02) 0px 0px 0px 1px,
  rgba(0,0,0,0.04) 0px 2px 6px,
  rgba(0,0,0,0.1) 0px 4px 8px;

/* 圆角 */
--radius-button: 8px;
--radius-badge: 14px;
--radius-card: 20px;
--radius-large: 32px;
--radius-full: 50%;

/* 间距 */
--space-xs: 4px;
--space-sm: 8px;
--space-md: 16px;
--space-lg: 24px;
--space-xl: 48px;

/* 动效 */
--motion-hover: 200ms ease-out;
--motion-enter: 400ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：纯白 + Rausch Red #ff385c + 三层阴影 + 大圆角 */
/* 应用方式：CTA 用 #ff385c，卡片使用三层阴影，圆角 20px */
```
