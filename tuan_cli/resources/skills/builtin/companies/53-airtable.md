# 53. Airtable — 数据库易用化 天空蓝

> **类型**：软件 | **领域**：低代码数据库 SaaS | **设计哲学**：表格的人性化重构

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / 浅灰 |
| 强调色 | `#18BFFF` Airtable天空蓝 |
| 字体策略 | 系统栈 + 展示无衬线 |
| 记忆点 | 天空蓝 + 表格卡片化 |

## HTML 板块 · 官网与营销页

### 设计哲学

Airtable 官网把"数据库"讲得亲切：天空蓝 `#18BFFF` 主强调、白底、表格/卡片可视化组件化展示；hero 常是"表格 + 视图切换"的动态产品截图。设计语言干净、现代、略带玩具感，目标是让企业软件**不再吓人**。营销页按"用例 × 视图"展开，图标轻量、插画为线框添加色块。

### 色彩

画布白 `#FFFFFF`、浅灰 `#F4F7FA`；主强调天空蓝 `#18BFFF`（CTA、链接、选中）、hover `#0E9BE5`；辅助强调可以灰蓝、青；文字 `#0B141A`、灰 `#5F6B76`；分割线 `#E0E6EC`；成功绿 `#26B6A2`（公式/完成）。

### 字体

系统栈 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`；标题 32–56px SemiBold；正文 15–18px；表格数字用 tabular；中文 PingFang SC / Microsoft YaHei。

### 布局、间距、圆角与动效

内容 1200px；区块 72–104px；卡片 12px 圆角、1px 描边、hover 上浮 2px；按钮 8px 圆角（主蓝/白描边）；hero 产品截图 8px 圆角；动效 200–300ms、stagger 30ms；表格 hover 行高亮。

### HTML CSS Token

```css
/* Airtable — HTML 官网 Token */
--at-blue: #18BFFF;
--at-blue-hover: #0E9BE5;
--at-blue-soft: #E6F8FF;
--at-teal: #26B6A2;
--at-bg: #FFFFFF;
--at-bg-gray: #F4F7FA;
--at-text: #0B141A;
--at-text-subtle: #5F6B76;
--at-line: #E0E6EC;
--at-radius-card: 12px;
--at-radius-btn: 8px;
--at-font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--at-space-section: 80px;
--at-motion: 250ms ease;
/* 应用：主 CTA 天空蓝实心；产品表格卡 1px 描边 12px 圆角 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品是"表格 + 灵活视图"的混合体：默认网格视图像电子表格，但一行记录可展开成卡片/表单/日历/看板。UI 目标是让数据库**视觉上轻**：浅灰底、细描边、hover 显示操作列；蓝色只做行动与当前字段。整体传达"弹性与秩序共存"。

### 色彩（组件与语义 Token）

主蓝 `#18BFFF` = 主行动/选中/链接；中性面白/`#F4F7FA`/hover `#EEF4F9`；描边 `#DCE3EA`；文字 `#0B141A`/`#5F6B76`；字段类型图标保持中性；成功 `#26B6A2`（公式绿色文本）；危险 `#D64545`。

### 字体

UI 13–15px；表格单元格 14px；字段名 13px Medium；视图 tab 14px；数字 tabular。中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

顶栏 56px；左侧工具栏（基/表）280px；网格表头 32px 高、行 40px；记录展开面板 420px；字段编辑浮层 8px 圆角。动效：行 hover 高亮 150ms、展开 250ms、视图切换 300ms fade。

### UI/UX CSS Token

```css
/* Airtable — UI/UX Token（数据库界面） */
--at-ui-bg: #FFFFFF;
--at-ui-bg-2: #F4F7FA;
--at-ui-hover: #EEF4F9;
--at-ui-line: #DCE3EA;
--at-ui-text: #0B141A;
--at-ui-text-subtle: #5F6B76;
--at-ui-blue: #18BFFF;
--at-ui-success: #26B6A2;
--at-ui-danger: #D64545;
--at-row-h: 40px;
--at-head-h: 32px;
--at-panel-w: 420px;
--at-radius-card: 8px;
--at-font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--at-motion: 200ms ease;
/* 应用：表格行 hover 高亮浅蓝；网格单元可横向无缝扩展 */
```

## 记忆点与应用方式

复现"Airtable 感"三步：①白/浅灰底 + 天空蓝 `#18BFFF` 主行动；②产品核心是"表格可视化"——用卡片/日历/看板视图展示数据；③1px 细描边 + 12px 圆角。做"数据库、无代码工具、CRM/表格类 SaaS"页面首选。

## 反混搭提示

不要让天空蓝铺成大面积渐变背景；Airtable 的轻来自"细线 + 浅灰"，忌厚重阴影。多视图展示可用色块区分视图类型，但 UI chrome 保持中性；避免深色主题（Airtable 是明亮产品）。
