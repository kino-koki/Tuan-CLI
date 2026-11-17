# 43. Medium — 深思阅读 衬线静土

> **类型**：软件 | **领域**：内容发布平台 | **设计哲学**：沉浸阅读式极简

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / `#242424` 暗 |
| 强调色 | `#1A8917` 阅读绿 |
| 字体策略 | Charter（衬线）+ Söhne（无衬线） |
| 记忆点 | 绿点 + 衬线标题单栏阅读 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## HTML 板块 · 官网与营销页

### 设计哲学

Medium 官网与文章页共享极简骨架：白/米白画布、衬线标题、单栏 680px 阅读宽度、绿叶绿 CTA。设计目标只有一个——"请安静地读"。营销页没有花哨 hero，常用文章卡片列表 + 少量大字，排版节奏像一本活着的杂志。暗色模式同理反转。

### 色彩

画布白 `#FFFFFF`、暖白 `#F5F4F0`（文章底）；文字墨黑 `#242424`（亮色）/白（暗色）；强调阅读绿 `#1A8917`（链接、CTA、logo 圆点、follow 按钮）、hover `#156D12`；辅助灰 `#6B6B6B`、`#757575`；分割线 `#E6E6E6`。

### 字体

标题：Charter（衬线）/ Georgia / Cambria；正文同衬线栈 `charter, Georgia, Cambria, "Times New Roman", serif`；界面与按钮：Söhne / `-apple-system, "Segoe UI", Roboto, sans-serif`；中文正文回落 Songti SC / SimSun（衬线中文），界面 PingFang SC / Microsoft YaHei。标题 32–48px，正文 20px/1.6。

### 布局、间距、圆角与动效

阅读列 680px、行高 1.6、段距 32px；区块纵向 64–96px；按钮胶囊 9999px（高 38px）；卡片列表 16px 圆角带 1px 描边，或纯白无边框列表；动效极轻：hover 仅文字颜色变化，200ms；禁大动画。

### HTML CSS Token

```css
/* Medium — HTML 官网 Token */
--mdm-green: #1A8917;
--mdm-green-hover: #156D12;
--mdm-bg: #FFFFFF;
--mdm-bg-warm: #F5F4F0;
--mdm-text: #242424;
--mdm-text-subtle: #6B6B6B;
--mdm-line: #E6E6E6;
--mdm-read-w: 680px;
--mdm-radius-pill: 9999px;
--mdm-font-serif: charter, Georgia, Cambria, "Times New Roman", "Songti SC", "SimSun", serif;
--mdm-font-sans: sohne, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
--mdm-motion: 200ms ease;
/* 应用：标题衬线粗体，正文 20px/1.6，绿叶绿胶囊按钮 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品界面把"阅读优先"做到极致：顶部极窄工具条、正文宽 680px、无任何侧栏干扰；右侧进度条与补齐按钮。编辑态同样安静——工具栏只在选中文字时浮现。设计意图是让写作与阅读都像"纸上的专注"。

### 色彩（组件与语义 Token）

语义：绿 `#1A8917` = 关注、推荐、链接；编辑蓝 `#3B49DF`（高亮/选中态，Medium 编辑蓝）；危险 `#8B0000` 系灰红仅错误文案；表面：白 → `#F5F4F0`（文章）→ `#F2F2F2` hover；描边 `#E6E6E6`。

### 字体

正文 20px/1.6 衬线；标题 32–40px 衬线 Bold；工具条/按钮 14–15px 无衬线；代码预设 `ui-monospace, SFMono-Regular, Menlo, monospace`；中文正文 18–20px 宋体衬线。

### 布局、间距、圆角与动效

工具条 57px 高、sticky；阅读列 680px 居中；段落 32px；图注 14px 灰；引用块左边框 4px；强调拖选工具条 44px 高、8px 圆角胶囊。动效：滚动进度条线性 0ms，工具条浮现 200ms fade，禁止视差。

### UI/UX CSS Token

```css
/* Medium — UI/UX Token（产品界面） */
--mdm-ui-bg: #FFFFFF;
--mdm-ui-bg-warm: #F5F4F0;
--mdm-ui-hover: #F2F2F2;
--mdm-ui-text: #242424;
--mdm-ui-text-subtle: #6B6B6B;
--mdm-ui-line: #E6E6E6;
--mdm-ui-green: #1A8917;
--mdm-ui-edit-blue: #3B49DF;
--mdm-read-w: 680px;
--mdm-toolbar-h: 57px;
--mdm-radius-pill: 9999px;
--mdm-font-serif-ui: charter, Georgia, Cambria, "Songti SC", "SimSun", serif;
--mdm-font-sans-ui: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
--mdm-motion: 200ms ease;
/* 应用：正文 20px 衬线 1.6 行高，选中工具条用胶囊浮层 */
```

## 记忆点与应用方式

复现"Medium 感"三步：①白/暖白画布 + 衬线标题 + 680px 单栏；②阅读绿 `#1A8917` 只做链接/CTA/关注；③所有装饰退位，靠字重与间距排版。做内容型页面（长文、博客、白皮书）时 Medium 是默认参考。

## 反混搭提示

Medium 是"反装饰"代表——不要加 hero 大图、不要多色渐变、不要圆角卡片堆砌、不要图标矩阵。绿 `#1A8917` 不能做背景填充；UI 若出现第二个强调色（编辑蓝除外）即偏离。
