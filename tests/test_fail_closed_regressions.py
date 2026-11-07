"""安全加固回归: 证明「异常路径不会变成放行」以及 fail-closed 默认值一致。

对应修复:
  R1  SandboxManager.DEFAULT_POLICY.enforce_required 与 config/defaults.py 统一为 True
  R2  显式指定的强后端不可用时不回落 (pick_backend 返回 available=False)
  R3  filters.py 中 6 处「异常即放行」改为 fail-closed
  R4  会执行仓库内代码的命令 (pip/npm/pytest/make...) 升级为人工确认

这些用例全部不依赖 docker / bwrap / seatbelt, 可在任意环境复跑。
"""
from __future__ import annotations

import sys

import pytest

from tuan_cli.sandbox.backends import pick_backend
from tuan_cli.sandbox.filters import (
    HardIsolationFilter,
    IntentFilter,
    ResourceFilter,
    TrustFilter,
    _has_network_request,
    _repo_code_execution_risk,
)
from tuan_cli.sandbox.manager import DEFAULT_POLICY, SandboxManager
from tuan_cli.sandbox.verdict import Action, Payload, SEV, Verdict
from tuan_cli.config import defaults as DEFAULTS


def _boom(*_a, **_kw):
    raise RuntimeError("simulated subsystem failure")


# ---------------------------------------------------------------- R1 默认值
class TestFailClosedDefaults:
    def test_manager_default_matches_config_default(self):
        """两套默认值必须一致, 否则 `sandbox:` 段覆盖后漏写该键会静默降级。"""
        assert DEFAULT_POLICY["enforce_required"] is True
        assert DEFAULTS.DEFAULT_CONFIG["sandbox"]["enforce_required"] is True

    def test_manager_instance_is_fail_closed_by_default(self):
        assert SandboxManager({"enabled": True}).policy["enforce_required"] is True

    def test_partial_policy_override_keeps_fail_closed(self):
        """只覆盖 backend 时, enforce_required 不得回落到 False。"""
        m = SandboxManager({"enabled": True, "backend": "auto"})
        assert m.policy["enforce_required"] is True


# ---------------------------------------------------------------- R2 后端选择
class TestBackendNoSilentFallback:
    def test_explicit_unavailable_backend_returns_false(self):
        name, ok = pick_backend("no-such-backend-xyz")
        assert name == "no-such-backend-xyz"
        assert ok is False

    def test_auto_still_selects_a_backend(self):
        name, ok = pick_backend("auto")
        assert name in ("landlock", "docker", "seatbelt", "token-acl", "jobobject", "local")
        assert isinstance(ok, bool)

    def test_hard_filter_denies_when_no_strong_backend(self, monkeypatch):
        """强隔离被要求但只有 local 可用 -> DENY, 不静默裸执行。"""
        import tuan_cli.sandbox.backends as b

        monkeypatch.setattr(b, "pick_backend", lambda prefer="auto": ("local", True))
        v = Verdict()
        v.isolate = True
        out = HardIsolationFilter(enforce_require=True).check(v, Payload(text=["echo hi"]))
        assert out is not None
        assert out.action == Action.DENY
        assert "fail-closed" in out.reason


# ---------------------------------------------------------------- R3 fail-closed
class TestExceptionPathsFailClosed:
    def test_network_probe_exception_is_treated_as_network_request(self, monkeypatch):
        import tuan_cli.core.network_guard as ng

        monkeypatch.setattr(ng, "get_network_guard", _boom)
        assert _has_network_request(["curl https://example.com"]) is True

    def test_redline_engine_unavailable_denies_critical(self, monkeypatch):
        """红线引擎导入失败时不得继续按「无红线」处理。"""
        monkeypatch.setitem(sys.modules, "tuan_cli.ext.safety_engine", None)
        v = IntentFilter().check(Payload(text=["echo hi"]))
        assert v is not None
        assert v.action == Action.DENY
        assert v.severity == SEV["critical"]
        assert "fail-closed" in v.reason

    def test_network_guard_exception_denies_high(self, monkeypatch):
        import tuan_cli.core.network_guard as ng

        monkeypatch.setattr(ng, "get_network_guard", _boom)
        v = IntentFilter().check(Payload(text=["echo hi"]))
        assert v is not None
        assert v.action == Action.DENY
        assert v.severity == SEV["high"]
        assert "fail-closed" in v.reason

    def test_domain_allowlist_exception_denies(self, monkeypatch):
        import tuan_cli.core.network_guard as ng

        monkeypatch.setattr(ng, "get_network_guard", _boom)
        p = Payload(text=["curl https://evil.example"], meta={"allowed_domains": ["good.example"]})
        v = TrustFilter().check(p)
        assert v is not None
        assert v.action == Action.DENY
        assert "fail-closed" in v.reason

    def test_embedded_secret_scan_exception_escalates_to_confirm(self, monkeypatch):
        import tuan_cli.core.secret_scanner as ss

        monkeypatch.setattr(ss, "scan_text", _boom)
        v = IntentFilter().check(Payload(text=["echo AKIAIOSFODNN7EXAMPLE"]))
        assert v is not None
        assert v.action == Action.CONFIRM
        assert "fail-closed" in v.reason

    def test_resource_filter_isolates_network_when_deny_net_enabled(self, monkeypatch):
        import tuan_cli.core.network_guard as ng

        monkeypatch.setattr(ng, "get_network_guard", _boom)
        v = ResourceFilter(deny_network_by_default=True).check(Payload(text=["curl https://x"]))
        assert v is not None
        assert v.network is False
        assert v.isolate is True


# ---------------------------------------------------------------- R4 仓库代码执行面
class TestRepoCodeExecutionGate:
    @pytest.mark.parametrize("cmd", [
        "pip install requests",
        "python -m pip install -e .",
        "npm install",
        "npm ci",
        "pnpm install",
        "yarn install",
        "poetry install",
        "uv sync",
        "pytest -q",
        "python -m pytest tests/",
        "tox",
        "go test ./...",
        "cargo test",
        "mvn test",
        "make build",
        "composer install",
    ])
    def test_installer_and_test_runners_require_confirmation(self, cmd):
        assert _repo_code_execution_risk([cmd]) is True
        v = IntentFilter().check(Payload(text=[cmd], trust_level="trusted"))
        assert v is not None
        assert v.action == Action.CONFIRM
        assert "仓库内代码" in v.reason

    @pytest.mark.parametrize("cmd", [
        "git status",
        "ls -la",
        "echo hi",
        "git commit -m 'fix'",
        "cat README.md",
        "pip --version",
        "pytest --help",
        "npm --version",
    ])
    def test_readonly_and_help_variants_stay_benign(self, cmd):
        assert _repo_code_execution_risk([cmd]) is False
        v = IntentFilter().check(Payload(text=[cmd], trust_level="trusted"))
        assert v is None or v.action != Action.DENY

    def test_recognition_failure_fails_closed(self):
        """识别过程本身出错时, 按「有风险」处理, 绝不返回 False。"""
        class Unparseable:
            def strip(self):
                raise RuntimeError("boom")

        assert _repo_code_execution_risk([Unparseable()]) is True
