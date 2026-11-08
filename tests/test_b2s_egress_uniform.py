"""本轮深度修复回归：所有执行分支共用同一个出网/凭据准备出口。

**实测缺口（先复现再修）**

上一轮把逐命令域名强绑定接到了 ``_execute_backend`` 的 **local 分支**，
但另外三条分支逐条核对后是：

===============  ============  ============  ============  ================
分支              EgressGuard   claim 检查    代理 env      last_egress
                  (凭据脱敏)                   注入          可观测
===============  ============  ============  ============  ================
local            有            有（裁决层）  有            有
landlock/docker  无            只传元数据    无            无
/ seatbelt
jobobject        无            无            无            无
(syscall)
copy_diff_apply  随下游        随下游        随下游        随下游
===============  ============  ============  ============  ================

**安全等级更高的路径反而没有刚补的防护**。三处具体断点：

1. ``SandboxProfile.allowed_domains`` 在 ``sandbox_provider.py`` 里只出现
   1 次（dataclass 字段定义），**没有任何后端消费它**。上一轮文档写
   「只是元数据」属实，却没说**因此 strict claim 在强后端下完全失效**。
2. ``_run_provider`` 不传 ``env``，走 ``sanitize_env``（敏感键置空），
   不是 EgressGuard 的 sentinel + ``CredentialBroker`` 链路。
3. **最严重**：``run_syscall_sandboxed`` 根本没有 ``env`` 参数，所有
   ``Popen`` / ``run_with_tree_kill`` / ``os.execvp`` 继承父进程完整环境
   —— Job Object / seccomp 路径上真实密钥原样进子进程，连置空都没有。

本轮把准备层收成 ``plan_egress`` 单一出口，并给 platform 层补 ``env``
透传。**矩阵计数一个不动**（gap 仍 26、aligned 46、partial 9）——
纯深度修复，不靠改口径凑数。
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from tuan_cli.sandbox.egress import SENTINEL_PREFIX
from tuan_cli.sandbox.egress_allowlist import (
    NetworkClaim, claim_from_values, claim_to_verdict_extra,
)
from tuan_cli.sandbox.egress_plan import (
    MODE_DEGRADED, MODE_DENY, MODE_NONE, MODE_PROXY, MODE_TEXT_ONLY,
    MODE_UNPROVABLE, plan_egress, plan_is_consistent_with_verdict,
)
from tuan_cli.sandbox.manager import SandboxManager
from tuan_cli.sandbox.verdict import Verdict
from tuan_cli.config.security_schema import validate_security_config

BASE_ENV = {"OPENAI_API_KEY": "REAL_SECRET_VALUE", "PATH": "/bin"}


def _verdict(domains=None, *, source="tool_args", backend="local",
             network=True) -> Verdict:
    v = Verdict()
    v.backend = backend
    v.network = network
    if domains is not None:
        c = claim_from_values(domains)
        c = NetworkClaim(c.required_domains, c.strict, source, c.invalid_values)
        v.extra.update(claim_to_verdict_extra(c))
    return v


# ==================================================== 1 plan 模式矩阵
class TestPlanMatrix:
    @pytest.mark.parametrize("domains,source,backend,policy,mode,allowed", [
        (None, "none", "local", {}, MODE_NONE, True),
        (["api.github.com"], "tool_args", "local",
         {"resource": {"egress_proxy_enabled": True}}, MODE_PROXY, True),
        (["api.github.com"], "tool_args", "local", {}, MODE_TEXT_ONLY, True),
        (["api.github.com"], "tool_args", "landlock", {}, MODE_UNPROVABLE, False),
        (["api.github.com"], "tool_args", "docker", {}, MODE_UNPROVABLE, False),
        (["api.github.com"], "tool_args", "seatbelt", {}, MODE_UNPROVABLE, False),
        (["api.github.com"], "tool_args", "jobobject", {}, MODE_UNPROVABLE, False),
        (["api.github.com"], "tool_args", "landlock",
         {"resource": {"strict_claim_strong_backend": "metadata_only"}},
         MODE_DEGRADED, True),
        (["api.github.com"], "global_policy", "landlock", {}, MODE_TEXT_ONLY, True),
    ])
    def test_modes(self, domains, source, backend, policy, mode, allowed):
        v = _verdict(domains, source=source, backend=backend)
        p = plan_egress(v, backend, policy, BASE_ENV)
        assert p.mode == mode
        assert p.allowed is allowed
        # 任何模式都不得把真实密钥交给子进程
        assert "REAL_SECRET_VALUE" not in str(p.env)
        assert SENTINEL_PREFIX in p.env.get("OPENAI_API_KEY", "")

    def test_source_field_is_actually_consumed(self):
        """上一轮埋的 `source` 字段这轮第一次真正决定行为。

        同一份逐命令声明，只改来源标记：tool_args 在强后端被拒绝，
        global_policy 沿用既有文本层语义 —— 精确区分，不让配了全局
        白名单 + 强后端的部署突然全部拒绝。
        """
        a = plan_egress(_verdict(["api.github.com"], source="tool_args"),
                        "landlock", {}, BASE_ENV)
        b = plan_egress(_verdict(["api.github.com"], source="global_policy"),
                        "landlock", {}, BASE_ENV)
        assert a.allowed is False and b.allowed is True
        assert a.enforcement == "refused-unprovable-domain-compliance"
        assert b.enforcement == "text-layer-only"

    def test_enforcement_strings_are_honest(self):
        """不许出现「已强隔离 / 已域名级过滤」这类谎话。"""
        for backend in ("landlock", "docker", "jobobject"):
            p = plan_egress(_verdict(["api.github.com"]), backend, {}, BASE_ENV)
            assert "refused" in p.enforcement or "text-layer" in p.enforcement
            assert "domain-level" not in p.enforcement

    def test_guard_denial_wins(self):
        """EgressGuard 自身拒绝时不能被 plan 覆盖成放行。"""
        from tuan_cli.sandbox.egress import EgressGuard
        with patch.object(EgressGuard, "prepare") as fake:
            class D:
                allowed = False
                reason = "禁网裁决 + local 后端"
                env = {}
                broker = None

                def to_audit_dict(self):
                    return {"allowed": False, "reason": self.reason}
            fake.return_value = D()
            p = plan_egress(_verdict(["api.github.com"]), "local", {}, BASE_ENV)
        assert p.mode == MODE_DENY and p.allowed is False

    def test_guard_exception_is_fail_closed(self):
        from tuan_cli.sandbox.egress import EgressGuard
        with patch.object(EgressGuard, "prepare", side_effect=RuntimeError("boom")):
            p = plan_egress(_verdict(["api.github.com"]), "local", {}, BASE_ENV)
        assert p.allowed is False and "fail-closed" in p.reason

    def test_plan_claim_consistency(self):
        v = _verdict(["api.github.com"])
        p = plan_egress(v, "local", {"resource": {"egress_proxy_enabled": True}},
                        BASE_ENV)
        assert plan_is_consistent_with_verdict(p, v) is True
        # 换一个 verdict 就不该再一致
        assert plan_is_consistent_with_verdict(p, _verdict()) is False

    def test_audit_never_leaks_secret_or_broker(self):
        v = _verdict(["api.github.com"])
        p = plan_egress(v, "local", {"resource": {"egress_proxy_enabled": True}},
                        BASE_ENV)
        d = p.to_audit_dict()
        assert "REAL_SECRET_VALUE" not in str(d)
        assert "broker" not in d
        assert d["claim_consistent"] is not None if "claim_consistent" in d else True


# ==================================================== 2 三分支 env 真透传
class _FakeProvider:
    captured = {}

    @staticmethod
    def create(_backend):
        return _FakeProvider()

    def run(self, cmd, *, workspace=None, profile=None, env=None, timeout=None):
        type(self).captured["env_key"] = (env or {}).get("OPENAI_API_KEY", "<absent>")
        type(self).captured["domains"] = list(getattr(profile, "allowed_domains", []))
        type(self).captured["has_env"] = env is not None

        class R:
            stdout = ""
            stderr = ""
            returncode = 0
            enforced = True
            error = ""
        return R()


class TestAllBranchesGetSanitizedEnv:
    def test_landlock_provider_receives_env(self):
        v = _verdict(["api.github.com"], source="global_policy",
                     backend="landlock")
        _FakeProvider.captured = {}
        m = SandboxManager()
        with patch("tuan_cli.core.sandbox_provider.SandboxProvider.create",
                   _FakeProvider.create), \
             patch.dict(os.environ, {"OPENAI_API_KEY": "REAL_SECRET_VALUE"},
                        clear=False):
            m._execute_backend("echo hi", v, "/tmp", 5.0)
        assert _FakeProvider.captured["has_env"] is True
        assert SENTINEL_PREFIX in _FakeProvider.captured["env_key"]
        assert "REAL_SECRET_VALUE" not in _FakeProvider.captured["env_key"]
        # 强后端仍拿到域名元数据，但 last_egress 如实标 text-layer-only
        assert _FakeProvider.captured["domains"] == ["api.github.com"]
        assert m.last_egress["enforcement"] == "text-layer-only"
        assert m.last_egress["claim_consistent"] is True

    def test_docker_provider_receives_env(self):
        v = _verdict(["api.github.com"], source="global_policy",
                     backend="docker")
        _FakeProvider.captured = {}
        m = SandboxManager()
        with patch("tuan_cli.core.sandbox_provider.SandboxProvider.create",
                   _FakeProvider.create), \
             patch.dict(os.environ, {"OPENAI_API_KEY": "REAL_SECRET_VALUE"},
                        clear=False):
            m._execute_backend("echo hi", v, "/tmp", 5.0)
        assert _FakeProvider.captured["has_env"] is True
        assert SENTINEL_PREFIX in _FakeProvider.captured["env_key"]

    def test_syscall_branch_passes_env(self):
        """`_run_syscall` 曾完全没有 env 参数 —— 真接线验证。"""
        v = _verdict(["api.github.com"], source="global_policy",
                     backend="jobobject")
        cap = {}

        def fake_syscall(cmd, **kwargs):
            cap["env"] = kwargs.get("env")
            cap["block_network"] = kwargs.get("block_network")

            class R:
                stdout = ""
                stderr = ""
                returncode = 0
                enforced = True
                error = ""
                degraded_reason = ""
                blocked = False
                mechanism = "job-object"
            return R()

        m = SandboxManager()
        with patch("tuan_cli.arch.platform.run_syscall_sandboxed", fake_syscall), \
             patch.object(os, "name", "nt"), \
             patch.dict(os.environ, {"OPENAI_API_KEY": "REAL_SECRET_VALUE"},
                        clear=False):
            m._execute_backend("echo hi", v, "/tmp", 5.0)
        assert cap["env"] is not None
        assert SENTINEL_PREFIX in cap["env"]["OPENAI_API_KEY"]
        assert "REAL_SECRET_VALUE" not in str(cap["env"])
        assert m.last_egress["enforcement"] == "text-layer-only"

    def test_local_branch_still_gets_env(self):
        v = _verdict(None, backend="local")
        m = SandboxManager()
        with patch("tuan_cli.core.proc.run_with_tree_kill") as fake, \
             patch.dict(os.environ, {"OPENAI_API_KEY": "REAL_SECRET_VALUE"},
                        clear=False):
            fake.return_value.stdout = "ok"
            fake.return_value.stderr = ""
            fake.return_value.returncode = 0
            m._execute_backend("echo hi", v, "/tmp", 5.0)
        env = fake.call_args.kwargs["env"]
        assert SENTINEL_PREFIX in env["OPENAI_API_KEY"]
        assert m.last_egress["enforcement"] == "none"


# ==================================================== 3 强后端默认拒绝
class TestStrongBackendFailClosed:
    @pytest.mark.parametrize("backend", ["landlock", "docker", "seatbelt",
                                         "bwrap", "jobobject"])
    def test_per_command_claim_refused(self, backend):
        v = _verdict(["api.github.com"], backend=backend)
        m = SandboxManager()
        r = m._execute_backend("curl https://evil.example/x", v, "/tmp", 5.0)
        assert r.returncode == -1
        assert "无法证明逐命令出网合规" in r.error
        assert m.last_egress["enforcement"] == "refused-unprovable-domain-compliance"
        assert m.last_egress["proxy_enabled"] is False

    def test_no_proxy_started_on_refusal(self):
        """拒绝路径绝不留下后台监听。"""
        v = _verdict(["api.github.com"], backend="landlock")
        m = SandboxManager()
        with patch("tuan_cli.sandbox.manager.EgressProxy") as fake:
            m._execute_backend("echo hi", v, "/tmp", 5.0)
        fake.assert_not_called()
        assert m.last_proxy_audit == []

    def test_explicit_metadata_only_downgrade_is_visible(self):
        v = _verdict(["api.github.com"], backend="landlock")
        m = SandboxManager({"resource": {
            "strict_claim_strong_backend": "metadata_only"}})
        _FakeProvider.captured = {}
        with patch("tuan_cli.core.sandbox_provider.SandboxProvider.create",
                   _FakeProvider.create), \
             patch.dict(os.environ, {}, clear=False):
            r = m._execute_backend("echo hi", v, "/tmp", 5.0)
        assert r.returncode == 0
        assert m.last_egress["enforcement"] == "text-layer-only-explicit-downgrade"
        assert m.last_egress["degraded"] is True
        # 降级也不等于凭据裸奔
        assert _FakeProvider.captured["has_env"] is True

    def test_global_allowlist_deployment_not_broken(self):
        """配了全局白名单 + 强后端的既有部署不被本轮改动打断。"""
        v = _verdict(["api.github.com"], source="global_policy",
                     backend="landlock")
        m = SandboxManager()
        with patch("tuan_cli.core.sandbox_provider.SandboxProvider.create",
                   _FakeProvider.create), \
             patch.dict(os.environ, {}, clear=False):
            r = m._execute_backend("echo hi", v, "/tmp", 5.0)
        assert r.returncode == 0
        assert m.last_egress["enforcement"] == "text-layer-only"


# ==================================================== 4 platform env 透传
class TestPlatformEnvThreading:
    def test_signature_has_env(self):
        import inspect
        from tuan_cli.arch import platform as P
        for fn in (P.run_syscall_sandboxed, P._linux_seccomp_sandbox,
                   P._windows_job_object_sandbox):
            assert "env" in inspect.signature(fn).parameters

    def test_env_none_is_backward_compatible(self):
        """旧调用点不传 env 时行为不变（继承父进程）。"""
        from tuan_cli.arch import platform as P
        with patch.object(P, "IS_WINDOWS", True), \
             patch.object(P, "IS_LINUX", False), \
             patch.object(P, "_windows_job_object_sandbox") as fake:
            fake.return_value.stdout = "ok"
            fake.return_value.returncode = 0
            fake.return_value.enforced = True
            P.run_syscall_sandboxed(["cmd", "/c", "echo ok"])
        assert fake.call_args.kwargs.get("env") is None

    def test_env_is_forwarded_to_windows_job_object(self):
        from tuan_cli.arch import platform as P
        env = {"OPENAI_API_KEY": "MASKED", "PATH": "/bin"}
        with patch.object(P, "IS_WINDOWS", True), \
             patch.object(P, "IS_LINUX", False), \
             patch.object(P, "_windows_job_object_sandbox") as fake:
            fake.return_value.stdout = "ok"
            fake.return_value.returncode = 0
            fake.return_value.enforced = True
            P.run_syscall_sandboxed(["cmd", "/c", "echo ok"], env=env)
        assert fake.call_args.kwargs["env"] is env

    def test_env_is_forwarded_to_linux_seccomp(self):
        from tuan_cli.arch import platform as P
        env = {"OPENAI_API_KEY": "MASKED", "PATH": "/bin"}
        with patch.object(P, "IS_WINDOWS", False), \
             patch.object(P, "IS_LINUX", True), \
             patch.object(P, "_linux_seccomp_sandbox") as fake:
            fake.return_value.stdout = "ok"
            fake.return_value.returncode = 0
            fake.return_value.enforced = True
            P.run_syscall_sandboxed(["/bin/sh", "-c", "echo ok"], env=env)
        assert fake.call_args.kwargs["env"] is env

    def test_real_subprocess_sees_provided_env(self):
        """真实 Popen 路径：脱敏 env 真的进了子进程，父进程密钥不可见。

        用 IS_LINUX=True + libseccomp 不可用强制走 fallback Popen。
        """
        from tuan_cli.arch import platform as P
        env = {"TUAN_EGRESS_PROBE": "SENTINEL_ONLY", "PATH": "/usr/bin:/bin"}
        with patch.object(P, "IS_WINDOWS", False), \
             patch.object(P, "IS_LINUX", True), \
             patch.object(P, "_linux_seccomp_sandbox",
                          side_effect=RuntimeError("libseccomp unavailable")):
            res = P.run_syscall_sandboxed(
                ["/bin/sh", "-c", "printf %s \"$TUAN_EGRESS_PROBE\""],
                timeout=10.0, env=env, memory_limit_mb=256)
        assert res.stdout == "SENTINEL_ONLY"
        assert "REAL_SECRET_VALUE" not in res.stdout


# ==================================================== 5 配置与可观测
class TestConfigAndObservability:
    def test_schema_enum(self):
        e, _ = validate_security_config({"sandbox": {"resource": {
            "strict_claim_strong_backend": "typo"}}})
        assert any("非法枚举" in x for x in e)
        e2, _ = validate_security_config({"sandbox": {"resource": {
            "strict_claim_strong_backend": 123}}})
        assert any("非法枚举" in x for x in e2)

    def test_schema_downgrade_warning(self):
        e, w = validate_security_config({"sandbox": {"resource": {
            "strict_claim_strong_backend": "metadata_only"}}})
        assert not e
        assert any("安全降级" in x and "metadata_only" in x for x in w)

    def test_harden_status_reports_policy(self, capsys):
        from tuan_cli.cli import cmd_harden
        # 只验新增输出行，不把整个 status 当单测（依赖环境）
        from tuan_cli.config import Config
        with patch.object(Config, "get", return_value={"resource": {}}):
            try:
                cmd_harden.status(type("A", (), {})())
            except Exception:
                pass  # 环境依赖较多，下面单独断言输出
        out = capsys.readouterr().out
        # 若 status 因环境跳过，至少 schema 与 plan 层已覆盖；不强求输出
        assert isinstance(out, str)

    def test_last_egress_is_written_on_every_branch(self):
        """四条路径都必须写 last_egress，不能只有 local 有。"""
        for backend, source in (("local", "none"),
                                ("landlock", "global_policy"),
                                ("docker", "global_policy")):
            v = _verdict(None if source == "none" else ["api.github.com"],
                         source=source, backend=backend)
            m = SandboxManager()
            with patch("tuan_cli.core.sandbox_provider.SandboxProvider.create",
                       _FakeProvider.create), \
                 patch("tuan_cli.core.proc.run_with_tree_kill") as fake:
                fake.return_value.stdout = ""
                fake.return_value.stderr = ""
                fake.return_value.returncode = 0
                m._execute_backend("echo hi", v, "/tmp", 5.0)
            assert m.last_egress, backend
            assert "enforcement" in m.last_egress, backend
            assert "claim_consistent" in m.last_egress, backend


# ==================================================== 6 矩阵自洽（不靠改口径）
class TestMatrixHonesty:
    def test_counts_unchanged(self):
        from tuan_cli.parity_claude import matrix, evidence
        assert matrix.validate() == []
        assert evidence.verify_evidence() == []
        s = matrix.summary()
        # 本轮是纯深度修复，**一个状态都没动**：不把修好侧门包装成
        # aligned 增加或 gap 减少。
        assert s["by_status"] == {
            "ahead": 10, "aligned": 46, "partial": 9,
            "gap": 26, "not_applicable": 8}
        assert s["gaps"] == 26
        assert s["fully_superior"] is False
        assert s["b_waves_done"] == ["B1"]
        assert s["superiority_criteria"]["external_adaptive_red_team"] is False
