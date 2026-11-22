# 生产代码占位与质量信号清单

> 由 `python scripts/quality_inventory.py` 生成 (审计 #32)。口径: 扫描
> `tuan_cli/**.py` (排除 `resources/` 与缓存目录), 正则计数, 可复现。
> 占位多不等于有 bug, 但对「宣称完成的能力」应逐项核销。

| 信号 | 数量 |
|---|---|
| 纯 `pass` / `...` 占位行 | 669 |
| `raise NotImplementedError` | 6 |
| TODO / FIXME 注释 | 0 |
| 裸 `except:` (不绑类型) | 0 |
| 生产代码 `assert` (`python -O` 会跳过) | 28 |
| 扫描文件数 | 741 |

## `raise NotImplementedError` 位置 (至多 20 条)

- `tuan_cli/arch/execution.py:236: raise NotImplementedError`
- `tuan_cli/models/base.py:51: raise NotImplementedError`
- `tuan_cli/runtime/agent/loop.py:131: raise NotImplementedError`
- `tuan_cli/runtime/agent/step_request.py:75: raise NotImplementedError`
- `tuan_cli/runtime/contract.py:285: raise NotImplementedError`
- `tuan_cli/skills/universal_format.py:132: raise NotImplementedError`

## 纯 pass/`...` 占位 Top 15 文件

| 文件 | 数量 |
|---|---|
| `tuan_cli/web/code_anim_render.py` | 30 |
| `tuan_cli/web/server.py` | 23 |
| `tuan_cli/tui/state.py` | 18 |
| `tuan_cli/cli/cmd_chat.py` | 13 |
| `tuan_cli/core/prompts.py` | 12 |
| `tuan_cli/core/tool_executor.py` | 12 |
| `tuan_cli/_http.py` | 11 |
| `tuan_cli/arch/platform.py` | 10 |
| `tuan_cli/tools/filesystem.py` | 10 |
| `tuan_cli/tools/mcp/client.py` | 10 |
| `tuan_cli/web/server_ops.py` | 10 |
| `tuan_cli/runtime/mcp/client_stdio.py` | 8 |
| `tuan_cli/tools/base.py` | 8 |
| `tuan_cli/config/loader.py` | 7 |
| `tuan_cli/memory/store.py` | 7 |

## TODO/FIXME Top 10 文件

| 文件 | 数量 |
|---|---|

## 裸 except Top 10 文件

| 文件 | 数量 |
|---|---|

## 生产代码 assert 分布 (Top 10)

安全路径上的 assert 一律不得承担访问控制/拦截职责 (`python -O` 会整段
跳过)。2026-11-20 人工核查结论: `ext/`、`tools/shell.py`、`security_gate.py`、
`web/server.py`、`sandbox/` 等安全路径上的 assert 均为类型收窄用途,
不承担安全裁决; 本表用于持续监督。

| 文件 | 数量 |
|---|---|
| `tuan_cli/hooks/manager.py` | 3 |
| `tuan_cli/tools/mcp/client.py` | 3 |
| `tuan_cli/agents/base.py` | 2 |
| `tuan_cli/core/path_safety.py` | 2 |
| `tuan_cli/tui/render.py` | 2 |
| `tuan_cli/tui/state.py` | 2 |
| `tuan_cli/core/agent_loop_fusion.py` | 1 |
| `tuan_cli/core/goal_mode.py` | 1 |
| `tuan_cli/ext/script_isolation.py` | 1 |
| `tuan_cli/hooks/exit_semantics.py` | 1 |
