# 23. YouTube — 二十年后的动态表达

> **类型**：软件 | **领域**：视频流媒体 | **设计哲学**：Motion-First Identity, Expressive Flexibility

| 规格总览 | 值 |
|---|---|
| 画布色 | `#0F0F0F` |
| 强调色 | `#FF0000` 红 |
| 字体策略 | YouTube Display |
| 记忆点 | 红到品红渐变 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## 设计规格（定本原文）

**领域标签**：视频流媒体 | **设计哲学**：Motion-First Identity, Expressive Flexibility

YouTube 在 2025 年 20 周年之际进行了品牌刷新，核心变化是引入动态身份。标志性红黑白配色和播放按钮语言保留，但新增了红到品红的渐变用于平台表达，以及与 Sharp Type 合作开发的 YouTube Display 展示字体，基于 Logo 几何结构，支持九种全球文字系统。

**色彩**：YouTube Red `#FF0000` 或更新后的红调，搭配黑 `#0F0F0F` 和白 `#FFFFFF`。新渐变从红到品红（`#FF0000` → `#E91E8C`）用于品牌表达区域。界面以暗色为主（`#0F0F0F`），内容（缩略图）提供色彩。

**字体**：YouTube Display（Sharp Type 定制）用于标题和品牌表达，基于 Logo 几何结构。正文使用 Roboto 或 YouTube Sans。标题粗重有力，支持九种全球文字系统。

**间距**：视频卡片网格间距 16px，区块间距 32–48px。暗色界面下间距需要更慷慨以创造呼吸感。

**记忆点**：红到品红渐变 + YouTube Display 几何字体 + 播放按钮语言。

## CSS Token（可直接复现）

```
/* YouTube — 可复现设计系统 Token */

/* 字体 */
--font-display: 'YouTube Display', 'YouTube Sans', sans-serif;
--font-body: 'YouTube Sans', 'Roboto', sans-serif;

/* 字号 */
--fs-display: clamp(2rem, 4vw, 3rem);
--fs-title: clamp(1.125rem, 2vw, 1.5rem);
--fs-body: 0.875rem;
--fs-note: 0.75rem;
--fw-regular: 400;
--fw-medium: 500;
--fw-bold: 700;

/* 色彩 */
--yt-red: #FF0000;
--yt-red-hover: #CC0000;
--yt-gradient-start: #FF0000;
--yt-gradient-end: #E91E8C;
--yt-black: #0F0F0F;
--yt-dark: #212121;
--yt-white: #FFFFFF;
--yt-gray-500: #AAAAAA;
--yt-gray-700: #717171;

/* 间距 */
--space-xs: 4px;
--space-sm: 8px;
--space-md: 16px;
--space-lg: 24px;
--space-xl: 32px;
--space-2xl: 48px;

/* 圆角 */
--radius-sm: 4px;
--radius-md: 8px;
--radius-lg: 12px;

/* 动效 */
--motion-hover: 150ms ease-out;
--motion-enter: 300ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：红到品红渐变 + YouTube Display 几何字体 */
/* 应用方式：品牌区域使用红-品红渐变，标题用 YouTube Display */
```
