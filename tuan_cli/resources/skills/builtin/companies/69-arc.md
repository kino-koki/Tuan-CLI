# 69. Arc (The Browser Company) — 未来浏览器 静谧蓝

> **类型**：软件 | **领域**：浏览器产品 | **设计哲学**：让浏览器成为操作系统

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / 深蓝 `#0A0E1A` |
| 强调色 | `#4A88F5` Arc蓝 |
| 字体策略 | 系统栈 + 圆角几何展示 |
| 记忆点 | 静谧蓝 + 弧形/圆润窗口 |

## HTML 板块 · 官网与营销页

### 设计哲学

Arc 官网（The Browser Company）把"浏览器"讲成产品设计的先锋实验：深蓝黑段 + 静谧蓝 `#4A88F5` 主强调 + 超圆润窗口/书签卡；hero 常直接是浏览器产品 UI。设计语言**克制但极具辨识**——大量留白、几何圆角、罕见的大标题排版；营销纪录片式（视频截图 + 竖排文案），传达"我们把浏览器重新发明了"。

### 色彩

画布白 `#FFFFFF`、深蓝黑 `#0A0E1A`（dark 段）、浅灰 `#F5F6F8`；主强调蓝 `#4A88F5`（CTA、链接、选中）、hover `#3A6FD6`；文字 `#101318`/白、灰 `#5C6470`；分割线 `#E4E8EE`；成功绿 `#2FA866`。

### 字体

系统栈 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`；展示可圆角几何粗体；标题 40–80px SemiBold；正文 16–18px；中文 PingFang SC / Microsoft YaHei。

### 布局、间距、圆角与动效

内容 1200px；区块 96–160px（大量留白）；卡片/窗口 16–24px 圆角（**可大圆角突显圆润**）、hover 上浮；按钮 8px（蓝实心/白描边）；hero 常为浏览器 UI 完整展示；动效 300ms 平滑、滚动叙事。

### HTML CSS Token

```css
/* Arc — HTML 官网 Token */
--ar-blue: #4A88F5;
--ar-blue-hover: #3A6FD6;
--ar-blue-soft: #E9F0FE;
--ar-bg: #FFFFFF;
--ar-bg-dark: #0A0E1A;
--ar-bg-gray: #F5F6F8;
--ar-text: #101318;
--ar-text-subtle: #5C6470;
--ar-line: #E4E8EE;
--ar-success: #2FA866;
--ar-radius-window: 20px;
--ar-radius-card: 16px;
--ar-radius-btn: 8px;
--ar-font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--ar-space-section: 120px;
--ar-motion: 300ms cubic-bezier(0.3, 0.7, 0.3, 1);
/* 应用：浏览器窗口 20px 大圆角 + 轻阴影；hero 深蓝黑段 + 蓝 CTA */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品界面是"浏览器即工作台"：左侧边栏（Space/标签）、中央内容、底部命令面板；UI 深色可选、极圆润（标签卡、菜单、输入框大量 12–20px 圆角）。蓝色做当前标签/主行动，其余中性。设计目标是**让浏览器的每个部件都可被命令化触发**（Cmd+T、空格菜单），视觉安静以服务快捷。

### 色彩（组件与语义 Token）

蓝 `#4A88F5` = 当前标签/主行动/选中；中性面白/浅灰 `#F5F6F8` hover `#EDF0F4`；描边 `#DDE2EA`；文字 `#101318`/`#5C6470`；深色模式面板 `#101014`、hover `#1C1C22`；危险红 `#E5484D` 仅关闭/删除。

### 字体

UI 13–15px；标签名 13px Medium；命令面板 14px；收藏夹标题 14px。中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

侧边栏 240–280px 可折叠；标签卡 10px 圆角、hover 显示关闭；命令面板（Cmd+T）居中 680px、20px 圆角；底部提示条胶囊。动效：面板 250ms scale、标签切换 200ms、URL 加载进度 300ms。

### UI/UX CSS Token

```css
/* Arc — UI/UX Token（浏览器） */
--ar-ui-blue: #4A88F5;
--ar-ui-bg: #FFFFFF;
--ar-ui-bg-2: #F5F6F8;
--ar-ui-hover: #EDF0F4;
--ar-ui-line: #DDE2EA;
--ar-ui-text: #101318;
--ar-ui-text-subtle: #5C6470;
--ar-ui-dark-panel: #101014;
--ar-ui-dark-hover: #1C1C22;
--ar-ui-danger: #E5484D;
--ar-sidebar-w: 260px;
--ar-radius-tab: 10px;
--ar-radius-palette: 20px;
--ar-font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--ar-motion: 250ms cubic-bezier(0.3, 0.7, 0.3, 1);
/* 应用：命令面板居中 20px 圆角深底；当前标签蓝 underline 2px */
```

## 记忆点与应用方式

复现"Arc 感"三步：①静谧蓝 `#4A88F5` + 白/深蓝黑画布；②浏览器窗口 16–20px 大圆角是核心记忆点；③大量留白 + 大标题 + 平滑滚动叙事。做"浏览器、桌面软件、未来感工具"类官网首选。

## 反混搭提示

Arc 蓝温和不发紫——不要渐变蓝紫光晕；圆角可以大但阴影必须轻（避免"迪士尼风"）。产品页不要把命令面板做成聊天机器人；保持"工作台"秩序感。
