# 8. McKinsey & Company — 高对比咨询权威

> **类型**：品牌 | **领域**：战略咨询 | **设计哲学**：High Contrast, Authoritative

| 规格总览 | 值 |
|---|---|
| 画布色 | 白 |
| 强调色 | `#2251FF` 电光蓝 |
| 字体策略 | Bower + McKinsey Sans |
| 记忆点 | 极端字体对比 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## 设计规格（定本原文）

**领域标签**：战略咨询 | **设计哲学**：High Contrast, Authoritative

McKinsey 2019 年品牌刷新以“高对比”为核心理念：深蓝与白色形成强烈对比，字体在富有特色的 Bower 衬线与干净的 Theinhardt 之间形成对比。蓝色仍然是核心色彩，象征使命与价值观的恒常性，但现在是更深的色调置于白色背景之上。

**字体**：Bower（以创始人 Marvin Bower 命名的定制衬线字体）+ McKinsey Sans。Bower 用于标题和展示，McKinsey Sans 用于正文。通过极端的字体对比创造有冲击力的演示效果。

**色彩**：Electric Blue `#2251FF` 与 Deep Navy `#051C2C` 的双重结构。双层次阴影系统。

**记忆点**：Bower 衬线 + McKinsey Sans 的极端字体对比 + 深蓝高对比 + 双层次阴影。

## CSS Token（可直接复现）

```
/* McKinsey — 可复现设计系统 Token */

/* 字体 */
--font-display: 'Bower', Georgia, serif;
--font-body: 'McKinsey Sans', 'Helvetica Neue', sans-serif;

/* 字号 */
--fs-display: clamp(2.5rem, 5vw, 4rem);
--fs-title: clamp(1.5rem, 3vw, 2rem);
--fs-body: 1rem;

/* 色彩 */
--mckinsey-blue: #2251FF;
--mckinsey-deep-navy: #051C2C;
--mckinsey-white: #FFFFFF;
--mckinsey-accent: #E3120B;
--text-primary: #0D0D0D;
--text-secondary: #666666;

/* 双层次阴影 */
--shadow-layer-1: 0 1px 3px rgba(0,0,0,0.08);
--shadow-layer-2: 0 4px 12px rgba(0,0,0,0.12);

/* 间距 */
--space-xs: 4px;
--space-sm: 8px;
--space-md: 16px;
--space-lg: 32px;
--space-xl: 64px;
--space-2xl: 96px;

/* 圆角 */
--radius-sm: 0px;
--radius-md: 2px;

/* 动效 */
--motion-hover: 150ms ease-out;
--motion-enter: 300ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：Bower 衬线 + McKinsey Sans 对比 + 深蓝 #051C2C + 双层次阴影 */
/* 应用方式：标题用 Bower 衬线，正文用 McKinsey Sans，主色 #2251FF */
```
