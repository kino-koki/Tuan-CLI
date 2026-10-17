# 58. Uber — 出行网络 纯黑极简

> **类型**：软件 | **领域**：出行平台 | **设计哲学**：速度与可靠的极简黑

| 规格总览 | 值 |
|---|---|
| 画布色 | `#000000` 黑 / `#FFFFFF` 白 |
| 强调色 | `#000000` 黑（无彩色品牌） |
| 字体策略 | 系统栈（Uber Move 类几何无衬线展示） |
| 记忆点 | 黑底白字 + 地图绿点 |

## HTML 板块 · 官网与营销页

### 设计哲学

Uber 官网是"极简黑"的教科书：纯黑画布、白色粗体大字、无彩色装饰（品牌自 2018 起刻意去彩色化），唯一色彩来源是产品 UI 里的地图/车辆图案。文案直接、排版锋锐，传达**速度、可靠、城市感**。Uber Eats 另用绿色但主品牌保持黑白；营销页以大片城市/出行摄影 + 大字标语推进。

### 色彩

画布黑 `#000000`（默认）/ 白 `#FFFFFF`（亮段）；文字白/黑；辅助灰 `#A8A8A8`（说明）、深灰 `#222222`（次级面）；**品牌本身无强调色**——若需 CTA 强调可用白底黑字或黑底白描边；地图/行程可用产品绿 `#06C167` 但仅限在 UI 截图内。

### 字体

品牌展示字 Uber Move（几何无衬线）或回退系统栈 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`；标题 40–80px Medium/Regular（Uber 反直觉地用中等字重做大字）；正文 16–18px；中文 PingFang SC / Microsoft YaHei。

### 布局、间距、圆角与动效

内容 1200px；区块 96–160px（黑色大段）；图片全出血或 8px 圆角；按钮 8px 圆角（白实心/黑实心），**不常用胶囊**；动效 300ms 平滑、滚动切换段落；hover 仅透明度/位移变化，无彩色反馈。

### HTML CSS Token

```css
/* Uber — HTML 官网 Token */
--ub-bg: #000000;
--ub-bg-light: #FFFFFF;
--ub-bg-2: #222222;
--ub-text: #FFFFFF;
--ub-text-light: #000000;
--ub-text-subtle: #A8A8A8;
--ub-green: #06C167;   /* 仅产品/地图内使用 */
--ub-radius-btn: 8px;
--ub-radius-card: 8px;
--ub-font-display: 'Uber Move', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--ub-space-section: 120px;
--ub-motion: 300ms cubic-bezier(0.3, 0.7, 0.3, 1);
/* 应用：黑底白字 Medium 大标题；CTA 用白底黑字方钮 8px 圆角 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品界面（乘客端/司机端）以地图为画布：全屏地图 + 底部操作卡（目的地、车型、价格预估）；深色地图模式是 signature。UI 极简单色：黑底白字、绿色行车/可达性点（`#00AC4E`/`#06C167`）、红色不可达 `#E02020`。目标是**上车前每个决策 3 秒完成**。

### 色彩（组件与语义 Token）

地图底深 `#0D0D0D`/浅 `#E5E3DF`；主行动绿 `#06C167`（叫车、可乘区域）；危险红 `#E11B48`（取消、不可乘）；文字白/黑、灰 `#A8A8A8`；按钮黑底白字 8px 圆角；ETA 时间数字特大加粗。

### 字体

UI 15–17px；ETA 数字 32–40px ExtraBold tabular；车型名 16px Medium；按钮 16px SemiBold。中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

安全区底部操作卡 12px 圆角、padding 16–24px；地图全屏可拖动；顶部输入栏胶囊 56px；车型卡列表 8px 圆角。动效：叫车请求 300ms、车辆到达 pop 400ms、ETA 滚动数字 200ms；地图移动实时平滑。

### UI/UX CSS Token

```css
/* Uber — UI/UX Token（乘客端） */
--ub-ui-map-dark: #0D0D0D;
--ub-ui-map-light: #E5E3DF;
--ub-ui-card: #FFFFFF;
--ub-ui-card-dark: #111111;
--ub-ui-text: #000000;
--ub-ui-text-dark: #FFFFFF;
--ub-ui-subtle: #6E6E6E;
--ub-ui-green: #06C167;
--ub-ui-danger: #E11B48;
--ub-radius-card: 12px;
--ub-radius-input: 9999px;
--ub-font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--ub-eta-fs: clamp(28px, 6vw, 40px);
--ub-motion: 250ms ease;
/* 应用：底部操作卡白底 12px 圆角；ETA 数字超大 tabular */
```

## 记忆点与应用方式

复现"Uber 感"三步：①纯黑画布 + 白色中等字重大标题；②彩色只存在于地图/产品 UI 内（绿 `#06C167` 可乘/红不可达）；③按钮 8px 圆角方钮、图片全出血。做"出行、配送、城市服务"类官网时，黑白 + 地图绿点是 Uber 语言。

## 反混搭提示

Uber 的黑色不是"炫酷黑"而是"效率黑"——不要加渐变、玻璃拟态或霓虹；绿色禁止用在品牌装饰（只做产品可乘语义）。避免把按钮做成胶囊（那是 Apple/X 语言）。
