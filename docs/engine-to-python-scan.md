# Claude Code TS 引擎源码 → 青小团 Python 补贴清单

> 只读探查产物。目标：在"底层引擎整体替换为青小团 Python 实现、Electron 壳保留"之前，判定 engine/src 中哪些 TS 源码值得转写为 **Python 3.10（Windows，CLI/本地引擎角色）** 补贴青小团不完善的能力。
> 探查范围：claude-desktop-app/engine/src 全部目录（约 1500 个 TS 文件）对照 tuan_cli/ 实际读码；electron/bridge-server.cjs 的事件处理逻辑作为协议契约参照。
> 方法：6 个互斥探查域（多Agent编排 / Hooks+Skills+Plan / MCP+工具框架 / 运维类 / 引擎核心与协议 / 状态与支撑设施），关键文件精读 + Grep 定位 + 抽样。全程只读，未修改 engine/、tuan_cli/、electron/ 任何文件，未运行任何构建。
> 日期：2026-10-06

---

## 一、总体结论（先读）

**青小团不是"从零补"，而是"结构性补 + 协议补"**：

- **已确认青小团已有且部分强于 Claude Code（不重复补贴）**：hooks 系统（603 行，含看门狗进程树强杀）、skills（~2000 行，4 激活档/依赖图/10 格式适配器）、cron 调度（解析+原子存储+跨平台锁+超时+审计）、MCP 客户端骨架（stdio/http/sse 三传输+连接管理器，手写 JSON-RPC）、权限规则引擎（fnmatch+参数粒度+网络白名单）、注入扫描、影响半径/ledger 回滚、Auto Memory（FTS5+标签+分类）、ReAct 查询循环本体、供应链安全（harden/）。
- **三个结构性缺口（高优先级）**：
  1. **stream-json 线协议**（引擎核心域）——青小团"不会说"Claude 的 NDJSON 线协议；壳（bridge-server.cjs）只认 `system/init → stream_event → result` 这几种信封。**这是"替换底层后壳能否继续工作"的决定性契约**。
  2. **异步后台子 Agent + 续作 worker**（多Agent域）——青小团子 Agent 工具是同步阻塞、一次性、跑完即弃；无后台执行、无 `<task-notification>` 结果回灌、无 agentId 续作。
  3. **Git Worktree 会话状态机**（运维域）——青小团 worktree 只是 CRUD 壳，子代理隔离用 `tempfile.mkdtemp` 模拟（无分支语义、无法回灌、泄漏无人清理）。
- **勘误（与原预设不符，必须说明）**：`engine/src/hooks/` 下 76 个文件**不是**事件中间件 hook 系统，而是 React/Ink 的 UI hooks（useCanUseTool 等），属被排除的纯 UI 层。Claude Code 真正的事件中间件 hook 引擎在 `types/hooks.ts`（272 行）+ `services/tools/toolHooks.ts`（621 行）+ `utils/hooks.ts`（4675 行）。本清单 Hooks 域条目均基于这三个文件。

---

## 二、能力基线覆盖对照表（用户指定 10 项 + 协议契约）

| # | 能力基线 | 判定 | 承载条目 | 优先级 |
|---|---|---|---|---|
| ① | Subagents & 多 Agent 团队（动态生成/编排） | 缺口大：同步一次性 → 异步+可续作 | MA-1/2/3/4/6 | 高 |
| ② | Hooks 系统（事件中间件） | 青小团已完整；补增量（异步/分层语义/失败事件） | HK-2/3/5/7 | 中 |
| ③ | MCP（stdio/HTTP/SSE 多传输） | 客户端骨架已有；缺协议高级特性 | MC-1~6 | 高（MC-1/2） |
| ④ | Skills（可复用指令包） | 青小团已更强；仅 frontmatter 加固 | HK-6 | 低-中 |
| ⑤ | Plan Mode（计划/执行两阶段） | 本地审批门缺失（模型可自说自话放行） | HK-1 | 高 |
| ⑥ | Worktree 隔离（并行 Git worktree） | 有壳无肉：无会话状态机、子代理用 tempdir | OP-1/2 | 高 |
| ⑦ | Headless 模式（CI/CD 无 TUI） | **线协议整体缺失**（--print 裸文本一次性） | EC-1~7 | 高 |
| ⑧ | Security Plugin（漏洞/敏感信息扫描） | 有通用脱敏；缺 provider 规则表与检测 API | OP-3 | 中 |
| ⑨ | Scheduled Tasks（定时任务） | 青小团已完整；仅 one-shot/next_fire 小补丁 | OP-4 | 低 |
| ⑩ | Agent Teams / Multi-agent Orchestration | 跨进程文件总线 vs 共享任务清单 | MA-5 | 中 |
| — | stream-json 协议契约（壳兼容） | **缺失**：壳靠 init/result 判定就绪与 turn 结束 | EC-1~5 | 高 |

---

## 三、逐项补贴清单

### A. 多 Agent 编排域（对照 tuan_cli arch/、core/、tools/）

| 条目 | TS 源路径 | 补贴的能力缺口 | 青小团现状 | 优先级 | 转写工作量 | 依赖与风险 | 可借鉴的实现细节 |
|---|---|---|---|---|---|---|---|
| MA-1 异步/后台子 Agent + `<task-notification>` 回灌 | `tools/AgentTool/runAgent.ts`(~860行)、`coordinator/coordinatorMode.ts`(~370行)、`tasks/LocalAgentTask/` | 青小团 subagent 工具**同步阻塞**（`sub_agent.run(...)` 等跑完才返回截断文本）；无法"先发后干"、无法在主 turn 中收到 worker 完成通知再调度 | 弱/缺失：`tools/subagent_tool.py` 同步返回字符串；`ports/protocol/events.py:367` 定义了 `run_in_background/swarm_index` 字段但全库无人消费（有壳无肉） | **高** | 400–600 行 | 纯逻辑；AbortController→threading.Event/futures；难点在往主 query-loop 注入结果消息的挂接点（与 EC 域耦合） | `isAsync ? new AbortController() : ...` 决定 worker 独立性；完成注入 `<task-notification><task-id/><status>completed|failed|killed</status><summary/><result/><usage/>` 用户消息，主 agent 当内部信号不向用户复述 |
| MA-2 续作已有 worker（SendMessage→agentId） | `tools/SendMessageTool/`、`tools/AgentTool/runAgent.ts`(recordSidechainTranscript/writeAgentMetadata)、`tools/AgentTool/resumeAgent.ts` | 青小团子代理跑完即弃：无 agentId、不落盘 sidechain，无法在同一已加载上下文续作（重复探索） | 缺失：`tools/messaging_tool.py` 是跨进程文件总线（core/message_bus.py）+手动轮询，非同进程 worker 续作 | **高** | 300–500 行 | 依赖 MA-1；需 transcript 落盘+按 agentId 恢复（可复用青小团 session 存储） | sidechain 逐条落盘+agent 元数据（agentType/description）；`coordinatorMode.ts` 的"续作 vs 新开"决策表（研究过的文件要改→续作；验证别人代码→新开；纠正失败→续作；方法全错→新开） |
| MA-3 Coordinator 编排玩法（系统提示+委派剧本） | `coordinator/coordinatorMode.ts` `getCoordinatorSystemPrompt()` | 青小团 Orchestrator 是代码驱动的批量 spawn；无"主 agent 在对话中自决派 worker/综合再下发"的 LLM 玩法 | 缺失：`arch/orchestration.py` 批量等待模型；无 coordinator 模式开关 | 中高 | 100–150 行（纯提示工程） | 零 Node 依赖；文案引用工具名需与 MA-1/2 对齐 | 四阶段 Research→Synthesis→Implementation→Verification；只读研究并行/写操作同文件串行；"prompt 必须自包含文件路径:行号"；禁"based on your findings"式懒委派 |
| MA-4 统一后台任务状态机/注册表 | `Task.ts`(126行)、`tasks.ts`、`tasks/types.ts` | 青小团无统一后台任务模型（只有 background_shell 管 shell 命令）；MA-1 落地需要 | 缺失：`core/background_shell.py`、`tools/task_tool.py` 的 run_in_background 指命令后台跑 | 中 | 150–250 行 | 纯逻辑低风险；无需 React AppState，用 dict+锁 | `TaskStatus=pending\|running\|completed\|failed\|killed` + `isTerminalTaskStatus()`；`generateTaskId(type)`=类型前缀+8位base36（防 symlink 猜测）；按 type 分发的 kill 注册表 |
| MA-5 团队/共享任务清单协作 | `tools/TeamCreateTool/`、`tools/shared/spawnMultiAgent.ts`(~1094行)、`utils/swarm/`(inProcess 部分) | 青小团跨代理通信=文件总线+手动轮询；无"团队=共享任务清单"、成员发现、owner 认领、自动投递 | 弱：`tools/messaging_tool.py` 需 agent 主动 receive_messages 拉取；无 team 配置、无任务所有权 | 中 | 600–900 行（最重，最后做） | 依赖 MA-1/2；**tmux/iTerm2 分屏后端不转**；in-process 用线程队列即可 | Team 1:1 对应 task list；`~/.tuan/teams/{name}/config.json` 的 `members[]`；TaskUpdate(owner=) 认领、按 ID 顺序领未阻塞任务；leader 忙时排队、turn 结束自动投递、每轮发 idle 通知 |
| MA-6 结构化 worker 结果信封 | `coordinator/coordinatorMode.ts`(usage 块)、`runAgent.ts`(onQueryProgress/pushApiMetricsEntry) | 青小团子代理只返回截断 8000 字自由文本，主 agent 无法做成本/进度聚合 | 弱：subagent_tool.py 有 emit subagent.completed 事件但返回仍为自由文本 | 中 | 50–100 行 | 纯数据结构；并入 MA-1 顺手做 | `<usage><total_tokens/><tool_uses/><duration_ms/></usage>` 固定信封，主 agent 据此聚合而非解析自然语言 |

### B. Hooks + Skills + Plan Mode 域（对照 tuan_cli hooks/、skills/、core/）

> 勘误见"总体结论"：真正的 hook 引擎在 `types/hooks.ts` + `services/tools/toolHooks.ts` + `utils/hooks.ts`。青小团 hooks/skills 已完整且部分强于 CC，本域只做增量补齐。

| 条目 | TS 源路径 | 补贴的能力缺口 | 青小团现状 | 优先级 | 转写工作量 | 依赖与风险 | 可借鉴的实现细节 |
|---|---|---|---|---|---|---|---|
| HK-1 **Plan Mode 本地审批门** | `tools/ExitPlanModeTool/ExitPlanModeV2Tool.ts`(~494行)、`commands/plan/index.ts`、`utils/permissions/PermissionMode.ts`(plan 是 permissionMode='plan') | 青小团本地 `exit_plan_mode` 被模型一调就**立即退出并放行写操作**，无"呈现计划→用户批准"的人工门；模型可自说自话提交计划立刻开改 | 弱（本地路径）：`tools/session_tools.py:240-250` `_exit_plan_handler` 直接 `_set_plan_mode(False)` 未接审批门；ACP 路径已有 plan_review/approve/revise | **高** | 150–250 行 | 纯逻辑零 Node 依赖；可复用青小团 ask_user/ACP plan_review；切回全量工具时机须与审批严格绑定 | `checkPermissions()` 对非 teammate 恒返回 `behavior:'ask'`；`call()` 恢复 `prePlanMode`（非写死 default）；tool_result 回显 "User has approved your plan... ## Approved Plan: <plan>"，区分"edited by user" |
| HK-2 异步 hook（首行 `{"async":true}` 后台化） | `utils/hooks.ts`:1112-1145/184/987-1014、`types/hooks.ts:171-176` | 青小团所有 hook 同步阻塞（Popen+communicate 死等到超时）；慢 hook（联网 lint/远程扫描）拖慢每一轮 | 缺失：`hooks/manager.py:366-430` `_exec_command` 全阻塞 | 中 | ~200 行 | 纯标准库；**只对 stdout 首行探测**；首期只对 notify 类事件开放 async（PreToolUse 的 async 语义复杂） | 只解析 stdout 第一行（注释："must parse ONLY the first line, otherwise a fast hook's later output breaks parsing"）；`asyncTimeout` 可覆盖默认超时；shellCommandTransferred 标记防重复 wait |
| HK-3 hook 权限分层语义 | `services/tools/toolHooks.ts:332-433` `resolveHookPermissionDecision`、`utils/permissions/permissions.js` | hook 的 allow 不覆盖 settings deny/ask 规则（安全正确性问题）：青小团 hook 放行后不再查规则闸门 | 弱：`hooks/manager.py:241-283` run_pre 返回 HookDecision 后无二次规则复审 | 中 | 80–120 行 | 纯逻辑；需与 sandbox/verdict.py、core/auto_mode.py 打通避免双重提示 | 决策链：hook allow 且工具需交互→仍走 canUseTool；hook allow 后仍跑规则（deny 覆盖、ask 仍弹框）；hook deny 直接采用；hook ask 的 reason 作为 dialog 文案——"hook 建议 < 规则硬约束 < 用户确认" |
| HK-4 文件监听 hook 链 | `utils/hooks.ts`:353/631/1665/2801、`types/hooks.ts:87-91` | SessionStart hook 可返回 `watchPaths`，引擎监视文件树、变动触发 `FileChanged` hook；青小团无 FileChanged/CwdChanged 事件，无法做"文件一变自动跑格式化/lint" | 缺失：`hooks/manager.py:34-46` HOOK_EVENTS 无 FileChanged | 低（可选增强） | 250–350 行 | Windows 无标准库事件监听，需轮询或第三方 watchdog；误触发率偏高 | watchPaths 可由任意相关事件**动态返回并累积**（不写死在配置）；FileChanged matcher 只看 `basename(file_path)` |
| HK-5 hook 事件面补齐 | `types/hooks.ts:70-163`、`services/tools/toolHooks.ts:193-319` `runPostToolUseFailureHooks` | 缺 PostToolUseFailure（失败独立触发）、Notification、PermissionRequest（hook 代裁权限弹窗）等细粒度事件 | 缺失（部分）：`hooks/manager.py:285-306` 把失败塞进 PostToolUse 的 result.content | 中（PostToolUseFailure）/低（其余） | 60–150 行 | PostToolUseFailure 纯逻辑低风险；PermissionRequest 代批权限安全敏感，需与 HK-3 一起做 | 失败事件与成功 PostToolUse 平行、带 error/isInterrupt 入参、独立 try/catch 上报；PermissionRequest decision 判别联合 `{behavior:'allow',updatedInput?,updatedPermissions?} \| {behavior:'deny',message?,interrupt?}` → Python dataclass |
| HK-6 skill frontmatter 真 YAML 解析 + paths 作用域 | `skills/loadSkillsDir.ts:185-220`、`utils/frontmatterParser.js` | 青小团 frontmatter 用手写逐行正则，无法解析嵌套 YAML 列表块（enhanced.py 的 provides/requires 靠 re.split 兜底）；缺 paths/allowedTools/model 等字段 | 弱（解析器）：`skills/manager.py:311-354` 仅 key:value+逗号/方括号；多仓库发现/打分/激活档反而比 CC 全 | 低-中 | ~100 行 | 引入 pyyaml 是新增依赖（权衡：优先容错 YAML 子集）；低风险 | `parseSkillPaths`：剥 `/**` 后缀、全 `**` 视为无约束；`whenToUse` 字段承载"何时该用"供检索加权 |
| HK-7 hook matcher 升级正则 | `utils/hooks.ts:1346-1381` `matchesPattern` | 青小团 matcher 仅 fnmatch glob，无法表达"以 Test 开头不含 Integration"的正则语义 | 弱：`hooks/manager.py:212-237` 仅 fnmatch | 低 | ~30 行 | 纯逻辑；正则编译失败兜底返回 false | 先判是否纯 `[a-zA-Z0-9_|]`（是则精确/管道匹配，否则当正则 RegExp.test）——避免把 `Write` 误当正则；对 legacy 工具别名二次匹配 |

### C. MCP + 工具框架域（对照 tuan_cli runtime/mcp/、tools/mcp/）

> 关键背景：青小团已有完整 MCP 客户端骨架（runtime/mcp 手写 JSON-RPC，stdio/http/sse + 连接管理器 + pydantic 配置；tools/mcp 注册/注入扫描/限流/审计/命名碰撞）。**不是从零造客户端**，缺口在协议高级特性。权限/注入/ledger 已强，不重复列。

| 条目 | TS 源路径 | 补贴的能力缺口 | 青小团现状 | 优先级 | 转写工作量 | 依赖与风险 | 可借鉴的实现细节 |
|---|---|---|---|---|---|---|---|
| MC-1 MCP 服务端主动请求（roots/elicitation/progress） | `services/mcp/client.ts`(ListRootsRequest~L1009、callMCPToolWithUrlElicitationRetry~L2813)、`services/mcp/elicitationHandler.ts`(314行)、`Tool.ts` handleElicitation | 青小团对 server 主动请求统一回 `-32601`、`initialize` 声明 `capabilities:{}`；无法对接依赖 roots/list、elicitation/create（OAuth 授权页/敏感确认）、progress 回执的 server | 缺失：`runtime/mcp/client_stdio.py:282-284` 回 -32601、L103 capabilities 空；`runtime/mcp/types.py` 只声明 list_tools/call_tool/ping | **高** | 350–450 行 | 低，纯 JSON-RPC；elicitation 交互可复用 `ToolContext.confirm/requestPrompt`；initialize 需声明 `roots:{}`、`elicitation:{}` | `ListRootsRequest` 返回 `{roots:[{uri:"file://"+cwd}]}`；elicitation 分 form/url 两模式，核心流程：捕获 `-32042 UrlElicitationRequiredError` → URL 交给用户 → 等 ElicitationCompleteNotification → 自动重试原 call（模型无需再发一轮）；排队队列+resolve 闭包+abort → asyncio Future |
| MC-2 大结果处理（超限落盘+图片降采样+structuredContent 紧凑 schema） | `services/mcp/client.ts`:2478-2720(transformResultContent/inferCompactSchema/processMCPResult/persistBlobToTextBlock)、`utils/mcpOutputStorage.ts` | 青小团只对二进制 10MB 截断丢弃；大文本结果整段灌进上下文；图片不降采样；structuredContent 无紧凑类型签名 | 弱：`runtime/mcp/output.py` `_apply_binary_cap` 仅按 base64 长度切二进制，无文本阈值/落盘；structuredContent 原样塞 extras | **高** | 250–300 行 | 低，纯逻辑+临时文件；图片降采样用 Pillow（青小团已有 vision 依赖） | `processMCPResult` 决策树：超阈值→含图片退化截断，否则 `persistToolResult` 写盘返回 `getLargeOutputInstructions(path,size,...)` 提示模型用分页/过滤工具取子集；`inferCompactSchema(value,depth=2)` 生成 jq 友好类型签名（>10 键加 `, ...`）；二进制非图/音→落盘只回路径+大小+MIME |
| MC-3 指数退避自动重连 | `services/mcp/useManageMCPConnections.ts`:87-90(MAX_RECONNECT_ATTEMPTS=5, INITIAL_BACKOFF_MS=1000, MAX_BACKOFF_MS=30000)、`services/mcp/client.ts` reconnectMcpServerImpl | 青小团断线只置 failed 不自动重试（reconnect 是手动 API）；长驻 server 崩溃需手动 /mcp reconnect | 弱：`runtime/mcp/connection_manager.py:169-184` `_watch_unexpected_close` 仅置 failed | 中 | 100–150 行 | 低；重连成功重置计数、达上限置 failed；错峰防重连风暴 | `backoff = min(INITIAL*2**attempt, MAX)` + jitter；`Map<name,Timer>` 持有重连句柄供手动取消；`McpSessionExpiredError`（会话过期）与进程崩溃区分：前者清缓存立即重连，后者走退避 |
| MC-4 动态列表刷新（list_changed 通知） | `services/mcp/useManageMCPConnections.ts`:33-37、`client.ts` fetchToolsForClient(memoizeWithLRU ~L1743) | 青小团 stdio 读循环显式忽略所有无 id 的 notification；server 运行中动态增删工具时工具表永不更新 | 缺失：`client_stdio.py:284` 注释"通知（无 id）忽略" | 中 | 80–120 行 | 低-中；需先补 `ToolRegistry.remove`；重拉后处理同名工具 schema 更新 | 收 `notifications/tools/list_changed` → 失效 LRU 缓存 → 重拉 list_tools → 与当前注册集 diff：新增 register_mcp_tool、消失 registry.remove；fetchToolsForClient 的 LRU(key=client.name,size=20) 也可借鉴 |
| MC-5 MCP 工具 annotations/_meta → 权限与并发分类 | `services/mcp/client.ts`:1766-1832、`tools/MCPTool/classifyForCollapse.ts` | 青小团 MCPToolDefinition 只取 name/description/inputSchema 三字段，dangerous 写死 needs_confirm；只读工具无法在 plan 模式放行/并发，破坏性工具不自动标危险 | 弱：`runtime/mcp/types.py` 仅三字段；`tools/mcp/plugin.py:206-213` dangerous=needs_confirm 不区分 readOnly/destructive | 中 | 60–80 行 | 低，纯字段映射；hint 缺省 false（fail-closed） | readOnlyHint→read_only（plan 放行+并发安全）；destructiveHint→dangerous（强制确认）；openWorldHint→网络/外部副作用标记；`_meta.anthropic/searchHint`（3-10 词关键词）喂 MCP Tool Search |
| MC-6 远程 MCP OAuth 最小子集 | `services/mcp/auth.ts`(88KB，勿整体照搬)、`client.ts`(wrapFetchWithStepUpDetection、MCP_AUTH_CACHE_TTL_MS=15min) | 青小团远程 server 只支持静态 bearerTokenEnvVar；401/403 不触发刷新、无授权码流程、无 token 缓存 TTL | 弱：`client_http.py` 静态注入；`config.py` 声明 `auth:"oauth"` 后无实现 | 中（只做最小子集） | 150–200 行 | 中；本地随机端口回调、token 落盘权限 600；完整 DCR 不建议本期 | 只借鉴三件事：`authProvider.tokens()` 接口（传输层每次问 provider 要）；`wrapFetchWithStepUpDetection` 包裹顺序（最内层先看 403 再走刷新）；token 缓存 TTL=15min 按 serverId 存盘 |
| MC-7 resources/prompts 读取 | `services/mcp/client.ts`(fetchResourcesForClient ~L2000)、`tools/ListMcpResourcesTool/`、`tools/ReadMcpResourceTool/` | 青小团只做 tools/list；server 暴露的配置/文档/DB schema 资源模型无法读取 | 缺失（runtime/mcp 无 resources 模块） | 低-中 | 150–200 行 | 低；text/blob 归一复用 MC-2 的 content block 转换 | `ServerResource = Resource & {server}`；resources/read 的 text 直接转文本块、blob 按 MIME 走图片/落盘分支 |
| MC-8 工具入参 JSON-Schema 严格校验 | `Tool.ts` `validateInput` ~L95-101 | 青小团 dispatch 仅 json.loads 后直接调 handler；模型传错参时 TypeError 栈崩或静默错参执行 | 弱：`tools/base.py:452` 无 schema 校验 | 低 | 120–180 行 | 低；校验失败返回可读错误给模型自纠而非抛异常 | `validateInput` 返回结构化 `{ok,message,errorCode}`（缺必填/类型错/枚举越界），dispatch 转成 `ToolResult(status="error", content="[参数错误]...")` 喂回下一轮 |
| MC-9 配置分层 scope 合并 | `services/mcp/types.ts`(ConfigScopeSchema)、`services/mcp/config.ts`(filterMcpServersByPolicy/isStrictMcpConfig) | 青小团 merge_mcp_configs 是扁平 dict.update；无 enterprise/managed 策略层、无 strict 模式 | 弱：`runtime/mcp/config.py:140-147` 单层合并 | 低 | 80–120 行 | 低 | 每 server config 带 scope；合并顺序 enterprise>managed>project>user>local，高优先级 `enabled:false` 不可被低优先级翻回；strict 模式拒绝未知 server 类型 |

### D. 运维类域（Worktree / Security / Scheduled，对照 tuan_cli core/、gh/、cron/、harden/）

| 条目 | TS 源路径 | 补贴的能力缺口 | 青小团现状 | 优先级 | 转写工作量 | 依赖与风险 | 可借鉴的实现细节 |
|---|---|---|---|---|---|---|---|
| OP-1 **Git Worktree 会话状态机** | `utils/worktree.ts`(~1400行)、`tools/EnterWorktreeTool/`(127行)、`tools/ExitWorktreeTool/`(~11.6KB) | 青小团 worktree 只是手动 CRUD；无会话级状态机（不记录 originalCwd/branch/head，退出无法干净回原态、无法 --resume）；子代理隔离用 tempfile.mkdtemp（空临时目录而非 git worktree：无独立分支、无法 merge 回灌、无法 diff）；进程被 kill 后泄漏无人清理 | 弱（有壳无肉）：`core/worktree_layer.py`(182行 CRUD)、`cli/cmd_worktree.py`(67行)、`arch/orchestration.py`(tempfile.mkdtemp 注释明言"模拟隔离") | **高** | 600–900 行（在 worktree_layer.py 上扩，非重写） | 依赖 git CLI 子进程（subprocess 直接对应）；chdir 副作用需可控回滚；tmux 部分（createTmuxSessionForWorktree）Windows/本地引擎可不转 | `WorktreeSession` 数据结构（originalCwd/worktreePath/branch/originalBranch/originalHeadCommit/sessionId）+ saveWorktreeState 持久化；`createAgentWorktree/removeAgentWorktree` 给子代理用、**不触碰全局会话状态**（不 chdir 不写 project config）——与会话级 createWorktreeForSession 分离；`cleanupStaleAgentWorktrees` 用 ephemeral slug 正则（agent-a<7hex>/wf_<id>/bridge-*/job-*）精确圈定、绝不碰用户命名 worktree、fail-closed（有改动/未推送就跳过） |
| OP-2 Worktree 性能/磁盘细节 | `utils/worktree.ts`(getOrCreateWorktree/symlinkDirectories/flattenSlug/worktreeBranchName/parsePRReference) | 青小团每次裸跑 git worktree add（重复进入报已存在而非复用）；node_modules 每个 worktree 复制一份；无 .worktreeinclude；slug 无嵌套→分支名映射；无防挂起 env | 弱：`worktree_layer.py` `_wt_path` 仅拦分隔符/./..，create 不做存在即复用，subprocess 固定 30s 超时无防挂起 env | 中 | 150–250 行（随 OP-1） | 纯 git CLI+os.symlink（Windows symlink 需权限/开发者模式，降级为复制或跳过）；gitignore 匹配建议手写子集（零依赖约束） | fast-resume 直接读 worktree 的 `.git` 指针文件判存在（免 git rev-parse 开销）；`flattenSlug()` user/feature→user+feature 规避 git ref D/F 冲突；`GIT_NO_PROMPT_ENV={GIT_TERMINAL_PROMPT:0,GIT_ASKPASS:''}` 防凭据提示挂起；remove 后 sleep(100) 再 git branch -D |
| OP-3 Provider 专属密钥规则表 + scan/redact 双 API | `services/teamMemorySync/secretScanner.ts`(~325行，纯逻辑零 Node API) | 青小团脱敏只有通用模式（key=value/Bearer/sk-/JWT），AWS AKIA/GitHub ghp_/Slack xoxb-/Stripe sk_live_/PEM 等带前缀凭证漏报；且只有"脱敏"无"检测"闸门（无法用于上传/发布前拦截秘密外发） | 弱：`core/security_utils.py`(148行 redact_sensitive 等，规则窄)；注：harden/ 供应链安全已强于 TS，不需补贴 | 中 | 300–380 行 | **纯逻辑零依赖**，Python re 直接对应 JS RegExp（Go→JS 已转写过的正则原样搬到 Python）；风险极低 | `SECRET_RULES` 表（~35 条高置信规则，带独特前缀、近零误报，省略通用关键词上下文规则）；`scanForSecrets` 返回 `[{ruleId,label}]` 且**故意不回显匹配明文**；redact 全局替换**只替换捕获组 g1 保留边界字符**（引号/分号不被吃掉）；规则懒编译缓存 |
| OP-4 cron one-shot + next_fire 预览 | `utils/cronTasks.ts`(459行)、`utils/cron.ts`(308行)、`utils/cronScheduler.ts`(~21KB)、`tools/ScheduleCronTool/` | 青小团 cron 主体已完备，仅缺：one-shot 一次性任务（触发一次自动删）、`computeNextCronRun` 向前推算（无法预览"下次几点跑"）、recurringMaxAgeMs 自动过期 | 已有且完好：`cron/schedule.py`(194行 零依赖解析)、`store.py`(原子写+RLock+重启补跑)、`runner.py`(墙钟超时+跨平台锁 msvcrt/fcntl+锁内重读)、`daemon.py`(分片睡眠优雅退出) | 低 | 80–150 行 | 纯逻辑零依赖；jitter 是多会话/舰队场景，本地单用户**不建议转写** | one-shot 触发后 removeCronTasks 自删；`computeNextCronRun` 按月→日→时→分逐级跳跃（非逐分钟盲走），dom/dow 双限定时取 OR |

### E. 引擎核心与协议域（含 Headless，对照 tuan_cli core/agent.py、cli/、runtime/、acp/）

> 核心结论：青小团缺的不是查询循环（agent.py ReAct 循环已完好），而是**对外的那条线**——有 ACP（JSON-RPC）stdio 长驻脚手架，但完全不会 Claude 的 stream-json NDJSON 线协议。**壳能否继续工作，取决于 EC-1~5 能否落地。**
> stream-json 协议承载文件（已核实，按调用链）：`entrypoints/cli.tsx` → `cli/print.ts`(212KB，headless 驱动器) → `cli/structuredIO.ts`(860行，stdin/stdout+control RPC) → `cli/ndjsonSafeStringify.ts` → `QueryEngine.ts`(47KB，事件翻译) → `utils/messages/systemInit.ts`(init 构造) → `entrypoints/sdk/coreSchemas.ts`(56KB，线契约本体) + `query.ts`(核心循环)。壳以 `bun entrypoints/cli.tsx --input-format stream-json --output-format stream-json --include-partial-messages --permission-mode bypassPermissions --permission-prompt-tool stdio --add-dir <dir> --model <id>` 拉起引擎，按 `\n` 切 stdout 行，`system/init` 判就绪、`result` 判 turn 结束，向 stdin 写 `{"type":"user","message":{"role":"user","content":...},"uuid":...}`。`engine/src/bridge/` 是 claude.ai 远程桥接（不是本地 electron 契约承载者），远程鉴权/轮询/JWT 明确不转。

| 条目 | TS 源路径 | 补贴的能力缺口 | 青小团现状 | 优先级 | 转写工作量 | 依赖与风险 | 可借鉴的实现细节 |
|---|---|---|---|---|---|---|---|
| EC-1 **stream-json 线协议（消息 schema + 事件翻译层）** | `entrypoints/sdk/coreSchemas.ts`(56KB)、`QueryEngine.ts`(事件翻译)、`cli/ndjsonSafeStringify.ts`(1.4KB) | 青小团对外不会说 Claude 线协议：--print 把 token 裸写 stdout，无 init/stream_event/assistant/result 信封；壳 handleEngineStdoutLine 只认这几种 envelope，缺了前端拿不到结构化渲染 | **缺失**：现有 NDJSON/JSON-RPC 是 ACP 协议（acp/protocol.py），与 Claude schema 两套不同；内部 StreamedMessagePart 是 OpenAI 风格 tool_call，非 Anthropic content blocks | **高** | 800–1200 行（pydantic/dataclass 消息联合+事件翻译器+NDJSON 序列化含 U+2028/2029 转义 ~15行） | 低，纯数据结构；需补 OpenAI↔Anthropic 内容块形状映射 | 消息联合（system/init、compact_boundary、stream_event、assistant、user、result success/error、status、api_retry、task_*）每条带 uuid+session_id；`QueryEngine.ts:788 case 'stream_event'` 仅 includePartialMessages 时透传原始 event+parent_tool_use_id；ndjsonSafeStringify 转义 U+2028/2029 防按行切分截断 |
| EC-2 **持久多 turn stdin 引擎循环** | `cli/print.ts` runHeadlessStreaming(~L976)、`cli/structuredIO.ts` read()/processLine() | 壳对一个会话只拉一次引擎子进程，整个会话内向 stdin 写多轮 user；青小团 --print 是一次性 agent.run(task) 跑完即退 | 弱/部分：`acp/server.py` 已有 stdio 长驻骨架（serve/后台线程/一进程一会话），缺 stream-json 版同款循环 | **高** | 300–500 行（复用 acp/server.py 骨架，协议层换掉） | 低，asyncio/线程编排；注意 Agent.run() 是同步阻塞需放后台线程，主线程守 stdin | `print.ts:1019` heldBackResult（结果扣住等后续事件 flush 完再发）+ runPhase（draining_commands/waiting_for_agents/finally_flush）；structuredIO 跨 block 缓冲按 `\n` 切行、残行留到下个 block；SIGINT 中断在飞 query→gracefulShutdown |
| EC-3 **system/init 启动握手** | `utils/messages/systemInit.ts` buildSystemInitMessage(:53-96)、`QueryEngine.ts:540` | 壳把收到 system/init 当"引擎就绪"（resolveReady）并做 engine-pool 预热；青小团启动后什么都不发，壳永远等不到 ready | 缺失：ACP 侧有 session/update(initialized) 但字段是 ACP 形状 | **高**（壳 readiness 硬门槛） | 80–150 行 | 低，纯字段组装；从青小团配置收集 tools/model/permissionMode/cwd/session_id | init 字段集：type/subtype='init', cwd, session_id, tools[], mcp_servers[], model, permissionMode, slash_commands, apiKeySource, claude_code_version, output_style, agents[], skills[], plugins[], uuid；壳只严格依赖"出现"这一信号 |
| EC-4 **result 结束信封** | `entrypoints/sdk/coreSchemas.ts:1407`(SDKResultSuccessSchema/ErrorSchema)、发射点 QueryEngine.ts:618/851/981、print.ts:2429 | 壳靠 `{type:'result'}` 结束 turn 并回填最终答案（assistantText 空则取 evt.result）；青小团把 usage/cost 打 stderr 自由文本，壳无法判定 turn 结束 | 弱：有用量记账（agent.py _accumulate_usage/_estimate_total_cost）但未封装 result 信封 | **高**（turn 收尾硬门槛） | ~100 行 | 低；需累计 duration_ms/num_turns/total_cost_usd/per-model usage（多模型路由按模型分桶） | success 字段：duration_ms, duration_api_ms, is_error, num_turns, result, stop_reason, total_cost_usd, usage, modelUsage{model:ModelUsage}, permission_denials[], uuid, session_id；error 变体 subtype ∈ error_during_execution/error_max_turns/error_max_budget_usd/error_max_structured_output_retries，多 errors[] |
| EC-5 **Anthropic 原始 stream_event 透传** | `QueryEngine.ts:788-828`、`coreSchemas.ts:1496`(SDKPartialAssistantMessage) | 壳用 --include-partial-messages，期望逐块收 content_block_delta(text/thinking)/content_block_start(tool_use)；青小团流抽象是 OpenAI 风格（tool_call index/arguments_delta），形状对不上 | 弱：models/anthropic.py 能解析 Anthropic 原始事件但对外归一化；Agent 只喂 on_token/on_tool | **高**（前端流式渲染依赖） | 200–350 行 | 中；tool arguments:str 需 parse 成 dict 再转 Anthropic tool_use input；多 tool 并行 index 对齐 | 事件形状即任务书契约：content_block_delta{delta:{text_delta\|thinking_delta}}、content_block_start{tool_use{id,name,input}}；随后 assistant{content:[tool_use]}、再 user{content:[tool_result{tool_use_id,content,is_error}]}；QueryEngine 对 stream_event **原样透传不加工** |
| EC-6 control_request↔control_response 权限 RPC | `cli/structuredIO.ts` sendRequest/createCanUseTool/injectControlResponse、`entrypoints/sdk/controlSchemas.ts`(19KB) | 引擎可在 stdout 发 control_request（can_use_tool）并阻塞等 stdin 回 control_response；青小团无跨 stdin 请求/响应配对 | 缺失（stdio RPC 层）：权限在 core/whitelist.py 本地自动判定；**但本壳用 --permission-mode bypassPermissions，该部署下不触发** | 中（当前壳不阻塞，通用 headless 需要时再补） | 250–400 行 | 中；pending_requests dict(request_id→Future)+超时/abort/重复响应去重；需与同步 Agent 循环打通"阻塞等待 host" | pendingRequests: Map<request_id,{resolve,reject}>；resolvedToolUseIds Set（上限 1000）去重迟到 control_response 防 API 400；abort 时回发 control_cancel_request 并 reject；PermissionRequest hook 与 host 弹窗 Promise.race 先到者胜 |
| EC-7 stdout 卫生护栏 | `cli/print.ts:594` installStreamJsonStdoutGuard | 任何 stray stdout 输出（依赖 banner/调试 print）都会破坏壳的按行 JSON 解析 | 缺失：--print 直接 sys.stdout.write token，无"运行期把非协议 stdout 导流 stderr"的总护栏 | 中（可靠性） | ~50 行 | 低；替换 sys.stdout 注意编码与 flush；必须在第一条协议写之前安装 | 动机注释："any stray write to stdout breaks the client's line-by-line JSON parser; divert non-JSON lines to stderr" |
| EC-8 查询循环状态机对齐 | `query.ts` queryLoop(:241，State 集中)、QueryEngine.ts 终态分支 | 青小团 ReAct 循环已能跑，缺"循环态集中在一个 State、多个 continue-site 续跑"的结构与 max_turns/max_budget 各自终态 result 分支 | 已有（基本完好）：agent.py _run_react_inline(:685) 预算检查/compact_if_needed/tool 执行/verify_loop/max_iter 兜底，能力不输 TS | 低（循环本体不转写；只补终态分支） | ~100 行胶水 | 低 | 三种失败终态各发不同 result subtype：error_max_turns(:851)、error_max_budget_usd(:981)、error_max_structured_output_retries——青小团目前只在内部 session_append 记录，需提升为对外 result |
| EC-9 bridge/ 作为 stream-json host 的驱动范例 | `bridge/sessionRunner.ts`(18KB)、`bridge/replBridgeTransport.ts`(15KB)、`bridge/types.ts`(SessionSpawner/SessionHandle.writeStdin) | 未来"不经过 electron、直接用 Python host 驱动 Python 引擎"时的参考 | 已有同类：acp/server.py 本身是 host 两端 | 低（仅设计参考） | 0 | bridge/ 的 pollConfig/jwtUtils/workSecret/trustedDevice 全部绑定 claude.ai 远程，**明确不转写** | host↔engine 权限请求的双向桥接形状（writeStdin / PermissionResponseEvent=control_response 回投） |

### F. 状态与支撑设施域（对照 tuan_cli context/、memory/、config/、models/、audit/、runtime/）

| 条目 | TS 源路径 | 补贴的能力缺口 | 青小团现状 | 优先级 | 转写工作量 | 依赖与风险 | 可借鉴的实现细节 |
|---|---|---|---|---|---|---|---|
| ST-1 跨进程文件锁 + 反向行读 | `utils/lockfile.js`、`utils/fsOperations.ts`(24KB) | 青小团多进程/多会话并发写同一 JSONL 或配置文件时缺跨进程互斥；SessionStore 只用 threading.Lock（进程内），跨进程 append 会丢行/截断 | 弱：memory/store.py 有原子写（临时文件+os.replace）但无跨进程锁；无反向行读工具 | **高** | ~250 行 | Windows 用 msvcrt.locking（fcntl 不可用）；stale 锁超时需谨慎（10s） | `lock(path,{stale:10000,retries:{3,50ms}})` 锁文件协议（pid+时间戳，超时抢占）；readLinesReverse 按 64KB 块倒序读、块边界拼接行 |
| ST-2 跨项目用户 prompt 历史（Up-arrow/ctrl+r） | `history.ts`(465行)+`utils/pasteStore.js` | 青小团无"用户输入历史"能力（sessions.py 是会话事件流，用途审计/回放非输入 recall） | 缺失 | 中 | ~400 行 | 依赖 ST-1；[Pasted text #N] 引用解析与 UI 粘贴流耦合可先砍 | pending 缓冲+异步 flush+退出前 cleanup 冲刷三段式落盘；当前会话条目优先排序（并发会话不穿插）；removeLastFromHistory 的 skip-timestamp 集合（Esc 回退后 Up-arrow 不重复） |
| ST-3 会话级成本追踪与恢复 | `cost-tracker.ts`(324行) | 青小团 audit/store.py 有 cost/token 审计，缺会话断点恢复语义（lastSessionId 匹配才恢复，避免跨会话串账）与按模型累计（含 cache read/creation 细分） | 已有基础：audit/store.py 命中 cost/token/usage | 中 | ~300 行 | 依赖模型单价表（青小团 models/provider_catalog.py 已有等价）；无 Node API | `restoreCostStateForSession(sessionId)` 的"lastSessionId 匹配才恢复"守卫；ModelUsage dataclass（input/output/cacheRead/cacheCreation/webSearch/costUSD+contextWindow/maxOutputTokens） |
| ST-4 Auto Memory 入口裁剪与老化 | `memdir/`(memdir.ts 21KB、memoryAge.ts、memoryScan.ts、findRelevantMemories.ts) | 青小团 memory/store.py 已是同类且更强（FTS5+标签+四类记忆）；缺口很小：MEMORY.md 入口"行数+字节双上限裁剪"启发式、按时间老化的相关度排序 | 已有且完好 | 低（只补两段算法） | ~200 行 | 无，纯逻辑 | `truncateEntrypointContent`：200 行/25KB 双上限，先按行截再在最后一个换行处按字节截，附加 WARNING 说明触发哪个上限（"截断要带理由"）；memoryAge 降权公式 |
| ST-5 系统提示词组装模式 | `context.ts`(getSystemContext/getUserContext, memoize)、`constants/prompts.ts`(56KB)、`constants/systemPromptSections.ts` | 青小团 core/prompts.py(34KB)+resources/SOUL.md 已有；缺"每会话预组装系统上下文"模式：git 状态快照（分支/5 条提交/status 截 2000 字符）、日期注入、CLAUDE.md 缓存 | 已有基础（core/prompts.py、context/manager.py） | 中低 | ~350 行 | git 子进程（gh/ 已有封装）；CLAUDE.md 发现需对照 context/manager.py | git status 截断 2000 字符附"快照不随会话更新"说明；bare 模式与显式 --add-dir 的豁免逻辑（"bare 是跳过没要的，不是忽略要了的"）；memoize→lru_cache |
| ST-6 token 估算 | `services/tokenEstimation.ts`(17KB) | 青小团已有 token 计数（runtime/session/compaction.py 等），估算精度/缓存策略差距需实测 | 已有，弱项未知 | 中低（先对照再定） | ~400 行 | 无 | 按内容块类型（文本/工具结果/图像）分策略估算+结果缓存；与 compaction 阈值配合的估算上限 |
| ST-7 结构化搜索输出 / 大结果持久化 / 上下文占用分析 | `utils/ripgrep.ts`(21KB)、`utils/toolResultStorage.ts`(38KB)、`utils/analyzeContext.ts`(43KB) | 结构化 rg --json 输出解析（去重/截断）是 Python Grep 工具的现成模板；大工具结果落盘/恢复避免塞爆上下文；分段 token 占用分析配合 compaction | 弱/待对照：未发现 ripgrep 或 tool-result 持久化等价物 | 中 | ~800 行（三文件合计，纯逻辑） | Windows 需确认 rg 可用或改 Python 实现；toolResultStorage 与工具执行流程耦合（配合工具域） | rg --json 逐行解析+match 去重+按行数上限截断附说明；toolResultStorage 的"按大小分级：小结果内联、大结果落盘+哈希引用"（与 ST-2 pasteStore 同模式） |
| ST-8 CLAUDE.md / settings 发现与解析 | `utils/claudemd.ts`(46KB)、`utils/markdownConfigLoader.ts`(21KB) | cwd 向上发现、多级合并、注入过滤；settings markdown 表格解析（@import/作用域）——若青小团 context/manager.py 已覆盖则降级 | 待对照 | 中低 | ~500 行 | 无 | 注入顺序与优先级（项目>用户>全局）、bare 豁免、缓存失效策略 |
| ST-9 配置读写与启动编排 | `utils/config.ts`(63.5KB)、`setup.ts`(21KB) | 青小团 config/ 三件套已完整；setup.ts 的启动序列（切 cwd→项目根→hooks 快照→会话切换→清理注册）是可借鉴的编排顺序，但含大量 macOS 专属（iTerm2/Terminal 备份） | 已有且完好 | 低 | 不转写本体；只抄启动序列清单 ~100 行 | macOS 专属在 Windows 无意义；worktree/tmux 归 OP 域 | 顺序约束注释本身是移植关键：setCwd 必须先于一切依赖 cwd 的代码；hooks 配置快照必须先于任何 hook 执行 |
| ST-10 schemas/types/migrations/constants | `schemas/hooks.ts`(7.9KB)、`types/*.ts`、`migrations/*.ts`(11个 1-4KB)、`constants/*.ts` | hooks 配置 schema（Zod）可映射 Python dataclass（归 HK 域）；types 纯类型定义无逻辑可转；migrations 是旧设置值→新设置值小迁移；prompts.ts 提示词文本为 Anthropic 专有，只抄组装结构 | config/ 已有迁移/校验结构 | 低 | ~150 行（hooks schema 映射） | 无 | 无高价值细节，注明存在即可 |
| ST-11 upstreamproxy（CCR 容器上游代理） | `upstreamproxy/`(upstreamproxy.ts 9.8KB + relay.ts 15KB) | **不转写**：/run/ccr 令牌、Linux prctl（Windows 无）、Bun FFI、容器 CA 下载——Claude Remote 容器专属；青小团 models/router.py(25KB) 自有路由 | — | 不转写 | 0 | — | 仅借鉴设计：全步骤 fail-open（任何一步失败仅告警并禁用，绝不让代理破坏会话）；NO_PROXY 列表覆盖多运行时解析形态（glob/suffix/apex） |
| ST-12 state/AppStateStore + context(.tsx) + costHook | `state/AppStateStore.ts`(21.8KB)、`context/*.tsx`(9个)、`costHook.ts` | **排除**：AppStateStore 是桥接 Ink UI 的状态层（通知/todo/MCP 连接/权限上下文/补全边界），依赖 React 与 bridge 回调；context/ 全是 React Context；costHook 是 React useEffect——均属壳侧/UI 层 | — | 排除 | 0 | — | 其中 CompletionBoundary 类型（complete/bash/edit/denied_tool 四态）与 saveCurrentSessionCosts 调用点可作实现参考 |

---

## 四、明确不转写 / 排除清单（汇总）

| 类别 | 内容 | 理由 |
|---|---|---|
| UI 渲染层 | `ink/`(79)、`screens/`、`components/`(43)、`moreright/`、`outputStyles/`、`keybindings/`、`vim/`、`voice/`、`state/AppStateStore`、`context/`(全部 .tsx React Context)、`costHook.ts`、`utils/ansiToPng.ts`、`utils/messages.ts`(UI 文案) | 按硬约束：转写目标是 CLI/本地引擎角色，不碰 Electron/浏览器渲染层 |
| **勘误：engine/src/hooks/ 全部 76 文件** | React/Ink UI hooks（useCanUseTool 等），非事件中间件 | 真实 hook 引擎在 types/hooks.ts + services/tools/toolHooks.ts + utils/hooks.ts（本清单 HK-2/3/4/5/7 已覆盖） |
| Electron/平台专属 | `native-ts/`(NAPI/yoga-layout)、`remote/`、bridge/ 远程鉴权/轮询/JWT、upstreamproxy(CCR 容器)、setup.ts 的 iTerm2/Terminal.app 备份恢复、tmux/iTerm2 分屏、`utils/swarm/backends/` 分屏后端、appleTerminalBackup | 平台相关或绑定远程服务，Windows/本地引擎无意义 |
| 空脚手架 | `plugins/`(initBuiltinPlugins 注册为空) | 无可转写逻辑 |
| 青小团已强、不重复补贴 | hooks 整体、skills 整体、cron 主体、权限规则引擎（fnmatch+参数粒度+网络白名单）、注入扫描、影响半径/ledger 回滚、ReAct 循环本体、Auto Memory 主体（memory/store.py）、harden/ 供应链安全、MCP 传输本体（stdio/http/sse framing）、auth.ts 整体(88KB) | 青小团已对标或强于 Claude Code |
| 小众/低收益 | `buddy/`(gacha 虚拟宠物)、`forkSubagent.ts`(prompt-cache 字节对齐)、cron jitter、per-agent MCP server | 游戏化 UI / 小众性能项 / 多会话舰队场景 / 属他域 |

---

## 五、建议优先转写的 Top 5

1. **stream-json 线协议适配层（EC-1 + EC-2 + EC-3 + EC-4 + EC-5 打包）** —— 青小团完全不会说 Claude 线协议，而壳只认 init/stream_event/result 信封；这是"替换底层后壳能否继续工作"的决定性契约，建议作为第一个里程碑：Python 引擎用同样 argv 被 bridge-server.cjs 拉起、吐出合法 init→stream_event→result，**壳零改动即可对话**（复用 acp/server.py 的 stdio 长驻骨架，预估 1300–2000 行）。
2. **异步后台子 Agent + 结果回灌 + 续作 worker（MA-1 + MA-2）** —— 青小团子 Agent 是同步阻塞、跑完即弃，缺"后台跑+结果自动回来+按 agentId 续作"的运行时调度；这是能力基线 ①/⑩ 的最大结构性缺口（预估 700–1100 行）。
3. **Git Worktree 会话状态机（OP-1 + OP-2）** —— 青小团子代理隔离在用 tempfile 模拟（无分支语义、无法 merge 回灌、泄漏无人清理）；WorktreeSession 状态机+createAgentWorktree/removeAgentWorktree+cleanupStaleAgentWorktrees 是结构性差距（预估 750–1150 行）。
4. **Plan Mode 本地审批门（HK-1）** —— 青小团本地 exit_plan_mode 直接放行写操作、无人工确认门，模型可自说自话提交计划立刻开改；~150–250 行纯逻辑，安全收益最大。
5. **MCP 服务端主动请求 + 大结果落盘（MC-1 + MC-2）** —— 青小团 MCP 客户端骨架已完整但回 -32601、大结果直接丢弃/灌爆上下文；这两个补丁决定能否对接现代 MCP server 生态并保住上下文预算（预估 600–750 行）。

**顺位说明**：ST-1（跨进程文件锁）是并发写的前置基础，建议随任意第一批任务顺手做（~250 行）；EC-6（control_request RPC）在当前壳 bypassPermissions 部署下不触发，可延后；A5（团队共享任务清单）最重且依赖 MA-1/2，放最后。

---

## 六、探查覆盖与验证声明

- 6 个探查域对 engine/src 全部子目录/顶层文件实现了覆盖：多Agent编排（coordinator/tasks/Task/assistant/buddy/query 子目录+subagent/team 承载）、Hooks+Skills+Plan（types/hooks+services/tools/toolHooks+utils/hooks+skills+Plan Mode 定位）、MCP+工具框架（services/mcp+Tool.ts+tools.ts+框架基础设施+native-ts）、运维类（worktree/secretScanner/cron 承载）、引擎核心与协议（QueryEngine/query/cli/bridge/server/entrypoints/bootstrap/commands 框架）、状态与支撑（context/history/cost-tracker/setup/memdir/state/schemas/types/constants/upstreamproxy/migrations/utils/services 抽样）。
- 关键结论均已对照源码抽查核实（如 runtime/mcp 三传输客户端存在、cli/print.ts 与 structuredIO.ts/ndjsonSafeStringify.ts 存在、services/tools/toolHooks.ts 存在、entrypoints/sdk/coreSchemas.ts 存在、utils/messages/systemInit.ts 存在、tuan_cli tools/subagent_tool.py 与 messaging_tool.py 存在、core/worktree_layer.py 仅 CRUD）。
- 全程只读：未修改 engine/、tuan_cli/、electron/ 任何文件，未运行任何构建/安装/执行命令。
- 各域 findings 中间产物（scan-multiagent.md / scan-hooks-skills.md / scan-mcp-tools.md / scan-ops.md / scan-engine-core.md / scan-state-support.md）保留于各探查代理 artifacts 目录，本文件为整合后的唯一交付清单。
