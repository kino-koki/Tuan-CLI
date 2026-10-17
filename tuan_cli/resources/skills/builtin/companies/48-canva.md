# 48. Canva — 人人设计 青紫渐变

> **类型**：软件 | **领域**：设计工具平台 | **设计哲学**：让设计零门槛的灿烂

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / 奶油 `#FEFEFE` |
| 强调色 | 青 `#00C4CC` → 紫 `#7D2AE8` 渐变 |
| 字体策略 | Canva Sans / 系统栈（圆润几何） |
| 记忆点 | 青紫渐变 + 大量圆角卡片 |

## HTML 板块 · 官网与营销页

### 设计哲学

Canva 官网把"创意民主化"翻译成高饱和但轻盈的画面：青 `#00C4CC` 到紫 `#7D2AE8` 的品牌渐变做 logo、强调与插图渐变；卡片平台式布局（模板、团队、教育）配合鲜艳但不过载的插画。整体是**数位乐高**：圆、亮、可拼。营销页多用"产品界面大图 + 彩色渐变胶囊按钮"。

### 色彩

画布白/奶油；品牌渐变 `linear-gradient(135deg, #00C4CC, #7D2AE8)`（logo、主 CTA 描边、装饰）；主行动青 `#00C4CC`（hover）；辅助紫 `#7D2AE8`；文字近黑 `#1E1E1E`、灰 `#666`；警示绿 `#00B884`。**多色可用但必须"轻"：渐变只点缀，不做整页底**。

### 字体

品牌字 Canva Sans（圆润几何无衬线，2023 起）；`font-family: "Canva Sans", "Helvetica Neue", Arial, "PingFang SC", "Microsoft YaHei", sans-serif`；标题 32–56px SemiBold；正文 16–18px。中文用系统黑体。

### 布局、间距、圆角与动效

模块网格 12 列；卡片 16px 圆角、hover 上浮 4px + 阴影；按钮 9999px 胶囊（高 44–52px）；区块 64–96px；入场 stagger 40ms；动效 200–300ms，允许活泼 bounce；焦点图常用 4:3 或 1:1。

### HTML CSS Token

```css
/* Canva — HTML 官网 Token */
--cv-gradient: linear-gradient(135deg, #00C4CC, #7D2AE8);
--cv-teal: #00C4CC;
--cv-teal-hover: #00B3B8;
--cv-purple: #7D2AE8;
--cv-bg: #FFFFFF;
--cv-bg-cream: #FEFEFE;
--cv-text: #1E1E1E;
--cv-text-subtle: #666666;
--cv-green: #00B884;
--cv-radius-card: 16px;
--cv-radius-pill: 9999px;
--cv-font: 'Canva Sans', 'Helvetica Neue', Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--cv-space-section: 80px;
--cv-motion: 250ms cubic-bezier(0.2, 0.8, 0.4, 1);
/* 应用：主 CTA 青底胶囊；logo/装饰用青紫渐变；卡片 16px 圆角轻阴影 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

编辑器是全屏幕"画布 + 左/右面板"结构，但比专业工具亲切：顶部工具栏彩色图标、模板预览大图、属性面板轻量。所有操作都有即时高亮与撤销提示，饱和度克制在白底上（默认工具用中性，模板才出彩），核心是**让新手 3 秒上手**。

### 色彩（组件与语义 Token）

工具面白、画布灰 `#F2F2F2`；选色/描边自定义；主要行动青 `#00C4CC`（上传、创建）；渐变 `#00C4CC→#7D2AE8` 仅品牌区域与模板封面；次要按钮灰 `#E6E6E6`；危险红 `#C70000` 系；文字 `#1E1E1E`/`#666`。

### 字体

UI：Canva Sans 13–16px；画布文本用户自选。中文 PingFang SC/Microsoft YaHei 14px。

### 布局、间距、圆角与动效

顶部 56px 工具条；左面板 320px（模板库）；画布自由区；卡 12px 圆角；拖拽元素选中 2px 青 outline；旋转手柄、8px 锚点。动效：插入 200ms scale-in、拖拽实时、弹层 250ms；撤销 toast 300ms。

### UI/UX CSS Token

```css
/* Canva — UI/UX Token（编辑器） */
--cv-ui-canvas: #F2F2F2;
--cv-ui-surface: #FFFFFF;
--cv-ui-line: #E6E6E6;
--cv-ui-text: #1E1E1E;
--cv-ui-text-subtle: #666666;
--cv-ui-teal: #00C4CC;
--cv-ui-purple: #7D2AE8;
--cv-ui-danger: #C70000;
--cv-toolbar-h: 56px;
--cv-panel-w: 320px;
--cv-radius-tile: 12px;
--cv-font-ui: 'Canva Sans', 'Helvetica Neue', Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--cv-motion: 200ms cubic-bezier(0.2, 0.8, 0.4, 1);
/* 应用：选中元素 2px 青 outline；模板封面可用青紫渐变 */
```

## 记忆点与应用方式

复现"Canva 感"三步：①白底 + 圆角（卡片 16px/按钮胶囊）+ 轻阴影；②青 `#00C4CC` 到紫 `#7D2AE8` 渐变只做 logo/CTA 描边/装饰；③插画与模板丰富但 UI 工具中性。做"面向大众的创意/SaaS 产品"时最合适。

## 反混搭提示

Canva 渐变极易变成"廉价霓虹"——背景禁止满铺渐变、文字可用但勿大面积彩色渐变字体；按钮主色用青而非渐变；不要堆叠超过 3 个高饱和色块。
