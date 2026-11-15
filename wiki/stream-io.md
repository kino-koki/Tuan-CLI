# 流式 I/O（stream-json）

> 本条目对应 `tuan_cli/stream_json/`（5 文件/1219 行）、`tuan_cli/cli/subcommands/core_runtime.py`。

## 是什么

对标 Claude Code 的 **stream-json 线协议适配层**（转写自 TS 引擎）：

- `schema.py`：消息级事件流 wire protocol（system/init、assistant、user、result）。
- `translate.py`：信封序列。
- `headless.py`：headless 驱动器（`input_format="stream-json"`、`output_format="stream-json"`）。
- `__main__.py`：供 electron 壳拉起的 CLI 驱动器（`--input-format stream-json --output-format stream-json`，校验输入/输出格式）。
- `cli/cmd_agents.py:105`：把 agent 流式回调转成 NDJSON 事件行。

## 为什么

让青小团能被 **electron 桌面壳 / 外部宿主**以消息级流式协议驱动，而非只面向交互式终端。这是"headless 可嵌入"的关键。

## 关键文件

| 文件 | 职责 |
|---|---|
| `stream_json/schema.py` | wire protocol |
| `stream_json/headless.py` | headless 驱动器 |
| `stream_json/__main__.py` | CLI 驱动器（输入/输出格式校验） |
| `stream_json/translate.py` | 信封序列 |
| `cli/subcommands/core_runtime.py` | 输出格式 choices（text/json/stream-json） |

## 卖点

- `--input-format stream-json` 与 `--output-format stream-json` **均已实现**（headless 驱动器，诊断 2026-11-15 核实）。
- 消息级事件流（Anthropic 风格 message + content blocks）。
- `system/init` 首事件携带会话/工作区/模型元信息。

## 局限

- 流式输入**仅** headless 驱动器支持；主 CLI 无独立 `--input-format` 分支（诊断初报误判，实际已实现于 headless）。
