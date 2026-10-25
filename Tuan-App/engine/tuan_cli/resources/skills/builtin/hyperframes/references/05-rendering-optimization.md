# 05 — 渲染性能优化策略

## 1. 分块渲染

长视频按场景分块渲染再拼接，避免内存峰值。

```bash
# 每个场景独立渲染
hyperframes render --scene scene-1 --output scene-1.mp4
hyperframes render --scene scene-2 --output scene-2.mp4

# 拼接
hyperframes merge --inputs scene-*.mp4 --output final.mp4
```

内存峰值从 ~2GB 降至 ~500MB。

## 2. 帧缓存

相同元素的重复帧缓存复用。

```
帧 0:   [元素A] [元素B] [元素C]  → 渲染全部
帧 1:   [元素A*] [元素B] [元素C*] → 仅渲染 A 和 C
帧 2:   [元素A*] [元素B*] [元素C] → 仅渲染 B
```

速度提升 40-60%。

## 3. 并行场景

独立场景可并行渲染。

```bash
# 并行渲染 3 个场景
hyperframes render --parallel 3 --output output.mp4
```

## 4. 分辨率缩放渲染

先渲染 720p 预览，确认后再渲染 1080p 正式版。

```bash
# 快速预览
hyperframes render --resolution 720p --crf 28 --output preview.mp4

# 正式输出
hyperframes render --resolution 1080p --crf 18 --output final.mp4
```

## 5. 字体优化

- 仅加载使用的字体子集
- 使用 `font-display: swap` 避免 FOIT
- 预加载关键字体文件

```html
<link rel="preload" href="font.woff2" as="font" type="font/woff2">
```

## 6. 图像优化

- WebP 格式优先
- 懒加载非首屏图像
- 使用 `will-change` 提示合成层

```css
.animated-element {
  will-change: transform, opacity;
}
```

## 7. GPU 加速

```javascript
// 强制 GPU 合成
element.style.transform = 'translateZ(0)';
element.style.backfaceVisibility = 'hidden';
```

## 性能基准 (参考)

| 场景 | 720p 渲染时间 | 1080p 渲染时间 |
|------|--------------|---------------|
| 30s 纯文本 | 8s | 25s |
| 30s 图文混排 | 15s | 45s |
| 30s 3D 动画 | 45s | 2min |
| 30s 含配音 | 20s | 60s |
