# 30. Google — Material Design 3

> **类型**：软件 | **领域**：互联网平台 | **设计哲学**：Inclusive, Expressive, Adaptive

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 浅色 |
| 强调色 | `#0B57D0` Material蓝 |
| 字体策略 | Roboto / Google Sans |
| 记忆点 | Material 3 动态圆角 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## HTML 板块 · 官网与营销页

### 设计哲学

Google 的营销官网（design.google、about.google、Workspace 产品页）以白底 + 红黄蓝绿四色为"品牌底色"，但始终保持大面留白：四色只做 logo、图标与装饰节点，绝不铺满。产品页采用 Material 3 风格——白色卡片、20px 大圆角、M3 动态色彩，传达"智能、友好、无处不在"。核心是包容性：色彩与字体都追求在全设备、全文化、全语言下的可读。

### 色彩

主画布白 `#FFFFFF`，文本近黑 `#202124`（旧）/ `#1C1B1F`（M3）；Google Blue `#0B57D0` 为交互强调（链接、CTA、焦点）；品牌四色红 `#EA4335`、黄 `#FBBC04`、绿 `#34A853` 仅作 logo/图标/细节点缀；辅助灰 `#5F6368`。

### 字体

Google Sans / Product Sans 用于展示，Roboto 用于正文；Android 生态字体 Roboto Flex。标题常用 Medium/SemiBold，正文 Regular。

### 布局、间距、圆角与动效

8dp 栅格；hero 区块 96–128px 大留白，内容区块 64–96px；卡片 20px 大圆角、按钮胶囊；动效 300ms standard/emphasized easing；hover 轻微提升。网格渐晕（四色彩晕）只允许出现在 hero 背景。



### HTML CSS Token

```css
/* Google — HTML 官网 Token（M3 营销页） */
--g-blue: #0B57D0;
--g-blue-hover: #0842A0;
--g-red: #EA4335;
--g-yellow: #FBBC04;
--g-green: #34A853;
--g-bg: #FFFFFF;
--g-on-surface: #1C1B1F;
--g-text-secondary: #5F6368;
--g-outline: #747775;
--gradient-rainbow: linear-gradient(90deg, #4285F4, #EA4335, #FBBC04, #34A853);
--radius-card: 20px;
--radius-pill: 9999px;
--font-display: 'Google Sans', 'Product Sans', 'Roboto', sans-serif;
--font-body: 'Roboto', system-ui, sans-serif;
--space-section: 96px;
--motion-standard: 300ms cubic-bezier(0.2, 0, 0, 1);
/* 应用：白底黑字为主，#0B57D0 做交互，四色只做节点/图标，勿大面积填充 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

Material Design 3（M3）以"动态色彩"为核心——从壁纸提取 tonal palette 自动生成主题；四大 token 分类 Color / Type / Shape / Motion；可访问性内建：正文对比度 ≥ 4.5:1，触控目标 ≥ 48dp。产品界面（Gmail、Drive、Android）强调"包容、表现、自适应"。

### 色彩（组件与语义 Token）

明色主题：primary `#0B57D0`、onPrimary `#FFFFFF`、primaryContainer `#D3E3FD`、onPrimaryContainer `#041E49`；secondary `#625B71`、secondaryContainer `#E8DEF8`；tertiary `#7D5260`；surface `#FEF7FF`、surfaceContainer `#F3EDF7`、background `#FDF7FF`；error `#B3261E`；outline `#79747E`。暗色主题 primary `#A8C7FA`、surface `#141218`。

### 字体

Roboto / Roboto Flex；M3 Type Scale 共 15 级（display → label），展示标题用 Large/Medium，正文 bodyLarge 16px，标注 labelLarge 14px。

### 布局、间距、圆角与动效

8dp 栅格；组件内 4–8dp，区块 24–64dp。M3 Shape Scale：extra small 4、small 8、medium 12、large 16、extra large 28、full；按钮默认全胶囊。动效 standard easing `cubic-bezier(0.2,0,0,1)`（300ms）、emphasized（400ms）。按钮四态：filled（primary 底）、tonal（primaryContainer 底）、outlined、text。



### UI/UX CSS Token

```css
/* Google — UI/UX Token（Material Design 3 亮色） */
--md-primary: #0B57D0;
--md-on-primary: #FFFFFF;
--md-primary-container: #D3E3FD;
--md-on-primary-container: #041E49;
--md-secondary: #625B71;
--md-secondary-container: #E8DEF8;
--md-tertiary: #7D5260;
--md-surface: #FEF7FF;
--md-surface-container: #F3EDF7;
--md-surface-container-high: #ECE6F0;
--md-background: #FDF7FF;
--md-error: #B3261E;
--md-outline: #79747E;
--md-outline-variant: #CAC4D0;
--md-radius-s: 4px;
--md-radius-m: 12px;
--md-radius-l: 16px;
--md-radius-xl: 28px;
--md-radius-full: 9999px;
--md-space-1: 4px; --md-space-2: 8px; --md-space-4: 16px;
--md-space-8: 32px; --md-space-12: 48px;
--md-font: 'Roboto', system-ui, sans-serif;
--md-easing-standard: cubic-bezier(0.2, 0, 0, 1);
--md-motion-300: 300ms var(--md-easing-standard);
/* 应用：surface 为页底，primary 做 filled 按钮，tonal 用 primaryContainer，错误统一 #B3261E */
```

## 记忆点与应用方式

复现"Google 感"的三步：①白底 + 近黑文字 + 8dp 栅格；②`#0B57D0` 单一蓝色做全部交互；③卡片与按钮大圆角（20px/胶囊），四色只出现在 logo、图标、进度与 hero 色彩节点。营销页允许 300ms 缓和入场，产品页动效更轻（200ms 内）。

## 反混搭提示

Google 四色是"小结点"语言——若大面积四色填充 + 霓虹渐变即是偏离。勿把 M3 tonal 容器色（primaryContainer）当装饰色铺满卡片；勿用 Google 蓝做暗色 hero 渐变（那是 OpenAI/Framer 的领域）。
