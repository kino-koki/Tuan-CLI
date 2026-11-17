---
name: tuan-a11y
description: >
  无障碍 (Accessibility) 技能。覆盖 WCAG 2.1/2.2 AA/AAA 合规、ARIA 模式、
  屏幕阅读器兼容 (NVDA/VoiceOver/JAWS)、键盘导航、焦点管理、
  色彩对比度、语义 HTML、表单标签、alt 文本、焦点陷阱、
  屏幕阅读器测试、axe DevTools、Lighthouse 无障碍审计、
  可访问性设计模式、移动无障碍、字幕/文字替代、动画偏好。
  当用户要求无障碍、a11y、accessibility、WCAG、ARIA、
  屏幕阅读器、screen reader、键盘导航、对比度、contrast、
  表单可访问性、alt 文本、焦点管理、axe、Lighthouse 无障碍、
  可访问性设计、移动无障碍、字幕时使用。
activation: proactive
priority: 80
provides:
  - accessibility
  - wcag
  - a11y
  - aria
suggests:
  - tuan-design
  - frontend-design
  - tuan-docs
triggers:
  - 无障碍
  - a11y
  - accessibility
  - WCAG
  - ARIA
  - 屏幕阅读器
  - screen reader
  - 键盘导航
  - 对比度
  - contrast
  - 表单可访问性
  - alt 文本
  - 焦点管理
  - axe
  - Lighthouse 无障碍
  - 可访问性设计
  - 移动无障碍
  - 字幕
license: MIT
metadata:
  version: "1.0.0"
---

# TUAN A11Y — 无障碍

## WCAG 2.1/2.2 四大原则

| 原则 | 含义 | 示例 |
|------|------|------|
| 可感知 (Perceivable) | 信息可被感知 | alt 文本、字幕、对比度 ≥ 4.5:1 |
| 可操作 (Operable) | 界面可操作 | 键盘导航、焦点可见、无闪烁 |
| 可理解 (Understandable) | 信息可理解 | 语言声明、错误提示、标签清晰 |
| 健壮 (Robust) | 内容兼容工具 | 语义 HTML、ARIA、标准兼容 |

## ARIA 模式

### 标签 (Labels)

```html
<!-- 按钮 (无 ARIA，语义 HTML) -->
<button>提交</button>

<!-- 图标按钮 (需要 aria-label) -->
<button aria-label="搜索"><svg>...</svg></button>

<!-- 表单标签 -->
<label for="email">邮箱</label>
<input id="email" type="email" required aria-describedby="email-hint">
<small id="email-hint">不会公开显示</small>
```

### 对话框 / 模态框

```html
<div role="dialog" aria-modal="true" aria-labelledby="modal-title">
  <h2 id="modal-title">确认操作</h2>
  <p>确定要删除吗？此操作不可撤销。</p>
  <button autofocus>删除</button>
  <button>取消</button>
</div>
```

### 标签页 (Tabs)

```html
<div role="tablist">
  <button role="tab" aria-selected="true" aria-controls="tab-1" id="tab-1-btn">概览</button>
  <button role="tab" aria-selected="false" aria-controls="tab-2" id="tab-2-btn">设置</button>
</div>
<div role="tabpanel" id="tab-1" aria-labelledby="tab-1-btn">...</div>
<div role="tabpanel" id="tab-2" aria-labelledby="tab-2-btn" hidden>...</div>
```

### 状态指示

```html
<!-- 加载状态 -->
<div role="status" aria-live="polite">加载中...</div>

<!-- 错误消息 -->
<div role="alert" aria-live="assertive">保存失败，请重试</div>

<!-- 进度条 -->
<div role="progressbar" aria-valuenow="75" aria-valuemin="0" aria-valuemax="100">
  75%
</div>
```

## 色彩对比度

| 级别 | 文本 | 大号文本 (≥18px) | UI 组件 |
|------|------|-----------------|---------|
| AA | ≥ 4.5:1 | ≥ 3:1 | ≥ 3:1 |
| AAA | ≥ 7:1 | ≥ 4.5:1 | ≥ 4.5:1 |

```css
/* 检查对比度 */
/* 正常文本: #333 on #fff = 12.6:1 (AAA) */
/* 大号文本: #666 on #fff = 5.7:1 (AA) */
/* 失败: #999 on #fff = 2.85:1 (需要 4.5:1) */

/* 好的设计系统 */
:root {
  --text-primary: #1a1a1a;    /* 16:1 on white */
  --text-secondary: #555;     /* 7.5:1 on white */
  --text-disabled: #999;      /* 2.85:1 — 仅装饰，不承载信息 */
  --accent: #d97757;          /* 4.7:1 on white — AA for large text */
}
```

## 键盘导航

```
Tab / Shift+Tab    : 在可聚焦元素间移动
Enter / Space      : 激活按钮/链接
Escape             : 关闭模态框/下拉菜单
Arrow keys         : 标签页/列表/树形控件
Home / End         : 首项/末项
Ctrl+Home/End      : 页面顶部/底部
```

### 焦点管理

```javascript
// 模态框打开: 聚焦第一个元素
modal.focus();

// 焦点陷阱: Tab 不逃出模态框
function trapFocus(container) {
  const focusable = container.querySelectorAll(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
  );
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  
  container.addEventListener('keydown', (e) => {
    if (e.key === 'Tab') {
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    if (e.key === 'Escape') {
      container.closest('[role="dialog"]').remove();
    }
  });
}
```

## 表单无障碍

```html
<form aria-labelledby="form-title">
  <h2 id="form-title">注册</h2>
  
  <div>
    <label for="name">姓名 <span aria-hidden="true">*</span></label>
    <input id="name" type="text" required aria-required="true" 
           aria-invalid="false" aria-describedby="name-error">
    <div id="name-error" role="alert" hidden>请输入姓名</div>
  </div>
  
  <div>
    <label for="email">邮箱 <span aria-hidden="true">*</span></label>
    <input id="email" type="email" required 
           aria-describedby="email-hint">
    <small id="email-hint">我们不会公开显示你的邮箱</small>
  </div>
  
  <button type="submit" aria-describedby="submit-hint">注册</button>
  <span id="submit-hint">注册即同意服务条款</span>
</form>
```

## 检查清单

### HTML 语义
- [ ] 使用语义标签 (header/nav/main/section/article/footer)
- [ ] 标题层级正确 (h1 → h2 → h3，不跳级)
- [ ] 链接有描述性文本 (不用"点击这里")
- [ ] 按钮 vs 链接使用正确
- [ ] 表格有 caption 和 th

### ARIA
- [ ] 优先使用语义 HTML，ARIA 作为补充
- [ ] 动态内容用 aria-live
- [ ] 模态框用 role="dialog" + aria-modal
- [ ] 错误消息用 role="alert"
- [ ] 加载状态用 role="status"

### 视觉
- [ ] 文本对比度 ≥ 4.5:1 (AA)
- [ ] 焦点指示器可见 (outline / box-shadow)
- [ ] 图标有 aria-label 或 title
- [ ] 图片有 alt 文本
- [ ] 无闪烁 (≤ 3 次/秒)

### 交互
- [ ] 所有交互元素可键盘访问
- [ ] 焦点顺序合理
- [ ] 模态框焦点陷阱
- [ ] Escape 关闭模态框
- [ ] 不依赖鼠标 (纯键盘可操作)
```
