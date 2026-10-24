# 50. Asana — 协同工作 珊瑚红

> **类型**：软件 | **领域**：项目管理 SaaS | **设计哲学**：让团队行动对齐的暖色秩序

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 |
| 强调色 | `#F06A6A` Asana珊瑚红 |
| 字体策略 | 系统栈（显示可用更粗无衬线） |
| 记忆点 | 珊瑚红 + 圆角任务卡 |
| 核验说明 | 数据快照（v2.0 定本，具体采集日期未标注）；品牌规范可能更新，使用前建议核对官网 |

## HTML 板块 · 官网与营销页

### 设计哲学

Asana 官网把"团队协作"翻译成温暖、明快的语言：白底 + 珊瑚红 `#F06A6A` 主强调 + 圆角卡片；hero 常是产品界面大图 + 一句行动口号。整体气质是"友好的生产力"——不冰冷、不幼稚，用**暖红 + 清爽排版**平衡专业与亲和。营销页多用真实产品截图、人物场景插画与分步说明。

### 色彩

画布白 `#FFFFFF`、浅暖灰 `#F8F8F8`；主强调珊瑚红 `#F06A6A`（CTA、链接、选中）、hover 深红 `#D14B4B`；辅助暖黄橙可用于信息块（如 `#FF9A62`）但面积小；文字 `#1A2430`（Asana 近黑）、灰 `#5C6670`；分割线 `#E8E8E8`。

### 字体

系统栈 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`；标题 32–56px SemiBold；正文 16–18px；中文 PingFang SC / Microsoft YaHei。可少量用斜体展示词营造"行动感"。

### 布局、间距、圆角与动效

内容宽 1200px；区块 80–120px；卡片 12–16px 圆角、1px 描边或 2% 阴影；按钮 8px 圆角（非胶囊）；hero 产品截图 8px 圆角带阴影；动效 200–300ms、stagger 30–50ms；hover 卡片上浮 2px。

### HTML CSS Token

```css
/* Asana — HTML 官网 Token */
--as-red: #F06A6A;
--as-red-hover: #D14B4B;
--as-red-soft: #FDEEEE;
--as-orange: #FF9A62;
--as-bg: #FFFFFF;
--as-bg-warm: #F8F8F8;
--as-text: #1A2430;
--as-text-subtle: #5C6670;
--as-line: #E8E8E8;
--as-radius-card: 14px;
--as-radius-btn: 8px;
--as-font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--as-space-section: 88px;
--as-motion: 250ms ease;
/* 应用：主 CTA 珊瑚红实心 8px 圆角；卡片 1px 描边 + 轻阴影 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品界面是"任务驱动"的信息架构范本：左侧导航 + 中央任务看板/列表 + 右侧详情面板；颜色在 UI 中以语义为主（任务标记用多色 tag），品牌珊瑚红用于主行动与选中。任务卡圆角、白底、hover 浮起，整体**高识别、低噪音**——让团队成员 100% 时间知道"下一步做什么"。

### 色彩（组件与语义 Token）

主行动珊瑚红 `#F06A6A`（创建任务、主按钮）；中性：白面、`#F6F7F9` 灰面、hover `#EEF1F4`；描边 `#DCE0E5`；文字 `#1A2430`/`#5C6670`；任务 tag 色彩系统（绿完成 `#00A63D`、黄进行 `#FFB300`、红风险 `#E4572E`）允许多彩但按语义。

### 字体

UI 13–15px；任务标题 14px Medium；看板列头 13px SemiBold；数字 tabular。中文 UI PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

左侧栏 280px；看板列 300px、卡 gap 12px；任务卡 10–12px 圆角、内 padding 12px；详情面板 400px 右侧抽屉；主按钮 8px 圆角。动效：卡片拖拽 200ms、创建任务 250ms scale-in、完成打勾 300ms pop。

### UI/UX CSS Token

```css
/* Asana — UI/UX Token（项目管理） */
--as-ui-bg: #FFFFFF;
--as-ui-bg-2: #F6F7F9;
--as-ui-hover: #EEF1F4;
--as-ui-line: #DCE0E5;
--as-ui-text: #1A2430;
--as-ui-text-subtle: #5C6670;
--as-ui-red: #F06A6A;
--as-ui-green: #00A63D;
--as-ui-amber: #FFB300;
--as-ui-danger: #E4572E;
--as-radius-task: 10px;
--as-radius-btn: 8px;
--as-sidebar: 280px;
--as-font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--as-motion: 200ms ease;
/* 应用：任务卡白底圆角 hover 浮起；主行动一律珊瑚红 */
```

## 记忆点与应用方式

复现"Asana 感"三步：①白底 + 珊瑚红 `#F06A6A` 主 CTA；②任务卡 10–14px 圆角、1px 描边、hover 上浮；③多色 tag 只做语义（完成绿/进行黄/风险红），UI 其余中性。做"项目管理、任务协作、工作流 SaaS"类产品页首选。

## 反混搭提示

Asana 的珊瑚红是"行动色"，不要大面积铺底或渐变；任务 tag 多彩是语义不是装饰，不要让 tag 色溢出到卡片背景。避免深色 hero（Asana 主页是明亮的），避免玻璃拟态。
