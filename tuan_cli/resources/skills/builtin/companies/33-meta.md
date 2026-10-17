# 33. Meta — 一家公司一个蓝

> **类型**：软件 | **领域**：社交平台 | **设计哲学**：Connection, Simplicity, Trust

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` |
| 强调色 | `#0866FF` Meta蓝 |
| 字体策略 | 系统字体栈 |
| 记忆点 | 品牌色即通用交互蓝 |

## HTML 板块 · 官网与营销页

### 设计哲学

Meta 官网（about.meta.com、meta.com）的核心是"品牌色即通用蓝"——用同一个蓝色贯穿 Meta 全家桶与网页：纯白画布 + 蓝黑双色极简排版，hero 常见蓝色渐变光晕与产品拼接图，footer 深蓝黑。语言强调连接与信任，拒绝花哨装饰。

### 色彩

Meta 品牌蓝 `#0081FB`、Facebook 产品蓝 `#0866FF`、深蓝黑 `#1C1E21`；白 `#FFFFFF`；浅灰分隔 `#F0F2F5`；blue 渐变 `#0668E1 → #0081FB`。**全站只出现一个蓝色家族**。

### 字体

系统字体栈（`-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto`）；大标题 SemiBold，正文 Regular 15–17px。

### 布局、间距、圆角与动效

8px 栅格；hero 100–128px；卡片圆角 12–16px、按钮胶囊 9999；动效 150–250ms ease-out，hover 轻。



### HTML CSS Token

```css
/* Meta — HTML 官网 Token */
--meta-blue: #0081FB;
--meta-blue-deep: #0668E1;
--meta-facebook-blue: #0866FF;
--meta-bg: #FFFFFF;
--meta-ink: #1C1E21;
--meta-gray: #F0F2F5;
--gradient-blue: linear-gradient(135deg, #0668E1, #0081FB);
--font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
--radius-card: 16px;
--radius-pill: 9999px;
--space-section: 96px;
--motion: 200ms ease-out;
/* 应用：白底黑字，单一蓝做 CTA/链接，hero 用蓝渐变光晕 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品界面（Facebook、Instagram、Messenger Web）"橱窗化"：白色表面 + 灰色分隔 + 大圆角 + 单一蓝色 CTA；内容（图片与视频）是全部色彩来源。设计目标是低打扰、高可读、内容优先——UI chrome 永远是中性灰，品牌蓝只出现需要行动的地方。

### 色彩（组件与语义 Token）

页面/卡片底 `#FFFFFF`，画布分隔 `#F0F2F5`；文字 primary `#050505`、secondary `#65676B`；accent `#0866FF`、hover `#1877F2`；success `#31A24C`；error `#E41E3F`；边框 `#CED0D4`。暗色模式页面 `#000000`、卡片 `#242526`。

### 字体

系统字体栈；正文 15–17px，标题 17–24px SemiBold；数字用等宽（计量展示可选）。

### 布局、间距、圆角与动效

8px 栅格；feed 卡片内边距 16–24px；头像圆形；卡片圆角 8–16px、输入框 24px 全圆（故事环渐变描边 `#F58529→#DD2A7B→#8134AF→#515BD4`）。动效 100–200ms，hover 阴影轻微。



### UI/UX CSS Token

```css
/* Meta — UI/UX Token（Facebook/Instagram 组件） */
--meta-surface: #FFFFFF;
--meta-canvas: #F0F2F5;
--meta-text: #050505;
--meta-text-secondary: #65676B;
--meta-accent: #0866FF;
--meta-accent-hover: #1877F2;
--meta-success: #31A24C;
--meta-error: #E41E3F;
--meta-border: #CED0D4;
--meta-radius-sm: 6px;
--meta-radius-card: 12px;
--meta-radius-input: 24px;
--meta-radius-avatar: 50%;
--meta-space: 8px;
--meta-font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
--story-gradient: linear-gradient(45deg, #F58529, #DD2A7B, #8134AF, #515BD4);
--motion: 200ms ease-out;
/* 应用：白底内容，灰 #F0F2F5 做分区，CTA 蓝 #0866FF，错误红 #E41E3F */
```

## 记忆点与应用方式

复现"Meta 感"：①白卡片 + 灰分隔 + 大圆角的低打扰界面；②唯一蓝 `#0866FF` 驱动全部 CTA；③头像圆形、输入 24px 圆角；④故事环/品牌时刻用橙粉紫径向渐变，但只做描边不做背景。

## 反混搭提示

Meta 蓝是"唯一蓝"——再加紫色/青绿品牌色即流失（Klarna/Discord 领域）。勿做霓虹暗色（TikTok/Discord 领域）；卡片圆角保持在 16px 内，勿上 Airbnb 的三层阴影大圆角。
