# 沙箱与出站管控

> 本条目对应 `tuan_cli/sandbox/`（12 文件/2961 行）。

## 是什么

青小团的命令/工具执行滤网：

- `manager.py`：`assess_tool` / `assess_command` 把工具或命令归一化成 Payload，跑完整滤网，返回裁决（`sandbox/manager.py:271,362`）。
- `filters.py`：具体过滤规则。
- `verdict.py`：裁决模型（`Action.CONFIRM` 等）。
- `egress_plan.py`：出站计划 `plan_egress`（网络/文件出站管控）。
- `unattended.py`：无人值守模式。

## 为什么

四道闸门中的 YOLO 红线与出站管控都在 sandbox 层实现：任何工具/命令执行前必须过滤网，`run_shell` 经 `assess_command` + `plan_egress` + 净化环境。

## 关键文件

| 文件 | 职责 |
|---|---|
| `sandbox/manager.py` | assess_tool / assess_command 滤网 |
| `sandbox/filters.py` | 过滤规则 |
| `sandbox/verdict.py` | 裁决模型 |
| `sandbox/egress_plan.py` | 出站计划 |
| `sandbox/unattended.py` | 无人值守 |

## 卖点

- YOLO 红线贯通：`yolo=bool(getattr(ctx,"yolo",False))`，YOLO 模式仍走滤网（不绕过）。
- `assess_command` 把命令归一化成 Payload 跑完整滤网。
- 出站计划 `plan_egress` 管控网络/文件出站。

## 局限

- YOLO 红线依赖 `ctx.yolo` 属性，需上层显式传递。
- 滤网规则为内部代码，无外部规则 DSL 文档化。
