/**
 * 内置技术文档内容（随 Tuan-Chat 一起分发，离线可读）。
 *
 * 内容来源：README.md / ARCHITECTURE.md / CAPABILITY-MATRIX.md /
 * SUPPORTED_MODELS.md / docs/TUAN-DISPATCH-PROTOCOL.md 等仓库内真实文档，
 * 由 DocPage 以 Markdown 渲染（复用聊天同款 .tuan-md 排版）。
 *
 * 维护约定：引擎发版时同步更新本文件（版本号见 DOC_ENGINE_VERSION），
 * 不写无法在仓库中找到依据的数字。
 */

export interface DocArticle {
  id: string;
  title: string;
  /** 一句话简介（导航与搜索展示） */
  summary: string;
  /** 额外搜索词（英文/别名），空格分隔 */
  keywords?: string;
  /** 正文（Markdown，标题从 h2 起，页面标题由组件渲染） */
  body: string;
}

export interface DocGroup {
  id: string;
  title: string;
  desc: string;
  articles: DocArticle[];
}

/** 文档对应的引擎版本（随 tuan_cli/version.py 同步） */
export const DOC_ENGINE_VERSION = 'v0.3.1';

export const DOC_GROUPS: DocGroup[] = [
  /* ================= 架构与内核 ================= */
  {
    id: 'arch',
    title: '架构与内核',
    desc: '微内核如何转动、能力如何插件化、主循环如何切换',
    articles: [
      {
        id: 'overview',
        title: '总体架构',
        summary: '模型负责思考，Harness 负责让思考可控地运行',
        keywords: 'architecture overview kernel',
        body: `青小团（Tuan-CLI）是一个**微内核 + 插件**架构的 Agent CLI。内核本身不携带任何 Agent 能力，只负责「插件注册 / 服务发现 / 生命周期事件」；所有能力（工具、模型适配器、记忆、技能、安全、路由、Loop）都以**插件**形式挂载。

公式：**模型负责思考，Harness（青小团）负责让思考可控地运行。**

## 五大子系统

| 子系统 | 职责 | 核心模块 | 关键类 / 函数 |
| --- | --- | --- | --- |
| **Kernel** | 微内核：插件生命周期、服务注册表、事件总线 | \`core/kernel.py\` | \`Kernel\` · \`Plugin\` · \`@plugin\` · \`ServiceContainer\` · \`MiddlewareEventBus\` |
| **Loop** | Agent 主循环策略：ReAct / 规划-执行 / 开发循环，可热切换 | \`core/loop_provider.py\` · \`core/loop_plugin.py\` | \`LoopRegistry\` · \`ReActLoop\` · \`PlannerExecuteLoop\` · \`DevLoopProvider\` |
| **Security** | 红线拦截、白名单放行、审计落盘、本地黑名单减负 | \`ext/safety_engine.py\` · \`core/whitelist.py\` · \`ext/security_gate.py\` | \`is_redline()\` · \`is_hard_redline()\` · \`WhitelistManager\` · \`SecurityEventBus\` |
| **Router** | 按任务难度自动升降级模型，省成本不降质，fail-safe | \`models/router.py\` · \`core/auto_route.py\` | \`ModelRouter.decide()\` · \`AutoRouter\` · \`RouteSession\` |
| **Memory** | SQLite FTS5 + 会话事件流；三层记忆、可撤销 | \`memory/\` · \`core/rewind.py\` | \`/undo\` · checkpoint · replay · Trajectory 导出 |

## 一次 \`tuan run "任务"\` 的生命周期

\`\`\`text
[1] 启动：load_dotenv() 载入 ~/.tuan/.env 密钥 → build_parser() 解析子命令
[2] Kernel 启动：扫描 @plugin 类，按 requires 拓扑排序逐个 activate()
[3] 构造 Agent：从 kernel.require("loop_provider") 拿当前 Loop
[4] Loop 驱动主循环：think → tool → observe → think …
[5] Security 把关：每次工具执行前 is_hard_redline / is_redline / 白名单判定
[6] Router 升降级：按难度与连续失败轮数决策，无凭证绝不切换
[7] 收尾：Loop 返回答案；账本记录改动；安全审计落盘可追溯
\`\`\`

调用链一句话：**Kernel 装载插件 → Loop 决定怎么思考 → Security 在每次工具执行前把关 → Router 按难度/卡住情况升降级模型 → 所有安全事件落盘审计。**

## 目录导览

| 目录 | 内容 |
| --- | --- |
| \`core/\` | 内核、Loop、Agent、白名单、安全总线、子代理、worktree 层 |
| \`ext/\` | 安全引擎族（归一化 / 红线库 / 评分门面）、安全闸门 |
| \`models/\` | 供应商目录、OpenAI 兼容适配器、路由器 |
| \`tools/\` | 工具实现（shell / 文件 / 会话工具 / MCP / subagent） |
| \`memory/\` | 三层记忆、自动提取 |
| \`skills/\` | 技能管理与运行时注入 |
| \`arch/\` | 备用执行路径（hooks 修复后与主链路口径一致） |
| \`agents/\` | Agent-of-Agents 调度层（适配器 + 路由器 + 发现） |
| \`hooks/\` · \`cron/\` · \`sandbox/\` | 事件钩子 / 定时任务 / 系统级沙箱 |

配套命令：\`tuan others\`（能力目录）、\`tuan safe\`（安全总入口）、\`tuan models\`（模型与本地 LLM）。`,
      },
      {
        id: 'kernel',
        title: '微内核与插件系统',
        summary: '@plugin 一行声明，provide/require 发现服务，内核零业务',
        keywords: 'kernel plugin service registry event bus',
        body: `## 内核只做三件事

\`core/kernel.py\`：

1. **插件注册 / 激活 / 依赖解析**——按 \`requires\` 拓扑排序后逐个 \`activate()\`；
2. **服务注册表**——插件之间经服务名发现，不直接 import；
3. **生命周期事件**——append-only 事件总线 + 中间件管线。

## 关键 API

\`\`\`python
@plugin("my.tool", provides=["loop_registry"], requires=["config"])
class MyTool(Plugin):
    def activate(self, kernel):
        kernel.provide("loop_registry", LoopRegistry())
\`\`\`

- \`kernel.provide("name", impl)\` / \`kernel.require("name")\`——服务注册与发现；
- \`kernel.emit("event", payload)\`——\`MiddlewareEventBus\` 支持中间件拦截与改写事件；
- \`ServiceContainer\`——懒工厂（\`provide_factory\`）、生命周期钩子、类型安全 \`typed()\`。

## 运行时切换的范本：LoopPlugin

\`LoopPlugin\`（\`core/loop_plugin.py\`）声明 \`provides=["loop_registry", "loop_provider"]\`、\`requires=["config"]\`；\`activate\` 里建 \`LoopRegistry\` 并注册三种内置 Loop。切换：

\`\`\`python
LoopPlugin.switch_loop(kernel, name)
# → registry.set_current(name)
# → 更新 loop_provider 快捷引用
# → kernel.emit("loop.switched", ...)   # 供 /loop 命令消费
\`\`\`

## 写自己的插件

三步：① 子类 \`Plugin\`；② 加 \`@plugin(...)\` 元数据；③ 在 \`activate(kernel)\` 里 \`provide\` 你的服务。无需改内核——**内核零业务**，任何能力想加，都做成插件，不要往内核塞逻辑。`,
      },
      {
        id: 'loops',
        title: '主循环（Loop）',
        summary: 'ReAct / 规划-执行 / 开发循环，一个内核三种思考节奏',
        keywords: 'loop react planner devloop',
        body: `Loop 是 Agent 的「思考节奏」。\`LoopRegistry\` 提供 \`register(loop)\` / \`set_current(name)\` / \`get_current()\` / \`list_available()\`，Agent 每轮通过 \`kernel.require("loop_provider")\` 读取当前 Loop。

## 三种内置实现

| Loop | 文件 | 节奏 |
| --- | --- | --- |
| \`ReActLoop\`（默认） | \`core/loop_provider.py\` | 标准 think → tool → observe |
| \`PlannerExecuteLoop\` | \`core/loop_provider.py\` | 强模型规划、便宜模型执行 |
| \`DevLoopProvider\` | \`core/devloop.py\` | 包装 DevLoop，自主迭代开发 |

## 切换语义

\`set_current("planner")\` 立即换「脑子」，不影响已加载的服务；事件 \`loop.switched\` 供 \`/loop\` 命令与 UI 消费。

**硬红线语义**：Loop 切换是策略切换，**不改变 Security 的拦截口径**——换 Loop 不等于换安全等级，硬红线在任何 Loop 下都永不自动执行。`,
      },
    ],
  },

  /* ================= 安全模型 ================= */
  {
    id: 'security',
    title: '安全模型',
    desc: '四道闸门、红线与白名单、可复现的安全基准',
    articles: [
      {
        id: 'gates',
        title: '四道闸门',
        summary: '评分 → 爆燃预检 → 红线/白名单 → 事务账本，中断不是安全的替代品',
        keywords: 'safety gates redline ledger undo',
        body: `安全是优先级，不是可选项；**中断不是安全的替代品**。危险命令在运行**之前**被拦截，每一次写入都记入事务账本，可精确 \`/undo\`。

| # | 闸门 | 位置 | 行为 |
| --- | --- | --- | --- |
| 1 | 静态风险评分 | \`ext/safety_score.py\` | \`SafetyEngine.score()\` 对命令打分，决定提醒 / 确认 / 阻断 |
| 2 | 爆燃半径预检 | 工具执行前 | 先展示「这条命令会碰到什么」，再决定放行与否 |
| 3 | 红线与白名单 | \`ext/safety_redline.py\` · \`core/whitelist.py\` | 硬红线永不自动执行；白名单命令直接放行 |
| 4 | 事务账本 + \`/undo\` | \`core/rewind.py\` | 每一次写入落账，单文件 / 单步 / 整轮回滚 |

## 开发者体验不被牺牲

文件读写、常规 \`git\` 操作、装包、跑测试与 linter 一律评分 \`none\`——**零确认、零阻断**（\`safety_engine.is_benign_dev_command\`）。只有真正危险的行动才升级为提醒或阻断。

## YOLO 的准确语义

\`--yolo\` 只对「本需确认」的操作自动批准，**不穿透硬红线**；\`--isolation\` 提供引擎/进程级隔离以缩小爆燃半径，它不是完整 OS 沙箱，也不替代命令审批。

## 审计

拦截 / 放行事件经 \`emit_command_blocked\` / \`emit_command_allowed\` 写入 \`~/.tuan/security-audit.jsonl\`，\`tuan safe status\` 查看路径与统计。`,
      },
      {
        id: 'redline',
        title: '红线、白名单与减负',
        summary: '两层判定、本地白名单、按 label 减负、四层沙箱',
        keywords: 'redline whitelist blacklist sandbox confirm',
        body: `## 两层判定

1. **硬红线**（\`is_hard_redline\`）：OS/文件系统级毁灭操作（\`rm -rf /\`、\`dd\`、\`mkfs\`、force push、\`shutdown\` 等 token 化检测）。即使在 YOLO 模式也**永不自动执行**。
2. **综合红线**（\`is_redline\`）：硬红线基础上叠加 \`_CRITICAL/_HIGH/_MEDIUM\` 正则库（含 SQL 破坏性操作 DROP/DELETE/TRUNCATE，归为「可确认关键级」，经多阶段确认放行）。

安全引擎按职责拆为四个模块：\`safety_engine.py\`（兼容转发层，旧导入路径不变）、\`safety_normalize.py\`（归一化 / 混淆还原：间接调用展开、ANSI-C/Base64/Unicode 还原）、\`safety_redline.py\`（红线模式库与判定）、\`safety_score.py\`（IPC 门面）。

## 白名单与黑名单减负

- \`tuan safe allow <命令>\` 把可信命令加入本地白名单（**红线命令拒绝加入**）；\`tuan safe deny\` 移除。
- 某些内置模式在你的环境属误杀或可信：在 \`~/.tuan/blacklist-override.json\` 声明要抑制的 label 关键字，\`tuan safe reduce <关键字>\` / \`tuan safe restore <关键字>\` / \`tuan safe blacklist\` 管理。
- **安全边界**：减负只抑制正则模式库条目；不可逆/OS 级的 token 化硬红线走独立判定，**永不**受减负影响。

## 多阶段确认与沙箱

- 极高风险 5 次、高风险 3 次确认（\`ext/security_gate.py\`），含 TOCTOU 脚本检测。
- 沙箱四层滤网（\`sandbox/\`）：L0 意图 / L1 信任 / L2 资源 / L3 强隔离（Windows jobobject、Linux landlock、Docker 等）。默认 \`enforce_required=False\`——缺强后端时**降级**为过滤 + 副本 diff 执行；置 \`True\` 则无强后端 fail-closed 拒绝执行。按你的威胁模型决定。

被拦截时不是只说不：\`tuan safe suggest <命令>\` 给出命令感知的安全替代（\`git push --force\` → \`--force-with-lease\`，\`rm -rf\` → 回收站配方，\`curl | sh\` → 先下载审阅）。`,
      },
      {
        id: 'bench',
        title: '安全基准与复现',
        summary: '一条命令本地复现全部数字，不发布无法第三方验证的承诺',
        keywords: 'bench benchmark reproducible report',
        body: `## 基准构成（\`bench/\`）

- **10,000** 条对抗性 bash/generic 样本；
- **5,000** 条 PowerShell 样本；
- **2,310** 条手工构造的绕过载荷（含灾难级后果断言）。

## 当前代码实测（2026-09）

| 基准 | 结果 |
| --- | --- |
| 对抗 10k | 阻断召回 100% / 标记召回 100% / 误报 1.87% / 绕过 0 |
| PowerShell 5k | 准确率 100% / 漏放 0 / 误报 0 |
| 绕过矩阵 2,310 | 绕过 0 / 误报 1 / 灾难意图类 100% 拦截 |

**诚实声明**：仍存在刻意 fail-closed 的保守升级（如 \`nc\` 端口探测、\`tar|ssh\` 外传形状的载荷），它们解释了误报数字；可用 \`tuan safe reduce\` 按 label 关键字调回，无需改代码。请以本地复跑为准。

## 复现方式

\`\`\`bash
tuan safe bench     # 离线复现全部基准（无需联网、无需模型）
tuan safe report    # 生成自包含 HTML 安全报告
\`\`\`

原则：**我们发布的任何数字，必须能被第三方在本地复现。**`,
      },
    ],
  },

  /* ================= 模型与路由 ================= */
  {
    id: 'models',
    title: '模型与路由',
    desc: '58 家供应商、本地 Ollama、按难度自动升降级',
    articles: [
      {
        id: 'providers',
        title: '供应商与模型目录',
        summary: '一份 OpenAI 兼容适配器覆盖 58 家，本地模型零密钥',
        keywords: 'provider models ollama llamacpp catalog',
        body: `## 为什么一份适配器能覆盖 58 家

所有 OpenAI 兼容端点（DeepSeek、OpenAI、OpenRouter、Moonshot、SiliconFlow、智谱、通义……）都暴露同一个 \`/v1/chat/completions\` 协议。\`OpenAICompatAdapter\` 只依赖稳定的接口表面：

- 消息格式（\`system\` / \`user\` / \`assistant\` / \`tool\`）；
- 工具调用（\`tools\` / \`tool_calls\` / \`tool\` 角色回填）；
- 流式 SSE（\`stream\` + \`stream_options.include_usage\`）；
- 错误码（429 / 5xx / 401）与可选 \`Retry-After\`。

新增一家兼容供应商通常**不需要写代码**：\`tuan setup\` 填 \`base_url\` + \`API_KEY\` 即可。非兼容供应商（如 Anthropic 原生协议）走独立适配器，但同样接入同一套 Agent 工具循环与安全护栏。

## 本地与离线

- \`models/provider_catalog.py\` 预置 \`ollama\`（:11434）、\`llamacpp\`（:8080/v1）等自托管供应商；
- \`models/openai_compat.py\` 对 localhost 端点**放通空 key**——本地 LLM 无需密钥；
- \`tuan models local\` 探测，\`/offline\` 管理。不联网，也能跑。

## 常用命令

\`\`\`bash
tuan models list-providers   # 58 家供应商与 1400+ 模型
tuan setup                   # 配置供应商
tuan /model                  # 会话内热切换 + 连通性测试
\`\`\`

传输层兼容性由 \`tests/test_e2e_mock_server.py\` 的本地 mock 端点离线验证：真实适配器走完 \`chat → tool_call → 安全评估 → 工具回填 → 最终回答\` 全链路，并覆盖 5xx 自动重试。`,
      },
      {
        id: 'routing',
        title: '自动路由',
        summary: '按难度升降级：省钱、不降质、无凭证绝不切换',
        keywords: 'router auto route escalate stuck',
        body: `## ModelRouter.decide()

\`models/router.py\` 返回 \`{switch, reason, provider, model, capabilities, difficulty}\`，四条决策规则：

1. **自定义模型**（不在预设目录）→ 不切换，尊重你指定的「脑子」；
2. 难度超出当前模型能力，或缺少必需能力（如挂图需 vision）→ **升级**；
3. 更便宜且仍能胜任 → **降级**省钱；
4. 候选模型**无配置密钥** → 保持当前，**绝不切到无凭证端点**（核心 fail-safe）。

## AutoRouter（\`core/auto_route.py\`）

- \`RouteSession\` 跨 turn 记录 \`stuck\`（连续失败轮数）；
- \`plan_execute\`：规划首轮用强模型（难度 10），执行阶段用便宜模型（难度 2）；
- \`escalate_on_stuck\`：便宜模型连续失败达到阈值 → 升级强模型救场，救完降回。

路由与 Loop 并行，每轮决策；相关行为可在 \`router.*\` 配置项调整。`,
      },
    ],
  },

  /* ================= Agent of Agents ================= */
  {
    id: 'agents',
    title: 'Agent of Agents',
    desc: '一条 WebSocket 调度本机五家代理：委派，而非迁移',
    articles: [
      {
        id: 'dispatch',
        title: 'Tuan 调度协议 v1',
        summary: 'WebSocket /tuan/dispatch/v1，配对码握手，事件流回传',
        keywords: 'dispatch protocol websocket pair 8788',
        body: `Tuan-Chat 手机端 ⇄ 桌面端（Tauri）之间的 WebSocket 调度协议。桌面端把「任务」路由给本机 5 家本地代理（Claude Code / Codex / hermes / DeepSeek Harness / Kimi Code），手机只做「发起 + 看流 + 审批 + 取消」。

## 传输层

- **协议**：WebSocket，局域网明文 \`ws://\`，公网 \`wss://\`（TLS 由反向代理或桌面端证书提供）；
- **路径**：\`/tuan/dispatch/v1\`；**默认端口** \`8788\`（Tuan-CLI Web 是 \`8765\`）；
- **编码**：UTF-8 JSON；**帧上限** 256 KB（附件走文件通道）；
- **心跳**：客户端每 30s 发 \`ping\`，服务端 60s 未收到视为掉线。

每条消息必带 \`type\` 字段；**未知 type 必须忽略**（前向兼容）。版本策略：协议主版本 = URL 路径段，不兼容变更升 v2。

## 握手：hello / pair

连接建立后服务端立即下发 \`hello\`（不需要客户端先说话）：

\`\`\`jsonc
{
  "type": "hello", "protocol": 1,
  "hostname": "DESKTOP-ABC1234", "version": "0.3.1",
  "auth_required": true, "pair_code": "AB12",
  "agents": [                       // 每次连接重新扫 PATH 的实时探测，非缓存
    {"id": "claude-code", "name": "Claude Code", "healthy": true,  "version": "1.2.3"},
    {"id": "codex",       "name": "Codex",       "healthy": false, "reason": "not found in PATH"}
  ],
  "mode": "chat"
}
\`\`\`

客户端回 \`{"type": "pair", "code": "AB12"}\`；服务端回 \`pair_ok\` 或 \`error\`。

## 任务与事件流

\`\`\`text
client → dispatch {task_id, agent, mode, prompt}   # 发起任务
server → accepted {task_id, agent}                 # 受理
server → event {task_id, kind, ...}                # 事件流：
           kind = text       代理输出的文本片段
           kind = tool_call  工具调用（文件读写 / shell 执行）
           kind = approval   高风险操作需人工审批
           kind = stderr/error
           kind = done       任务结束
           kind = meta       元信息（代理版本、模型名）
client → approval {task_id, id, decision}          # 审批回传
client → cancel {task_id}                          # 取消
client → ping / list_agents                        # 心跳 / 刷新代理健康状态
\`\`\`

错误码与安全边界（配对码、局域网暴露面、审批不可绕过）见 \`docs/TUAN-DISPATCH-PROTOCOL.md\`。桌面端启动：

\`\`\`bash
python -m tuan_cli.web.dispatch_server --port 8788
\`\`\``,
      },
      {
        id: 'adapters',
        title: '适配器与路由',
        summary: '五家适配器、注册优先级、mode 打分 + 健康度',
        keywords: 'adapters router claude codex hermes kimi deepseek',
        body: `## 五家适配器（\`tuan_cli/agents/adapters/\`）

| id | 代理 | 说明 |
| --- | --- | --- |
| \`claude-code\` | Claude Code | 本机已积累的技能 / 命名代理 / 记忆直接复用 |
| \`codex\` | Codex | OpenAI Codex CLI |
| \`hermes\` | Hermes Agent | 三层记忆 / 技能自进化生态 |
| \`deepseek-harness\` | DeepSeek Harness | Cordis 微内核同源理念 |
| \`kimi-code\` | Kimi Code | Moonshot 终端代理 |

## 路由规则（\`agents/router.py\`）

两种模式：

- **显式指定**（\`task.agent != "auto"\`）：直接用；未安装返回 \`AGENT_NOT_FOUND\`，不健康返回 \`AGENT_UNHEALTHY\`；
- **自动**（\`task.agent == "auto"\`）：按 \`mode\` 打分 + 健康度 + 注册优先级排序。

打分细节：

- 每家适配器自带 \`weights\` 字典（\`mode\` → 分数），未匹配的 mode 默认 1 分；
- \`healthy=False\` 的代理**直接跳过**，不参与打分；
- 同分按注册顺序：\`claude-code > deepseek-harness > codex > kimi-code > hermes\`。

## 事件协议

\`agents/base.py\` 定义 \`AgentAdapter\`（\`detect()\` / \`build_command()\` / 事件流）、\`AgentEvent\` / \`EventType\`、\`TaskRequest\`、\`AgentInfo\`。\`discover_agents()\` 实时探测本机安装了哪些代理。

理念一句话：**委派，而非迁移**——本机已有哪家代理就把任务派给它，资产留在原处。`,
      },
    ],
  },

  /* ================= 记忆与会话 ================= */
  {
    id: 'memory',
    title: '记忆与会话',
    desc: '三层记忆、事务账本、撤销与检查点',
    articles: [
      {
        id: 'memory',
        title: '三层记忆',
        summary: 'SQLite FTS5 全文检索 + 会话事件流 + 自动提取',
        keywords: 'memory fts5 sqlite compact consolidate',
        body: `## 结构

- **SQLite FTS5**：对话与记忆的全文检索索引；
- **会话事件流**：每次交互以事件形式落盘（\`~/.tuan/\`），可回放、可导出；
- **自动提取**（\`memory/auto_extractor.py\`）：从对话中自动提炼值得长期记住的信息。

## 常用命令

| 命令 | 作用 |
| --- | --- |
| \`/memory\` | 查看 / 管理记忆 |
| \`/compact\` | 压缩上下文，保留要点 |
| \`/consolidate\` | 把短期记忆巩固为长期记忆 |
| \`/context\` | 查看当前上下文构成 |
| \`/stats\` | 会话统计 |

会话数据全部留在本机，不上云。`,
      },
      {
        id: 'undo',
        title: '撤销与检查点',
        summary: '每一次写入都入账：单文件、单步、整轮都能回滚',
        keywords: 'undo rewind checkpoint replay trajectory impact blast',
        body: `## 事务账本

所有**经手账本的写入**都可撤销：单个文件、单个步骤、整个回合。底层是事务账本 + diff \`reverse_transform\` + checkpoint 快照。

\`\`\`text
/undo        回滚最近一次写入（可多次）
/rewind      回到指定检查点
/checkpoint  创建检查点
/replay      重放一段会话
/impact      预览某操作的影响面
/blast       爆燃半径分析
\`\`\`

## Trajectory 导出

完整轨迹（思考 / 工具 / 结果）可导出，用于复盘、评测与回归。

不是万能药，但把「一次手滑必然丢失」变成「大概率救回」。`,
      },
    ],
  },

  /* ================= Tuan-Chat 桌面端 ================= */
  {
    id: 'chat',
    title: 'Tuan-Chat 桌面端',
    desc: 'Tauri 外壳 + 内嵌引擎，桌面完整能力、移动端降级直连',
    articles: [
      {
        id: 'shell',
        title: '双端架构',
        summary: '桌面端引擎承载完整 Agent 能力，Android 走 Rust 通道直连',
        keywords: 'tauri engine bundle android webview rust',
        body: `Tuan-Chat = **Tauri 外壳**（React + TypeScript + Vite + Tailwind）+ **内嵌引擎**（\`Tuan-App/engine/tuan_cli/\`，由根目录 \`tuan_cli/\` 同步构建）。

## 桌面端（Windows / macOS）

- 引擎承载完整提示词 / 工具循环 / 安全闸门；
- \`session\` 复用对话 id 续接上下文；
- 审批卡由引擎 \`_ask_approval\` 阻塞发起，UI 回传 \`allow\` / \`deny\`。

## Android 端

- 本机**没有**本地引擎：走 Rust agent 通道（\`src-tauri/src/agent.rs\` / \`agent_tools.rs\`）直连接口 + 轻量工具循环，多轮上下文由前端 history 拼接；
- 兼容 Android 8.0 的 Chrome 68 WebView：不用 \`color-mix()\` / \`:has()\` / 100dvh，\`env()\` 均带 \`0px\` 兜底；
- 安全区（\`--sat/--sar/--sab/--sal\`）、软键盘避让、伪路由返回栈、侧栏抽屉四件套在 \`platform/mobile.ts\` 统一接线。

## 降级模式

引擎缺失也能**纯对话**：不需要引擎即可立刻聊天（无工具调用与安全闸门）。装好引擎后从标题栏状态灯随时回来。

## 引擎同步

\`\`\`bash
python scripts/sync_engine_bundle.py            # 从根 tuan_cli/ 重建内嵌引擎
python scripts/sync_engine_bundle.py --dry-run  # 预演
python scripts/sync_engine_bundle.py --check    # 指纹校验
\`\`\``,
      },
      {
        id: 'install',
        title: '引擎自检与安装',
        summary: 'check_engine 真实探测，四步向导，命令真实可复制',
        keywords: 'check_engine install setup wizard python requirements',
        body: `## 自检返回什么

Rust \`check_engine\` 返回：\`ok\` / \`reason\` / \`python\` / \`app_version\` / \`engine_version\` / \`engine_root\`。启动加载序列的第三行「本地引擎」反映**真实**结果（就绪 / 未启用·降级 / 检测中），不表演假进度。

## 四步安装向导

1. **定位引擎目录**——确认安装目录下存在 \`engine\\\`（含 \`tuan_cli\\\` 与 \`requirements.txt\`）；
2. **准备 Python 3.10+**——\`python.org\` 安装（勾选 Add to PATH），或把便携版 \`python.exe\` 放到 \`<安装目录>\\engine\\python\\\`；
3. **安装依赖**——\`pip install -r "<安装目录>\\engine\\requirements.txt"\`（或开发机 \`python scripts/install_engine_env.py\`）；
4. **重新检测**——真实回调 \`check_engine\`，通过即进入主界面。

每一步的命令都可一键复制；随时可「先以降级模式进入」——跳过选择会持久化（\`tuan.engineSetupDismissed\`），不再每次启动弹，但从标题栏状态灯 / ⌘K「引擎安装向导」随时回来。

**诚实原则：不做假下载表演。**`,
      },
      {
        id: 'commands',
        title: '命令与快捷键',
        summary: '38 个子命令、50+ slash 命令、桌面快捷键',
        keywords: 'commands subcommands slash shortcuts hotkeys',
        body: `## 子命令速览（38 个）

| 分组 | 代表命令 |
| --- | --- |
| 运行 | \`tuan run\` · \`tuan chat\` · \`tuan dev\` · \`tuan agent\` · \`tuan acp\` |
| 安全 | \`tuan safe\`（allow/deny/reduce/bench/report/suggest/status） |
| 模型 | \`tuan models\`（list-providers/local/switch） · \`tuan setup\` |
| 生态 | \`tuan ecosystem\`（link/import/export） · \`tuan mcp\` · \`tuan hooks\` · \`tuan skill\` |
| 记忆会话 | \`tuan memory\` · \`tuan rewind\` · \`tuan session\` · \`tuan trajectory\` |
| 系统 | \`tuan doctor\` · \`tuan others\` · \`tuan upgrade\` · \`tuan web\` |

\`tuan help quickstart\` 直接在终端里看快速上手；\`tuan others\` 浏览能力目录。

## Slash 命令精选（50+）

\`\`\`text
/undo /rewind /checkpoint /replay /impact /blast     撤销与影响面
/memory /compact /consolidate /context /stats        记忆与上下文
/model /provider /mode /route /effort                模型与路由
/plan /subagent /swarm /handoff /goal                编排与协作
/mcp /mcp-tools /skills /hooks /permissions          扩展与权限
/personality /offline /cost /budget /diff /export    个性化与观测
\`\`\`

## Tuan-Chat 快捷键

| 快捷键 | 作用 |
| --- | --- |
| \`⌘N\` / \`Ctrl+N\` | 新建对话 |
| \`⌘K\` / \`Ctrl+K\` | 命令面板 |
| \`⌘O\` / \`⌘,\` | 打开设置 |
| \`⌘G\` | 使用教程 |
| \`⌘B\` | 切换侧栏 |
| \`⌘F\` / \`Ctrl+F\` | 聚焦对话搜索 |
| \`Enter\` / \`Shift+Enter\` | 发送 / 换行 |
| \`Esc\` | 返回聊天页 |`,
      },
    ],
  },

  /* ================= 生态与扩展 ================= */
  {
    id: 'eco',
    title: '生态与扩展',
    desc: 'MCP / ACP / 生态互操作，不重建生态只复用资产',
    articles: [
      {
        id: 'mcp',
        title: 'MCP 与 ACP',
        summary: '接入外部工具，也被 IDE 驱动',
        keywords: 'mcp acp stdio sse http vscode zed',
        body: `## MCP（Model Context Protocol）

- 客户端：\`tools/mcp/\` 支持 stdio / SSE / HTTP 三种传输；\`/mcp\` 与 \`tuan mcp\` 管理；
- 安全：所有 MCP 调用经 \`security_gate.decide_mcp_tool()\` 把关，与 shell 同一套红线口径；
- 服务端：\`ecosystem/mcp_server.py\` 把 tuan 自己挂成 MCP server，供其他宿主调用。

## ACP（Agent Client Protocol）

\`tuan acp\` 让 VSCode / Zed / JetBrains 等编辑器通过 ACP 驱动青小团——它是纯终端工具，但可以被 IDE 当「引擎」用。

## Hooks 与定时任务

- \`hooks/\`：PreToolUse / PostToolUse / SessionStart / SessionEnd / UserPromptSubmit 事件挂脚本，matcher 按工具名过滤（支持 \`*\` / \`|\` / \`!\`），stdout 回传 decision（block / modified_args）；
- \`cron/\`：零依赖 5 字段 cron 解析器，\`tuan cron add --cron "..."\` 标准排期，daemon 常驻执行。`,
      },
      {
        id: 'interop',
        title: '生态互操作',
        summary: '复用本机已有资产：技能、命名代理、记忆、SOUL、MCP 配置',
        keywords: 'ecosystem interop claude code hermes soul link',
        body: `我们**不重建生态**——本机 Claude Code / Hermes Agent 已经积累的资产，直接复用：

\`\`\`bash
tuan ecosystem            # 双向搬运：skills / named agents / memory / SOUL / MCP 配置
tuan ecosystem link       # 把 tuan 挂回它们（经 MCP），一个 harness 三份资产
\`\`\`

- **技能**：\`.claude/skills\` 等目录三层发现 + frontmatter 解析，运行时注入；
- **命名代理**：\`.claude/agents/*.md\` 直接成为 \`subagent\` 工具可调用的白名单；
- **SOUL 人格**：跨生态携带，切生态不切人格。

理念：**代码是自己写的，思想是共享的。** 完整灵感与致谢清单见仓库 \`NOTICE\` 与 README「Inspiration & attribution」——包括 \`--tui\` 终端皮肤对 Kimi Code 签名交互与配色的明确致谢。`,
      },
      {
        id: 'version',
        title: '版本与更新',
        summary: '单一版本源，0.x 的诚实语义',
        keywords: 'version semver changelog upgrade policy',
        body: `## 单一版本源

所有模块统一从 \`tuan_cli/version.py\` 读取 \`__version__\`，升级主包只改这一处。当前：**v0.3.1**（发布名 \`tuan-cli\`）。

## 为什么是 0.x 而不是 1.0

诚实的 SemVer 语义：\`0.x\` 表示公共 API（CLI 表面、配置 schema、工具协议、插件契约）**尚未冻结**，发布间仍可能变化。青小团功能面已经很宽（安全闸门 / 事务回滚 / 58 家模型中置热切换 / 三种主循环 / 微内核插件 / 三层记忆 / 生态互操作 / 子代理与 Swarm / 定时任务），但**版本号反映的是接口稳定性，不是功能完备度**。1.0 留给 API 真正稳定、能承诺向后兼容的那一天。

在此之前：破坏性变更 bump MINOR（附迁移提示），兼容新功能 bump MINOR，修复 bump PATCH（见 \`VERSION_POLICY.md\`）。

## 升级

\`\`\`bash
pip install -U tuan-cli
tuan upgrade        # 或内置升级命令
\`\`\`

发布说明见 \`CHANGELOG.md\`；本文档随引擎版本内置更新（当前文档版本 \`${DOC_ENGINE_VERSION}\`）。`,
      },
    ],
  },
];

/** 扁平化的全部文章（命令面板搜索用） */
export const DOC_ARTICLES: DocArticle[] = DOC_GROUPS.flatMap((g) => g.articles);

/** 按 id 找文章 */
export function findDocArticle(id: string): DocArticle | undefined {
  return DOC_ARTICLES.find((a) => a.id === id);
}
