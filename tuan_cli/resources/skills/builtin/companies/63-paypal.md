# 63. PayPal — 全球支付 双色深蓝

> **类型**：软件 | **领域**：在线支付平台 | **设计哲学**：让资金流通像网络一样可靠

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / 浅灰 |
| 强调色 | 深蓝 `#003087` + 亮蓝 `#0070E0` |
| 字体策略 | 系统栈 + PayPal Sans 展示 |
| 记忆点 | 双蓝组合 + 圆润卡片 |

## HTML 板块 · 官网与营销页

### 设计哲学

PayPal 官网把"支付"讲得全球、可靠：主深蓝 `#003087` 做 logo/页脚/主行动、亮蓝 `#0070E0` 做链接/hover/次级强调；白底 + 大圆角卡片 + 全球场景大图。设计语言**稳重但不老气**：圆角提升亲和力、蓝色梯度（深→亮）传递"专业金融科技"。营销页以"商家收款 + 消费者支付"双场景展开。

### 色彩

画布白 `#FFFFFF`、浅灰 `#F4F6FA`；主深蓝 `#003087`（logo、主 CTA、页脚）、亮蓝 `#0070E0`（链接、hover、次级行动）、天蓝 `#009CDE`（图标点缀）；文字 `#1A1A1A`、灰 `#5E6670`；分割线 `#E2E6EE`；成功绿 `#00A86B`。

### 字体

PayPal Sans（品牌字）与系统栈并用 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`；标题 32–56px SemiBold；正文 16–18px；金额 SemiBold tabular；中文 PingFang SC / Microsoft YaHei。

### 布局、间距、圆角与动效

内容 1200px；区块 72–112px；卡片 16px 圆角、1px 描边、hover 上浮；按钮 8px 圆角（深蓝实心/白描边）；hero 常为右图左文 + 双 CTA；动效 200–300ms。

### HTML CSS Token

```css
/* PayPal — HTML 官网 Token */
--pp-navy: #003087;
--pp-navy-hover: #00256B;
--pp-blue: #0070E0;
--pp-cyan: #009CDE;
--pp-soft: #E5F1FB;
--pp-bg: #FFFFFF;
--pp-bg-gray: #F4F6FA;
--pp-text: #1A1A1A;
--pp-text-subtle: #5E6670;
--pp-line: #E2E6EE;
--pp-success: #00A86B;
--pp-radius-card: 16px;
--pp-radius-btn: 8px;
--pp-font: 'PayPal Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--pp-space-section: 88px;
--pp-motion: 250ms ease;
/* 应用：主 CTA 深蓝实心；链接与次级动作用亮蓝 #0070E0 */
```

## UI/UX 板块 · 产品界面

### 设计哲学

产品界面（账户/结账）核心是"交易流水 + 一键支付"：白底、大圆角金额卡、双蓝行动；每一笔交易可视化（收款人 logo、金额、状态徽章）。设计目标是**让资金流向一目了然**——列表 + 徽章 + 大金额，蓝色系统让"可信感"贯穿始终。

### 色彩（组件与语义 Token）

深蓝 `#003087` = 主行动/导航/自主账户操作；亮蓝 `#0070E0` = 链接/次级；中性面白/`#F4F6FA`/hover `#EAF2FC`；描边 `#DCE1EA`；文字 `#1A1A1A`/`#5E6670`；成功绿 `#00A86B`（到账）、处理中蓝 `#0070E0`、失败红 `#C42B1C`。

### 字体

余额 28–40px SemiBold tabular；流水项 15px；状态 13px SemiBold；按钮 16px SemiBold。中文 PingFang SC/Microsoft YaHei。

### 布局、间距、圆角与动效

主页：余额卡（8–16px 圆角、渐变蓝底白字可选）→ 快捷操作 → 流水列表（分隔线）；支付确认 sheet 12px 圆角。动效：到账通知 300ms、金额滚动 150ms、状态徽章切换 200ms。

### UI/UX CSS Token

```css
/* PayPal — UI/UX Token（账户 / 支付） */
--pp-ui-navy: #003087;
--pp-ui-blue: #0070E0;
--pp-ui-bg: #FFFFFF;
--pp-ui-bg-2: #F4F6FA;
--pp-ui-hover: #EAF2FC;
--pp-ui-line: #DCE1EA;
--pp-ui-text: #1A1A1A;
--pp-ui-text-subtle: #5E6670;
--pp-ui-success: #00A86B;
--pp-ui-danger: #C42B1C;
--pp-balance-fs: clamp(28px, 5vw, 40px);
--pp-radius-card: 14px;
--pp-radius-btn: 8px;
--pp-font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--pp-motion: 200ms ease;
/* 应用：余额卡深蓝渐变底白字；状态徽章圆角 4px */
```

## 记忆点与应用方式

复现"PayPal 感"三步：①深蓝 `#003087` 主行动 + 亮蓝 `#0070E0` 链接的双蓝系统；②金额卡大数字 + 徽章化状态；③圆角 16px 卡片 + 全球场景图。做"支付、电商结算、金融科技"类页面时，双蓝 + 圆润 = 可信又现代。

## 反混搭提示

PayPal 双蓝是"金融蓝"，避免加入第三强调色；主 CTA 用深蓝而非亮蓝（亮蓝是链接/次级的职能）。不要用 Klarna 粉或 Robinhood 青绿混入支付流程；卡片圆角上限 16px。
