# 02 — 动画模式库 (20+ 种)

## 入场动画 (Entrance)

### fade-slide-up
淡入 + 从下方滑入，最通用。
```css
@keyframes fade-slide-up {
  from { opacity: 0; transform: translateY(40px); }
  to { opacity: 1; transform: translateY(0); }
}
```

### spring-pop
弹性弹出，适合数字/徽章。
```css
@keyframes spring-pop {
  0% { opacity: 0; transform: scale(0.3); }
  50% { transform: scale(1.2); }
  70% { transform: scale(0.95); }
  100% { opacity: 1; transform: scale(1); }
}
```

### stagger-reveal
元素逐个淡入，间隔 80ms。
```javascript
// 时间轴定义
elements: [
  { selector: ".item:nth-child(1)", delay: 0.0 },
  { selector: ".item:nth-child(2)", delay: 0.08 },
  { selector: ".item:nth-child(3)", delay: 0.16 },
]
```

### blur-focus
模糊聚焦入场。
```css
@keyframes blur-focus {
  from { opacity: 0; filter: blur(10px); }
  to { opacity: 1; filter: blur(0); }
}
```

## 文本动画 (Text)

### typewriter
打字机效果。
```css
@keyframes typewriter {
  from { width: 0; }
  to { width: 100%; }
}
```

### letter-spacing-expand
字间距展开，适合标题。
```css
@keyframes letter-spacing-expand {
  from { letter-spacing: 20px; opacity: 0; }
  to { letter-spacing: 2px; opacity: 1; }
}
```

### word-highlight
关键词高亮扫过。
```css
@keyframes word-highlight {
  from { background-position: -100% center; }
  to { background-position: 100% center; }
}
```

## 容器动画 (Container)

### card-flip
卡片翻转，3D 效果。
```css
@keyframes card-flip {
  from { transform: perspective(800px) rotateY(-90deg); opacity: 0; }
  to { transform: perspective(800px) rotateY(0); opacity: 1; }
}
```

### slide-in-right
从右侧滑入。
```css
@keyframes slide-in-right {
  from { opacity: 0; transform: translateX(60px); }
  to { opacity: 1; transform: translateX(0); }
}
```

### scale-bounce
缩放弹跳，适合图标。
```css
@keyframes scale-bounce {
  0% { transform: scale(0); }
  60% { transform: scale(1.3); }
  80% { transform: scale(0.9); }
  100% { transform: scale(1); }
}
```

## 数据动画 (Data)

### count-up
数字递增动画。
```css
@keyframes count-up {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}
```

### bar-grow
条形图生长。
```css
@keyframes bar-grow {
  from { transform: scaleY(0); }
  to { transform: scaleY(1); }
}
```

### pie-sweep
饼图扫描。
```css
@keyframes pie-sweep {
  from { stroke-dashoffset: 314; }
  to { stroke-dashoffset: var(--target-offset); }
}
```

## 转场动画 (Transitions)

### fade
淡入淡出。
### slide-left / slide-right
左右滑动。
### zoom-in / zoom-out
缩放转场。
### wipe
擦除转场。
### flip-horizontal / flip-vertical
翻转转场。
