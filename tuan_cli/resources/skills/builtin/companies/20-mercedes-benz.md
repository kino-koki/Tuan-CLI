# 20. Mercedes-Benz — 感性纯粹的标志性设计

> **类型**：品牌 | **领域**：汽车/豪华 | **设计哲学**：Sensual Purity, Iconic Design

| 规格总览 | 值 |
|---|---|
| 画布色 | `#000000`/`#FFFFFF` |
| 强调色 | `#00ADEF`（仅电动） |
| 字体策略 | Corporate A/S |
| 记忆点 | 感性纯粹 |

## 设计规格（定本原文）

**领域标签**：汽车/豪华 | **设计哲学**：Sensual Purity, Iconic Design

Mercedes-Benz 2025 年将“感性纯粹”设计语言提升到新高度。核心是“受过去启发，为未来而设计”——统一内燃机与电动车的设计语言，不刻意区分动力形式。设计主管 Gorden Wagener 发布设计宣言《Iconic Design》，强调豪华汽车不应沦为“轮子上的家电”。设计哲学是“一致、地位导向、跨产品线”。

**色彩**：黑白为基底，Mercedes 银灰 `#A0A0A0` 作为品牌锚点。EQ 系列使用蓝色点缀作为电动标识，但新设计语言弱化动力形式差异。内饰使用温暖材质与冷峻数字界面的对比。

**字体**：Mercedes-Benz 自有字体（Corporate A/S 系列），几何感强，干净利落。数字仪表使用定制字体，数字清晰可读。

**间距**：内饰空间的物理间距是核心——按钮布局、屏幕分区、材质过渡。数字界面中，信息层级清晰，不过度堆叠。

**记忆点**：感性纯粹的曲面语言 + 标志性设计 + 统一动力形式的设计哲学。

## CSS Token（可直接复现）

```
/* Mercedes-Benz — 可复现设计系统 Token（数字界面参考） */

/* 字体 */
--font-display: 'Corporate A', 'Mercedes-Benz Sans', sans-serif;
--font-body: 'Corporate S', 'Mercedes-Benz Sans', sans-serif;

/* 字号 */
--fs-display: clamp(2rem, 4vw, 3rem);
--fs-title: clamp(1.25rem, 2vw, 1.5rem);
--fs-body: 0.875rem;
--fw-regular: 400;
--fw-medium: 500;
--fw-bold: 700;

/* 色彩 */
--mb-black: #000000;
--mb-white: #FFFFFF;
--mb-silver: #A0A0A0;
--mb-blue: #00ADEF;
--mb-gray-100: #F3F3F3;
--mb-gray-500: #8C8C8C;
--mb-gray-900: #1A1A1A;

/* 间距 */
--space-xs: 4px;
--space-sm: 8px;
--space-md: 16px;
--space-lg: 32px;
--space-xl: 64px;

/* 圆角 */
--radius-sm: 0px;
--radius-md: 2px;
--radius-lg: 4px;

/* 动效 */
--motion-hover: 150ms ease-out;
--motion-enter: 350ms cubic-bezier(0.25, 0.1, 0.25, 1);

/* 记忆点：感性纯粹曲面 + 标志性设计 + 统一动力形式 */
/* 应用方式：黑白银为主，蓝色仅电动标识，零到极低圆角 */
```
