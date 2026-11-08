"""B3 续轮：扩展事件的**统一生产触发层**。

**为什么需要它（实测，不是推测）**

上一轮把 7 个扩展事件加进了 ``HOOK_EVENTS`` 并建了 ``run_decision``
裁决出口，但实测把 5 个事件各配一条 hook 之后，跑真实操作
（``Config.set_user`` / ``WorktreeLayer.create`` / ``_ask_user_handler`` /
``remote_control.notify``）**触发次数为 0**，全仓源码扫描
``run_notify("ConfigChange"...`` 等 5 个派发点也是 **0 命中**。
也就是说：配置能加载、引擎能裁决，但**没有任何生产代码调用它们** ——
用户以为装了拦截器，实际上什么都不会发生。

本模块把 5 个事件收敛成单一出口，各子系统只需一行。刻意不做的事：

- **不引入新的全局可变状态**：``set_default_hooks_provider()`` 注入的是
  一个**只读取值函数**（app.py 在启动时注入 ``lambda: agent.ctx.hooks``），
  不是把 HookManager 复制进各模块。provider 抛异常一律当「没配 hooks」。
- **不掀翻主路径**：通知类事件任何异常都吞掉；决策类事件只有在
  「用户显式配了 hook、但调用本身炸了」时才 **fail-closed 返回 block**，
  与 B1 的故障闭合一致。没配 hooks 时是严格 no-op（既有行为零变化）。
- **不让 hook 代答/覆盖用户**：``elicitation`` 的 block 表示「取消这次
  提问」，``elicitation_result`` 的 block 表示「作废本次回答」；二者都
  **没有**把 hook 的 stdout 当成用户答案的通道。CC 允许 Elicitation hook
  程序化代答，Tuan 刻意不等价 —— 那等于让模型自己答自己问。

事件语义映射（如实标注差异）：

======================  ==============================  =====================
事件                    触发点                          与 CC 的差异
======================  ==============================  =====================
ConfigChange            ``Config.set_user`` /           带 source + key；
                        ``delete_user`` /               reload 也触发
                        ``ManagedSettings.reload``
WorktreeCreate          ``WorktreeLayer.create`` /      **决策类**：block
                        ``create_agent_worktree``       → 拒绝创建
Elicitation             ``_ask_user_handler`` /        **决策类**：block
                        ACP ``ask_user``                → 取消提问；不代答
ElicitationResult       拿到真实用户答案之后            **决策类**：block
                                                       → 作废；不覆盖
Notification            ``remote_control.notify`` /    纯通知
                        ``SecurityAlerter`` 后台线程
======================  ==============================  =====================

``Notification`` / ``ConfigChange`` 走 ``run_notify``（stdout 忽略）；
``WorktreeCreate`` / ``Elicitation`` / ``ElicitationResult`` 走
``run_decision``（解析 stdout 裁决）—— 这正是上一轮 R2 修的那个坑：
决策类走通知通道等于把 hook 输出吞掉。
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional

from .manager import HookDecision

_DEFAULT_PROVIDER: Optional[Callable[[], Any]] = None

# B3 续轮 V: **重入守卫**。thread-local 而不是全局 set —— 不同线程并发
# 派发同一事件是合法的（SecurityAlerter 后台线程 + 主线程），不该互相抑制；
# 只有「同一线程、同一事件、hook 回调里又触发自己」才是递归。
_REENTRY_LOCAL = threading.local()
_STATS_LOCK = threading.Lock()
_REENTRY_STATS: Dict[str, int] = {
    "notify_suppressed": 0, "decision_suppressed": 0}

# B3 续轮 V: provider 是**进程级单会话假设**。实测两次
# set_default_hooks_provider(A) / (B) 之后，先用 A 构造的 HookTrigger
# 会拿到 B（A 零触发、B 收到 A 的事件）。这里不假装支持多会话，而是把
# 覆盖变成可诊断的：generation / owner / overrides 全部可查。
_PROVIDER_OWNER: Optional[str] = None
_PROVIDER_GENERATION: int = 0
_PROVIDER_OVERRIDES: int = 0


def set_default_hooks_provider(
    fn: Optional[Callable[[], Any]], *, owner: Optional[str] = None,
) -> None:
    """注入「当前会话的 HookManager 取值函数」（app.py 启动时调用）。

    ``None`` 表示清除。刻意传函数而不是对象：HookManager 在 app.py 里
    比多数子系统构造得晚，传对象会拿到 None 或过期实例。

    **B3 续轮 V 的边界**：这是**进程级单会话**默认出口。多会话并存时
    后建者覆盖先建者（实测串台），本函数不阻止覆盖，只把覆盖记进
    ``provider_diagnostics()`` 让它可见。需要严格隔离的调用方必须
    **显式传 hooks**：app.py 已把 ``config._hooks`` 回填为本会话的值，
    ``/worktree`` 显式传 ``agent.ctx.hooks``，``ask_user`` 用
    ``ctx.hooks``。只有模块级函数（``remote_control.notify``、
    ``SecurityAlerter`` 后台线程）仍依赖这个全局 fallback。
    """
    global _DEFAULT_PROVIDER, _PROVIDER_OWNER, _PROVIDER_GENERATION
    global _PROVIDER_OVERRIDES
    if (_DEFAULT_PROVIDER is not None and fn is not None
            and owner != _PROVIDER_OWNER):
        _PROVIDER_OVERRIDES += 1
    _DEFAULT_PROVIDER = fn
    _PROVIDER_OWNER = owner
    _PROVIDER_GENERATION += 1


def get_default_hooks_provider() -> Optional[Callable[[], Any]]:
    """只读访问，供测试/诊断确认注入状态。"""
    return _DEFAULT_PROVIDER


def provider_diagnostics() -> Dict[str, Any]:
    """只读诊断：让「全局 provider 被覆盖」不再静默。

    纯信息项，**不参与任何裁决**（与前面几轮的 evicted_total /
    unresolved_misses 同一处理）。``overrides >= 1`` 说明存在多会话
    覆盖风险，应检查调用方是否该显式传 hooks。
    """
    with _STATS_LOCK:
        reentry = dict(_REENTRY_STATS)
    return {
        "owner": _PROVIDER_OWNER,
        "generation": _PROVIDER_GENERATION,
        "overrides": _PROVIDER_OVERRIDES,
        "installed": _DEFAULT_PROVIDER is not None,
        "reentry": reentry,
    }


def _in_flight_events() -> set:
    s = getattr(_REENTRY_LOCAL, "events", None)
    if s is None:
        s = set()
        _REENTRY_LOCAL.events = s
    return s


def _bump_reentry(kind: str) -> None:
    with _STATS_LOCK:
        _REENTRY_STATS[kind] += 1


class HookTrigger:
    """5 个扩展事件的最小派发器。

    ``hooks`` 显式传入时优先；为 ``None`` 时回落到 default provider。
    两种都没取到 → 全部方法严格 no-op，既有行为零变化。
    """

    __slots__ = ("_hooks",)

    def __init__(self, hooks: Any = None) -> None:
        self._hooks = hooks

    # ---------------------------------------------------------------- 内部
    def _effective(self) -> Any:
        if self._hooks is not None:
            return self._hooks
        prov = _DEFAULT_PROVIDER
        if prov is None:
            return None
        try:
            return prov()
        except Exception:  # noqa: BLE001 - provider 异常不得掀翻任何主路径
            return None

    @staticmethod
    def _no_decision() -> HookDecision:
        return HookDecision()

    @staticmethod
    def _failed_closed(exc: Exception) -> HookDecision:
        return HookDecision(
            block=True,
            reason=f"扩展事件 hook 通道异常 (fail-closed): "
                   f"{type(exc).__name__}",
            failure_kind="trigger_error",
        )

    def _notify(self, event: str, payload: Dict[str, Any]) -> bool:
        """通知类：异常一律吞掉，返回是否真的派发了。

        B3 续轮 V: **同线程同事件重入直接跳过**。实测一个 in-process
        hook 在 ``run_notify`` 里再调 ``Config.set_user`` 会递归 247 层，
        而 ``dump_yaml`` 把 ``RecursionError`` 也吞掉 —— 表现为「配置写入
        失败」却仍在每一层派发 ConfigChange，既不报错也不停止。
        跨进程 command hook **不需要**守卫：子进程不继承父进程的
        thread-local，天然不会形成这条递归链（如实标注，不夸大覆盖面）。
        """
        hooks = self._effective()
        if hooks is None or not getattr(hooks, "enabled", False):
            return False
        run = getattr(hooks, "run_notify", None)
        if run is None:
            return False
        inflight = _in_flight_events()
        if event in inflight:
            _bump_reentry("notify_suppressed")
            return False
        inflight.add(event)
        try:
            try:
                run(event, payload)
                return True
            except Exception:  # noqa: BLE001
                return False
        finally:
            inflight.discard(event)

    def _decide(self, event: str, payload: Dict[str, Any],
                tool_name: str = "") -> HookDecision:
        """决策类：无 hooks → no-op；hook 通道异常 → fail-closed。

        B3 续轮 V: 决策类重入**不能返回空决策放行**（那会把递归变成
        安全绕过），统一 fail-closed 并标 ``reentry_suppressed``。
        """
        hooks = self._effective()
        if hooks is None or not getattr(hooks, "enabled", False):
            return self._no_decision()
        inflight = _in_flight_events()
        if event in inflight:
            _bump_reentry("decision_suppressed")
            return HookDecision(
                block=True,
                reason="同线程同事件重入已抑制 (fail-closed)",
                failure_kind="reentry_suppressed",
            )
        run = getattr(hooks, "run_decision", None)
        if run is None:
            # 配了 hooks 却是老式 mock（没有 run_decision）→ 不能静默放行
            return self._failed_closed(
                RuntimeError("HookManager 缺少 run_decision 裁决出口"))
        inflight.add(event)
        try:
            try:
                d = run(event, tool_name=tool_name, payload=payload)
            except Exception as exc:  # noqa: BLE001
                return self._failed_closed(exc)
            if d is None:
                return self._failed_closed(
                    RuntimeError("run_decision 返回 None（契约违约）"))
            return d
        finally:
            inflight.discard(event)

    # ---------------------------------------------------------------- 公开
    def config_change(self, *, source: str, key: str = "",
                      origin: str = "") -> bool:
        """配置写入 / 重载成功后触发 ``ConfigChange``（通知类）。"""
        return self._notify("ConfigChange", {
            "source": source, "key": key, "origin": origin,
        })

    def worktree_create(self, *, name: str, path: str, branch: str,
                        source: str = "", ephemeral: bool = False) -> HookDecision:
        """真正执行 ``git worktree add`` **之前**触发（决策类，可拒绝）。"""
        return self._decide(
            "WorktreeCreate",
            {"name": name, "path": path, "branch": branch,
             "source": source, "ephemeral": ephemeral},
            tool_name="worktree_create",
        )

    def elicitation(self, *, question: str, options: Optional[List[str]] = None,
                    server: str = "", source: str = "") -> HookDecision:
        """向用户提问之前触发（决策类，block = 取消提问，不代答）。"""
        return self._decide(
            "Elicitation",
            {"question": question, "options": list(options or []),
             "mcp_server_name": server, "source": source},
            tool_name=server or "ask_user",
        )

    def elicitation_result(self, *, answer: str, action: str = "accept",
                           server: str = "", source: str = "",
                           question: str = "") -> HookDecision:
        """拿到**真实**用户答案之后触发（决策类，block = 作废本次回答）。

        刻意不把 hook 输出作为新答案 —— CC 允许覆盖用户响应，Tuan 不做。
        """
        return self._decide(
            "ElicitationResult",
            {"action": action, "answer": answer, "question": question,
             "mcp_server_name": server, "source": source},
            tool_name=server or "ask_user",
        )

    def notification(self, *, title: str, body: str = "",
                     kind: str = "info", severity: str = "info",
                     source: str = "") -> bool:
        """系统通知触发 ``Notification``（通知类）。"""
        return self._notify("Notification", {
            "title": title, "message": body, "kind": kind,
            "severity": severity, "source": source,
        })
