# 68. Perplexity — AI 搜索 智慧青

> **类型**：软件 | **领域**：AI 搜索引擎 | **设计哲学**：让回答来源可见的信赖感

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / 青黑 `#16262E` |
| 强调色 | `#20808D` Perplexity青 |
| 字体策略 | Perplexity Sans + 系统栈 |
| 记忆点 | 青 #20808D + 引用来源卡片 |

## HTML 板块 · 官网与营销页

### 设计哲学

Perplexity 官网（2025 品牌重塑后）用"智慧青" `#20808D` 建立全新识别：青黑 hero + 白色搜索框 + 圆润卡片；品牌字 Perplexity Sans 圆润带衬感。设计语言**清晰、可信、适度未来**——强调"答案有来源"：每个结果配来源卡（数字引文）。营销页以搜索 UI 演示 + 引用网格为主。

### 色彩

画布白 `#FFFFFF`、青黑 `#16262E`（暗段）、浅青灰 `#F0F5F6`；主强调青 `#20808D`（logo、CTA、链接、选中）、hover `#176570`；文字 `#111111`/白、灰 `#5F6B76`；来源卡描边 `#DCE4E6`；成功绿 `#2FA866`。

### 字体

Perplexity Sans / 系统栈 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`；标题 36–64px SemiBold；搜索答案正文 16–17px/1.6；中文 PingFang SC / Microsoft YaHei。

### 布局、间距、圆角与动效

内容 1180px；区块 64–112px；卡片 12–16px 圆角、1px 描边；按钮 8px（青实心/黑实心）；hero 青黑段 + 巨型搜索框（48px 胶囊）；动效 200–300ms、结果 stagger 20ms。

### HTML CSS Token

```css
/* Perplexity — HTML 官网 Token */
--ppx-teal: #20808D;
--ppx-teal-hover: #176570;
--ppx-teal-soft: #E4F0F2;
--ppx-bg: #FFFFFF;
--ppx-bg-dark: #16262E;
--ppx-bg-gray: #F0F5F6;
--ppx-text: #111111;
--ppx-text-subtle: #5F6B76;
--ppx-line: #DCE4E6;
--ppx-success: #2FA866;
--ppx-radius-card: 14px;
--ppx-radius-btn: 8px;
--ppx-radius-search: 9999px;
--ppx-font: 'Perplexity Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--ppx-space-section: 88px;
--ppx-motion: 250ms ease;
/* 应用：主 CTA 青实心；hero 青黑底 + 白色胶囊搜索框 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品界面（问答页）是"搜索 + 对话"的融合：顶部搜索栏、左侧来源列表、右侧回答流；数字引文（[1][2]）贯穿全文，来源卡 hover 高亮。青色只做品牌、链接与当前答案高亮，阅读区白底黑字。设计目标：**答案可验证**——UI 让读者随时跳去原始来源。

### 色彩（组件与语义 Token）

青 `#20808D` = 品牌/链接/引文高亮/主行动；中性面白/`#F0F5F6`/hover `#E9F1F2`；描边 `#D6E0E2`；文字 `#111111`/`#5F6B76`；引用角标灰底 → hover 青底白字；成功绿 `#2FA866`（答案可用）；危险红 `#D64545`。

### 字体

回答正文 16px/1.65；来源标题 14px Medium；引用数字 13px tabular；侧栏建议 14px。中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

左来源列 320px（sticky）；右回答流 680px；搜索 52px 胶囊；引文角标 18px 圆 6px；来源卡 12px 圆角。动效：回答流 300ms 渐入、引文 hover 200ms、重新生成 400ms shimmer。

### UI/UX CSS Token

```css
/* Perplexity — UI/UX Token（问答界面） */
--ppx-ui-teal: #20808D;
--ppx-ui-bg: #FFFFFF;
--ppx-ui-bg-2: #F0F5F6;
--ppx-ui-hover: #E9F1F2;
--ppx-ui-line: #D6E0E2;
--ppx-ui-text: #111111;
--ppx-ui-text-subtle: #5F6B76;
--ppx-ui-success: #2FA866;
--ppx-ui-danger: #D64545;
--ppx-cited-badge: 18px;
--ppx-answer-w: 680px;
--ppx-radius-card: 12px;
--ppx-radius-search: 9999px;
--ppx-font-ui: 'Perplexity Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--ppx-motion: 250ms ease;
/* 应用：引文 [1] 编号角标；来源列表 hover 高亮对应答案段落 */
```

## 记忆点与应用方式

复现"Perplexity 感"三步：①智慧青 `#20808D` + 白/青黑双画布；②巨型胶囊搜索框 + 数字引文贯穿回答；③来源卡 12px 圆角 1px 描边。做"AI 搜索、知识问答、LLM 产品"类页面首选。

## 反混搭提示

Perplexity 青不是霓虹青（区别于 TikTok 青）——保持温润、偏灰的 `#20808D`；不要大面积渐变；答案页必须保持高可读白底与引文体系，别把搜索工具做成纯对话聊天窗。
