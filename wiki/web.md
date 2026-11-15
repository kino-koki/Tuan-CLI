# Web / 桌面端

> 本条目对应 `tuan_cli/web/`（16 文件/11833 行）、`tuan_cli/app_desktop.py`、`tuan_cli/cli/cmd_web.py`。

## 是什么

青小团的 Web 工作台与桌面壳：

- **Web 工作台**（`web/`）：`dispatch_server.py`（Agent-of-Agents 派发 + mode/health 路由）、Web 界面。
- **桌面壳**（`app_desktop.py`）：electron 壳入口，拉起 `tuan_cli.stream_json` headless 驱动器。
- **Web 命令**（`cmd_web.py`、`cmd_webcache.py`、`cmd_web_audit.py`）：Web 服务、缓存、审计。

## 为什么

青小团不只有终端：Web 工作台让非开发者也能用，桌面壳让 stream-json 协议可嵌入。

## 关键文件

| 文件 | 职责 |
|---|---|
| `web/dispatch_server.py` | 派发服务器 |
| `app_desktop.py` | 桌面壳 |
| `cli/cmd_web.py` | Web CLI |

## 卖点

- dispatch_server 支持 mode/health 路由（Agent-of-Agents）。
- 桌面壳经 stream-json 驱动（输入/输出校验）。
- Web 审计（web_audit）与缓存（webcache）齐备。

## 局限

- Web 层依赖外部进程/网络，偶发争用（诊断：ipc 全量并行 60s 超时环境相关）。
