# ACP 接入

> 本条目对应 `tuan_cli/runtime/acp/`（4 文件/529 行）。

## 是什么

青小团的 **ACP 客户端/服务端握手层**：

- `runtime/acp/bridge.py`：ACP 桥（elicitation RPC 携带会话 owner）。
- `runtime/acp/protocol.py`：握手协议。
- `runtime/acp/server.py`：服务端。
- `runtime/acp/version.py`：版本协商。

## 为什么

让青小团**作为 ACP 客户端/服务端与其它宿主握手**，实现跨宿主互操作（如 elicitation 时正确归属会话）。

## 关键文件

| 文件 | 职责 |
|---|---|
| `runtime/acp/bridge.py` | ACP 桥 |
| `runtime/acp/protocol.py` | 握手协议 |
| `runtime/acp/server.py` | 服务端 |

## 卖点

- ACP 桥 elicitation RPC 用 `_resolve_owner`（显式 owner → ctx 句柄 → contextvar）携带会话标识。
- MCP/ACP 互操作完整。

## 局限

- ACP 服务端依赖宿主进程存活。
