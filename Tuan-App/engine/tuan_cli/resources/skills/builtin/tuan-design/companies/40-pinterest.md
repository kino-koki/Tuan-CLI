# 40. Pinterest — 灵感瀑布流 大红

> **类型**：软件 | **领域**：视觉搜索社区 | **设计哲学**：发现美的轻快屏风

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 |
| 强调色 | `#E60023` Pinterest红 |
| 字体策略 | 系统字体栈 |
| 记忆点 | 瀑布流卡片 + 大红圆角按钮 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## HTML 板块 · 官网与营销页

### 设计哲学

Pinterest 官网的核心是"让内容说话"：hero 直接展示瀑布流灵感卡片，品牌红只出现在 logo 与关键 CTA。设计语言轻盈、圆润、亲切，像在整理自己的灵感板——大留白 + 圆角卡片 + 克制单一强调色。营销页以"案例故事 + 大图"推进，从不堆砌文字。

### 色彩

画布白 `#FFFFFF`，深灰文字 `#211922`（Pinterest 专用深灰）、辅助灰 `#5F5F5F`；品牌红 `#E60023` 用于 logo、主 CTA、hover 红 `#AD081B`；浅灰填充 `#EFEFEF` 用于卡片占位。全局除了红以外禁止第二种强调色。

### 字体

系统字体栈 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`；标题 24–44px Bold，正文 16px；中文回落 PingFang SC / Microsoft YaHei。无衬线、无装饰性展示字——加粗与大小就是层级。

### 布局、间距、圆角与动效

营销页 hero 常是"居中标题 + 横向瀑布流缩略图背景"；内容区栅格 4 列瀑布流（列宽 236px）；卡片 16px 圆角、图片 1:1 或 2:3；按钮胶囊 9999px（高 40–48px）；悬停 200ms 上浮 4px + 阴影；区块间距 64–96px。

### HTML CSS Token

```css
/* Pinterest — HTML 官网 Token */
--pin-red: #E60023;
--pin-red-hover: #AD081B;
--pin-red-soft: #FFE0E4;
--pin-bg: #FFFFFF;
--pin-bg-gray: #EFEFEF;
--pin-text: #211922;
--pin-text-subtle: #5F5F5F;
--pin-radius-card: 16px;
--pin-radius-pill: 9999px;
--pin-font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, "PingFang SC", "Microsoft YaHei", sans-serif;
--pin-space-section: 72px;
--pin-motion: 200ms ease;
--pin-shadow-card: 0 2px 8px rgba(0, 0, 0, 0.08);
/* 应用：主 CTA 红色胶囊按钮，卡片底灰占位 + 圆角，hover 上浮加阴影 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品界面的"灵感流"模型：等宽瀑布流让图片自然呼吸，用户只做两个动作——逛与钉。视觉层级极低对比：灰底、小字号说明、大图优先；交互反馈柔和（红色只在 hover 与已保存状态出现），意图是"不吓走灵感"。

### 色彩（组件与语义 Token）

行动红 `#E60023`：主按钮、已保存态、hover 图标；中性层级：白面 → `#EFEFEF` 面 → `#E9E9E9` 描边 `#CDCDCD`；文本 `#211922` 主 / `#5F5F5F` 次 / `#8E8E8E` 弱；遮罩 `rgba(0,0,0,0.6)`。

### 字体

界面 14–16px；卡片说明 14px；标题 20px SemiBold；数字与计数用 tabular。多语言 UI 全程系统栈，中文 14–15px。

### 布局、间距、圆角与动效

瀑布流列宽 236px 起、卡片 margin 8px；卡片内 padding 0（图片全出血）→ 说明区 12px；圆角 16px；头像 32px 圆形；底部工具条 hover 250ms 弹出。动效以 150–250ms 淡入淡出 + 轻上浮为主，禁止弹跳动画。

### UI/UX CSS Token

```css
/* Pinterest — UI/UX Token（产品界面） */
--pin-ui-bg: #FFFFFF;
--pin-ui-surface: #FFFFFF;
--pin-ui-surface-gray: #EFEFEF;
--pin-ui-hover: #E9E9E9;
--pin-ui-line: #CDCDCD;
--pin-ui-text: #211922;
--pin-ui-text-subtle: #5F5F5F;
--pin-ui-accent: #E60023;
--pin-ui-saved: #E60023;
--pin-radius-card: 16px;
--pin-radius-pill: 9999px;
--pin-col: 236px;
--pin-font-ui: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
--pin-motion: 200ms ease;
/* 应用：瀑布流无边框卡片、图片出血；hover 才露红色已保存心形 */
```

## 记忆点与应用方式

复现"Pinterest 感"三步：①白底 + 灰卡片占位 + 16px 圆角；②全站唯一强调色大红 `#E60023`（主 CTA 胶囊）；③内容区用瀑布流而非网格（等宽列、图片不同高）。要表达"灵感收藏"气质就用大图 + 轻量文字。

## 反混搭提示

不要让红 `#E60023` 溢出到背景或大面积填充——红色在 Pinterest 里是"行动/收藏"的记号，不是装饰。不要用多色渐变瀑布流、不要给卡片加厚重阴影（Pinterest 卡片是平面 8% 阴影以内）。
