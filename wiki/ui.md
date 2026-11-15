# UI 权威渲染层

> 本条目对应 `tuan_cli/ui/`（31 文件/5779 行）。

## 是什么

青小团的**权威渲染层**（阶段 D 定 `ui/` 为权威、`tui/` 为兼容壳）：

- `ui/splash.py`：启动画面。
- `ui/mascot.py`：吉祥物。
- `ui/theme.py`：主题 token 单一来源。
- `ui/approval_overlay.py`：审批浮层。
- `ui/approval_policy.py`：审批树（阶段 C）。
- `ui/repl.py`：REPL。

## 为什么

收敛 `tui/` 与 `ui/` 双渲染栈，明确单一入口（`ui/` 为权威），消除"两套颜色/提示语"歧义。

## 关键文件

| 文件 | 职责 |
|---|---|
| `ui/theme.py` | BRAND_PRIMARY/BRAND_SECONDARY 唯一 token |
| `ui/splash.py` | 启动画面 |
| `ui/approval_policy.py` | 审批树 |
| `ui/repl.py` | REPL |

## 卖点

- `ui/` 为权威渲染层，主题 token 单一来源。
- 审批树（ApprovalTree）分层路由。

## 局限

- 与 `tui/` 仍有少量职责重叠（需持续收敛）。
