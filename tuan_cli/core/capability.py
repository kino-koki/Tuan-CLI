"""AgentCapability 统一门面 —— 「一个 Agent 体验所有 Agent 能力」(v0.4.2)。

Tuan-CLI 内部已有 7 套注册机制 (extension_registry / loop_registry / kernel
plugin / skills / agents_registry / modes / hooks),但它们彼此独立、用户不可见。
:class:`AgentCapability` + :class:`CapabilityRegistry` 是一个**统一门面
(facade)**:把散落的能力收口到一个可枚举、可启停、可组合的用户可见清单,
把「融合多家 Agent 核心理念」从口号变成运行时可观察的能力矩阵。

对齐的各家理念 (每条对应一个内置 capability, 落点标注来源):
- **spec-driven + spec hooks** (Kiro): ``spec_driven``
- **agent steering** (Windsurf): ``agent_steering``
- **自主编码循环** (Codebuff): ``autonomous_coding``
- **codebase indexing** (Cursor): ``codebase_indexing``
- **checkpoints/rewind** (Cursor/Claude): ``checkpoints``
- **background agents** (Claude Code): ``background_agents``
- **parallel subagents** (Claude Code): ``parallel_subagents``
- **planner/reviewer swarm** (herdr): ``swarm_planner``
- **multi-agent orchestration** (LangGraph/A2A): ``collaboration_protocol``
- **soul/persona** (Character/Kiro): ``persona``
- **long-term memory** (MemGPT/Claude): ``memory``
- **auto model routing**: ``model_routing``
- **hook 系统** (Claude Code): ``hooks``
- **MCP 生态**: ``mcp``
- **inline edit / 精准改动** (Kimi Code / kimicode): ``inline_edit``
- **多模态识图/语音输入** (doubao-cli / 豆包): ``multimodal_input``

安全不变量: capability 仅是「门面 + 开关」, 本身不绕过任何安全层;
``enabled`` 默认跟随模式 (MODE_LEVELS), 危险能力 (autonomous_coding 等)
在受限模式下自动关闭。所有能力启停只改本机状态, 无云端。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# 受限模式下默认关闭的能力 (自主/高副作用)
_RESTRICTED_CAPABILITIES = {"autonomous_coding", "background_agents", "swarm_planner"}


@dataclass
class AgentCapability:
    """一个 Agent 能力 (统一门面单元)。

    name: 稳定 id (如 "spec_driven")
    source: 理念来源标注 (如 "Kiro") —— 让「融合谁」可观察
    enabled: 是否启用
    origin: 底层落点模块 (供 doctor/诊断, 如 "codedev.spec_driven")
    handler: 可选的运行时入口 (懒调用), 能力本身可无 handler (纯声明/组合)
    """

    name: str
    description: str
    source: str = ""
    origin: str = ""
    enabled: bool = True
    restricted: bool = False  # 受限模式下强制关闭
    handler: Optional[Callable[[Dict[str, Any]], Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, hide_handler: bool = True) -> Dict[str, Any]:
        out = {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "origin": self.origin,
            "enabled": self.enabled,
            "restricted": self.restricted,
            "metadata": dict(self.metadata),
        }
        if not hide_handler:
            out["has_handler"] = self.handler is not None
        return out


class CapabilityRegistry:
    """能力注册表 (线程安全, 纯本机状态)。

    - ``register``: 登记一个能力 (重复名覆盖, 便于热更新)
    - ``enable/disable``: 切换开关 (受限能力不可在受限模式强制开启)
    - ``set_mode``: 按模式级别批量装配默认能力集
    - ``list``: 导出用户可见能力矩阵 (不含 handler 引用)
    - ``invoke``: 调用某能力的 handler (未启用/无 handler 即失败)
    """

    def __init__(self) -> None:
        self._caps: Dict[str, AgentCapability] = {}
        self._lock = threading.RLock()
        self._mode = "standard"

    # ---------------------------------------------------------- 注册

    def register(self, cap: AgentCapability) -> None:
        with self._lock:
            self._caps[cap.name] = cap

    def register_many(self, caps: List[AgentCapability]) -> None:
        for c in caps:
            self.register(c)

    def unregister(self, name: str) -> bool:
        with self._lock:
            return self._caps.pop(name, None) is not None

    # ---------------------------------------------------------- 查询

    def get(self, name: str) -> Optional[AgentCapability]:
        with self._lock:
            return self._caps.get(name)

    def is_enabled(self, name: str) -> bool:
        cap = self.get(name)
        return bool(cap and cap.enabled)

    def count(self) -> int:
        with self._lock:
            return len(self._caps)

    def count_enabled(self) -> int:
        with self._lock:
            return sum(1 for c in self._caps.values() if c.enabled)

    def list(self) -> List[Dict[str, Any]]:
        """导出能力矩阵 (用户可见, 不含 handler 引用)。"""
        with self._lock:
            return [c.to_dict() for c in self._caps.values()]

    def by_source(self) -> Dict[str, List[str]]:
        """按理念来源分组 (展示「融合了哪些 Agent」)。"""
        with self._lock:
            out: Dict[str, List[str]] = {}
            for c in self._caps.values():
                out.setdefault(c.source or "tuan", []).append(c.name)
            return out

    # ---------------------------------------------------------- 启停/模式

    def iter_callables(self) -> List[Tuple[str, Callable[[Dict[str, Any]], Any]]]:
        """返回有 handler 的能力列表 [(name, handler), ...]，供协调器安全接入。

        快照返回 (不持锁迭代)，只暴露可调用入口，不泄漏内部字典结构。
        """
        with self._lock:
            return [(cap.name, cap.handler) for cap in self._caps.values()
                    if callable(cap.handler)]

    def enable(self, name: str, *, force: bool = False) -> bool:
        with self._lock:
            cap = self._caps.get(name)
            if cap is None:
                raise KeyError(f"未知能力: {name}")
            if cap.restricted and not force and self._mode in {"restricted", "safe"}:
                log.info("受限能力 %s 在 %s 模式下保持关闭", name, self._mode)
                return False
            cap.enabled = True
            return True

    def disable(self, name: str) -> bool:
        with self._lock:
            cap = self._caps.get(name)
            if cap is None:
                raise KeyError(f"未知能力: {name}")
            cap.enabled = False
            return True

    def set_mode(self, mode: str) -> Dict[str, Any]:
        """按模式装配默认能力集。受限/安全模式关闭高副作用能力。"""
        with self._lock:
            self._mode = mode
            changed = 0
            for cap in self._caps.values():
                if mode in {"restricted", "safe"} and (
                    cap.restricted or cap.name in _RESTRICTED_CAPABILITIES
                ):
                    if cap.enabled:
                        cap.enabled = False
                        changed += 1
                elif mode in {"standard", "full", "advanced"}:
                    # 非受限能力在标准及以上恢复默认启用
                    if not cap.restricted and not cap.enabled:
                        cap.enabled = True
                        changed += 1
            return {"mode": mode, "changed": changed,
                    "enabled": self.count_enabled(), "total": self.count()}

    @property
    def mode(self) -> str:
        return self._mode

    # ---------------------------------------------------------- 调用

    def invoke(self, name: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        """调用某能力的统一入口 (fail-closed)。

        - 未启用 → RuntimeError
        - 有显式 handler → 调用它
        - 无 handler 但有内置路由 (team_* 等) → 走对应模块
        - 两者皆无 → 抛带**可执行指引**的错误 (告诉调用方走哪个模块/CLI)
        """
        cap = self.get(name)
        if cap is None:
            raise KeyError(f"未知能力: {name}")
        if not cap.enabled:
            raise RuntimeError(f"能力未启用: {name}")
        if cap.handler is not None:
            return cap.handler(dict(payload or {}))
        # 内置路由: 把「声明型」能力映射到真实运行时
        if name in _CAPABILITY_ROUTES:
            return _CAPABILITY_ROUTES[name](dict(payload or {}))
        raise RuntimeError(
            f"能力 {name} 无运行时入口; 请通过其落点模块或 CLI 调用 "
            f"(落点: {cap.origin or '未知'})"
        )


# ============================================================ 内置运行时路由

# 把「声明型」能力映射到真实运行时入口, 让 invoke() 真正可用。
# 每个路由: payload -> 结果; 缺少必要参数即抛带指引的 KeyError。
_CAPABILITY_ROUTES: Dict[str, Callable[[Dict[str, Any]], Any]] = {}


def _register_route(name: str) -> Callable:
    """装饰器: 注册一个能力的内置运行时路由。"""
    def deco(fn: Callable[[Dict[str, Any]], Any]) -> Callable[[Dict[str, Any]], Any]:
        _CAPABILITY_ROUTES[name] = fn
        return fn
    return deco


def _require(payload: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    """校验 payload 必填键, 缺失即抛带指引的 KeyError。"""
    missing = [k for k in keys if k not in payload or payload[k] in (None, "")]
    if missing:
        raise KeyError(f"能力调用缺少必要参数: {', '.join(missing)}")
    return payload


@_register_route("team_group")
def _route_team_group(payload: Dict[str, Any]) -> Any:
    """团组状态查询 (只读, 不需要敏感参数)。"""
    from .team_group import load_team_group
    from ..config import home_dir
    ws = str(payload.get("workspace") or home_dir())
    store = load_team_group(ws)
    return {"group": store.export_public()}


@_register_route("team_security")
def _route_team_security(payload: Dict[str, Any]) -> Any:
    """团组安全状态: 当前轮换状态 + 用量策略查询。"""
    from .team_group import load_team_group
    from .team_security import load_team_security
    from ..config import home_dir
    ws = str(payload.get("workspace") or home_dir())
    store = load_team_group(ws)
    if store.group is None:
        raise RuntimeError("团组未创建, 无安全状态可查")
    sec = load_team_security(store)
    gid = payload.get("grant_id")
    out: Dict[str, Any] = {"group": store.export_public()}
    if gid:
        out["usage"] = sec.usage_of(gid)
    return out


@_register_route("team_agents")
def _route_team_agents(payload: Dict[str, Any]) -> Any:
    """团组协调器: 派发 worker 计划 (goal + workers)。"""
    from .team_group import load_team_group
    from .team_security import load_team_security
    from .team_agents import TeamAgentCoordinator, WorkerSpec
    from ..config import home_dir
    ws = str(payload.get("workspace") or home_dir())
    store = load_team_group(ws)
    if store.group is None:
        raise RuntimeError("团组未创建")
    sec = load_team_security(store)
    workers = [
        WorkerSpec(worker_id=w["worker_id"], capability=w["capability"],
                   prompt=w.get("prompt", ""), provider=w.get("provider"),
                   model=w.get("model"), member=w.get("member"),
                   nonce=w.get("nonce"), meta=w.get("meta") or {})
        for w in payload.get("workers", [])
    ]
    if not workers:
        raise KeyError("team_agents 需要 workers 列表")
    coord = TeamAgentCoordinator(sec)
    return coord.dispatch(payload.get("goal", ""), workers,
                          actor=payload.get("actor", "")).to_dict()


@_register_route("external_expert_team")
def _route_external_expert_team(payload: Dict[str, Any]) -> Any:
    """专家团: 调度本机外部 CLI agent 组成开发团。

    invoke() 是同步门面, 故在此用 asyncio.run 跑完 TeamLead.run 协程,
    返回 TeamReport (非协程), 调用方无需 await。
    """
    import asyncio

    from .team_lead import make_audited_team_lead
    from .team_group import load_team_group
    from ..config import home_dir
    ws = str(payload.get("workspace") or home_dir())
    store = None
    try:
        s = load_team_group(ws)
        if s.group is not None:
            store = s
    except Exception:  # noqa: BLE001
        store = None
    lead = make_audited_team_lead(store, cwd=ws, timeout_sec=payload.get("timeout", 600))
    goal = payload.get("goal")
    if not goal:
        raise KeyError("external_expert_team 需要 goal")

    async def _go() -> Any:
        return await lead.run(goal, extra_context=payload.get("context", ""),
                              roles=payload.get("roles"), actor=payload.get("actor", ""))

    # 若调用方已有运行中的 loop (如 Web 服务器线程), 在独立线程新建 loop 跑完,
    # 避免 asyncio.run 在运行 loop 内抛 "cannot be called from a running event loop"。
    try:
        asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            report = ex.submit(lambda: asyncio.run(_go())).result()
    except RuntimeError:
        report = asyncio.run(_go())
    return report.to_dict()


def builtin_capabilities() -> List[AgentCapability]:
    """内置能力清单 (理念来源标注 + 落点)。

    薄壳门面: 不重复实现, 只是把已有模块收口到统一清单。
    handler 默认 None (能力作为「声明 + 开关」; 具体调用走各自模块)。
    """
    caps = [
        ("spec_driven", "规格驱动开发: 需求/设计/任务三件套工件", "Kiro",
         "codedev.spec_driven", False),
        ("agent_steering", "运行时转向: 循环中途中断并注入新指令", "Windsurf",
         "core.agent_hooks", False),
        ("autonomous_coding", "自主编码循环 (规划→执行→验证闭环)", "Codebuff",
         "core.background+devloop+verify_loop", True),
        ("codebase_indexing", "代码库索引与检索", "Cursor",
         "context.indexer+fast_index", False),
        ("checkpoints", "检查点与回滚 (rewind)", "Cursor/Claude",
         "core.checkpoint_store+rewind", False),
        ("background_agents", "后台代理 (长任务不阻塞)", "Claude Code",
         "core.background", True),
        ("parallel_subagents", "并行子代理池", "Claude Code",
         "core.subagents", False),
        ("swarm_planner", "规划/验收/执行角色分工 (herdr 式)", "herdr",
         "core.swarm", True),
        ("collaboration_protocol", "多智能体协作协议 (结构化消息/依赖/冲突)", "LangGraph/A2A",
         "core.collaboration_protocol", False),
        ("persona", "灵魂/人格文件 (SOUL)", "Character/Kiro",
         "resources.SOUL+core.personality", False),
        ("memory", "长期记忆", "MemGPT/Claude",
         "memory.store+memory_notes", False),
        ("model_routing", "按任务难度自动路由模型", "Tuan",
         "core.model_router+auto_route", False),
        ("hooks", "Hook 系统 (工具/会话生命周期)", "Claude Code",
         "hooks.manager", False),
        ("mcp", "MCP 生态互通", "Anthropic MCP",
         "ecosystem.mcp_server", False),
        ("team_group", "团组: 本地团队 + 供应商/模型授权互通", "Tuan v0.4.2",
         "core.team_group", False),
        ("team_security", "团组安全强化: 密钥轮换/防重放/challenge/用量策略", "Tuan v0.4.2",
         "core.team_security", False),
        ("team_agents", "Agent-of-Agents 团组协调器: 并行派发+授权前置+结果聚合", "Tuan v0.4.2",
         "core.team_agents", False),
        ("external_expert_team", "专家团: 调度本机外部 CLI agent (claude/codex/kimi) 组成开发团", "Tuan v0.4.2",
         "core.team_lead", False),
        ("inline_edit", "精准内联编辑 (光标处最小改动, kimicode 式)", "Kimi Code/kimicode",
         "tools.edit+cursor_patch", False),
        ("multimodal_input", "多模态识图/语音输入 (doubao-cli 式)", "doubao-cli/豆包",
         "tools.image+speech_input", False),
    ]
    out: List[AgentCapability] = []
    for name, desc, source, origin, restricted in caps:
        out.append(AgentCapability(
            name=name, description=desc, source=source, origin=origin,
            enabled=True, restricted=restricted,
        ))
    return out


def make_capability_registry(mode: str = "standard") -> CapabilityRegistry:
    """构造一个装好内置能力的注册表并按模式装配。"""
    reg = CapabilityRegistry()
    reg.register_many(builtin_capabilities())
    reg.set_mode(mode)
    return reg
