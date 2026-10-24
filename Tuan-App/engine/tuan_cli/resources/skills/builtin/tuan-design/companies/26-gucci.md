# 26. Gucci — 黑白的极致奢华

> **类型**：品牌 | **领域**：奢侈品 | **设计哲学**：Monochrome Luxury, Maximalist Product, Minimalist Chrome

| 规格总览 | 值 |
|---|---|
| 画布色 | `#000000`/`#FFFFFF` |
| 强调色 | 无（产品即色） |
| 字体策略 | Gucci Sans Pro |
| 记忆点 | 纯黑白 UI |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## 设计规格（定本原文）

**领域标签**：奢侈品 | **设计哲学**：Monochrome Luxury, Maximalist Product, Minimalist Chrome

Gucci 的网站设计贯彻“产品即色彩”的奢侈品哲学——界面 chrome 彻底黑白，所有色彩来自产品摄影。Gucci Sans Pro 字体配合纯黑 CTA 构建出“奢华直角美学”。金色仅出现在 Logo 中，绝不泛用。设计极简精致，让产品成为唯一焦点。

**色彩**：纯黑 `#000000` 和纯白 `#FFFFFF` 构成全部 UI。金色仅出现在 Logo 中。产品摄影提供所有色彩——绿色红条纹、花卉印花、皮革材质。

**字体**：Gucci Sans Pro 是品牌字体，几何无衬线，干净利落。字体层级克制，标题与正文的差异靠字重和字号，不靠花哨装饰。

**间距**：奢侈品网站需要慷慨的留白。区块间距 96–128px，条目间距 32–48px。大量负空间创造“产品呼吸”的感觉。

**记忆点**：纯黑白 UI + 产品即色彩 + Gucci Sans Pro + 金色仅 Logo。

## CSS Token（可直接复现）

```
/* Gucci — 可复现设计系统 Token */

/* 字体 */
--font-display: 'Gucci Sans Pro', 'Helvetica Neue', sans-serif;
--font-body: 'Gucci Sans Pro', 'Helvetica Neue', sans-serif;

/* 字号 */
--fs-display: clamp(2rem, 4vw, 3rem);
--fs-title: clamp(1.125rem, 2vw, 1.375rem);
--fs-body: 0.875rem;
--fs-note: 0.75rem;
--fw-regular: 400;
--fw-bold: 700;

/* 色彩 — 纯黑白 */
--gucci-black: #000000;
--gucci-white: #FFFFFF;
--gucci-gold: #D4AF37;   /* 仅 Logo */
--gucci-gray-100: #F5F5F5;
--gucci-gray-500: #999999;

/* 间距 — 慷慨留白 */
--space-xs: 8px;
--space-sm: 16px;
--space-md: 32px;
--space-lg: 64px;
--space-xl: 96px;
--space-2xl: 128px;

/* 圆角 */
--radius-sm: 0px;
--radius-md: 0px;

/* 动效 */
--motion-hover: 200ms ease-out;
--motion-enter: 400ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：纯黑白 + 产品即色彩 + Gucci Sans Pro */
/* 应用方式：UI 纯黑白，金色仅 Logo，产品摄影提供全部色彩 */
```
