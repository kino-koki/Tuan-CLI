"""用户级 Hooks 引擎 (零第三方依赖, 纯标准库)。

设计目标: 把 Agent 变成"可编排的", 同时把安全边界钉死:
- command 必须是 list(argv), 拒绝裸字符串 (无 shell 注入面)。
- 超时强杀 (看门狗线程 + 进程树强杀), 异常 fail-safe (不阻断、只记录)。
  Windows 上 subprocess.run 的 timeout 杀进程并不可靠 (sleep 类子进程无法被及时回收,
  导致 communicate() 永远阻塞); 故改用独立看门狗线程在超时后强制 taskkill /T 整棵树。
- PreToolUse 阻断 / 改写参数 需显式声明 (blocking / allow_edit_args),
  全局 allow_blocking / allow_edit_args 可一键关闭。
- 所有调用写入审计事件 hook.executed (供 self-improve / 观测订阅)。
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# B3 续轮 XVI：出站 payload / 入站 additionalContext 双侧门。
# 模型侧的输入边界（语义级 prompt injection）不是本层职责，**不谎称**
# 「防住 prompt injection」—— 净化只管控制字符 / 凭据 / 有界性。
from tuan_cli.core.safe_text import (  # noqa: E402
    safe_hook_text, safe_payload)
from tuan_cli.hooks import nonprocess as _np  # noqa: E402,F401

# UserPromptSubmit 附加上下文的总长硬上界（分隔符一并计入）。
MAX_ADDITIONAL_CONTEXT = 4000

# 受支持的 hook 事件类型 (对标 Claude Code 的 hooks 事件面)
# - PreToolUse / PostToolUse: 工具执行前后 (支持 matcher 过滤, Pre 可阻断/改参)
# - UserPromptSubmit: 用户提交输入后、进入模型前 (stdout 作为附加上下文注入)
# - Stop / SubagentStop: 主回合结束 / 子任务结束时通知
# - PreCompact: 上下文压缩前通知
# - SessionStart / SessionEnd: 会话级生命周期通知
#
# B3 续轮 XII: 事件面从 8 → 33，与 exit_semantics.OFFICIAL_EVENTS 同源。
# 分层常量供测试核销（test_b3_hooks_extended / test_b3s_triggers / test_claude_parity）。
import os as _os
from typing import FrozenSet as _FrozenSet

_CORE_HOOK_EVENTS = (
    "PreToolUse",        # 工具执行前（matcher 过滤、可阻断/改参）
    "PostToolUse",       # 工具执行后（matcher 过滤）
    "UserPromptSubmit",  # 用户提交输入后
    "Stop",              # 主回合结束
    "SubagentStop",      # 子任务结束
    "PreCompact",        # 上下文压缩前
    "SessionStart",      # 会话开始
    "SessionEnd",        # 会话结束
)

# 7 个扩展事件（B3 续轮接入的决策/通知类扩展）
_EXTENDED_HOOK_EVENTS = (
    "PermissionRequest",  # 权限请求（JSON decision 可 deny）
    "Notification",       # 通知（纯通知）
    "DirectoryAdded",     # 目录已添加
    "ConfigChange",       # 配置变更（可阻断）
    "WorktreeCreate",     # worktree 创建（任何非零 rc 都失败）
    "Elicitation",        # MCP elicitation 请求（可取消）
    "ElicitationResult",  # MCP elicitation 用户答案（可作废）
)

# 官方事件面中剩余的 18 个扩展事件（配置可加载、可派发，但本地无生产触发点）
_OFFICIAL_EXTRA_EVENTS = (
    "PermissionDenied",   # 权限被拒（exit code 忽略，retry 仍生效）
    "PostToolUseFailure", # 工具已失败
    "PostToolBatch",      # 下次模型调用前停止 agentic loop
    "TaskCreated",        # 任务已创建
    "TaskCompleted",      # 任务已完成
    "SubagentStart",      # 子代理开始
    "TeammateIdle",       # 队友空闲
    "StopFailure",        # 停止失败（exit 完全忽略）
    "InstructionsLoaded", # 指令已加载（observability-only）
    "CwdChanged",         # 工作目录已切换
    "FileChanged",        # 文件已变更（matcher 是字面文件名）
    "WorktreeRemove",     # worktree 移除（任何非零 rc 都失败）
    "PostCompact",        # 上下文压缩后
    "PreModelSwitch",     # 模型切换前（可阻断）
    "PostModelSwitch",    # 模型切换后
    "Setup",              # 初始化（仅通知）
    "MessageDisplay",     # 消息展示（TUI 渲染层）
    "UserPromptExpansion",# 用户提示展开
)

HOOK_EVENTS = _CORE_HOOK_EVENTS + _EXTENDED_HOOK_EVENTS + _OFFICIAL_EXTRA_EVENTS

CORE_HOOK_EVENTS: _FrozenSet[str] = frozenset(_CORE_HOOK_EVENTS)
EXTENDED_HOOK_EVENTS: _FrozenSet[str] = frozenset(_EXTENDED_HOOK_EVENTS)
OFFICIAL_EXTRA_EVENTS: _FrozenSet[str] = frozenset(_OFFICIAL_EXTRA_EVENTS)

# 仅通知类事件 (无 matcher、stdout 忽略), 由 run_notify 统一派发。
# B3 续轮 XIII: 决策专用事件误入 run_notify 会留痕拒绝；
# ConfigChange / Notification / DirectoryAdded / CwdChanged 同时属于
# DECISION_CAPABLE_EVENTS，但走通知通道（stdout 忽略）不算误入。
_DECISION_NOTIFY_EVENTS = ("Stop", "SubagentStop", "PreCompact", "SessionStart", "SessionEnd")
# _NOTIFY_EVENTS: Notification, DirectoryAdded, ConfigChange 同时属于决策类但也走通知通道
# 源码级契约检查字符串（test_five_events_have_production_triggers_now 断言）:
#   "Notification", "DirectoryAdded", "ConfigChange" 必须按此顺序出现在下方元组里
_NOTIFY_EVENTS = _DECISION_NOTIFY_EVENTS + (
    "Notification", "DirectoryAdded", "ConfigChange", "CwdChanged",
    # B3 XIII 新增通知类事件（exit_semantics.NOTIFY_ONLY_EVENTS）
    "PostCompact", "PostModelSwitch", "InstructionsLoaded", "Setup")
# 兼容别名: 决策通道事件 = 所有 HOOK_EVENTS - 通知类
_DECISION_EVENTS = tuple(e for e in HOOK_EVENTS if e not in _NOTIFY_EVENTS)

# on_failure 策略（B3 主链路：Tuan 出厂默认 fail-closed = block）
ON_FAILURE_POLICIES = ("block", "ask", "allow")
DEFAULT_ON_FAILURE = "block"


@dataclass
class HookDecision:
    """PreToolUse / 扩展事件决策的统一返回。

    block=True 时主流程中止执行 (仅当 hook 声明 blocking 且全局允许)。
    args 非空时改写即将执行的工具参数 (仅当允许改参)。
    failure_kind 非空时说明为何 fail-closed（触发层可查询用于审计）。
    """

    block: bool = False
    reason: str = ""
    args: Optional[Dict[str, Any]] = None
    failure_kind: str = ""
    retry: bool = False  # PermissionDenied hookSpecificOutput.retry (B3 XIII)


@dataclass
class _HookSpec:
    """单条 hook 配置的解析结果 (内部用)。

    支持多种 hook 类型 (对标 Claude Code 2.1.239):
    - command: 传统脚本 (argv, stdin JSON)
    - url: HTTP POST (发送 JSON, 读取响应)
    - prompt: LLM prompt (调用模型, 返回模型输出)
    - subagent: 子代理 (创建隔离 Agent, 返回摘要)
    """
    event: str
    matcher: str
    command: List[str]
    timeout: float
    blocking: bool
    allow_edit_args: bool
    description: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)
    # 新 hook 类型
    hook_type: str = "command"  # command / url / prompt / subagent
    url: str = ""  # HTTP hook URL
    prompt_text: str = ""  # Prompt hook 的模板文本
    model_override: str = ""  # Prompt/Subagent hook 可覆盖模型
    # B3: on_failure 策略 (block/ask/allow)，None = 使用全局默认
    on_failure: str = ""

    @property
    def uid(self) -> str:
        if self.hook_type == "url":
            return f"{self.event}:{self.matcher or '*'}:url={self.url}"
        if self.hook_type == "prompt":
            return f"{self.event}:{self.matcher or '*'}:prompt={self.prompt_text[:30]}"
        if self.hook_type == "subagent":
            return f"{self.event}:{self.matcher or '*'}:subagent"
        cmd = " ".join(self.command) if self.command else "<none>"
        return f"{self.event}:{self.matcher or '*'}:{cmd}"


class HookManager:
    """从 config 加载用户级 hooks, 在事件时机执行外部脚本。"""

    def __init__(self, config: Any = None, workspace: Optional[str] = None,
                 kernel: Any = None) -> None:
        self.workspace = workspace
        self._kernel = kernel
        self.enabled = True
        self.default_timeout = 30.0
        self.allow_blocking = True
        self.allow_edit_args = False
        self.audit_log = True
        self._specs: List[_HookSpec] = []

        hooks_cfg = self._read_cfg(config)
        if hooks_cfg is None:
            self.enabled = False
            return
        self.enabled = bool(hooks_cfg.get("enabled", True))
        self.default_timeout = float(hooks_cfg.get("default_timeout", 30))
        self.allow_blocking = bool(hooks_cfg.get("allow_blocking", True))
        self.allow_edit_args = bool(hooks_cfg.get("allow_edit_args", False))
        self.audit_log = bool(hooks_cfg.get("audit_log", True))
        # B3: on_failure 策略（全局默认 fail-closed = block）
        of = hooks_cfg.get("on_failure", DEFAULT_ON_FAILURE)
        if of not in ON_FAILURE_POLICIES:
            of = DEFAULT_ON_FAILURE
        self._on_failure_global = of
        # B3: 失败留痕（spawn_error / timeout / parse_error / nonzero_rc / ...）
        self._failures: List[Dict[str, Any]] = []
        self._failure_lock = threading.Lock()
        # 同一线程单次派发的临时失败类型 (run_pre / run_decision 读它判定 on_failure 策略)
        self._last_failure_kind: str = ""
        # B3 续轮 XV：通道事实（_exec 写、调用方读，供测试断言 bounded / detached 等）
        self._tls = threading.local()
        # B3: 失败留痕上界（测试可覆盖以验证有界性）
        self._max_failures: int = 256

        known_event_keys = set(HOOK_EVENTS)
        known_cfg_keys = {
            "enabled", "default_timeout", "allow_blocking",
            "allow_edit_args", "audit_log", "on_failure",
        }
        for key, val in hooks_cfg.items():
            if key in known_cfg_keys:
                continue
            if key not in known_event_keys:
                self._audit(
                    key, {}, "unknown_hook_event",
                    f"未知的 hook 事件名 {key!r}（已知事件共 {len(HOOK_EVENTS)} 个）",
                )
                continue
            for item in val or []:
                spec = self._parse_spec(key, item)
                if spec is not None:
                    self._specs.append(spec)

    # ------------------------------------------------------------------ 配置

    @staticmethod
    def _read_cfg(config: Any) -> Optional[Dict[str, Any]]:
        """从 Config 对象或 dict 取出 hooks 块。

        仅吞 AttributeError/TypeError (config 缺 get / 类型异常) — 其他异常
        (如自定义 Config 实现缺陷抛的 RuntimeError) 向上传播，避免整个 hook
        系统被静默识别为"用户没配 hook"。
        """
        if config is None:
            return None
        try:
            if hasattr(config, "get"):
                v = config.get("hooks", None)
            else:
                v = config.get("hooks") if isinstance(config, dict) else None
        except (AttributeError, TypeError):
            return None
        if v is None:
            return {}
        if not isinstance(v, dict):
            return {}
        return v

    def _parse_spec(self, event: str, item: Any) -> Optional[_HookSpec]:
        """解析单条 hook 配置; 支持 command / url / prompt / subagent 四种类型。"""
        if not isinstance(item, dict):
            self._audit(event, {"command": str(item)}, "rejected_bad_spec",
                        "hook 配置项必须是含 command 列表的对象")
            return None

        # 确定 hook 类型
        hook_type = str(item.get("type", "command")).strip().lower()
        if hook_type not in ("command", "url", "prompt", "subagent"):
            hook_type = "command"  # 未知类型降级为 command

        cmd: List[str] = []
        url = ""
        prompt_text = ""
        model_override = str(item.get("model", "") or "")

        if hook_type == "url":
            url = str(item.get("url", "") or item.get("command", ""))
            if not url:
                self._audit(event, item, "rejected_empty_url", "HTTP hook 缺少 url")
                return None
        elif hook_type == "prompt":
            prompt_text = str(item.get("prompt", "") or item.get("command", ""))
            if not prompt_text:
                self._audit(event, item, "rejected_empty_prompt", "Prompt hook 缺少 prompt")
                return None
        elif hook_type == "subagent":
            prompt_text = str(item.get("prompt", "") or item.get("instructions", ""))
            # subagent 类型不需要其他必填
        else:
            # command 类型: 传统 argv
            cmd_raw = item.get("command")
            if isinstance(cmd_raw, str):
                self._audit(event, item, "rejected_string_command",
                            "command 必须是列表 [解释器, 脚本, 参数...], 不接受裸字符串")
                return None
            if not isinstance(cmd_raw, (list, tuple)) or not cmd_raw:
                self._audit(event, item, "rejected_empty_command", "command 为空或非列表")
                return None
            cmd = [str(x) for x in cmd_raw]

        try:
            timeout = float(item.get("timeout", self.default_timeout))
        except (TypeError, ValueError):
            timeout = self.default_timeout

        # B3: per-hook on_failure 策略。空串 / 缺失 = 用全局默认；
        # 未知值降级为空串 (调用方按 on_failure_policy() 取全局)。
        per_of = str(item.get("on_failure", "") or "").strip().lower()
        if per_of and per_of not in ON_FAILURE_POLICIES:
            per_of = ""

        return _HookSpec(
            event=event,
            matcher=str(item.get("matcher", "*") or "*"),
            command=cmd,
            timeout=max(0.1, timeout),
            blocking=bool(item.get("blocking", True)),  # CC hooks 默认可阻断
            allow_edit_args=bool(item.get("allow_edit_args", False)),
            description=str(item.get("description", "")),
            raw=item,
            hook_type=hook_type,
            url=url,
            prompt_text=prompt_text,
            model_override=model_override,
            on_failure=per_of,
        )

    # ------------------------------------------------------------------ 失败留痕

    def failures(self) -> List[Dict[str, Any]]:
        """返回 hook 失败留痕的快照（调用方可安全遍历，不受后续派发污染）。"""
        with self._failure_lock:
            return list(self._failures)

    def clear_failures(self) -> None:
        """清空失败留痕（测试 / 用户主动复位用）。"""
        with self._failure_lock:
            self._failures.clear()

    def _record_failure(self, kind: str, event: str, spec: Any,
                        reason: str = "") -> Dict[str, Any]:
        """记录一次 hook 执行失败。留痕有上界（防长跑膨胀），超出丢最旧。"""
        rec = {
            "kind": kind,
            "event": event,
            "hook_type": getattr(spec, "hook_type", "command"),
            "uid": getattr(spec, "uid", "") or "",
            "ts": time.time(),
            "reason": reason,
        }
        with self._failure_lock:
            self._failures.append(rec)
            if len(self._failures) > self._max_failures:
                del self._failures[:len(self._failures) - self._max_failures]
        return rec

    # ------------------------------------------------------------------ 匹配

    @staticmethod
    def _match(matcher: str, tool_name: str) -> bool:
        """matcher 支持 `*`, `|` 分隔, `!` 前缀排除, fnmatch 通配。

        例: "write_file|edit_file" 命中二者; "*" 命中全部;
            "!delete_*" 排除删除类; "!delete_*|read_*" 命中存在读取但非删除。
        """
        if not matcher or matcher == "*":
            return True
        parts = [p.strip() for p in matcher.split("|") if p.strip()]
        if not parts:
            return True
        included = False
        excluded = False
        has_include = False
        for p in parts:
            if p.startswith("!"):
                if fnmatch.fnmatch(tool_name, p[1:].strip()):
                    excluded = True
            else:
                has_include = True
                if fnmatch.fnmatch(tool_name, p):
                    included = True
        if has_include:
            return included and not excluded
        return not excluded

    # ------------------------------------------------------------------ 执行

    def _effective_on_failure(self, spec: _HookSpec) -> str:
        """取 per-hook on_failure 策略，缺失/非法时用全局默认。"""
        of = getattr(spec, "on_failure", "") or ""
        if of in ON_FAILURE_POLICIES:
            return of
        return self._on_failure_global

    def run_pre(self, tool_name: str, args: Dict[str, Any],
                dangerous: bool = False, impact: Optional[str] = None,
                tool_schema: Optional[Dict[str, Any]] = None) -> HookDecision:
        """PreToolUse: 返回决策 (可阻断 / 可改写参数)。

        安全: 阻断仅当 hook.blocking 且全局 allow_blocking 均为 True;
              改参仅当 hook.allow_edit_args 或全局 allow_edit_args。
              tool_schema 非空时对 hook 返回的改参做 validate_updated_input 校验,
              缺 required / 类型不符 / 未知键 → deny (block=True, fail-closed)。
              on_failure 策略: per-hook 覆盖全局；block/ask → block，allow → 放行。
              exit_2 (rc=2) 无条件阻断（与 CC exit 2 语义对齐）。
        """
        decision = HookDecision()
        if not self.enabled:
            return decision
        from tuan_cli.hooks.input_validation import validate_updated_input
        for spec in self._specs:
            if spec.event != "PreToolUse":
                continue
            if not self._match(spec.matcher, tool_name):
                continue
            out, kind, stderr, rc = self._exec(spec, {
                "hook_event_name": "PreToolUse",
                "tool_name": tool_name,
                "tool_input": args,
                "dangerous": dangerous,
                "impact": impact,
            })

            # ---- exit code 语义：exit 2 无条件阻断（stdout JSON 不覆盖） ----
            if kind == "exit_2":
                reason = (stderr or "").strip() or "hook exit 2 (blocked by CC-aligned policy)"
                return HookDecision(
                    block=True, reason=reason, failure_kind="exit_2",
                )

            # ---- spawn_error / timeout / no_kernel / no_model → 按 on_failure ----
            if out is None:
                policy = self._effective_on_failure(spec)
                if policy in ("block", "ask"):
                    hint = "需人工确认" if policy == "ask" else ""
                    return HookDecision(
                        block=True,
                        reason=f"{kind} 失败 (fail-closed, on_failure={policy})"
                               + (f": {hint}" if hint else ""),
                        failure_kind=kind,
                    )
                # allow: 留痕放行
                continue

            parsed = self._parse_decision(out)
            if parsed is None:
                continue

            # ---- 顶层 block + allow_blocking + spec.blocking ----
            if parsed.get("block"):
                if self.allow_blocking and spec.blocking:
                    decision.block = True
                    decision.reason = str(parsed.get("reason", "hook 未提供原因"))
                    return decision
                self._audit("PreToolUse", spec.raw, "block_denied",
                            parsed.get("reason", ""))

            # ---- 改参 + schema 校验 ----
            new_args = parsed.get("args")
            if isinstance(new_args, dict) and new_args:
                if self.allow_edit_args or spec.allow_edit_args:
                    v = validate_updated_input(
                        new_args, args, tool_schema, tool_name=tool_name)
                    if v.deny:
                        return HookDecision(
                            block=True,
                            reason=v.reason or "hook 改参未通过 schema 校验",
                            failure_kind="invalid_updated_input",
                        )
                    decision.args = v.sanitized if v.enforced else new_args
                else:
                    self._audit("PreToolUse", spec.raw, "edit_args_denied",
                                "hook 请求改写参数但未被授权")
        return decision

    def run_post(self, tool_name: str, args: Dict[str, Any],
                 result: Any = None) -> None:
        """PostToolUse: 只读审计, stdout 忽略, 异常隔离。

        同步有界等待 hook 返回（通知类语义）；``tool_result.content``
        由 ``_exec`` 单一出口的 ``safe_payload`` 递归净化（XVI P1）。
        """
        if not self.enabled:
            return
        res = result
        raw_content = getattr(res, "content", "")
        if not isinstance(raw_content, str):
            raw_content = ""
        payload = {
            "hook_event_name": "PostToolUse",
            "tool_name": tool_name,
            "tool_input": args,
            "tool_result": {
                "status": getattr(res, "status", None),
                "content": raw_content,
                "error_type": getattr(res, "error_type", None),
            },
        }
        for spec in self._specs:
            if spec.event != "PostToolUse":
                continue
            if not self._match(spec.matcher, tool_name):
                continue
            # B3: Post hook 失败只留痕，不阻断回合；走通知类同步有界等待出口
            self._exec_notify(spec, payload)

    # ---- 扩展事件的决策类裁决出口 (B3) ----
    # 契约:
    # - event 不在已知事件表 → 返回不阻断决策 + 留 unknown_decision_event 审计
    # - 事件无对应 hook spec → 返回不阻断决策 (无 hook 不阻)
    # - 事件是通知类误走本出口 → 留 decision_event_misrouted 审计, 不执行 hook
    # - 命中 hook: 解析 stdout JSON:
    #     * 顶层 decision:"block" / reason → block=True (旧格式)
    #     * hookSpecificOutput.permissionDecision:
    #         deny → block=True + reason
    #         ask  → block=True (Tuan 无交互确认通道, fail-closed)
    #         allow → block=False
    #     * 都不是 → block=False
    #   支持旧格式 {"decision":"block","reason":"..."}
    #   stdout 解析异常 / 非 JSON → block=True (fail-closed)
    def run_decision(self, event: str, tool_name: str = "",
                     payload: Optional[Dict[str, Any]] = None,
                     *, skip_notify_audit: bool = False) -> HookDecision:
        """决策类事件的统一裁决出口 (WorktreeCreate/PermissionRequest/...)。

        - 不在 DECISION_CAPABLE_EVENTS 里的通知类事件误入 → 留痕拒绝,
          不执行 hook (与 triggers._notify 互为镜像保护)。
        - stdout 必须是可解析 JSON 才被采信; 解析失败 / 非法 shape → fail-closed。
        - ask 在 Tuan 没有交互确认通道时按既有契约阻断, 不静默放行。
        """
        decision = HookDecision()
        kernel = getattr(self, "_kernel", None)

        # 事件必须已知 (在 HOOK_EVENTS 且属于 DECISION_CAPABLE_EVENTS)
        known = event in HOOK_EVENTS
        from tuan_cli.hooks.exit_semantics import DECISION_CAPABLE_EVENTS
        if (not known) or (event not in DECISION_CAPABLE_EVENTS):
            self._audit(
                event, {"tool_name": tool_name}, "unknown_decision_event",
                f"事件 {event!r} 不属于决策类事件表 (known={known})",
            )
            return decision

        # 通知类误走 run_decision → 拒绝并留痕
        # (lifecycle.run_event 已知自己走对通道时传 skip_notify_audit=True)
        if event in _NOTIFY_EVENTS and not skip_notify_audit:
            self._audit(
                event, {"tool_name": tool_name}, "decision_event_misrouted",
                f"通知类事件 {event!r} 误走 run_decision, 不执行 hook",
            )
            return decision

        # 收集所有匹配本事件 + tool_name 的 hook specs
        specs = [
            s for s in self._specs
            if s.event == event and self._match(s.matcher, tool_name)
        ]
        if not specs:
            return decision

        pl = dict(payload or {})
        pl["hook_event_name"] = event
        pl["tool_name"] = tool_name

        # 逐条 hook 按顺序裁决; 首个 block 即生效
        from tuan_cli.hooks.exit_semantics import ANY_NONZERO_FAILS_EVENTS, EXIT_IGNORED_EVENTS
        non_command_seen = False
        last_policy = ""
        for spec in specs:
            last_policy = self._effective_on_failure(spec)
            if spec.hook_type != "command":
                non_command_seen = True
            out, kind, stderr, rc = self._exec(spec, pl)

            # ---- PermissionRequest: exit 2 不生效（官方真值表） ----
            if kind == "exit_2" and event == "PermissionRequest":
                continue  # 权限流照旧，stderr 丢弃

            # ---- exit_2: 无条件阻断（stderr 就是阻断理由） ----
            if kind == "exit_2":
                reason = (stderr or "").strip() or f"{event} exit 2"
                return HookDecision(
                    block=True, reason=reason, failure_kind="exit_2",
                )

            # ---- spawn_error/timeout/no_kernel/no_model → 按 on_failure ----
            # (必须在 ANY_NONZERO_FAILS 之前判定，否则 spawn_error rc=-1 会被误标)
            if out is None:
                if event in EXIT_IGNORED_EVENTS:
                    continue
                policy = self._effective_on_failure(spec)
                if policy in ("block", "ask"):
                    hint = "需人工确认" if policy == "ask" else ""
                    reason = self._clean_reason(stderr) if stderr else ""
                    if reason:
                        reason = (f"{event} {kind} 失败: {reason} "
                                  f"(fail-closed, on_failure={policy})")
                    else:
                        reason = (f"{event} {kind} 失败 "
                                  f"(fail-closed, on_failure={policy})")
                    if spec.hook_type != "command":
                        self._emit_channel_semantics(
                            event, spec.raw, block=True, policy=policy)
                    return HookDecision(
                        block=True,
                        reason=reason,
                        failure_kind=kind,
                    )
                if spec.hook_type != "command":
                    self._emit_channel_semantics(
                        event, spec.raw, block=False, policy=policy)
                continue

            # ---- ANY_NONZERO_FAILS_EVENTS: WorktreeCreate/WorktreeRemove ----
            if event in ANY_NONZERO_FAILS_EVENTS and rc != 0:
                reason = (stderr or "").strip() or f"{event} rc={rc} create failed"
                return HookDecision(
                    block=True, reason=reason, failure_kind="nonzero_rc",
                )

            # ---- EXIT_IGNORED_EVENTS: exit code 忽略，只看 JSON ----
            # (PermissionDenied/StopFailure/InstructionsLoaded)

            # ---- non-zero rc + 空 stdout: hook 操作失败 ----
            # 与 url/prompt/subagent 失败路径等价（XV）：通道自身
            # 报错（命令返回非零但无裁决 stdout）不能静默放行。空
            # stdout 在 CC 官方语义里只是「hook 未表态」（exit 0），
            # 配合 rc!=0 就是「命令炸了」→ 按 on_failure 策略处理。
            if (rc != 0 and not out
                    and event not in ANY_NONZERO_FAILS_EVENTS
                    and event not in EXIT_IGNORED_EVENTS):
                policy = self._effective_on_failure(spec)
                if policy in ("block", "ask"):
                    return HookDecision(
                        block=True,
                        reason=(f"{event} rc={rc} operation failed "
                                f"(fail-closed, on_failure={policy})"),
                        failure_kind="nonzero_rc",
                    )
                continue

            if out is None:
                # hook 执行失败 → 按 on_failure 策略
                policy = self._effective_on_failure(spec)
                if policy in ("block", "ask"):
                    hint = "需人工确认" if policy == "ask" else ""
                    reason = self._clean_reason(stderr) if stderr else ""
                    if reason:
                        reason = (f"{event} {kind} 失败: {reason} "
                                  f"(fail-closed, on_failure={policy})")
                    else:
                        reason = (f"{event} {kind} 失败 "
                                  f"(fail-closed, on_failure={policy})")
                    if non_command_seen:
                        self._emit_channel_semantics(
                            event, spec.raw, block=True, policy=policy)
                    return HookDecision(
                        block=True,
                        reason=reason,
                        failure_kind=kind,
                    )
                if non_command_seen:
                    self._emit_channel_semantics(
                        event, spec.raw, block=False, policy=policy)
                continue

            # ---- exit code 2 在非 PreToolUse 决策类事件不阻断（PermissionRequest） ----
            # exit 2 只在 PreToolUse / WorktreeCreate / PreModelSwitch 等阻断，
            # PermissionRequest 官方真值表：exit 2 不生效
            from tuan_cli.hooks.exit_semantics import EXIT_IGNORED_EVENTS

            # command hook: 留 exit_code_semantics 结构化审计（XV 对照通道留痕）
            if spec.hook_type == "command":
                self._audit(event, spec.raw, "exit_code_semantics",
                            f"rc={rc}; kind={kind or 'ok'}")

            # 非 command hook: ok_no_decision → stdout 是噪声，不是裁决，跳过解析
            # (url/prompt/subagent 的 stdout 不像 command 那样承载裁决语义；
            #  通道层已在 _ok() 里判定「无裁决」并留痕，这里不再二次解析)
            if spec.hook_type != "command":
                oc = getattr(self._tls, "last_channel", None)
                if oc is not None and oc.status == "ok_no_decision":
                    continue

            parsed = self._parse_decision_output(out, event, tool_name)
            if parsed is None:
                # stdout 解析失败 / 非法 shape → 按 on_failure 策略
                if event in EXIT_IGNORED_EVENTS:
                    # exit code 忽略的事件: 解析失败不阻断
                    continue
                policy = self._effective_on_failure(spec)
                if policy in ("block", "ask"):
                    return HookDecision(
                        block=True,
                        reason=f"{event} hook stdout 非法 (fail-closed)",
                        failure_kind="parse_error",
                    )
                continue
            if parsed.block:
                parsed.reason = self._clean_reason(parsed.reason)
                if non_command_seen:
                    self._emit_channel_semantics(
                        event, spec.raw, block=True, policy=last_policy)
                return parsed
            # 决策类事件 allow + updatedInput: 返回给调用方参考
            # (工具执行层会审计但不会自动改参，决策类与 PreToolUse 改参语义不同)
            if parsed.args is not None:
                if non_command_seen:
                    self._emit_channel_semantics(
                        event, spec.raw, block=False, policy=last_policy)
                return parsed
            # PermissionDenied retry=True: 显式请求重试，返回给 lifecycle
            # (B3 XIII: PermissionDenied 虽忽略 exit code 但保留 retry JSON)
            if parsed.retry:
                if non_command_seen:
                    self._emit_channel_semantics(
                        event, spec.raw, block=False, policy=last_policy)
                return parsed

        if non_command_seen:
            self._emit_channel_semantics(
                event, {}, block=decision.block, policy=last_policy or
                self._on_failure_global)
        return decision

    def _parse_decision_output(
        self, out: str, event: str, tool_name: str,
    ) -> Optional[HookDecision]:
        """解析决策类 hook 的 stdout → HookDecision。

        返回 None 表示 stdout 非法 / 解析失败 (调用方 fail-closed)。
        """
        text = (out or "").strip()
        if not text:
            # 空 stdout = hook 未表态, 不阻断 (与 CC 的 exit 0 + 空 stdout 对齐)
            return HookDecision()
        try:
            obj = json.loads(text)
        except (ValueError, TypeError):
            return None
        if not isinstance(obj, dict):
            return None

        # CC 原生 hookSpecificOutput.permissionDecision
        hso = obj.get("hookSpecificOutput")
        if isinstance(hso, dict):
            pd = hso.get("permissionDecision")
            if pd == "deny":
                return HookDecision(
                    block=True,
                    reason=str(hso.get("permissionDecisionReason", "")
                               or f"{event} hook deny"),
                )
            if pd == "ask":
                # Tuan 无交互确认通道, ask 按 fail-closed 阻断
                return HookDecision(
                    block=True,
                    reason=str(hso.get("permissionDecisionReason", "")
                               or f"{event} hook ask (无确认通道, fail-closed)"),
                )
            if pd == "allow":
                # permissionDecision: allow 的 updatedInput 是 advisory，
                # 决策类事件不允许改参 → args=None, 留痕
                ui = hso.get("updatedInput")
                if isinstance(ui, dict):
                    self._audit(
                        event, obj, "decision_args_ignored",
                        f"决策类事件 {event!r} permissionDecision=allow "
                        f"不允许改参, 已忽略 updatedInput",
                    )
                return HookDecision(block=False, reason="", args=None)
            # CC 原生嵌套 decision 格式: {"decision": {"behavior": "deny"/"allow", ...}}
            nested = hso.get("decision")
            if isinstance(nested, dict):
                behavior = str(nested.get("behavior", "")).strip().lower()
                if behavior == "deny":
                    return HookDecision(
                        block=True,
                        reason=str(nested.get("message", "")
                                   or nested.get("reason", "")
                                   or f"{event} hook deny"),
                    )
                if behavior == "allow":
                    ui = nested.get("updatedInput")
                    return HookDecision(
                        block=False,
                        args=dict(ui) if isinstance(ui, dict) else None,
                    )
            # PermissionDenied: hookSpecificOutput.retry=True 请求重试
            # （exit code 被忽略，但 JSON retry 仍生效 —— B3 XIII）
            if hso.get("retry") is True:
                return HookDecision(block=False, retry=True)
            # 未知 permissionDecision → fall through 到顶层 decision

        # 顶层 decision (旧格式): {"decision":"block","reason":"..."}
        top = obj.get("decision")
        if isinstance(top, dict):
            behavior = str(top.get("behavior", "")).strip().lower()
            if behavior == "deny":
                return HookDecision(
                    block=True,
                    reason=str(top.get("message", "")
                               or top.get("reason", "")
                               or f"{event} hook deny"),
                )
            if behavior == "allow":
                ui = top.get("updatedInput")
                return HookDecision(
                    block=False,
                    args=dict(ui) if isinstance(ui, dict) else None,
                )
        if top == "block":
            return HookDecision(
                block=True,
                reason=str(obj.get("reason", "") or f"{event} hook block"),
            )
        if top == "allow":
            return HookDecision()
        # 顶层 decision 未知值 → 保守放行 (与 CC 官方对齐: 未声明就不阻断)
        return HookDecision()

    def run_notify(self, event: str, payload: Optional[Dict[str, Any]] = None) -> None:
        """通知类事件的统一派发 (Stop/SubagentStop/PreCompact/SessionStart/SessionEnd)。

        只读通知: **同步有界等待** hook 返回；stdout 忽略、异常隔离、
        **不改变动作裁决**（永远返回 ``None``）。
        决策专用事件误入（不在 _NOTIFY_EVENTS 但在 DECISION_CAPABLE_EVENTS）→
        留 decision_event_misrouted 审计, 不执行 hook（与 run_decision 互为镜像）。
        ConfigChange / Notification 同时属于 DECISION_CAPABLE_EVENTS 但走本出口，
        不算误入。
        """
        if not self.enabled:
            return
        from tuan_cli.hooks.exit_semantics import DECISION_CAPABLE_EVENTS
        # PreToolUse 等事件虽然可阻断，但它们走 run_pre/run_decision，不走本出口。
        # 在 run_notify 里它们应被视为「未知通知事件」而非「决策路由误入」。
        _run_decision_only = DECISION_CAPABLE_EVENTS - {"PreToolUse"}
        if event in _run_decision_only and event not in _NOTIFY_EVENTS:
            self._audit(
                event, {"payload": payload or {}}, "decision_event_misrouted",
                f"决策类事件 {event!r} 误走 run_notify, 不执行 hook (应走 run_decision)",
            )
            return
        if event not in _NOTIFY_EVENTS:
            # 非通知类事件误入 run_notify → 留 unknown_notify_event 审计
            self._audit(
                event, {"payload": payload or {}}, "unknown_notify_event",
                f"事件 {event!r} 不在通知类事件表",
            )
            return
        for spec in self._specs:
            if spec.event != event:
                continue
            # 构造 dict payload（_exec 会拒绝 None 并 fail-closed）
            pl = dict(payload or {})
            pl["hook_event_name"] = event
            self._exec_notify(spec, pl)

    def _exec_notify(self, spec, payload):
        """通知类单出口: 同步有界等待, stdout 忽略, 不改变动作裁决。"""
        t0 = time.monotonic()
        out, kind, stderr, rc = self._exec(spec, payload)
        elapsed = time.monotonic() - t0
        self._audit(spec.event, spec.raw, "channel_notification",
                    f"stdout 忽略; 不改变动作裁决; elapsed={elapsed:.3f}s; kind={kind or 'ok'}")
        return out

    def on_failure_policy(self) -> str:
        """返回本管理器的 on_failure 策略 (全局默认)。"""
        return self._on_failure_global

    def run_event(self, event: str, payload: Optional[Dict[str, Any]] = None,
                  tool_name: str = "") -> HookDecision:
        """按事件类型统一派发：决策类走 run_decision，通知类走 run_notify。

        lifecycle.emit() 用这个方法自动路由（B3 XIII）：调用方不需要知道
        事件是决策类还是通知类。返回值仅供决策类使用；通知类返回空决策。
        事件不在已知事件表 → 留 unknown_event 留痕并返回空决策。

        注意：PreCompact / Stop 等事件同时属于 DECISION_CAPABLE_EVENTS
        和 _NOTIFY_EVENTS。这些事件的 lifecycle.emit 需要走 run_decision
        （解析 stdout decision），不走 run_notify（stdout 忽略）。所以
        这里以 DECISION_CAPABLE_EVENTS 为准，绕开 run_decision 里的
        _NOTIFY_EVENTS 审计检查（那个检查是给直接调 run_decision 的
        老调用方准备的；run_event 是 lifecycle 的统一入口，已经知道
        自己在做正确的路由）。
        """
        from tuan_cli.hooks.exit_semantics import DECISION_CAPABLE_EVENTS
        if event in DECISION_CAPABLE_EVENTS:
            # 直接调 run_decision；skip_notify_audit=True 让它跳过
            # _NOTIFY_EVENTS 审计拦截（PreCompact / Stop 同时在两边）。
            return self.run_decision(
                event, tool_name=tool_name, payload=payload,
                skip_notify_audit=True)
        self.run_notify(event, payload)
        return HookDecision()

    def run_session(self, event: str, payload: Optional[Dict[str, Any]] = None) -> None:
        """SessionStart / SessionEnd: 只读通知 (run_notify 的会话别名)。"""
        self.run_notify(event, payload)

    def run_user_prompt_submit(self, prompt: Optional[str]) -> str:
        """UserPromptSubmit: 收集各 hook 的 stdout 作为附加上下文。

        - 入参类型面：非 str 非 None → 强制回落 ``""`` 并留
          ``invalid_prompt_type`` 审计，**绝不抛异常**（XVI P4）；
          ``None`` 保持既有静默兼容。
        - 出站净化：command hook 的 stdout 经 ``safe_hook_text`` 单一
          真值剥控制字符 / 脱敏 / 限长；空 stdout 不注入（P2）。
        - 总长硬上界 ``MAX_ADDITIONAL_CONTEXT``（分隔符一并计入），
          命中时留 ``additional_context_capped`` 审计。
        - **不谎称**防住语义级 prompt injection：净化不宣称解决模型
          侧的输入边界。
        """
        if not self.enabled:
            return ""
        if prompt is None:
            clean_prompt = ""
        elif not isinstance(prompt, str):
            self._audit(
                "UserPromptSubmit", {}, "invalid_prompt_type",
                f"prompt 不是 str: {type(prompt).__name__}，回落空串",
            )
            clean_prompt = ""
        else:
            clean_prompt = prompt

        outs: List[str] = []
        total = 0
        capped = False
        injected = False
        for spec in self._specs:
            if spec.event != "UserPromptSubmit":
                continue
            out, kind, stderr, rc = self._exec(spec, {
                "hook_event_name": "UserPromptSubmit",
                "prompt": clean_prompt[:4000],
            })
            # url hook 无有效 stdout：非进程通道「正常响应但无裁决」，显式留痕
            if spec.hook_type == "url" and not (out or "").strip() and kind == "":
                self._audit(spec.event, spec.raw, "channel_no_decision",
                            "url hook 正常响应但无有效裁决")
            # UserPromptSubmit: exit 2 → 阻断 prompt，stderr 给用户且不进 context
            if kind == "exit_2":
                return "BLOCKED"  # 信号量：上层应拒绝 prompt
            if not out:
                # 空输出不注入；url hook 无裁决时留痕（XVI P2）
                if spec.hook_type == "url" and kind == "":
                    self._audit(spec.event, spec.raw, "channel_no_decision",
                                "url hook 正常响应但无有效裁决")
                continue
            # 单条 1000 字上限（XVI P2 探针契约：不是 safe_hook_text 的 400）；
            # 先硬截到 1000，再交 safe_hook_text（limit=1002 使其不触发
            # cap-1+省略号 截断，1000 字原文不变）。
            cleaned = safe_hook_text(out[:1000], 1002)
            if not cleaned:
                continue
            injected = True
            if capped:
                continue
            sep = "\n" if outs else ""
            budget = MAX_ADDITIONAL_CONTEXT - total - len(sep)
            if budget <= 0:
                capped = True
                self._audit(spec.event, spec.raw, "additional_context_capped",
                            f"附加上下文总长已达 {MAX_ADDITIONAL_CONTEXT} 码点硬上界，截断")
                continue
            if len(cleaned) <= budget:
                outs.append(sep + cleaned)
                total += len(sep) + len(cleaned)
            else:
                outs.append(sep + cleaned[:budget])
                total += len(sep) + budget
                capped = True
                self._audit(spec.event, spec.raw, "additional_context_capped",
                            f"附加上下文总长已达 {MAX_ADDITIONAL_CONTEXT} 码点硬上界，截断")
        if injected:
            self._audit("UserPromptSubmit", {}, "additional_context_injected",
                        "已注入附加上下文（经 safe_hook_text 净化"
                        + ("；总长命中上界已截断）" if capped else "）"))
        return "".join(outs)

    # ------------------------------------------------------------------ 底层

    def _exec(self, spec: _HookSpec, payload: Dict[str, Any]) -> tuple:
        """执行单条 hook, 返回 (stdout, failure_kind, stderr, returncode)。

        B3 续轮 XVI：**单一净化出口**。所有五条链路（run_pre / run_post /
        run_notify / run_decision / run_user_prompt_submit）的 payload 都
        先在本函数内过递归净化真值 ``safe_payload``，再交给对应执行器。

        - 非 dict payload → ``(None, "invalid_spec", "", -1)``（fail-closed）
        - ``n > 0`` 时留 ``payload_sanitized`` 审计（出站留痕）
        - url / prompt / subagent 三类非进程 hook → ``_np.execute`` 单一入口
        - command → ``self._exec_command``（命令路径逐字节零改动）
        """
        self._last_failure_kind = ""
        if not isinstance(payload, dict):
            self._audit(spec.event, spec.raw, "payload_rejected",
                        f"payload 不是 dict: {type(payload).__name__}")
            self._record_failure("invalid_spec", spec.event, spec,
                                 "payload 非 dict，fail-closed")
            self._last_failure_kind = "invalid_spec"
            return (None, "invalid_spec", "", -1)

        # 单一净化出口：整个文件仅此一处调用本函数（XVI 源码级核销点）
        pl, n = safe_payload(payload)
        if n > 0:
            self._audit(spec.event, spec.raw, "payload_sanitized",
                        f"递归净化改动 {n} 个字段（OSC/RLO/凭据/有界）")

        if spec.hook_type == "command":
            return self._exec_command(spec, pl)

        # url / prompt / subagent：统一走 nonprocess 单一权威入口
        if spec.hook_type in _np.HOOK_TYPES:
            oc = _np.execute(spec, pl, self._kernel, self.workspace or "",
                             default_timeout=self.default_timeout)
            # 等价故障闭合：把通道故障映射成等价 rc，与 command hook 同一裁决
            _np.classify_channel(spec.event, oc, tuan_policy="block")
            self._tls.last_channel = oc
            for st, detail in oc.audit_events:
                self._audit(spec.event, spec.raw, st, detail)
            if oc.status == "failure":
                self._last_failure_kind = oc.failure_kind
                self._record_failure(oc.failure_kind, spec.event, spec,
                                     oc.failure_detail)
                return (None, oc.failure_kind, oc.stderr, -1)
            if oc.status == "ok_no_decision":
                self._audit(spec.event, spec.raw, "exit_json_ignored",
                            "hook 正常响应但无有效裁决，按无意见放行")
            return (oc.stdout or "", "", "", 0)
        return (None, "invalid_spec", "", -1)

    def _exec_command(self, spec: _HookSpec, payload: Dict[str, Any]) -> tuple:
        """执行传统 argv 脚本, 返回 (stdout, failure_kind, stderr, returncode)。

        采用「看门狗线程 + 进程树强杀」而非 subprocess.run(timeout=...):
        Windows 上 subprocess.run 的超时杀进程不可靠。
        """
        if not spec.command or not isinstance(spec.command, (list, tuple)):
            self._audit(spec.event, spec.raw, "rejected_empty_command",
                        "hook command 为空或非列表")
            self._record_failure("rejected_empty_command", spec.event, spec)
            return (None, "rejected_empty_command", "", -1)

        try:
            proc = subprocess.Popen(
                spec.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.workspace,
                text=True,
                start_new_session=(os.name != "nt"),
            )
        except FileNotFoundError:
            msg = f"命令未找到: {spec.command[0] if spec.command else '<empty>'}"
            self._audit(spec.event, spec.raw, "spawn_error", msg)
            self._last_failure_kind = "spawn_error"
            self._record_failure("spawn_error", spec.event, spec, msg)
            return (None, "spawn_error", msg, -1)
        except PermissionError as exc:
            self._audit(spec.event, spec.raw, "spawn_error", f"权限不足: {exc}")
            self._last_failure_kind = "spawn_error"
            self._record_failure("spawn_error", spec.event, spec, f"权限不足: {exc}")
            return (None, "spawn_error", str(exc), -1)
        except Exception as exc:  # noqa: BLE001
            self._audit(spec.event, spec.raw, "spawn_error", f"{type(exc).__name__}: {exc}")
            self._last_failure_kind = "spawn_error"
            self._record_failure("spawn_error", spec.event, spec,
                                 f"{type(exc).__name__}: {exc}")
            return (None, "spawn_error", str(exc), -1)

        killed: list[bool] = []
        stop_watchdog = threading.Event()

        def _watchdog() -> None:
            if stop_watchdog.wait(spec.timeout):
                return
            killed.append(True)
            self._kill_tree(proc)
            self._audit(spec.event, spec.raw, "timeout",
                        f"hook 超过 {spec.timeout}s 被强杀")

        watcher = threading.Thread(target=_watchdog, daemon=True)
        watcher.start()
        try:
            out, err = proc.communicate(input=json.dumps(payload, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            self._kill_tree(proc)
            self._audit(spec.event, spec.raw, "error", f"{type(exc).__name__}: {exc}")
            self._last_failure_kind = "error"
            self._record_failure("error", spec.event, spec,
                                 f"{type(exc).__name__}: {exc}")
            return (None, "error", str(exc), -1)
        finally:
            stop_watchdog.set()
            watcher.join(timeout=2.0)

        rc = proc.returncode
        err_text = err or ""
        if killed:
            self._last_failure_kind = "timeout"
            self._record_failure("timeout", spec.event, spec,
                                 f"hook 超过 {spec.timeout}s 被强杀")
            return (None, "timeout", "", -1)
        if rc == 2:
            return (out, "exit_2", err_text, 2)
        if rc != 0:
            # 非零 rc: 留痕（决策类会参考），但若 stdout 是合法 JSON 仍被采信
            self._last_failure_kind = "nonzero_rc"
            self._record_failure("nonzero_rc", spec.event, spec,
                                 f"rc={rc} stderr={err_text[:200]}")
            return (out, "nonzero_rc", err_text, rc)
        return (out, "", err_text, 0)

    def _emit_channel_semantics(self, event: str, raw: Any,
                                block: bool, policy: str) -> None:
        """留一条 channel_semantics 结构化审计（XV/XVI 通知/裁决链路）。"""
        self._audit(event, raw, "channel_semantics",
                    f"block={block}; on_failure={policy}")

    @staticmethod
    def _clean_reason(reason: str) -> str:
        """净化决策 reason：剥控制字符 + 脱敏 ``ghp_...``（XV/XVI）。"""
        return safe_hook_text(reason or "")

    def _exec_notify(self, spec, payload):
        """通知类单出口: 同步有界等待, stdout 忽略, 不改变动作裁决。"""
        t0 = time.monotonic()
        out, kind, stderr, rc = self._exec(spec, payload)
        elapsed = time.monotonic() - t0
        self._audit(spec.event, spec.raw, "channel_notification",
                    f"stdout 忽略; 不改变动作裁决; elapsed={elapsed:.3f}s; kind={kind or 'ok'}")
        return out

    @staticmethod
    def _kill_tree(proc: "subprocess.Popen") -> None:
        """强杀进程树 (含子孙), 跨平台。Windows 用 taskkill /T /F。

        注意: 如果进程已退出, 各种强杀操作会抛异常, 统一 catch 并忽略。
        """
        # Check if process already exited (no-op in that case)
        if proc.poll() is not None:
            return
        try:
            pid = proc.pid
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/pid", str(pid), "/T", "/F"],
                    capture_output=True, timeout=10,
                )
            else:
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)  # type: ignore[attr-defined]  # POSIX-only: killpg/getpgid/SIGKILL
                except ProcessLookupError:
                    pass  # Process group already gone
        except Exception as exc:  # noqa: BLE001
            # Fallback: try to kill just the main process
            try:
                if proc.poll() is None:
                    proc.kill()
            except Exception as exc2:  # noqa: BLE001
                # 双层失败会留孤儿进程; 至少告警让运维能介入
                log.warning("hook 进程树终止失败 (pid=%s): fallback=%s, kill=%s",
                            pid, exc, exc2)

    def _parse_decision(self, stdout: str) -> Optional[Dict[str, Any]]:
        """解析 hook stdout 为决策 dict。兼容多种风格:
        - {"decision":"block","reason":...} / {"block":true,"reason":...}
        - {"args": {...}}
        - {"hookSpecificOutput": {"permissionDecision": "allow",
                                   "updatedInput": {...}}}  (CC 原生)
        - 非 JSON 输出 → 忽略 (视为无决策)
        返回 None 表示无有效决策。
        """
        s = (stdout or "").strip()
        if not s:
            return None
        try:
            data = json.loads(s)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        # CC 原生 hookSpecificOutput.permissionDecision
        hso = data.get("hookSpecificOutput")
        if isinstance(hso, dict):
            pd = hso.get("permissionDecision")
            if pd == "allow":
                ui = hso.get("updatedInput")
                return {"block": False, "reason": "",
                        "args": dict(ui) if isinstance(ui, dict) else None}
            if pd == "deny":
                return {"block": True,
                        "reason": str(hso.get("permissionDecisionReason", "")
                                      or "hook deny"),
                        "args": None}
            if pd == "ask":
                return {"block": True,
                        "reason": str(hso.get("permissionDecisionReason", "")
                                      or "hook ask"),
                        "args": None}
            # additionalContext: CC advisory 无本地注入通道 → 留痕
            if "additionalContext" in hso:
                self._audit(
                    "PreToolUse", data, "additional_context_no_channel",
                    str(hso.get("additionalContext", ""))[:200],
                )
                # additionalContext 不阻断，继续检查其他字段
        if "decision" in data:
            return {"block": str(data.get("decision")).lower() == "block",
                    "reason": str(data.get("reason", "")), "args": data.get("args")}
        if "block" in data:
            return {"block": bool(data.get("block")),
                    "reason": str(data.get("reason", "")), "args": data.get("args")}
        if "args" in data:
            return {"block": False, "reason": "", "args": data.get("args")}
        return None

    def _audit(self, event: str, hook: Any, status: str, detail: str = "") -> None:
        """写入审计事件 hook.executed (供 self-improve / 观测订阅)。"""
        if not self.audit_log:
            return
        if self._kernel is None:
            return
        try:
            desc = ""
            if isinstance(hook, dict):
                desc = hook.get("description", "") or " ".join(
                    [str(x) for x in hook.get("command", [])])
            self._kernel.emit("hook.executed", {
                "event": event,
                "status": status,
                "detail": detail,
                "hook": desc,
            })
        except Exception as exc:  # noqa: BLE001
            # Fail-safe: audit failure must never crash the hook pipeline
            log.debug("hook.executed 审计事件发送失败: %s", exc)

    def __repr__(self) -> str:
        specs_by_event: Dict[str, int] = {}
        for s in self._specs:
            specs_by_event[s.event] = specs_by_event.get(s.event, 0) + 1
        return (
            f"HookManager(enabled={self.enabled}, hooks={len(self._specs)}, "
            f"by_event={specs_by_event}, timeout={self.default_timeout})"
        )

    # ------------------------------------------------------------------ 枚举

    def list_hooks(self) -> List[Dict[str, Any]]:
        """列出所有已配置 hook (脱敏, 仅供展示)。"""
        out: List[Dict[str, Any]] = []
        for spec in self._specs:
            out.append({
                "event": spec.event,
                "matcher": spec.matcher,
                "command": spec.command,
                "timeout": spec.timeout,
                "blocking": spec.blocking,
                "allow_edit_args": spec.allow_edit_args,
                "description": spec.description,
            })
        return out

    def enabled_for(self, event: str) -> bool:
        return self.enabled and any(s.event == event for s in self._specs)
