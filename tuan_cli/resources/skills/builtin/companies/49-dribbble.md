# 49. Dribbble — 设计社区 芭比粉

> **类型**：软件 | **领域**：设计师作品社区 | **设计哲学**：让作品墙成为主角

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / 浅灰 `#F5F1EF` |
| 强调色 | `#EA4C89` Dribbble粉 |
| 字体策略 | 系统栈（显示字可用更粗） |
| 记忆点 | 粉色点/按钮 + 作品卡片墙 |

## HTML 板块 · 官网与营销页

### 设计哲学

Dribbble 官网是典型"作品级 UGC 社区"范式：满屏作品卡片（拖拽大图）、粉色只在 logo、hover、主 CTA 出现；底色白/浅米，文字黑灰。整体氛围轻松、创意思维，接近"设计界的 Pinterest"。营销页以**作品瀑布 + 大标语**为主，很少用插画。

### 色彩

画布白 `#FFFFFF`、浅米 `#F5F1EF`（区块底）；品牌粉 `#EA4C89`（logo、CTA、选中、数值高亮）、hover 深粉 `#C53D6E`；文字 `#0D0C22`（Dribbble 专用近黑）、灰 `#6E6D7A`；分割线 `#E7E7E9`。

### 字体

系统栈 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`；标题 28–52px Bold/ExtraBold；正文 16px；可加文字描边或斜体展示（社区感）；中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

内容宽 1200–1400px；作品墙 3–4 列、卡片 12–16px 圆角、图片 4:3；hover 图放大 1.03 + 阴影；区块 64–88px；按钮 6–8px（非胶囊）；动效 200–300ms，hover 柔和。

### HTML CSS Token

```css
/* Dribbble — HTML 官网 Token */
--db-pink: #EA4C89;
--db-pink-hover: #C53D6E;
--db-pink-soft: #FCE7F0;
--db-bg: #FFFFFF;
--db-bg-alt: #F5F1EF;
--db-text: #0D0C22;
--db-text-subtle: #6E6D7A;
--db-line: #E7E7E9;
--db-radius-card: 14px;
--db-radius-btn: 6px;
--db-font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--db-space-section: 72px;
--db-motion: 250ms ease;
/* 应用：标题极粗 + 作品卡 4:3 大图；粉 #EA4C89 用于 CTA 与 logo */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品即"作品墙"：feed 卡片、浏览筛选、收藏与点赞都围绕作品图展开；UI 退到极简白灰，粉色只做点赞填充/收藏/当前 tab。搜索与筛选是核心交互，筛选条紧凑不遮挡内容。整体是"低 UI 干扰、高内容密度"的设计师工作台。

### 色彩（组件与语义 Token）

粉 `#EA4C89` = 点赞、收藏、当前态；neutral 面白/`#F5F1EF`/hover `#F9F0F3`；文字 `#0D0C22`/`#6E6D7A`；描边 `#E7E7E9`；成功（已关注）`#0D0C22` 黑按钮；遮罩 `rgba(13,12,34,0.6)`。

### 字体

UI 13–15px；卡片标题 15px SemiBold；数字/统计 SemiBold tabular；筛选标签 13px。中文 PingFang SC 14px。

### 布局、间距、圆角与动效

feed 3 列卡片、gap 24px；卡片 14px 圆角、内 padding 12px；筛选条 sticky 56px；hover 叠加操作按钮（复制链接、收藏、喜欢）200ms；加载更多按钮 6px 圆角。动效轻量：点赞 heart 250ms pop。

### UI/UX CSS Token

```css
/* Dribbble — UI/UX Token（作品社区） */
--db-ui-bg: #FFFFFF;
--db-ui-bg-alt: #F5F1EF;
--db-ui-hover: #F9F0F3;
--db-ui-text: #0D0C22;
--db-ui-text-subtle: #6E6D7A;
--db-ui-pink: #EA4C89;
--db-ui-line: #E7E7E9;
--db-radius-card: 14px;
--db-radius-btn: 6px;
--db-card-gap: 24px;
--db-font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--db-motion: 250ms ease;
/* 应用：点赞命中粉 #EA4C89；筛选条 sticky、卡片 hover 浮出操作层 */
```

## 记忆点与应用方式

复现"Dribbble 感"三步：①白/浅米底 + 作品图做大主角 + 3 列 14px 圆角卡；②粉 `#EA4C89` 只做点赞/CTA/logo；③字体粗黑、UI 紧凑。做"作品集、展示墙、创意社区"类页面直接套用。

## 反混搭提示

不要让粉 `#EA4C89` 铺满背景或渐变；Dribbble 的粉是小面积信号色。避免厚重阴影与玻璃拟态；作品卡片边框要细（1px `#E7E7E9`）。
