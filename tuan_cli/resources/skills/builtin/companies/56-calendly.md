# 56. Calendly — 日程自动化 自信蓝

> **类型**：软件 | **领域**：预约日程 SaaS | **设计哲学**：把约时间的麻烦自动化

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / 浅灰 |
| 强调色 | `#0069FF` Calendly蓝 |
| 字体策略 | 系统栈 + 展示无衬线 |
| 记忆点 | 亮蓝 + 日历块 + 双栏预约 |

## HTML 板块 · 官网与营销页

### 设计哲学

Calendly 官网把"约时间"讲得无比顺滑：亮蓝 `#0069FF` 主强调、白底、产品日历界面大图；hero 常是"一键预约 vs 邮件往来"的对比场景。设计目标：**快速、清晰、无摩擦**——配色明快、按钮醒目、文案直接。营销页多用步骤式（1-2-3）与时间对比动画。

### 色彩

画布白 `#FFFFFF`、浅蓝灰 `#F5F8FC`；主强调蓝 `#0069FF`（CTA、链接、选中焦点）、hover `#0052CC`；文字 `#0F1722`、灰 `#5F6B76`；分割线 `#DCE3EA`；成功绿 `#0D9B5E`（"已预约"）。

### 字体

系统栈 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`；标题 32–56px SemiBold；正文 16–18px；中文 PingFang SC / Microsoft YaHei；时间/日期数字 tabular。

### 布局、间距、圆角与动效

内容 1180px；区块 72–104px；卡片 12–16px 圆角、1px 描边；按钮 8px 圆角；hero 常为双栏"日历面板 + 说明"；动效 200–300ms；hover 行高亮浅蓝。

### HTML CSS Token

```css
/* Calendly — HTML 官网 Token */
--ca-blue: #0069FF;
--ca-blue-hover: #0052CC;
--ca-blue-soft: #E8F1FF;
--ca-bg: #FFFFFF;
--ca-bg-gray: #F5F8FC;
--ca-text: #0F1722;
--ca-text-subtle: #5F6B76;
--ca-line: #DCE3EA;
--ca-success: #0D9B5E;
--ca-radius-card: 14px;
--ca-radius-btn: 8px;
--ca-font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--ca-space-section: 80px;
--ca-motion: 200ms ease;
/* 应用：主 CTA 亮蓝实心；日历小方块 8px 圆角 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品核心是"预订页 + 日历网格"：左侧日期/时间选择、右侧事件详情；被约者看到的是一个**比官网还轻的纯 UI**——白底、蓝选中、无导航。设计目标是消除约时间的认知负担：时间槽 hover 即选、点击即确认。

### 色彩（组件与语义 Token）

主蓝 `#0069FF` = 选中日期/时间槽/主行动；中性白面、`#F5F8FC` 灰面、hover `#E8F1FF`；描边 `#DCE3EA`；文字 `#0F1722`/`#5F6B76`；已预约不可选槽灰 `#B3BFCC`；成功 `#0D9B5E`。

### 字体

UI 13–15px；日期标题 20px SemiBold；时间槽 14px Medium；说明 14px；数字 tabular。中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

预订页居中 720px 卡片（12px 圆角 + 描边）；左日历 320px、右详情 320px；时间槽 40px 高、8px 圆角；今天/选中标记蓝点 6px。动效：时间槽 hover 150ms、选中 250ms、提交 300ms。

### UI/UX CSS Token

```css
/* Calendly — UI/UX Token（预订日历） */
--ca-ui-bg: #FFFFFF;
--ca-ui-bg-2: #F5F8FC;
--ca-ui-hover: #E8F1FF;
--ca-ui-line: #DCE3EA;
--ca-ui-text: #0F1722;
--ca-ui-text-subtle: #5F6B76;
--ca-ui-blue: #0069FF;
--ca-ui-disabled: #B3BFCC;
--ca-ui-success: #0D9B5E;
--ca-card-w: 720px;
--ca-slot-h: 40px;
--ca-radius-slot: 8px;
--ca-font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--ca-motion: 200ms ease;
/* 应用：日期选中 2px 蓝 outline + 蓝 dot；时间槽 hover 浅蓝 */
```

## 记忆点与应用方式

复现"Calendly 感"三步：①白底 + 亮蓝 `#0069FF` 唯一强调；②日历网格是核心视觉（选中蓝、今天点）；③预订页 720px 卡片零导航。做"预约、排期、日历类 SaaS"页面首选。

## 反混搭提示

Calendly 的蓝是"效率蓝"——不要渐变、不要大圆角装饰、不要深色 hero；所有 UI 以"帮你快速选时间"为唯一目标，加太多营销装饰即偏离。
