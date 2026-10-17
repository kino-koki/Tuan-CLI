# 71. LEGO — 拼搭玩具 乐高红

> **类型**：品牌 | **领域**：积木玩具 | **设计哲学**：让想象力可见的积木乐园

| 规格总览 | 值 |
|---|---|
| 画布色 | `#FFFFFF` 白 / 浅灰 |
| 强调色 | `#D01012` LEGO红 + 黄 `#FFCF00` |
| 字体策略 | LEGO 圆润粗体（自研）/ 系统栈 |
| 记忆点 | 乐高红 + 圆角积木卡 |

## 官网板块 · 数字化品牌体验

### 设计哲学

LEGO 官网是"彩色积木美学"的极致：乐高红 `#D01012` 为品牌主色，搭配黄 `#FFCF00`、蓝 `#006DB7`、绿 `#00A651` 的积木色板；圆角、胖圆图标、拼搭中的积木图形无处不在。设计目标是**让大人和孩子都愿意停留**——色彩饱满但不刺眼、卡片圆润、动效活泼。营销页以"主题套装 + 拼搭过程 + 角色故事"为主。

### 色彩

画布白 `#FFFFFF`、浅灰 `#F4F4F4`；主强调红 `#D01012`（logo、主 CTA）、辅黄 `#FFCF00`（促销、Star 徽章）、蓝 `#006DB7`（次要行动/链接）；绿积木 `#00A651`；文字 `#1A1A1A`、灰 `#5F5F5F`；描边可做积木拼缝 `#E0DCD3`。

### 字体

LEGO 自研圆润粗体（可回退 `'Baloo', 'Arial Rounded MT Bold', system-ui`）；标题 32–64px Heavy/Extrabold；正文 14–16px；中文思源黑体 Heavy + PingFang SC。

### 布局、间距、圆角与动效

内容 1280px；区块 56–96px；卡片 16–24px 圆角（**可大圆角积木感**）、hover 上浮 4px + 阴影；按钮 12px 圆角（红实心/白描边）；hero 常为套装大图 + 黄底标题；动效 250–400ms 带 bounce、产品 hover 微弹。

### HTML CSS Token

```css
/* LEGO — HTML 官网 Token */
--lg-red: #D01012;
--lg-red-hover: #A80C0E;
--lg-yellow: #FFCF00;
--lg-blue: #006DB7;
--lg-green: #00A651;
--lg-bg: #FFFFFF;
--lg-bg-gray: #F4F4F4;
--lg-text: #1A1A1A;
--lg-text-subtle: #5F5F5F;
--lg-notch: #E0DCD3;
--lg-radius-card: 20px;
--lg-radius-btn: 12px;
--lg-font-display: 'LEGO', 'Baloo', 'Arial Rounded MT Bold', 'PingFang SC', 'Microsoft YaHei', sans-serif;
--lg-font-body: system-ui, -apple-system, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
--lg-space-section: 72px;
--lg-motion: 300ms cubic-bezier(0.2, 1.4, 0.4, 1);
/* 应用：主 CTA 红实心 12px 圆角；卡片 20px 大圆角；黄底标题块可做促销 */
```

## 记忆点与应用方式

复现"LEGO 感"三步：①乐高红 `#D01012` 主色 + 黄/蓝/绿积木色板；②圆角 20px 卡片 + 胖圆图形 + 可加积木拼缝纹理；③动效带 bounce、文案充满"拼搭乐趣"。做"玩具、儿童、家庭消费、快乐品牌"类官网首选。

## 反混搭提示

LEGO 是"高饱和但有序"——不要把积木色板全部铺满一个页面（红黄蓝绿各司其职）；避免做极简冷淡风（削弱品牌快乐感）；圆角可以大但按钮也要 12px 以上保持拥抱感。
