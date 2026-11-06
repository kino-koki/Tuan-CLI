"""审批覆盖层 —— 高危操作的卡片呈现与显式决策路由。

交互契约与组件分层借鉴自 **OpenAI Codex CLI** 的 TUI 审批覆盖层
(``codex-rs/tui/src/bottom_pane/approval_overlay.rs``, Apache-2.0)。
详见仓库根目录 ``THIRD_PARTY_NOTICES.md``。

**这不是 Rust 源码移植**。Codex TUI 是 Rust + ratatui + crossterm + tokio
(567 个 .rs / 24.7 万行)，本项目是纯 Python + prompt_toolkit/rich，跨语言
逐字复制既不可行，也会整体替换掉 Tuan 的 TUI 入口 —— 而权限策略注入、
确认通道、沙箱路由都挂在那个入口上，替换等于把已修好的侧门重新打开。
因此这里只**等价实现其交互契约与组件分层**，渲染落到 Tuan 现有卡片体系。

借鉴的四条契约 (来自 approval_overlay.rs 模块头与实现):

1. **选择总是发出显式决策事件** —— 没有"没输入 = 同意"，也没有静默的
   ``continue without info``。
2. **Esc / 取消永远映射为 Cancel** —— 即便有自定义键位，关闭对话框也
   不能变成"继续但缺信息"(Codex 对 MCP elicitation 特别保证这一点)。
   本模块里 ``ABORT`` 与 ``DENY`` 都是非授权结果，且中止优先。
3. **UI 层不判定安全性** —— 模块原文: "This module does not evaluate
   whether an action is safe to run; it only presents choices and routes
   user decisions." 安全裁决由 E1 策略库 / E7 的 ``confirm_apply`` 负责，
   本模块只把 ``DiffPreview`` / 权限域如实呈现并路由决策。
4. **作用域区分** —— Codex 有 ``Accept`` / ``AcceptForSession`` /
   ``PermissionsDecision::GrantForTurn`` / ``GrantForSession``；这里等价为
   ``ONCE`` / ``SESSION`` 两个通用作用域。具体持久化语义由调用方定义并
   **在卡片上明示**：E1 里 ONCE = 会话内临时授权(不写盘)、SESSION = 写盘
   持久化(跨重启, 作用域比 Codex 的 session 更宽)；E7 里两者都只影响本次
   apply，不扩展任何权限。

另外借鉴 ``list_selection_view`` 的选项列表与 ``popup_consts::
accept_cancel_hint_line`` 的 accept/cancel 提示行排版。
"""
from __future__ import annotations

import secrets
import sys
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# Codex 的 ApprovalRequest 有四种: Exec / Permissions / ApplyPatch /
# McpElicitation。这里保留同样的 kind 分类，新增 mcp_trust 对应 E1。
_REQUEST_KINDS = ("exec", "permissions", "file_change",
                  "mcp_elicitation", "mcp_trust")


class ApprovalDecision(str, Enum):
    """一次审批的显式决策事件。"""

    ONCE = "once"          # 仅本次 (Codex: Accept / GrantForTurn)
    SESSION = "session"    # 本会话 (Codex: AcceptForSession / GrantForSession)
    DENY = "deny"          # 明确拒绝
    ABORT = "abort"        # 中止 / Esc / Ctrl-C (Codex: Cancel -> Abort)
    RETRY = "retry"        # 无效输入, 由通道重问 (不视为批准, 也不视为拒绝)

    @property
    def granted(self) -> bool:
        return self in (ApprovalDecision.ONCE, ApprovalDecision.SESSION)


@dataclass(frozen=True)
class ApprovalOption:
    """一个可选项 (Codex: SelectionItem + ApprovalOption)。"""
    label: str
    decision: ApprovalDecision
    hint: str = ""          # 键位提示 (Codex: ShortcutHint)

    def to_dict(self) -> Dict[str, str]:
        return {"label": self.label, "decision": self.decision.value,
                "hint": self.hint}


@dataclass
class ApprovalRequest:
    """一条需要用户裁决的请求 (纯数据, 不含任何安全判定)。"""

    kind: str
    title: str
    body: str = ""
    options: List[ApprovalOption] = field(default_factory=list)
    expected_code: Optional[str] = None   # 高危: 必须精确键入该码
    sensitive: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in _REQUEST_KINDS:
            raise ValueError(f"未知审批类型: {self.kind}")
        if not self.options:
            self.options = [
                ApprovalOption("确认，仅本次", ApprovalDecision.ONCE, "y / 1"),
                ApprovalOption("确认，本会话不再询问", ApprovalDecision.SESSION, "s / 2"),
                ApprovalOption("拒绝", ApprovalDecision.DENY, "n / 3"),
                ApprovalOption("中止", ApprovalDecision.ABORT, "Esc"),
            ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind, "title": self.title, "body": self.body,
            "options": [o.to_dict() for o in self.options],
            "expected_code": self.expected_code,
            "sensitive": self.sensitive,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------- 渲染

def _disp_width(s: str) -> int:
    """显示宽度: CJK 全角按 2 列 (与 tui.py 的 _disp_width 同口径)。"""
    w = 0
    for ch in s:
        try:
            w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        except Exception:  # noqa: BLE001
            w += 1
    return w


def _wrap_dw(text: str, width: int) -> List[str]:
    if width <= 0:
        return [text]
    out: List[str] = []
    cur = ""
    for ch in text:
        cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if _disp_width(cur) + cw > width and cur:
            out.append(cur)
            cur = ""
        cur += ch
    out.append(cur)
    return out or [""]


def _clip_dw(text: str, width: int) -> str:
    if _disp_width(text) <= width:
        return text
    out = ""
    for ch in text:
        if _disp_width(out) + (2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1) > width:
            break
        out += ch
    return out + "…"


def _new_confirmation_code() -> str:
    """高危确认码: 6 位大写字母数字, 去掉易混淆字符。"""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


def render_approval_card(request: ApprovalRequest, width: int = 78) -> str:
    """把审批请求渲染成纯文本卡片 (Tuan 现有卡片同排版, 可独立测试)。

    结构对应 Codex 的 list-selection view + accept/cancel hint line:
    标题 -> 正文逐行折行 -> 编号选项 -> 键位提示行 -> 边框。
    """
    width = max(40, min(int(width), 200))
    inner = width - 2
    lines: List[str] = ["╭" + "─" * (width - 2) + "╮"]
    top = ("⚠ " if request.sensitive else "? ") + request.title
    if request.sensitive:
        top += "  [!敏感]"
    for seg in _wrap_dw(_clip_dw(top, inner - 4), inner - 4):
        lines.append("│  " + seg + " " * max(0, inner - 4 - _disp_width(seg)) + "  │")
    lines.append("│" + " " * inner + "│")

    for raw_line in str(request.body or "").split("\n"):
        for seg in _wrap_dw(raw_line, inner - 4):
            lines.append("│  " + seg + " " * max(0, inner - 4 - _disp_width(seg)) + "  │")

    if request.options:
        lines.append("│" + " " * inner + "│")
        for i, opt in enumerate(request.options, 1):
            hint = f" ({opt.hint})" if opt.hint else ""
            label = f"  {i}) {opt.label}{hint}"
            for j, seg in enumerate(_wrap_dw(_clip_dw(label, inner - 4), inner - 4)):
                prefix = seg if j == 0 else "   " + seg.lstrip()
                lines.append("│  " + prefix + " " * max(0, inner - 4 - _disp_width(prefix)) + "  │")

    # Codex: accept_cancel_hint_line —— "Press <accept> to ... or <cancel> to ..."
    hint_line = "Press y/1 to approve once  ·  s/2 for this session  ·  n/Esc to cancel"
    if request.expected_code:
        hint_line = (f"高危操作: 必须精确键入确认码 {request.expected_code} 才授权"
                     f"  ·  其它输入一律拒绝")
    for seg in _wrap_dw(hint_line, inner - 4):
        lines.append("│  " + seg + " " * max(0, inner - 4 - _disp_width(seg)) + "  │")
    lines.append("╰" + "─" * (width - 2) + "╯")
    return "\n".join(lines)


# ---------------------------------------------------------------- 决策解析
_ABORT_WORDS = frozenset({
    "", "esc", "escape", "\x1b", "q", "quit", "abort", "cancel",
    "取消", "中止", "退出", "ctrl-c", "\x03",
})
_DENY_WORDS = frozenset({"n", "no", "deny", "reject", "否", "拒绝", "3"})
_ONCE_WORDS = frozenset({"y", "yes", "ok", "approve", "是", "执行", "确认", "1"})
_SESSION_WORDS = frozenset({"s", "session", "2", "本会话", "会话"})


def resolve_decision(text: Optional[str],
                     request: ApprovalRequest) -> ApprovalDecision:
    """把用户输入解析成**显式**决策事件。fail-closed 是本函数的核心。

    - ``None`` / 空 / Esc / Ctrl-C  -> ``ABORT`` (Codex 契约 2: 关闭对话框
      绝不静默变成 continue)
    - 有 ``expected_code`` 时: 只有精确匹配才授权, ``y`` 不能绕过;
      不匹配 -> ``DENY`` (不是 RETRY, 防止无限试探)
    - 未知输入 -> ``RETRY`` (由通道重问; 绝不视为批准)
    """
    raw = ("" if text is None else str(text)).strip()
    low = raw.lower()

    # 中止优先于确认码: Esc 永远不能变成"继续"
    if low in _ABORT_WORDS or raw == "":
        return ApprovalDecision.ABORT

    if request.expected_code:
        if raw.upper() == str(request.expected_code).upper():
            # 确认码对应"仅本次", 不扩展到会话 (最小权限)
            return ApprovalDecision.ONCE
        return ApprovalDecision.DENY

    # 数字先映射到**本次请求的实际选项**: 自定义选项列表里 "2" 未必是
    # session 档, 关键词表不能盖掉调用方声明的决策。默认四选项里
    # 1->ONCE / 2->SESSION / 3->DENY / 4->ABORT, 与关键词表恰好一致。
    if raw.isdigit() and 1 <= int(raw) <= len(request.options):
        return request.options[int(raw) - 1].decision

    if low in _DENY_WORDS:
        return ApprovalDecision.DENY
    if low in _SESSION_WORDS:
        return ApprovalDecision.SESSION
    if low in _ONCE_WORDS:
        return ApprovalDecision.ONCE

    return ApprovalDecision.RETRY


def route_decision(request: ApprovalRequest,
                   decision: ApprovalDecision) -> Dict[str, Any]:
    """路由决策事件 —— **不做任何安全判定** (Codex 契约 3)。

    返回结构化事件供调用方 (E1 策略库 / E7 confirm_apply / 审计) 消费。
    本函数不改变任何策略、不写盘、不执行命令。
    """
    return {
        "kind": request.kind,
        "decision": decision.value,
        "granted": decision.granted,
        "scope": "session" if decision == ApprovalDecision.SESSION else "turn",
        "sensitive": request.sensitive,
        "metadata": dict(request.metadata),
    }


# ---------------------------------------------------------------- 请求构造

def build_file_change_request(preview: Dict[str, Any], *,
                              require_code: bool = True) -> ApprovalRequest:
    """E7: 从 ``DiffPreview.to_dict()`` 构造变更确认卡片。

    内容预览与敏感标记由 E7 后端提供, 本函数只负责呈现 —— 不判定
    "这段 diff 是否安全" (契约 3)。
    """
    entries = list(preview.get("entries") or [])
    body_lines: List[str] = [
        f"副本: {preview.get('copy', '')}",
        f"原始: {preview.get('original', '')}",
        f"变更文件: {preview.get('total', len(entries))} 个"
        + (f"  [!] 敏感文件 {preview.get('sensitive_count', 0)} 个"
           if preview.get("sensitive_count") else ""),
    ]
    if not entries:
        body_lines.append("(无变更)")
    for e in entries:
        flag = " [!敏感]" if e.get("sensitive") else ""
        body_lines.append(
            f"[{str(e.get('status', '')).upper()}] {e.get('path', '')}{flag} "
            f"({e.get('size_before', 0)} -> {e.get('size_after', 0)} bytes)")
        if e.get("binary"):
            body_lines.append("  (二进制文件, 不展示内容)")
        elif e.get("preview"):
            for ln in str(e["preview"]).splitlines()[:20]:
                body_lines.append("  | " + ln)
    return ApprovalRequest(
        kind="file_change",
        title="隔离副本变更确认 —— 确认后才会写回真实工作区",
        body="\n".join(body_lines),
        expected_code=_new_confirmation_code() if require_code else None,
        sensitive=bool(preview.get("sensitive_count")),
        metadata={"fingerprint": preview.get("fingerprint", ""),
                  "total": preview.get("total", len(entries))},
    )


def build_mcp_trust_request(server: str, tier: str, *,
                            tool_allowlist: Sequence[str] = (),
                            tool_denylist: Sequence[str] = (),
                            allowed_domains: Sequence[str] = (),
                            read_only: bool = True,
                            require_code: bool = False) -> ApprovalRequest:
    """E1: 构造 MCP server 信任授予卡片 (权限域必须完整可见)。"""
    body = "\n".join([
        f"server: {server}",
        f"信任等级: {tier}",
        f"read_only: {read_only}",
        f"tool_allowlist: {', '.join(tool_allowlist) or '(空 — 仅按档位默认)'}",
        f"tool_denylist: {', '.join(tool_denylist) or '(空)'}",
        f"allowed_domains: {', '.join(allowed_domains) or '(不限制)'}",
        "",
        "未登记 server 默认 untrusted; 授予后该 server 才可按上述权限域调用。",
        "选择「本会话」只做临时授权, 不写盘; 选择「仅本次」同样不持久化。",
    ])
    return ApprovalRequest(
        kind="mcp_trust",
        title=f"授予 MCP server 信任等级: {server}",
        body=body,
        options=[
            ApprovalOption("仅本会话临时授权 (不写盘, 进程结束失效)",
                           ApprovalDecision.ONCE, "y / 1"),
            ApprovalOption("授予并持久化 (写盘, 跨重启生效, 作用域更宽)",
                           ApprovalDecision.SESSION, "s / 2"),
            ApprovalOption("拒绝, 保持 untrusted", ApprovalDecision.DENY, "n / 3"),
            ApprovalOption("中止", ApprovalDecision.ABORT, "Esc"),
        ],
        expected_code=_new_confirmation_code() if require_code else None,
        metadata={"server": server, "tier": tier},
    )


# ---------------------------------------------------------------- 通道

@dataclass
class ApprovalResult:
    request: ApprovalRequest
    decision: ApprovalDecision
    event: Dict[str, Any]

    @property
    def granted(self) -> bool:
        return self.decision.granted

    def to_dict(self) -> Dict[str, Any]:
        return {"request": self.request.to_dict(),
                "decision": self.decision.value, "event": self.event}


def run_approval(request: ApprovalRequest,
                 read_line: Callable[[str], Optional[str]],
                 *, max_attempts: int = 3) -> ApprovalResult:
    """跑一次审批: 渲染 -> 读取输入 -> 解析 -> 路由。

    ``read_line`` 收到渲染后的卡片文本, 返回一行输入 (None = 通道不可用)。
    无效输入重问, 超过 ``max_attempts`` 后按 DENY 收尾 (fail-closed)。
    """
    text = render_approval_card(request)
    decision = ApprovalDecision.ABORT
    for _ in range(max(1, int(max_attempts))):
        raw = read_line(text)
        if raw is None:              # stdin 不可用 / 通道断开 -> 中止
            decision = ApprovalDecision.ABORT
            break
        decision = resolve_decision(raw, request)
        if decision != ApprovalDecision.RETRY:
            break
    else:
        decision = ApprovalDecision.DENY
    return ApprovalResult(request, decision,
                          route_decision(request, decision))


def stdin_read_line(prompt: str) -> Optional[str]:
    """headless 默认输入通道: 打印卡片 + 读一行。

    stdin 不可用 / EOF / 任何异常 -> 返回 None (调用方按 ABORT = 拒绝处理)。
    """
    try:
        # 非交互 stdin 时连卡片都不打印: 没有可读通道就不制造"看起来在等确认"
        # 的假象, 直接返回 None -> ABORT (fail-closed)。
        if not sys.stdin or not sys.stdin.isatty():
            return None
        print(prompt, flush=True)
        return sys.stdin.readline()
    except Exception:  # noqa: BLE001
        return None


def headless_approval(request: ApprovalRequest) -> ApprovalResult:
    """无 TUI 时的默认审批通道 (显式确认码 + stdin)。"""
    return run_approval(request, stdin_read_line)


def make_confirm_callable(ctx: Any) -> Tuple[Callable[[Dict[str, Any]], str],
                                             Callable[[str], bool]]:
    """为 E7 的 ``confirm_apply`` 造 ``(renderer, confirm_fn)``。

    - ``renderer(preview_dict)`` 把 DiffPreview 渲染成 Codex 风格卡片文本;
    - ``confirm_fn(text)`` 优先走 ``ctx.confirm`` (现有 TUI 挂起式卡片通道),
      缺失时退到 headless: 打印卡片 + 要求精确键入确认码, stdin 不可用即拒绝。

    两条路径的卡片**内容不同且如实**: TUI 路径不显示确认码提示 (它走 y/n,
    由 ``_resolve_confirm`` 解析, ``cancel_confirm`` / 应用退出一律按拒绝);
    headless 路径强制精确确认码。避免"卡片写着必须输入确认码、实际按 y 就放行"
    这种文档说谎。

    **不改变** ``confirm_apply`` 的 fail-closed 契约: 任何非显式授权输入、
    通道异常、应用退出都返回 False。上一轮「无 confirm 通道直接失败」的
    headless 缺口在这里补上 —— 不是放宽, 而是提供一个同样要求显式决策的
    默认通道。
    """
    pending: Dict[str, ApprovalRequest] = {}

    def renderer(preview: Dict[str, Any]) -> str:
        has_ui = callable(getattr(ctx, "confirm", None))
        req = build_file_change_request(preview, require_code=not has_ui)
        pending["req"] = req
        return render_approval_card(req)

    def confirm_fn(text: str) -> bool:
        req = pending.get("req")
        if req is None:
            return False
        if req.expected_code is None:
            # TUI 通道: 卡片文本已含全部变更与敏感高亮
            ui_confirm = getattr(ctx, "confirm", None)
            if not callable(ui_confirm):
                return False
            try:
                return bool(ui_confirm(text))
            except Exception:  # noqa: BLE001
                return False
        # headless: 重新渲染 (确定性) 并打印, 要求精确键入确认码
        return run_approval(req, stdin_read_line).granted

    return renderer, confirm_fn
