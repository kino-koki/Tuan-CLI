"""沙箱缺口补齐测试 (round3 / group_sandbox)。

针对对照 Claude Code 审计发现的真实缺口:
  GAP-A: L0 意图滤网此前只 consult safety_engine(红线) + network_guard(网络外泄),
         完全不接 core/secret_scanner —— 写入/命令文本里内嵌的明文高风险密钥
         (AWS Access Key / GitHub token / OpenAI 风格 key / PEM 私钥) 会绕过沙箱。
         现补齐: 命中 high 级凭据 → CONFIRM(附修复建议); medium/无命中 → 放行。

本文件只覆盖"补齐内容"的回归, 既有行为仍由 test_sandbox_system.py 钉死。
"""
from __future__ import annotations

from tuan_cli.sandbox.verdict import Action, Payload, SEV
from tuan_cli.sandbox.filters import IntentFilter, _scan_embedded_secrets
from tuan_cli.sandbox.manager import SandboxManager


# ================================================================ GAP-A 单元
class TestEmbeddedSecretScan:
    def test_aws_key_triggers_confirm(self):
        v = IntentFilter().check(
            Payload(text=['cfg = "AKIAIOSFODNN7EXAMPLE"'])
        )
        assert v is not None
        assert v.action == Action.CONFIRM
        assert v.severity == SEV["high"]
        assert "AWS" in v.reason

    def test_pem_private_key_triggers_confirm(self):
        v = IntentFilter().check(
            Payload(text=["-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA"])
        )
        assert v is not None and v.action == Action.CONFIRM
        assert "私钥" in v.reason

    def test_github_token_triggers_confirm_with_remediation(self):
        v = IntentFilter().check(
            Payload(text=["token = ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ab"])
        )
        assert v is not None and v.action == Action.CONFIRM
        # 修复建议必须带上 (轮换/撤销 token)
        assert any("撤销" in s or "轮换" in s for s in v.suggestions)

    def test_benign_content_no_confirm(self):
        for txt in (
            'print("hello world")',
            "git status",
            "echo hi",
            "def add(a, b):\n    return a + b\n",
        ):
            v = IntentFilter().check(Payload(text=[txt]))
            # 良性文本绝不能因密钥扫描而升级为 confirm/deny
            assert v is None or v.action != Action.CONFIRM

    def test_medium_only_secret_does_not_confirm(self):
        """仅 medium 级 (JWT / 通用 key=value) 不触发确认, 避免误杀正常配置。"""
        # JWT 三段式 (medium)
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        v = IntentFilter().check(Payload(text=[f"jwt = {jwt}"]))
        assert v is None or v.action != Action.CONFIRM

    def test_redline_still_beats_secret(self):
        """致命红线优先级最高: 即便同时含密钥, 也必须是 DENY critical 而非 confirm。"""
        v = IntentFilter().check(
            Payload(text=['rm -rf / && echo "AKIAIOSFODNN7EXAMPLE"'])
        )
        assert v.action == Action.DENY
        assert v.severity == SEV["critical"]

    def test_scan_helper_never_raises_on_bad_text(self):
        assert _scan_embedded_secrets(["", "   "]) is None
        assert _scan_embedded_secrets([]) is None


# ================================================================ GAP-A 端到端 (manager)
class _Confirm:
    def __init__(self, accept: bool) -> None:
        self.accept = accept
        self.calls = 0

    def __call__(self, prompt: str) -> bool:
        self.calls += 1
        return self.accept


def _ctx(trust="trusted", yolo=False, confirm=None):
    return type("ctx", (), {
        "workspace": "/tmp/ws", "workspace_trust_level": trust,
        "plan_mode": False, "yolo": yolo, "safety_severity": None,
        "kernel": None, "confirm": confirm,
    })()


class TestAssessToolEmbeddedSecret:
    def test_write_secret_accept(self):
        m = SandboxManager({"enabled": True})
        acc = _Confirm(True)
        denied, msg = m.assess_tool(
            "write_file",
            {"path": "/tmp/ws/c.py", "content": 'KEY="AKIAIOSFODNN7EXAMPLE"'},
            _ctx(confirm=acc),
        )
        assert denied is False
        assert acc.calls == 1  # 确认通道被触发过

    def test_write_secret_reject(self):
        m = SandboxManager({"enabled": True})
        denied, msg = m.assess_tool(
            "write_file",
            {"path": "/tmp/ws/k.pem", "content": "-----BEGIN RSA PRIVATE KEY-----\nMIIE"},
            _ctx(confirm=_Confirm(False)),
        )
        assert denied is True
        assert "用户拒绝" in msg

    def test_no_confirm_channel_fails_closed(self):
        """无确认通道 + 非 yolo + 含密钥 → fail-closed 拒绝, 不得放行。"""
        m = SandboxManager({"enabled": True})
        denied, msg = m.assess_tool(
            "write_file",
            {"path": "/tmp/ws/c.py", "content": 'KEY="AKIAIOSFODNN7EXAMPLE"'},
            _ctx(confirm=None),
        )
        assert denied is True
        assert "确认" in msg

    def test_yolo_optout_skips_confirm(self):
        """yolo 模式用户已声明免确认, 密钥扫描降为放行 (红线仍硬拒)。"""
        m = SandboxManager({"enabled": True})
        denied, msg = m.assess_tool(
            "write_file",
            {"path": "/tmp/ws/c.py", "content": 'KEY="AKIAIOSFODNN7EXAMPLE"'},
            _ctx(yolo=True),
        )
        assert denied is False

    def test_plain_write_still_passes(self):
        m = SandboxManager({"enabled": True})
        denied, msg = m.assess_tool(
            "write_file",
            {"path": "/tmp/ws/ok.py", "content": 'print("hello")'},
            _ctx(confirm=_Confirm(True)),
        )
        assert denied is False
