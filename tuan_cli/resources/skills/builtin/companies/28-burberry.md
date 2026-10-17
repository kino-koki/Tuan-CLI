# 28. Burberry — 皇家蓝的当代英国

> **类型**：品牌 | **领域**：奢侈品 | **设计哲学**：Contemporary British, Heritage Modernized

| 规格总览 | 值 |
|---|---|
| 画布色 | `#F5F0E8` 骨色 |
| 强调色 | `#1E3A8A` 皇家蓝 |
| 字体策略 | Burberry Serif |
| 记忆点 | 皇家蓝+战马 |

## 设计规格（定本原文）

**领域标签**：奢侈品 | **设计哲学**：Contemporary British, Heritage Modernized

Burberry 在 Daniel Lee 主导下焕新品牌识别，“战马”骑士图案回归，皇家蓝成为代表色。Logo 字体变得纤细瘦长，改为衬线字体，在古典与现代之间达到平衡。红色和蜜色的 TB 交织图案是对品牌 1901 年最初 Logo 的呼应。

**色彩**：皇家蓝（Royal Blue）是新的代表色，搭配骨色背景。TB 交织图案使用珊瑚红、蜜色和白色。品牌在皇家蓝与黑白版本之间灵活切换。

**字体**：衬线字体（纤细瘦长，优雅当代）用于品牌表达。Bodoni 风格的自定义字体，自 1901 年以来就是品牌识别的一部分。

**间距**：奢侈品编辑节奏。区块间距 96–128px，产品展示区域慷慨留白。

**记忆点**：皇家蓝 + 衬线字体 + 战马回归 + TB 交织图案（珊瑚红/蜜色/白）。

## CSS Token（可直接复现）

```
/* Burberry — 可复现设计系统 Token */

/* 字体 */
--font-display: 'Burberry Serif', 'Bodoni', Georgia, serif;
--font-body: 'Burberry Sans', 'Helvetica Neue', sans-serif;

/* 字号 */
--fs-display: clamp(2rem, 4vw, 3rem);
--fs-title: clamp(1.25rem, 2vw, 1.5rem);
--fs-body: 0.9375rem;
--fw-regular: 400;
--fw-light: 300;

/* 色彩 */
--burberry-royal-blue: #1E3A8A;
--burberry-bone: #F5F0E8;
--burberry-black: #000000;
--burberry-white: #FFFFFF;
--burberry-coral: #E85D4A;
--burberry-honey: #D4A853;

/* 间距 */
--space-xs: 8px;
--space-sm: 16px;
--space-md: 32px;
--space-lg: 64px;
--space-xl: 96px;
--space-2xl: 128px;

/* 圆角 */
--radius-sm: 0px;
--radius-md: 2px;

/* 动效 */
--motion-hover: 200ms ease-out;
--motion-enter: 400ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：皇家蓝 + 衬线字体 + 战马 + TB 交织图案 */
/* 应用方式：主色皇家蓝，背景骨色，衬线字体纤细优雅 */
```
