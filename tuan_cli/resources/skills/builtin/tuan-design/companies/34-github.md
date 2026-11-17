# 34. GitHub — Primer 设计系统

> **类型**：软件 | **领域**：开发者平台 | **设计哲学**：System over components, Accessibility, Community

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` |
| 强调色 | `#0969DA` Primer蓝 |
| 字体策略 | 系统栈 + ui-monospace |
| 记忆点 | 密度、复用、透明度 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## HTML 板块 · 官网与营销页

### 设计哲学

GitHub 官网体现"开发者的诚实"：白底、6px 圆角、系统字体、代码即装饰——hero 常见终端窗口/代码截图，强调透明、效率与社区。营销站支持暗色 `#0D1117`，八爪鱼 logo 是唯一吉祥物。设计语言：**不假装创新，只把工程讲清楚**。

### 色彩

白 `#FFFFFF`、近黑 `#1F2328`、accent `#0969DA`；次要文字 `#656d76`；边框 `#d0d7de`；浅底 `#f6f8fa`；暗色 bg `#0D1117`、文字 `#f0f6fc`、accent `#4493f8`。

### 字体

系统栈 `-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial`；代码 `ui-monospace, SFMono-Regular, Menlo`；标题 36–56px SemiBold，正文 16px。

### 布局、间距、圆角与动效

4/8 网格；区块 64–96px；按钮/输入 6px 圆角，大营销卡 16–24px；动效 150ms ease-out，仅 hover 颜色/阴影微变。



### HTML CSS Token

```css
/* GitHub — HTML 官网 Token */
--gh-bg: #FFFFFF;
--gh-ink: #1F2328;
--gh-muted: #656d76;
--gh-border: #d0d7de;
--gh-canvas-subtle: #f6f8fa;
--gh-accent: #0969DA;
--gh-accent-hover: #0860CA;
--gh-bg-dark: #0D1117;
--gh-fg-dark: #f0f6fc;
--gh-accent-dark: #4493f8;
--gh-radius: 6px;
--gh-radius-card: 16px;
--font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
--font-mono: ui-monospace, SFMono-Regular, Menlo, monospace;
--space-section: 96px;
--motion: 150ms ease-out;
/* 应用：白底黑字，蓝 #0969DA 做链接/CTA，圆角 6px 起步，代码块可当装饰 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

Primer 原则：一切组件"像同一个系统的一部分"；可访问优先（对比度、键盘、屏幕阅读器）；组件化与主题复用（CSS 变量明暗切换）。产品界面以高密度列表（repos、issues、PRs）著称——**信息密度是功能，不是妥协**。

### 色彩（组件与语义 Token）

明色：canvas 默认 `#ffffff`、canvas-subtle `#f6f8fa`、bg-accent-subtle `#ddf4ff`；fg 默认 `#1F2328`、muted `#656d76`、accent `#0969DA`、success `#1a7f37`、attention `#9a6700`、danger `#cf222e`、done `#8250df`；border 默认 `#d0d7de`、muted `#d8dee4`。暗色对应 bg `#0d1117`、fg `#f0f6fc`、accent `#4493f8`。

### 字体

系统栈；代码字体 mono；基准字号小（14px），标题 20–32px。表格、标签、导航全部高密度。

### 布局、间距、圆角与动效

4px 网格；列表条目 8–16px；卡片/控件 6px 圆角，大卡 12–24px；区块 24–48px。动效 120–200ms，hover 以颜色变化为主；标签（Label）与状态徽章用语义 fg 色 + subtle 底色。



### UI/UX CSS Token

```css
/* GitHub — UI/UX Token（Primer 明色） */
--pr-bg-default: #ffffff;
--pr-bg-subtle: #f6f8fa;
--pr-bg-accent-subtle: #ddf4ff;
--pr-bg-danger-subtle: #ffebe9;
--pr-fg-default: #1F2328;
--pr-fg-muted: #656d76;
--pr-fg-accent: #0969DA;
--pr-fg-success: #1a7f37;
--pr-fg-attention: #9a6700;
--pr-fg-danger: #cf222e;
--pr-fg-done: #8250df;
--pr-border-default: #d0d7de;
--pr-border-muted: #d8dee4;
--pr-radius: 6px;
--pr-space: 4px;
--pr-font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
--pr-font-mono: ui-monospace, SFMono-Regular, Menlo, monospace;
/* 应用：列表高密度，状态用语义 fg+subtle 底，控件 6px 圆角，暗色自动切换 */
```

## 记忆点与应用方式

复现"GitHub 感"：①系统字体 + 14px 基准高密度列表；②6px 圆角控件与卡片；③语义状态色（绿/黄/红/紫）只用在状态与徽章，不做装饰；④代码块/终端是天然装饰元素；⑤蓝色 `#0969DA` 单点交互。

## 反混搭提示

GitHub 不给卡片三层阴影（那是 Airbnb）；不给标题配粗衬线（那是 McKinsey/Burberry）；状态色不用作大面积背景；暗色只用 #0D1117 低饱和家族。
