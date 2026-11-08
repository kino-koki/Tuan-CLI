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

from typing import Any, Callable, Dict, List, Optional

from .manager import HookDecision

_DEFAULT_PROVIDER: Optional[Callable[[], Any]] = None


def set_default_hooks_provider(fn: Optional[Callable[[], Any]]) -> None:
    """注入「当前会话的 HookManager 取值函数」（app.py 启动时调用）。

    ``None`` 表示清除。刻意传函数而不是对象：HookManager 在 app.py 里
    比多数子系统构造得晚，传对象会拿到 None 或过期实例。
    """
    global _DEFAULT_PROVIDER
    _DEFAULT_PROVIDER = fn


def get_default_hooks_provider() -> Optional[Callable[[], Any]]:
    """只读访问，供测试/诊断确认注入状态。"""
    return _DEFAULT_PROVIDER


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
        """通知类：异常一律吞掉，返回是否真的派发了。"""
        hooks = self._effective()
        if hooks is None or not getattr(hooks, "enabled", False):
            return False
        run = getattr(hooks, "run_notify", None)
        if run is None:
            return False
        try:
            run(event, payload)
            return True
        except Exception:  # noqa: BLE001
            return False

    def _decide(self, event: str, payload: Dict[str, Any],
                tool_name: str = "") -> HookDecision:
        """决策类：无 hooks → no-op；hook 通道异常 → fail-closed。"""
        hooks = self._effective()
        if hooks is None or not getattr(hooks, "enabled", False):
            return self._no_decision()
        run = getattr(hooks, "run_decision", None)
        if run is None:
            # 配了 hooks 却是老式 mock（没有 run_decision）→ 不能静默放行
            return self._failed_closed(
                RuntimeError("HookManager 缺少 run_decision 裁决出口"))
        try:
            d = run(event, tool_name=tool_name, payload=payload)
        except Exception as exc:  # noqa: BLE001
            return self._failed_closed(exc)
        if d is None:
            return self._failed_closed(
                RuntimeError("run_decision 返回 None（契约违约）"))
        return d

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
