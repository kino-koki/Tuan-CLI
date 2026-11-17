# 53. Intercom — 客户沟通 塑型蓝

> **类型**：软件 | **领域**：客户支持 SaaS | **设计哲学**：对话驱动的人性化科技

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / 深墨 `#10131F` |
| 强调色 | `#1F8FEB` Intercom蓝 |
| 字体策略 | 系统栈（展示可用几何粗体） |
| 记忆点 | 对话气泡 + 塑型蓝 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## HTML 板块 · 官网与营销页

### 设计哲学

Intercom 官网的核心隐喻是"对话"：hero 常是产品聊天界面截图 + 深色/浅色双段；主品牌蓝 `#1F8FEB`（官方 Blue）配合黑/白画布，传达**机器与人之间的温暖科技**。整体现代、克制、带一点工程感——适合"B 端产品但要有人味"的场景。营销页多展示真实聊天 UI 与人物引用。

### 色彩

画布白 `#FFFFFF`、深墨蓝黑 `#10131F`（dark 段）、浅灰 `#F5F7FA`；主强调蓝 `#1F8FEB`（CTA、链接、消息发送键）、hover `#1773C7`；文字 `#16181D`、灰 `#5E6472`；分割线 `#E6E9EF`；成功绿 `#0CA678`。

### 字体

系统栈 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`；展示可配粗体几何（标题 36–64px SemiBold/Extrabold）；正文 15–18px；中文 PingFang SC / Microsoft YaHei。

### 布局、间距、圆角与动效

内容 1200px；区块 88–128px（深色段常全屏）；卡片 12–16px 圆角；按钮 8px；hero 产品聊天窗 12px 圆角 + 阴影；动效 250ms、聊天消息入场 stagger 100ms；hover 卡片上浮。

### HTML CSS Token

```css
/* Intercom — HTML 官网 Token */
--ic-blue: #1F8FEB;
--ic-blue-hover: #1773C7;
--ic-blue-soft: #E9F4FE;
--ic-bg: #FFFFFF;
--ic-bg-dark: #10131F;
--ic-bg-gray: #F5F7FA;
--ic-text: #16181D;
--ic-text-subtle: #5E6472;
--ic-line: #E6E9EF;
--ic-success: #0CA678;
--ic-radius-card: 14px;
--ic-radius-btn: 8px;
--ic-font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--ic-space-section: 96px;
--ic-motion: 250ms ease;
/* 应用：主 CTA 蓝实心；深墨 hero 段可白字 + 蓝按钮 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品界面围绕"收件箱 + 对话"构建：客户收件箱（会话列表 + 对话详情 + 右侧客户档案）、帮助中心、即时聊天控件。UI 以**对话气泡为主角**，蓝 `#1F8FEB` 用作头像/已读/发送，灰阶保持专业；整体氛围像"现代的 CRM 与聊天室交叉体"。

### 色彩（组件与语义 Token）

蓝 `#1F8FEB` = 品牌/主行动/未读标识；中性：白面、`#F4F6F9` hover、`#ECEFF3` 选中；描边 `#DCE1E8`；文字 `#16181D`/`#5E6472`；自动回复绿点 `#0CA678`、离线灰点 `#C4CAD4`；危险红 `#D64545`。

### 字体

UI 13–15px；会话标题 14px Medium；消息正文 14px/1.5；客户名 15px SemiBold。中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

左侧导航 240px；会话列表 360px；对话区自适应（气泡向左/右）；右档案 320px；气泡 12px 圆角、我方蓝底白字/对方白底灰字；输入框胶囊。动效：新消息 250ms 入场、未读红点 200ms、输入提示打字机 300ms。

### UI/UX CSS Token

```css
/* Intercom — UI/UX Token（收件箱 / 聊天） */
--ic-ui-bg: #FFFFFF;
--ic-ui-bg-2: #F4F6F9;
--ic-ui-hover: #ECEFF3;
--ic-ui-line: #DCE1E8;
--ic-ui-text: #16181D;
--ic-ui-text-subtle: #5E6472;
--ic-ui-blue: #1F8FEB;
--ic-ui-success: #0CA678;
--ic-ui-offline: #C4CAD4;
--ic-ui-danger: #D64545;
--ic-list-w: 360px;
--ic-avatar: 36px;
--ic-radius-bubble: 12px;
--ic-radius-btn: 8px;
--ic-font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--ic-motion: 200ms ease;
/* 应用：我方气泡蓝底白字 12px 圆角；对方白底描边（模拟聊天产品） */
```

## 记忆点与应用方式

复现"Intercom 感"三步：①主蓝 `#1F8FEB` + 白/深墨双画布；②核心资产是对话 UI——气泡、头像、未读点；③B 端页可加"人来人往"的真实引用。做"客服、CRM、聊天机器人"类产品页面时直接参考。

## 反混搭提示

Intercom 蓝不要做成渐变霓虹；聊天气泡方形或超大圆角都偏离（12px 刚刚好）。避免把深墨段做成蓝紫色渐变；多色只在用户状态点（在线绿/离线灰）。
