# 14. Slack — 多彩协作的视觉语言

> **类型**：软件 | **领域**：团队协作 | **设计哲学**：Vibrant Collaboration, Playful Professionalism

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` |
| 强调色 | `#4A154B` Aubergine |
| 字体策略 | Slack-Lato |
| 记忆点 | 三栏协作骨架 |

## 设计规格（定本原文）

**领域标签**：团队协作 | **设计哲学**：Vibrant Collaboration, Playful Professionalism

Slack 的品牌系统围绕“色彩即语言”构建——Aubergine 紫 `#4A154B` 作为主品牌色，搭配蓝、绿、黄、红四个辅助色构成完整的色彩语言。侧边栏的 Aubergine 主题是 Slack 最具辨识度的视觉锚点。三栏布局（sidebar、message list、thread）是产品界面的骨架。

**色彩**：Aubergine `#4A154B` 是品牌核心。四个品牌色（蓝 `#36C5F0`、绿 `#2EB67D`、黄 `#ECB22E`、红 `#E01E5A`）用于产品功能标记和品牌表达。界面底色为白色或浅灰。

**字体**：系统字体栈，`Slack-Lato` 作为首选（自定义字体），保持跨平台一致性。产品界面字体适中，但品牌表达区域可用更粗的字重。

**间距**：三栏布局定义了空间节奏。侧边栏窄（70px collapsed），消息列表宽，thread 面板中等。间距以 4px 为基准。

**记忆点**：Aubergine 紫侧边栏 + 四色品牌语言 + 三栏布局的协作骨架。

## CSS Token（可直接复现）

```
/* Slack — 可复现设计系统 Token */

/* 字体 */
--font-display: 'Slack-Lato', 'Lato', system-ui, sans-serif;
--font-body: 'Slack-Lato', 'Lato', system-ui, sans-serif;

/* 字号 */
--fs-display: clamp(1.75rem, 3.5vw, 2.5rem);
--fs-title: 1.125rem;
--fs-body: 0.9375rem;
--fs-note: 0.8125rem;
--fw-regular: 400;
--fw-bold: 700;

/* 色彩 */
--slack-aubergine: #4A154B;
--slack-blue: #36C5F0;
--slack-green: #2EB67D;
--slack-yellow: #ECB22E;
--slack-red: #E01E5A;
--slack-white: #FFFFFF;
--slack-surface: #F8F8F8;
--slack-text-primary: #1D1C1D;
--slack-text-secondary: #616061;
--slack-border: #DDDDDD;
--slack-sidebar-active: #1164A3;

/* 间距 */
--space-xs: 4px;
--space-sm: 8px;
--space-md: 16px;
--space-lg: 24px;
--space-xl: 32px;

/* 圆角 */
--radius-sm: 4px;
--radius-md: 8px;
--radius-lg: 12px;

/* 动效 */
--motion-hover: 120ms ease-out;
--motion-enter: 250ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：Aubergine 侧边栏 + 四色品牌 + 三栏协作骨架 */
/* 应用方式：侧边栏 #4A154B，品牌色用于功能标记，三栏布局 */
```
