# 29. Discord — Blurple 暗色游戏俱乐部

> **类型**：软件 | **领域**：社交游戏 | **设计哲学**：Nocturnal Clubhouse, Playful Density

| 规格总览 | 值 |
|---|---|
| 画布色 | `#313338` 暗色 |
| 强调色 | `#5865F2` Blurple |
| 字体策略 | gg sans |
| 记忆点 | Blurple 暗色发光 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## 设计规格（定本原文）

**领域标签**：社交游戏 | **设计哲学**：Nocturnal Clubhouse, Playful Density

Discord 的设计系统像一个“俱乐部会所而非企业应用”——柔软、圆润、略带夜间气质，为闲逛而建。标志性的 Blurple `#5865f2` 在深蓝炭色表面上发光，暗色主题是默认人格而非选项。一切友好而活泼：粗圆角、厚实按钮、慷慨内边距、读起来亲切而非严肃的字体。

**色彩**：Blurple `#5865f2` 是主强调色（CTA、链接、品牌填充）。暗色画布 `#313338` 是主表面，`#1e1f22` 是最深层级（服务器列表/侧边栏），`#2b2d31` 是频道列。状态色：绿 `#23a559`（在线）、黄 `#f0b232`（离开）、红 `#da373c`（勿扰）。

**字体**：gg sans（Discord 定制 Whitney 替代字体），圆润人文风格，意图是温暖、随意、在密集聊天的小尺寸下仍可读。显示字重上限 700，活泼感来自圆角和颜色而非极端字重。

**间距**：8px 基准（4px 微步），尺度 4·8·12·16·20·24·32·40·64px。圆角默认肥大：输入 8px、按钮 8px、卡片 16px、模态框 24px、头像 50%。

**记忆点**：Blurple #5865f2 在深色表面上发光 + gg sans 圆润字体 + 肥大圆角 + 音调分层代替阴影。

## CSS Token（可直接复现）

```
/* Discord — 可复现设计系统 Token */

/* 字体 */
--font-display: 'gg sans', 'Noto Sans', 'Helvetica Neue', sans-serif;
--font-body: 'gg sans', 'Noto Sans', 'Helvetica Neue', sans-serif;

/* 字号 */
--fs-display: 3.5rem;      /* 56px */
--fs-h1: 2.5rem;           /* 40px */
--fs-h2: 1.75rem;          /* 28px */
--fs-title: 1.25rem;       /* 20px */
--fs-body: 1rem;           /* 16px */
--fs-body-sm: 0.875rem;    /* 14px */
--fs-label: 0.75rem;       /* 12px */
--fw-regular: 400;
--fw-medium: 500;
--fw-semibold: 600;
--fw-bold: 700;

/* 色彩 — 暗色默认 */
--discord-blurple: #5865F2;
--discord-blurple-active: #4752C4;
--discord-bg: #313338;
--discord-bg-deep: #1E1F22;
--discord-bg-mid: #2B2D31;
--discord-bg-light: #383A40;
--discord-fg: #DBDEE1;
--discord-muted: #949BA4;
--discord-placeholder: #80848E;
--discord-border: #3F4147;
--discord-success: #23A559;
--discord-warning: #F0B232;
--discord-destructive: #DA373C;

/* 间距 — 8px 基准 */
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-5: 20px;
--space-6: 24px;
--space-8: 32px;
--space-10: 40px;
--space-16: 64px;

/* 圆角 — 肥大默认 */
--radius-input: 8px;
--radius-button: 8px;
--radius-card: 16px;
--radius-modal: 24px;
--radius-avatar: 50%;
--radius-squircle: 16px;

/* 阴影 — 罕见，仅弹出层 */
--shadow-popover: 0 8px 16px rgba(0,0,0,0.24);

/* 动效 */
--motion-hover: 150ms ease;
--motion-enter: 250ms ease;

/* 记忆点：#5865F2 Blurple 在深色表面发光 + gg sans + 肥大圆角 */
/* 应用方式：body 背景 #313338，侧边栏 #1E1F22，CTA #5865F2，卡片圆角 16px */
```
