# 37. Salesforce — Lightning 设计系统

> **类型**：软件 | **领域**：企业软件 | **设计哲学**：Clarity, Efficiency, Consistency, Beauty

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF`/`#F3F3F3` |
| 强调色 | `#0176D3` Lightning蓝 |
| 字体策略 | Salesforce Sans |
| 记忆点 | 低对比蓝绿 + 高密度数据 |

## HTML 板块 · 官网与营销页

### 设计哲学

Salesforce 官网是"云 CRM 信任蓝"：白底大卡片、Low-saturation 蓝绿（`#0176D3` + `#00A1E0`）、8–16px 圆角、行业云大图与客户 Logo 墙；营销语言乐观友好，AI 功能用虚线/网格元素表达。整体传达"可靠但不笨重"的企业软件气质。

### 色彩

主蓝 `#0176D3`、天青 `#00A1E0`、偶用紫 `#5C4DB0`；白 `#FFFFFF`、浅灰 `#F3F3F3`；文字 `#080707`、次要 `#514F4D`；边框 `#C9C9C9`。

### 字体

Salesforce Sans（fallback Arial/Helvetica）：展示 32–56px、正文 16px；数字用于数据场景可用等宽。

### 布局、间距、圆角与动效

12px 基础层；区块 72–96px；卡片 12px、按钮 4px（Low-radius，方）；动效 200ms ease-out。



### HTML CSS Token

```css
/* Salesforce — HTML 官网 Token */
--sf-blue: #0176D3;
--sf-blue-hover: #014486;
--sf-blue-light: #00A1E0;
--sf-purple: #5C4DB0;
--sf-bg: #FFFFFF;
--sf-bg-soft: #F3F3F3;
--sf-ink: #080707;
--sf-muted: #514F4D;
--sf-border: #C9C9C9;
--font: 'Salesforce Sans', Arial, Helvetica, sans-serif;
--radius-card: 12px;
--radius-button: 4px;
--space-section: 96px;
--motion: 200ms ease-out;
/* 应用：白底为主，蓝绿 CTA，4px 方按钮，卡片 12px 圆角 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

Lightning Design System（LDS）追求"企业级清晰"：页面浅灰底 `#F3F3F3`、白色数据卡片、4px 方按钮、高密度表格与侧导航；可访问配色经官方验证（对比度、键盘导航）。设计目标是让复杂业务数据**一眼可扫**。

### 色彩（组件与语义 Token）

Brand `#0176D3`、brand hover `#014486`；页面背景 `#F3F3F3`、surface `#FFFFFF`；文字 primary `#080707`、secondary `#514F4D`；边框 `#C9C9C9`、separator `#E5E5E5`；success `#2E844A`、warning `#DD7A01`、error `#BA0517`、info `#706E6B`；大页头（header band）可用深蓝 `#032D60`。

### 字体

Salesforce Sans 13px 基准（数据稠密时 12–14px）；标题 16–24px SemiBold。表格表头 12px 大写可选。

### 布局、间距、圆角与动效

4/8 栅格；卡片内 12–16px；控件/按钮 4px 圆角、卡片 8px；区块 16–24px。动效 100–250ms，聚焦用 2px 品牌蓝 ring。



### UI/UX CSS Token

```css
/* Salesforce — UI/UX Token（Lightning） */
--lds-brand: #0176D3;
--lds-brand-hover: #014486;
--lds-page: #F3F3F3;
--lds-surface: #FFFFFF;
--lds-text: #080707;
--lds-text-secondary: #514F4D;
--lds-border: #C9C9C9;
--lds-border-separator: #E5E5E5;
--lds-success: #2E844A;
--lds-warning: #DD7A01;
--lds-error: #BA0517;
--lds-link: #0176D3;
--lds-radius-control: 4px;
--lds-radius-card: 8px;
--lds-focus-ring: 0 0 0 2px rgba(1, 118, 211, 0.5);
--font: 'Salesforce Sans', Arial, sans-serif;
--space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px;
--motion: 150ms ease-out;
/* 应用：页面 #F3F3F3、卡片白、数据 13px、按钮 4px 圆角、聚焦蓝色 ring */
```

## 记忆点与应用方式

复现"Salesforce 感"：①浅灰页面底 + 白卡片 + 高密度表格的企业后台骨架；②低饱和蓝绿（正蓝 #0176D3 + 天青 #00A1E0）；③4px 方按钮、2px 蓝色聚焦 ring；④状态色（绿/琥珀/红）永远语义化。

## 反混搭提示

勿给 Salesforce 加超亮渐变 CTA（Stripe 领域）；控件保持 4px 方边、勿上 Airbnb 大圆角三层阴影；暗色模式优先做"深蓝页头 + 浅内容"而非全黑。
