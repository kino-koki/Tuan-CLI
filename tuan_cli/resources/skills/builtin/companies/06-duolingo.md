# 6. Duolingo — 游戏化教室

> **类型**：软件 | **领域**：消费教育 | **设计哲学**：The World's Most Playful Classroom

| 规格总览 | 值 |
|---|---|
| 画布色 | 白/Snow |
| 强调色 | `#58cc02` Feather绿 |
| 字体策略 | Feather Bold圆润 |
| 记忆点 | 4px底部3D阴影 |

## 设计规格（定本原文）

**领域标签**：消费教育 | **设计哲学**：The World's Most Playful Classroom

Duolingo 的设计系统是一个高能量、游戏化的环境，使用鲜艳色彩和圆润友好的形状让学习感觉像游戏。设计原则包括：Punchy（实色鲜艳标题）、Soft（平静渐变和色彩）、Modular（卡片式灵活布局）、Flat（极简布局+大量留白）。

**色彩**：Feather Green `#58cc02` 是品牌主色。Streak Orange `#ff9600` 和 Gem Pink `#ce82ff` 是次级品牌色。Eel 用于排版，Snow 是主背景色。

**字体**：Feather Bold（自定义圆润无衬线）用于界面，Mona Sans（或 Inter）用于正文。`din-round`、`DIN Round Pro`、Nunito 作为回退字体栈。

**3D 按钮系统**：每个交互元素有 4px 底部阴影，读起来像一个等待被按下的 3D 按钮。

**记忆点**：Feather Green + 4px 底部阴影的 3D 按钮 + 圆润友好的形状语言。

## CSS Token（可直接复现）

```
/* Duolingo — 可复现设计系统 Token */

/* 字体 */
--font-display: 'Feather Bold', 'DIN Round Pro', 'Nunito', sans-serif;
--font-body: 'Mona Sans', 'Inter', sans-serif;

/* 字号 */
--fs-display: clamp(2rem, 4vw, 3rem);
--fs-title: clamp(1.25rem, 2vw, 1.75rem);
--fs-body: 1rem;
--fw-display: 700;
--fw-body: 500;

/* 色彩 */
--duo-green: #58cc02;
--duo-green-shadow: #58a700;
--duo-lime: #89e219;
--streak-orange: #ff9600;
--gem-pink: #ce82ff;
--eel: #4b4b4b;
--snow: #ffffff;
--polar: #f7f7f7;
--macaw: #1cb0f6;

/* 3D 按钮 */
--btn-shadow-offset: 4px;
--btn-shadow-color: var(--duo-green-shadow);

/* 圆角 */
--radius-button: 16px;
--radius-card: 16px;
--radius-large: 24px;

/* 间距 */
--space-xs: 4px;
--space-sm: 8px;
--space-md: 16px;
--space-lg: 24px;
--space-xl: 32px;

/* 动效 */
--motion-press: 100ms ease-out;
--motion-enter: 300ms cubic-bezier(0.175, 0.885, 0.32, 1.275);

/* 记忆点：Feather Green + 4px 底部阴影 + 圆润字体 */
/* 应用方式：所有按钮使用 border-bottom: 4px solid var(--duo-green-shadow) */
```
