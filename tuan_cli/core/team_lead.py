"""专家团编排器 (TeamLead) —— Agent-of-Agents 的正解 (v0.4.2)。

**语义澄清**: 这里的「Agent-of-Agents」指的是 Tuan 调度**本机已安装的外部
CLI Agent** (Claude Code / Codex / Hermes / DeepSeek Harness / Kimi Code)
组成一支**专家开发团**, 而不是进程内的 SubAgent (见 :mod:`core.subagents`,
那是共享内核工具表的轻量并行子代理)。两者互补:

- ``subagents``: 单 Tuan 进程内、共享工具、隔离上下文的并行子任务。
- ``team_lead`` (本模块): 跨进程调度真实的外部 agent 二进制, 每家有自己的
  模型/工具/人格, 组成角色分工的「专家团」。

职责:
1. **发现**: 用 :func:`agents.discovery.discover_agents` 探测本机装了哪几家。
2. **角色分配**: 把开发角色 (架构师/实现者/审查者/测试者) 映射到具体 agent,
   优先用健康的、按角色偏好排序; 缺员时降级到可用 agent 或标记缺位。
3. **并行派发**: 对每个角色构造 :class:`TaskRequest`, 用
   :meth:`AgentAdapter.run` (async generator) 流式收集事件。
4. **结果聚合**: 收敛每角色输出为 :class:`RoleReport`, 汇成
   :class:`TeamReport` (成功/失败/缺位 + 每角色文本)。
5. **失败隔离**: 单个外部 agent 崩溃/超时不拖垮整团。

纯本地: 只 spawn 本机已装 CLI, 不经任何云端中转。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..agents.base import EventType, TaskRequest

log = logging.getLogger(__name__)


# ============================================================ 角色


@dataclass
class DevRole:
    """一个专家团角色 (开发流程中的一环)。"""

    key: str  # 稳定 id, 如 "architect"
    title: str  # 展示名, 如 "架构师"
    instruction: str  # 注入给外部 agent 的角色指令 (system-style preamble)
    preferred: List[str] = field(default_factory=list)  # 偏好 agent id (降序)


def default_roles() -> List[DevRole]:
    """默认专家团角色 (覆盖一个典型开发闭环)。"""
    return [
        DevRole(
            key="architect",
            title="架构师",
            instruction=(
                "你是资深架构师。针对下面的目标, 给出简洁的设计方案: 模块划分、"
                "关键接口、数据流、风险点。不要写完整实现, 聚焦决策与取舍。"
            ),
            preferred=["claude-code", "codex", "gemini"],
        ),
        DevRole(
            key="implementer",
            title="实现者",
            instruction=(
                "你是高级工程师。根据给定方案写出可运行的最小实现 (代码为主, "
                "解释为辅)。遵循现有代码风格, 只改必要文件。"
            ),
            preferred=["codex", "aider", "claude-code", "kimi-code"],
        ),
        DevRole(
            key="reviewer",
            title="审查者",
            instruction=(
                "你是严格的代码审查者。审查给定代码/方案, 列出 bug、安全隐患、"
                "边界情况与改进建议, 按严重度排序。不要重写整个文件。"
            ),
            preferred=["claude-code", "deepseek-harness", "gemini"],
        ),
        DevRole(
            key="tester",
            title="测试者",
            instruction=(
                "你是测试工程师。为给定功能设计并写出关键测试用例 (覆盖正常/"
                "边界/异常), 用 pytest 风格。给出可运行的测试代码。"
            ),
            preferred=["codex", "kimi-code", "qwen-code"],
        ),
    ]


# ============================================================ 报告


@dataclass
class RoleReport:
    """单个角色的执行结果。"""

    role: str
    title: str
    agent_id: str
    status: str  # ok / failed / missing / empty
    text: str = ""
    error: str = ""
    events: int = 0
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "title": self.title,
            "agent_id": self.agent_id,
            "status": self.status,
            "text": self.text,
            "error": self.error,
            "events": self.events,
            "duration_ms": self.duration_ms,
        }


@dataclass
class TeamReport:
    """整支专家团一轮的聚合报告。"""

    goal: str
    total: int
    ok: int
    failed: int
    missing: int
    roles: List[RoleReport] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "total": self.total,
            "ok": self.ok,
            "failed": self.failed,
            "missing": self.missing,
            "duration_ms": self.duration_ms,
            "roles": [r.to_dict() for r in self.roles],
        }


# ============================================================ 编排器


class TeamLead:
    """专家团编排器: 调度本机外部 CLI agent 组成开发团队。

    用法::

        lead = TeamLead()
        infos = await lead.discover()          # 探测已装 agent
        report = await lead.run("实现 X 功能")  # 组团并并行执行
        print(report.to_dict())
    """

    def __init__(
        self,
        roles: Optional[List[DevRole]] = None,
        *,
        cwd: Optional[str] = None,
        timeout_sec: int = 600,
    ) -> None:
        from ..agents.adapters import ADAPTERS

        self._adapters = ADAPTERS
        self.roles = roles or default_roles()
        self.cwd = cwd
        self.timeout_sec = timeout_sec
        self._health: Dict[str, Any] = {}  # agent_id -> AgentInfo

    # ---------------------------------------------------------- 发现

    async def discover(self) -> List[Any]:
        """探测本机已装的外部 agent (并行, 结果缓存供路由)。"""
        from ..agents.discovery import discover_agents

        infos = await discover_agents()
        self._health = {i.id: i for i in infos}
        return infos

    def healthy_agents(self) -> List[str]:
        """当前健康 (PATH 命中) 的 agent id 列表。"""
        return [aid for aid, info in self._health.items() if info.healthy]

    # ---------------------------------------------------------- 角色分配

    def assign_role(self, role: DevRole) -> Optional[str]:
        """为一个角色挑一个执行 agent。

        优先级: 角色显式 preferred (且健康) > 其它健康 agent > None (缺位)。
        """
        healthy = set(self.healthy_agents())
        # 先按角色偏好
        for aid in role.preferred:
            if aid in healthy:
                return aid
        # 降级到任意健康 agent (保证不缺位, 尽量团内闭环)
        for aid in self.healthy_agents():
            return aid
        return None

    def plan(self) -> Dict[str, Optional[str]]:
        """给出 角色 -> agent 的分配计划 (缺位为 None)。"""
        return {r.key: self.assign_role(r) for r in self.roles}

    # ---------------------------------------------------------- 派发

    async def run(
        self, goal: str, *, extra_context: str = "", roles: Optional[List[str]] = None,
    ) -> TeamReport:
        """组团并并行执行。goal 是开发目标; extra_context 追加上下文。"""
        started = time.time()
        if not self._health:
            await self.discover()
        selected = [r for r in self.roles if roles is None or r.key in roles]
        if not selected:
            raise ValueError("没有可执行的角色")

        prompt_suffix = f"\n\n[目标] {goal}"
        if extra_context:
            prompt_suffix += f"\n\n[上下文] {extra_context}"

        tasks = [self._run_role(r, prompt_suffix) for r in selected]
        role_reports = await asyncio.gather(*tasks, return_exceptions=True)

        reports: List[RoleReport] = []
        for r, res in zip(selected, role_reports):
            if isinstance(res, RoleReport):
                reports.append(res)
            else:  # gather 捕获的异常
                reports.append(RoleReport(
                    role=r.key, title=r.title, agent_id="-",
                    status="failed", error=f"{type(res).__name__}: {res}",
                ))

        ok = sum(1 for r in reports if r.status == "ok")
        failed = sum(1 for r in reports if r.status == "failed")
        missing = sum(1 for r in reports if r.status == "missing")
        return TeamReport(
            goal=goal, total=len(reports), ok=ok, failed=failed, missing=missing,
            roles=reports, duration_ms=int((time.time() - started) * 1000),
        )

    async def _run_role(self, role: DevRole, prompt_suffix: str) -> RoleReport:
        """执行单个角色 (失败/缺位/空输出都收敛为对应 status)。"""
        agent_id = self.assign_role(role)
        if agent_id is None:
            return RoleReport(
                role=role.key, title=role.title, agent_id="-",
                status="missing", error="本机无可用外部 agent (PATH 未命中)",
            )
        adapter = self._adapters.get(agent_id)
        if adapter is None:
            return RoleReport(
                role=role.key, title=role.title, agent_id=agent_id,
                status="failed", error=f"适配器未注册: {agent_id}",
            )
        task = TaskRequest(
            id=f"tl-{role.key}-{int(time.time())}",
            prompt=f"{role.instruction}{prompt_suffix}",
            agent=agent_id, mode="collaboration", cwd=self.cwd,
            timeout_sec=self.timeout_sec,
        )
        started = time.time()
        chunks: List[str] = []
        err: List[str] = []
        n_events = 0
        status = "ok"
        error_msg = ""
        try:
            async def _collect() -> None:
                nonlocal status, error_msg, n_events
                async for ev in adapter.run(task):
                    n_events += 1
                    if ev.kind == EventType.TEXT:
                        chunks.append(str(ev.data.get("text", "")))
                    elif ev.kind == EventType.STDERR:
                        err.append(str(ev.data.get("text", "")))
                    elif ev.kind == EventType.ERROR:
                        error_msg = str(ev.data.get("message", ""))
                        status = "failed"
                    elif ev.kind == EventType.DONE:
                        d = ev.data
                        if d.get("status") in {"error", "timeout", "cancelled"}:
                            status = "failed"
                            error_msg = error_msg or f"done:{d.get('status')}"

            await asyncio.wait_for(_collect(), timeout=self.timeout_sec)
        except asyncio.TimeoutError:
            status = "failed"
            error_msg = error_msg or f"角色超时 ({self.timeout_sec}s)"
        except Exception as exc:  # noqa: BLE001
            status = "failed"
            error_msg = error_msg or f"{type(exc).__name__}: {exc}"

        text = "".join(chunks).strip()
        if status == "ok" and not text:
            # 子进程跑了但无 stdout: 视为空结果 (仍算失败, 避免「假成功」)
            status = "empty"
            error_msg = "外部 agent 无文本输出" + (f" (stderr: {''.join(err)[:200]})" if err else "")
        return RoleReport(
            role=role.key, title=role.title, agent_id=agent_id,
            status=status, text=text, error=error_msg,
            events=n_events, duration_ms=int((time.time() - started) * 1000),
        )


# ============================================================ 工厂


def make_team_lead(
    roles: Optional[List[DevRole]] = None, *, cwd: Optional[str] = None,
    timeout_sec: int = 600,
) -> TeamLead:
    """构造一个 TeamLead (roles 默认为标准开发闭环)。"""
    return TeamLead(roles or default_roles(), cwd=cwd, timeout_sec=timeout_sec)


class AuditedTeamLead:
    """带团组审计的专家团编排器 —— 把每轮派发/结果写入 ``team_audit.jsonl``。

    团组安全模型 (team_group) 要求关键操作可追溯。本包装器让「调用外部专家团」
    也进入同一审计链: 派发前记 ``expert_dispatch`` (goal + 各角色选中的 agent),
    聚合后记 ``expert_report`` (ok/failed/missing + 耗时)。store 不可用时优雅
    降级为纯 TeamLead (不写审计), 不阻断开发流程。
    """

    def __init__(self, lead: TeamLead, store: Optional[Any] = None) -> None:
        self.lead = lead
        self._store = store

    async def discover(self) -> List[Any]:
        return await self.lead.discover()

    def healthy_agents(self) -> List[str]:
        return self.lead.healthy_agents()

    def plan(self) -> Dict[str, Optional[str]]:
        return self.lead.plan()

    async def run(
        self, goal: str, *, extra_context: str = "", roles: Optional[List[str]] = None,
        actor: str = "",
    ) -> TeamReport:
        plan = self.lead.plan()
        self._audit("expert_dispatch", actor, {
            "goal": goal, "plan": {k: v for k, v in plan.items()
                                    if roles is None or k in (roles or plan.keys())},
        })
        report = await self.lead.run(goal, extra_context=extra_context, roles=roles)
        self._audit("expert_report", actor, {
            "goal": goal, "total": report.total, "ok": report.ok,
            "failed": report.failed, "missing": report.missing,
            "duration_ms": report.duration_ms,
            "roles": [{r.role: r.agent_id} for r in report.roles],
        })
        return report

    def _audit(self, action: str, actor: str, detail: Dict[str, Any]) -> None:
        if self._store is None:
            return
        try:
            self._store._audit(action, actor=actor, detail=detail)  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            log.debug("专家团审计写入失败 (不阻断): %s", exc)


def make_audited_team_lead(
    store: Optional[Any] = None,
    roles: Optional[List[DevRole]] = None, *, cwd: Optional[str] = None,
    timeout_sec: int = 600,
) -> AuditedTeamLead:
    """构造带审计的专家团 (store 可为团组 store 或 None)。"""
    return AuditedTeamLead(
        make_team_lead(roles, cwd=cwd, timeout_sec=timeout_sec), store=store,
    )
