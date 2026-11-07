"""用户级 Hooks 引擎 (零第三方依赖, 纯标准库)。

设计目标: 把 Agent 变成"可编排的", 同时把安全边界钉死:
- command 必须是 list(argv), 拒绝裸字符串 (无 shell 注入面)。
- 超时强杀 (看门狗线程 + 进程树强杀)。Windows 上 subprocess.run 的 timeout
  杀进程并不可靠 (sleep 类子进程无法被及时回收, 导致 communicate() 永远阻塞);
  故改用独立看门狗线程在超时后强制 taskkill /T 整棵树。
- **故障默认闭合 (B1 / 超 Claude Code v2.1.319)**: hook 的 spawn 失败、
  超时、异常、无模型/无内核、非零退出全部记入 ``failures()``；对
  ``PreToolUse`` 默认 ``on_failure="block"`` 直接阻断并给出结构化原因。
  对标 CC 的 ``onFailure:"block"`` —— 但在 CC 里那是**用户逐条 hook
  显式配置**的选项, 旧行为是静默 fail-open；这里把它做成出厂默认。
  可用 ``hooks.on_failure`` (全局) 或单条 hook 的 ``on_failure`` 覆盖为
  ``ask`` / ``allow``，未知取值一律回退最严格档并记审计。
- **阻断默认生效**: ``blocking`` 由 False 改为 True。此前 hook 返回
  ``{"block": true}`` 时若未显式写 ``blocking: true`` 会被吞掉只记一条
  ``block_denied``，是第二个配置侧门。仍可显式 ``blocking: false`` 关闭。
  注意: ``blocking`` 只管 hook **自己返回的** block 决策，**不管**
  执行失败的 fail-closed —— 失败阻断不受该开关影响。
- 通知类事件 (PostToolUse / Stop / Session* / UserPromptSubmit) 没有
  action 可阻断, 失败**只留痕不卡住主回合**；``failures()`` 可查询。
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

# hook 故障策略 (B1)。"block" 最严格且为出厂默认；"ask" 同样阻断但标注
# 需人工确认；"allow" 是显式逃生口, 会记 failure_allowed 审计。
ON_FAILURE_POLICIES = ("block", "ask", "allow")
DEFAULT_ON_FAILURE = "block"

# 受支持的 hook 事件类型 (对标 Claude Code 的 hooks 事件面)
# - PreToolUse / PostToolUse: 工具执行前后 (支持 matcher 过滤, Pre 可阻断/改参)
# - UserPromptSubmit: 用户提交输入后、进入模型前 (stdout 作为附加上下文注入)
# - Stop / SubagentStop: 主回合结束 / 子任务结束时通知
# - PreCompact: 上下文压缩前通知
# - SessionStart / SessionEnd: 会话级生命周期通知
HOOK_EVENTS = (
    "PreToolUse",
    "PostToolUse",
    "UserPromptSubmit",
    "Stop",
    "SubagentStop",
    "PreCompact",
    "SessionStart",
    "SessionEnd",
)

# 仅通知类事件 (无 matcher、stdout 忽略), 由 run_notify 统一派发
_NOTIFY_EVENTS = ("Stop", "SubagentStop", "PreCompact", "SessionStart", "SessionEnd")


@dataclass
class HookDecision:
    """PreToolUse 的返回决策。

    block=True 时主流程中止执行 (hook 自身决策需 blocking 且全局允许；
    **执行失败导致的 fail-closed 不受该开关影响**)。
    args 非空时改写即将执行的工具参数 (仅当允许改参)。
    failure_kind 非空表示这次阻断来自 hook 故障而非 hook 主动 block。
    """

    block: bool = False
    reason: str = ""
    args: Optional[Dict[str, Any]] = None
    failure_kind: str = ""


@dataclass(frozen=True)
class HookFailure:
    """一次 hook 执行失败的结构化记录 (可查询、可审计、可回放)。"""

    uid: str
    event: str
    hook_type: str
    kind: str          # invalid_spec / spawn_error / timeout / error /
                       # nonzero_rc / http_error / no_kernel / no_model
    detail: str
    tool_name: str = ""
    ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {"uid": self.uid, "event": self.event,
                "hook_type": self.hook_type, "kind": self.kind,
                "detail": self.detail, "tool_name": self.tool_name,
                "ts": self.ts}


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
    on_failure: str = ""      # 单条覆盖全局 hooks.on_failure；空 = 用全局

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
        # B1: 故障闭合默认策略 + 有界失败记录 + 线程局部「最近一次失败」
        self.on_failure = DEFAULT_ON_FAILURE
        self._failures: List[HookFailure] = []
        self._max_failures = 200
        self._tls = threading.local()

        hooks_cfg = self._read_cfg(config)
        if hooks_cfg is None:
            self.enabled = False
            return
        self.enabled = bool(hooks_cfg.get("enabled", True))
        self.default_timeout = float(hooks_cfg.get("default_timeout", 30))
        self.allow_blocking = bool(hooks_cfg.get("allow_blocking", True))
        self.allow_edit_args = bool(hooks_cfg.get("allow_edit_args", False))
        self.audit_log = bool(hooks_cfg.get("audit_log", True))
        raw_policy = str(hooks_cfg.get("on_failure", DEFAULT_ON_FAILURE)
                         or DEFAULT_ON_FAILURE).strip().lower()
        if raw_policy not in ON_FAILURE_POLICIES:
            # 未知策略绝不静默接受 —— 回退最严格档并留痕
            self._audit("config", {"on_failure": raw_policy},
                        "invalid_on_failure",
                        f"未知 on_failure={raw_policy!r}, 回退 {DEFAULT_ON_FAILURE}")
            raw_policy = DEFAULT_ON_FAILURE
        self.on_failure = raw_policy

        for evt in HOOK_EVENTS:
            for item in hooks_cfg.get(evt, []) or []:
                spec = self._parse_spec(evt, item)
                if spec is not None:
                    self._specs.append(spec)

    # ------------------------------------------------------------------ 配置

    @staticmethod
    def _read_cfg(config: Any) -> Optional[Dict[str, Any]]:
        """从 Config 对象或 dict 取出 hooks 块。"""
        if config is None:
            return None
        try:
            if hasattr(config, "get"):
                v = config.get("hooks", None)
            else:
                v = config.get("hooks") if isinstance(config, dict) else None
        except Exception:
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

        # 单条 hook 可覆盖全局故障策略；未知值忽略并用全局, 不静默接受
        per_hook = str(item.get("on_failure", "") or "").strip().lower()
        if per_hook and per_hook not in ON_FAILURE_POLICIES:
            self._audit(event, item, "invalid_on_failure",
                        f"单条 hook 未知 on_failure={per_hook!r}, 忽略并用全局策略")
            per_hook = ""

        return _HookSpec(
            event=event,
            matcher=str(item.get("matcher", "*") or "*"),
            command=cmd,
            timeout=max(0.1, timeout),
            # B1: 阻断默认生效。此前默认 False 会吞掉 hook 返回的 block。
            blocking=bool(item.get("blocking", True)),
            allow_edit_args=bool(item.get("allow_edit_args", False)),
            description=str(item.get("description", "")),
            raw=item,
            hook_type=hook_type,
            url=url,
            prompt_text=prompt_text,
            model_override=model_override,
            on_failure=per_hook,
        )

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

    def run_pre(self, tool_name: str, args: Dict[str, Any],
                dangerous: bool = False, impact: Optional[str] = None) -> HookDecision:
        """PreToolUse: 返回决策 (可阻断 / 可改写参数)。

        安全: 阻断仅当 hook.blocking 且全局 allow_blocking 均为 True;
              改参仅当 hook.allow_edit_args 或全局 allow_edit_args。
        """
        decision = HookDecision()
        if not self.enabled:
            return decision
        for spec in self._specs:
            if spec.event != "PreToolUse":
                continue
            if not self._match(spec.matcher, tool_name):
                continue
            out = self._exec(spec, {
                "hook_event_name": "PreToolUse",
                "tool_name": tool_name,
                "tool_input": args,
                "dangerous": dangerous,
                "impact": impact,
            })
            failure = getattr(self._tls, "last_failure", None)
            failed_run = (out is None or
                          (isinstance(out, str) and not out.strip()))                 and failure is not None
            if failed_run:
                # B1: hook 故障默认闭合。CC 需逐条显式 onFailure:"block"。
                # blocking 开关只影响 hook 自己返回的 block, 不影响这里。
                policy = spec.on_failure or self.on_failure
                reason = (
                    f"hook 执行失败 (fail-closed, on_failure={policy}): "
                    f"event={spec.event} hook={spec.uid} "
                    f"kind={failure.kind} detail={failure.detail}")
                if policy == "ask":
                    reason += " [需人工确认]"
                if policy in ("block", "ask"):
                    decision.block = True
                    decision.reason = reason
                    decision.failure_kind = failure.kind
                    self._audit("PreToolUse", spec.raw, "failure_blocked", reason)
                    return decision
                # policy == "allow": 显式逃生口, 必须留痕
                self._audit("PreToolUse", spec.raw, "failure_allowed",
                            f"on_failure=allow 放行 ({failure.kind})")
                continue
            if out is None:
                continue
            parsed = self._parse_decision(out)
            if parsed is None:
                continue
            if parsed.get("block"):
                if self.allow_blocking and spec.blocking:
                    decision.block = True
                    decision.reason = str(parsed.get("reason", "hook 未提供原因"))
                    return decision  # 首个阻断即生效
                # 配置不允许阻断 → 仅记录, 不阻断 (fail-safe)
                self._audit("PreToolUse", spec.raw, "block_denied",
                            parsed.get("reason", ""))
            new_args = parsed.get("args")
            if isinstance(new_args, dict) and new_args:
                if self.allow_edit_args or spec.allow_edit_args:
                    decision.args = new_args
                else:
                    self._audit("PreToolUse", spec.raw, "edit_args_denied",
                                "hook 请求改写参数但未被授权")
        return decision

    def run_post(self, tool_name: str, args: Dict[str, Any],
                 result: Any = None) -> None:
        """PostToolUse: 只读审计, stdout 忽略, 异常隔离。"""
        if not self.enabled:
            return
        res = result
        payload = {
            "hook_event_name": "PostToolUse",
            "tool_name": tool_name,
            "tool_input": args,
            "tool_result": {
                "status": getattr(res, "status", None),
                "content": (getattr(res, "content", "") or "")[:2000],
                "error_type": getattr(res, "error_type", None),
            },
        }
        for spec in self._specs:
            if spec.event != "PostToolUse":
                continue
            if not self._match(spec.matcher, tool_name):
                continue
            self._exec(spec, payload)  # stdout 忽略

    def run_notify(self, event: str, payload: Optional[Dict[str, Any]] = None) -> None:
        """通知类事件的统一派发 (Stop/SubagentStop/PreCompact/SessionStart/SessionEnd)。

        只读通知: stdout 忽略、异常隔离、不阻断主流程。
        """
        if not self.enabled or event not in _NOTIFY_EVENTS:
            return
        pl = dict(payload or {})
        pl["hook_event_name"] = event
        for spec in self._specs:
            if spec.event != event:
                continue
            self._exec(spec, pl)

    def run_session(self, event: str, payload: Optional[Dict[str, Any]] = None) -> None:
        """SessionStart / SessionEnd: 只读通知 (run_notify 的会话别名)。"""
        self.run_notify(event, payload)

    def run_user_prompt_submit(self, prompt: str) -> str:
        """UserPromptSubmit: 收集各 hook 的 stdout 作为附加上下文。

        返回所有命中 hook 的 stdout (各截断 1000 字符后以换行拼接);
        无 hook 命中或无输出时返回空串。对标 Claude Code 的 additionalContext。
        """
        if not self.enabled:
            return ""
        outs: List[str] = []
        for spec in self._specs:
            if spec.event != "UserPromptSubmit":
                continue
            out = self._exec(spec, {
                "hook_event_name": "UserPromptSubmit",
                "prompt": (prompt or "")[:4000],
            })
            if out and out.strip():
                outs.append(out.strip()[:1000])
        return "\n".join(outs)

    # ------------------------------------------------------------------ 底层

    def _record_failure(self, spec: _HookSpec, kind: str, detail: str,
                        tool_name: str = "") -> None:
        """记录一次 hook 执行失败 (线程局部 + 有界历史 + 审计)。

        绝不抛异常：记录失败本身不能把 hook 流水线弄崩。
        """
        rec = HookFailure(
            uid=spec.uid, event=spec.event, hook_type=spec.hook_type,
            kind=kind, detail=str(detail)[:400], tool_name=tool_name,
            ts=time.time(),
        )
        try:
            self._tls.last_failure = rec
        except Exception:  # noqa: BLE001
            pass
        self._failures.append(rec)
        if len(self._failures) > self._max_failures:
            self._failures = self._failures[-self._max_failures:]
        self._audit(spec.event, spec.raw, "failed", f"{kind}: {detail}")

    def failures(self) -> List[Dict[str, Any]]:
        """返回本实例的 hook 失败记录 (只读副本)。"""
        return [f.to_dict() for f in list(self._failures)]

    def clear_failures(self) -> None:
        """清空失败记录 (供测试/运维显式重置)。"""
        self._failures.clear()
        self._tls.last_failure = None

    def on_failure_policy(self) -> str:
        """当前全局故障策略 (block / ask / allow)。"""
        return self.on_failure

    def _exec(self, spec: _HookSpec, payload: Dict[str, Any]) -> Optional[str]:
        """执行单条 hook, 返回结果文本; 超时/异常返回 None。

        支持四种类型:
        - command: 传统 argv 脚本 (stdin JSON, stdout 文本)
        - url: HTTP POST (发送 JSON, 读取响应)
        - prompt: LLM prompt (调用模型, 返回模型输出)
        - subagent: 子代理 (创建隔离 Agent, 返回摘要)

        B1: 每次派发前清空「最近一次失败」，执行器在失败时调用
        ``_record_failure``。调用方据此做 fail-closed 判定。
        """
        self._tls.last_failure = None
        if spec.hook_type == "url":
            return self._exec_http(spec, payload)
        elif spec.hook_type == "prompt":
            return self._exec_prompt(spec, payload)
        elif spec.hook_type == "subagent":
            return self._exec_subagent(spec, payload)
        else:
            return self._exec_command(spec, payload)

    def _exec_command(self, spec: _HookSpec, payload: Dict[str, Any]) -> Optional[str]:
        """执行传统 argv 脚本。

        采用「看门狗线程 + 进程树强杀」而非 subprocess.run(timeout=...):
        Windows 上 subprocess.run 的超时杀进程不可靠 —— 对已 sleep / 阻塞的子进程,
        TerminateProcess 未必及时回收, 导致内部 communicate() 永久阻塞 (实测会挂死)。
        看门狗在超时后强制 taskkill /T 整棵树, 主线程的 communicate() 随管道关闭而返回。
        """
        # Validate command before spawning (fail-fast for misconfigured hooks)
        if not spec.command or not isinstance(spec.command, (list, tuple)):
            self._audit(spec.event, spec.raw, "rejected_empty_command",
                        "hook command 为空或非列表")
            self._record_failure(spec, "invalid_spec", "hook command 为空或非列表")
            return None

        try:
            proc = subprocess.Popen(
                spec.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.workspace,
                text=True,
                start_new_session=(os.name != "nt"),  # POSIX 独立会话: 强杀不波及父进程组
            )
        except FileNotFoundError:
            d = f"命令未找到: {spec.command[0] if spec.command else '<empty>'}"
            self._audit(spec.event, spec.raw, "spawn_error", d)
            self._record_failure(spec, "spawn_error", d)
            return None
        except PermissionError as exc:
            d = f"权限不足: {exc}"
            self._audit(spec.event, spec.raw, "spawn_error", d)
            self._record_failure(spec, "spawn_error", d)
            return None
        except Exception as exc:  # noqa: BLE001
            d = f"{type(exc).__name__}: {exc}"
            self._audit(spec.event, spec.raw, "spawn_error", d)
            self._record_failure(spec, "spawn_error", d)
            return None

        killed: list[bool] = []
        stop_watchdog = threading.Event()

        def _watchdog() -> None:
            if stop_watchdog.wait(spec.timeout):
                return
            killed.append(True)
            self._kill_tree(proc)
            d = f"hook 超过 {spec.timeout}s 被强杀"
            # 只在这里审计；failure 由**主线程**在 killed 分支补记。
            # _record_failure 写的是 thread-local 的 last_failure，若在
            # 看门狗线程里调用，run_pre 读不到，fail-closed 就会被绕过。
            self._audit(spec.event, spec.raw, "timeout", d)

        watcher = threading.Thread(target=_watchdog, daemon=True)
        watcher.start()
        try:
            out, err = proc.communicate(input=json.dumps(payload, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            self._kill_tree(proc)
            d = f"{type(exc).__name__}: {exc}"
            self._audit(spec.event, spec.raw, "error", d)
            self._record_failure(spec, "error", d)
            return None
        finally:
            stop_watchdog.set()
            watcher.join(timeout=2.0)

        if killed:
            self._record_failure(
                spec, "timeout", f"hook 超过 {spec.timeout}s 被强杀")
            return None
        if proc.returncode != 0:
            d = f"rc={proc.returncode} stderr={err[:200]}"
            self._audit(spec.event, spec.raw, "nonzero_rc", d)
            # 仍返回 out: 若 hook 输出了合法 decision 则优先按 decision 处理
            # (兼容既有行为)；out 为空时 run_pre 会按 on_failure 闭合。
            self._record_failure(spec, "nonzero_rc", d)
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
        except Exception:  # noqa: BLE001
            # Fallback: try to kill just the main process
            try:
                if proc.poll() is None:
                    proc.kill()
            except Exception:  # noqa: BLE001
                pass

    def _exec_http(self, spec: _HookSpec, payload: Dict[str, Any]) -> Optional[str]:
        """执行 HTTP POST hook。"""
        import urllib.request
        import urllib.error

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            spec.url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "tuan_cli-hook"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=spec.timeout) as resp:  # noqa: S310
                body = resp.read(50000).decode("utf-8", errors="replace")
                return str(body)
        except urllib.error.HTTPError as exc:
            d = f"HTTP {exc.code} {exc.reason}"
            self._audit(spec.event, spec.raw, "http_error", d)
            self._record_failure(spec, "http_error", d)
            return None
        except Exception as exc:  # noqa: BLE001
            d = f"{type(exc).__name__}: {exc}"
            self._audit(spec.event, spec.raw, "error", d)
            self._record_failure(spec, "error", d)
            return None

    def _exec_prompt(self, spec: _HookSpec, payload: Dict[str, Any]) -> Optional[str]:
        """执行 Prompt hook: 调用模型返回结果。"""
        if self._kernel is None:
            d = "Prompt hook: 无内核, 模型不可用"
            self._audit(spec.event, spec.raw, "no_kernel", d)
            self._record_failure(spec, "no_kernel", d)
            return None
        model = self._kernel.get("model_adapter")
        if model is None:
            d = "Prompt hook: 无可用模型适配器"
            self._audit(spec.event, spec.raw, "no_model", d)
            self._record_failure(spec, "no_model", d)
            return None

        # 构建 prompt: 将 payload 注入模板
        prompt = spec.prompt_text
        for key, val in payload.items():
            placeholder = "{" + key + "}"
            if placeholder in prompt:
                prompt = prompt.replace(placeholder, json.dumps(val, ensure_ascii=False) if not isinstance(val, str) else val)

        messages = [{"role": "user", "content": prompt}]
        try:
            result = model.chat(messages, stream=False)
            if hasattr(result, "content"):
                return result.content or ""
            return str(result) if result else ""
        except Exception as exc:  # noqa: BLE001
            d = f"Prompt hook 模型调用失败: {exc}"
            self._audit(spec.event, spec.raw, "error", d)
            self._record_failure(spec, "error", d)
            return None

    def _exec_subagent(self, spec: _HookSpec, payload: Dict[str, Any]) -> Optional[str]:
        """执行 Subagent hook: 创建隔离 Agent 运行任务。"""
        if self._kernel is None:
            d = "Subagent hook: 无内核, 无法创建隔离 Agent"
            self._audit(spec.event, spec.raw, "no_kernel", d)
            self._record_failure(spec, "no_kernel", d)
            return None
        try:
            from ..app import create_agent
            sub = create_agent(self._kernel, self.workspace or "")
            # 将 payload 注入为上下文
            context = json.dumps(payload, ensure_ascii=False)[:3000]
            task = f"{spec.prompt_text}\n\n上下文: {context}" if spec.prompt_text else f"处理以下事件: {context}"
            result = sub.run(task, stream=False, max_iterations=5)
            return result[:3000] if result else ""
        except Exception as exc:  # noqa: BLE001
            d = f"Subagent hook 失败: {exc}"
            self._audit(spec.event, spec.raw, "error", d)
            self._record_failure(spec, "error", d)
            return None

    @staticmethod
    def _parse_decision(stdout: str) -> Optional[Dict[str, Any]]:
        """解析 hook stdout 为决策 dict。兼容多种风格:
        - {"decision":"block","reason":...} / {"block":true,"reason":...}
        - {"args": {...}}
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
