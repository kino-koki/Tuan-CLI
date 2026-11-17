# 49. Behance — 创意平台 工程蓝

> **类型**：软件 | **领域**：设计作品平台 | **设计哲学**：专业作品集的公立美术馆

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / 浅灰 `#F3F4F6` |
| 强调色 | `#1769FF` Behance蓝 |
| 字体策略 | 系统栈 + 数字展示 |
| 记忆点 | 蓝 #1769FF + 白底网格 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## HTML 板块 · 官网与营销页

### 设计哲学

Behance（Adobe 旗下）官网的气质介于"专业画廊"与"Adobe 工具生态"之间：白底、蓝 `#1769FF` 强调、干净的网格作品墙；信息层级靠字重与间距而非装饰。营销页用**作品大图 + 蓝色主行动**推进，传达"把你的创意放进专业陈列馆"。

### 色彩

画布白 `#FFFFFF`、灰段 `#F3F4F6`（卡片/页脚底）；主强调蓝 `#1769FF`（CTA、链接、选中）、hover `#0B4FCC`；文字 `#1A1A1A`、辅助灰 `#666666`、`#9C9C9C`；分割线 `#E0E0E0`。

### 字体

系统栈 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`；标题 26–48px SemiBold；正文 14–16px；展示数字（作品数、关注）用 SemiBold + tabular；中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

内容宽 1280px；网格 4–5 列作品卡、gap 20px；卡片圆角 8px；hover 图放大 1.02 + 阴影；按钮 4–6px 圆角（蓝实心/白描边）；区块 64–96px；动效 200ms，克制。

### HTML CSS Token

```css
/* Behance — HTML 官网 Token */
--bh-blue: #1769FF;
--bh-blue-hover: #0B4FCC;
--bh-blue-soft: #EAF1FF;
--bh-bg: #FFFFFF;
--bh-bg-gray: #F3F4F6;
--bh-text: #1A1A1A;
--bh-text-subtle: #666666;
--bh-line: #E0E0E0;
--bh-radius-card: 8px;
--bh-radius-btn: 6px;
--bh-font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--bh-space-section: 72px;
--bh-motion: 200ms ease;
/* 应用：主 CTA 蓝 `#1769FF` 实心；白底 4 列网格作品墙 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品是典型的"画廊 + 档案"结构：项目详情页是核心（大图、说明、评论、点赞），feed 与搜索保持克制的蓝白灰。导航极简（顶部栏 + 筛选）；任何装饰都不该盖过作品——这也正是 Behance 与 Dribbble 的区别：更"档案化"、更安静、更可信。

### 色彩（组件与语义 Token）

蓝 `#1769FF` = 主行动/关注/链接/当前态；中性面白/`#F3F4F6`/hover `#EAF0F8`；文字 `#1A1A1A`/`#666666`；描边 `#E0E0E0`；危险 `#D93025`；成功（已关注）按钮黑 `#1A1A1A`。遮罩 `rgba(0,0,0,0.6)`。

### 字体

UI 13–15px；项目标题 20–24px SemiBold、长项目正文 16px；数字 tabular；标签 12–13px。中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

feed 4 列、gap 20px；项目卡 8px 圆角、图 16:10；详情页图宽 ≤1200px 居中、说明列 720px；点赞/收藏操作条 sticky 底部任务栏 56px。动效：图 hover 放大 1.02、点赞 200ms，无弹跳。

### UI/UX CSS Token

```css
/* Behance — UI/UX Token（项目平台） */
--bh-ui-bg: #FFFFFF;
--bh-ui-bg-gray: #F3F4F6;
--bh-ui-hover: #EAF0F8;
--bh-ui-text: #1A1A1A;
--bh-ui-text-subtle: #666666;
--bh-ui-blue: #1769FF;
--bh-ui-blue-hover: #0B4FCC;
--bh-ui-danger: #D93025;
--bh-radius-card: 8px;
--bh-radius-btn: 6px;
--bh-font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--bh-motion: 200ms ease;
/* 应用：项目详情大图 + 720px 说明列；操作条白底描边 sticky */
```

## 记忆点与应用方式

复现"Behance 感"三步：①白底 + 灰卡 `#F3F4F6` + 4 列网格 + 8px 圆角；②蓝 `#1769FF` 做内容行动（关注/链接）；③项目卡图上浮 1.02 加轻阴影。做"作品集、档案、创意平台"类页面首选。

## 反混搭提示

Behance 是"档案感"——不要渐变、不要玻璃拟态、不要过大的品牌装饰；蓝只做单一强调。避免与 Dribbble 粉混淆：同属作品社区但 Behance 的蓝是"工程蓝"而非"社交粉"。
