# 60. Klarna — 支付体验 芭比粉轰炸

> **类型**：软件 | **领域**：金融支付 SaaS | **设计哲学**：把无聊支付变得有趣

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFB3C7` Klarna粉 / 黑 `#000000` |
| 强调色 | `#FFB3C7` Klarna粉 + 黑 |
| 字体策略 | 压缩粗黑展示字（Knockout 类）+ 系统栈 |
| 记忆点 | 全屏芭比粉 + 超大粗黑字 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## HTML 板块 · 官网与营销页

### 设计哲学

Klarna 是"品牌越界"的教科书：整个官网可以是大面积芭比粉 `#FFB3C7`、超大压缩黑体字、倾斜构图、粗黑描边——丑得高级，辨识度极高。设计目标：**让金融支付充满个性与幽默**。营销页用巨型文字 + 产品卡片 + 波普排版，任何常规 "金融蓝" 都不存在。

### 色彩

画布粉 `#FFB3C7`（Klarna 招牌粉）可作整段背景，黑 `#000000` 做文字/图形，白 `#FFFFFF` 做内容卡；辅助可用粉调、紫调少量点缀；强调通常就是"粉底黑字"或"白底黑字+粉按钮"；文字黑或白——对比直给，不用灰阶渐变。

### 字体

展示用压缩粗黑体（接近 Knockout/compact 风格）：`font-stretch: condensed` + 700–900 weight；标题 48–128px 全大写或奇怪断行；正文用系统栈 16–18px；中文同样用粗黑（思源黑体 Heavy）。

### 布局、间距、圆角与动效

区块可以不对称、倾斜（rotate -2deg）或超大圆（`border-radius: 999px` 装饰环）；卡片 16–24px 圆角;按钮全黑或全粉、圆角 8–12px；动效活泼：200–400ms 带弹跳、hover 大位移；排版允许字被裁切、断续、错位。

### HTML CSS Token

```css
/* Klarna — HTML 官网 Token */
--kl-pink: #FFB3C7;
--kl-pink-deep: #FF7C9E;
--kl-black: #000000;
--kl-white: #FFFFFF;
--kl-text: #000000;
--kl-radius-card: 20px;
--kl-radius-btn: 10px;
--kl-font-display: 'Knockout', 'Arial Narrow', 'Helvetica Neue Condensed', 'PingFang SC', 'Microsoft YaHei', sans-serif;
--kl-font-body: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--kl-space-section: 112px;
--kl-motion: 300ms cubic-bezier(0.2, 1.4, 0.4, 1);
/* 应用：粉底黑字超大粗体；卡片 20px 圆角；允许不对称/倾斜构图 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品界面（支付/购物 App）比官网"收敛"但仍带品牌个性：粉 `#FFB3C7` 用在标志、按钮与促销卡；主交易流程保持白底高可读。设计目标：**结账不再冷冰冰**——进度条粉色、成功动画俏皮、卡片圆润。店员式亲切感 × 大平台可靠性。

### 色彩（组件与语义 Token）

粉 `#FFB3C7` = 品牌/促销/主要视觉；主行动黑 `#000000`（立即支付）或白描边；中性面白/浅灰 `#F7F7F7`/hover `#FCEEF2`；描边 `#E5E5E5`；文字 `#1A1A1A`/`#6E6E6E`；成功绿 `#00B36B`（拆分成功）；危险红 `#D0021B`。

### 字体

UI 14–16px；按钮 16px ExtraBold；金额 24–32px ExtraBold tabular；促销标题可继续用压缩粗体。中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

结账单列 480px 居中；步骤条 4px 粉线；商品卡 12px 圆角；支付方式大按钮 12px 圆角（带 logo）；成功动画 400ms pop + 彩带。动效轻而有趣，但输入与确认反馈必须即时。

### UI/UX CSS Token

```css
/* Klarna — UI/UX Token（支付流程） */
--kl-ui-pink: #FFB3C7;
--kl-ui-pink-soft: #FCEEF2;
--kl-ui-black: #000000;
--kl-ui-bg: #FFFFFF;
--kl-ui-line: #E5E5E5;
--kl-ui-text: #1A1A1A;
--kl-ui-text-subtle: #6E6E6E;
--kl-ui-success: #00B36B;
--kl-ui-danger: #D0021B;
--kl-checkout-w: 480px;
--kl-radius-card: 12px;
--kl-radius-btn: 12px;
--kl-font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--kl-motion: 250ms cubic-bezier(0.2, 1.2, 0.4, 1);
/* 应用：结账步骤条粉色 4px；支付按钮黑底白字或白底粉边 */
```

## 记忆点与应用方式

复现"Klarna 感"三步：①大面积芭比粉 `#FFB3C7` 背景 + 压缩粗黑超大字；②黑/粉双色对比，允许不对称与倾斜排版；③交易类页面白底但粉色点缀保品牌。做"支付、金融、年轻消费品牌"页面时最出挑。

## 反混搭提示

Klarna 粉是"宣言色"不是"少女色"——粉底必须配粗黑大字才会高级；避免柔滑渐变与渐变阴影；不要在金融流程里过度加装饰，流程页要回到清晰与可信（粉色做点缀）。
