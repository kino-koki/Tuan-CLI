# 56. Zoom — 视频会议 亲和蓝

> **类型**：软件 | **领域**：音视频会议 SaaS | **设计哲学**：让远程见面更接近见面

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / 浅灰 |
| 强调色 | `#0B5CFF` Zoom蓝 |
| 字体策略 | 系统栈 + 展示无衬线 |
| 记忆点 | Zoom 蓝 + 人像大图 + 圆润按钮 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## HTML 板块 · 官网与营销页

### 设计哲学

Zoom 官网把"会议"讲得有人情味：主蓝 `#0B5CFF`（产品新蓝）与天蓝点缀，白底 + 大量真实会议场景照片；hero 常是"多人在线格子"的大图示意。设计语言**圆润、友好、可信**——按钮带圆角、图形带光晕，传达"距离不是障碍"。营销页以场景（教学、医疗、企业）分区块。

### 色彩

画布白 `#FFFFFF`、浅蓝灰 `#F4F8FE`；主强调蓝 `#0B5CFF`（CTA、链接）、hover `#0946C2`；辅助天蓝 `#00A0FF`；文字 `#101113`、灰 `#5E6670`；分割线 `#E4E9F0`；成功绿 `#2E9E5B`。

### 字体

系统栈 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`；标题 32–56px SemiBold；正文 16–18px；中文 PingFang SC / Microsoft YaHei。

### 布局、间距、圆角与动效

内容 1180px；区块 72–112px；卡片 12–16px 圆角、hover 上浮；按钮 8px 圆角（主蓝/白描边）；hero 常为左右分栏（左文案右视频格子图）；动效 200–300ms。

### HTML CSS Token

```css
/* Zoom — HTML 官网 Token */
--zo-blue: #0B5CFF;
--zo-blue-hover: #0946C2;
--zo-blue-soft: #E7F0FF;
--zo-cyan: #00A0FF;
--zo-bg: #FFFFFF;
--zo-bg-gray: #F4F8FE;
--zo-text: #101113;
--zo-text-subtle: #5E6670;
--zo-line: #E4E9F0;
--zo-success: #2E9E5B;
--zo-radius-card: 14px;
--zo-radius-btn: 8px;
--zo-font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--zo-space-section: 88px;
--zo-motion: 250ms ease;
/* 应用：主 CTA 蓝实心；视频格子卡 14px 圆角 + 深色底 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品界面以"会议室格子"为核心：与会者头像网格、底部控制栏（镜头/麦克风/共享/结束）、右侧聊天。UI 深色为主（`#1D1D1D` 会议室底）——让视频画面突出；控制按钮圆润、hover 高亮、图标化。目标是让每个参会者**3 秒找到控制项**。

### 色彩（组件与语义 Token）

会议室底色深 `#1D1D1D`；控制栏按钮白字灰底 `#3C3C3C` → hover 亮 `#565656`；主行动蓝 `#0B5CFF`（加入/开始）；危险红 `#E02020`（结束会议、静音异常）；静音/镜头关闭状态红点；聊天面板 `#232323`。

### 字体

UI 13–15px；名字标签 12px；会议标题 16px Medium；控制项图标 20–24px。中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

视频格自适应、默认画廊 4–9 格；底部控制栏居中 56px 高、圆角胶囊组；右侧聊天 320px；浮动窗口 12px 圆角。动效：加入/离开 200ms fade、静音图标 150ms、举手 300ms 弹出；画面切换 250ms。

### UI/UX CSS Token

```css
/* Zoom — UI/UX Token（会议室） */
--zo-ui-bg: #1D1D1D;
--zo-ui-panel: #232323;
--zo-ui-ctrl: #3C3C3C;
--zo-ui-ctrl-hover: #565656;
--zo-ui-text: #FFFFFF;
--zo-ui-text-subtle: #B8B8B8;
--zo-ui-blue: #0B5CFF;
--zo-ui-danger: #E02020;
--zo-ctrlbar-h: 56px;
--zo-radius-ctrl: 9999px;
--zo-radius-window: 12px;
--zo-font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--zo-motion: 200ms ease;
/* 应用：控制栏胶囊按钮组；静音/镜头异常用红点语义 */
```

## 记忆点与应用方式

复现"Zoom 感"三步：①官网白底 + 蓝 `#0B5CFF` CTA + 真人会议大图；②产品界面深色 `#1D1D1D` 底 + 底部胶囊控制栏；③图形圆润、人像多、文案温情。做"会议、协作、实时通信"类页面可直接参考，深浅两套并行。

## 反混搭提示

Zoom 蓝不要混入紫色调；会议 UI 深色底上方块必须中性灰，不能加彩色渐变（那是游戏风）。控制栏按钮不要做得像消费者 App 那样扁平无 hover 态。
