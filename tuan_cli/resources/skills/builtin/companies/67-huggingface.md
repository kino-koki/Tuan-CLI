# 67. Hugging Face — 开源AI模型 香蕉黄

> **类型**：软件 | **领域**：AI 模型平台（开源社区） | **设计哲学**：让 AI 平权、开放、可玩

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / 深墨 `#141414` |
| 强调色 | `#FFD21E` 香蕉黄 |
| 字体策略 | 系统栈 + 圆润粗展示 |
| 记忆点 | 香蕉黄 + 笑脸 logo + 模型卡 |

## HTML 板块 · 官网与营销页

### 设计哲学

Hugging Face 官网把"AI 模型"做成社区超市：香蕉黄 `#FFD21E` 品牌色 + 圆角模型卡 + 友善语气（logo 是 hugging face）；设计语言**开放、明亮、略带玩心**，但产品信息（模型数、下载量、榜单）排布严谨。营销页以"模型卡墙 + 社区数据"为主，黄色做 logo、CTA 与高亮数字。

### 色彩

画布白 `#FFFFFF`、深墨 `#141414`（dark 段）、浅灰 `#F3F4F6`；主强调黄 `#FFD21E`（logo、CTA、高亮）、hover `#E5B800`；文字 `#1A1A1A`/白、灰 `#5F6B76`；模型徽章多色（框架标识）但 UI 中性；分割线 `#E5E7EB`。

### 字体

系统栈 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`；标题 36–64px SemiBold；模型标题 16px Medium；代码块等宽；中文 PingFang SC / Microsoft YaHei。

### 布局、间距、圆角与动效

内容 1200px；区块 64–112px；模型卡 12px 圆角、1px 描边、hover 上浮 + 阴影；按钮 8px（黄底黑字/黑底白字）；hero 墨底 + 黄色大字 + 笑脸图形；动效 200ms。

### HTML CSS Token

```css
/* Hugging Face — HTML 官网 Token */
--hf-yellow: #FFD21E;
--hf-yellow-hover: #E5B800;
--hf-yellow-soft: #FFF7D6;
--hf-bg: #FFFFFF;
--hf-bg-dark: #141414;
--hf-bg-gray: #F3F4F6;
--hf-text: #1A1A1A;
--hf-text-subtle: #5F6B76;
--hf-line: #E5E7EB;
--hf-radius-card: 12px;
--hf-radius-btn: 8px;
--hf-font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--hf-font-mono: ui-monospace, SFMono-Regular, Menlo, monospace;
--hf-space-section: 88px;
--hf-motion: 220ms ease;
/* 应用：主 CTA 黄底黑字；模型卡 12px 圆角 + 1px 描边；hero 墨底黄字 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品界面（模型 Hub、Spaces、数据集）是"社区 + 平台"混合体：搜索栏超大、模型卡列表、右侧配置；黄 `#FFD21E` 只做 logo、主行动与选中徽章，模型卡用框架多彩 logo 打字。设计目标是**让发现模型像逛商店**——卡片化、可筛选、数字即信任。

### 色彩（组件与语义 Token）

黄 `#FFD21E` = 品牌/主行动/选中；中性面白/`#F3F4F6`/hover `#F9FAFB`；描边 `#E2E5E9`；文字 `#1A1A1A`/`#5F6B76`；框架徽章色（PyTorch 橙、TF 橙、JAX 蓝）按库标识；运行状态绿 `#239D45`、报错红 `#D43D2A`。

### 字体

UI 13–15px；模型名 15px Medium；下载量/星级 SemiBold tabular；代码 13px 等宽。中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

顶部大搜索（48px 高、胶囊）；筛选行 sticky；模型卡 3–4 列、gap 16px；详情页左模型信息右推理 widget。动效：筛选 200ms、卡片 hover 上浮、推理运行 300ms 进度环。

### UI/UX CSS Token

```css
/* Hugging Face — UI/UX Token（Model Hub） */
--hf-ui-yellow: #FFD21E;
--hf-ui-bg: #FFFFFF;
--hf-ui-bg-2: #F3F4F6;
--hf-ui-hover: #F9FAFB;
--hf-ui-line: #E2E5E9;
--hf-ui-text: #1A1A1A;
--hf-ui-text-subtle: #5F6B76;
--hf-ui-success: #239D45;
--hf-ui-danger: #D43D2A;
--hf-radius-card: 12px;
--hf-radius-search: 9999px;
--hf-font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--hf-font-mono-ui: ui-monospace, SFMono-Regular, Menlo, monospace;
--hf-motion: 220ms ease;
/* 应用：搜索框胶囊 48px；模型框架用库官方多彩 logo 但不染 UI */
```

## 记忆点与应用方式

复现"Hugging Face 感"三步：①香蕉黄 `#FFD21E` + 白/墨双画布；②模型卡 12px 圆角 1px 描边、数字即信任（下载量/评分）；③语气友善（笑脸/文案俏皮）但信息排布严谨。做"AI 开源、模型社区、开发者平台"类官网首选。

## 反混搭提示

香蕉黄是大面积警戒色——不要满屏黄底，黄底必须配黑字且有"品牌资产"身份（logo/CTA/高亮）。避免把 AI 产品做得阴沉（HF 是明亮开放的社区感），但业务页面也要保留工程师秩序。
