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

# B3 续轮 VI: **按 owner 分桶的显式会话注册表**。上一轮的 default
# provider 是单个变量，后建者覆盖先建者；registry 让「同一进程里多个
# 会话」可以各自按 owner 取回自己的 hooks，而不依赖最后一次覆盖。
#
# 刻意**不做 LRU 静默淘汰**：安全相关绑定被悄悄挤掉会让老会话突然
# 派发到别处（或静默 no-op），比注册失败危险。超出上界直接拒绝。
_SESSIONS: Dict[str, Any] = {}
_SESSION_LOCK = threading.Lock()
_MAX_SESSIONS = 64


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


def _resolve_default() -> Any:
    """解析一次当前 default provider（**调用方负责冻结**）。

    provider 异常一律当「没配 hooks」，绝不掀翻任何主路径。
    """
    prov = _DEFAULT_PROVIDER
    if prov is None:
        return None
    try:
        return prov()
    except Exception:  # noqa: BLE001
        return None


def current_session_hooks() -> Any:
    """返回**此刻**当前会话的 hooks 快照，供长生命周期实例在构造时捕获。

    ``SecurityAlerter`` 的后台通知线程、``RemoteControl`` 的模块级
    ``notify()``、ACP ``ask_user`` 都不该在**派发时刻**再去读全局
    provider —— 实测那样会派到后来覆盖的会话（C4-A/C）。
    """
    return _resolve_default()


def register_session(owner: str, hooks: Any) -> bool:
    """按 owner 注册会话 hooks；超出上界**拒绝**而不是静默淘汰。"""
    if not isinstance(owner, str) or not owner:
        return False
    with _SESSION_LOCK:
        if owner not in _SESSIONS and len(_SESSIONS) >= _MAX_SESSIONS:
            return False
        _SESSIONS[owner] = hooks
        return True


def unregister_session(owner: str) -> bool:
    """如实返回是否真删掉；``hooks=None`` 也是合法注册值，不能靠 pop 值判空。"""
    with _SESSION_LOCK:
        if owner not in _SESSIONS:
            return False
        del _SESSIONS[owner]
        return True


def resolve_session(owner: str) -> Any:
    with _SESSION_LOCK:
        return _SESSIONS.get(owner)


def session_registry_diagnostics() -> Dict[str, Any]:
    with _SESSION_LOCK:
        return {
            "owners": sorted(_SESSIONS),
            "count": len(_SESSIONS),
            "max": _MAX_SESSIONS,
        }


def bind_session_hooks(hooks: Any, *, owner: Optional[str] = None) -> bool:
    """**会话级统一绑定**：注册 registry + 回填 3 个模块级单例。

    B3 续轮 VI：``_global_alerter`` / ``_notify_rc`` 是进程级单例，
    构造时刻可能早于 ``app.py`` 注入 provider（拿到 None）。本函数在
    会话启动时把已存在的实例**显式回填**到本会话 hooks；后续新建的
    实例由 ``current_session_hooks()`` 在构造时捕获。

    回填只改 ``hooks`` 属性，不改单例对象身份 —— 既有
    ``get_alerter()`` / ``_shared_rc()`` 调用方零感知。
    """
    ok = True
    if owner:
        ok = register_session(owner, hooks)
    for _mod, _attr in (("security_alert", "_global_alerter"),
                        ("remote_control", "_notify_rc")):
        try:
            from importlib import import_module
            m = import_module("tuan_cli.core." + _mod)
            inst = getattr(m, _attr, None)
            if inst is not None:
                inst.hooks = hooks
        except Exception:  # noqa: BLE001 - 绑定不得掀翻会话启动
            pass
    return ok


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
        "sessions": session_registry_diagnostics(),
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

    __slots__ = ("_hooks", "_owner")

    def __init__(self, hooks: Any = None, *, owner: Optional[str] = None) -> None:
        """**构造时冻结**本次派发要用的 hooks。

        B3 续轮 VI 实测缺陷（C4-A）：上一版 ``_effective()`` 在**每次
        派发时**才读全局 provider，于是「A 会话构造的 trigger，在 B
        覆盖 provider 之后派发」会静默落到 B（A 零触发、B 代收）。
        现在构造时解析一次并冻结：现场构造的 trigger 仍绑定调用时刻
        的当前会话，而长期持有的 trigger 不会随后续覆盖漂移。

        优先级：显式 ``hooks`` > ``owner`` 查 registry > 冻结 default。
        ``owner`` 查不到时**不回落** default（避免 owner 拼错就静默
        派到别的会话）。
        """
        if hooks is not None:
            self._hooks = hooks
            self._owner = "explicit"
        elif owner is not None:
            self._hooks = resolve_session(owner)
            self._owner = owner
        else:
            self._hooks = _resolve_default()
            self._owner = None

    # ---------------------------------------------------------------- 内部
    def _effective(self) -> Any:
        """返回构造时冻结的 hooks —— 不再读全局 provider。"""
        return self._hooks

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
