# 45. Squarespace — 建站美学 墨黑画廊

> **类型**：软件 | **领域**：建站平台 | **设计哲学**：画廊级极简展示

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / `#000000` 黑 |
| 强调色 | `#000000` 黑（无彩色品牌） |
| 字体策略 | 系统几何无衬线（Avenir / Inter 类） |
| 记忆点 | 黑白两色 + 巨型版面摄影 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## HTML 板块 · 官网与营销页

### 设计哲学

Squarespace 官网是"用产品本身做广告"的典范：全屏大图、超大衬线/几何字标题、黑白主色，页面像一间当代艺术画廊。品牌没有固定彩色——黑色就是它的 signature，任何模板都围绕"内容即设计"展开。营销页节奏：全屏图片段 + 极简标题段交替，滚动即翻页。

### 色彩

画布白 `#FFFFFF`、黑 `#000000`、灰 `#F5F5F5`（浅段）、深灰 `#111111`（暗段）；文字黑/白、辅助灰 `#6E6E6E`；**系统内无品牌色**，模板色彩全部由用户内容决定；若出现强调色（如黄 `#FFD200`），仅作营销闪耀点且面积极小。

### 字体

模板字体库丰富，官网常用无衬线几何（Avenir Next、Inter、Helvetica）与衬线展示体（如 "Garamond"）；标题 48–96px、字重 Light–Medium；正文 16–18px；可用 `letter-spacing` 拉开字距做"画廊字"。中文标题可用思源黑体/Source Han Sans。

### 布局、间距、圆角与动效

全屏 hero（100vh）；区块间距 120–160px；栅格 12 列、卡片 0–4px 圆角（**趋直角**）；按钮黑色实心/白描边矩形（0–4px）；图片全出血或留白 1:1 交替；滚动 400–700ms 平滑、视差适度；hover 图片轻微缩放 1.02。

### HTML CSS Token

```css
/* Squarespace — HTML 官网 Token */
--sq-bg: #FFFFFF;
--sq-bg-dark: #111111;
--sq-bg-gray: #F5F5F5;
--sq-text: #000000;
--sq-text-subtle: #6E6E6E;
--sq-black: #000000;
--sq-white: #FFFFFF;
--sq-radius: 0px;
--sq-radius-card: 4px;
--sq-space-section: 128px;
--sq-fs-display: clamp(40px, 6vw, 88px);
--sq-font-display: 'Avenir Next', Inter, 'Helvetica Neue', 'PingFang SC', 'Microsoft YaHei', sans-serif;
--sq-font-body: Inter, system-ui, sans-serif;
--sq-ease: cubic-bezier(0.25, 0.46, 0.45, 0.94);
--sq-motion: 500ms var(--sq-ease);
/* 应用：全屏 hero + 黑色矩形按钮；字距拉开、黑白两色、图片全出血 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

用户后台（site editor / 内容管理）延续画廊美学：左侧面板极薄、主画布即"你正在编辑的网站"，选择器、色板与模板列表都以大面积缩略图呈现。设计目的是让用户"所见即所得"——编辑器本身就是成品预览，UI 控件低调到近乎隐形。

### 色彩（组件与语义 Token）

中性为主：白面、`#FAFAFA` 二级面、黑字、灰 `#8C8C8C` 说明；强调仅一档（模板自带品牌色可配置）；选中态黑色描边或 2px 黑色 outline；危险 `#D0021B`；分割线 `#E4E4E4`；遮罩 `rgba(0,0,0,0.5)`。

### 字体

面板：系统栈 13–15px；画布标题模拟站点字（用模板字体）；图标线框风格 20px；数字 tabular。中文 UI PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

左侧栏 280px、可折叠；主画布全高；模板卡片 8px 圆角、1px 描边；工具条 48px；拖拽手柄 hover 显示 4px 圆点。动效：拖拽 200ms、面板滑入 250ms ease、画布切换 300ms fade，禁用弹跳。

### UI/UX CSS Token

```css
/* Squarespace — UI/UX Token（站点编辑器） */
--sq-ui-bg: #FFFFFF;
--sq-ui-bg-2: #FAFAFA;
--sq-ui-line: #E4E4E4;
--sq-ui-text: #000000;
--sq-ui-text-subtle: #8C8C8C;
--sq-ui-accent: #000000;
--sq-ui-selected: 2px solid #000000;
--sq-ui-danger: #D0021B;
--sq-panel-w: 280px;
--sq-radius-tile: 8px;
--sq-font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--sq-motion: 250ms ease;
/* 应用：编辑器面板低调灰阶，选中态一律黑色描边 */
```

## 记忆点与应用方式

复现"Squarespace 感"三步：①黑白两色 + 全屏大图 + 超大字（40–88px）；②按钮直角/近直角、间距 120px+ 拉大；③滚动平滑如翻页。做"作品集、品牌官网、高端模板"类页面时，画布与字体即可完成全部表达。

## 反混搭提示

Squarespace 的品牌感靠"空"建立——不要加渐变、不要加多彩按钮、不要堆组件卡片；任何彩色出现都必须小到像"画廊里的一件作品"。按钮禁用胶囊；模板类页面禁用厚重阴影。
