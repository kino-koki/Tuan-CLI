# 四道安全闸门

> 本条目对应 `tuan_cli/ext/safety_redline.py`、`tuan_cli/core/write_boundary.py`、`tuan_cli/core/ledger.py`、`tuan_cli/sandbox/manager.py`。

## 是什么

青小团的安全叙事是 **blast-radius 预览 → 硬红线 → 精确 /undo** 的四层闸门：

1. **硬红线（Hard Redline）**：`ext/safety_redline.py` 的 `is_hard_redline` 类判定，拦截绝对禁止的高危命令（rm -rf、磁盘格式化、凭证外泄等）。`is_system_critical` 盘符无关判定（Windows/Linux 统一）。
2. **YOLO 红线**：`sandbox/manager.py` 的 `assess_tool/assess_command` 把工具/命令归一化成 Payload，跑完整滤网返回裁决；`yolo=bool(getattr(ctx,"yolo",False))` 时 `require_confirm=False`，YOLO 模式仍走滤网（不绕过）。
3. **事务账本（Ledger）**：`core/ledger.py:294-360` 的 `undo_last/undo_file/undo_all/undo_since`，支持精确回滚单个文件或整批操作。
4. **写边界（Write Boundary）**：`core/write_boundary.py` 模块 + `blockWritesOutsideWorkingDirectories` + `/add-dir` 可写认证，把写路径硬约束在工作目录内。

## 为什么

这是"**safety-first**"的立身之本：0 星也要先证明"不会炸掉用户机器"，再谈能力。四道闸门逐层收紧，任一命中即拦截，且事务账本保证可恢复。

## 关键文件

| 文件 | 闸门 |
|---|---|
| `ext/safety_redline.py` | 硬红线（约 1426 行起类判定） |
| `sandbox/manager.py` | YOLO 红线 + assess_tool/assess_command 滤网 |
| `core/ledger.py` | 事务账本 /undo |
| `core/write_boundary.py` | 写边界模块 |
| `config/security_schema.py` | 安全配置 schema |

## 卖点

- 四道闸门全部**贯通**（诊断 2026-11-15 逐项核实）。
- 写边界 `set_user/delete_user` 用 `dump_yaml_checked` 如实返回落盘成败，**只在真正落盘成功时派发 ConfigChange**（B3 续轮回归已根治，27 测试绿）。
- 审批重入 **fail-closed**（决策类绝不放行）。
- 配置写失败绝不误导外部 hook"配置已生效"。

## 局限

- `sandbox/manager.py` 的 YOLO 红线依赖 ctx.yolo 属性，需上层显式传递。
- 事件总线溢出（2000 条）可能丢超旧事件（有意设计）。
