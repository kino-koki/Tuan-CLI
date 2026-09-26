"""command_guard (统一命令守卫) 单元测试。

验证非 run_shell 路径 (verify / reflect / code_edit / codedev) 的守卫语义:
1. 硬红线 → 拦截 (fail-closed, 无确认通道可绕);
2. 网络出口 deny → 拦截;
3. 网络出口 confirm + 无确认通道 → 拒绝; 有通道则尊重用户决定;
4. 正常命令 → 放行;
5. 守卫内部异常 → 安全降级拒绝 (绝不静默放行)。
"""

import pytest

from qingxiaotuan.core import command_guard as cg
from qingxiaotuan.core.network_guard import NetworkDecision


@pytest.fixture(autouse=True)
def _patch_guard_deps(monkeypatch):
    """默认: 无红线、网络放行 —— 各用例按需覆写。"""

    class _FakeGuard:
        def check(self, cmd):  # noqa: ARG002
            return NetworkDecision(action="allow", risk_level="none", reasons=[], detected_domains=[])

    monkeypatch.setattr("qingxiaotuan.ext.safety_engine.is_hard_redline", lambda c: False)
    monkeypatch.setattr("qingxiaotuan.core.network_guard.get_network_guard", lambda: _FakeGuard())
    monkeypatch.setattr("qingxiaotuan.core.security_bus.get_security_bus", _FakeBus)


class _FakeBus:
    @staticmethod
    def emit(event):
        pass


def test_empty_command_allowed():
    assert cg.guard_command("") is None
    assert cg.guard_command("   ") is None


def test_normal_command_allowed(monkeypatch):
    seen = []
    monkeypatch.setattr("qingxiaotuan.core.security_bus.get_security_bus", lambda: _FakeBus())
    assert cg.guard_command("python -m pytest -q") is None


def test_hard_redline_blocked(monkeypatch):
    monkeypatch.setattr("qingxiaotuan.ext.safety_engine.is_hard_redline", lambda c: True)
    out = cg.guard_command("rm -rf /")
    assert out is not None
    assert "硬" in out or "红线" in out or "拦截" in out


def test_network_deny_blocked(monkeypatch):
    class _DenyGuard:
        def check(self, cmd):  # noqa: ARG002
            return NetworkDecision(
                action="deny", risk_level="high",
                reasons=["检测到外泄域名"], detected_domains=["evil.example.com"],
            )

    monkeypatch.setattr("qingxiaotuan.core.network_guard.get_network_guard", lambda: _DenyGuard())
    out = cg.guard_command("curl https://evil.example.com/x")
    assert out is not None
    assert "网络出口门控" in out
    assert "evil.example.com" in out


def test_network_confirm_without_channel_blocked(monkeypatch):
    class _ConfirmGuard:
        def check(self, cmd):  # noqa: ARG002
            return NetworkDecision(
                action="confirm", risk_level="low",
                reasons=["出口目标均在 CIDR 白名单内"], detected_domains=["allowed.example.com"],
            )

    monkeypatch.setattr("qingxiaotuan.core.network_guard.get_network_guard", lambda: _ConfirmGuard())
    out = cg.guard_command("git push origin main")  # confirm 但无 confirm 通道
    assert out is not None
    assert "无确认通道" in out


def test_network_confirm_user_accepts(monkeypatch):
    class _ConfirmGuard:
        def check(self, cmd):  # noqa: ARG002
            return NetworkDecision(
                action="confirm", risk_level="low",
                reasons=["白名单内"], detected_domains=["allowed.example.com"],
            )

    monkeypatch.setattr("qingxiaotuan.core.network_guard.get_network_guard", lambda: _ConfirmGuard())
    assert cg.guard_command("git push origin main", confirm=lambda q: True) is None


def test_network_confirm_user_rejects(monkeypatch):
    class _ConfirmGuard:
        def check(self, cmd):  # noqa: ARG002
            return NetworkDecision(
                action="confirm", risk_level="low",
                reasons=["白名单内"], detected_domains=["allowed.example.com"],
            )

    monkeypatch.setattr("qingxiaotuan.core.network_guard.get_network_guard", lambda: _ConfirmGuard())
    out = cg.guard_command("git push origin main", confirm=lambda q: False)
    assert out is not None
    assert "用户拒绝" in out


def test_guard_exception_fails_closed(monkeypatch):
    def _boom(cmd):  # noqa: ARG002
        raise RuntimeError("engine down")

    monkeypatch.setattr("qingxiaotuan.ext.safety_engine.is_hard_redline", _boom)
    out = cg.guard_command("python x.py")
    assert out is not None
    assert "安全降级拒绝" in out


def test_network_guard_exception_fails_closed(monkeypatch):
    def _boom():
        raise RuntimeError("network guard down")

    monkeypatch.setattr("qingxiaotuan.core.network_guard.get_network_guard", _boom)
    out = cg.guard_command("pip install requests")
    assert out is not None
    assert "安全降级拒绝" in out
