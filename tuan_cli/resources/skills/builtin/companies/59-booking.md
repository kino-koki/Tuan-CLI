# 59. Booking.com — 出行预订 深蓝信任

> **类型**：软件 | **领域**：在线旅行平台 | **设计哲学**：全球感与信任感的深蓝

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / 浅灰 `#F5F5F5` |
| 强调色 | `#0071C2` Booking蓝 |
| 字体策略 | 系统栈 + 数字展示 |
| 记忆点 | 深蓝 CTA + 列表卡片 + 评分徽章 |

## HTML 板块 · 官网与营销页

### 设计哲学

Booking.com 官网把"全球房源"讲成极度信息化的购物页：白底、深蓝 CTA、房源卡片流、价格/评分/徽章密密麻麻——但层级清晰。设计语言是**"大卖场的秩序感"**：用蓝色统一所有行动、用星级/评分/取消政策徽章建立信任、用大图吸引点击。营销页同样保持功能优先：搜索框即 hero。

### 色彩

画布白 `#FFFFFF`、浅灰 `#F5F5F5`、页脚深蓝 `#003580`；主强调蓝 `#0071C2`（搜索、预订、链接）、hover `#005D9E`；文字 `#1A1A1A`、灰 `#5A5A5A`；评分绿 `#008009`（好评）、黄 `#FFB700`（星级）；分割线 `#E6E6E6`。

### 字体

系统栈 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`；标题 24–48px SemiBold；正文 14–16px；价格与评分用 SemiBold tabular；中文 PingFang SC / Microsoft YaHei。

### 布局、间距、圆角与动效

内容 1200px；房源卡 8–12px 圆角、1px 描边、hover 上浮 + 阴影；图片 4:3；主 CTA 深蓝实心 6px 圆角；评分徽章圆角 4px；区块 48–80px；动效 200ms。

### HTML CSS Token

```css
/* Booking.com — HTML 官网 Token */
--bk-blue: #0071C2;
--bk-blue-hover: #005D9E;
--bk-blue-dark: #003580;
--bk-bg: #FFFFFF;
--bk-bg-gray: #F5F5F5;
--bk-text: #1A1A1A;
--bk-text-subtle: #5A5A5A;
--bk-good: #008009;
--bk-star: #FFB700;
--bk-line: #E6E6E6;
--bk-radius-card: 10px;
--bk-radius-btn: 6px;
--bk-font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--bk-space-section: 64px;
--bk-motion: 200ms ease;
/* 应用：预订/搜索按钮 6px 圆角深蓝；房源卡 1px 描边 + hover 阴影 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品界面（房源详情/预订流程）延续"效率优先"：多列信息（照片、设施、评分、价格）+ 右侧常驻预订卡；蓝 `#0071C2` 统一所有确认行动，深蓝 `#003580` 做导航底。设计目标：**让"比价 + 下单"在一屏内完成**，因此信息密度高但分隔线整齐。

### 色彩（组件与语义 Token）

主蓝 `#0071C2` = 预订/选择/链接；深蓝 `#003580` = 顶部导航/页脚/徽章底；评分绿 `#008009`、警告橙 `#E87722`、中性面白/`#F5F5F5`/hover `#EDF4FA`；描边 `#D6D6D6`；文字 `#1A1A1A`/`#5A5A5A`。

### 字体

UI 13–16px；房型标题 16–18px SemiBold；价格 20–24px ExtraBold tabular；设施标签 13px。中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

房源详情：左图文 9 列 + 右预订卡 3 列 sticky；预订卡 8px 圆角 + 描边；步骤条（1 选择 2 填写 3 确认）40px 高；输入框 6px 圆角。动效：日期选择 150ms、价格变化 200ms、预订成功 300ms。

### UI/UX CSS Token

```css
/* Booking.com — UI/UX Token（预订流程） */
--bk-ui-blue: #0071C2;
--bk-ui-blue-dark: #003580;
--bk-ui-bg: #FFFFFF;
--bk-ui-bg-2: #F5F5F5;
--bk-ui-hover: #EDF4FA;
--bk-ui-line: #D6D6D6;
--bk-ui-text: #1A1A1A;
--bk-ui-text-subtle: #5A5A5A;
--bk-ui-good: #008009;
--bk-ui-warn: #E87722;
--bk-radius-card: 8px;
--bk-radius-btn: 6px;
--bk-rail-w: 320px;
--bk-font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--bk-motion: 200ms ease;
/* 应用：右侧预订卡 sticky 8px 圆角；确认按钮始终深蓝 */
```

## 记忆点与应用方式

复现"Booking 感"三步：①白底 + 深蓝 `#0071C2` 行动 + 房源卡 1px 描边；②评分用绿色数字 + 黄星，徽章化处理；③信息密度高但分隔线整齐（大卖场秩序）。做"OTA、电商列表、比价"类页面首选。

## 反混搭提示

Booking 不需要"设计感"——不要加入大量留白、不要做艺术化 hero、不要渐变；蓝色必须保持商务感的 `#0071C2` 系，不能发紫或发青。卡片避免大圆角（10px 内）。
