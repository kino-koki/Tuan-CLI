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

## B3 续轮 XIV：接线之后的失败闭合与 payload 脱敏（先实测复现）

XIII 把 13 个事件接到真实生产点后，本轮真跑又抓出 7 个缺陷，全是
「装了 hook 反而不安全」这一类：

- **F1/F2（安全洞）**：``owner`` 未注册、或 provider 抛异常时
  ``_resolve_hooks`` 返回 ``None``，``emit`` 走 ``no_hooks`` 静默放行 ——
  ``emit_preventable`` 返回 ``False``，可预防动作照做。B3 VII 的
  「owner 拼错 fail-closed」与本模块 docstring 写的「决策类沿用 B1
  fail-closed」在**新模块里一条都没接**。
- **F3/F4**：``dict(payload or {})`` 在 ``try`` 之外，脏 payload
  （str/int/list）直接抛；``str(event)`` 对 ``__str__`` 抛异常的未知对象
  也掀翻 ``emit``。生产触发点全包 ``except Exception: pass``，异常被吞
  → 又一次静默放行。
- **F5（脱敏）**：真起 command hook 把 stdin 原样落盘，实测
  ``PermissionDenied`` 的 ``reason``/``safety_advice``、``TaskCreated``
  的 ``task.content``、``CwdChanged`` 的 ``cwd`` 把 ``ghp_`` 明文与
  OSC 8 / RLO 原样送给第三方子进程。前十几轮给日志 / 错误文本 /
  标语净化层建过的脱敏契约，这个新模块一条都没接。
- **F6**：hook stdout 的 ``reason`` 原样进 ``LifecycleOutcome``
  （``to_dict`` 只截 400，不剥控制字符）。
- **F7**：4 个可预防触发点的 ``except Exception: pass`` 吞掉注入的
  ``emit_preventable`` 异常，todo 仍写入、``set_model`` 仍切换。

修法：**``emit`` 自己永不抛异常**（全程单一 try + 按决策类 fail-closed
分流），payload / reason 统一过净化出口；4 个可预防触发点的兜底改
fail-closed。通知类 9 处保持吞异常（动作已发生，不该回滚）。

许可：纯 Python 独立实现，零源码复制；见 ``NOTICE``。
"""
from __future__ import annotations

import json
import math
import re
import threading
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Optional, Tuple

from tuan_cli.core import security_utils as _SU
from tuan_cli.ui.slogans import _clean as _CL

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
    "LifecyclePayload": "B3 XIV：Tuan 对所有 lifecycle payload 与 hook reason 做"
                        "控制字符清理 + 凭据脱敏 + 有界递归截断后才交给 hook，"
                        "CC 会把完整 payload（含工具参数/正文）原样传给 hook；"
                        "这是刻意更严的脱敏边界，不是事件语义等价",
}

_REENTRY = threading.local()
_STATS_LOCK = threading.Lock()
_STATS: Dict[str, int] = {
    "emitted": 0, "decision": 0, "notify": 0, "blocked": 0,
    "noop_no_hooks": 0, "reentry_suppressed": 0, "errors_swallowed": 0,
    "unknown_event": 0,
    # B3 XIV: 失败闭合与脱敏的可观测计数（不是装饰，validate 会核销键）
    "owner_not_registered": 0, "provider_error": 0,
    "payload_rejected": 0, "sanitized_fields": 0, "fail_closed": 0,
}

# ---------------------------------------------------------------- XIV: 净化出口
# 复现 F5：真起 command hook、把 stdin 原样落盘，实测 ``ghp_`` 明文与
# OSC 8 / RLO 原样进第三方子进程。复用既有**单一真值源**，不造第三套：
#   - 控制字符序列（OSC/CSI/bidi/Cf/Cc）→ _clean.sanitize_log_field
#   - 密钥（ENV 行 / key=value / Bearer / sk- / JWT）→ security_utils.redact_sensitive
# 顺序刻意是「先清控制字符，再脱敏」：控制字符夹在 token 中间时，先清理
# 才能让脱敏正则匹配上；安全文本链路的 safe_error_text 是同样的取舍。
#
# 本地补充一条：``redact_sensitive`` 实测**不认裸 ``ghp_`` 串**（只在
# ``GITHUB_TOKEN=...`` 这类 ENV 行/键值形式里遮蔽）。不改全局
# security_utils：那会误伤文档里的 ``ghp_...`` 占位串与既有审计口径，
# 属于把本轮修复扩散成全局行为变更。这里显式登记，只覆盖 lifecycle
# 出站的 payload / reason。
# A′（XIV 自查）两条：
# 1) 初版加了 ``\b`` 前边界，实测 ``xghp_<36 chars>``（token 与其它
#    文本粘连，这是 payload 里的常态）**匹配不到** —— ``x`` 与 ``g``
#    都是 \w，中间没有词边界。去掉边界，按子串匹配。
# 2) 初版 ``ghp_[A-Za-z0-9]{20,}`` 不含下划线，实测带下划线的
#    token 形态仍漏。统一成 ``[A-Za-z0-9_]{20,}``；仍要求 20+ 字符，
#    文档占位 ``ghp_...`` / ``ghp_REAL_SECRET_VALUE`` 不会被误伤。
# A′（XIV 自查 #3）：无上限的 ``{20,}`` 会把 token **后面紧邻的普通
# 文本**一并吃掉（实测 ``BLOCKED<token>END`` -> ``BLOCKED[REDACTED]``，
# ``END`` 丢了）。classic PAT 是 ``ghp_`` + 精确 36 位字母数字，优先用
# 精确分支；宽松分支保留给 fine-grained / 带下划线的形态，但设 80 上界
# 并在边界里如实登记「紧邻普通文本可能被一并遮蔽」。
_SECRET_TOKEN_RE = re.compile(
    r"(?:ghp_[A-Za-z0-9]{36}"
    r"|github_pat_[A-Za-z0-9_]{20,80}"
    r"|ghp_[A-Za-z0-9_]{20,80})")
_MAX_STR = 512            # 单个字符串值上限（码点）
_MAX_REASON = 400
_MAX_DEPTH = 8
_MAX_ITEMS = 64
_MAX_TOTAL = 65536        # 整个 payload 输出上限，防超长/深递归 DoS


def _clean_str(s: str, limit: int = _MAX_STR) -> str:
    """单个字符串出口：剥控制字符 → 脱敏凭据 → 限长。绝不抛异常。"""
    try:
        out = _CL.sanitize_log_field(s, 4096)
        out = _SU.redact_sensitive(out)
        out = _SECRET_TOKEN_RE.sub("[REDACTED]", out)
        if len(out) > limit:
            out = out[:limit].rstrip() + "…"
        return out
    except Exception:  # noqa: BLE001 - 净化自身绝不让事件通道再抛
        return ""


def _walk(value: Any, depth: int, budget: list, changed: list) -> Any:
    """有界递归净化：非 str 输入只取类型名，绝不 str() 未知对象。"""
    if depth > _MAX_DEPTH or budget[0] >= _MAX_TOTAL:
        changed[0] += 1
        return "<已截断:深度或总量超限>"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else "<non-finite-float>"
    if isinstance(value, str):
        s = _clean_str(value)
        if s != value:
            changed[0] += 1
        budget[0] += len(s)
        if budget[0] > _MAX_TOTAL:
            changed[0] += 1
            return "<已截断:总量超限>"
        return s
    if isinstance(value, (bytes, bytearray)):
        changed[0] += 1
        return "<bytes:%d>" % len(value)
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= _MAX_ITEMS:
                out["<...>"] = "<%d 项省略>" % (len(value) - _MAX_ITEMS)
                changed[0] += 1
                break
            key = _clean_str(k, 64) if isinstance(k, str) else type(k).__name__
            out[key] = _walk(v, depth + 1, budget, changed)
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        seq = list(value)
        if len(seq) > _MAX_ITEMS:
            changed[0] += 1
        return [_walk(x, depth + 1, budget, changed)
                for x in seq[:_MAX_ITEMS]]
    changed[0] += 1
    return "<%s>" % type(value).__name__


def _sanitize_payload(payload: Any) -> Tuple[Dict[str, Any], int]:
    """返回 (净化后 payload, 被改动字段数)。非 dict 一律拒绝，交给 emit
    按决策类 fail-closed —— 绝不把脏值变成「没配 hook」而放行。"""
    if not isinstance(payload, dict):
        raise TypeError("payload_must_be_dict")
    budget = [0]
    changed = [0]
    out = _walk(payload, 0, budget, changed)
    return out, changed[0]



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


def _resolve_hooks(hooks: Any, owner: Optional[str]) -> Tuple[Any, str, Optional[str]]:
    """显式 hooks > owner 分桶 > 当前会话 > default。

    **B3 XIV（F1/F2）**：返回第三项 ``failure``，把三种「拿不到 hooks」
    分开，绝不混成一个 ``no_hooks`` 静默放行：

    - ``owner_not_registered``：拼错 / 未注册的 owner（B3 VII O5 契约）
    - ``provider_error``：provider / registry 抛异常
    - ``None`` + ``source=no_hooks``：**确实没配 hook**，这是唯一允许
      放行的分支（既有「没配 hooks 时 emit 严格 no-op」契约零变化）
    """
    if hooks is not None:
        return hooks, "explicit", None
    if owner is not None:
        # A′（XIV 自查）：owner 非字符串 / 不可 hash 时 ``resolve_session``
        # 会抛 TypeError，旧版把它归到 provider_error —— 归因错了。
        # 拼错的 owner 就是「未注册」，不该被记成 provider 故障。
        if not isinstance(owner, str) or not owner:
            return None, "owner_not_registered", "owner_not_registered"
        try:
            h = TR.resolve_session(owner)
        except Exception:  # noqa: BLE001
            return None, "provider_error", "provider_error"
        if h is None:
            try:
                TR._bump_owner_miss(owner)
            except Exception:  # noqa: BLE001
                pass
            return None, "owner_not_registered", "owner_not_registered"
        return h, "owner", None
    # A′（XIV 自查 F2）：``TR.current_session_hooks()`` →
    # ``_resolve_default()`` **内部就把 provider 异常吞成 None**，
    # lifecycle 根本感知不到，于是又走 no_hooks 静默放行。这里直接
    # 取 provider 自己调一次（语义等价，只是能看见异常），不改
    # triggers 的既有「绝不掀翻主路径」契约。
    try:
        provider = TR.get_default_hooks_provider()
        h = provider() if provider is not None else None
    except Exception:  # noqa: BLE001
        return None, "provider_error", "provider_error"
    if h is None:
        return None, "no_hooks", None
    return h, "default", None


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

    **B3 XIV 契约：本函数永不抛异常。** 生产触发点全都包在
    ``try/except`` 里，只要 emit 会抛，异常就被吞成静默放行 —— 实测
    F3（脏 payload）、F4（恶意 event ``__str__``）、F7（注入异常）
    都是这条路。现在全程单一 try，任何异常按
    ``decision_channel and preventable`` fail-closed；通知类只吞。

    ``prevent`` 只接受 ``bool``（脏值回落真值表），``None`` 时按
    ``semantics_for(event).blocks_on_exit2`` 判定。
    """
    # event 守卫刻意**不调 str(event)**：未知对象 __str__ 可能抛异常
    # 或泄露 repr，固定占位 + unknown_event 计数即可（F4）。
    if not isinstance(event, str) or event not in XS.OFFICIAL_EVENTS:
        _bump("unknown_event")
        return _noop("<invalid-event>", "unknown_event")

    inflight = _in_flight()
    # A′（XIV 自查）：add 必须在判定**之后**。初版把 add 提到 try 外
    # 最前面，``event in inflight`` 于是恒真 —— 每个事件都被误判成
    # 重入、决策类全部 fail-closed，既有 XIII 回归整片变红。先算快照。
    reentry = event in inflight
    inflight.add(event)
    try:
        sem = XS.semantics_for(event)
        decision_channel = event in XS.DECISION_CAPABLE_EVENTS
        preventable = (prevent if isinstance(prevent, bool)
                       else bool(sem and sem.blocks_on_exit2))

        # 重入抑制：防 in-process hook 无限递归。决策类按 B3 V 既有
        # 契约 fail-closed，不静默放行。
        if reentry:
            _bump("reentry_suppressed")
            if decision_channel and preventable:
                _bump("fail_closed")
                return LifecycleOutcome(
                    event, False, True, True,
                    "生命周期 hook 重入抑制 (fail-closed)",
                    True, "reentry_suppressed")
            return _noop(event, "reentry_suppressed")

        # payload 归一化 + 净化（原本 dict(payload or {}) 在 try 之外）
        try:
            pl, nsan = _sanitize_payload(payload if payload is not None else {})
        except Exception:  # noqa: BLE001
            _bump("payload_rejected")
            if decision_channel and preventable:
                _bump("fail_closed")
                return LifecycleOutcome(
                    event, True, True, True,
                    "生命周期 payload 非法 (fail-closed)",
                    True, "payload_rejected")
            return _noop(event, "payload_rejected")
        if nsan:
            _bump("sanitized_fields")
        pl["hook_event_name"] = event

        m, source, failure = _resolve_hooks(hooks, owner)
        if failure is not None:
            _bump(failure)
            if decision_channel and preventable:
                _bump("fail_closed")
                return LifecycleOutcome(
                    event, True, True, True,
                    "生命周期 hook 通道不可用 (fail-closed): %s" % failure,
                    True, failure)
            return _noop(event, failure)
        if m is None:
            _bump("noop_no_hooks")
            return _noop(event, "no_hooks")

        _bump("emitted")
        if decision_channel:
            _bump("decision")
            d = m.run_event(event, pl, tool_name=tool_name)
            blocked = bool(d.block) and preventable
            if blocked:
                _bump("blocked")
            # hook stdout 的 reason 也过同一份净化真值（F6）
            reason = _clean_str(d.reason or "", _MAX_REASON)
            return LifecycleOutcome(
                event, True, True, blocked, reason,
                preventable, source, bool(getattr(d, "retry", False)))
        _bump("notify")
        m.run_notify(event, pl)
        return LifecycleOutcome(event, True, False, False, "",
                                preventable, source)
    except Exception as exc:  # noqa: BLE001 - 绝不掀翻主流程
        _bump("errors_swallowed")
        if decision_channel and preventable:
            _bump("fail_closed")
            return LifecycleOutcome(
                event, True, True, True,
                "生命周期 hook 通道异常 (fail-closed): %s" % type(exc).__name__,
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
    # B3 XIV: 净化出口真跑自检（不只检查函数存在）
    for key in ("owner_not_registered", "provider_error",
                "payload_rejected", "sanitized_fields", "fail_closed"):
        if key not in _STATS:
            problems.append("XIV 失败闭合计数键缺失: %s" % key)
    probe = ("x\x1b]8;;https://evil.example\x07\u202e" +
             "ghp_" + "A" * 36 + " GITHUB_TOKEN=ghp_" + "B" * 36)
    cleaned = _clean_str(probe)
    if "ghp_" in cleaned or "\x1b" in cleaned or "\u202e" in cleaned:
        problems.append("payload 净化出口未清除凭据/控制字符")
    try:
        dirty, n = _sanitize_payload({"a": probe, "b": [probe] * 3})
        if n == 0 or "ghp_" in json.dumps(dirty, ensure_ascii=False):
            problems.append("payload 递归净化未生效")
    except Exception as exc:  # noqa: BLE001
        problems.append("_sanitize_payload 抛异常: %s" % type(exc).__name__)
    return problems
