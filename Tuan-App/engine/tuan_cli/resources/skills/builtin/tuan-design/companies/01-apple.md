# 1. Apple — Human Interface Guidelines

> **类型**：软件 | **领域**：科技/操作系统 | **设计哲学**：Clarity, Deference, Depth, Consistency

| 规格总览 | 值 |
|---|---|
| 画布色 | 白/系统背景 |
| 强调色 | 系统蓝 |
| 字体策略 | SF Pro 全系 |
| 记忆点 | 内容优先无形设计 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## 设计规格（定本原文）

**领域标签**：科技/操作系统 | **设计哲学**：Clarity, Deference, Depth, Consistency

Apple HIG 的四大核心原则是 Clarity、Deference、Depth 和 Consistency。Clarity 要求文字在任何尺寸下都清晰可读、图标精确、功能显而易见；Deference 确保内容突出，周围视觉元素不与内容竞争；Depth 通过层级和动效传达空间关系；Consistency 保证跨设备体验统一。

**字体系统**：SF Pro、SF Compact、SF Mono 为系统字体。使用 Dynamic Type 样式（`largeTitle`、`body`、`caption`），不硬编码正文字号，必须使用 Auto Layout 适配全部字号范围。避免 Ultralight、Thin、Light 字重，优先使用 Regular、Medium、Semibold、Bold。

**色彩**：系统语义色彩（`label`、`secondaryLabel`、`systemBlue` 等）随亮/暗模式自动切换。颜色用于传达状态、提供视觉连续性和表达品牌。

**布局**：布局必须跨显示尺寸、方向和分屏配置自适应。使用安全区域、对齐锚点和 Auto Layout 保证响应式。

**材料与深度**：Materials 创建前景与背景元素之间的深度、层叠和层级感知。

**记忆点**：内容优先的“无形设计”——最好的界面是用户感觉不到界面存在，只感受到内容。

## CSS Token（可直接复现）

```
/* Apple HIG — 可复现设计系统 Token */

/* 字体 */
--font-display: 'SF Pro Display', -apple-system, sans-serif;
--font-body: 'SF Pro Text', -apple-system, sans-serif;
--font-mono: 'SF Mono', ui-monospace, monospace;

/* 字号（Dynamic Type 映射） */
--fs-largeTitle: clamp(2.125rem, 5vw, 3.25rem);
--fs-title1: 1.75rem;
--fs-title2: 1.375rem;
--fs-body: 1.0625rem;
--fs-caption: 0.75rem;
--fw-regular: 400;
--fw-medium: 500;
--fw-semibold: 600;

/* 色彩（亮色模式） */
--color-label: #000000;
--color-secondaryLabel: rgba(60,60,67,0.6);
--color-systemBlue: #007AFF;
--color-systemGreen: #34C759;
--color-systemRed: #FF3B30;
--color-background: #FFFFFF;
--color-secondaryBackground: #F2F2F7;

/* 间距 */
--space-xs: 4px;
--space-sm: 8px;
--space-md: 16px;
--space-lg: 24px;
--space-xl: 32px;
--space-2xl: 48px;

/* 圆角 */
--radius-sm: 8px;
--radius-md: 12px;
--radius-lg: 16px;
--radius-full: 9999px;

/* 动效 */
--motion-micro: 150ms ease-out;
--motion-enter: 400ms cubic-bezier(0.25, 0.1, 0.25, 1);
--motion-spring: 500ms cubic-bezier(0.175, 0.885, 0.32, 1.275);

/* 记忆点：内容优先，界面退让 */
/* 应用方式：所有 UI chrome 使用低饱和中性色，内容使用高对比 */
```
