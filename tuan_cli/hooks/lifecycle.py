"""B3 续轮 XIII：**18 个新增官方事件的统一生产出口**。

## 为什么需要它（实测复现，不是推测）

上一轮（XII）把事件表从 15 扩到 33，18 个新增事件配置**能加载**，
但实测跑真实操作（上下文压缩 / `/cd` / 批量工具 / 模型切换 / 指令
加载 / setup / worktree 移除 / todo 写入）**触发次数全部为 0**；
全仓源码扫描 18 个事件名在生产侧也**几乎全部 0 命中**。

更糟的是 D1：18 个新增事件被**全部**塞进 ``_NOTIFY_EVENTS``，而按
官方真值表其中 ConfigChange / TaskCreated / TaskCompleted /
PreCompact / PreModelSwitch / Stop / PostToolBatch 等是**可阻断 / 支持
JSON decision** 的事件 —— 走通知通道等于把 hook 的 stdout 裁决整个
吞掉。这正是 B3 主链路 R2 修过的坑，在新增事件上又犯了一次。

本模块做四件事：

1. ``emit()`` 按 ``exit_semantics`` 真值表**自动路由**：决策类走
   ``HookManager.run_event()``（解析 stdout），通知类走 ``run_notify``。
2. ``blocked`` 语义由 ``semantics_for(event).blocks_on_exit2`` 区分
   「可预防动作」（真阻断）与「动作已发生、只作反馈」（不阻断，但把
   reason 返回给调用方）。
3. ``WIRED_EVENTS`` 是**显式接线清单**：只列真正挂了生产代码的事件。
   ``coverage()`` 把 wired / no_local_lifecycle / not_wired 三张表分开
   核销 —— 绝不把「本地有对应概念」虚报成「已接生产触发点」。
4. 全路径异常隔离：没配 hooks、provider 抛异常、hook 自身炸了，
   都不得掀翻主流程（通知类吞掉，决策类沿用 B1 fail-closed）。

## 刻意不做的事

- **不造空转触发点**：本地确实没有对应生命周期的 6 个事件
  （``NO_LOCAL_LIFECYCLE``）如实登记，不为了凑覆盖率在渲染循环里
  假装派发 —— 那正是「转圈标语装忙」要反对的东西。
- **不改既有 7 个扩展事件的路由**：``triggers.py`` 里 ConfigChange
  是「写盘成功后」的通知语义（B3 V 修过「写盘失败不派发」），本轮
  **零改动**，不为了对齐数字破坏既有正确性。剩余语义差异在
  ``SEMANTIC_DIFFERENCES`` 里显式登记。
- **不把本地 CLI 没有的能力包装成对齐**：CC 事件面持续演进，本地
  只登记可核验清单，不宣称与某一发行版逐值相等。

许可：纯 Python 独立实现，零源码复制；见 ``NOTICE``。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Optional, Tuple

from . import exit_semantics as XS
from . import triggers as TR

# ---------------------------------------------------------------- 接线清单
# **只列真正挂了生产代码的事件**。每加一行，必须在
# tests/test_b3xiii_lifecycle.py 里有对应的端到端真跑验证（真跑真实
# 操作，不是 monkeypatch emit 自己）。coverage() 会核销三张表。
# 本轮由 ``lifecycle.emit`` 真实接线的事件（**只有这些**有本轮新增的
# 生产派发代码）。分开登记是为了不让「既有机制已接」被算成本轮成果。
LIFECYCLE_WIRED_EVENTS: FrozenSet[str] = frozenset({
    "PreCompact", "PostCompact", "CwdChanged", "PostToolBatch",
    "PostToolUseFailure", "PermissionDenied", "PreModelSwitch",
    "PostModelSwitch", "InstructionsLoaded", "Setup",
    "WorktreeRemove", "TaskCreated", "TaskCompleted",
})

# 既有机制已接（CORE 生命周期 + B3 续轮 5 个扩展事件），本轮零改动，
# 仅作为「有真实生产触发点」登记，不计入本轮接线成果。
LEGACY_WIRED_EVENTS: FrozenSet[str] = frozenset({
    "SessionStart", "SessionEnd", "PreToolUse", "PostToolUse",
    "UserPromptSubmit", "Stop", "SubagentStop", "Notification",
    "DirectoryAdded", "ConfigChange", "WorktreeCreate",
    "Elicitation", "ElicitationResult", "PermissionRequest",
})

WIRED_EVENTS: FrozenSet[str] = frozenset(
    LIFECYCLE_WIRED_EVENTS | LEGACY_WIRED_EVENTS)

# 与 CC 的**显式语义差异**（不是缺口，也不假装等价）。
SEMANTIC_DIFFERENCES: Dict[str, str] = {
    "ConfigChange": "Tuan 在写盘成功后派发（post-hoc 通知），CC 在变更前可阻断；"
                    "B3 V 的「写盘失败不派发」契约本轮零改动",
    "Elicitation": "Tuan 不允许模型自问自答（CC 允许程序化代答）——刻意更严",
    "ElicitationResult": "Tuan 只作废回答、绝不覆盖用户答案（CC 允许改写）",
    "WorktreeCreate": "Tuan 含 fast-resume 复用路径也派发，比 CC 更严",
    "PermissionRequest": "Tuan 的 hook allow 不能跳过 ctx.confirm 安全闸门",
    "PostModelSwitch": "set_model 只记录偏好、不保证切换已完成；本轮按通知派发",
    "PreCompact": "Tuan 有 agent 层既有通知 + context 层可阻断执行两个派发点，"
                  "CC 只有压缩前一个；如实登记双重触发，不假装逐值等价",
    "PostToolBatch": "CC 的 exit 2 会停止 agentic loop；Tuan 只派发并保留 reason，"
                     "不擅自替上层终止回合",
    "InstructionsLoaded": "payload 只带路径/字节数/是否截断，不带正文（凭据脱敏），"
                          "CC 会带文件内容",
}

_REENTRY = threading.local()
_STATS_LOCK = threading.Lock()
_STATS: Dict[str, int] = {
    "emitted": 0, "decision": 0, "notify": 0, "blocked": 0,
    "noop_no_hooks": 0, "reentry_suppressed": 0, "errors_swallowed": 0,
    "unknown_event": 0,
}


@dataclass(frozen=True)
class LifecycleOutcome:
    """一次派发的结构化结果（调用方据此决定是否真的阻止动作）。"""
    event: str
    fired: bool
    decision_channel: bool
    blocked: bool
    reason: str
    preventable: bool
    source: str          # explicit / owner / default / no_hooks / suppressed / error
    retry: bool = False  # PermissionDenied hookSpecificOutput.retry

    def to_dict(self) -> dict:
        return {
            "event": self.event, "fired": self.fired,
            "decision_channel": self.decision_channel, "blocked": self.blocked,
            "reason": self.reason[:400], "preventable": self.preventable,
            "source": self.source, "retry": self.retry,
        }


def _noop(event: str, source: str) -> LifecycleOutcome:
    return LifecycleOutcome(event, False, False, False, "", False, source)


def _resolve_hooks(hooks: Any, owner: Optional[str]) -> Tuple[Any, str]:
    """显式 hooks > owner 分桶 > 当前会话 > default。

    ``owner`` 查不到时**不回落** default（拼错 owner 绝不静默派到别的
    会话）—— 这是 B3 VI/VII 用实测换来的契约。
    """
    if hooks is not None:
        return hooks, "explicit"
    if owner is not None:
        h = TR.resolve_session(owner)
        if h is None:
            TR._bump_owner_miss(owner)
        return h, "owner"
    try:
        return TR.current_session_hooks(), "default"
    except Exception:  # noqa: BLE001 - provider 异常一律当「没配 hooks」
        return None, "default"


def _in_flight() -> set:
    s = getattr(_REENTRY, "events", None)
    if s is None:
        s = set()
        _REENTRY.events = s
    return s


def _bump(key: str) -> None:
    with _STATS_LOCK:
        _STATS[key] = _STATS.get(key, 0) + 1


def emit(event: str, payload: Optional[Dict[str, Any]] = None, *,
         hooks: Any = None, owner: Optional[str] = None,
         tool_name: str = "", prevent: Optional[bool] = None) -> LifecycleOutcome:
    """按官方真值表派发一个生命周期事件。

    ``prevent`` 覆盖「这次动作是否还能被阻止」：``None`` 时按
    ``semantics_for(event).blocks_on_exit2`` 判定。对「动作已发生」的
    事件（PostToolUse / PostToolUseFailure 等），即便 hook 返回 block
    也只把 reason 作为反馈返回，``blocked=False`` —— 与 CC 逐事件
    exit-code-2 表一致。
    """
    if not isinstance(event, str) or event not in XS.OFFICIAL_EVENTS:
        _bump("unknown_event")
        return _noop(str(event), "unknown_event")

    sem = XS.semantics_for(event)
    decision_channel = event in XS.DECISION_CAPABLE_EVENTS
    preventable = (prevent if prevent is not None
                   else bool(sem and sem.blocks_on_exit2))

    # 同线程同事件重入抑制（in-process hook 里再触发自己会无限递归）
    inflight = _in_flight()
    if event in inflight:
        _bump("reentry_suppressed")
        return _noop(event, "reentry_suppressed")

    m, source = _resolve_hooks(hooks, owner)
    if m is None:
        _bump("noop_no_hooks")
        return _noop(event, "no_hooks")

    pl = dict(payload or {})
    pl.setdefault("hook_event_name", event)
    inflight.add(event)
    try:
        _bump("emitted")
        if decision_channel:
            _bump("decision")
            d = m.run_event(event, pl, tool_name=tool_name)
            blocked = bool(d.block) and preventable
            if blocked:
                _bump("blocked")
            return LifecycleOutcome(
                event, True, True, blocked, d.reason or "",
                preventable, source, bool(getattr(d, "retry", False)))
        _bump("notify")
        # 既有 7 个扩展事件中 ConfigChange 等仍走 run_notify；新增通知类
        # 事件同样走它。run_notify 内部对决策类事件会 misrouted 拒绝，
        # 本函数已按真值表把决策类分流，不会踩到那个坑。
        m.run_notify(event, pl)
        return LifecycleOutcome(event, True, False, False, "",
                                preventable, source)
    except Exception as exc:  # noqa: BLE001 - 绝不掀翻主流程
        _bump("errors_swallowed")
        # 决策类沿用 B1 fail-closed；通知类只吞。
        if decision_channel and preventable:
            return LifecycleOutcome(
                event, True, True, True,
                f"生命周期 hook 通道异常 (fail-closed): {type(exc).__name__}",
                True, "error")
        return _noop(event, "error")
    finally:
        inflight.discard(event)


def emit_preventable(event: str, payload: Optional[Dict[str, Any]] = None,
                     **kw: Any) -> bool:
    """便捷入口：可预防动作，返回是否应当**阻止**该动作。"""
    return emit(event, payload, prevent=True, **kw).blocked


def coverage() -> dict:
    """三张表分开核销，禁止把「本地有能力」虚报成「已接触发点」。"""
    wired = set(WIRED_EVENTS)
    no_local = set(XS.NO_LOCAL_LIFECYCLE)
    official = set(XS.OFFICIAL_EVENTS)
    not_wired = official - wired - no_local
    return {
        "official": len(official),
        "wired": len(wired),
        "wired_this_round": len(LIFECYCLE_WIRED_EVENTS),
        "wired_legacy": len(LEGACY_WIRED_EVENTS),
        "no_local_lifecycle": len(no_local),
        "not_wired": len(not_wired),
        "not_wired_events": sorted(not_wired),
        "no_local_lifecycle_events": sorted(no_local),
        "decision_capable_wired": len(wired & set(XS.DECISION_CAPABLE_EVENTS)),
        "notify_only_wired": len(wired & set(XS.NOTIFY_ONLY_EVENTS)),
        "wired_all_official": wired <= official,
        "wired_disjoint_from_no_local": not (wired & no_local),
        "wired_equals_union": wired == (LIFECYCLE_WIRED_EVENTS | LEGACY_WIRED_EVENTS),
        "lifecycle_wired_disjoint_from_legacy": not (
            LIFECYCLE_WIRED_EVENTS & LEGACY_WIRED_EVENTS),
        "semantic_differences": dict(SEMANTIC_DIFFERENCES),
        "stats": dict(_STATS),
    }


def stats() -> dict:
    with _STATS_LOCK:
        return dict(_STATS)


def reset_stats() -> None:
    with _STATS_LOCK:
        for k in list(_STATS):
            _STATS[k] = 0


def validate() -> list:
    problems = []
    c = coverage()
    if not c["wired_all_official"]:
        problems.append("WIRED_EVENTS 含非官方事件")
    if not c["wired_disjoint_from_no_local"]:
        problems.append("WIRED_EVENTS 与 NO_LOCAL_LIFECYCLE 有交集")
    if c["wired"] + c["no_local_lifecycle"] + c["not_wired"] != c["official"]:
        problems.append("coverage 三张表不相加")
    if XS.validate():
        problems.append("exit_semantics 真值表自检不干净")
    if c["decision_capable_wired"] == 0:
        problems.append("没有任何决策类事件接了生产触发点")
    if not c["wired_equals_union"]:
        problems.append("WIRED_EVENTS 与两类接线清单不一致")
    if not c["lifecycle_wired_disjoint_from_legacy"]:
        problems.append("本轮接线与既有接线有交集（重复计数）")
    return problems
