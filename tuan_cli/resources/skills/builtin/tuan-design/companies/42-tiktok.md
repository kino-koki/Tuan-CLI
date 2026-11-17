# 42. TikTok — 全屏短影音 双彩黑

> **类型**：软件 | **领域**：短视频平台 | **设计哲学**：青春、节奏、全屏冲击

| 规格总览 | 值 |
|---|---|
| 画布色 | `#000000` 黑 / `#FFFFFF` 白 |
| 强调色 | `#25F4EE` 电光青 + `#FE2C55` 芭比粉 |
| 字体策略 | TikTok Sans / 系统字体栈 |
| 记忆点 | 黑白底 + 青粉双强调 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## HTML 板块 · 官网与营销页

### 设计哲学

TikTok 官网与产品共享"黑白极端 + 双彩点缀"的基因：黑色大画布、白色粗体大标语，电光青 `#25F4EE` 与芭比粉 `#FE2C55` 只出现在关键 CTA、播放进度与装饰节点。整体节奏快、能量高，hero 常用全屏视频/3D 元素。营销页像演唱会海报：大声、直接、动感。

### 色彩

画布黑 `#000000`（默认）/ 白 `#FFFFFF`（亮色段落）；文字白/黑；双强调：青 `#25F4EE`（主 CTA、进度、播放态）、粉 `#FE2C55`（点赞、直播、热门标记）；辅助灰 `#161823`（产品底）与 `#8A8B91`（说明文字）。**青粉二色可同时出现但面积必须克制**。

### 字体

TikTok Sans（展示，粗、几何、略带工程感）与系统栈并用；标题 40–72px ExtraBold、可带描边（stroke）或霓虹文字阴影；正文 15–18px；中文回落 PingFang SC / Microsoft YaHei。数字用粗体 tabular。

### 布局、间距、圆角与动效

营销 hero 无圆角大图/视频全出血；按钮 4–8px 小圆角（**拒绝胶囊**）高 48px；间距 48–96px；卡片 12px；动效 200–300ms，可允许 bounce（青春感）；hover 用亮度变化与 sắc色彩位移。入场 stagger 30–60ms。

### HTML CSS Token

```css
/* TikTok — HTML 官网 Token */
--tt-bg: #000000;
--tt-bg-alt: #FFFFFF;
--tt-cyan: #25F4EE;
--tt-pink: #FE2C55;
--tt-text: #FFFFFF;
--tt-text-subtle: #8A8B91;
--tt-text-dark: #161823;
--tt-radius-btn: 8px;
--tt-radius-card: 12px;
--tt-font: TikTok Sans, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
--tt-ease: cubic-bezier(0.22, 1, 0.36, 1);
--tt-motion: 250ms var(--tt-ease);
/* 应用：黑底白大字 + 青/粉小面积点缀；按钮小圆角，禁止胶囊 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品界面是全球最激进的"沉浸式单条流"：全屏视频、右侧操作区（头像、点赞、评论、分享、音乐）、底部进度条。UI 几乎透明化——白色图标叠加在视频上，黑 `#161823` 只用于评论面板与搜索页，让内容覆盖一切。

### 色彩（组件与语义 Token）

语义：青 `#25F4EE` = 当前播放/进度/链接；粉 `#FE2C55` = 点赞/直播/热榜；页面底 `#161823`（feed 非视频面）；文字白 `#FFFFFF` 与灰 `#8A8B91`；分割线 `#2E2E35`；遮罩 `rgba(0,0,0,0.5)` 到 `rgba(22,24,35,0.5)`。

### 字体

右侧操作区数字 12–13px（赞/评/转发）；引导文案 14–16px；评论区 15px；标题最大使用 30px+ 粗体作挑战/标签。中文界面 PingFang SC 15px。

### 布局、间距、圆角与动效

全屏视频列（9:16）；右侧操作列 96px 宽、图标 30–52px 圆形（头像 52px + 渐变环）；底部进度条 2px 青；评论面板 12px 圆角、slide-up 300ms；点赞 heart 动画 400ms pop；音乐唱盘旋转 360°/6s 线性。

### UI/UX CSS Token

```css
/* TikTok — UI/UX Token（产品界面） */
--tt-ui-bg: #161823;
--tt-ui-overlay: linear-gradient(180deg, rgba(22,24,35,0.3), rgba(22,24,35,0) 20%, rgba(0,0,0,0.55));
--tt-ui-cyan: #25F4EE;
--tt-ui-pink: #FE2C55;
--tt-ui-text: #FFFFFF;
--tt-ui-text-subtle: #8A8B91;
--tt-ui-line: #2E2E35;
--tt-action-col: 96px;
--tt-avatar: 52px;
--tt-radius-panel: 12px;
--tt-font-ui: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
--tt-motion-pop: 400ms cubic-bezier(0.2, 1.6, 0.4, 1);
/* 应用：操作图标白/青双态，点赞命中变粉 #FE2C55 */
```

## 记忆点与应用方式

复现"TikTok 感"三步：①黑底（产品内 `#161823`）或白底极端画布；②青 `#25F4EE` + 粉 `#FE2C55` 双强调且面积≤8%；③按钮小圆角、标题粗体可加描边。要表达"节奏与流行"就用全屏视觉 + 右侧圆形操作区。

## 反混搭提示

TikTok 的青粉双色是"信号色"不是"主题色"——大面积双色渐变背景是忌。不要用胶囊按钮（那是 X/Google 的语言）；不要给视频卡片加白框或重阴影；字体超粗没问题但禁止衬线。
