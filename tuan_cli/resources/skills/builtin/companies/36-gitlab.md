# 36. GitLab — Pajamas 设计系统

> **类型**：软件 | **领域**：开发者平台 | **设计哲学**：Person-first, Transparent, Unified

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` |
| 强调色 | `#FC6D26` GitLab橙 |
| 字体策略 | Inter |
| 记忆点 | 黑 + 橙工具箱语言 |

## HTML 板块 · 官网与营销页

### 设计哲学

GitLab 官网把"橙色工具箱"当成人格：顶部黑色导航条 + GitLab 橙 `#FC6D26` CTA，白底内容，墨黑大字；开源与社区气质，无过度动画、无花哨渐变。文案直白（from idea to production），视觉也是"工具"而非"秀场"。

### 色彩

橙 `#FC6D26`（CTA/品牌）、hover `#E24329`；墨黑 `#171321`（导航/页脚/标题）；白 `#FFFFFF`；浅灰 `#F4F3F1`；次要文字 `#6D6D6D`。橙不做大面积填充，只点按钮与品牌脉冲。

### 字体

Inter（全站统一）：展示 32–56px SemiBold，正文 16px，代码 JetBrains Mono / ui-monospace。

### 布局、间距、圆角与动效

8px 栅格；区块 72–96px；卡片 12px、按钮 6px 圆角；动效 150ms ease-out，hover 对 CTA 做颜色加深。



### HTML CSS Token

```css
/* GitLab — HTML 官网 Token */
--gl-orange: #FC6D26;
--gl-orange-hover: #E24329;
--gl-black: #171321;
--gl-bg: #FFFFFF;
--gl-soft: #F4F3F1;
--gl-text: #171321;
--gl-muted: #6D6D6D;
--gl-border: #DCD7D1;
--font: 'Inter', -apple-system, 'Segoe UI', sans-serif;
--font-mono: 'JetBrains Mono', ui-monospace, monospace;
--radius-card: 12px;
--radius-button: 6px;
--space-section: 72px;
--motion: 150ms ease-out;
/* 应用：导航黑、CTA 橙、内容白；橙色不做大面积填充 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

Pajamas 用语义 token 管理颜色——按"用途"命名（primary/attention/severity），主题经 CSS 变量切换；组件密度适中、可访问性内建（对比度 ≥ 4.5:1）；透明的状态系统（CI/CD 流水线、issue 状态）贯穿产品。

### 色彩（组件与语义 Token）

主画布 `#FFFFFF`、subtle `#F7F6F5`；文字 `#171321`、muted `#6D6D6D`；品牌强调橙 `#FC6D26`；次级蓝（Pajamas blue-500，观察值）`#1F75CB`；success `#1B7C46`、warning `#B36300`、danger `#A11F1F`；边框 `#DCD7D1`；暗色可选 bg `#1F1E24`、文字 `#FDFDFC`。

### 字体

Inter；正文 14–16px、标题 16–32px；代码 JetBrains Mono。数据表密度高，标签字号 12px。

### 布局、间距、圆角与动效

8px 栅格；表单/按钮 6–8px 圆角、卡片 8–12px；侧边导航 + 内容流。动效 100–200ms，状态切换用颜色而非位移。



### UI/UX CSS Token

```css
/* GitLab — UI/UX Token（Pajamas 语义） */
--pj-bg: #FFFFFF;
--pj-bg-subtle: #F7F6F5;
--pj-text: #171321;
--pj-text-muted: #6D6D6D;
--pj-primary: #1F75CB;
--pj-accent: #FC6D26;
--pj-accent-hover: #E24329;
--pj-success: #1B7C46;
--pj-warning: #B36300;
--pj-danger: #A11F1F;
--pj-border: #DCD7D1;
--pj-radius: 8px;
--pj-space: 8px;
--font: 'Inter', -apple-system, sans-serif;
--font-mono: 'JetBrains Mono', ui-monospace, monospace;
--motion: 150ms ease-out;
/* 应用：语义 token 命名复用；暗色 bg #1F1E24 可选；橙用于关键动作 */
```

## 记忆点与应用方式

复现"GitLab 感"：①黑色导航栏 + 白内容 + 橙色 CTA 的"工具箱"三段式；②Inter 全站统一；③语义化 token 命名（不叫 green/red，叫 success/danger）；④状态徽章直白、可扫描。

## 反混搭提示

GitLab 橙别和 Google 四色混用；黑导航是"墨色"不用霓虹渐变；次级蓝 #1F75CB 只做辅助强调，主 CTA 永远是橙。
