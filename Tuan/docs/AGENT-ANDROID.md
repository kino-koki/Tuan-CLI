# Android 轻量 Agent

移动端没有本地 Python 引擎，`tuan_cli` 的完整 agent 能力（系统提示词分层、子 agent、
MCP、代码执行、安全闸门）无法直接搬过来。本模块用 Rust 复刻其中**在手机沙箱内真正
可用的那一部分**，代价是包体几乎不增（不打包解释器）。

实现：`src-tauri/src/agent.rs`（主循环）+ `src-tauri/src/agent_tools.rs`（工具集）。

## 路由

| 平台 | 通道 | 说明 |
|---|---|---|
| Windows / macOS | `engine_chat_stream` | 走 `tuan_cli` 引擎，能力最全 |
| Android（Agent 开） | `agent_chat_stream` | 本模块，Rust 侧工具调用循环 |
| Android（Agent 关） | `chat_stream` | 退化为纯对话 |
| 网页预览 | 浏览器 fetch | 仅开发预览 |

平台判定在 `src/platform/engine.ts` 的 `isAndroid()`：Tauri 的 `isTauri()` 在安卓同样
返回 true，无法区分，必须按 UA 判断。

## 工具集

只收录**不需要额外权限**的工具。手机没有 shell、没有任意路径读写、没有本地进程，
因此不移植 `code` / `shell` / `backend_dev` / `image_gen` 等依赖本地执行的工具。

| 工具 | 作用 | 实现 |
|---|---|---|
| `web_search` | 联网搜索 | DuckDuckGo HTML 端点，免密钥 |
| `web_fetch` | 抓取网页/接口正文 | reqwest + 内置 HTML→文本提取 |
| `calc` | 精确算术 | 递归下降求值，支持 `+ - * / % ^` 与括号 |
| `note` | 记录笔记 | 会话内累积，供模型后续引用 |

## 循环流程

```
用户提问
  → 模型请求（带 tools schema）
  → 无 tool_calls？→ 输出文本，结束
  → 有 tool_calls？→ 回显 tool 事件 → 逐个执行 → 结果回灌消息序列
  → 下一轮（最多 MAX_ROUNDS = 8 轮）
```

事件契约与引擎一致：`text` / `tool` / `tool_result` / `done` / `error`，
前端 `App.tsx` 无需区分平台即可渲染工具执行过程。

协议双向兼容：
- **OpenAI 兼容**：`tools: [{type:"function",...}]`，回灌 `role:"tool"` + `tool_call_id`
- **Anthropic**：`tools: [{name, description, input_schema}]`，回灌 `tool_use` / `tool_result` block

不支持函数调用的模型会自动降级为普通对话（`tool_choice: "auto"` 语义）。

## 安全与边界

- **工具执行有上限**：单次输出截断 4KB，HTTP 响应截断 200KB，轮次上限 8 轮，
  防止模型陷入死循环烧流量或大段内容挤爆移动端内存
- **能力边界写进系统提示词**：明确告知模型无法执行 shell、无法改动代码工程、
  无法访问任意文件，遇到这类任务应引导用户去桌面端——避免模型承诺做不到的事
- **工具失败如实上报**：`is_error` 标记回传，失败时提示词要求模型不得假装成功
- `web_fetch` 仅允许 http/https，拦截 `file://` 等本地协议

## 已知限制

1. **搜索依赖 DuckDuckGo HTML 端点**，无正式 SLA，可能被限流或改版失效。
   接入正式搜索 API 时只需替换 `run_tool` 中该分支，工具契约（入参/返回）对模型不变。
2. **无持久化**：会话内的 `note` 只在单轮循环中累积，不落盘。
3. **无子 agent / MCP / 代码执行**：这些依赖本地进程，沙箱内不可用。
4. `html_to_text` 是轻量提取器（非完整 HTML parser），对复杂动态页面效果有限。

## 开关

设置 → 外观 → 轻量 Agent。持久化键 `tuan.agentMode`，默认开启。
关闭后安卓退化为纯对话，工具调用不会被触发。