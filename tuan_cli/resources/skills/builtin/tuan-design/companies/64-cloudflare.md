# 64. Cloudflare — 网络基础设施 协议橙

> **类型**：软件 | **领域**：云网络与安全 | **设计哲学**：开放协议的工程诚实

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / 深墨 `#121212` |
| 强调色 | `#F38020` Cloudflare橙 |
| 字体策略 | 系统栈 + 几何展示字 |
| 记忆点 | 工程橙 + 网络节点 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## HTML 板块 · 官网与营销页

### 设计哲学

Cloudflare 官网把"互联网基础设施"讲得工程师友好：白/墨双画布 + 官方橙 `#F38020` 主强调 + 大量网络拓扑/节点图；设计语言**直接、开放、略粗粝**——像开源项目主页而不是广告。营销页以性能数字、开发者文档、网络架构图为主，字体稳健、卡片规整，传达"我们跑在公理上"。

### 色彩

画布白 `#FFFFFF`、深墨 `#121212`（暗段）、浅灰 `#F5F5F5`；主强调橙 `#F38020`（CTA、链接、高亮数字）、hover `#D96A13`；文字 `#1A1A1A`/白、灰 `#5F5F5F`；成功绿 `#00A3A3`（青绿）、警示黄 `#FFC400`；分割线 `#E5E5E5`。

### 字体

系统栈 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`；标题 36–64px SemiBold；正文 15–18px；代码/命令块 `ui-monospace`；数字 tabular；中文 PingFang SC / Microsoft YaHei。

### 布局、间距、圆角与动效

内容 1200px；区块 72–112px；卡片 8–12px 圆角、1px 描边、hover 上浮；按钮 8px（橙实心/黑实心）；hero 常为暗色 + 网络节点动画；动效 200–300ms；hover 行高亮。

### HTML CSS Token

```css
/* Cloudflare — HTML 官网 Token */
--cf-orange: #F38020;
--cf-orange-hover: #D96A13;
--cf-orange-soft: #FEF0E4;
--cf-teal: #00A3A3;
--cf-bg: #FFFFFF;
--cf-bg-dark: #121212;
--cf-bg-gray: #F5F5F5;
--cf-text: #1A1A1A;
--cf-text-subtle: #5F5F5F;
--cf-line: #E5E5E5;
--cf-radius-card: 10px;
--cf-radius-btn: 8px;
--cf-font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--cf-font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
--cf-space-section: 88px;
--cf-motion: 250ms ease;
/* 应用：主 CTA 橙实心；hero 暗色 + 节点/网络纹理；代码块等宽 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品界面（控制台、Analytics、Zero Trust）是深色开发者工作台：左侧导航 + 指标图 + 配置项；橙色只做品牌标识与行动，图表多色按语义。设计目标是**让网络状态透明可查**——请求、延迟、威胁都变成实时图表，UI 冷静专业。

### 色彩（组件与语义 Token）

橙 `#F38020` = logo/主行动/通知重点；中性深色面板 `#1C1C1C`、hover `#2A2A2A`；描边 `#3A3A3A`；文字白/灰 `#A0A0A0`；图表语义：攻击红 `#E84B4B`、正常青 `#00C1D4`、警告黄 `#FFC400`、成功绿 `#2EB67D`。

### 字体

UI 13–15px；指标大数字 24–36px SemiBold tabular；日志/代码 13px 等宽。中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

左导航 220px；指标卡 8px 圆角、深底；图表区无边框、网格线 1px `#2A2A2A`；状态徽章 4px 圆角。动效：实时图表 300ms 平滑、威胁告警 400ms 闪动、配置保存 toast 250ms。

### UI/UX CSS Token

```css
/* Cloudflare — UI/UX Token（控制台） */
--cf-ui-bg: #121212;
--cf-ui-panel: #1C1C1C;
--cf-ui-hover: #2A2A2A;
--cf-ui-line: #3A3A3A;
--cf-ui-text: #FFFFFF;
--cf-ui-text-subtle: #A0A0A0;
--cf-ui-orange: #F38020;
--cf-ui-green: #2EB67D;
--cf-ui-red: #E84B4B;
--cf-ui-warn: #FFC400;
--cf-ui-cyan: #00C1D4;
--cf-sidebar: 220px;
--cf-radius-card: 8px;
--cf-font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--cf-font-mono-ui: ui-monospace, SFMono-Regular, Menlo, monospace;
--cf-motion: 250ms ease;
/* 应用：图表网格线 1px #2A2A2A；威胁告警红色徽章 */
```

## 记忆点与应用方式

复现"Cloudflare 感"三步：①白/墨双画布 + 橙 `#F38020` 唯一品牌色；②网络拓扑与实时数据图表为核心视觉；③卡片 1px 描边、细节硬朗。做"云计算、安全、网络基础设施"类官网首选。

## 反混搭提示

Cloudflare 橙是"工程橙"——不要做成渐变支付宝橙，不要大面积铺底；深色段必须 `#121212` 系纯墨（不偏蓝）。避免把卡片做圆润到消费级（10px 内）、避免加插画吉祥物。
