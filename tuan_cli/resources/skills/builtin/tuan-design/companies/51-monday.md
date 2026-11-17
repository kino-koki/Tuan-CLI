# 51. Monday.com — 工作操作系统 亮蓝方块

> **类型**：软件 | **领域**：项目管理 SaaS | **设计哲学**：亮色方块的活力秩序

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / 浅灰 |
| 强调色 | `#0073FF` Monday蓝 |
| 字体策略 | 系统栈 + 几何无衬线展示 |
| 记忆点 | 方块 logo + 亮蓝 + 多彩板 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## HTML 板块 · 官网与营销页

### 设计哲学

Monday 官网充满"活力工作台"气息：亮蓝 `#0073FF` 主强调 + 白底 + 大图标方块（logo 就是四格方块）；产品截图直接放 hero，强化"开箱即用的工作操作系统"。营销页把功能讲成**彩色板块/图形**：图表、进度、自动化，全部以明亮高对比呈现，传达高效、现代、可视化。

### 色彩

画布白 `#FFFFFF`、浅灰 `#F6F7FB`；主强调蓝 `#0073FF`（CTA、链接）、hover `#0061DB`；多彩辅助（图表用）：红 `#FF3300`、黄 `#FFCB00`、绿 `#00C875`、紫 `#A25DDC`——只用于数据可视化与板块图标；文字 `#2D3A4B`、灰 `#6B7C8F`。

### 字体

系统栈 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`；展示标题可更粗（700–800）与轻微字距压缩；标题 32–56px；正文 16–18px；中文 PingFang SC / Microsoft YaHei。

### 布局、间距、圆角与动效

内容 1200px；区块 80–112px；卡片 12px 圆角、hover 上浮；按钮 6–8px 圆角（可胶囊化但更常见小圆角）；hero 常为"左侧文案 + 右侧产品大屏截图"；图表板可全彩；动效 200–300ms、滚动带动画醒目。

### HTML CSS Token

```css
/* Monday.com — HTML 官网 Token */
--mo-blue: #0073FF;
--mo-blue-hover: #0061DB;
--mo-bg: #FFFFFF;
--mo-bg-gray: #F6F7FB;
--mo-text: #2D3A4B;
--mo-text-subtle: #6B7C8F;
--mo-ok: #00C875;
--mo-warn: #FFCB00;
--mo-danger: #FF3300;
--mo-purple: #A25DDC;
--mo-radius-card: 12px;
--mo-radius-btn: 8px;
--mo-font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--mo-space-section: 88px;
--mo-motion: 250ms ease;
/* 应用：主 CTA 亮蓝；图表数据用多色（蓝红黄绿紫各司其职） */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品是"看板之上再叠看板"的高密度工作台：左侧功能栏 + 居中看板/表格/日历视图 + 右侧详情；视图切换是核心交互。UI 用亮色区分功能（状态列颜色、分组色块），白灰底保持可读；整体目标是**让数据像乐高一样可见、可拖、可配**——可视化优先，文字退后。

### 色彩（组件与语义 Token）

主行动蓝 `#0073FF`（新建、添加、主按钮）；状态色系统：done 绿 `#00C875`、working 蓝 `#009EF4`、stuck 红 `#FF3300`；分组/标签色 12+ 可选；中性面白/`#F6F7FB`/hover `#E9F2FF`；描边 `#D8DCE5`；文字 `#2D3A4B`/`#6B7C8F`。

### 字体

UI 13–15px；视图中文字可 14px Medium；数字与进度 tabular；列头 13px SemiBold。中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

顶栏 56px；左侧导航 260px；主视图自由区；卡片 8px 圆角、12px padding；拖拽把手 hover 显现；状态色点 10px 圆形。动效：卡片拖拽 200ms、视图切换 300ms crossfade、完成动画 300ms bounce（适可而止）。

### UI/UX CSS Token

```css
/* Monday.com — UI/UX Token（工作台） */
--mo-ui-bg: #FFFFFF;
--mo-ui-bg-2: #F6F7FB;
--mo-ui-hover: #E9F2FF;
--mo-ui-line: #D8DCE5;
--mo-ui-text: #2D3A4B;
--mo-ui-text-subtle: #6B7C8F;
--mo-ui-blue: #0073FF;
--mo-ui-green: #00C875;
--mo-ui-cyan: #009EF4;
--mo-ui-red: #FF3300;
--mo-radius-card: 8px;
--mo-radius-btn: 8px;
--mo-sidebar: 260px;
--mo-font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--mo-motion: 200ms ease;
/* 应用：状态色点 10px 圆形；视图切换 300ms crossfade */
```

## 记忆点与应用方式

复现"Monday 感"三步：①白底 + 亮蓝 `#0073FF` 主 CTA + 方块图形；②多色只给图表/状态（绿 done/蓝 working/红 stuck）；③产品界面大屏直给 hero。做"工作 OS、数据看板、团队协作"类页面时，亮蓝 + 彩色视图 = 活力生产力。

## 反混搭提示

不要把 Monday 的多彩色做成 UI 背景彩虹；多色是数据语义。蓝色主按钮避免渐变，避免深色 hero；卡片圆角 8–12px，不要 20px+ 大圆角（那是 Google M3）。
