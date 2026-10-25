# Tuan-Chat Native 架构（手机远程调度桌面 Agent-of-Agents）

> v0.3.2 五模式改造的姊妹文档。与 `TUAN-DISPATCH-PROTOCOL.md` 配套阅读。
> 状态：方案落地（MVP 可运行）。

---

## 1. 一句话结论

**手机 Tuan-Chat Native（Android 原生）⇄ 桌面 Tuan-Chat（Tauri/Tuan-App）⇄ 本机 5 家本地代理（Claude Code / CodeX / hermes / DeepSeek Harness / Kimi Code）**，三段式：手机只做发起 + 看流 + 审批 + 取消；桌面做路由 + 执行 + 审计；本地代理做真正的活。

CLI 与 Chat **都有 Agent-of-Agents 内核**（`tuan_cli/agents/` 共享）；**远程调度（WebSocket）只在 Chat/Tuan-App 一侧暴露**，CLI 不具备。

## 2. 系统全景

```
┌──────────────────────────────────────┐
│  手机 Tuan-Chat Native (Android)      │
│  Kotlin + Compose + OkHttp            │
│                                        │
│  [配对] ──ws──▶ [分发] ──ws──▶ [事件流] │
└──────────────┬───────────────────────┘
               │  WebSocket wss://desktop:8788/tuan/dispatch/v1
               ▼
┌──────────────────────────────────────┐
│  桌面 Tuan-Chat (Tauri + Python)       │
│                                        │
│  ┌─ dispatch_server.py ──────────┐   │
│  │  WebSocket 服务 (asyncio)      │   │
│  │  - hello / pair                │   │
│  │  - dispatch → router           │   │
│  │  - event stream 回推            │   │
│  │  - approval / cancel / ping    │   │
│  └──────────────┬─────────────────┘   │
│                 │                     │
│  ┌──────────────▼─────────────────┐   │
│  │  AgentRouter (agents/router.py)│   │
│  │  任务 → 代理 适配度打分           │   │
│  └──┬───┬───┬───┬───┬─────────────┘   │
└─────┼───┼───┼───┼───┼──────────────────┘
      │   │   │   │   │
      ▼   ▼   ▼   ▼   ▼
   [claude-code] [codex] [hermes] [deepseek-harness] [kimi-code]
   本地 CLI 进程 (subprocess)
```

## 3. 目录落地

### 3.1 桌面端（Python，共享内核）

```
tuan_cli/agents/                       ← 新增包: Agent-of-Agents 内核
├── __init__.py
├── base.py                            ← AgentAdapter ABC + EventType + TaskRequest + AgentInfo
├── discovery.py                       ← 扫 PATH 探测 5 家代理
├── router.py                          ← 路由器: 任务 → 代理打分 → 选中
└── adapters/
    ├── __init__.py                    ← 适配器注册表
    ├── claude_code.py
    ├── codex.py
    ├── hermes.py
    ├── deepseek_harness.py
    └── kimi_code.py

tuan_cli/web/dispatch_server.py        ← 新增: WebSocket 服务端 (只在 Chat 侧暴露)
```

CLI **不新增**远程调度子命令。桌面 Chat 由 Tauri 后端 `src/engine.rs` 启动 Python 侧的 dispatch server，把端口透出给前端。

### 3.2 手机端（Kotlin + Compose）

```
Tuan-App/android/                      ← 新增 Android 工程
├── build.gradle.kts
├── settings.gradle.kts
├── gradle.properties
├── gradle/libs.versions.toml
├── app/
│   ├── build.gradle.kts
│   └── src/main/
│       ├── AndroidManifest.xml
│       ├── res/ (strings/themes/icons)
│       └── java/com/tuan/chat/
│           ├── TuanChatApplication.kt
│           ├── MainActivity.kt
│           ├── model/Protocol.kt          ← 与协议 v1.0 一一对应
│           ├── ws/
│           │   ├── DispatchClient.kt      ← OkHttp WebSocket
│           │   └── DispatchRepository.kt  ← StateFlow 状态管理
│           └── ui/
│               ├── PairingScreen.kt
│               ├── DispatchScreen.kt
│               ├── EventStreamScreen.kt
│               └── theme/Theme.kt
└── README.md
```

## 4. 五家本地代理 · 适配器策略

| 代理 | id | 命令探测 | 调用方式 | 输出格式 | 备注 |
|---|---|---|---|---|---|
| Claude Code | `claude-code` | `claude`, `claude-code` | `claude -p "<prompt>"` 或 `claude --print` | 文本流 | Anthropic 官方 CLI |
| CodeX | `codex` | `codex` | `codex exec "<prompt>"` | 文本流 | OpenAI 官方 CLI |
| hermes | `hermes` | `hermes` | `hermes run "<prompt>"` | 文本流 | 通用本地代理；命令未公开时按默认模式适配 |
| DeepSeek Harness | `deepseek-harness` | `dsh`, `deepseek-harness` | `dsh --prompt "<prompt>"` | 文本流 | 本会话运行环境；有 subagent/workflow |
| Kimi Code | `kimi-code` | `kimi-code`, `kimi` | `kimi-code --prompt "<prompt>"` | 文本流 | Moonshot AI 官方 CLI |

**探测策略**（`discovery.py`）：
1. `shutil.which(cmd)` 逐个找 PATH 中的可执行文件；
2. 找到后跑一次 `cmd --version` 取版本（超时 3s，失败不算不健康，只是 `version=None`）；
3. 全部找到则 `healthy=True`，未找到 `healthy=False` + `reason="not found in PATH"`。

**路由器打分**（`router.py`）：
- 显式指定 `agent`：直接用，未安装报错 `AGENT_NOT_FOUND`。
- `agent="auto"`：按 `mode` 打分（`chat`→claude-code/hermes，`lingma`→codex/kimi-code，`gantong`→hermes/deepseek-harness，`collaboration`→claude-code，`boundless`→任意）。
- 健康度：`healthy=False` 的代理跳过。
- 打分相同：按 `claude-code > deepseek-harness > codex > kimi-code > hermes` 优先级。

## 5. 审批与安全

- **默认 fail-closed**：`auto_approve_low_risk=false` 时，任何 `kind=approval` 都必须客户端显式 `allow`。
- **medium/high 风险**：无论 `auto_approve_low_risk` 如何，都需人工审批（协议 §5.3）。
- **超时**：审批事件 5 分钟未响应 = deny，服务端推 `done(status="denied")`。
- **审计**：所有 `dispatch` 与 `approval` 事件写入 `~/.tuan/audit/dispatch.jsonl`（每行一条 JSON）。
- **不暴露 shell**：手机端只能 `dispatch` 让桌面代理间接执行；桌面代理本身的 shell 工具仍受 Tuan-CLI 安全引擎（`tuan_cli/harden/`）约束。

## 6. 与现有模块的关系

| 现有模块 | 关系 |
|---|---|
| `tuan_cli/modes/`（五模式） | 路由器按 mode 打分，复用现有 prompt 与权限模型 |
| `tuan_cli/harden/`（安全引擎） | 代理执行时仍受桌面 Tuan-CLI 安全约束；手机端无 shell 权限 |
| `tuan_cli/web/server.py`（HTTP API） | 远程调度 WebSocket 是独立端口 `8788`，与现有 HTTP `8765` 并存 |
| `Tuan-App/src-tauri/src/engine.rs` | 启动 Python 侧 dispatch server（MVP 未接入，后续 Tauri 后端补） |
| `Tuan-App/docs/ANDROID-8.0-SOLUTION.md` | Android 8.0 特供版走 `Tuan-App/android/` 新工程；本文档是远程调度方案 |

## 7. MVP 边界

**已做**：
- 协议规范（v1.0）
- Python 端：AgentAdapter 基类 + 5 适配器 + 路由器 + WebSocket 服务端
- Android 端：完整工程骨架（Gradle + Compose + OkHttp + 三屏 UI）
- 协议在双端一一对应

**未做**（后续迭代）：
- Tauri 后端接入 dispatch server（当前 dispatch server 通过 `python -m tuan_cli.web.dispatch_server` 独立运行）
- TLS / wss 支持（当前仅 ws://）
- 配对码持久化与会话管理（当前内存态，重启桌面需重新配对）
- 附件文件通道（当前只支持 base64 小文件内联）
- 多手机并发（当前一个 session 一个连接）
- iOS 客户端
- Play Store 上架（当前 GitHub Releases sideload）

## 8. 运行

```bash
# 桌面端启动 dispatch server (MVP 独立运行方式)
python -m tuan_cli.web.dispatch_server --port 8788

# 生成配对码后, 手机端输入:
#   主机: 192.168.1.x:8788
#   配对码: XXXX
```

Android 端：Android Studio 打开 `Tuan-App/android/`，`./gradlew assembleDebug`。
