# 40. LinkedIn — 专业网络 信任蓝

> **类型**：软件 | **领域**：职业社交 | **设计哲学**：专业、可信、克制的中性蓝

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / `#F3F2EF` 灰 |
| 强调色 | `#0A66C2` LinkedIn蓝 |
| 字体策略 | 系统字体栈 + 数字可变字体 |
| 记忆点 | 方切（2px）按钮 + 单栏专注阅读 |

## HTML 板块 · 官网与营销页

### 设计哲学

LinkedIn 官网把"职业信任"翻译成克制的蓝白语言：深蓝标题、灰底卡片、极少装饰。页面焦点永远是"行动"——登录、注册、发布职位。营销页保留大量空白，用真实人物照片建立信任而非插画。整体气质像一本装帧严谨的商业刊物：不需要惊艳，需要可靠。

### 色彩

主画布白 `#FFFFFF`，次级画布灰 `#F3F2EF`；品牌蓝 `#0A66C2` 用于 CTA、链接与图标，深蓝 `#004182` 用于页脚与强调标题；文字石墨 `#000000`/`#666666`，辅助灰 `#8C8C8C`。成功绿 `#057642` 仅用于增值显示。

### 字体

主体使用系统字体栈（`-apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif`）；新品牌数字展示用可变字体（Lab Grotesque 风格）——标题 28–56px 中等字重，正文 16px Regular；中文回落 PingFang SC / Microsoft YaHei。

### 布局、间距、圆角与动效

内容宽度 1128px 居中；区块纵向 56–88px；卡片 8–12px 圆角、1px 边框 `#E0DFDC`，**主 CTA 按钮接近直角 2px**（"专业、利落"的视觉签名）；悬停 200ms 轻微抬升 + 边框加深；hero 常为左文右图 6:4 分栏。

### HTML CSS Token

```css
/* LinkedIn — HTML 官网 Token */
--li-blue: #0A66C2;
--li-blue-dark: #004182;
--li-bg: #FFFFFF;
--li-bg-alt: #F3F2EF;
--li-text: #000000;
--li-text-alt: #666666;
--li-text-subtle: #8C8C8C;
--li-green: #057642;
--li-line: #E0DFDC;
--li-radius-btn: 2px;
--li-radius-card: 8px;
--li-radius-modal: 12px;
--li-font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", "PingFang SC", "Microsoft YaHei", sans-serif;
--li-space-section: 64px;
--li-container: 1128px;
--li-ease: ease; --li-motion: 200ms var(--li-ease);
/* 应用：Primary CTA 用 2px 直角蓝按钮，卡片灰底白卡双层给层级 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品界面是高密度 B2B 信息架构的范本：导航、feed、右侧"你可能认识的人"模块都整齐列队，颜色在界面中退位，靠字体字重与间距建立秩序。整体传达"这是工作的地方"——稳定、直接、不打扰。

### 色彩（组件与语义 Token）

主行动蓝 `#0A66C2`（关注、连接、消息）；危险/取消灰 `#666666`；成功 `#057642` 用于认证徽章。表面层级：白 → 灰 `#F3F2EF` → 更浅 `#F9F9F9`；描边 `#E0DFDC`；正文近黑 `#191919`、次要 `#00000099`（60% 透明度语义色）。

### 字体

界面 14–16px；导航 14px；标题 20–24px SemiBold；数字（职位数、连接数）用 Semibold + tabular。行高 1.33–1.5。中文界面全站 PingFang SC / Microsoft YaHei 15px。

### 布局、间距、圆角与动效

主列 780px + 右栏 320px；feed 卡片 12px 圆角、白底、1px 描边、24px padding；头像 40–56px 圆形；按钮主 2px 直角、次级 12px 圆角；tab 下划线指示器 2px 蓝。动效 150–250ms，hover 用底色变化 + 下划线，避免弹跳与缩放。

### UI/UX CSS Token

```css
/* LinkedIn — UI/UX Token（产品界面） */
--li-ui-bg: #F3F2EF;
--li-ui-surface: #FFFFFF;
--li-ui-surface-2: #F9F9F9;
--li-ui-line: #E0DFDC;
--li-ui-text: #191919;
--li-ui-text-subtle: rgba(0, 0, 0, 0.6);
--li-ui-accent: #0A66C2;
--li-ui-accent-hover: #004182;
--li-ui-success: #057642;
--li-radius-card: 12px;
--li-radius-btn: 2px;
--li-nav-h: 52px;
--li-font-ui: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
--li-motion: 200ms ease;
/* 应用：feed 卡片白底 + 细描边，行距 24px；主要行动始终 2px 直角蓝按钮 */
```

## 记忆点与应用方式

复现"LinkedIn 感"三步：①灰 `#F3F2EF` 页面底 + 白卡片 + 1px 描边；②单一职业蓝 `#0A66C2` 做全部行动；③主 CTA 用 2px 直角蓝按钮（这是区别于其他社交平台的签名）。人物卡片头像圆形、无彩色渐变。

## 反混搭提示

LinkedIn 拒绝大圆角玩具感（主按钮 2px）、拒绝渐变与玻璃拟态、拒绝插画 hero——它的信任感来自"灰底白卡 + 直角蓝钮"的工程感。不要用 LinkedIn 蓝做霓虹/发光效果，不要给头像加故事渐变色环。
