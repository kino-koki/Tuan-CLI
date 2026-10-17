# 32. Microsoft — Fluent Design 2

> **类型**：软件 | **领域**：科技软件 | **设计哲学**：Coherent, Crafted, Familiar

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 浅色 |
| 强调色 | `#0F6CBD` Fluent蓝 |
| 字体策略 | Segoe UI Variable |
| 记忆点 | Fluent 2 亚克力分层 |

## HTML 板块 · 官网与营销页

### 设计哲学

Microsoft 官网以 Fluent 2 语言呈现：白/浅灰基底、Fluent 蓝 `#0F6CBD` 交互、**Mica / Acrylic 材质**制造玻璃分层、4px 圆角工程网格；大 hero 图 + 模块化卡片；Windows 11 桌面墙纸式蓝紫光晕被复用为 hero 背景。整体气质是"现代办公室的秩序感"：清晰、友善、不浮夸。

### 色彩

主强调 `#0F6CBD`（链接、CTA、焦点）；hero 渐变蓝紫（`#0078D4 → #6B4EFF` 类光晕，来自 Windows 壁纸）；文本 `#1B1B1B`、次要 `#616161`；背景白 `#FFFFFF` 与浅灰 `#F5F5F5` 交替。

### 字体

Segoe UI Variable（Display 用于标题、Text 用于正文），标题 SemiBold；fallback `Segoe UI, system-ui`。

### 布局、间距、圆角与动效

12 列栅格；区块 64–96px；卡片圆角 4–8px（值小、方正）；按钮 4px。动效 150–300ms，hover 用轻微 elevation 与颜色变化，不做弹跳。



### HTML CSS Token

```css
/* Microsoft — HTML 官网 Token（Fluent 2 营销页） */
--ms-accent: #0F6CBD;
--ms-accent-hover: #115EA3;
--ms-bg: #FFFFFF;
--ms-bg-soft: #F5F5F5;
--ms-text: #1B1B1B;
--ms-text-secondary: #616161;
--ms-border: #E1E1E1;
--gradient-hero:
  radial-gradient(ellipse at 30% 20%, rgba(0,120,212,0.35), transparent 60%),
  radial-gradient(ellipse at 75% 30%, rgba(107,78,255,0.30), transparent 55%),
  #FFFFFF;
--radius-sm: 4px;
--radius-md: 8px;
--font-display: 'Segoe UI Variable Display', 'Segoe UI', system-ui, sans-serif;
--font-body: 'Segoe UI Variable Text', 'Segoe UI', system-ui, sans-serif;
--space-section: 96px;
--motion: 200ms ease;
/* 应用：白底为主，accent 蓝做 CTA/链接，hero 用蓝紫光晕，圆角 4-8px */
```

## UI/UX 板块 · 产品界面

### 设计哲学

Fluent 2 三大原则 Coherent（连贯）、Crafted（精工）、Familiar（熟悉）。Windows 11 引入 Mica 云母材质（背景随窗口内容实时微动）、Acrylic 亚克力（浮层半透明模糊）、圆角窗口与 Snap 布局；产品语言是"材质 + 层级 + 秩序"，用背景深浅与阴影分层而非彩色块。

### 色彩（组件与语义 Token）

亮色：TextPrimary `#1B1B1B`、TextSecondary `#5D5D5D`、Accent `#0F6CBD`、页面背景 `#FFFFFF`、SurfaceSunken `#F5F5F5`、边框 `#E1E1E1`。暗色：TextPrimary `#FFFFFF`、背景 `#202020`、Surface `#2B2B2B`。状态：success `#0F7B0F`、warning `#9D5D00`、danger `#C42B1C`、info 蓝。

### 字体

Segoe UI Variable；Type Ramp 14 级（display → caption），标题用 Segoe UI Variable Display SemiBold。

### 布局、间距、圆角与动效

8px 间距栅格；浮层 24px 内边距；控件圆角 4px、卡片 8px、窗口 8px（Fluent 2 保持小圆角）。动效 easing `cubic-bezier(0.1,0.9,0.2,1)`：ControlFast 167ms、Control 250ms。层级用 Elevation 阴影 0–8 级与 Mica/Acrylic 材质，不用大色块。



### UI/UX CSS Token

```css
/* Microsoft — UI/UX Token（Fluent 2） */
--fluent-accent: #0F6CBD;
--fluent-accent-hover: #115EA3;
--fluent-text-primary: #1B1B1B;
--fluent-text-secondary: #5D5D5D;
--fluent-bg: #FFFFFF;
--fluent-bg-subtle: #F5F5F5;
--fluent-surface-sunken: #F5F5F5;
--fluent-border: #E1E1E1;
--fluent-success: #0F7B0F;
--fluent-warning: #9D5D00;
--fluent-danger: #C42B1C;
--fluent-radius-control: 4px;
--fluent-radius-card: 8px;
--fluent-radius-window: 8px;
--fluent-space: 8px;
--fluent-elevation-2: 0 2px 8px rgba(0,0,0,0.08), 0 0 2px rgba(0,0,0,0.04);
--font: 'Segoe UI Variable', 'Segoe UI', system-ui, sans-serif;
--motion-fast: 167ms cubic-bezier(0.1, 0.9, 0.2, 1);
--motion-normal: 250ms cubic-bezier(0.1, 0.9, 0.2, 1);
/* 应用：层级靠背景浅灰与阴影，控件 4px 圆角，accent 只用于交互/选中 */
```

## 记忆点与应用方式

复现"微软感"：①白/浅灰双层背景 + 4px 圆角小控件；②Fluent 蓝 `#0F6CBD` 单色交互；③hero 用 Windows 壁纸式蓝紫光晕；④浮层用 Acrylic 半透明模糊材质做出"玻璃分层"，而非厚卡片阴影。

## 反混搭提示

微软是"浅色工程网格"——勿加粗衬线标题（McKinsey 领域），勿让蓝紫渐变铺满全屏 hero（Vercel 是黑白+网格渐变）；层级用 elevation 与材质，不用彩色块。
