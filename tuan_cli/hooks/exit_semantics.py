"""Claude Code hooks **exit-code-2 逐事件语义**的可核验真值表。

为什么单独做这一层
==================
B3 主链路把 ``on_failure``（Tuan 的 fail-closed 出厂默认）当成**唯一**
故障处理规则：任何非零 rc 记一条 failure，out 为空就按策略闭合。这在
实测里被一行 stdout JSON 直接打穿：

    hook: exit 2, stderr="BLOCKED: 禁止写 /etc",
          stdout='{"hookSpecificOutput":{"permissionDecision":"allow"}}'
    Tuan 旧行为: block=False, reason="", failure_kind=""
    CC 官方行为: 阻断工具调用，stderr 作为阻断原因反馈给模型，
                 stdout 里的 allow **不能**覆盖 exit 2。

也就是说「失败闭合」被 stdout 的一行 JSON 绕过了，而且 stderr 里的
阻断原因彻底丢失。这不是文档口径问题，是**真实的安全洞**。

本模块做的事：

1. 把官方 Hooks 参考的**逐事件** exit-code-2 行为做成常量真值表
   （哪些事件阻断、哪些忽略 exit code、哪些只把 stderr 给用户看、
   WorktreeCreate/Remove 任何非零都失败、PermissionRequest 的 exit 2
   不生效只有 JSON decision 能 deny）。
2. ``classify()`` 返回结构化 ``ExitVerdict``，把「阻断 / 原因 /
   stderr 去向 / JSON 是否被忽略 / 走了哪条规则」全部显式化。
3. ``OFFICIAL_EVENTS`` / ``NO_MATCHER_EVENTS`` 让事件面可核销。

**刻意保留的 Tuan 差异**（不伪装成逐值相等）：

- Tuan 的 ``on_failure=block`` 出厂默认比 CC 更严：CC 里 exit 1 是
  非阻断错误、动作继续；Tuan 默认闭合。这是 B1 就确立的安全立场，
  **不因为对标就放宽**。``classify()`` 给的是「CC 原生语义」真值，
  调用方（``manager.run_pre`` / ``run_decision``）再叠加 Tuan 策略。
  两者差异可在 ``compare_with_tuan_policy()`` 里逐项核销。
- 官方不同页面对「exit 2 时 stdout JSON 是否被读取」措辞有差异
  （旧版参考说忽略 stdout 及其中 JSON；另一处说 JSON 字段仍读取但
  **不能覆盖**阻断）。所有来源一致的硬规则是：**allow 不能覆盖
  exit 2**。本实现锁死这一条，JSON 是否解析作为 ``json_ignored``
  字段显式记录，不臆测版本细节。

口径来源：Claude Code 官方 Hooks 参考 / hooks-guide（code.claude.com、
docs.claude.com），以及逐事件表交叉核对（cc.bruniaux.com
hooks-events-reference、Claude Wiki hooks-system）。CC 事件面随版本
演进，本表按可核验清单登记，**不宣称与某一发行版逐值相等**。

许可：纯 Python 独立实现，零源码复制；见 ``NOTICE``。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional

# ---------------------------------------------------------------- 行为枚举
# exit2 取值（官方逐事件表）:
#   blocks_*            —— exit 2 阻断该动作
#   nonblocking_notice  —— exit 2 只显示 hook error 通知，动作继续
#   stderr_only_*       —— 动作已发生/不可阻断，stderr 按去向呈现
#   ignored             —— exit code 与 stderr 完全忽略
#   not_honored         —— exit 2 不生效，只有 JSON decision 生效
EXIT2_BLOCKS = "blocks"
EXIT2_BLOCKS_FEED_CLAUDE = "blocks_feed_claude"
EXIT2_BLOCKS_SHOW_USER = "blocks_show_user"
EXIT2_NONBLOCKING_NOTICE = "nonblocking_notice"
EXIT2_STDERR_TO_CLAUDE = "stderr_to_claude"
EXIT2_STDERR_TO_USER = "stderr_to_user"
EXIT2_STDERR_DISCARDED = "stderr_discarded"
EXIT2_IGNORED = "ignored"
EXIT2_NOT_HONORED = "not_honored"

# stderr 去向
STDERR_CLAUDE = "claude"
STDERR_USER = "user"
STDERR_DISCARDED = "discarded"
STDERR_DEBUG = "debug_log"
STDERR_IGNORED = "ignored"


@dataclass(frozen=True)
class EventSemantics:
    event: str
    exit2: str
    stderr_destination: str
    any_nonzero_fails: bool = False
    exit_ignored: bool = False
    no_matcher: bool = False
    hook_specific_output_ignored_on_exit2: bool = False
    note: str = ""

    @property
    def blocks_on_exit2(self) -> bool:
        return self.exit2.startswith("blocks") or self.any_nonzero_fails


def _row(event, exit2, dest, **kw) -> EventSemantics:
    return EventSemantics(event=event, exit2=exit2,
                          stderr_destination=dest, **kw)


# ---------------------------------------------------------------- 官方逐事件真值表
# 依据：官方 Hooks 参考「Exit code 2 behavior per event」+ 交叉核对表。
_SEMANTICS: Dict[str, EventSemantics] = {
    e.event: e for e in (
        # ---- 工具生命周期
        _row("PreToolUse", EXIT2_BLOCKS_FEED_CLAUDE, STDERR_CLAUDE,
             note="阻断工具调用，stderr 反馈给模型"),
        _row("PostToolUse", EXIT2_STDERR_TO_CLAUDE, STDERR_CLAUDE,
             note="工具已执行，stderr 只作为反馈，阻断被忽略"),
        _row("PostToolUseFailure", EXIT2_STDERR_TO_CLAUDE, STDERR_CLAUDE,
             note="同上，工具已失败"),
        _row("PostToolBatch", EXIT2_BLOCKS, STDERR_CLAUDE,
             no_matcher=True, note="下次模型调用前停止 agentic loop"),
        _row("PermissionRequest", EXIT2_NOT_HONORED, STDERR_DISCARDED,
             note="exit 2 不生效：权限流照旧、stderr 丢弃；只有 JSON decision 能 deny"),
        _row("PermissionDenied", EXIT2_IGNORED, STDERR_IGNORED,
             exit_ignored=True, note="exit code 与 stderr 完全忽略"),
        # ---- 回合 / 子代理 / 团队
        _row("Stop", EXIT2_BLOCKS_FEED_CLAUDE, STDERR_CLAUDE,
             no_matcher=True, note="阻止停止、继续回合；reason 成为下一条指令"),
        _row("StopFailure", EXIT2_IGNORED, STDERR_IGNORED,
             exit_ignored=True, note="输出与 exit code 完全忽略"),
        _row("SubagentStart", EXIT2_NONBLOCKING_NOTICE, STDERR_USER,
             note="stderr 作为 hook error 通知，子代理继续"),
        _row("SubagentStop", EXIT2_BLOCKS_FEED_CLAUDE, STDERR_CLAUDE,
             note="阻止子代理停止"),
        _row("TeammateIdle", EXIT2_BLOCKS_FEED_CLAUDE, STDERR_CLAUDE,
             no_matcher=True, note="队友继续工作，stderr 反馈"),
        _row("TaskCreated", EXIT2_BLOCKS_FEED_CLAUDE, STDERR_CLAUDE,
             no_matcher=True, note="回滚任务创建"),
        _row("TaskCompleted", EXIT2_BLOCKS_FEED_CLAUDE, STDERR_CLAUDE,
             no_matcher=True, note="阻止完成"),
        # ---- 提示 / 模型
        _row("UserPromptSubmit", EXIT2_BLOCKS_SHOW_USER, STDERR_USER,
             no_matcher=True, note="阻断 prompt 并从 context 抹除，stderr 给用户且不进 context"),
        _row("UserPromptExpansion", EXIT2_BLOCKS_SHOW_USER, STDERR_USER,
             note="阻断展开"),
        _row("PreModelSwitch", EXIT2_BLOCKS_SHOW_USER, STDERR_USER,
             note="阻断模型切换，stderr 给用户"),
        _row("PostModelSwitch", EXIT2_STDERR_TO_USER, STDERR_USER,
             note="模型已切换，stderr 只给用户"),
        _row("MessageDisplay", EXIT2_STDERR_TO_USER, STDERR_USER,
             no_matcher=True, note="原文照常显示"),
        # ---- 配置 / 文件 / 目录
        _row("Setup", EXIT2_NONBLOCKING_NOTICE, STDERR_USER,
             note="仅通知"),
        _row("SessionStart", EXIT2_NONBLOCKING_NOTICE, STDERR_USER,
             note="仅通知，会话继续"),
        _row("SessionEnd", EXIT2_STDERR_TO_USER, STDERR_USER,
             note="stderr 只给用户"),
        _row("ConfigChange", EXIT2_BLOCKS, STDERR_CLAUDE,
             note="阻断配置变更（policy_settings 除外）"),
        _row("InstructionsLoaded", EXIT2_IGNORED, STDERR_IGNORED,
             exit_ignored=True, note="exit code 忽略，observability-only"),
        _row("CwdChanged", EXIT2_STDERR_TO_USER, STDERR_USER,
             no_matcher=True, note="stderr 只给用户"),
        _row("FileChanged", EXIT2_STDERR_TO_USER, STDERR_USER,
             note="stderr 只给用户；matcher 是字面文件名，非 regex"),
        _row("DirectoryAdded", EXIT2_STDERR_DISCARDED, STDERR_DEBUG,
             note="目录已添加；stderr 进 debug log"),
        _row("Notification", EXIT2_STDERR_TO_USER, STDERR_USER,
             note="stderr 只给用户"),
        # ---- 压缩
        _row("PreCompact", EXIT2_BLOCKS, STDERR_CLAUDE,
             note="阻断压缩"),
        _row("PostCompact", EXIT2_STDERR_TO_USER, STDERR_USER,
             note="stderr 只给用户"),
        # ---- worktree：任何非零都失败
        _row("WorktreeCreate", EXIT2_BLOCKS, STDERR_CLAUDE,
             any_nonzero_fails=True, no_matcher=True,
             note="任何非零 rc 都使创建失败，JSON 说了不算"),
        _row("WorktreeRemove", EXIT2_BLOCKS, STDERR_CLAUDE,
             any_nonzero_fails=True, no_matcher=True,
             note="任何非零 rc 且目录仍存在 → 移除失败"),
        # ---- MCP elicitation
        _row("Elicitation", EXIT2_BLOCKS, STDERR_CLAUDE,
             hook_specific_output_ignored_on_exit2=True,
             note="拒绝 elicitation；exit 2 时 hookSpecificOutput 被忽略"),
        _row("ElicitationResult", EXIT2_BLOCKS, STDERR_CLAUDE,
             hook_specific_output_ignored_on_exit2=True,
             note="阻断响应（effective action = decline）；hookSpecificOutput 被忽略"),
    )
}

# 官方事件面（按可核验清单登记，33 项）。CC 会持续新增事件，故以
# 「配置不再被静默丢弃」为契约，不宣称与某一版本逐值相等。
OFFICIAL_EVENTS: FrozenSet[str] = frozenset(_SEMANTICS)

NO_MATCHER_EVENTS: FrozenSet[str] = frozenset(
    e.event for e in _SEMANTICS.values() if e.no_matcher)

ANY_NONZERO_FAILS_EVENTS: FrozenSet[str] = frozenset(
    e.event for e in _SEMANTICS.values() if e.any_nonzero_fails)

EXIT_IGNORED_EVENTS: FrozenSet[str] = frozenset(
    e.event for e in _SEMANTICS.values() if e.exit_ignored)

# ---------------------------------------------------------------- 决策通道分类
# B3 续轮 XIII 实测复现：上一轮把 18 个新增事件**全部**塞进
# ``_NOTIFY_EVENTS``，但按官方真值表其中 ConfigChange / TaskCreated /
# TaskCompleted / PreCompact / PreModelSwitch / Stop / PostToolBatch
# 等是**可阻断 / 支持 JSON decision** 的事件。走通知通道等于把 hook
# 的 stdout 裁决整个吞掉 —— 正是 B3 主链路 R2 修过的坑，在新增事件上
# 又犯了一次。
#
# 这里是显式真值源（不靠 ``blocks_on_exit2`` 隐式推断，因为
# PermissionDenied 虽忽略 exit code 却支持 hookSpecificOutput.retry，
# PermissionRequest 虽 exit 2 不生效却只有 JSON decision 能 deny）。
DECISION_CAPABLE_EVENTS: FrozenSet[str] = frozenset({
    # 顶层 decision:"block" / hookSpecificOutput 类
    "PreToolUse", "PermissionRequest", "PreModelSwitch",
    "UserPromptSubmit", "UserPromptExpansion", "PostToolUse",
    "PostToolUseFailure", "PostToolBatch", "Stop", "SubagentStop",
    "TeammateIdle", "TaskCreated", "TaskCompleted", "ConfigChange",
    "PreCompact", "Elicitation", "ElicitationResult",
    # 任何非零都失败（JSON 说了不算）
    "WorktreeCreate", "WorktreeRemove",
    # exit code 被忽略，但 hookSpecificOutput.retry 仍生效
    "PermissionDenied",
})

NOTIFY_ONLY_EVENTS: FrozenSet[str] = frozenset(
    OFFICIAL_EVENTS - DECISION_CAPABLE_EVENTS)

# ---------------------------------------------------------------- 本地生命周期
# 如实登记：Tuan 是单进程 CLI，以下事件在**本地没有对应生命周期**。
# 不造空转触发点（那正是「转圈标语装忙」要反对的东西），也不把
# 「本地不适用」包装成「已对齐」。配置这些事件仍可加载、仍可经
# 统一出口派发（供外部集成/未来宿主），但本地 CLI 不会凭空触发。
NO_LOCAL_LIFECYCLE: FrozenSet[str] = frozenset({
    "FileChanged",       # 无文件监视器 / CLAUDE_ENV_FILE watch list
    "TeammateIdle",      # 无 agent team 编排
    "SubagentStart",     # ports/protocol 有事件类，但生产侧无派发点
    "UserPromptExpansion",  # 无 prompt 展开机制
    "MessageDisplay",    # TUI render 层，本轮不接（避免渲染循环副作用）
})
# A′ 自查修正：初版把 ``PostModelSwitch`` 也列进 NO_LOCAL_LIFECYCLE，
# 但同一轮又在 ``KernelAcpBridge.set_model`` 真接了它 —— 自相矛盾，
# validate() 立刻报「WIRED 与 NO_LOCAL 有交集 / 三表不相加」。
# 真实情况是「接了，但语义不完全等价」，应留在
# ``lifecycle.SEMANTIC_DIFFERENCES``，而不是「本地无生命周期」。

# A′ 自查修正：初版把「不是 NO_LOCAL_LIFECYCLE」直接叫
# ``LOCAL_LIFECYCLE_EVENTS``，27 个事件全都算进去，会给人「都有生产
# 触发点」的错觉 —— 那恰恰是用户反对的「广度代替深度」。改名为
# ``LOCAL_CAPABLE``（仅表示本地有对应概念/能力），**实际接线清单**
# 由 ``lifecycle.WIRED_EVENTS`` 单独维护，两张表分开核销。
LOCAL_CAPABLE_EVENTS: FrozenSet[str] = frozenset(
    OFFICIAL_EVENTS - NO_LOCAL_LIFECYCLE)


def semantics_for(event: str) -> Optional[EventSemantics]:
    if not isinstance(event, str):
        return None
    return _SEMANTICS.get(event)


@dataclass(frozen=True)
class ExitVerdict:
    """结构化裁决：调用方不需要再猜「这个 rc 到底该不该阻断」。"""
    event: str
    rc: int
    block: bool
    reason: str
    stderr_destination: str
    json_ignored: bool
    code_path: str          # 走了哪条规则，供审计与回归核销
    known_event: bool
    # A′ 自查修正：CC 在**非 2** 的非零退出码下仍读取 stdout 的有效
    # JSON decision（"reads JSON output fields from stdout on every exit
    # code, not only 0"）。Tuan 的 on_failure 叠加层虽也闭合，但不能
    # 因此把 hook 自己写的 reason 吞掉。只有 exit 2 / any_nonzero_fails
    # 才**绝不**允许 JSON 覆盖（H1 硬规则）。
    json_may_override: bool = False

    def to_dict(self) -> dict:
        return {
            "event": self.event, "rc": self.rc, "block": self.block,
            "reason": self.reason[:400],
            "stderr_destination": self.stderr_destination,
            "json_ignored": self.json_ignored,
            "code_path": self.code_path, "known_event": self.known_event,
            "json_may_override": self.json_may_override,
        }


def classify(event: str, rc: int, stderr: str = "",
             *, tuan_policy: str = "block") -> ExitVerdict:
    """把 ``(event, rc, stderr)`` 裁决成结构化结果。

    ``tuan_policy`` 是 Tuan 的 ``on_failure`` 叠加层：

    - ``block`` / ``ask``（出厂默认）：**非 2 的非零 rc 也闭合**
      （CC 里那是非阻断错误）。这是 B1 既有安全立场，显式保留。
    - ``allow``：显式逃生口，非 2 非零 rc 不闭合、只留痕。

    无论策略如何，**exit 2 在可阻断事件上一定阻断，且 stdout 的
    allow 不能覆盖** —— 这正是修掉 H1 的硬规则。
    """
    if not isinstance(rc, int) or isinstance(rc, bool):
        rc = 0
    sem = semantics_for(event)
    known = sem is not None
    err = (stderr or "").strip()

    if not known:
        # 未知事件：Tuan 不静默放行，沿用既有 fail-closed。
        blocking = rc != 0 and tuan_policy in ("block", "ask")
        return ExitVerdict(event, rc, blocking,
                           err or f"未知事件 {event!r} rc={rc}",
                           STDERR_USER, False,
                           "unknown_event_fail_closed" if blocking
                           else "unknown_event_no_failure",
                           False)

    # 1) exit code 完全忽略的事件
    if sem.exit_ignored:
        return ExitVerdict(event, rc, False, "", STDERR_IGNORED,
                           False, "exit_ignored", True)

    # 2) 任何非零都失败（WorktreeCreate / WorktreeRemove）
    if sem.any_nonzero_fails and rc != 0:
        return ExitVerdict(event, rc, True,
                           err or f"{event} 非零 rc={rc}（CC: 任何非零都失败）",
                           STDERR_CLAUDE, True,
                           "any_nonzero_fails", True)

    # 3) exit 2
    if rc == 2:
        if sem.exit2 == EXIT2_NOT_HONORED:
            # PermissionRequest：exit 2 不生效，stderr 丢弃；只有 JSON deny
            return ExitVerdict(event, rc, False, "", STDERR_DISCARDED,
                               False, "exit2_not_honored", True)
        if sem.blocks_on_exit2:
            return ExitVerdict(event, rc, True,
                               err or f"{event} 被 hook exit 2 阻断",
                               sem.stderr_destination, True,
                               "exit2_blocks", True)
        if sem.exit2 == EXIT2_NONBLOCKING_NOTICE:
            return ExitVerdict(event, rc, False,
                               err or "hook error notice",
                               sem.stderr_destination, False,
                               "exit2_nonblocking_notice", True)
        if sem.exit2 in (EXIT2_STDERR_TO_CLAUDE, EXIT2_STDERR_TO_USER,
                         EXIT2_STDERR_DISCARDED):
            return ExitVerdict(event, rc, False, err,
                               sem.stderr_destination, False,
                               "exit2_stderr_only", True)
        return ExitVerdict(event, rc, False, err,
                           sem.stderr_destination, False,
                           "exit2_ignored", True)

    # 4) 其它非零 rc：CC 是非阻断错误；Tuan 默认策略可叠加闭合
    if rc != 0:
        if tuan_policy in ("block", "ask"):
            return ExitVerdict(event, rc, True,
                               err or f"hook 非零 rc={rc}（Tuan on_failure={tuan_policy} 闭合）",
                               sem.stderr_destination, False,
                               "non2_nonzero_tuan_fail_closed", True,
                               json_may_override=True)
        return ExitVerdict(event, rc, False, err,
                           STDERR_USER, False,
                           "non2_nonzero_nonblocking_error", True)

    return ExitVerdict(event, rc, False, "", sem.stderr_destination,
                       False, "exit0", True)


def compare_with_tuan_policy() -> dict:
    """逐项核销「CC 原生」与「Tuan 叠加策略」的差异，防止靠口径蒙混。"""
    diffs = []
    for name in sorted(_SEMANTICS):
        cc = classify(name, 1, "boom", tuan_policy="allow")
        tuan = classify(name, 1, "boom", tuan_policy="block")
        if cc.block != tuan.block:
            diffs.append({"event": name, "cc_block": cc.block,
                          "tuan_block": tuan.block,
                          "cc_path": cc.code_path,
                          "tuan_path": tuan.code_path})
    return {"events": len(_SEMANTICS),
            "non2_nonzero_differences": diffs,
            "exit2_always_blocks_when_preventable": all(
                classify(n, 2, "boom", tuan_policy="allow").block
                for n, s in _SEMANTICS.items()
                if s.blocks_on_exit2)}


def validate() -> list:
    """真值表自检：常量自洽、无重复、no_matcher / 特例集合可反查。"""
    problems = []
    if len(_SEMANTICS) != len(OFFICIAL_EVENTS):
        problems.append("事件表与 OFFICIAL_EVENTS 数量不一致")
    if not NO_MATCHER_EVENTS <= OFFICIAL_EVENTS:
        problems.append("NO_MATCHER_EVENTS 含未知事件")
    if ANY_NONZERO_FAILS_EVENTS != frozenset(
            {"WorktreeCreate", "WorktreeRemove"}):
        problems.append("any_nonzero_fails 特例集合不对")
    if EXIT_IGNORED_EVENTS != frozenset(
            {"PermissionDenied", "StopFailure", "InstructionsLoaded"}):
        problems.append("exit_ignored 特例集合不对")
    # B3 XIII: 分类自洽
    if not DECISION_CAPABLE_EVENTS <= OFFICIAL_EVENTS:
        problems.append("DECISION_CAPABLE_EVENTS 含未知事件")
    if DECISION_CAPABLE_EVENTS & NOTIFY_ONLY_EVENTS:
        problems.append("决策类与通知类有交集")
    if (DECISION_CAPABLE_EVENTS | NOTIFY_ONLY_EVENTS) != OFFICIAL_EVENTS:
        problems.append("决策/通知分类未覆盖全部事件")
    if not NO_LOCAL_LIFECYCLE <= OFFICIAL_EVENTS:
        problems.append("NO_LOCAL_LIFECYCLE 含未知事件")
    if (LOCAL_CAPABLE_EVENTS | NO_LOCAL_LIFECYCLE) != OFFICIAL_EVENTS:
        problems.append("本地能力登记未覆盖全部事件")
    if LOCAL_CAPABLE_EVENTS & NO_LOCAL_LIFECYCLE:
        problems.append("本地能力登记有交集")
    # 硬规则：可阻断事件必须在决策类里（否则 JSON 裁决被吞）
    for name, sem in _SEMANTICS.items():
        if sem.blocks_on_exit2 and name not in DECISION_CAPABLE_EVENTS:
            problems.append("%s 可阻断却落在通知类" % name)
    # 硬规则：exit 完全忽略的事件除 PermissionDenied 外不进决策类
    for name in EXIT_IGNORED_EVENTS - {"PermissionDenied"}:
        if name in DECISION_CAPABLE_EVENTS:
            problems.append("%s exit 被忽略却进了决策类" % name)
    for name, sem in _SEMANTICS.items():
        if sem.event != name:
            problems.append("%s: event 字段不匹配" % name)
        if sem.exit_ignored and sem.blocks_on_exit2:
            problems.append("%s: exit_ignored 与 blocks 冲突" % name)
    # 硬规则：所有可阻断事件的 exit 2 在 allow 策略下也必须阻断
    for name, sem in _SEMANTICS.items():
        if sem.blocks_on_exit2:
            v = classify(name, 2, "boom", tuan_policy="allow")
            if not v.block or not v.json_ignored:
                problems.append("%s: exit 2 未强制阻断/未忽略 JSON" % name)
    # 硬规则：exit 2 绝不允许 JSON 覆盖；非 2 非零允许 JSON decision 优先
    v2 = classify("PreToolUse", 2, "boom")
    if v2.json_may_override or not v2.json_ignored:
        problems.append("exit 2 未锁死 JSON 覆盖")
    v1 = classify("PreToolUse", 1, "boom")
    if not v1.json_may_override or v1.json_ignored:
        problems.append("rc=1 的有效 JSON decision 被吞掉")
    # 硬规则：PermissionRequest 的 exit 2 不阻断
    v = classify("PermissionRequest", 2, "boom")
    if v.block or v.code_path != "exit2_not_honored":
        problems.append("PermissionRequest exit 2 语义不对")
    # 硬规则：exit_ignored 事件任何 rc 都不阻断
    for name in EXIT_IGNORED_EVENTS:
        for rc in (0, 1, 2, 7):
            if classify(name, rc, "boom").block:
                problems.append("%s rc=%d 不该阻断" % (name, rc))
    return problems
