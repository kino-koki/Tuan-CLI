# 04 — 设计系统套用规范

## 自动检测流程

1. 检查项目根目录是否存在 `.tuan/design-system.json`
2. 检查是否安装了 `tuan-design` 技能
3. 检测 `package.json` 中的设计系统依赖
4. 回退到默认 Anthropic 风格

## 设计系统映射

```json
{
  "anthropic": {
    "css_tokens": {
      "surface-page": "#faf9f5",
      "text-primary": "#141413",
      "accent-primary": "#d97757",
      "accent-secondary": "#6a9bcc",
      "accent-tertiary": "#788c5d"
    },
    "fonts": {
      "display": "'Poppins', 'Arial', sans-serif",
      "body": "Georgia, 'Times New Roman', serif"
    },
    "spacing": { "xs": 4, "sm": 8, "md": 16, "lg": 32, "xl": 64 }
  },
  "apple": {
    "css_tokens": {
      "surface-page": "#ffffff",
      "text-primary": "#1d1d1f",
      "accent-primary": "#0071e3"
    },
    "fonts": {
      "display": "-apple-system, 'SF Pro Display', sans-serif",
      "body": "-apple-system, 'SF Pro Text', sans-serif"
    }
  }
}
```

## CSS 变量注入

HyperFrames 在渲染时自动注入设计系统 CSS 变量到 HTML 的 `<head>` 中：

```html
<style>
  :root {
    /* 自动注入的设计系统 Token */
    --surface-page: #faf9f5;
    --accent-primary: #d97757;
    /* ... */
  }
</style>
```

## 视频中的设计约束

1. **对比度**：文字与背景的对比度 ≥ 4.5:1 (WCAG AA)
2. **字号**：标题 ≥ 48px，正文 ≥ 24px，字幕 ≥ 28px
3. **安全区**：文字距边缘 ≥ 80px，字幕距底边 ≥ 80px
4. **颜色循环**：多形状循环使用强调色时，按橙→蓝→绿→橙顺序
5. **禁止**：纯黑 `#000` 和纯白 `#fff`

## 与 Tuan-Design 技能联动

```
1. Agent 加载 HyperFrames 技能
2. HyperFrames 检测到 tuan-design 已安装
3. 自动读取 .tuan/design-system.json 或 ~/.tuan/skills/tuan-design/SKILL.md
4. 提取 CSS Token
5. 注入到视频 HTML 中
6. 渲染时保持设计一致性
```

## 品牌一致性检查清单

- [ ] 色彩与网站/品牌指南一致
- [ ] 字体与品牌一致
- [ ] 间距节奏与品牌一致
- [ ] 动画缓动与品牌一致
- [ ] 无 emoji
- [ ] 无纯黑/纯白
