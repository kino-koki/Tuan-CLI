# 42. Instagram — 视觉社区 渐变品牌

> **类型**：软件 | **领域**：社交平台 | **设计哲学**：让照片说话的多彩方框

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / `#000000` 暗 |
| 强调色 | 品牌渐变（金→粉→紫） |
| 字体策略 | Instagram Sans / 系统字体栈 |
| 记忆点 | 圆角图标 + 品牌渐变只做点缀 |

## HTML 板块 · 官网与营销页

### 设计哲学

Instagram 官网与产品共享同一套视觉语法：巨大的方形内容框、圆角头像、克制的中性 UI，品牌彩虹渐变（黄橙→粉→紫）只出现在 logo、Story 光环与营销插画节点，绝不铺满。产品页以"全屏照片墙 + 少量文案"呈现，让作品成为明星。

### 色彩

亮色画布白 `#FFFFFF`、暗色黑 `#000000`；界面主强调为品牌渐变 `linear-gradient(45deg, #F58529, #DD2A7B, #8134AF)`（发帖、品牌资产）；UI 用蓝 `#0095F6` 做链接与"关注"按钮；文字 `#000000`/`#737373`；分割线 `#DBDBDB`。

### 字体

Instagram Sans（2024 品牌字体，展示用，几何无衬线）；产品 UI 回退系统栈 `-apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`；标题 28–48px，正文 15–16px；中文回落 PingFang SC / Microsoft YaHei。

### 布局、间距、圆角与动效

营销 hero 常为中心 340–540px 方形手机框架 + 侧边文字；栅格 3–5 列照片墙；头像 32–150px 圆形、Story 光环用渐变 ring；按钮 8px 圆角（蓝")或"白底描边"两种；动效 200–300ms，hover 轻放大图片。

### HTML CSS Token

```css
/* Instagram — HTML 官网 Token */
--ig-gradient: linear-gradient(45deg, #F58529, #DD2A7B, #8134AF);
--ig-blue: #0095F6;
--ig-bg: #FFFFFF;
--ig-bg-dark: #000000;
--ig-text: #000000;
--ig-text-subtle: #737373;
--ig-line: #DBDBDB;
--ig-radius-photo: 8px;
--ig-radius-btn: 8px;
--ig-radius-avatar: 9999px;
--ig-font: Instagram Sans, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
--ig-star-ring: conic-gradient(from 210deg, #FEDA75, #FA7E1E, #D62976, #962FBF, #4F5BD5);
--ig-motion: 250ms ease;
/* 应用：品牌渐变只用于 logo/Story 环/发帖图标；照片 8px 圆角，蓝 #0095F6 做关注按钮 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品界面以"内容即 UI"闻名：白色卡片式 feed、顶部 Story 渐变环、底部 5 图标导航，视觉上几乎无装饰——照片负责色彩，UI 负责秩序。暗色模式保持同构：黑底、白圆头像、蓝关注钮。

### 色彩（组件与语义 Token）

语义：关注蓝 `#0095F6`、已关注灰 `#EFEFEF` 按钮、私信蓝 `#0095F6`、直播红点 `#ED4956`、链接蓝 `#00376B`（暗色 `#E0F1FF`）；表面：白 → `#FAFAFA` 灰 → `#EFEFEF` 浅灰；描边 `#DBDBDB`；遮罩 `rgba(0,0,0,0.65)`。

### 字体

feed 用户名 14px SemiBold；正文 14px；标题 16–20px；使用系统栈保证多语言。数字（点赞数）用 Impact 风格大字仅限短视频封面区；常规 UI 一律无衬线。

### 布局、间距、圆角与动效

feed 卡片宽 470px 居中；卡片内 4–8px padding；头像 32/56px 圆形；Action 行 40px 高、图标 24px；弹窗 12px 圆角。动效：点赞 heart 200ms 缩放、Story 打开 300ms slide-up、stagger 150ms。tab bar 图标 4px hover 圆角底。

### UI/UX CSS Token

```css
/* Instagram — UI/UX Token（产品界面） */
--ig-ui-bg: #FFFFFF;
--ig-ui-bg-alt: #FAFAFA;
--ig-ui-surface: #FFFFFF;
--ig-ui-line: #DBDBDB;
--ig-ui-text: #000000;
--ig-ui-text-subtle: #737373;
--ig-ui-accent: #0095F6;
--ig-ui-alert: #ED4956;
--ig-radius-photo: 8px;
--ig-radius-btn: 8px;
--ig-feed-w: 470px;
--ig-story-ring: conic-gradient(from 210deg, #FEDA75, #FA7E1E, #D62976, #962FBF, #4F5BD5);
--ig-font-ui: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
--ig-motion: 250ms ease;
/* 应用：feed 470px 卡片居中、照片 8px 圆角、Story 环渐变必须用 conic-gradient */
```

## 记忆点与应用方式

复现"Instagram 感"三步：①白/黑单一画布 + 照片全出血展示；②品牌金粉紫渐变只用于 logo、Story 环、发帖图标；③关注按钮蓝 `#0095F6`、界面其余零彩色。方形照片 + 8px 圆角 + 大留白即可成立。

## 反混搭提示

Instagram 渐变是最容易被滥用的资产——它是"品牌光环"不是"页面背景"，禁止铺成 hero 渐变底或按钮填充。UI 中不要再用第二强调色；不要给卡片加粗边框，Instagram 用间距和底色分层。
