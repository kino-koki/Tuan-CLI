# 54. Typeform — 表单体验 粉紫柔和

> **类型**：软件 | **领域**：在线表单 SaaS | **设计哲学**：让提问变成对话

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / 奶油 |
| 强调色 | 粉紫渐变（粉 `#FF5A5F` → 紫 `#6B45F2`） |
| 字体策略 | 系统栈 + 圆润展示字 |
| 记忆点 | 一次一题 + 粉紫渐变 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## HTML 板块 · 官网与营销页

### 设计哲学

Typeform 官网竭力传达"表单可以很美"：品牌粉紫渐变（粉 `#FF5A5F`/`#FF6E79` → 紫 `#6B45F2`）做 logo、CTA 与装饰弧线；产品演示一次一题的聊天式表单直接嵌入 hero；整体柔和、亲切、现代。营销页以**真人使用场景 + 大圆角渐变卡片**为主，目标是消除填写表单的紧张感。

### 色彩

画布白 `#FFFFFF`、奶油灰 `#F9F7F5`；品牌渐变 `linear-gradient(135deg, #FF5A5F, #6B45F2)`（logo/CTA 文字渐变）；强调也可独立用紫 `#6B45F2` 或粉 `#FF5A5F`；文字 `#0A0A0A`、灰 `#6A6A6A`；分割线 `#E8E4E0`；成功绿 `#00C19A`。

### 字体

系统栈 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`；展示可圆润粗体（标题 32–56px）；正文 16–18px；中文 PingFang SC / Microsoft YaHei。

### 布局、间距、圆角与动效

内容 1180px；区块 72–112px；卡片 16–24px 圆角（**可大圆角**）、hover 上浮 + 阴影；按钮胶囊 9999px；渐变装饰多为弧形/波形插入或"光环";动效 250ms；测测看 demo 一次一题切换 300ms。

### HTML CSS Token

```css
/* Typeform — HTML 官网 Token */
--tf-gradient: linear-gradient(135deg, #FF5A5F, #6B45F2);
--tf-pink: #FF5A5F;
--tf-pink-soft: #FFE9EA;
--tf-purple: #6B45F2;
--tf-purple-soft: #ECE7FE;
--tf-bg: #FFFFFF;
--tf-bg-cream: #F9F7F5;
--tf-text: #0A0A0A;
--tf-text-subtle: #6A6A6A;
--tf-line: #E8E4E0;
--tf-success: #00C19A;
--tf-radius-card: 20px;
--tf-radius-pill: 9999px;
--tf-font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--tf-space-section: 88px;
--tf-motion: 250ms ease;
/* 应用：主 CTA 渐变文字或紫底胶囊；卡片 20px 大圆角 + 轻阴影 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品是"一次一题"的全屏表单引擎：每个问题占一屏，进度条在顶部，回答后自动 next；UI 由表单内容决定——大标题、大选择卡、无干扰。设计核心是**节奏**：回答者始终只有"正在回答的这一题"。配色默认可自定义，品牌模板偏柔和粉紫。

### 色彩（组件与语义 Token）

默认白底 + 深字；模板品牌色粉紫为默认强调；进度条紫 `#6B45F2` 或品牌色；选项卡白底描边 → 选中渐变；错误 `#D84343`；成功勾 `#00C19A`；背景可换（品牌设定的渐变/图片）。

### 字体

题目 24–32px SemiBold；选项 18px；按钮 16px Medium；说明 14px 灰。中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

全屏一题；内容居中 600px；顶部进度条 4px 高；选项卡 12–16px 圆角、内 16px；next 按钮气泡 48px 胶囊位于右下；键盘 Tab/Enter 全支持。动效：切换 300ms slide、选项选中 150ms、进度条线性 200ms。

### UI/UX CSS Token

```css
/* Typeform — UI/UX Token（表单引擎） */
--tf-ui-bg: #FFFFFF;
--tf-ui-text: #0A0A0A;
--tf-ui-text-subtle: #6A6A6A;
--tf-ui-primary: #6B45F2;
--tf-ui-pink: #FF5A5F;
--tf-ui-line: #E8E4E0;
--tf-ui-success: #00C19A;
--tf-ui-danger: #D84343;
--tf-q-w: 600px;
--tf-progress-h: 4px;
--tf-radius-option: 14px;
--tf-radius-pill: 9999px;
--tf-font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--tf-motion: 250ms ease;
--tf-motion-slide: 300ms cubic-bezier(0.2, 0.9, 0.3, 1);
/* 应用：一次一题 + 顶部 4px 进度条；next 胶囊按钮右下角 */
```

## 记忆点与应用方式

复现"Typeform 感"三步：①粉紫渐变只做 logo/CTA 装饰（大圆角白卡片衬托）；②一次一题全屏表单 + 顶部细进度条；③选项卡 14px 圆角、点击即过。做"问卷、表单、评测、Onboarding"类交互页面时直接参考。

## 反混搭提示

粉紫渐变铺满整页背景就是跑偏——Typeform 的渐变是"微笑的装饰"，主体仍是白；选项卡不要做成胶囊（14px 圆角正好）；避免用太多霓虹色干扰回答节奏。
