# 人机交互：TUI / UI 双栈与主题

> 本条目对应 `tuan_cli/tui/`（44 文件/16202 行）、`tuan_cli/ui/`（31 文件/5779 行）、`tuan_cli/ui/theme.py`。

## 是什么

青小团有两套渲染栈，且已收敛到**主题 token 单一来源**（AGENT-EVOLUTION-ROADMAP 阶段 D）：

- **UI 权威渲染层**（`ui/`）：splash、mascot、theme、approval_overlay、repl。`ui/theme.py` 是 `BRAND_PRIMARY`/`BRAND_SECONDARY` 的**唯一定义**。
- **TUI 兼容壳**（`tui/`，40+ 文件）：`common.py`、`kimi_modules.py`、`tui.py` 等，全部改 import token（不再硬编码品牌色），保留为交互壳。
- **主题一致性测试**（`tests/test_theme_consistency.py`）：全库扫描确认无游离品牌色硬编码（#63A8F8/#5BC0BE 直写命中为 0）。

## 为什么

双栈并存曾导致"两套颜色、两套提示语、主题不统一"。阶段 D 把 token 收敛到 `theme.py` 单一来源，TUI 引用同一 token，消除歧义。

## 关键文件

| 文件 | 职责 |
|---|---|
| `ui/theme.py` | BRAND_PRIMARY/BRAND_SECONDARY 唯一 token |
| `ui/splash.py` | 启动画面（引用 token） |
| `ui/mascot.py` | 吉祥物（引用 token） |
| `ui/approval_policy.py` | 审批树（阶段 C） |
| `tui/tui.py` | TUI 交互（键盘/鼠标 support，`mouse_support` 975 行） |
| `tui/common.py` | TUI 通用（引用 token） |
| `tui/kimi_modules.py` | Kimi 模块（引用 token） |

## 卖点

- 主题 token 单一来源（全库无游离品牌色硬编码）。
- TUI 有 `mouse_support`、focus、key_bindings（键盘/鼠标完整）。
- 17 个新主题一致性测试 + 90 渲染回归通过（阶段 D 验收）。

## 局限

- TUI 无 aria/screen-reader 支持（可访问性待补）。
- TUI 内部有局部色常量（`_SUCCESS="#4EC87E"` 等）未全部走 theme.py（诊断 2026-11-15）。
