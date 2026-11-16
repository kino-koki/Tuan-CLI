# 青小团 Tuan-CLI —— 最强多理念融合 Agent 系统完善路线图

> 目标：把青小团从"已融合 DeepSeek Harness / Kimi Code / Claude Code / Hermes / MCP / ACP 理念的成熟 Agent 宿主"，推进到"**最强多理念融合 Agent 系统**"。
>
> 作者：AI 协作会话 · 2026-11-15 · 版本：v1（草案，待评审后进入实现）
> 关联：[CAPABILITY-MATRIX.md](parity/CAPABILITY-MATRIX.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [ROADMAP.md](ROADMAP.md)

---

## 0. 为什么这份路线图存在

青小团目前是一个**插件容器式分层 Agent 宿主**，已具备：四道安全闸门、事务账本 `/undo`、58 Provider 热切换、三主循环（ReAct/Planner-Execute/DevLoop）、三层记忆、技能自进化、MCP/ACP 生态互操作、Agent-of-Agents 派发、多 Agent 协作（swarm/collaboration）、cron、subagents、Goal mode。

深度诊断（2026-11-15）表明：**记忆、上下文工程、可观测性、模型路由、MCP/ACP 互操作、沙箱、CLI 命令面已「完整」**。真正限制它成为"最强"的缺口集中在四个理念维度，本路线图逐一补齐。

### 已融合理念来源（基线）

| 来源 | 理念 | 落地 |
|---|---|---|
| DeepSeek Harness / Cordis | 插件容器 + 服务注册表 + append-only 事件总线 | `core/kernel.py` |
| Kimi Code | TUI 交互手感与配色 | `tui/` |
| Claude Code | `/` 斜杠命令、命名 Agent、Goal、DevLoop | `cli/`、`agents/`、`modes/` |
| Hermes Agent | 三层记忆、技能自进化、SOUL、cron | `memory/`、`self_improve/`、`cron/` |
| ACP | 客户端/服务端握手语义 | `runtime/acp/` |
| MCP | 客户端协议接入工具生态 | `runtime/mcp/`、`ecosystem/` |
| Agent-of-Agents | 五适配器 + mode/health 路由 | `agents/router.py`、`web/dispatch_server.py` |

---

## 1. 缺口矩阵（诊断结论）

| # | 理念维度 | 现状 | 缺口 | 优先级 |
|---|---|---|---|---|
| A | **反思性自我进化闭环** | `self_improve/` 有蒸馏/规则/技能生成 | 缺"执行→自评→改进→回归验证"真实闭环 | ★★★ |
| B | **持久化多 Agent 编排与故障恢复** | `swarm.py`/`collaboration_protocol.py` 存在 | 缺跨会话群组状态持久化、任务 DAG 断点恢复、失败重试/回滚 | ★★★ |
| C | **人机协同审批增强** | `sandbox/unattended.py`、`ui/approval_overlay.py`、`tools/mcp/policy.py` | 缺策略可编程审批树、与审计追溯联动 | ★★ |
| D | **UX 双栈收敛** | `tui/`(40+文件) 与 `ui/` 并存 | 双栈并存、大量 parity/slogans 装饰、主题不统一 | ★★ |

> 已完整、无需重复投入：长期记忆、上下文工程、可观测性、模型路由、MCP/ACP 互操作、沙箱。

---

## 2. 分阶段实现计划

> 原则：每个阶段必须**有测试 + 可复现验证**；不破坏现有未提交工作（在独立分支上进行）；改动聚焦、不过度工程。

### 阶段 A —— 反思性自我进化闭环（优先级最高）

**目标**：构建 `执行 → 自评 → 改进 → 回归验证` 的可循环闭环，让青小团能真正"从经验中成长"。

- **A1. 评测器（Evaluator）**：对一次任务的产物做结构化自评（正确性/完整性/性能/风格维度打分），产出 `EvaluationResult`。
- **A2. 回归验证器（RegressionGate）**：改进前后跑同一任务集，对比评分，只接受净改进（fail-safe：回退劣化）。
- **A3. 进化循环驱动（EvolutionLoop）**：调度 evaluator → 生成改进候选 → 应用 → 回归验证 → 接受/回滚，记录到 `self_improve/evolution_ledger.jsonl`。
- **A4. CLI/命令面**：`tuan evolve run <task>` / `tuan evolve report`。
- **测试**：`tests/test_evolution_loop.py`（候选改进模拟、劣化回滚、回归门控、账本落盘）。

### 阶段 B —— 持久化多 Agent 编排与故障恢复

**目标**：把会话内协作升级为**跨会话可恢复的编排层**。

- **B1. 群组状态持久化**：`GroupState` 落盘（SQLite/JSON），含任务 DAG、worker 状态、黑板快照、阶段游标。
- **B2. DAG 断点恢复**：`resume_from_checkpoint()` —— 未完成节点重跑、已完成节点复用结果、依赖拓扑排序。
- **B3. 失败重试/回滚**：每节点独立重试（指数退避），节点级失败触发依赖子树回滚（`rollback_subtree`）。
- **B4. 可重放编排层**：`Orchestrator` 暴露 `plan/execute/resume/rollback`，替换/增强 `cmd_dag`。
- **测试**：`tests/test_orchestration_persistence.py`（断点恢复、失败回滚、DAG 重放）。

### 阶段 C —— 人机协同审批增强

**目标**：把审批从"二选一确认"升级为**策略可编程的审批树 + 审计联动**。

- **C1. 审批树（ApprovalTree）**：按风险等级分层策略（默认/白名单/需人工/硬红线），可编程规则。
- **C2. 审计联动**：每次审批决策写入审计事件流（who/what/decision/timestamp），可追溯。
- **C3. 审批策略可配置**：`permissions.approval_policy` 配置节，支持自定义规则 DSL。
- **测试**：`tests/test_approval_tree.py`（分层路由、规则覆盖、审计写入）。

### 阶段 D —— UX 双栈收敛

**目标**：收敛 `tui/` 与 `ui/` 双渲染栈，统一主题，去除冗余。

- **D1. 渲染栈归一**：明确单一入口（`ui/` 为权威渲染层，`tui/` 保留为兼容壳），消除歧义。
- **D2. 主题统一**：`ui/theme.py` 统一 token，TUI 引用同一 token。
- **D3. 去冗余**：清理无引用的 parity/slogans 装饰（**低风险，需确认无引用后删除**）。
- **测试**：`tests/test_theme_consistency.py`（主题 token 单一来源）、渲染冒烟。

---

## 3. 验证策略

每阶段完成后：

1. **单元/集成测试**：新增本阶段测试文件 + 全量回归（`pytest tests/ -q`）。
2. **类型门控**：`mypy tuan_cli`（若环境可用）。
3. **文档同步**：更新 `README.md` / `docs/parity/CAPABILITY-MATRIX.md` / `CHANGELOG.md` 对应条目。
4. **安全不降级**：阶段 A/B/C 涉及安全敏感路径时，跑 `tuan safe bench --quick` 确认无绕过回归。

## 4. 风险与约束

- **不干扰现有未提交工作**：当前 `main` 有 65 文件未提交改动（web/dispatch/version 等，他人进行中）。本路线图在**新分支**上开发，仅触碰路线图涉及的模块；若同一文件既有他人改动又有本路线图需求，以**最小侵入**原则合并，避免覆盖。
- **不过度工程**：只实现上述缺口，不引入新的大型第三方依赖；尽量用现有 stdlib 与内部工具。
- **安全叙事不可弱化**：任何改动不得降低既有安全闸门（硬红线、YOLO 红线、事务账本）语义。
- **环境可执行性**：`.venv` 的 Python 已失效（指向被删的 uv 缓存），需重建或使用系统 Python 3.13/3.11 验证。

---

## 5. 里程碑

| 阶段 | 交付 | 状态 |
|---|---|---|
| A | 反思性自我进化闭环 | ✅ 已完成（evaluator/regression_gate/evolution_loop/cmd_evolve，15 测试通过） |
| B | 持久化多 Agent 编排与故障恢复 | ✅ 已完成（GroupState 持久化/DAG 断点恢复/失败回滚/Orchestrator，12 测试通过） |
| C | 人机协同审批增强 | ✅ 已完成（审批树/审计联动/策略可配置，13 测试通过） |
| D | UX 双栈收敛 | ✅ 已完成（主题 token 单一来源，17 新测试 + 90 渲染回归通过） |

> 本路线图是活文档；每阶段完成后更新对应交付状态。
>
> **实现记录**（2026-11-15）：阶段 A/B/C/D 全部完成并通过回归验证。
> - 阶段 A：`tuan_cli/self_improve/{evaluator,regression_gate,evolution_loop}.py` + `cli/cmd_evolve.py`
> - 阶段 B：`tuan_cli/core/orchestrator.py`
> - 阶段 C：`tuan_cli/ui/approval_policy.py`
> - 阶段 D：`ui/theme.py` 主题 token 单一来源（`BRAND_PRIMARY`/`BRAND_SECONDARY` 唯一定义），`splash/mascot/kimi_modules/tui/common/tui/tui` 全部改 import token；新增 `tests/test_theme_consistency.py` 全库扫描确认无游离品牌色硬编码。
> - 最终回归：193（核心）+ 59（kernel/swarm/self-improve）+ 90（渲染）= **342 passed**。

---

## 6. 最新开源卖点（2026-11-15）：ComfyUI 式多模型自动化视频工作台

> 目标：调研 2026-11-15 最新开源项目卖点（代码制作动画视频等一切新颖卖点），
> 把青小团从"Agent 宿主"推进到"**文本模型调用 → 自动化视频 AI 制作**"的闭环。

### 调研发现（最新开源卖点）

| 项目 | 卖点 | 青小团对齐 |
|---|---|---|
| HyperFrames (43.9k★) | HTML 即视频格式，可 diff/remix，Agent 原生 | `/web` 节点工作台 + tuan-video skill |
| OpenMontage | 首个开源 agentic 视频生产系统，9 阶段流水线 + 12 管线 + 400 skill | `ModelGateway.call_intent` 意图路由流水线 |
| givemotion | 相机跟随/路径运动/shape morph/25+ 转场/kinetic/粒子/音乐卡点 | `code_anim_render` 高级动效原语 |
| Motion AI Kit | 官方 skill + MCP + Performance Doctor | MCP `codeanim_render`/`codeanim_frame` |
| cinecode | three.js/Canvas2D 全帧渲染 + 音频混音 → MP4，无视频模型 | 纯 Python Pillow + ffmpeg 渲染器 |

### 阶段实现（新增 12 阶段，85 项相关测试通过）

| 阶段 | 交付 | 状态 |
|---|---|---|
| 1 | ComfyUI 类数据流节点图执行引擎（`web/dataflow_graph.py`：端口/连线/拓扑调度/缓存/失败传播） | ✅ 已完成（22 测试通过） |
| 2 | 多模型网关（`runtime/gateway.py`：provider 目录 + 意图路由 + json_schema 结构化输出透传） | ✅ 已完成（17 测试通过） |
| 3 | 高级代码动画原语（`code_anim_render.py`：transition/particles/kinetic/beat，frame-stable） | ✅ 已完成（21 测试通过） |
| 4 | MCP 挂动画/视频工具 + 套件化 skill（`codeanim_render`/`codeanim_frame` + `tuan-video-suite` SKILL.md） | ✅ 已完成（2 测试通过） |
| 5 | MCP 暴露多模型网关（`llm_call` 直调 `ModelGateway.generate` + `models_list` 模型目录） | ✅ 已完成（2 测试通过） |
| 6 | /web 工作台接线 DataFlowGraph（`graph_api.py` 存储+套件执行器 + `/api/graph/*` 路由） | ✅ 已完成（10 测试通过） |
| 7 | givemotion 式动效补全（shape_morph/camera/path_motion/hand_drawn 节点） | ✅ 已完成（4 测试通过） |
| 8 | cinecode 式音频混音（`project_json.audio` 经 ffmpeg amix 混入 mp4） | ✅ 已完成（5 测试通过） |
| 9 | OpenMontage 式流水线驱动（`VideoPipeline` 9 阶段 + `video_pipeline_run` MCP） | ✅ 已完成（7 测试通过） |
| 10 | Motion AI Kit 性能分析（`render_video(profile=True)` 逐节点耗时 + `frame_series` 热力图） | ✅ 已完成（8 测试通过） |
| 11 | 多语言叙事 TTS（`narration_tts` 确定性 WAV 合成 + 旁白轨并入 compose 混音 + `narration_tts` MCP） | ✅ 已完成（15 测试通过） |
| 12 | 数据流图三栏工作台前端闭环（`graph_frontend.py` GRAPH_HTML + `/web/graph` + `/api/media` 媒体回放 + `media_rel` 前端拼预览） | ✅ 已完成（11 测试通过） |

> **实现记录**（2026-11-15）：
> - 阶段1：`tuan_cli/web/dataflow_graph.py` —— 纯数据流调度器，节点行为由调用方 `exec_fn` 注入（避免过度耦合）。
> - 阶段2：`tuan_cli/runtime/gateway.py` —— 底层用 legacy 同步 `ModelAdapter`（与项目主调用路径一致）；`models/base.py`/`openai_compat.py` 扩展 `chat(response_format=...)`。
> - 阶段3：`tuan_cli/web/code_anim_render.py` —— 新增 4 节点类型并同步 `_KNOWN_NODE_TYPES` 白名单；全变体 + frame-stable 断言。
> - 阶段4：`ecosystem/mcp_server.py` 挂 2 个工具（非法项目 fail-closed 返回 `isError`）；`resources/skills/builtin/tuan-video-suite/SKILL.md` 内置套件技能。
> - 全链路 **fail-closed**：未知节点类型跳过、结构化输出解析失败抛错、provider 未配置/未知意图拒绝调用、MCP 非法输入返回错误。
