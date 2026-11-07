"""与 Codex ``tui/src/collaboration_modes.rs`` 对齐的协作模式预设。

上游模块头（契约原文）：

    "Server collaboration-mode discovery and TUI-visible selection.
     Missing discovery adds no presets."

逐分支对齐：
  - ``filtered_presets``：只保留 ``mask.mode.is_some_and(ModeKind::is_tui_visible)``
    的预设（**不可见 mode 一律不进 UI 列表**）；
  - ``default_mask``：先找 ``ModeKind::Default``，找不到则取列表第一个；
  - ``mask_for_kind``：**先检查 kind 是否 tui_visible，不可见直接 None**，
    再在已过滤预设里找；
  - ``next_mask``：按列表顺序循环，当前不在列表里时从第 0 个开始
    （``map_or(0, |idx| (idx+1) % len)``）；
  - ``default_mode_mask`` / ``plan_mask`` 是 ``mask_for_kind`` 的包装；
  - ``list()``：带 **2 秒超时**的 RPC；成功时逐 mask 重建，且
    ``developer_instructions: Some(None)`` —— 上游注释：
      "The RPC intentionally omits prompts. Clear restored overrides so the
       server supplies its current instructions when this mode is selected."
    **失败/超时/任何错误一律返回空 Vec + warn**，注释写
    "Discovery is optional even on servers that accept the rest of TUI bootstrap."

**本轮最值钱的修正**：上游把「发现失败」和「服务端确实没有预设」
都压成**同一个空 Vec**（模块头那句 "Missing discovery adds no presets"）。
调用方无法区分「没查到」与「查了但没有」，于是一个超时/网络错误会
被当成「无需展示模式选择器」静默吞掉。本模块用 ``DiscoveryResult``
显式区分 ``ok / empty / unavailable / timeout / protocol_error``，并保留
``warning``；**``unavailable`` 绝不冒充 ``empty``**。

本地化修改（如实列出）：
  - Rust ``ModeKind`` / ``CollaborationModeMask`` -> Python Enum + dataclass；
  - **严格字段白名单**：RPC 返回的未知字段一律拒绝（对齐 Rust 编译期
    类型；动态 dict 若不拦会把服务端新增字段带进 UI/日志）；
  - ``developer_instructions`` 显式置 ``None`` 且新增
    ``prompts_omitted=True`` 标记，让「服务端会提供当前指令」可审计；
  - 字符串字段做控制字符/长度校验（防终端转义注入，与第 11 轮
    ``terminal_program_status`` 口径一致）；
  - 中文/本地模型字段，超时可注入，便于确定性测试；
  - 本地化增强：``discover()`` 返回结构化结果，调用方必须显式处理
    ``unavailable``，不提供「静默当空」的默认路径。

许可：Apache-2.0（NOTICE 第 13 条）。无 Rust 源码逐字复制。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence

DISCOVERY_TIMEOUT_SECS = 2  # 逐值对齐 Duration::from_secs(2)
DISCOVERY_REQUEST_PREFIX = "collaboration-mode-list-"
MAX_STRING_FIELD_LEN = 512

# 上游 mask 的五个字段（严格白名单）
MASK_FIELDS = ("name", "mode", "model", "reasoning_effort",
               "developer_instructions")


class ModeKind(str, Enum):
    """对齐上游 ``ModeKind`` 的 TUI 可见性判定。"""

    DEFAULT = "Default"
    PLAN = "Plan"
    # 上游还有若干非 TUI 可见 kind；本地只保留这两个 + 一个不可见样例
    HIDDEN = "Hidden"  # 用于验证 is_tui_visible() 的负分支

    def is_tui_visible(self) -> bool:
        """逐值对齐 ``ModeKind::is_tui_visible``。"""
        return self in (ModeKind.DEFAULT, ModeKind.PLAN)


@dataclass(frozen=True)
class CollaborationModeMask:
    """对齐 ``CollaborationModeMask`` 五字段。"""

    name: str = ""
    mode: Optional[ModeKind] = None
    model: Optional[str] = None
    reasoning_effort: Optional[str] = None
    # Some(None)：RPC 故意省略 prompts，清掉恢复的覆盖
    developer_instructions: Optional[str] = None
    prompts_omitted: bool = True  # 本地化标记（见模块头）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "mode": self.mode.value if self.mode else None,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "developer_instructions": self.developer_instructions,
            "prompts_omitted": self.prompts_omitted,
        }


def _safe_text(value: Any, label: str, problems: List[str]) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        problems.append(f"{label} 不是字符串")
        return None
    if len(value) > MAX_STRING_FIELD_LEN:
        problems.append(f"{label} 超长 ({len(value)})")
        return None
    if any(ord(c) < 32 or c in ("\x07", "\x1b") for c in value):
        problems.append(f"{label} 含终端控制字符")
        return None
    return value


def mask_from_wire(raw: Dict[str, Any],
                   problems: Optional[List[str]] = None) -> CollaborationModeMask:
    """对齐 ``list()`` 里的逐 mask 重建，外加严格字段白名单。"""
    problems = problems if problems is not None else []
    for k in raw:
        if k not in MASK_FIELDS:
            problems.append(f"collaboration mask 含未知字段 {k!r}")
    mode_raw = raw.get("mode")
    mode: Optional[ModeKind] = None
    if mode_raw is not None:
        try:
            mode = ModeKind(str(mode_raw))
        except ValueError:
            problems.append(f"未知 mode {mode_raw!r}")
    # 上游 developer_instructions: Some(None) —— 清掉恢复的覆盖
    return CollaborationModeMask(
        name=_safe_text(raw.get("name"), "name", problems) or "",
        mode=mode,
        model=_safe_text(raw.get("model"), "model", problems),
        reasoning_effort=_safe_text(raw.get("reasoning_effort"),
                                    "reasoning_effort", problems),
        developer_instructions=None,
        prompts_omitted=True,
    )


# ---------------------------------------------------------------- 预设筛选
def filtered_presets(catalog_masks: Sequence[CollaborationModeMask]
                     ) -> List[CollaborationModeMask]:
    """对齐：只保留 ``mode.is_some_and(is_tui_visible)``。"""
    return [m for m in catalog_masks
            if m.mode is not None and m.mode.is_tui_visible()]


def default_mask(catalog_masks: Sequence[CollaborationModeMask]
                 ) -> Optional[CollaborationModeMask]:
    """先找 Default，找不到取第一个；空列表返回 None。"""
    presets = filtered_presets(catalog_masks)
    for m in presets:
        if m.mode is ModeKind.DEFAULT:
            return m
    return presets[0] if presets else None


def mask_for_kind(catalog_masks: Sequence[CollaborationModeMask],
                  kind: ModeKind) -> Optional[CollaborationModeMask]:
    """**先判可见性**：不可见 kind 直接 None（上游逐分支）。"""
    if not kind.is_tui_visible():
        return None
    return next((m for m in filtered_presets(catalog_masks)
                 if m.mode is kind), None)


def default_mode_mask(catalog_masks: Sequence[CollaborationModeMask]
                      ) -> Optional[CollaborationModeMask]:
    return mask_for_kind(catalog_masks, ModeKind.DEFAULT)


def plan_mask(catalog_masks: Sequence[CollaborationModeMask]
              ) -> Optional[CollaborationModeMask]:
    return mask_for_kind(catalog_masks, ModeKind.PLAN)


def next_mask(catalog_masks: Sequence[CollaborationModeMask],
              current: Optional[CollaborationModeMask]
              ) -> Optional[CollaborationModeMask]:
    """按列表顺序循环；当前不在列表里 -> 第 0 个（对齐 ``map_or(0,..)``）。"""
    presets = filtered_presets(catalog_masks)
    if not presets:
        return None
    current_kind = current.mode if current else None
    idx = next((i for i, m in enumerate(presets)
                if m.mode is current_kind), None)
    next_index = 0 if idx is None else (idx + 1) % len(presets)
    return presets[next_index]


# ---------------------------------------------------------------- 发现
class DiscoveryStatus(str, Enum):
    """本地化：把上游「一律空 Vec」拆成可区分的状态。"""

    OK = "ok"
    EMPTY = "empty"
    UNAVAILABLE = "unavailable"   # 上游吞掉的失败
    TIMEOUT = "timeout"
    PROTOCOL_ERROR = "protocol_error"


@dataclass(frozen=True)
class DiscoveryResult:
    status: DiscoveryStatus
    masks: List[CollaborationModeMask] = field(default_factory=list)
    warning: Optional[str] = None
    request_id: Optional[str] = None
    problems: List[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """调用方必须显式处理 UNAVAILABLE，绝不静默当空。"""
        return self.status in (DiscoveryStatus.OK, DiscoveryStatus.EMPTY)

    def to_dict(self) -> Dict[str, Any]:
        return {"status": self.status.value,
                "masks": [m.to_dict() for m in self.masks],
                "warning": self.warning,
                "request_id": self.request_id,
                "usable": self.usable,
                "problems": list(self.problems)}


def discover(
    requester: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
    *, request_id: Optional[str] = None,
    timeout_secs: float = DISCOVERY_TIMEOUT_SECS,
    clock: Optional[Callable[[], float]] = None,
) -> DiscoveryResult:
    """对齐 ``list()`` 的 2s 超时与逐 mask 重建，但**不吞掉失败**。

    ``requester(request_id, params)`` 返回 wire 响应 dict（含 ``data``
    列表）或抛异常；``clock`` 可注入用于确定性超时测试。
    """
    rid = request_id or (DISCOVERY_REQUEST_PREFIX + "local")
    if requester is None:
        return DiscoveryResult(
            status=DiscoveryStatus.UNAVAILABLE, request_id=rid,
            warning="optional collaborationMode/list discovery unavailable "
                    "(no requester configured)")
    t0 = clock() if clock else 0.0
    try:
        response = requester(rid, {})
    except TimeoutError:
        return DiscoveryResult(
            status=DiscoveryStatus.TIMEOUT, request_id=rid,
            warning=f"collaborationMode/list discovery timed out after "
                    f"{timeout_secs}s")
    except Exception as exc:  # noqa: BLE001 - 对齐上游「任何错误」
        return DiscoveryResult(
            status=DiscoveryStatus.UNAVAILABLE, request_id=rid,
            warning=f"optional collaborationMode/list discovery unavailable: "
                    f"{type(exc).__name__}: {exc}")
    if clock and clock() - t0 > timeout_secs:
        return DiscoveryResult(
            status=DiscoveryStatus.TIMEOUT, request_id=rid,
            warning=f"collaborationMode/list discovery timed out after "
                    f"{timeout_secs}s")
    if not isinstance(response, dict) or not isinstance(response.get("data"), list):
        return DiscoveryResult(
            status=DiscoveryStatus.PROTOCOL_ERROR, request_id=rid,
            warning="collaborationMode/list 响应缺少 data 列表")
    problems: List[str] = []
    masks = [mask_from_wire(x, problems) if isinstance(x, dict)
             else CollaborationModeMask() for x in response["data"]]
    if problems:
        return DiscoveryResult(
            status=DiscoveryStatus.PROTOCOL_ERROR, request_id=rid,
            warning="collaborationMode/list 响应字段校验失败",
            problems=problems)
    return DiscoveryResult(
        status=DiscoveryStatus.OK if masks else DiscoveryStatus.EMPTY,
        masks=masks, request_id=rid)


def constants() -> Dict[str, Any]:
    return {"timeout_secs": DISCOVERY_TIMEOUT_SECS,
            "request_prefix": DISCOVERY_REQUEST_PREFIX,
            "mask_fields": list(MASK_FIELDS),
            "discovery_statuses": [s.value for s in DiscoveryStatus],
            "mode_kinds": [k.value for k in ModeKind]}
