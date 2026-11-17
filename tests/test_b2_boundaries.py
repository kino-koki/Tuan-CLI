"""B2 回归：子进程出网边界 / 凭据 sentinel / 无人值守拒绝 / worktree 边界。

本轮的两个**实测**缺陷（不是推测）：

1. ``SandboxManager._execute_backend`` 算出 ``block_net`` 却既不传给
   ``local`` 分支、也不传 env —— 禁网裁决在唯一没有 OS 级出网隔离能力
   的后端上静默失效，且父进程真实凭据原样进入子进程。
2. ``WorktreeLayer._git`` 继承完整 ``os.environ``，``GIT_WORK_TREE`` /
   ``GIT_DIR`` 可把 git 元数据重定向到 workspace 之外；create 路径也
   没校验解析后的 target 仍在边界内。

所有断言都针对**修复后**行为，并用 monkeypatch 真调接线点，不靠读源码。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from tuan_cli.sandbox.egress import (
    SENTINEL_PREFIX, CredentialBroker, EgressGuard, build_child_env,
    enforce_local_egress, is_sensitive_env_name,
)
from tuan_cli.sandbox.unattended import (
    SCOPE_ALL, SCOPE_NO_CHANNEL, UnattendedOutcome, UnattendedPolicy,
    resolve_confirm,
)
from tuan_cli.sandbox.verdict import Action, Verdict
from tuan_cli.sandbox.manager import SandboxManager
from tuan_cli.sandbox.worktree_boundary import (
    assert_worktree_target, current_git_redirect_vars, inspect_git_command,
    sanitize_git_env,
)
from tuan_cli.config.security_schema import validate_security_config


# ================================================================ 1 出网边界
class TestLocalEgress:
    def test_local_denied_network_is_rejected_not_executed(self):
        """修复前：local 分支直接 run_with_tree_kill，禁网完全无效。"""
        v = Verdict()
        v.network = False
        d = EgressGuard().prepare(v, "local", {"PATH": "/bin"})
        assert d.allowed is False
        assert "fail-closed" in d.reason and "local" in d.reason
        assert d.block_local_applied is True
        assert "真实值" not in d.reason  # 理由里不含任何凭据

    def test_strong_backend_does_not_double_block(self):
        v = Verdict()
        v.network = False
        for backend in ("docker", "landlock", "seatbelt", "jobobject", "token-acl"):
            allowed, reason, applied = enforce_local_egress(v, backend)
            assert allowed and reason == "" and applied is False, backend

    def test_local_with_network_allowed_still_runs(self):
        v = Verdict()  # network=True by default
        d = EgressGuard().prepare(v, "local", {"PATH": "/bin"})
        assert d.allowed is True and d.env == {"PATH": "/bin"}

    def test_explicit_escape_hatch_is_visible(self):
        v = Verdict()
        v.network = False
        g = EgressGuard(block_local_when_denied=False)
        d = g.prepare(v, "local", {"PATH": "/bin"})
        assert d.allowed is True
        assert "安全降级" in d.reason
        e, w = validate_security_config({
            "sandbox": {"resource": {"egress_block_local_when_denied": False}}})
        assert any("egress_block_local_when_denied" in x for x in e)

    def test_manager_refuses_to_spawn_when_local_denied(self):
        """真调接线：run_with_tree_kill 调用次数必须为 0。"""
        m = SandboxManager()
        v = Verdict()
        v.network = False
        with patch("tuan_cli.core.proc.run_with_tree_kill") as fake:
            res = m._execute_backend("echo hi", v, "/tmp", 5.0)
        assert fake.call_count == 0
        assert res.returncode == -1 and res.enforced is False
        assert "fail-closed" in (res.error or "")
        assert m.last_egress["allowed"] is False

    def test_manager_passes_sanitized_env_when_allowed(self):
        m = SandboxManager()
        v = Verdict()
        with patch("tuan_cli.core.proc.run_with_tree_kill") as fake:
            fake.return_value.stdout = "ok"
            fake.return_value.stderr = ""
            fake.return_value.returncode = 0
            m._execute_backend("echo hi", v, "/tmp", 5.0)
        assert fake.call_count == 1
        env = fake.call_args.kwargs["env"]
        assert isinstance(env, dict)
        for name, value in env.items():
            if is_sensitive_env_name(name):
                assert str(value).startswith(SENTINEL_PREFIX), name


# ================================================================ 2 凭据代理
class TestCredentialBroker:
    def test_sensitive_names_are_masked_and_safe_names_kept(self):
        assert is_sensitive_env_name("GITHUB_TOKEN")
        assert is_sensitive_env_name("AWS_SECRET_ACCESS_KEY")
        assert is_sensitive_env_name("MY_PASSWORD")
        assert not is_sensitive_env_name("PATH")
        assert not is_sensitive_env_name("HOME")
        assert not is_sensitive_env_name("LANG")
        assert not is_sensitive_env_name(123)

    def test_real_value_never_enters_child_env(self):
        broker = CredentialBroker()
        env, masked, dropped, invalid = build_child_env({
            "PATH": "/bin", "LANG": "C",
            "GITHUB_TOKEN": "ghp_REALVALUE", "AWS_SECRET_ACCESS_KEY": "S3CR3T",
        }, broker=broker)
        assert not invalid and dropped == ()
        assert env["PATH"] == "/bin" and env["LANG"] == "C"
        assert env["GITHUB_TOKEN"].startswith(SENTINEL_PREFIX)
        assert env["AWS_SECRET_ACCESS_KEY"].startswith(SENTINEL_PREFIX)
        assert "ghp_REALVALUE" not in repr(env) and "S3CR3T" not in repr(env)
        assert masked == ("GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY")
        assert len(broker) == 2
        assert broker.resolve(env["GITHUB_TOKEN"]) == "ghp_REALVALUE"
        assert broker.resolve("not-a-sentinel") is None
        assert broker.resolve(123) is None

    def test_repr_and_audit_never_leak(self):
        broker = CredentialBroker()
        s = broker.mask("TOKEN", "SUPER_SECRET")
        assert "SUPER_SECRET" not in repr(broker)
        d = EgressGuard().prepare(Verdict(), "local", {"TOKEN": "SUPER_SECRET"})
        assert "SUPER_SECRET" not in json.dumps(d.to_audit_dict())
        assert d.to_audit_dict()["masked_names"] == ["TOKEN"]
        assert broker.resolve(s) == "SUPER_SECRET"

    def test_injection_is_off_by_default(self):
        """catalog 标 partial 的依据：出网代理注入尚未接线。"""
        broker = CredentialBroker()
        s = broker.mask("TOKEN", "REAL")
        headers = {"Authorization": s}
        assert broker.inject_enabled is False
        assert broker.inject_headers(headers) == {"Authorization": s}
        broker.enable_injection()
        assert broker.inject_headers(headers) == {"Authorization": "REAL"}

    def test_invalid_base_does_not_inherit_parent_env(self):
        for bad in (123, ["x"], object(), b"bytes"):
            env, masked, dropped, invalid = build_child_env(bad)
            assert invalid is True and env == {} and masked == ()
        d = EgressGuard().prepare(Verdict(), "local", 123)
        assert d.invalid_base is True and d.env == {}
        assert "不继承父进程" in d.reason

    def test_non_string_keys_or_values_are_dropped(self):
        env, _m, dropped, invalid = build_child_env({
            "PATH": "/bin", 123: "x", "BAD": object(), "TOKEN": "real",
        })
        assert not invalid
        assert env["PATH"] == "/bin"
        assert "BAD" not in env and 123 not in env
        assert len(dropped) == 2
        assert env["TOKEN"].startswith(SENTINEL_PREFIX)

    def test_guard_policy_strict_types(self):
        for bad in ("false", 0, None, 1):
            g = EgressGuard(mask_credentials=bad,
                            block_local_when_denied=bad)
            # 脏值一律回落最严档，绝不 ``bool("false") == True`` 那种静默转真
            assert g.mask_credentials is True
            assert g.block_local_when_denied is True
        g2 = EgressGuard.from_policy({"resource": {
            "egress_credential_masking": False,
            "egress_block_local_when_denied": False}})
        assert g2.mask_credentials is False
        assert g2.block_local_when_denied is False


# ================================================================ 3 无人值守
class _Ctx:
    yolo = False
    confirm = None
    workspace = "/tmp/w"
    kernel = None


class _FakeChain:
    def evaluate(self, payload):
        return Verdict(Action.CONFIRM, reason="危险命令需确认")


class TestDenyInsteadOfPrompting:
    @pytest.mark.parametrize("enabled,has_channel,scope,denied,cont,applied", [
        (False, False, SCOPE_NO_CHANNEL, False, False, False),
        (True, False, SCOPE_NO_CHANNEL, True, True, True),
        (True, True, SCOPE_NO_CHANNEL, False, False, False),
        (True, True, SCOPE_ALL, True, True, True),
    ])
    def test_matrix(self, enabled, has_channel, scope, denied, cont, applied):
        o = resolve_confirm(
            Verdict(Action.CONFIRM, reason="危险命令"),
            has_confirm_channel=has_channel,
            policy=UnattendedPolicy(enabled=enabled, scope=scope))
        assert (o.denied, o.continue_turn, o.applied) == (denied, cont, applied)
        assert isinstance(o, UnattendedOutcome)

    def test_denial_is_never_relaxed(self):
        o = resolve_confirm(Verdict(Action.CONFIRM), has_confirm_channel=False,
                            policy=UnattendedPolicy(enabled=True))
        assert o.denied is True  # 「拒绝并继续」不等于「放行」

    def test_invalid_policy_is_fail_closed(self):
        p = UnattendedPolicy(enabled=True, scope="typo")
        assert p.validate()
        o = resolve_confirm(Verdict(Action.CONFIRM), has_confirm_channel=True,
                            policy=p)
        assert o.denied is True and "配置非法" in o.reason

    def test_from_mapping_three_key_shapes(self):
        for cfg in (
            {"permissions.denyInsteadOfPrompting": True},
            {"denyInsteadOfPrompting": True},
            {"unattended": {"deny_instead_of_prompting": True}},
        ):
            assert UnattendedPolicy.from_mapping(cfg).enabled is True
        assert UnattendedPolicy.from_mapping(
            {"permissions.denyInsteadOfPrompting": "false"}).enabled is False
        assert UnattendedPolicy.from_mapping(None).enabled is False
        assert UnattendedPolicy.from_mapping(
            {"permissions.denyInsteadOfPromptingScope": SCOPE_ALL}).scope == SCOPE_ALL
        assert UnattendedPolicy.from_mapping(
            {"permissions.denyInsteadOfPromptingScope": "typo"}).scope == SCOPE_NO_CHANNEL

    def test_manager_wiring_default_off_is_unchanged(self):
        m = SandboxManager()
        m.chain = _FakeChain()
        denied, msg = m.assess_tool("run_shell", {"command": "x"}, _Ctx())
        assert denied is True
        assert "需要人工确认但没有确认通道" in msg
        assert m.unattended_decisions() == []

    def test_manager_wiring_enabled_records_continue_turn(self):
        m = SandboxManager({"permissions.denyInsteadOfPrompting": True})
        m.chain = _FakeChain()
        denied, msg = m.assess_tool("run_shell", {"command": "x"}, _Ctx())
        assert denied is True and "denyInsteadOfPrompting" in msg
        assert "continue_turn=True" in msg
        rows = m.unattended_decisions()
        assert len(rows) == 1
        assert rows[0]["continue_turn"] is True
        assert rows[0]["suppressed_prompt"] is True
        assert rows[0]["denied"] is True
        assert "x" not in json.dumps(rows)  # 不记命令原文

    def test_schema_validation(self):
        e, w = validate_security_config({
            "permissions.denyInsteadOfPrompting": True})
        assert not e and any("行为变更" in x for x in w)
        e2, _ = validate_security_config({
            "permissions.denyInsteadOfPrompting": "yes"})
        assert any("应为 bool" in x for x in e2)
        e3, _ = validate_security_config({
            "permissions.denyInsteadOfPromptingScope": "typo"})
        assert any("非法枚举" in x for x in e3)


# ================================================================ 4 worktree 边界
class TestWorktreeBoundary:
    def test_target_inside_is_proven(self, tmp_path):
        ws = tmp_path / "ws"
        (ws / ".tuan" / "worktrees").mkdir(parents=True)
        p = assert_worktree_target(ws, ws / ".tuan" / "worktrees" / "x")
        assert p.within is True
        assert p.to_dict()["target"].startswith(str(ws))

    def test_target_outside_is_rejected(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        with pytest.raises(ValueError, match="之外"):
            assert_worktree_target(ws, tmp_path / "outside")

    def test_target_equal_to_workspace_root_is_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="不能等于"):
            assert_worktree_target(tmp_path, tmp_path)

    def test_symlink_ancestor_is_detected(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        try:
            (ws / ".tuan").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("平台不支持目录 symlink")
        with pytest.raises(ValueError, match="之外"):
            assert_worktree_target(ws, ws / ".tuan" / "worktrees" / "x")

    def test_git_redirect_env_is_stripped(self, monkeypatch):
        env, stripped = sanitize_git_env({
            "PATH": "/bin", "GIT_WORK_TREE": "/evil",
            "GIT_DIR": "/evil2", "GIT_INDEX_FILE": "/evil3",
        })
        assert env == {"PATH": "/bin"}
        assert set(stripped) == {"GIT_WORK_TREE", "GIT_DIR", "GIT_INDEX_FILE"}
        monkeypatch.setenv("GIT_DIR", "/evil")
        assert "GIT_DIR" in current_git_redirect_vars()

    def test_dirty_git_env_is_not_inherited(self):
        env, stripped = sanitize_git_env(123)
        assert env == {}
        assert "GIT_DIR" in stripped and "GIT_WORK_TREE" in stripped
        assert set(stripped) == set(current_git_redirect_vars()) or \
            set(stripped) == {
                "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                "GIT_CEILING_DIRECTORIES", "GIT_NAMESPACE"}

    def test_git_argv_redirect_is_rejected(self):
        assert inspect_git_command(["worktree", "add", "x"])[0] is True
        for args in (["-C", "/evil"], ["--git-dir=/evil"],
                     ["--work-tree", "/evil"], ["--namespace", "x"]):
            assert inspect_git_command(args)[0] is False, args
        assert inspect_git_command("git worktree add")[0] is False
        assert inspect_git_command(["worktree", 123])[0] is False

    def test_real_create_wiring_rejects_escape(self, tmp_path):
        """真调 WorktreeLayer.create，不是只测纯函数。"""
        from tuan_cli.core.worktree_layer import WorktreeLayer, WorktreeError
        ws = tmp_path / "ws"
        ws.mkdir()
        layer = WorktreeLayer(str(ws))
        with patch.object(layer, "_require_git", lambda: None), \
             patch.object(layer, "_wt_path",
                          lambda name: tmp_path / "outside" / name):
            with pytest.raises(WorktreeError, match="边界校验失败"):
                layer.create("x")
            assert getattr(layer, "last_boundary_proof", None) is None

    def test_real_git_wiring_strips_redirect(self, tmp_path, monkeypatch):
        from tuan_cli.core.worktree_layer import WorktreeLayer
        ws = tmp_path / "ws"
        ws.mkdir()
        monkeypatch.setenv("GIT_DIR", "/evil")
        layer = WorktreeLayer(str(ws))
        captured = {}

        def fake_run(argv, **kwargs):
            captured["env"] = kwargs.get("env", {})
            captured["argv"] = argv

            class R:
                returncode = 0
                stdout = ""
                stderr = ""
            return R()

        with patch("tuan_cli.core.worktree_layer.subprocess.run", fake_run):
            layer._git(["worktree", "list"])
        assert "GIT_DIR" not in captured["env"]
        assert layer.last_git_stripped_env == ("GIT_DIR",)


# ================================================================ 5 矩阵自洽
class TestMatrixStillHonest:
    def test_validate_clean_and_superior_still_false(self):
        from tuan_cli.parity_claude import matrix
        assert matrix.validate() == []
        s = matrix.summary()
        assert s["fully_superior"] is False
        assert s["superiority_criteria"]["external_adaptive_red_team"] is False
        assert s["b_waves_done"] == ["B1"]
        assert s["gaps"] == 26

    def test_no_doc_only_status_change(self):
        """加状态必须带真实存在的证据路径。"""
        from tuan_cli.parity_claude import evidence
        assert evidence.verify_evidence() == []
