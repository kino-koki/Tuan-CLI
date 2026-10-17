# 64. NVIDIA — 算力巨头 荧光绿

> **类型**：软件 | **领域**：芯片与 AI 计算 | **设计哲学**：未来感与工程权威

| 规格总览 | 值 |
|---|---|
| 画布色 | `#000000` 黑 / 白 |
| 强调色 | `#76B900` NVIDIA绿 |
| 字体策略 | 系统栈 + 展示几何无衬线 |
| 记忆点 | 荧光绿 + 黑底科技纹 |

## HTML 板块 · 官网与营销页

### 设计哲学

NVIDIA 官网是"黑底 + 荧光绿"的极致：纯黑画布、绿色 logo 与 CTA、几何去线化排版，背景密集使用 GPU 芯片/电路纹理或 AI 可视化光效。设计语言传达**算力、未来、工程权威**——像为超级计算机做的发布会。营销页以产品大图、架构图 + 少量文字为主，绿只出场在关键节点（logo、按钮、数字、标注）。

### 色彩

画布黑 `#000000`、次级深灰 `#191919`、白段可用；主强调绿 `#76B900`（NVIDIA 官方绿：CTA、链接、logo）、hover 亮绿 `#8BC34A`；文字白、灰 `#B0B0B0`；分隔线 `#2E2E2E`；成功/状态绿可复用 `#76B900`，红色仅警示 `#E02020`。

### 字体

科技感几何无衬线（GeForce/展示用 NVIDIA Sans 风格）或系统栈 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`；标题 36–72px SemiBold（可带硬件式窄字距）；正文 15–17px；数字与规格用 tabular；中文思源黑体/PingFang SC。

### 布局、间距、圆角与动效

内容 1200px；区块 64–128px；卡片 8px 圆角（**克制**）、1px 白 8% 描边；按钮 4–8px 圆角（绿实心/白描边）；hero 常为全屏暗色 + 产品渲染图；背景纹理用 CSS 网格线/rgb 扫描线；hover 亮2px 绿色 outline；动效 250ms。

### HTML CSS Token

```css
/* NVIDIA — HTML 官网 Token */
--nv-green: #76B900;
--nv-green-hover: #8BC34A;
--nv-green-soft: rgba(118, 185, 0, 0.12);
--nv-bg: #000000;
--nv-bg-2: #191919;
--nv-text: #FFFFFF;
--nv-text-subtle: #B0B0B0;
--nv-line: rgba(255, 255, 255, 0.12);
--nv-danger: #E02020;
--nv-radius-card: 8px;
--nv-radius-btn: 6px;
--nv-grid-line: linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px);
--nv-font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--nv-space-section: 96px;
--nv-motion: 250ms ease;
/* 应用：绿只做 logo/CTA/数字高亮；卡片 8px 圆角 + 白8%描边；hero 深色纹理 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品界面（驱动管理、NGC、企业控制台）延续黑绿科技语言但更实用：深色侧栏 + 参数卡 + 状态指示。绿 `#76B900` 作为"已就绪/在线/性能达标"信号，其余中性。设计目标是**让硬件状态一眼可读**：图表、负载、告警都以绿色系为主、灰阶为辅。

### 色彩（组件与语义 Token）

绿 `#76B900` = 就绪/主行动/选中；中性面黑/`#191919`/hover `#242424`；描边 `#333333`；文字白/`#B0B0B0`；负载图绿→黄 `#FFC107`→红 `#E02020`（热区语义）；输入框深灰底白字。

### 字体

UI 13–15px；规格数字 SemiBold tabular；系统监控大数字 28px ExtraBold。中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

左侧导航 240px；内容卡 8px 圆角、16px padding；监控图无边框；状态点 8px 圆形（绿/黄/红）；按钮 6px。动效：状态刷新 300ms fade、告警呼吸灯 1.5s loop（仅告警态）、图表实时平滑。

### UI/UX CSS Token

```css
/* NVIDIA — UI/UX Token（控制台 / 驱动） */
--nv-ui-green: #76B900;
--nv-ui-bg: #000000;
--nv-ui-panel: #191919;
--nv-ui-hover: #242424;
--nv-ui-line: #333333;
--nv-ui-text: #FFFFFF;
--nv-ui-text-subtle: #B0B0B0;
--nv-ui-warn: #FFC107;
--nv-ui-danger: #E02020;
--nv-sidebar: 240px;
--nv-radius-card: 8px;
--nv-radius-btn: 6px;
--nv-font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--nv-motion: 250ms ease;
/* 应用：状态点绿=就绪/黄=警告/红=错误；输入框深灰底白字 */
```

## 记忆点与应用方式

复现"NVIDIA 感"三步：①纯黑底 + 荧光绿 `#76B900` 只做 logo/CTA/状态；②背景加网格线/电压纹理提升"算力感"；③卡片 8px 圆角、按钮 6px，克制不去圆角化。做"芯片、AI、算力、科技硬件"类官网首选。

## 反混搭提示

NVIDIA 绿是"信号绿"不是"清新绿"——不要铺满背景、不要渐变；黑色必须干净（不要蓝黑或紫黑）。避免消费电子的玻璃拟态与 20px 大圆角（那是 Apple/Google 语言）。
