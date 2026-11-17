# 59. Coinbase — 加密货币 信赖蓝

> **类型**：软件 | **领域**：加密货币交易所 | **设计哲学**：让加密世界可信可懂

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / 深蓝黑 `#0B1426` |
| 强调色 | `#0052FF` Coinbase蓝 |
| 字体策略 | 系统栈（Coinbase Sans 类几何无衬线） |
| 记忆点 | 纯蓝 #0052FF + 深蓝黑画布 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## HTML 板块 · 官网与营销页

### 设计哲学

Coinbase 官网把"加密"讲得极保守可信：白/深蓝黑画布、主蓝 `#0052FF`、几何无衬线、价格图表实时展示；整体像一家"硅谷银行"而非投机交易所。设计语言强调**监管感、安全感、简单化**——圆角克制、字体干净、图表权威。营销页以产品图表 + 简洁文案为主。

### 色彩

画布白 `#FFFFFF`、深蓝黑 `#0B1426`（暗段）、浅灰 `#F5F7FA`；主强调蓝 `#0052FF`（CTA、链接、选中）、hover `#0041CC`；文字 `#0E1525`、灰 `#5B6470`；成功绿 `#0D9B5E`（行情涨）、危险红 `#DF1D4E`（跌）；分割线 `#E4E7EB`。

### 字体

Coinbase Sans（几何无衬线）或系统栈 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`；标题 36–64px SemiBold；正文 16–18px；价格数字 ExtraBold tabular；中文 PingFang SC / Microsoft YaHei。

### 布局、间距、圆角与动效

内容 1200px；区块 80–128px（暗段全屏）；卡片 8–12px 圆角、1px 描边；按钮 8px 圆角（蓝实心）；价格图表无圆角、细线；动效 200–300ms；hover 上浮 2px。

### HTML CSS Token

```css
/* Coinbase — HTML 官网 Token */
--cb-blue: #0052FF;
--cb-blue-hover: #0041CC;
--cb-blue-soft: #E8EFFF;
--cb-bg: #FFFFFF;
--cb-bg-dark: #0B1426;
--cb-bg-gray: #F5F7FA;
--cb-text: #0E1525;
--cb-text-subtle: #5B6470;
--cb-up: #0D9B5E;
--cb-down: #DF1D4E;
--cb-line: #E4E7EB;
--cb-radius-card: 10px;
--cb-radius-btn: 8px;
--cb-font: 'Coinbase Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--cb-space-section: 96px;
--cb-motion: 250ms ease;
/* 应用：主 CTA 蓝实心；暗段深蓝黑底 + 白字 + 价格图表 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

交易 App 的 UI 以"资产列表 + 行情走势"为核心：白底大列表、蓝色主行动（交易/买入）、红绿涨跌一眼可读；图表区无边框、细网格线。整体目标是**让新手觉得安全**：层级简单、术语减少、数字大而清晰——"银行 App 的信任感 × 加密的速度感"。

### 色彩（组件与语义 Token）

主蓝 `#0052FF` = 主行动/选卡；涨绿 `#0D9B5E`、跌红 `#DF1D4E`（行情专用）；中性面白/`#F5F7FA`/hover `#EDF2FA`；描边 `#D9DEE5`；文字 `#0E1525`/`#5B6470`；资产图标彩色但系统 UI 中性。

### 字体

资产名 16px Medium；余额 28–40px ExtraBold tabular；涨跌 14px SemiBold；图表 label 12px。中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

底部 Tab 栏 56px（首页/交易/卡片/设置）；资产卡 10px 圆角、16px padding；图表高 180–240px；买/卖大按钮 48px 圆角 8px。动效：行情刷新数字滚动 150ms、买入确认 250ms、卡片横滑 300ms。

### UI/UX CSS Token

```css
/* Coinbase — UI/UX Token（交易 App） */
--cb-ui-blue: #0052FF;
--cb-ui-bg: #FFFFFF;
--cb-ui-bg-2: #F5F7FA;
--cb-ui-hover: #EDF2FA;
--cb-ui-line: #D9DEE5;
--cb-ui-text: #0E1525;
--cb-ui-text-subtle: #5B6470;
--cb-ui-up: #0D9B5E;
--cb-ui-down: #DF1D4E;
--cb-balance-fs: clamp(28px, 6vw, 40px);
--cb-radius-card: 10px;
--cb-radius-btn: 8px;
--cb-tabbar-h: 56px;
--cb-font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--cb-motion: 200ms ease;
/* 应用：余额数字超大 tabular；红绿只做行情语义 */
```

## 记忆点与应用方式

复现"Coinbase 感"三步：①蓝 `#0052FF` + 白/深蓝黑双画布；②价格数字超大加粗 tabular，红绿只做涨跌；③卡片 1px 描边 10px 圆角、几何无衬线。做"金融科技、交易所、Web3"类官网默认参考。

## 反混搭提示

注意与 Robinhood、EToro 区分：Coinbase 蓝是"银行蓝"不是"霓虹青"——禁止渐变、禁止荧光；不要用比特币橙做大面积品牌色（那是其他交易所的定位）。
