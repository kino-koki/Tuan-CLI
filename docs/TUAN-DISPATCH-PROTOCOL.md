# Tuan Dispatch Protocol v1.0

> Tuan-Chat 手机端 ⇄ 桌面端（Tauri/Tuan-App）之间的 WebSocket 调度协议。
> 桌面端把「任务」路由给本机 5 家本地代理（Claude Code / CodeX / hermes / DeepSeek Harness / Kimi Code），
> 手机只做「发起 + 看流 + 审批 + 取消」。
>
> 版本策略：协议主版本 = URL 路径段 `/tuan/dispatch/v1`。不兼容变更升 v2。

---

## 1. 传输层

- **协议**：WebSocket，明文 `ws://` 局域网直连，公网 `wss://`（TLS 由反向代理或桌面端 cert 提供）。
- **路径**：`/tuan/dispatch/v1`
- **默认端口**：桌面端 `8788`（避开通用 8080/8765；Tuan-CLI Web 是 `8765`）
- **编码**：UTF-8 JSON。
- **帧上限**：单条消息 ≤ 256 KB（附件走文件通道，不走协议帧）。
- **心跳**：客户端每 30s 发 `{"type":"ping"}`，服务端 60s 未收到视为掉线。

## 2. 消息信封

每条消息都是 JSON 对象，必带 `type` 字段。未知 `type` 接收方必须忽略（前向兼容）。

```jsonc
{ "type": "hello", "protocol": 1, ... }
```

## 3. 握手：hello / pair

### 3.1 Server → Client：`hello`

连接建立后服务端立即下发（不需要客户端先说话）：

```jsonc
{
  "type": "hello",
  "protocol": 1,
  "hostname": "DESKTOP-ABC1234",
  "version": "0.3.2",
  "build": "20261024",
  "auth_required": true,
  "pair_code": "AB12",           // 4 位大写字符, 服务端生成, 展示在桌面 UI
  "agents": [
    {"id": "claude-code",       "name": "Claude Code",       "path": "C:\\Users\\...\\claude.exe", "healthy": true,  "version": "1.2.3"},
    {"id": "codex",             "name": "Codex",             "path": null,                            "healthy": false, "version": null, "reason": "not found in PATH"},
    {"id": "hermes",            "name": "Hermes",            "path": "/usr/local/bin/hermes",         "healthy": true,  "version": "unknown"},
    {"id": "deepseek-harness",  "name": "DeepSeek Harness",  "path": "C:\\dsh\\dsh.exe",               "healthy": true,  "version": "0.6.x"},
    {"id": "kimi-code",         "name": "Kimi Code",         "path": "/opt/kimi/bin/kimi-code",       "healthy": true,  "version": "unknown"}
  ],
  "mode": "chat"                 // 桌面当前 Tuan-CLI 模式 (chat/collaboration/gantong/lingma/boundless)
}
```

`agents[]` 是**实时探测结果**（每次连接时重新扫 PATH），不是缓存。手机端据此渲染可选代理列表。

### 3.2 Client → Server：`pair`

```jsonc
{ "type": "pair", "code": "AB12" }
```

### 3.3 Server → Client：`pair_ok` / `error`

```jsonc
{ "type": "pair_ok", "session": "s-a1b2c3d4", "ttl": 3600 }
```

失败：

```jsonc
{ "type": "error", "code": "INVALID_PAIR_CODE", "message": "配对码错误" }
```

服务端立即关闭连接（`close(code=4401)`）。

## 4. 任务分发：dispatch / accepted

### 4.1 Client → Server：`dispatch`

```jsonc
{
  "type": "dispatch",
  "task": {
    "id": "t-001",                      // 客户端生成, ULID 或 uuid4
    "prompt": "帮我把 src/a.py 里的 print 全换成 logging",
    "agent": "auto",                    // "auto" 或具体 id: claude-code/codex/hermes/deepseek-harness/kimi-code
    "mode": "chat",                     // 桌面 Tuan-CLI 模式
    "cwd": "/workspace/proj",           // 可选; null = 桌面默认 cwd
    "attachments": [                    // 可选; 只支持 text/* 小文件
      {"name": "a.py", "content_b64": "..."}
    ]
  },
  "options": {
    "stream": true,
    "timeout_sec": 600,
    "auto_approve_low_risk": true,
    "language": "zh-CN"
  }
}
```

### 4.2 Server → Client：`accepted`

```jsonc
{
  "type": "accepted",
  "task_id": "t-001",
  "routed_to": "claude-code",          // 路由器实际选中的 agent id
  "started_at": 1732358400
}
```

路由器选了 `auto` 时，服务端必须回显最终选中的 agent，手机端高亮显示。

## 5. 事件流：event

服务端把本地代理的 stdout/stderr/工具调用/审批请求等，按 seq 顺序流式推给客户端。

```jsonc
{
  "type": "event",
  "task_id": "t-001",
  "seq": 1,                            // 从 1 开始递增, 严格单调
  "kind": "text",                      // text | tool_call | approval | stderr | error | done | meta
  "data": { ... }                      // kind 相关负载, 见下
}
```

### 5.1 kind = `text`（代理输出的自然语言文本片段）

```jsonc
{ "kind": "text", "data": { "text": "我看了一下 a.py，里面有 3 处 print…" } }
```

### 5.2 kind = `tool_call`（代理调用工具，可能是文件读写、shell 执行）

```jsonc
{
  "kind": "tool_call",
  "data": {
    "tool": "edit",
    "target": "src/a.py",
    "args": { "old": "print(x)", "new": "logger.info(x)" },
    "risk": "low"                      // low | medium | high
  }
}
```

### 5.3 kind = `approval`（高风险操作需要人工审批）

```jsonc
{
  "kind": "approval",
  "data": {
    "approval_id": "ap-001",
    "description": "写入 /etc/hosts（高风险）",
    "risk": "high",
    "diff": "..."
  }
}
```

客户端必须回 `{"type":"approval","approval_id":"ap-001","decision":"allow"|"deny"}`。
超时（默认 5 min）视为 deny。

### 5.4 kind = `stderr` / `error`

```jsonc
{ "kind": "stderr", "data": { "text": "warning: ..." } }
{ "kind": "error",  "data": { "message": "command not found: codex" } }
```

### 5.5 kind = `done`（任务结束）

```jsonc
{
  "kind": "done",
  "data": {
    "status": "ok" | "error" | "timeout" | "cancelled" | "denied",
    "summary": "改动 3 处 print → logging",
    "stats": { "duration_sec": 42, "tokens_in": 1200, "tokens_out": 800 }
  }
}
```

`done` 是终态，此后不再有其他 event。

### 5.6 kind = `meta`（元信息，如代理版本、模型名）

```jsonc
{ "kind": "meta", "data": { "model": "claude-3-5-sonnet", "engine": "claude-code v1.2.3" } }
```

## 6. 客户端指令

### 6.1 `approval`

```jsonc
{ "type": "approval", "approval_id": "ap-001", "decision": "allow" }
```

### 6.2 `cancel`

```jsonc
{ "type": "cancel", "task_id": "t-001" }
```

服务端终止对应本地代理进程（先 SIGTERM，10s 后 SIGKILL），推一个 `done(status="cancelled")`。

### 6.3 `ping`

```jsonc
{ "type": "ping" }
```

服务端回 `{"type":"pong"}`。

### 6.4 `list_agents`（可选，中途刷新代理健康状态）

```jsonc
{ "type": "list_agents" }
```

服务端回一次 `hello` 里的 `agents[]` 部分。

## 7. 错误码

| code | 含义 | 客户端处理 |
|---|---|---|
| `INVALID_PAIR_CODE` | 配对码错误 | 关闭连接，提示用户重试 |
| `SESSION_EXPIRED` | 会话过期 | 重新 pair |
| `AGENT_NOT_FOUND` | 指定 agent 未安装或不可用 | 提示用户，允许 auto 重试 |
| `AGENT_UNHEALTHY` | agent 进程启动失败 | 显示错误 |
| `TASK_TIMEOUT` | 超时 | 显示超时 |
| `TASK_CANCELLED` | 被取消 | 显示已取消 |
| `RATE_LIMITED` | 并发任务数超限 | 排队或提示 |
| `PROTOCOL_VERSION` | 协议版本不兼容 | 拒绝连接 |

## 8. 安全边界

1. **配对码**：4 位大写字符（0-9 A-Z，去掉易混淆的 0/O/1/I），TTL 60s，展示在桌面 UI 与移动端输入框对照。
2. **无加密传输**：默认 `ws://` 仅用于局域网。公网必须 `wss://` + TLS。
3. **不存凭据**：手机端不存配对码、不存任务内容（退出即清）。桌面端会话表 30 天清理。
4. **审批 fail-closed**：`auto_approve_low_risk=false` 时所有 `approval` 事件都必须显式 allow；`true` 时仅 `risk=low` 自动放行，medium/high 仍要手动。
5. **不暴露 shell**：手机端不能直接执行 shell，只能通过 `dispatch` 让桌面代理间接执行。
6. **审计**：所有 `dispatch` 与 `approval` 事件写入桌面端 `~/.tuan/audit/dispatch.jsonl`。

## 9. 参考实现

- 桌面端：`tuan_cli/agents/`（路由器 + 5 适配器）+ `tuan_cli/web/dispatch_server.py`（WebSocket 服务）
- 手机端：`Tuan-App/android/`（Kotlin + Compose + OkHttp WebSocket）
