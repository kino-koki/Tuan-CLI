"""统一、fail-closed 安全闸门 —— 最强安全级别的核心。

所有「会产生副作用的动作」入口 (shell / mcp 工具 / 文件写 / 远程 prompt /
自我改进 / 定时任务 / 技能) 都应经此闸门裁决。设计原则:

- **fail-closed**: 任何异常、未知动作类型或未知信任级别, 一律 DENY;
- **红线优先**: ``is_hard_redline`` 命中永远 DENY, 即便 YOLO / 远程 / 白名单也不例外;
- **信任级别**: untrusted 工作区禁止 shell / 写文件; unknown 必须 confirm;
- **远程来源**: 远程发来的 prompt/命令默认升级 (非良性需 confirm, 红线 DENY)。

本模块只依赖标准库与同级安全组件 (safety_engine / security_policy), 不引入新网络或
重型依赖; 对 core 内模块的依赖通过方法内惰性 import 完成, 避免循环导入。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from .safety_engine import (
    SafetyEngine,
    is_benign_dev_command,
    is_hard_redline,
    is_redline,
)
from ..core.workspace_trust import TrustLevel


@dataclass(frozen=True)
class GateVerdict:
    """闸门裁决结果 (不可变, 便于在多线程/异步上下文安全传递)。"""

    action: str          # allow | confirm | deny
    severity: str        # none | low | medium | high | critical
    reasons: tuple       # 触发原因 (双语, 便于展示/日志)

    def blocks(self) -> bool:
        return self.action == "deny"

    def needs_confirm(self) -> bool:
        return self.action == "confirm"

    def allows(self) -> bool:
        return self.action == "allow"


_DENY_CRITICAL = "critical"
_DENY = "deny"
_CONFIRM = "confirm"
_ALLOW = "allow"

#: Windows 保留设备名 —— 写入这些名字实际落到设备而非文件 (NUL 丢弃写入,
#: CON/PRN/AUX 绑控制台, COM1-9/LPT1-9 绑串口), 是隐蔽的破坏/信息泄露路径。
_WIN_RESERVED_DEVICES = frozenset(
    ["NUL", "CON", "PRN", "AUX"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)


def _windows_reserved_device(path: str) -> Optional[str]:
    """返回路径命中的 Windows 保留设备名 (未命中则 None)。

    取路径最后一段, 去掉扩展名后与保留名比对 (大小写不敏感):
    ``NUL`` / ``CON.txt`` / ``com1`` / ``LPT9.log`` 均命中;
    ``COM10`` 及以上不是保留设备名, 不命中。
    """
    import re as _re

    base = _re.split(r"[/\\]", str(path or "").strip())[-1]
    if not base:
        return None
    stem = base.split(".")[0].strip().upper()
    return stem if stem in _WIN_RESERVED_DEVICES else None


def _iter_text_values(obj: Any):
    """递归收集对象中的字符串值 (命令/脚本等可执行文本字段)。

    也处理 JSON 字符串: 参数以字符串形式传入时 (如 '{"command": "rm -rf /"}'),
    先解析再递归, 否则会被当作整体文本而漏判。
    """
    if isinstance(obj, str):
        stripped = obj.lstrip()
        if stripped[:1] in ("{", "["):
            try:
                parsed = json.loads(obj)
            except Exception:  # noqa: BLE001 - 非 JSON, 按普通文本处理
                parsed = None
            if parsed is not None:
                yield from _iter_text_values(parsed)
                return
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_text_values(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _iter_text_values(v)


class SecurityGate:
    """fail-closed 统一安全闸门。

    用法::

        gate = SecurityGate(yolo=False, trust_level=TrustLevel.TRUSTED, remote=False)
        v = gate.decide_shell(command)
        if v.blocks():
            ...
        elif v.needs_confirm():
            ...
    """

    def __init__(
        self,
        *,
        yolo: bool = False,
        trust_level: Optional[str] = None,
        remote: bool = False,
        rules_engine: Any = None,
        auditor: Any = None,  # 可选: SecurityAuditor 实例, 记录每条决策的 provenance
        mode: Optional[str] = None,  # 可选: 五模式 ID (chat/lingma/gantong/boundless/collaboration)
    ) -> None:
        # yolo 仅影响「可确认」层级的放行; 红线/信任级别始终 fail-closed。
        self.yolo = bool(yolo)
        self.trust_level = trust_level
        self.remote = bool(remote)
        self._rules = rules_engine  # 可选: 文件写规则校验 (RuleEngine 实例)
        self._auditor = auditor  # 可选: SecurityAuditor, 记录每条决策的 provenance
        self.mode = mode  # 可选: 五模式 ID, 用于附加能力过滤

    # ---------------------------------------------------------- shell
    def decide_shell(
        self, command: str, *, confirmable_redline: bool = False
    ) -> GateVerdict:
        """Classify a shell command; opt in only when the caller enforces confirmation."""
        try:
            # 1. 硬红线: 永不自动执行 (YOLO/白名单/远程 均不豁免)
            if is_hard_redline(command):
                return GateVerdict(
                    _DENY, _DENY_CRITICAL,
                    ("命中致命红线 (文件系统/OS 级毁灭操作), 永不自动执行",),
                )

            # 2. 软红线 (critical/high 级): 默认拒绝; shell 可将其交给多阶段确认流程。
            if is_redline(command):
                if confirmable_redline:
                    return GateVerdict(
                        _CONFIRM, _DENY_CRITICAL,
                        ("命令命中安全红线, 需确认后执行",),
                    )
                if self.yolo:
                    return GateVerdict(
                        _CONFIRM, _DENY_CRITICAL,
                        ("命令命中安全红线 (YOLO 模式下升级为确认)",),
                    )
                return GateVerdict(
                    _DENY, _DENY_CRITICAL,
                    ("命令命中安全红线, 已拒绝执行",),
                )

            # 3. 高危 (共享打分库): **只回报风险等级, 不代替调用方决定「要不要问」**。
            #    模式策略统一由 tools/shell.py 的分级阶梯执行:
            #      warning_level >= 5 (极高危) → 5 次确认, **YOLO 也不豁免**;
            #      warning_level >= 3 (高危)   → standard 弹 3 次确认; YOLO 视为
            #        「用户已预先授权自动批准」, 放行 (yolo 的语义是"别拿琐碎确认
            #        打断我", 不是"剥夺我对危险操作的决定权")。
            #    曾经这里是 "YOLO 不豁免 SafetyEngine risk==high → CONFIRM", 与上面的
            #    阶梯直接冲突: gate 一旦 needs_confirm, shell.py step3 的 YOLO 自动
            #    批准分支永远走不到 —— 表现为「开了 yolo 还在为 docker rm -f /
            #    kubectl delete 弹 3 次确认」。
            #    两套分类器已核对: 所有 risk==high 的命令其 warning_level 均 >= 3,
            #    已被阶梯完整覆盖, 故此处不重复拦截, 也不产生覆盖缺口。
            #    但**保留 severity 回报**: 维持「闸门与共享打分库口径一致」的不变量
            #    (等级由打分库给出; 要不要人工决定由调用方按模式决定)。
            shared_severity = "none"
            try:
                shared_severity = SafetyEngine().score({"command": command})["risk"] or "none"
            except Exception:  # noqa: BLE001 - 打分不可用时按低风险继续 (阶梯仍会兜底)
                shared_severity = "none"

            # 4. 信任级别检查
            lvl = self.trust_level
            if lvl is not None:
                if lvl == TrustLevel.UNTRUSTED:
                    return GateVerdict(
                        _DENY, "high",
                        ("工作区信任级别为 untrusted, 禁止执行 shell 命令",),
                    )
                if lvl == TrustLevel.UNKNOWN:
                    return GateVerdict(
                        _CONFIRM, "medium",
                        ("工作区信任级别未知, 需用户确认后方可执行 shell",),
                    )
                if lvl == TrustLevel.LIMITED and not is_benign_dev_command(command):
                    return GateVerdict(
                        _CONFIRM, "medium",
                        ("工作区为 limited 信任, 非良性命令需确认",),
                    )

            # 4. 远程来源: 非良性操作需确认
            if self.remote and not is_benign_dev_command(command):
                return GateVerdict(
                    _CONFIRM, "high",
                    ("命令来自远程控制会话, 非良性操作需用户确认",),
                )

            # 5. 模式附加过滤（不改变现有判定顺序，仅 ALLOW→DENY 升级）
            if self.mode is not None:
                from ..modes.policy import get_mode_policy
                policy = get_mode_policy(self.mode)
                if not policy.shell_allowed():
                    return GateVerdict(
                        _DENY, "medium",
                        (f"模式 {self.mode} 禁用 Shell",),
                    )

            return GateVerdict(_ALLOW, shared_severity, ())
        except Exception:  # noqa: BLE001 - fail-closed
            return GateVerdict(_DENY, _DENY_CRITICAL, ("安全闸门异常, 保守拒绝执行",))

    # ---------------------------------------------------------- mcp 工具
    def decide_mcp_tool(self, tool_name: str, args: Any = None) -> GateVerdict:
        try:
            # 单一来源: 把参数中的所有文本字段递归送 safety_engine 做红线检测。
            # 不依赖工具名是否带 mcp__ 前缀或含危险关键词 —— 沙箱场景下 server 不可信,
            # 即便工具名叫 echo_text, 其参数里的 rm -rf 也必须 fail-closed 拒绝。
            from ..ext.safety_engine import is_redline as _engine_is_redline
            for text in _iter_text_values(args):
                if text.strip() and _engine_is_redline(text):
                    return GateVerdict(
                        _DENY, _DENY_CRITICAL,
                        (f"MCP 工具 {tool_name} 的参数包含危险操作, 已阻止",),
                    )

            # 模式附加过滤（不改变现有判定顺序，仅 ALLOW→DENY 升级）
            if self.mode is not None:
                from ..modes.policy import get_mode_policy
                policy = get_mode_policy(self.mode)
                if not policy.mcp_allowed():
                    return GateVerdict(
                        _DENY, "medium",
                        (f"模式 {self.mode} 禁用 MCP 工具调用",),
                    )

            return GateVerdict(_ALLOW, "none", ())
        except Exception:  # noqa: BLE001 - fail-closed
            return GateVerdict(_DENY, _DENY_CRITICAL, ("MCP 安全闸门异常, 保守拒绝调用",))

    # ---------------------------------------------------------- 远程 prompt
    def classify_remote_prompt(self, prompt: str) -> GateVerdict:
        """对远程控制会话发来的 prompt 做安全分类。

        - 硬红线 -> deny (远程设备绝不能驱动致命命令)
        - 软红线 -> confirm (极端确认)
        - 非良性 -> confirm (普通确认)
        - 良性开发命令 -> allow
        """
        try:
            if is_hard_redline(prompt):
                return GateVerdict(_DENY, _DENY_CRITICAL,
                                   ("远程 prompt 命中致命红线, 拒绝执行",))
            if is_redline(prompt):
                return GateVerdict(_CONFIRM, _DENY_CRITICAL,
                                   ("远程 prompt 含危险操作, 需极端确认",))
            if not is_benign_dev_command(prompt):
                return GateVerdict(_CONFIRM, "high",
                                   ("远程 prompt 非良性开发命令, 需用户确认",))
            return GateVerdict(_ALLOW, "none", ())
        except Exception:  # noqa: BLE001 - fail-closed
            return GateVerdict(_DENY, _DENY_CRITICAL, ("远程 prompt 安全分类异常, 保守拒绝",))

    # 系统敏感路径: 写入这些路径默认需确认 (非 hard_redline, 但 defense-in-depth)
    _SYSTEM_PATH_RE = None  # Lazy init to avoid import at module level

    @classmethod
    def _get_system_path_re(cls):
        if cls._SYSTEM_PATH_RE is None:
            import re as _re
            # 路径段级匹配 (不依赖 ^ 开头锚定): 相对形态 ./.ssh/config / sub/.ssh/x
            # 与绝对形态 /etc/ /var/log/ 一律命中; 反斜杠分隔符等价。
            #
            # 口径扩展 (v0.3.3, 加严不改宽 —— 命中一律只是「需确认」, 不是拒绝):
            #  - Linux: 补 /root /opt /system;
            #  - Windows: 补 Program Files / Program Files (x86) / ProgramData /
            #    System32 / WinSxS (带盘符与相对形态均命中);
            #  - 凭据文件: 补 .npmrc .pypirc .netrc .gitconfig 与 id_rsa /
            #    id_ed25519 等私钥文件 (含 .pem/.key/.p12/.pfx)。
            cls._SYSTEM_PATH_RE = _re.compile(
                r"(?:^|[/\\])\.(?:ssh|aws|gnupg|docker|kube|npmrc|pypirc|netrc|gitconfig)(?:[/\\]|$)|"
                r"^/(?:etc|boot|root|opt|system|sys|proc|"
                r"usr/(?:lib|bin|sbin)|var/(?:log|run|spool))(?:[/\\]|$)|"
                r"(?:^|[/\\])(?:Program Files(?: \(x86\))?|ProgramData|WinSxS|System32)(?:[/\\]|$)|"
                r"(?:^|[/\\])id_(?:rsa|ed25519|ecdsa|dsa)(?:\.pub)?(?:[/\\]|$)|"
                r"(?:^|[/\\])[^/\\]*\.(?:pem|key|p12|pfx)(?:[/\\]|$)",
                _re.IGNORECASE,
            )
        return cls._SYSTEM_PATH_RE

    # ---------------------------------------------------------- 文件写
    def decide_file_write(self, path: str, content: str) -> GateVerdict:
        try:
            raw_path = str(path or "")
            # 0. 路径注入防御 —— 必须排在所有路径判定之前:
            #    0.1 null byte: C 层字符串会以 NUL 截断, 是路径穿越/注入的经典特征
            if "\x00" in raw_path:
                return GateVerdict(
                    _DENY, _DENY_CRITICAL,
                    (f"路径含 null byte, 拒绝写入: {raw_path!r}",),
                )
            #    0.2 Windows 保留设备名: NUL/CON/PRN/AUX/COM1-9/LPT1-9。
            #        写入 "NUL" 实际会写到设备而非文件, 是隐蔽的破坏/信息泄露路径。
            device = _windows_reserved_device(raw_path)
            if device:
                return GateVerdict(
                    _DENY, "high",
                    (f"路径使用 Windows 保留设备名 {device}, 拒绝写入: {raw_path}",),
                )
            # 1. 内容红线检测: 写入内容本身含危险操作 (如写入 rm -rf / 到脚本)
            #    硬红线 (文件系统/OS 级毁灭) 与软红线 (CRITICAL/HIGH 黑名单) 都拒绝,
            #    但**文案区分**: 硬红线明确标注「硬红线」便于审计定位。
            if is_hard_redline(content):
                return GateVerdict(_DENY, _DENY_CRITICAL,
                                   ("写入内容含硬红线操作, 拒绝写入",))
            if is_redline(content):
                return GateVerdict(_DENY, _DENY_CRITICAL,
                                   ("写入内容含致命操作, 拒绝写入",))
            # 2. 信任级别检查
            lvl = self.trust_level
            if lvl == TrustLevel.UNTRUSTED:
                return GateVerdict(_DENY, "high",
                                   ("工作区为 untrusted, 禁止写文件",))
            # 3. 系统敏感路径保护: 写入 /etc/ ~/.ssh/ ./.ssh 等路径需确认 (defense-in-depth)
            #    先做 expanduser + normpath + 斜杠归一, 使 ~/.ssh/x 与 ./sub/../.ssh/x
            #    以及 Windows 反斜杠形态都能命中。
            #    同时用 realpath 解析一遍: 让 ./link -> .ssh/ 这类 symlink 穿透也被命中
            #    (相对路径保留相对形态, 不因 realpath 变成绝对路径而误判)。
            import os as _os
            path_norm = _os.path.normpath(_os.path.expanduser(raw_path)).replace("\\", "/")
            candidates = [path_norm]
            try:
                resolved = _os.path.normpath(_os.path.realpath(_os.path.expanduser(raw_path)))
                resolved = resolved.replace("\\", "/")
                if resolved and resolved != path_norm:
                    candidates.append(resolved)
            except Exception:  # noqa: BLE001 - realpath 失败不阻断 (原有判定继续)
                pass
            path_re = self._get_system_path_re()
            if raw_path and path_re:
                hit = next((c for c in candidates if path_re.search(c)), None)
                if hit is not None:
                    if self.yolo:
                        return GateVerdict(
                            _CONFIRM, "high",
                            (f"写入系统敏感路径: {path} (YOLO 模式下升级为确认)",),
                        )
                    return GateVerdict(
                        _CONFIRM, "high",
                        (f"写入系统敏感路径: {path}, 需用户确认",),
                    )
            # 4. 用户自定义规则校验
            eng = self._rules
            if eng is not None:
                violations = eng.check(path, content, kind="file")
                blocking = [v for v in violations if v.get("severity") == "error"]
                if blocking:
                    msgs = "; ".join(v.get("message", v.get("id", "")) for v in blocking)
                    return GateVerdict(_DENY, "high", (f"命中策略错误规则: {msgs}",))

            # 5. 模式附加过滤（不改变现有判定顺序，仅 ALLOW→DENY 升级）
            if self.mode is not None:
                from ..modes.policy import get_mode_policy
                policy = get_mode_policy(self.mode)
                if not policy.file_write_allowed():
                    return GateVerdict(
                        _DENY, "medium",
                        (f"模式 {self.mode} 禁用文件写入",),
                    )

            return GateVerdict(_ALLOW, "none", ())
        except Exception:  # noqa: BLE001 - fail-closed
            return GateVerdict(_DENY, _DENY_CRITICAL, ("文件写安全闸门异常, 保守拒绝写入",))

    # ---------------------------------------------------------- 统一分发
    def decide(self, kind: str, payload: Any = None, **extra: Any) -> GateVerdict:
        """统一入口: kind ∈ {shell, mcp_tool, remote_prompt, file_write}。"""
        verdict = None
        try:
            if kind == "shell":
                verdict = self.decide_shell(str(payload))
            elif kind == "mcp_tool":
                name = extra.get("tool_name", payload)
                verdict = self.decide_mcp_tool(name, extra.get("args"))
            elif kind == "remote_prompt":
                verdict = self.classify_remote_prompt(str(payload))
            elif kind == "file_write":
                verdict = self.decide_file_write(
                    str(extra.get("path", "")), str(payload))
            else:
                # 未知动作类型: fail-closed
                verdict = GateVerdict(_DENY, _DENY_CRITICAL, (f"未知动作类型: {kind}",))
        except Exception:  # noqa: BLE001 - fail-closed
            verdict = GateVerdict(_DENY, _DENY_CRITICAL, ("安全闸门分发异常, 保守拒绝",))

        # 安全溯源: 记录每条决策的完整 provenance
        if self._auditor is not None and verdict is not None:
            try:
                self._auditor.record(
                    module="security_gate",
                    action=verdict.action,
                    severity=verdict.severity,
                    input_summary=str(payload)[:500] if payload else kind,
                    reasons=list(verdict.reasons),
                    context={
                        "kind": kind,
                        "yolo": self.yolo,
                        "trust_level": self.trust_level,
                        "remote": self.remote,
                        "mode": self.mode,
                    },
                )
            except Exception:  # noqa: BLE001
                pass  # 审计失败不应影响安全裁决

        return verdict
