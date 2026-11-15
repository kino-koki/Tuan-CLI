# 主题系统

> 本条目对应 `tuan_cli/ui/theme.py`。

## 是什么

青小团的**主题 token 单一来源**：

- `ui/theme.py`：`BRAND_PRIMARY`/`BRAND_SECONDARY` 的**唯一定义**。
- `ui/splash.py`、`ui/mascot.py`：引用 token。
- `tui/`：`common.py`、`kimi_modules.py`、`tui.py` 全部改 import token。
- `tests/test_theme_consistency.py`：全库扫描确认无游离品牌色硬编码（#63A8F8/#5BC0BE 直写命中为 0）。

## 为什么

双栈（`tui/` 与 `ui/`）并存曾导致"两套颜色、两套提示语、主题不统一"。阶段 D 把 token 收敛到 `theme.py` 单一来源，TUI 引用同一 token，消除歧义。

## 关键文件

| 文件 | 职责 |
|---|---|
| `ui/theme.py` | BRAND_PRIMARY/BRAND_SECONDARY 唯一 token |
| `tests/test_theme_consistency.py` | 一致性扫描 |

## 卖点

- 主题 token 单一来源。
- 全库无游离品牌色硬编码。
- 17 新测试 + 90 渲染回归通过（阶段 D 验收）。

## 局限

- TUI 内部有局部色常量（`_SUCCESS="#4EC87E"` 等）未全部走 theme.py。
