# 72. IKEA — 家居民主 蓝黄经典

> **类型**：品牌 | **领域**：家居零售 | **设计哲学**：让好设计人人可得的平价民主

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / 浅灰 |
| 强调色 | 蓝 `#0058A3` + 黄 `#FFDB00` |
| 字体策略 | IKEA Sans（Noto 变体）/ 系统栈 |
| 记忆点 | 家喻户晓的蓝黄 + 家居场景大图 |

## 官网板块 · 数字化品牌体验

### 设计哲学

IKEA 官网把"平价家居"讲成民主设计：品牌蓝 `#0058A3` 做导航/页脚/主 CTA、亮黄 `#FFDB00` 做促销与强调；白底 + 大量真实家居场景图（阳光、真实生活）。设计目标：**让顾客想象"我家也可以这样"**——图片比文字优先、产品卡简洁、价格清晰。营销页以房间场景 + 产品清单 + 服务（组装/配送）为主。

### 色彩

画布白 `#FFFFFF`、浅灰 `#F0F0F0`；主蓝 `#0058A3`（logo、导航、主 CTA）、hover `#0B4F8C`；促销黄 `#FFDB00`（价格签、折扣块、强调）；文字 `#111111`、灰 `#595959`；分割线 `#E4E4E4`；成功绿 `#007F00`（有货）。

### 字体

IKEA Sans（源自 Verdana/Noto 定制）或回退 `system-ui, -apple-system, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif`；标题 28–56px SemiBold；价格 18–24px SemiBold tabular；正文 14–16px。

### 布局、间距、圆角与动效

内容 1280px；区块 48–96px；产品卡 8px 圆角、hover 上浮 + 阴影；按钮 8px（蓝实心/白描边黄字）；价格签可用黄底黑字小卡；hero 常为全宽家居场景 + 白字说明；动效 200–300ms。

### HTML CSS Token

```css
/* IKEA — HTML 官网 Token */
--ik-blue: #0058A3;
--ik-blue-hover: #0B4F8C;
--ik-blue-soft: #E6F0F8;
--ik-yellow: #FFDB00;
--ik-bg: #FFFFFF;
--ik-bg-gray: #F0F0F0;
--ik-text: #111111;
--ik-text-subtle: #595959;
--ik-line: #E4E4E4;
--ik-success: #007F00;
--ik-radius-card: 8px;
--ik-radius-btn: 8px;
--ik-font: system-ui, -apple-system, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--ik-space-section: 64px;
--ik-container: 1280px;
--ik-motion: 250ms ease;
/* 应用：导航/主 CTA 蓝；价格签黄底黑字；产品 hover 上浮加阴影 */
```

## 记忆点与应用方式

复现"IKEA 感"三步：①蓝 `#0058A3` 结构 + 黄 `#FFDB00` 促销；②真实家居场景大图 + 简洁产品信息；③价格透明、组件化卡片。做"家居、零售、生活消费"类官网首选（蓝黄即瑞典平价民主设计）。

## 反混搭提示

IKEA 蓝黄是"实用主义"——黄不要大面积铺导航（只做促销/价格）；避免高端冷淡风（IKEA 是平价亲切的）；不要加过多装饰图形，让场景图与产品自己说话。
