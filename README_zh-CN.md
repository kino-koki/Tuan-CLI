# 青小团 · Tuan-CLI

> **「Model + Harness = Agent」** —— 把「会思考」和「靠谱地跑」拆开，两者都交到你手里。
> 一个安全优先、模型无关、纯 Python 的 AI Agent Harness。`v0.3.3` · MIT · Python ≥ 3.10

> ### 定位：安全优先的 Agent，尽量不牺牲开发体验
>
> **安全是优先项，不是可选项**；同时**不拿「打扰」冒充安全**。
>
> - **安全优先**：危险命令在**执行前**被拦（影响半径预演 → 硬红线 → 多阶段确认才放行），每一次写操作进事务账本，`/undo` 精确回滚。
> - **安全语义**：YOLO/`--yolo` 会自动批准通常需要确认的操作，但**不会**绕过硬红线。`--isolation` 提供引擎/进程级隔离，以减小影响半径并限制故障影响；它不是完整的系统级沙箱，也不能替代命令审批。
> - **保留开发体验**：文件读写、`git` 常规操作、包管理、跑测试、lint 等良性开发命令判定为 `none` —— **零确认、零拦截**（`safety_engine.is_benign_dev_command`）。只有真正危险的才升级为提示或拦截。
> - **可复现的度量**：我们的目标是「危险命令少放行、良性命令少打扰」，数字**必须由第三方可复现**，不卖无法验证的绝对承诺。内部基准见 [`bench/`](bench/README.md)：1 万条 bash/通用对抗样本 + 5 千条 PowerShell 对抗样本 + 2497 个手工绕过载荷（含灾难后果级断言）。**一条命令 `tuan safe bench` 全程本地复现**（不依赖网络与模型），`tuan safe report` 生成自包含 HTML 安全报告。当前代码实测（2026-10）：对抗样本 10k → 拦截召回 100% / 标记召回 100% / 误杀率 0.45% (5 条) / 绕过 0；PowerShell 5k → 正确率 100% / 漏放 0 / 误杀 0；绕过矩阵 2497 载荷 → 绕过 0 / 误杀 1 / 灾难意图类别 100% 拦截。其中刻意保留了一些 fail-closed 的保守升级（如 `nc` 端口探测、`tar|ssh` 外传形态），误杀数字即来自这类保守判定，请以本地重跑为准。
> - **生态互操作**：不重复造生态，把 Claude Code / Hermes Agent 在本机积累的技能、命名 Agent、记忆、SOUL 人格与 MCP 配置**直接拿来用**（`tuan ecosystem`，一条命令双向搬运）；反向用 MCP 把自己挂进它们（`tuan ecosystem link`）——一个 Harness，三个生态的积累共用。

**语言/Language:** [English](README.md) · **简体中文** · [繁體中文](README_zh-GAT.md) · [日本語](README_ja.md) · [한국어](README_ko.md) · [Español](README_es.md) · [Português (Brasil)](README_pt-BR.md) · [Français](README_fr.md) · [Deutsch](README_de.md) · [Русский](README_ru.md)

**翻牌子前先看：** [SECURITY.md](SECURITY.md)（威胁模型）· [CHANGELOG.md](CHANGELOG.md)（版本纪律）· [ARCHITECTURE.md](ARCHITECTURE.md)（架构）· `tuan models list-providers`

---

## 一句话

核心思路是**模型负责想，Harness 负责让思考可控地跑**。青小团把「模型」和「宿主」解耦：模型热切换、多家供应商、本地离线都能跑；命令出事能撤回、动手前先算影响半径；微内核插件任你插。定位上它不是某家模型的绑定套壳，而是一个尽量中立、可自托管的终端 Agent 宿主。

**它不是什么**：不是某家模型的专属客户端（热切换、自托管、离线随你）；不是 IDE 的附属（标准终端工具，可被 ACP/IDE 驱动）；不是一层套壳（面向开发者的微内核插件架构 + 面向普通人的一条 `setup`）。

---

## 什么让它不一样

| 它给的 | 细节 |
|---|---|
| 🛡️ **安全优先** | 四道闸：静态评分、影响半径预拦截、YOLO 红线兜底、事务化账本 `/undo` 精确回滚 |
| 🎯 **开发体验** | 良性开发命令零确认零拦截、`/undo` 兜底、40+ 斜杠命令、`tuan safe allow` 显式放行、YOLO 一键省掉重复确认 |
| 🔌 **模型无关** | 58 家供应商 + 本地 Ollama + 运行时热切换 + 自动路由（`router.*`） |
| 🧠 **三种主循环** | ReAct / Planner-Execute / DevLoop，可插拔，"同一个内核跑不同的思考节奏" |
| 🔧 **微内核** | `@plugin` 一行声明，服务注册表、append-only 事件总线、hook 中间件 |
| 🗂️ **记忆** | SQLite FTS5 + 会话事件流；三层记忆、`/undo`、checkpoint、replay、Trajectory 导出 |
| 🧩 **生态** | MCP + ACP + **Claude Code / Hermes Agent 互操作**：技能 / 命名 Agent / 记忆 / SOUL / MCP 配置三方双向搬运（`tuan ecosystem`），彼此开箱即用 |
| 🤝 **Agent-of-Agents** | 一条 WebSocket 统管本机所有编码 Agent：Claude Code / Codex / Hermes / DeepSeek Harness / Kimi Code，按 `mode` + 健康度自动择优路由；运行态"委派不搬家" |
| 🌍 **十种语言** | 默认简体中文，界面随机给你换语种，接口也本地化 |
| 🐍 **纯 Python** | 大面积 `.py` 实现，MIT，想怎么啃怎么啃 |

---

## 快问快答

**Q：它是「独立自研」吗？不遮不掩说说。**
**代码**是自研的：内核与绝大部分能力（`core/`、`runtime/`、`arch/`、`tools/`、`ports/` 等）从架构到实现逐行手写，只对相关**协议**做接口对齐。但**理念与设计**确实大量借鉴、融合了已知的 Agent 项目——这不是需要遮掩的事，恰恰是站在前人肩膀上。两件事请分开看：**代码是清的，理念是借的**。唯一连「风格」都保留的部分是终端 TUI——`--tui` 的交互手感与配色刻意沿用 Kimi Code 的招牌风格（`#4FA8FF` 主色、moon 旋转加载、两行状态栏），因为「手感好就不折腾」，版权与署名见 [NOTICE](NOTICE)。完整的受借鉴清单见下文[受借鉴与融合](#受借鉴与融合)。

**Q：凭什么命令执行前总拦我？**
特性，不是 bug。危险命令默认要确认；YOLO 命中硬红线也一样拒。嫌烦就 `tuan safe allow <cmd>` 显式放行，别关安全。

**Q：被拦了是不是就只能绕道？**
不是。拦截只是第一层 —— 每次拦截/确认都会带上**命令感知的安全替代建议**（`tuan safe suggest <cmd>` 可随时查询）：`git push --force` 会给 `--force-with-lease`，`rm -rf` 会给回收站方案，`curl | sh` 会给"先下载审查"流程。我们不只拦你，还带你安全地做完。

**Q：/undo 能撤掉啥？**
所有进账本的写操作：单文件、单 step、整段。底层 = 事务化账本 + diff `reverse_transform` + 检查点快照。不是万灵丹，但把「误操作 = 必亏」变成「大概率能捞回来」。

**Q：怕它读我隐私文件？**
权限策略用 domain allow-list 圈住工具范围；网络出口有管控防外带；写出去的输出会对你密钥做脱敏。这些是安全机制的实际能力，具体默认开关与可配置项见 [SECURITY.md](SECURITY.md)。

**Q：想完全离线？**
`tuan models local` 探测，`/offline` 管理 Ollama。没网也照跑。

**Q：能写自己的工具/插件吗？**
当然。`@plugin` 声明元数据，`activate(kernel)` 里 `kernel.provide(...)` / `kernel.require(...)` 注册与取用服务，三步接入：

```python
from ..core.kernel import Kernel, Plugin

@plugin("my.tool", provides=["loop_registry"])
class MyTool(Plugin):
    def activate(self, kernel):
        def _handler(ctx, query: str) -> str:
            return f"echo: {query}"
        kernel.provide("tools.my", _handler)
```

---

## 生态互操作：Claude Code / Hermes Agent 开箱互用

青小团的第三条腿（在「安全优先」与「模型无关」之外）：**不重复造生态，直接把另外两个 Agent 生态的积累拿来用**。技能（SKILL.md 开放标准）、命名 Agent（`.claude/agents`）、记忆与人格（Hermes 的 `MEMORY.md`/`USER.md`/`SOUL.md`）、上下文文件（`AGENTS.md`/`CLAUDE.md`）、MCP server 配置——三方格式高度同构，青小团把它们打通：

```bash
tuan ecosystem scan                        # 探测本机 Claude Code / Hermes 及其资产（只读）
tuan ecosystem import all                  # 双方技能/子代理/记忆/SOUL/MCP 配置并入 tuan
tuan ecosystem export skills --to claude   # tuan 技能 → .claude/skills（Hermes 同款 --to hermes）
tuan ecosystem link                        # 反向挂载：让 Claude Code/Hermes 经 MCP 直接调 tuan
```

- **会话内自动生效**：Claude Code 装过的技能、Hermes 蒸馏出的技能，青小团直接可用（`~/.claude/skills`、`~/.hermes/skills` 已进搜索目录）；`tuan ecosystem serve` 把 tuan 的能力以 MCP server 暴露，Claude Code / Hermes 会话里直接多出 `tuan_*` 工具（记忆检索/写入、技能清单/读取、headless 任务派发）。
- **委派不搬家**：`claude_code_run` / `hermes_run` 两个工具让青小团把任务交给对方完整环境执行（对方用自己的配置/记忆/技能/MCP）。
- 完整文档：[`docs/ecosystem_bridge.md`](docs/ecosystem_bridge.md)（格式对照表 / 安全设计 / 目录结构）。

---

## Agent-of-Agents：一块面板统管本机所有 Agent

上文的生态桥在本体之间搬运**资产**。而 Agent-of-Agents 调度层（`tuan_cli/web/dispatch_server.py` + `tuan_cli/agents/`）搬运的是**任务**——它把你的手机或浏览器变成一块遥控器，统管本机装好的每一个编码 Agent。

- **五家适配器，一套协议。** Claude Code、Codex、Hermes、DeepSeek Harness、Kimi Code 各有一个轻量 `AgentAdapter`——一次 PATH 探测、一个 `build_command`、一套流式 `AgentEvent` 协议。不 fork、不复刻任何一个 Agent，青小团只驱动它们原生的 CLI。
- **按 mode + 健康度自动择优。** 任务带一个 `mode`（`chat` / `collaboration` / `lingma` / `gantong` / `boundless`），路由器并行探测全部适配器后按 `weights[mode]` + 健康分排序取最高——健康分：100 = PATH 命中且 `--version` 校验通过，70 = 版本未知，60 = 疑似同名工具，0 = 未安装；不健康的直接跳过；若一个可用的都没有，返回干净的 `NO_AGENT_AVAILABLE`，而不是静默兜底。
- **显式指定，fail-closed。** 传 `agent: "codex"` 可钉死引擎；未知 id 返回 `AGENT_NOT_FOUND`、没装返回 `AGENT_UNHEALTHY`——和青小团其余部分一样，越权即拒绝。
- **委派不搬家·运行态版。** 这是生态桥的运行态孪生：不是把技能*搬进*青小团，而是把*整桩任务*交给对方的原生环境执行——它的配置、记忆、技能、MCP 都原样不动。桥搬运资产，调度层跑活。
- **流式 + 审批。** 每家 Agent 经同一条 WebSocket 流式回传 `text` / `tool_call` / `stderr` / `approval` 事件；高风险步骤弹出 `[TUAN_APPROVAL]` 闸门，手机端可允许或拒绝，远程操控也不掉安全底线。
- **有自己的独立命令。** 调度层不止能跑服务器——`tuan dispatch` 让任意终端直接判定与派活（见下）。

```bash
tuan dispatch status                       # 探测本机 5 家代理（健康分 + 版本）
tuan dispatch route "修一下这个 flaky 测试"  # dry-run：完整打分明细，不执行
tuan dispatch run "修一下这个 flaky 测试"    # 路由 → 流式执行 → 汇总（--agent/--mode/--timeout）
tuan dispatch serve --port 8788            # WebSocket 在 ws://HOST:8788/tuan/dispatch/v1
# 手机 / WebUI → 选 mode → 青小团路由到本机最合适 Agent → 事件流回传
```

- 协议文档：[`docs/TUAN-DISPATCH-PROTOCOL.md`](docs/TUAN-DISPATCH-PROTOCOL.md)（事件 schema、hello 握手、审批流、`tuan dispatch` 命令参考）。

---

## 版本号说明

**为什么现在是 `0.3.3`，不是 `1.0`？** 遵循 [SemVer](https://semver.org/) 的诚实口径：**`0.x` 阶段意味着公共 API（CLI 接口、配置 schema、工具协议、插件契约）尚未冻结**，仍可能随迭代调整。Tuan-CLI 功能面已相当完整（安全拦截/事务回滚、模型无关热切换（58 家供应商 + 本地 Ollama）、三种主循环、微内核插件架构、三层记忆、生态互操作（MCP/ACP/Claude Code/Hermes 三方桥）、子代理与 Swarm、cron 与后台任务、Goal 模式与精确权限等，均配有测试），但**版本号反映的是接口稳定度，不是功能完成度**——功能齐全 ≠ API 该冻结。`1.0` 预留给公共 API 真正稳定、敢于承诺向后兼容之时。此前：破坏性变更在 `0.x` 内升 MINOR（并附迁移提示）、兼容功能升 MINOR、修复升 PATCH（见 [VERSION_POLICY.md](VERSION_POLICY.md)）。

| 版本号语义 | 说明 |
|---|---|
| `0.3.3`（当前） | **API 尚未冻结**：`0.x` 阶段允许破坏性调整，会预告 + 给迁移提示；不承诺向后兼容 |
| `1.0`（预留） | 公共 API 冻结、承诺向后兼容时启用；此后破坏性变更才升 MAJOR（2.0） |

---

## 受借鉴与融合

青小团不是从石头里蹦出来的，设计上明确借鉴、以下几种「已知 Agent 项目与协议」，在此如实列出（并尽可能在源码注释中标注原始出处）：

| 借鉴对象 | 借鉴了什么 |
|---|---|
| **DeepSeek Harness / Cordis** | 微内核 + 服务注册表 + append-only 事件总线的架构理念（`core/kernel.py` 有注释标注） |
| **Kimi Code** | 终端 TUI 的交互手感与配色风格（见 [NOTICE](NOTICE)） |
| **Claude Code** | `/` 斜杠命令体系、命名 Agents（`.claude/agents` 兼容）、Goal 模式、DevLoop 等交互范式的接口对齐 |
| **Hermes Agent** | 三层记忆、技能自进化闭环、SOUL 身份、自注册工具、cron 机制的语义对齐；`tuan ecosystem` 把双方记忆/技能/SOUL 双向同步 |
| **ACP（Agent Client Protocol）** | 作为 server/client 对齐其消息与握手语义，让 IDE 能驱动青小团 |
| **MCP（Model Context Protocol）** | 作为 client 对齐其协议，接入工具生态 |
| **OpenAI / Anthropic / Google 等厂商 API** | provider 适配器按官方 REST 语义实现，只做协议适配、不复刻内部实现 |

> 边界：**代码**为自研；**协议/接口**做对齐；**理念/设计**做借鉴与融合。若某处引用了具体实现细节，会在对应源码注释与 [NOTICE](NOTICE) 中声明。

---

## 快速上手

```bash
# 1) 装（自带 [dev] 全套餐；只要 API 可省 [openai] [mcp]）
git clone <此仓库> && cd tuan-cli
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 2) 配置一个模型（deepseek / groq-free / siliconflow-free / github-models / ollama …14 个内置 profile）
tuan setup
# 或手动：编辑 ~/.tuan/config.yaml
#   model.provider: deepseek
#   model.model: deepseek-chat
#   model.api_key_env: DEEPSEEK_API_KEY      # 密钥从不写明文

# 3) 开聊
tuan
# 或一句话冒烟：
tuan --print run "你好，一句话介绍你自己"
```

---

## 命令行面：50 个子命令（含嵌套共 194 个）+ 50 个斜杠命令

上手常用的几个：

| 命令 | 干啥 |
|---|---|
| `tuan` | 交互式 TUI（Kimi Code 皮肤） |
| `tuan setup` / `tuan models` | 配供应商 / 列出模型（58 家供应商、1400+ 内置模型） |
| `tuan sessions` / `--continue` / `--resume <id>` / `setup --skip` | 列出/恢复/删除已存会话，可从命令行直接续跑；首次运行自动弹出配置向导（`setup --skip` 跳过） |
| `tuan models update` | 本地更新模型/供应商目录：把内置最新清单合并写入 `~/.tuan/models_catalog.json`（离线、保留用户自建条目；`--check` 只报差异、`--background` 后台执行） |
| `tuan agent` | 命名 Agents（`.claude/agents` 兼容 + 三层发现） |
| `tuan acp` | 启动 ACP server，让 VS Code / Zed / JetBrains 来驱动你 |
| `tuan ecosystem` | **生态互操作**：`scan` 探测 Claude Code / Hermes；`import` 把双方技能/Agent/记忆/SOUL/MCP 配置并入 tuan；`export` 反向导出；`link` 让它们经 MCP 直接调用 tuan；`serve` 以 MCP server 运行（详见 [docs/ecosystem_bridge.md](docs/ecosystem_bridge.md)） |
| `tuan cron` | 后台定时任务 |
| `tuan doctor` / `tuan bench` | 体检 / 跑分 |
| `tuan arch demo` | 一键验证五层架构插件是否就位 |
| `tuan upgrade` | 检查并升级到最新版（`--check` 只查不装 / `--yes` 免确认 / `--version <ver>` 装指定版） |
| `tuan permissions list|test` | 查看权限规则，只读测试某次调用命中哪条规则 |

历史最常用的斜杠命令：`/plan`（只读模式）· `/model`（切模型）· `/undo`·`/impact`（回滚+影响半径）· `/swarm`（多 Agent 协作）· `/log`·`/stats`·`/cost`·`/budget`·`/goal`·`/sandbox`·`/offline`·`/verify`·`/audit`·`/more`·`/help`。完整列表在 TUI 里按 `Ctrl-G`。

> **Goal 增强**：`/goal all tests pass` 会自动拆成 3~7 个子步骤逐步验证续轮推进，进度落盘 `.tuan/goal.json`，`/goal status` 看步骤进度，`/goal clear` 停止。
> **精确权限**：规则可写到参数级，如 `tuan config set permissions.rules '[{"tool":"run_shell","param":"command","value":"rm -rf*","action":"deny"}]'`，再用 `tuan permissions test run_shell '{"command":"rm -rf /"}'` 验证命中。

---

## 三种主循环，同一种稳

- **ReActLoop**：想→做→看，默认节奏。
- **PlannerExecuteLoop**：先让强模型拆计划、再用便宜模型打执行（`router.*` 支持 plan/execute 分舱）。省钱思路。
- **DevLoop**：自动写→测→验的自找bug闭环（`/verify`，识别 Python/Node/Rust/Go 自动推断测试命令并自愈，最多 N 轮）。

---

## 安全模型：四道闸 + 记账撤销

1. **闸一 · 静态评分**：每个 shell 命令执行前经安全引擎门面 `SafetyEngine.score(params)` 判风险（none→critical），含间接调用展开（IFS、`$VAR`、命令替换、ANSI-C/八/十六进转义、PowerShell Base64、Unicode NFKC，递归 ≤32 层）。
2. **闸二 · 影响半径预拦截**：危险命令在**执行前**就告诉你它会碰到啥，`--impact` 可视化。
3. **闸三 · YOLO 红线兜底**：YOLO 可关闭逐条确认，但**关不掉**硬红线——文件系统/OS 级破坏（递归 `rm`、force-push、`chmod -R 000 /`…）不可自动执行。
4. **闸四 · 事务化账本**：一切写操作记账，`/undo` 用 diff `reverse_transform` + 快照精确还原。

规则优先级恒为 `deny > ask > allow`。要更顺手就用 `tuan safe allow <cmd>` 白名单，而不是一键关安全。

---

## 安全基准：一条命令复现

`tuan safe bench` 把三套可复现基准打包成一条命令（全程本地、不调用模型，第三方可原样复现）：

- **对抗样本基准** `bench/safety_bench_10k.py`：10,000 条 bash/通用命令（随机种子 20260906，可复现），输出拦截召回 / 标记召回 / 误杀率 / 绕过。
- **PowerShell 基准** `bench/bench_powershell_safety.py`：5,000 条（危险 2,300 / 安全 2,700），输出正确率 / 漏放 / 误杀。
- **绕过矩阵** `bench/bypass_matrix.py`：2,497 个手工对抗载荷，除模式匹配外还按**灾难后果类别**断言「每一类可怕后果是否全部实际拦截」。

```bash
tuan safe bench                 # 全量 (~3 分钟)
tuan safe bench --quick         # 快速自检 (~30 秒)
tuan safe bench --check         # 跑完与存档对比: 安全指标变差即退出码 1 (回归门禁)
tuan safe report                # 自包含 HTML 安全报告 (可分享)
tuan safe report --release      # RELEASE 版: 数字 + 时间戳 + git 提交三方绑定 (防数字过期)
```

当前代码实测（2026-10-25，`tuan safe bench` 复现）：

| 套件 | 规模 | 核心指标 | 绕过 | 误杀 |
|---|---|---|---|---|
| 对抗样本 | 10,000 条 | 拦截召回 100% · 标记召回 100% · 误杀率 0.45% (5 条) | 0 | — |
| PowerShell | 5,000 条 | 正确率 100% · 漏放 0 | 0 | 0 |
| 绕过矩阵 | 2,497 载荷 | 灾难意图类别 100% 拦截 | 0 | 1 |

口径说明：绕过矩阵刻意 fail-closed，保留少量保守升级（如 `nc` Unicode 变形探测、`tar|ssh` 外传形态），故存在「语义良性但被标记」的误杀；对抗样本的 0.45% (5 条) 误杀率同样来自这类保守判定 —— 5 条全为 `flag`（无一条硬拦），且是同一个 `tar|ssh` 良性用例的程序化前缀变体。数字以 `tuan safe bench` 本地重跑为准。

**CI 数字门禁**：`.github/workflows/security-ci.yml` 的 `safety-benchmarks` job 每次 push 都会全量重跑三套基准，并与提交进仓库的存档对比——数字变差（如出现绕过、灾难类别漏拦、误杀率明显上升）会让 CI **直接失败**。存档 `bench/security-bench.json` 与 README 表格数字一一对应。

---

## 大开脑洞的地方

- **记忆**：三层（用户级/项目级/会话级）+ SQLite FTS5（trigram），自动检测不可用就降级纯文本。
- **子代理**：类型化委派（general-purpose / explore / plan / coder）+ 隔离子代理 + 并发 Worker + Swarm 切碎长任务。
- **Cron & 后台**：`tuan cron start --detach`；headless 也能自己跑。
- **Hooks**：`PreToolUse` 能 `block` 或改写 `args`（`hooks.allow_edit_args`），给二开留了缝。
- **可观测**：`/stats`·`/audit`·`/impact`·`/bench`·`/cost` 齐全，成本摆上桌面。
- **crypto**：装了 `cryptography` 走 AES-GCM(AEAD)，否则回退 HMAC-SHA256 流密码，`open()` 缺 MAC/被篡改一律 fail-closed。

---

## 开发 & 契约

```bash
python -m pytest tests/ -q                 # 上千用例
python -m mypy tuan_cli                # 类型门禁
tuan --print run "你好，一句话介绍你自己"     # 冒烟
```

- **多语言文档纪律**：以 `README_zh-CN.md`（本文件）为权威母本，新增内容同步到全部 10 份，对译求「生动、零漂移」，**禁机械直译**。
- **版本**：`v0.3.3`（`0.x` 阶段 API 未冻结）；破坏性调整提前预告 + 迁移提示，`1.0` 预留给 API 冻结。
- **深挖**：九大引擎签名与新增工具走查见文末「附录」，插桩/二开/调试党请直接翻 `README_zh-CN.md` 尾部。

---

## 完全本地离线 · 无账户登录

Tuan-CLI **不提供任何账户登录**：没有 GitHub / Apple / DeepSeek 账号绑定，没有 OAuth 回调，没有登录态令牌落盘。
这是刻意的设计选择——**除了你自己配置的模型 API，一切都跑在本地**。

- **不登录即可完整使用**：文件读写、命令执行、记忆、技能、子代理、安全护栏全部本地。
- **唯一的「云端」是你选的模型 API**：密钥由你掌握，只用于向该端点发起模型请求，不经过任何第三方中转。
- **想整条链路零联网**：装 Ollama 或 llama.cpp，`tuan models local` 探测、`tuan models set ollama <模型>` 接入，全程不出网。

### 配置模型 API Key

```bash
tuan models set deepseek deepseek-chat   # 选择供应商与模型
tuan models                              # 交互式配置 (API Key 写入 ~/.tuan/.env)
```

密钥集中存放于 `~/.tuan/.env`（建议权限 600、勿入库），也可直接用环境变量（如 `DEEPSEEK_API_KEY`）。

---
## License & 关联阅读

- **License**：MIT（自由使用/修改/分发，保留版权声明）
- **必读**：[SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [NOTICE](NOTICE)（TUI 风格署名）

> 要「开箱即用的闭源体验」有别的选择；要「跑在自己的模型上、拿得到控制权、出事了能撤回」——这里给的是另一条路。
---

## 附录：九大引擎签名

青小团把高频、确定性能力拆成 **9 个纯 Python 外部引擎**，通过 JSONL IPC 协议与内核对话
（注册表见 `tuan_cli/ext/registry.py`，均可用 `tuan ext selftest` 一键健康检查）：

| 引擎 | 模块 | 能力 |
|---|---|---|
| diff | `ext/diff_engine.py` | 行/词级 Myers diff + patch + 3-way merge（`/diff`、`/undo` 底层） |
| crypto | `ext/crypto_engine.py` | PBKDF2-HMAC-SHA256 派生 + SHA256-keystream 流式加密 + 指纹 |
| index | `ext/index_engine.py` | FNV-1a 增量符号索引（代码检索） |
| ansi | `ext/ansi_engine.py` | 终端转义解析/剥离/渲染 |
| safety | `ext/safety_engine.py` | 最小影响半径护栏：风险评分 + blast radius（四道闸核心） |
| json | `ext/json_engine.py` | RFC 6901 Pointer / 逐路径 diff / 深合并 |
| search | `ext/search_engine.py` | 递归正则检索 |
| notify | `ext/notify_engine.py` | 跨平台桌面通知 |
| rules | `ext/rules_engine.py` | YAML 规则策略校验（无 eval 安全表达式） |

引擎统一入口：`tuan ext engines`（列表）· `tuan ext selftest`（健康检查）·
`tuan ext call <engine> <method>`（单次调用）· `tuan ext info <engine>`（方法清单）。
进程隔离场景下引擎经 `core/engine_isolation.py` 以真实 JSONL 子进程运行，崩溃/超时安全回落。

---

## 附录：新增工具走查

内置工具全部落在 `tuan_cli/tools/`（Shell / 文件系统 / 代码检索 / 记忆 / 子代理 /
MCP 等，`dispatch.py` 负责工具注册与分发）。新增一个工具只需三步：

```python
# 1) 定义工具类 (继承 tools/base.py 的 Tool)
from ..tools.base import Tool

class MyTool(Tool):
    name = "my_tool"                      # 工具名 (模型可见)
    description = "做某件事的工具"          # 一句话说明 (模型据此决定何时调用)
    parameters = {                        # JSON Schema 参数定义
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    def run(self, ctx, query: str) -> str:
        return f"结果: {query}"
```

```python
# 2) 注册进工具集 (修改 tools/dispatch.py 或所在工具的 registry)
#    注册后模型即可在会话中调用, 名称 = self.name
```

```python
# 3) 验证 (必备, 不是可选)
python -m pytest tests/test_tools.py -q     # 工具测试
python -m mypy tuan_cli                  # 类型门禁
```

要点：工具返回 `str` 给模型；危险操作在 `run()` 内先走 `ctx.confirm` /
`safety_engine` 判定（fail-closed）；写操作应登记事务账本以支持 `/undo`。
