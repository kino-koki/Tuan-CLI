# 34. OpenAI — 白色画布上的克制绿点

> **类型**：软件 | **领域**：AI研究 | **设计哲学**：Clarity, Scale, Deference

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 纯白 |
| 强调色 | `#10A37F` 品牌绿 |
| 字体策略 | 简洁无衬线 |
| 记忆点 | 克制的白绿双色 + 光学晕 hero |

## HTML 板块 · 官网与营销页

### 设计哲学

OpenAI 官网以白/黑双模式极简呈现"AI 研究的庄重与前沿"：超大无衬线标题、模块化网格、克制色板；品牌绿 `#10A37F` 只出现在 logo 与极少量强调处（研究站标注），hero 常用黑色背景 + 蓝紫/青光学晕表达"模型之光"。设计气质像研究机构而非消费品牌：**安静、宏大、可证明**。

### 色彩

白 `#FFFFFF` 与近黑 `#0D0D0D` 双画布；品牌绿 `#10A37F`（历史）/ 新中性灰黑 logo；文字 `#0D0D0D`、次要 `#6E6E6E`；边框 `#E5E5E5`；hero 光学晕用蓝 `#3B82F6`、紫 `#8B5CF6`、青 `#22D3EE` 低透明度扩散。

### 字体

无衬线系统栈（`-apple-system, 'Segoe UI', Roboto`）——展示用 SemiBold 大标题；代码 `ui-monospace`。卡片标题 20–32px、正文 16–18px。

### 布局、间距、圆角与动效

12 列栅格；hero 96–128px；卡片圆角 16–24px、按钮胶囊；进场 400ms `cubic-bezier(0.16,1,0.3,1)` fade+slide；hover 150ms。



### HTML CSS Token

```css
/* OpenAI — HTML 官网 Token */
--oa-bg: #FFFFFF;
--oa-bg-dark: #0D0D0D;
--oa-ink: #0D0D0D;
--oa-green: #10A37F;
--oa-green-dark: #0E8A6D;
--oa-muted: #6E6E6E;
--oa-border: #E5E5E5;
--gradient-aura:
  radial-gradient(ellipse at 25% 20%, rgba(59,130,246,0.22), transparent 55%),
  radial-gradient(ellipse at 75% 35%, rgba(139,92,246,0.18), transparent 50%),
  radial-gradient(ellipse at 55% 80%, rgba(34,211,238,0.14), transparent 55%);
--font-display: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
--font-body: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
--font-mono: ui-monospace, 'SF Mono', SFMono-Regular, monospace;
--radius-card: 16px;
--radius-pill: 9999px;
--space-section: 96px;
--motion-enter: 400ms cubic-bezier(0.16, 1, 0.3, 1);
/* 应用：白/黑二选一画布，绿仅 logo/轻度强调，暗 hero 用光学晕 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

ChatGPT 等产品界面"对话优先"：输入框是主舞台，模型输出是英雄；界面用大量灰阶表面与极简 chrome 让文本呼吸，气泡感弱化（用户与助手消息用浅层区分而非重描边）。AI 状态用点级指示（生成中、思考中），动效表现为流式渲染与轻量 shimmer，不打断阅读。

### 色彩（组件与语义 Token）

亮色：页面 `#FFFFFF`、助手消息 `#F9F9F9`、用户消息浅绿容器 `#E6F4F1`（新品渐变到更中性）、文字 `#0D0D0D`、次要 `#6E6E6E`、边框 `#E5E5E5`、accent 绿 `#10A37F`（仅品牌/状态）。深色：侧栏 `#171717`、内容区 `#212121`、文字 `#ECECEC`。

### 字体

系统无衬线栈；对话正文 16px、代码 14px mono；标题 20–32px SemiBold。

### 布局、间距、圆角与动效

消息流 24px 呼吸；侧栏 16px；输入框 24px 胶囊（含附件区）；卡片 12–16px；浮层右侧面板用于工具/历史。动效 150–250ms ease-out；打字等待用 shimmer 而非旋转。



### UI/UX CSS Token

```css
/* OpenAI — UI/UX Token（ChatGPT 产品） */
--chat-bg: #FFFFFF;
--chat-bg-dark: #212121;
--chat-sidebar-dark: #171717;
--chat-assistant: #F9F9F9;
--chat-user: #E6F4F1;
--chat-text: #0D0D0D;
--chat-text-dark: #ECECEC;
--chat-text-secondary: #6E6E6E;
--chat-border: #E5E5E5;
--chat-accent: #10A37F;
--chat-radius-input: 24px;
--chat-radius-card: 16px;
--font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
--font-mono: ui-monospace, 'SF Mono', monospace;
--motion: 200ms ease-out;
--shimmer: linear-gradient(90deg, transparent, rgba(255,255,255,0.4), transparent);
/* 应用：深色模式侧栏 #171717、内容区 #212121；消息用浅层背景区分而非描边 */
```

## 记忆点与应用方式

复现"OpenAI 感"：①大排版：32px+ 标题 + 96px 区块留白；②白/黑画布二选一，绿 `#10A37F` 永远小而准；③暗 hero 用低透明度蓝紫光学晕，位置靠边缘；④对话产品：输入胶囊 + 助手/用户浅层背景 + 流式渲染。

## 反混搭提示

OpenAI 绿不用作大面积 CTA 背景（克制是记忆点）。暗色别照搬 Spotify/Linear 的多级色层——OpenAI 就两层（侧栏一次）；勿把消息做成粗描边气泡。
