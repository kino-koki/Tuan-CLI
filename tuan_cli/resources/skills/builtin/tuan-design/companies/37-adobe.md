# 37. Adobe — Spectrum 设计系统

> **类型**：软件 | **领域**：创意工具 | **设计哲学**：Coherent, Clear, Inclusive

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FAFAFA` |
| 强调色 | `#FA0F00` Adobe红 |
| 字体策略 | Adobe Clean |
| 记忆点 | 红黑三角符号 + 灰阶工具层 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## HTML 板块 · 官网与营销页

### 设计哲学

Adobe 官网把"创造力"做成高浓度视觉：白底 + Adobe Red `#FA0F00` 强调、红黑三角形 A 符号、丰富产品卡（PS/AI/PR…）+ 灰阶分层；2023 品牌刷新用更烈的红色与更直白的排版表达"万物可编辑"。营销页允许艺术化渐变，但 UI 骨架保持黑白灰。

### 色彩

Adobe Red `#FA0F00`、白 `#FFFFFF`、黑 `#000000`；浅灰 `#F5F5F5`、深灰 `#2C2C2C`、次要文字 `#6E6E6E`；艺术区可用低饱和冷暖渐变。

### 字体

Adobe Clean（官网/产品）+ fallback `'Segoe UI', Arial`：展示 40–64px Bold、正文 16px。

### 布局、间距、圆角与动效

12px 基础栅格；区块 96px；卡片 12–16px、按钮 8px（偏方）；动效 200–300ms ease-out。



### HTML CSS Token

```css
/* Adobe — HTML 官网 Token */
--adobe-red: #FA0F00;
--adobe-red-hover: #D30D00;
--adobe-black: #000000;
--adobe-bg: #FFFFFF;
--adobe-bg-soft: #F5F5F5;
--adobe-ink: #2C2C2C;
--adobe-muted: #6E6E6E;
--font: 'Adobe Clean', 'Segoe UI', Arial, sans-serif;
--radius-card: 12px;
--radius-pill: 9999px;
--space-section: 96px;
--motion: 250ms ease-out;
/* 应用：红仅 logo/重点 CTA，大面积黑白灰，产品卡 12px 圆角 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

Spectrum（现 Spectrum 2）为工具类界面而生：中性灰阶分层（gray 系列）、accent 蓝 `#1473E6` 只做焦点/选中、红色仅品牌；画布/文档永远中立。Spectrum 2 相比 v1 加大了圆角与留白，让密集工具"可呼吸"，但密度仍显著高于消费级应用。

### 色彩（组件与语义 Token）

亮色：bg `#FFFFFF`、gray-50 `#FAFAFA`、gray-200 `#EEEEEE`、gray-300 `#E1E1E1`、gray-500 `#B7B7B7`；text `#1D1D1D`、text-secondary `#6E6E6E`；accent `#1473E6`；success `#2D9D78`、warning `#F9A03F`、error `#E34850`、violet `#8B6FC4`。深色模式 bg `#1D1D1D`、text `#F5F5F5`。

### 字体

Adobe Clean；工具栏 12–13px、面板正文 14–16px、标题 16–24px。等宽用于代码/坐标。

### 布局、间距、圆角与动效

4px 栅格；工具栏 8px、面板 12–16px；Spectrum 2 控件圆角 6–8px、卡片 12–16px、浮层 12px。动效 150–300ms，支持减少动态（reduced-motion）。



### UI/UX CSS Token

```css
/* Adobe — UI/UX Token（Spectrum 2 亮色） */
--sp-bg: #FFFFFF;
--sp-gray-100: #FAFAFA;
--sp-gray-200: #EEEEEE;
--sp-gray-300: #E1E1E1;
--sp-gray-500: #B7B7B7;
--sp-text: #1D1D1D;
--sp-text-secondary: #6E6E6E;
--sp-accent: #1473E6;
--sp-accent-hover: #0D66D0;
--sp-success: #2D9D78;
--sp-warning: #F9A03F;
--sp-error: #E34850;
--sp-violet: #8B6FC4;
--sp-radius-small: 6px;
--sp-radius-medium: 8px;
--sp-radius-large: 16px;
--font: 'Adobe Clean', 'Segoe UI', Arial, sans-serif;
--space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px; --space-8: 32px;
--motion: 200ms ease-out;
/* 应用：灰阶分层，accent 蓝做焦点/选中，红只留在品牌点 */
```

## 记忆点与应用方式

复现"Adobe 感"：①红黑三角符号是小而准的品牌点，UI 保持灰阶；②工具栏 12px 密度 + Spectrum 2 的 8px 圆角新语言；③accent 蓝 `#1473E6` 管一切焦点/选中；④画布永远中立——色彩来自用户内容而非界面。

## 反混搭提示

Adobe 红绝不大面积铺（Coca-Cola 领域）；工具界面勿霓虹渐变（那是 hero 专属）；勿把工具栏做成 Airbnb 的圆润大按钮。
