# 45. Substack — 订阅出版 信件橙

> **类型**：软件 | **领域**：内容发布平台 | **设计哲学**："一封值得打开的信"

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / `#111111` 黑 |
| 强调色 | `#FF6719` Substack橙 |
| 字体策略 | 衬线正文 + 系统无衬线 UI |
| 记忆点 | 橙点/橙字 + 信件式排版 |

## HTML 板块 · 官网与营销页

### 设计哲学

Substack 官网与创作后台统一采用"出版物即品牌"的思想：页面克制的像一张信纸，无插画、无渐变，只有衬线标题、直白文字与一个橙色入口。品牌橙 `#FF6719` 作为唯一的"行动色"，配合黑/白双画布，传达**独立作者、直接订阅**的手艺感。营销页靠"创作者名单 + 大字标题"建立信任。

### 色彩

画布白 `#FFFFFF`（亮）/黑 `#111111`（暗，编辑器默认）；文字近黑 `#1F1F1F`/白；强调橙 `#FF6719`（订阅按钮、logo 圆点、链接悬停）、hover 深橙 `#E85D14`；辅助灰 `#6F6F6F`、`#8A8A8A`；分割线 `#E8E8E8`/`#2A2A2A`。

### 字体

文章正文与营销标题多用衬线（如 `Georgia`/编辑器内置排版），UI 用系统栈 `-apple-system, "Segoe UI", Roboto, sans-serif`；标题 28–48px Bold；中文正文回落宋体（Songti SC/SimSun），界面 PingFang SC/Microsoft YaHei。**字重、大小即层级，不得靠彩色堆视觉**。

### 布局、间距、圆角与动效

阅读列 600–680px 居中；区块间距 48–96px；按钮胶囊（9999px，高 40–44px）；编辑状态使用 8px 小圆角输入框；卡片可有可无（多用无边框列表）；动效 150–250ms，hover 多为橙字或下划线；禁重动画。

### HTML CSS Token

```css
/* Substack — HTML 官网 Token */
--ss-orange: #FF6719;
--ss-orange-hover: #E85D14;
--ss-bg: #FFFFFF;
--ss-bg-dark: #111111;
--ss-text: #1F1F1F;
--ss-text-subtle: #6F6F6F;
--ss-line: #E8E8E8;
--ss-line-dark: #2A2A2A;
--ss-read-w: 640px;
--ss-radius-pill: 9999px;
--ss-font-serif: Georgia, 'Times New Roman', 'Songti SC', 'SimSun', serif;
--ss-font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--ss-motion: 200ms ease;
/* 应用：主 CTA 橙色胶囊按钮；正文衬线 1.65 行高；标志性"橙点"可做列表 marker */
```

## UI/UX 板块 · 产品界面

### 设计哲学

编辑器与订阅页把"写作工具"做成出版物：正文区宽 660px、居中、衬线排版，工具栏极简；订阅弹出层与评论区保持纸张气质。整体是一种"安静的生产力"——没有仪表盘式花哨组件，所有 UI 都退到文字后面，橙色只出现在订阅/付费行为。

### 色彩（组件与语义 Token）

语义：橙 `#FF6719` = 订阅、付费、主行动；编辑蓝 `#0F766E`（链接，编辑器中链接默认绿蓝）按需；成功 `#22C55E`（已订阅）；危险灰红 `#D13438`；表面：白 → `#F7F5F2`（浅米，附件卡）→ `#FAFAFA` hover；描边 `#E8E8E8`；文字 `#1F1F1F`/`#6F6F6F`。

### 字体

正文 16–18px/1.65 衬线；标题 22–32px；UI 按钮 14–15px 无衬线 SemiBold；代码 14px 等宽。中文出版物正文 16–18px 宋体。

### 布局、间距、圆角与动效

正文列 660px；工具栏 48px、sticky；段落 24px；引用左边线 4px 灰；评论区头像 40px 圆形、回复按钮 24px 胶囊；订阅卡片 8px 圆角 + 1px 描边。动效：评论展开 200ms ease、订阅弹窗 250ms fade+scale，禁用拖拽类重动画。

### UI/UX CSS Token

```css
/* Substack — UI/UX Token（编辑器 / 订阅页） */
--ss-ui-bg: #FFFFFF;
--ss-ui-bg-warm: #F7F5F2;
--ss-ui-hover: #FAFAFA;
--ss-ui-text: #1F1F1F;
--ss-ui-text-subtle: #6F6F6F;
--ss-ui-line: #E8E8E8;
--ss-ui-orange: #FF6719;
--ss-ui-success: #22C55E;
--ss-ui-danger: #D13438;
--ss-read-w: 660px;
--ss-radius-btn: 9999px;
--ss-radius-card: 8px;
--ss-font-serif-ui: Georgia, 'Times New Roman', 'Songti SC', 'SimSun', serif;
--ss-font-sans-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--ss-motion: 200ms ease;
/* 应用：编辑区衬线 1.65；订阅/付费入口必须橙色胶囊 */
```

## 记忆点与应用方式

复现"Substack 感"三步：①白/黑画布 + 衬线标题 + 640px 阅读列；②唯一强调色橙 `#FF6719`，只做订阅/主行动；③无插画无渐变，杂志版面靠字重与留白。做"订阅、邮件、出版、创作者"类页面时直接参考。

## 反混搭提示

Substack 拒绝过度组件化——不要给页面加彩色图标矩阵、不要用渐变 hero、不要做玻璃拟态。橙 `#FF6719` 是大面积禁区（只用于按钮/链接/点）；暗色模式必须用 `#111111` 而非蓝黑。
