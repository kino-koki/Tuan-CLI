# 66. Supabase — 开源数据库 生态绿

> **类型**：软件 | **领域**：开发者平台（开源 BaaS） | **设计哲学**：开源、快乐、亲开发者的专业

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / 深墨 `#1C1C1C` |
| 强调色 | `#3ECF8E` Supabase绿 |
| 字体策略 | 系统栈（展示可几何无衬线） |
| 记忆点 | 绿 #3ECF8E + 代码/终端氛围 |

## HTML 板块 · 官网与营销页

### 设计哲学

Supabase 官网是"开源开发者工具"的审美代表：深墨 hero + 亮绿 `#3ECF8E` 品牌色 + 强调代码片段；亮色段白底黑字。设计语言**直接、极客、略带玩心**（吉祥物小恐龙、终端风、过大 typorgraphy）。营销页以"代码示例 + 数据表 + 架构图"为主，绿色只做 CTA、logo 与高亮符号。

### 色彩

画布白 `#FFFFFF`、深墨 `#1C1C1C`（dark 段）、浅灰 `#F7F8F8`；主强调绿 `#3ECF8E`（CTA、链接、代码高亮）、hover `#2FBF7D`；文字 `#191919`/白、灰 `#5E666E`；Ruby 粉 `#D9853B` 系仅代码语法高亮；分割线 `#E8EAED`。

### 字体

系统栈 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`；标题 36–72px SemiBold；代码 14px `ui-monospace`；终端块墨底白字；中文 PingFang SC / Microsoft YaHei。

### 布局、间距、圆角与动效

内容 1180px；区块 72–128px；卡片 12px 圆角、1px 描边、hover 上浮；按钮 8px（绿实心/墨实心，**禁用胶囊**）；代码块 8px 圆角墨底；hero 常为墨底大字 + 终端动画；动效 200–300ms。

### HTML CSS Token

```css
/* Supabase — HTML 官网 Token */
--su-green: #3ECF8E;
--su-green-hover: #2FBF7D;
--su-green-soft: #E2F9EE;
--su-bg: #FFFFFF;
--su-bg-dark: #1C1C1C;
--su-bg-gray: #F7F8F8;
--su-text: #191919;
--su-text-subtle: #5E666E;
--su-line: #E8EAED;
--su-radius-card: 12px;
--su-radius-btn: 8px;
--su-font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--su-font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
--su-space-section: 96px;
--su-motion: 250ms ease;
/* 应用：主 CTA 绿实心；代码/终端块墨底 8px 圆角；hero 墨底大字 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品界面（dashboard、SQL 编辑器、Auth 面板）深色为主：`#1C1C1C` 底 + 绿状态 + 等宽代码；数据表与图表在暗色上高可读。设计意图：**让开发者操作像写代码一样顺**——面板紧凑、快捷键齐全、反馈即时。

### 色彩（组件与语义 Token）

绿 `#3ECF8E` = 在线/运行/连接成功/主行动；中性面板 `#1C1C1C`、`#242424` hover、`#2E2E2E` 输入底；描边 `#3E3E3E`；文字白/灰 `#A6A6A6`；错误红 `#E5534B`、警告黄 `#D9A62E`；语法高亮多彩（仅代码编辑器内）。

### 字体

UI 13–15px；SQL/日志 13px 等宽；表格数字 tabular；终端输出 13px。中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

顶部栏 52px；左树 240px；主区表格/图表；SQL 编辑器等高区；状态徽章 6px 圆角绿底 12% 透明。动效：查询加载 300ms、行选中 150ms、连接回连动画 400ms。

### UI/UX CSS Token

```css
/* Supabase — UI/UX Token（Dashboard） */
--su-ui-green: #3ECF8E;
--su-ui-bg: #1C1C1C;
--su-ui-panel: #242424;
--su-ui-input: #2E2E2E;
--su-ui-line: #3E3E3E;
--su-ui-text: #FFFFFF;
--su-ui-text-subtle: #A6A6A6;
--su-ui-danger: #E5534B;
--su-ui-warn: #D9A62E;
--su-sidebar: 240px;
--su-toolbar-h: 52px;
--su-radius-card: 8px;
--su-radius-btn: 8px;
--su-font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--su-font-mono-ui: ui-monospace, SFMono-Regular, Menlo, monospace;
--su-motion: 250ms ease;
/* 应用：SQL 编辑器暗底等宽；连接成功用绿色状态徽章 */
```

## 记忆点与应用方式

复现"Supabase 感"三步：①白/墨双画布 + 生态绿 `#3ECF8E` 品牌色；②代码与终端氛围是核心（墨底代码块、语法高亮）；③按钮 8px 禁胶囊。做"开发者工具、开源产品、BaaS/数据库"类官网首选。

## 反混搭提示

Supabase 绿不要过度霓虹；不要把产品做成全亮色（它的产品界面是深色工作台）。避免把开发者品牌做得"企业化沉重"——保留一点玩心（吉祥物、emoji 在文案中适度）。
