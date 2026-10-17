# 47. Webflow — 可视开发 科技蓝

> **类型**：软件 | **领域**：低代码建站平台 | **设计哲学**：让开发者与设计师同屏

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / `#0E0E1A` 深 |
| 强调色 | `#146EF5` Webflow蓝 |
| 字体策略 | 系统几何无衬线 + Figtree 展示 |
| 记忆点 | 蓝色几何块 + 代码感点缀 |

## HTML 板块 · 官网与营销页

### 设计哲学

Webflow 官网把"无代码开发"讲得像工程师文化：深蓝黑底 + 白色几何字 + 网格线/代码片段装饰，主蓝色 `#146EF5` 清晰锋利。页面大量使用"拖拽操作"与产品 UI 截图，结构规整、直角（4–8px）、信息密度高——传达**精确、可控、专业**。营销 hero 常用黑底 + 蓝色光点/网格背景。

### 色彩

画布白（亮段）/深蓝黑 `#0E0E1A`（暗段）；文字 `#111111`/白；主强调蓝 `#146EF5`（CTA、链接、hover）、深蓝 `#0B5FFF` 渐变可用；辅助灰 `#737373`、`#9A9A9A`；网格纹理线 `rgba(255,255,255,0.08)`（暗）/`rgba(0,0,0,0.06)`（亮）。

### 字体

展示字 Figtree（Webflow 品牌字）/ Inter；`font-family: "Figtree", Inter, system-ui, sans-serif`；标题 40–64px SemiBold；代码块 14px `ui-monospace, SFMono-Regular, Menlo, monospace`；中文标题 PingFang SC/Source Han Sans，正文同。

### 布局、间距、圆角与动效

内容区 1200px；区块 96–128px；卡片 8px 圆角、1px 描边、hover 上浮 2px；按钮 6–8px 圆角（非胶囊）；hero 常叠加网格渐变背景；动效 200–300ms，滚动可带 stagger 入场（20–40ms×序号）。

### HTML CSS Token

```css
/* Webflow — HTML 官网 Token */
--wf-blue: #146EF5;
--wf-blue-hover: #0B5FFF;
--wf-bg: #FFFFFF;
--wf-bg-dark: #0E0E1A;
--wf-text: #111111;
--wf-text-subtle: #737373;
--wf-line: #E5E7EB;
--wf-line-dark: rgba(255, 255, 255, 0.12);
--wf-grid-dark: rgba(255, 255, 255, 0.06);
--wf-radius-card: 8px;
--wf-radius-btn: 6px;
--wf-font-display: Figtree, Inter, system-ui, sans-serif;
--wf-font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
--wf-space-section: 96px;
--wf-container: 1200px;
--wf-motion: 250ms ease;
/* 应用：深色 hero + 蓝 CTA；卡片 1px 描边、8px 圆角；穿插代码/网格纹理 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品是可视化网页设计器，UI 核心是"三层结构"：左层面板（元素/样式）、中间画布（所见即所得）、右侧属性面板。配色简洁：白/灰面板 + 蓝色选中态 + 黑色勾勒；每个可拖拽元素 hover 时显示蓝色 outline 与间距标注，把"开发过程"变成视觉语言。

### 色彩（组件与语义 Token）

画布面 `#F7F7F7`（设计器底）/白（画布）；选中 outline 蓝 `#146EF5`；hover 浅蓝 `#E8F0FE`；主行动蓝 `#1B6BF0`；危险红 `#E5484D`；成功绿 `#30A46C`；面板文字 `#1E1E1E` 主/`#6E6E6E` 次；分割线 `#D9D9D9`。

### 字体

UI 统一 Figtree/Inter 13–14px；属性输入 13px；画布保留用户站点字体。代码视图 13px 等宽。中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

左栏 280–320px、右栏 300px、画布居中；工具栏 48px；元素树行高 28px；拖拽标注 1px 虚线蓝；下拉/弹层 8px 圆角 + 4px 阴影。动效：面板 200ms、拖拽实时、hover outline 0ms（避免延迟感）。

### UI/UX CSS Token

```css
/* Webflow — UI/UX Token（可视化设计器） */
--wf-ui-canvas: #F7F7F7;
--wf-ui-surface: #FFFFFF;
--wf-ui-line: #D9D9D9;
--wf-ui-text: #1E1E1E;
--wf-ui-text-subtle: #6E6E6E;
--wf-ui-blue: #146EF5;
--wf-ui-blue-soft: #E8F0FE;
--wf-ui-danger: #E5484D;
--wf-ui-success: #30A46C;
--wf-panel-l: 300px;
--wf-panel-r: 300px;
--wf-radius-panel: 8px;
--wf-font-ui: Figtree, Inter, system-ui, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--wf-font-code: ui-monospace, SFMono-Regular, Menlo, monospace;
--wf-motion: 200ms ease;
/* 应用：选中元素 2px 蓝色 outline；拖拽间距标注 1px 虚线蓝 */
```

## 记忆点与应用方式

复现"Webflow 感"三步：①深蓝黑 hero（`#0E0E1A`）+ 网格/代码纹理；②蓝 `#146EF5` 只做行动与选中；③卡片 1px 描边 8px 圆角、标题用 Figtree 几何感。做"开发者工具、建站平台、SaaS 产品页"时，蓝色 + 代码纹理 = 工程师气质。

## 反混搭提示

Webflow 不是"类 Notion 的奶油感"——避免大红大紫、避免玻璃拟态与 20px 大圆角；蓝色必须保持 `#146EF5` 系锐利，不能发紫发粉。暗色 hero 别做成渐变蓝紫（那是 Vercel/OpenAI 的语言）。
