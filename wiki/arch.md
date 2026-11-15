# 分层抽象（arch）

> 本条目对应 `tuan_cli/arch/`（7 文件/1182 行）。

## 是什么

青小团的**分层抽象层**（融合 DeepSeek Harness 理念）：

- `arch/context.py`：执行上下文（会话、owner、事务）。
- `arch/execution.py`：执行模型。
- `arch/platform.py`：平台抽象（路径、OS 差异）。
- `arch/observability.py`：轨迹/归因存储。
- `arch/security.py`：安全策略层。
- `arch/orchestration.py`：编排抽象。
- `arch/plugin.py`：插件基类/接口。

## 为什么

把"平台相关"与"平台无关"分离，让青小团在 Windows/Linux/macOS 上行为一致（如 `is_system_critical` 盘符无关判定）。

## 关键文件

| 文件 | 职责 |
|---|---|
| `arch/context.py` | 执行上下文 |
| `arch/platform.py` | 平台抽象 |
| `arch/security.py` | 安全策略层 |
| `arch/orchestration.py` | 编排抽象 |

## 卖点

- 平台抽象统一（Windows 路径/盘符无关判定已修）。
- 执行上下文携带 owner（线程安全，contextvar）。

## 局限

- 轨迹存储无 trace_id 传播（待补）。
