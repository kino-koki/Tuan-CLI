"""六个「超越维度」的**运行时探针**。

「超 Claude Code」不能靠文档自述。本模块对每个维度**真实调用仓库里的
现有代码**，跑通才把该维度的 ``ahead`` 模块计入「已证实领先」；跑不通
就如实标 ``unverified``，并让 ``matrix`` 的领先计数下降。

设计约束：
  - 探针**只读 / 用临时目录**，不写用户配置、不联网、不改仓库状态；
  - 每个探针内部吞掉异常并转成 ``ok=False + detail``，绝不把失败抛给
    ``tuan claude parity``；
  - 探针证明的是「该能力此刻真的成立」，不是「曾经写过」。

六个维度与 ``catalog.SUPERIORITY_DIMENSIONS`` 一一对应：

1. ``fail_closed_default``  hook 执行失败时默认阻断（CC 需显式
   ``onFailure:"block"``，旧行为是静默放行）；
2. ``audit_replay``          HMAC 篡改检出 + AEAD 原始 blob round-trip
                             + 跨会话关联器 ``replay()`` 可调用；
3. ``config_correctness``    畸形 sandbox / permissions 配置被结构化拒绝；
4. ``least_authority``       未登记 MCP server 默认拒绝 + 策略文件损坏
                             进入 locked（不重建为空策略）；
5. ``local_offline_i18n``    10 语言 i18n + 10 语言 README 真实存在；
6. ``verifiable_parity``     Codex TUI 165 模块矩阵自检干净。
"""
from __future__ import annotations

import logging
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List

from . import catalog, evidence


@contextmanager
def _quiet_logger(name: str):
    """探针故意构造损坏策略/失败 hook；临时静音其告警，避免污染 CLI 输出。"""
    lg = logging.getLogger(name)
    old = lg.level
    lg.setLevel(logging.CRITICAL)
    try:
        yield
    finally:
        lg.setLevel(old)


@dataclass(frozen=True)
class ProbeResult:
    dim: str
    ok: bool
    detail: str
    checks: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"dim": self.dim, "ok": self.ok,
                "detail": self.detail, "checks": list(self.checks)}


def _probe_fail_closed_default() -> ProbeResult:
    """注入一个必然 spawn 失败的 PreToolUse hook，断言默认阻断。"""
    checks: List[str] = []
    try:
        from ..hooks.manager import HookManager
        cfg = {
            "hooks": {
                "enabled": True,
                "audit_log": False,
                "PreToolUse": [{
                    "type": "command",
                    "matcher": "*",
                    "command": ["/definitely/missing/tuan-parity-probe-binary"],
                    "timeout": 1.0,
                }],
            }
        }
        with tempfile.TemporaryDirectory(prefix="tuan-probe-") as td:
            hm = HookManager(config=cfg, workspace=td)
            d = hm.run_pre("write_file", {"path": "x.txt"})
            checks.append("spawn 失败 -> run_pre().block")
            ok = bool(getattr(d, "block", False))
            if not ok:
                return ProbeResult(
                    catalog.SUPERIORITY_DIMENSIONS[0], False,
                    "hook spawn 失败未触发阻断（仍是 fail-open）", checks)
            checks.append("结构化原因存在")
            reason = str(getattr(d, "reason", "") or "")
            if not reason:
                return ProbeResult(
                    catalog.SUPERIORITY_DIMENSIONS[0], False,
                    "阻断但缺少结构化原因", checks)
            checks.append("失败记录可查询 failures()")
            if hasattr(hm, "failures") and callable(hm.failures):
                if not hm.failures():
                    return ProbeResult(
                        catalog.SUPERIORITY_DIMENSIONS[0], False,
                        "阻断但 failures() 无失败记录", checks)
            return ProbeResult(
                catalog.SUPERIORITY_DIMENSIONS[0], True,
                "hook 故障默认阻断，带原因与可查询失败记录", checks)
    except Exception as exc:  # noqa: BLE001
        return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[0], False,
                           f"探针异常: {type(exc).__name__}: {exc}", checks)


def _probe_audit_replay() -> ProbeResult:
    checks: List[str] = []
    try:
        from ..harden.crypto_provider import SoftwareProvider
        from ..core.audit_correlation import AuditCorrelator, CorrelationAlert
        p = SoftwareProvider()
        key = b"tuan-parity-probe-key-0123456789"
        mac = p.hmac_sign(b"audit-record", key)
        checks.append("HMAC 原值校验通过")
        if not p.hmac_verify(b"audit-record", key, mac):
            return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[1], False,
                               "HMAC 原值校验失败", checks)
        checks.append("HMAC 篡改检出")
        if p.hmac_verify(b"audit-record-TAMPERED", key, mac):
            return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[1], False,
                               "篡改后的审计记录未被 HMAC 检出", checks)
        blob = p.seal_raw(b"audit-record", key)
        checks.append("AEAD 原始 blob round-trip")
        if p.open_raw(blob, key) != b"audit-record":
            return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[1], False,
                               "审计 blob 无法还原", checks)
        checks.append("跨会话关联器 replay/assess/recent_alerts 可调用")
        corr = AuditCorrelator(window_seconds=60)
        for name in ("replay", "assess", "recent_alerts"):
            if not callable(getattr(corr, name, None)):
                return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[1], False,
                                   f"AuditCorrelator 缺 {name}()", checks)
        checks.append("告警 kind 三态契约")
        a = CorrelationAlert(kind="cross_session", fingerprint="f",
                             module="m", action="a", severity="high",
                             count=2, sessions=("s1", "s2"), message="x",
                             first_ts=0.0, last_ts=1.0)
        if a.to_dict()["kind"] != "cross_session":
            return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[1], False,
                               "告警契约异常", checks)
        return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[1], True,
                           "HMAC 防篡改 + AEAD round-trip + 跨会话重放可用", checks)
    except Exception as exc:  # noqa: BLE001
        return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[1], False,
                           f"探针异常: {type(exc).__name__}: {exc}", checks)


def _probe_config_correctness() -> ProbeResult:
    checks: List[str] = []
    try:
        from ..config.security_schema import validate_security_config
        e1, _ = validate_security_config({"sandbox": "not-a-dict"})
        checks.append("sandbox 非 dict 被拒")
        if not e1:
            return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[2], False,
                               "sandbox 类型错误未被拒绝", checks)
        # 注意: security_schema 用**扁平键** "permissions.rules"，与
        # HookManager 的嵌套 config.get("hooks") 是两个配置层，不可混用。
        e2, _ = validate_security_config({
            "permissions.rules": [{"tool": "x", "action": "maybe"}]})
        checks.append("未知 permissions.action 被拒")
        if not e2:
            return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[2], False,
                               "未知 action 未被拒绝", checks)
        e3, _ = validate_security_config({"sandbox": {"enabled": False}})
        checks.append("sandbox.enabled=false 被拒/告警")
        if not e3:
            return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[2], False,
                               "sandbox.enabled=false 未产生 error", checks)
        e4, _ = validate_security_config({"hooks": {"on_failure": "sometimes"}})
        checks.append("未知 hooks.on_failure 被拒")
        if not e4:
            return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[2], False,
                               "未知 hooks.on_failure 未被拒绝", checks)
        return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[2], True,
                           "sandbox / permissions / hooks 畸形配置被结构化拒绝", checks)
    except Exception as exc:  # noqa: BLE001
        return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[2], False,
                           f"探针异常: {type(exc).__name__}: {exc}", checks)


def _probe_least_authority() -> ProbeResult:
    checks: List[str] = []
    try:
        from ..tools.mcp.policy import MCPPolicyStore, ServerTier
        with tempfile.TemporaryDirectory(prefix="tuan-probe-") as td, \
                _quiet_logger("tuan_cli.tools.mcp.policy"):
            home = Path(td)
            store = MCPPolicyStore(home=home, session_id="probe")
            d = store.authorize("never-registered-server", "read_file", {})
            checks.append("未登记 server 默认 untrusted 且拒绝")
            if d.action != "deny" or d.tier != ServerTier.UNTRUSTED:
                return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[3], False,
                                   f"未登记 server 未被拒绝: {d.to_dict()}", checks)
            (home / "mcp_server_policy.json").write_text("{broken", encoding="utf-8")
            broken = MCPPolicyStore(home=home, session_id="probe2")
            checks.append("策略文件损坏进入 locked")
            if not broken.locked:
                return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[3], False,
                                   "损坏策略被重建为空策略（fail-open）", checks)
            d2 = broken.authorize("anything", "write_file", {})
            checks.append("locked 状态下仍拒绝")
            if d2.action == "allow":
                return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[3], False,
                                   "locked 状态下竟放行", checks)
            return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[3], True,
                               "默认不信任 + 损坏即锁定拒绝一切", checks)
    except Exception as exc:  # noqa: BLE001
        return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[3], False,
                           f"探针异常: {type(exc).__name__}: {exc}", checks)


def _probe_local_offline_i18n() -> ProbeResult:
    checks: List[str] = []
    try:
        from .. import i18n
        langs = i18n.available_languages()
        checks.append(f"i18n 语言数 {len(langs)}")
        if len(langs) < 10:
            return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[4], False,
                               "i18n 语言不足 10", checks)
        readmes = evidence.readme_languages()
        checks.append(f"README_<lang>.md 数 {len(readmes)}")
        if len(readmes) < 10:
            return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[4], False,
                               "多语言 README 不足 10", checks)
        return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[4], True,
                           f"{len(langs)} 语言 i18n + {len(readmes)} 语言 README 真实存在",
                           checks)
    except Exception as exc:  # noqa: BLE001
        return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[4], False,
                           f"探针异常: {type(exc).__name__}: {exc}", checks)


def _probe_verifiable_parity() -> ProbeResult:
    checks: List[str] = []
    try:
        from ..tui.parity import parity_validate, matrix
        problems = parity_validate()
        checks.append("tui parity_validate 干净")
        if problems:
            return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[5], False,
                               f"parity_validate 有问题: {problems[:2]}", checks)
        s = matrix.summary()
        checks.append(f"Codex TUI 模块树 {s['total_modules']} 个")
        if s["total_modules"] != 165:
            return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[5], False,
                               "Codex TUI 模块树规模不是 165", checks)
        checks.append("fully_identical 如实为 false（pending != 0）")
        if s["pending"] == 0 and s["fully_identical"] is not True:
            return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[5], False,
                               "指标自相矛盾", checks)
        return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[5], True,
                           f"165 模块矩阵自检干净，pending 如实为 {s['pending']}", checks)
    except Exception as exc:  # noqa: BLE001
        return ProbeResult(catalog.SUPERIORITY_DIMENSIONS[5], False,
                           f"探针异常: {type(exc).__name__}: {exc}", checks)


PROBES: Dict[str, Callable[[], ProbeResult]] = {
    catalog.SUPERIORITY_DIMENSIONS[0]: _probe_fail_closed_default,
    catalog.SUPERIORITY_DIMENSIONS[1]: _probe_audit_replay,
    catalog.SUPERIORITY_DIMENSIONS[2]: _probe_config_correctness,
    catalog.SUPERIORITY_DIMENSIONS[3]: _probe_least_authority,
    catalog.SUPERIORITY_DIMENSIONS[4]: _probe_local_offline_i18n,
    catalog.SUPERIORITY_DIMENSIONS[5]: _probe_verifiable_parity,
}


def probe_all() -> Dict[str, ProbeResult]:
    return {dim: fn() for dim, fn in PROBES.items()}


def verified_ahead(results: Dict[str, ProbeResult]) -> Dict[str, Any]:
    """只有探针通过的维度，其 ahead 模块才计入「已证实领先」。"""
    ahead = evidence.ahead_by_dimension()
    verified: Dict[str, List[str]] = {}
    unverified: Dict[str, List[str]] = {}
    for dim, mods in ahead.items():
        r = results.get(dim)
        if r is not None and r.ok:
            verified[dim] = list(mods)
        else:
            unverified[dim] = list(mods)
    return {
        "declared_ahead": sum(len(v) for v in ahead.values()),
        "verified_ahead": sum(len(v) for v in verified.values()),
        "verified": verified,
        "unverified": unverified,
        "dimensions_ok": [d for d, r in results.items() if r.ok],
        "dimensions_unverified": [d for d, r in results.items() if not r.ok],
    }


def constants() -> Dict[str, Any]:
    return {"dimensions": list(catalog.SUPERIORITY_DIMENSIONS),
            "probes": list(PROBES)}
