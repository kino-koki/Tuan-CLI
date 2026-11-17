# 61. Robinhood — 大众投资 青柠绿

> **类型**：软件 | **领域**：证券交易 App | **设计哲学**：把投资变成清爽的青绿

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / 浅灰 `#F8FAFA` |
| 强调色 | `#00C805` Robinhood青绿 |
| 字体策略 | 系统栈 + 展示几何无衬线 |
| 记忆点 | 青绿 #00C805 + 折线图即 logo |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## HTML 板块 · 官网与营销页

### 设计哲学

Robinhood 官网把"投资民主化"讲得轻盈：白/浅灰底 + 青绿 `#00C805` 主强调 + 大幅折线图与卡片；logo 就是一条上扬折线。设计语言干净、乐观、平易近人——**股票交易不再西装革履**。营销页以"零佣金 + 移动端截图 + 行情图表"为主，图表是其最重要的视觉资产。

### 色彩

画布白 `#FFFFFF`、浅灰 `#F8FAFA`；主强调青绿 `#00C805`（CTA、链接、选中）、hover `#00A805`；文字近黑 `#141414`、灰 `#6E6F6F`；涨绿 `#00C805`、跌红 `#F72833`；分割线 `#E7E8E8`。

### 字体

系统栈 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`；标题 36–64px SemiBold；正文 16–18px；行情数字 24–48px ExtraBold tabular；中文 PingFang SC / Microsoft YaHei。

### 布局、间距、圆角与动效

内容 1200px；区块 64–112px；卡片 12px 圆角、1px 描边；按钮 8px 圆角（青绿实心/黑实心）；折线图细线 2px、无填充或微渐变；动效 200–300ms；hover 上浮。

### HTML CSS Token

```css
/* Robinhood — HTML 官网 Token */
--rh-green: #00C805;
--rh-green-hover: #00A805;
--rh-green-soft: #E6F9E6;
--rh-red: #F72833;
--rh-bg: #FFFFFF;
--rh-bg-gray: #F8FAFA;
--rh-text: #141414;
--rh-text-subtle: #6E6F6F;
--rh-line: #E7E8E8;
--rh-radius-card: 12px;
--rh-radius-btn: 8px;
--rh-font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--rh-space-section: 88px;
--rh-motion: 250ms ease;
/* 应用：主 CTA 青绿实心；折线图 2px 细线做核心视觉 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

交易 App 是"极简行情"典范：顶部大余额 + 折线图 + 简易买/卖按钮；UI 白底、大数字、单个主 CTA（"买入"大按钮）。设计目标：**让首次买股票像点外卖一样简单**——所有操作 1–2 步完成，图表永远是主角，红绿只做行情。

### 色彩（组件与语义 Token）

主行动青绿 `#00C805`（买入/确认）；行情涨绿 `#00C805`、跌红 `#F72833`；中性面白/`#F8FAFA`/hover `#EAF4EA`；描边 `#E0E3E2`；文字 `#141414`/`#6E6F6F`；警告橙 `#F5A623`（保证金等）。

### 字体

余额 32–48px ExtraBold tabular；行情 16–20px SemiBold tabular；按钮 16px ExtraBold。中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

主页：顶部余额卡 → 图表 200px → 快捷操作三按钮；买入流程底部 sheet 12px 圆角（金额/确认）；Tab 栏 56px。动效：数字滚动 150ms、买入成功 300ms pop、图表刷新手势跟手。

### UI/UX CSS Token

```css
/* Robinhood — UI/UX Token（交易 App） */
--rh-ui-green: #00C805;
--rh-ui-red: #F72833;
--rh-ui-bg: #FFFFFF;
--rh-ui-bg-2: #F8FAFA;
--rh-ui-hover: #EAF4EA;
--rh-ui-line: #E0E3E2;
--rh-ui-text: #141414;
--rh-ui-text-subtle: #6E6F6F;
--rh-ui-warn: #F5A623;
--rh-balance-fs: clamp(32px, 7vw, 48px);
--rh-radius-sheet: 12px;
--rh-radius-btn: 8px;
--rh-tabbar-h: 56px;
--rh-font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--rh-motion: 200ms ease;
/* 应用：底部买入 sheet 12px 圆角；大余额 48px ExtraBold */
```

## 记忆点与应用方式

复现"Robinhood 感"三步：①白底 + 青绿 `#00C805` 单一强调；②折线图/行情是核心视觉资产；③大余额数字 + 单主 CTA 的极简操作。做"券商、投资、金融科技"类 App/官网首选（区别于 Coinbase 深蓝与 Klarna 粉）。

## 反混搭提示

Robinhood 青绿不要大面积渐变；红绿只做行情，UI 其余保持中性。避免把页面做成 Coinbase 那样深色"银行感"——Robinhood 是明亮、低门槛的消费感。
