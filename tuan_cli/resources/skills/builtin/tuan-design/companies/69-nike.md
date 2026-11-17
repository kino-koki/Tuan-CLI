# 69. Nike — 运动精神 黑白宣言

> **类型**：品牌 | **领域**：运动服饰与装备 | **设计哲学**：行动与胜利的黑白宣言

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / `#000000` 黑 |
| 强调色 | `#000000` 黑 + 荧光点缀可选 |
| 字体策略 | Nike TG / 压缩粗体（Futura Condensed 类） |
| 记忆点 | Swoosh + 黑白大字 + 运动摄影 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## 官网板块 · 数字化品牌体验

### 设计哲学

Nike 官网是全球最强烈的"品牌宣言式"电商站：黑白对比 + 巨型压缩字体（Nike TG，源自 Futura Condensed）+ 高速运动摄影；Swoosh 勾是唯一的恒常图形。设计目标是**传达力量与速度**——页面排版硬朗、图片充满动势、文字短促有力（Just Do It）。产品页保持黑白 UI，彩色完全来自产品与影像。

### 色彩

画布白 `#FFFFFF`、黑 `#000000`（hero/页脚）、灰 `#F5F5F5`；强调就是黑与白本身——CTA 黑底白字或白底黑字；可用荧光点缀（如 Volt 黄 `#D4FF00`、Pink Blast `#FF5C72`）仅做促销/限量标记；文字黑/白、灰 `#757575`。

### 字体

Nike TG（压缩粗体）/ 回退 `'Arial Narrow', 'Helvetica Neue Condensed', system-ui`；标题 40–96px ExtraBold 压缩（`font-stretch: condensed`）；正文 14–16px；价格 16px SemiBold tabular；中文思源黑体 Heavy。

### 布局、间距、圆角与动效

内容 1440px 宽屏（Nike 偏爱全宽）；区块 48–120px；产品卡 0–2px 圆角（**趋直角**）、hover 图缩放 1.03；按钮直角或 2px 圆角；hero 全屏运动摄影（黑底 logo 大字）；动效 200–300ms、滚动可带动势视差。

### HTML CSS Token

```css
/* Nike — HTML 官网 Token */
--nk-black: #000000;
--nk-white: #FFFFFF;
--nk-gray: #F5F5F5;
--nk-text-subtle: #757575;
--nk-volt: #D4FF00;
--nk-pink-blast: #FF5C72;
--nk-radius-card: 2px;
--nk-radius-btn: 2px;
--nk-font-display: 'Nike TG', 'Arial Narrow', 'Helvetica Neue Condensed', 'PingFang SC', 'Microsoft YaHei', sans-serif;
--nk-font-body: system-ui, -apple-system, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--nk-space-section: 88px;
--nk-container: 1440px;
--nk-motion: 250ms ease;
/* 应用：黑底白字压缩粗体 hero；产品 hover 图缩放 1.03；荧光色只做限量角标 */
```

## 记忆点与应用方式

复现"Nike 感"三步：①黑白 + 压缩粗体（Nike TG）+ Swoosh；②全宽运动摄影、文字短促；③产品卡近直角、hover 缩放。做"运动、竞技、街头文化"类官网首选；荧光色（Volt/Pink Blast）只做限量与促销信号。

## 反混搭提示

Nike 黑是"宣言黑"——不要加渐变、玻璃拟态；荧光色禁止大面积铺底（只做限量/促销标记）；避免把品牌做得柔和童趣（那是 Adidas Originals 或 New Balance 之外的领域，Nike 是锋利进攻的）。
