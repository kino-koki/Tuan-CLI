"""B2 收尾回归：逐命令域名强绑定 + 本地回环出网代理。

**实测缺口（先复现再修）**

``TrustFilter`` 的全局白名单只在**命令文本层**生效；``SandboxProfile``
只有 ``network: bool``、``verdict.extra`` 为空 —— 执行层和出网路径上
完全没有域名概念。前几轮 477 条 fuzz 已证文本识别可被零宽字符 /
ANSI-C / 注释换行绕过。

本轮把强制点搬到出网路径：逐命令 ``allowed_domains`` 声明 →
``verdict.extra`` → ``SandboxProfile.allowed_domains`` → 本地回环代理的
CONNECT / 明文 HTTP 主机校验；凭据 sentinel 在代理转发时还原。

**A'（本轮自己引入、自己抓回）**：初版 ``normalize_domain`` 用
``str.encode("idna")``，U+200B ZWSP 被静默丢弃，
``evil\\u200b.example`` 归一化成 ``evil.example``。已加 ASCII + 逐字符
白名单先挡住，下面有专门回归锁住。

所有代理测试都是**真实起本地 socket**，不是 mock 掉网络层。
"""
from __future__ import annotations

import http.server
import json
import socket
import threading
from unittest.mock import patch

import pytest

from tuan_cli.sandbox.egress import CredentialBroker, SENTINEL_PREFIX
from tuan_cli.sandbox.egress_allowlist import (
    NetworkClaim, claim_from_args, claim_from_values, claim_from_verdict,
    claim_matches, claim_to_verdict_extra, evaluate_claim, normalize_domain,
    profile_domains,
)
from tuan_cli.sandbox.egress_proxy import EgressProxy
from tuan_cli.sandbox.manager import SandboxManager
from tuan_cli.sandbox.verdict import Verdict
from tuan_cli.core.sandbox_provider import SandboxProfile
from tuan_cli.config.security_schema import validate_security_config


# ============================================================ 1 归一化
class TestNormalizeDomain:
    @pytest.mark.parametrize("raw,expect", [
        ("API.GitHub.COM.", "api.github.com"),
        ("*.example.com", "*.example.com"),
        ("127.0.0.1", "127.0.0.1"),
        ("[::1]", "::1"),
        ("localhost", "localhost"),
    ])
    def test_valid(self, raw, expect):
        assert normalize_domain(raw) == expect

    @pytest.mark.parametrize("raw", [
        "*", "*.", "*.*", "http://evil/x", "evil.example:443", "a b",
        "?", "#", "user@host", "a/b", "x" * 300, 123, None, b"bytes",
    ])
    def test_invalid_is_not_silently_widened(self, raw):
        assert normalize_domain(raw) is None

    def test_zero_width_chars_are_rejected_not_dropped(self):
        """A' 回归：IDNA 编码会吞掉 ZWSP，绝不能让它归一化成合法域名。"""
        assert normalize_domain("evil\u200b.example") is None
        assert normalize_domain("api.github\u200b.com") is None
        assert normalize_domain("evil\ufeff.example") is None
        assert normalize_domain("evil\u200d.example") is None
        assert normalize_domain("münchen.example") is None
        # 同一主机插入 ZWSP 后不再匹配白名单声明
        assert claim_matches("api.github.com", "api.github\u200b.com") is False

    def test_wildcard_is_suffix_only(self):
        assert claim_matches("*.example.com", "a.example.com") is True
        assert claim_matches("*.example.com", "example.com") is True
        assert claim_matches("*.example.com", "example.com.evil") is False
        assert claim_matches("api.github.com", "evil.api.github.com") is False

    def test_ip_requires_exact_match(self):
        assert claim_matches("127.0.0.1", "127.0.0.1") is True
        assert claim_matches("127.0.0.1", "127.0.0.2") is False


# ============================================================ 2 claim 构造
class TestNetworkClaim:
    def test_claim_from_values_dedup_and_normalize(self):
        c = claim_from_values(["API.GitHub.COM.", "api.github.com"])
        assert c.required_domains == ("api.github.com",)
        assert c.strict is True and c.source == "tool_args"

    def test_dirty_values_are_fail_closed(self):
        for bad in (123, {"a": 1}, object()):
            c = claim_from_values(bad)
            assert c.strict is True
            assert c.invalid_values
            assert evaluate_claim(c, []).allowed is False
        c2 = claim_from_values(["api.github.com", "evil\u200b.example"])
        assert c2.required_domains == ("api.github.com",)
        assert c2.invalid_values
        assert evaluate_claim(c2, ["api.github.com"]).allowed is False

    def test_none_means_no_strict_binding(self):
        c = claim_from_values(None)
        assert c.strict is False and c.source == "none"
        assert evaluate_claim(c, ["evil.example"]).allowed is True

    def test_claim_from_args_prefers_per_command(self):
        args = {"command": "curl https://api.github.com",
                "allowed_domains": ["api.github.com"]}
        c = claim_from_args(args, fallback=["evil.example"])
        assert c.required_domains == ("api.github.com",)
        assert c.source == "tool_args"
        c2 = claim_from_args({"command": "x"}, fallback=["evil.example"])
        assert c2.required_domains == ("evil.example",)
        assert c2.source == "global_policy"  # 回落不假装是逐命令声明

    def test_evaluate_claim_fail_closed_matrix(self):
        c = claim_from_values(["api.github.com"])
        assert evaluate_claim(c, ["api.github.com"]).allowed is True
        assert evaluate_claim(c, ["evil.example"]).allowed is False
        assert evaluate_claim(c, ["api.github.com", "evil.example"]).allowed is False
        # strict 且检测不到域名：不因「没检测到」拒绝（最终由代理主机层强制），
        # 但必须标记 undetectable，绝不悄悄当成已证明合规
        d = evaluate_claim(c, [])
        assert d.allowed is True and d.undetectable is True
        # strict 但没声明任何主机 → 拒绝一切
        assert evaluate_claim(NetworkClaim((), True, "none"),
                              ["api.github.com"]).allowed is False

    def test_verdict_extra_roundtrip(self):
        c = claim_from_values(["api.github.com"])
        v = Verdict()
        v.extra.update(claim_to_verdict_extra(c))
        assert claim_from_verdict(v).required_domains == ("api.github.com",)
        assert claim_from_verdict(Verdict()).strict is False
        assert claim_from_verdict(None).strict is True  # 缺失裁决 fail-closed
        assert profile_domains(c) == ("api.github.com",)


# ============================================================ 3 真实代理
class _Upstream(http.server.BaseHTTPRequestHandler):
    seen = {}

    def do_GET(self):
        type(self).seen["auth"] = self.headers.get("Authorization")
        type(self).seen["path"] = self.path
        body = b"OK"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a):
        pass


@pytest.fixture
def upstream():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Upstream)
    _Upstream.seen = {}
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def _proxy_request(px, raw: bytes) -> bytes:
    s = socket.create_connection(("127.0.0.1", px._server.server_address[1]), 5)
    try:
        s.sendall(raw)
        out = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            out += chunk
        return out
    finally:
        s.close()


class TestEgressProxy:
    def test_real_plain_http_allows_and_injects_credential(self, upstream):
        broker = CredentialBroker()
        sentinel = broker.mask("TOKEN", "REAL_SECRET_VALUE")
        claim = claim_from_values(["127.0.0.1"])
        with EgressProxy(claim, broker, timeout=5.0) as px:
            assert px.running and px.url.startswith("http://127.0.0.1:")
            env = px.env_overrides
            assert env["HTTP_PROXY"] == px.url
            assert env["HTTPS_PROXY"] == px.url
            assert env["NO_PROXY"] == ""  # 清空防绕过
            req = (f"GET http://127.0.0.1:{upstream}/ok HTTP/1.1\r\n"
                   f"Host: 127.0.0.1\r\nAuthorization: {sentinel}\r\n"
                   "Connection: close\r\n\r\n").encode()
            resp = _proxy_request(px, req)
            assert resp.startswith(b"HTTP/1.1 200")
            # 真实凭据只在代理转发时还原；上游看到的是真实值
            assert _Upstream.seen["auth"] == "REAL_SECRET_VALUE"
            assert _Upstream.seen["path"] == "/ok"
            audit = px.audit()
            assert any(x["injected_count"] == 1 for x in audit)
            # 审计绝不泄露真实值 / header / body
            assert "REAL_SECRET_VALUE" not in json.dumps(audit)
            assert sentinel not in json.dumps(audit)
        assert px.running is False   # finally 一定 stop

    def test_plain_http_outside_claim_is_403(self, upstream):
        with EgressProxy(claim_from_values(["api.github.com"]),
                         timeout=5.0) as px:
            req = (f"GET http://127.0.0.1:{upstream}/x HTTP/1.1\r\n"
                   "Host: 127.0.0.1\r\nConnection: close\r\n\r\n").encode()
            resp = _proxy_request(px, req)
            assert resp.startswith(b"HTTP/1.1 403")
            assert any(x["allowed"] is False and x["kind"] == "plain_http"
                       for x in px.audit())

    def test_connect_outside_claim_is_403(self):
        with EgressProxy(claim_from_values(["api.github.com"]),
                         timeout=5.0) as px:
            resp = _proxy_request(
                px, b"CONNECT evil.example:443 HTTP/1.1\r\n\r\n")
            assert resp.startswith(b"HTTP/1.1 403")
            assert any(x["allowed"] is False and x["kind"] == "connect"
                       for x in px.audit())

    def test_strict_empty_claim_denies_everything(self):
        with EgressProxy(NetworkClaim((), True, "none"), timeout=5.0) as px:
            resp = _proxy_request(px, b"CONNECT api.github.com:443 HTTP/1.1\r\n\r\n")
            assert resp.startswith(b"HTTP/1.1 403")

    def test_audit_never_contains_real_secret(self):
        broker = CredentialBroker()
        # 即便 broker 持有真实值，repr 与审计都不泄露
        broker.mask("TOKEN", "DO_NOT_LEAK")
        with EgressProxy(claim_from_values(["api.github.com"]), broker,
                         timeout=5.0) as px:
            assert "DO_NOT_LEAK" not in repr(px)
            assert "DO_NOT_LEAK" not in repr(broker)
            assert "DO_NOT_LEAK" not in json.dumps(px.audit())

    def test_bad_request_line_is_closed_not_allowed(self):
        with EgressProxy(claim_from_values(["api.github.com"]),
                         timeout=5.0) as px:
            resp = _proxy_request(px, b"GARBAGE\r\n\r\n")
            assert b"400" in resp[:64]
            assert any(x["kind"] == "parse_error" for x in px.audit())


# ============================================================ 4 manager 接线
class _Ctx:
    yolo = False
    confirm = None
    workspace = "/tmp/w"
    kernel = None
    safety_severity = None
    plan_mode = False


class TestManagerWiring:
    def test_per_command_claim_reaches_verdict_extra(self):
        m = SandboxManager()
        # assess_command 走全局回落；默认没配白名单 → 非 strict，但结构仍写入
        v = m.assess_command("curl https://api.github.com/x", _Ctx())
        assert "network_claim" in v.extra
        assert claim_from_verdict(v).strict is False
        # assess_tool 携带逐命令声明 → 结构进 verdict.extra 且来源如实标注
        denied, _ = m.assess_tool("run_shell", {
            "command": "curl https://api.github.com/x",
            "allowed_domains": ["api.github.com"]}, _Ctx())
        assert denied is False
        assert m.last_allowlist["claim"]["source"] == "tool_args"
        assert m.last_allowlist["claim"]["required_domains"] == ["api.github.com"]

    def test_declared_outside_command_is_denied(self):
        m = SandboxManager()
        denied, msg = m.assess_tool("run_shell", {
            "command": "curl https://evil.example/x",
            "allowed_domains": ["api.github.com"]}, _Ctx())
        assert denied is True
        assert "声明外" in msg or "egress_allowlist" in msg
        assert m.last_allowlist["allowed"] is False

    def test_detection_exception_is_fail_closed(self):
        m = SandboxManager()
        with patch.object(m, "_detected_domains", side_effect=RuntimeError("boom")):
            denied, msg = m.assess_tool("run_shell", {
                "command": "curl https://api.github.com/x",
                "allowed_domains": ["api.github.com"]}, _Ctx())
        assert denied is True and "fail-closed" in msg

    def test_proxy_default_off_no_env_change(self):
        m = SandboxManager()
        v = Verdict()
        v.extra.update(claim_to_verdict_extra(claim_from_values(["api.github.com"])))
        with patch("tuan_cli.core.proc.run_with_tree_kill") as fake:
            fake.return_value.stdout = "ok"
            fake.return_value.stderr = ""
            fake.return_value.returncode = 0
            m._execute_backend("echo hi", v, "/tmp", 5.0)
        env = fake.call_args.kwargs["env"]
        assert "HTTP_PROXY" not in env
        assert m.last_egress.get("proxy_enabled") is None

    def test_proxy_enabled_injects_env_and_always_stops(self):
        m = SandboxManager({"resource": {"egress_proxy_enabled": True}})
        v = Verdict()
        v.extra.update(claim_to_verdict_extra(claim_from_values(["api.github.com"])))
        with patch("tuan_cli.core.proc.run_with_tree_kill") as fake:
            fake.return_value.stdout = "ok"
            fake.return_value.stderr = ""
            fake.return_value.returncode = 0
            m._execute_backend("echo hi", v, "/tmp", 5.0)
        env = fake.call_args.kwargs["env"]
        assert "HTTP_PROXY" in env and env["NO_PROXY"] == ""
        assert m.last_egress.get("proxy_enabled") is True
        assert isinstance(m.last_proxy_audit, list)

    def test_proxy_not_enabled_without_strict_claim(self):
        m = SandboxManager({"resource": {"egress_proxy_enabled": True}})
        v = Verdict()   # 无 claim → 不改写网络出口
        with patch("tuan_cli.core.proc.run_with_tree_kill") as fake:
            fake.return_value.stdout = "ok"
            fake.return_value.stderr = ""
            fake.return_value.returncode = 0
            m._execute_backend("echo hi", v, "/tmp", 5.0)
        assert "HTTP_PROXY" not in fake.call_args.kwargs["env"]

    def test_profile_carries_allowed_domains(self):
        m = SandboxManager()
        v = Verdict()
        v.extra.update(claim_to_verdict_extra(claim_from_values(["api.github.com"])))
        captured = {}

        class FakeProvider:
            @staticmethod
            def create(_backend):
                return FakeProvider()

            def run(self, _cmd, *, workspace=None, profile=None, timeout=None):
                captured["domains"] = list(profile.allowed_domains)
                captured["network"] = profile.network

                class R:
                    stdout = ""
                    stderr = ""
                    returncode = 0
                    enforced = True
                    error = ""
                return R()

        with patch("tuan_cli.core.sandbox_provider.SandboxProvider.create",
                   FakeProvider.create):
            m._run_provider("landlock", "echo hi", "/tmp", 5.0, False, v)
        assert captured["domains"] == ["api.github.com"]
        assert isinstance(SandboxProfile().allowed_domains, list)

    def test_schema_new_switch(self):
        e, w = validate_security_config({
            "sandbox": {"resource": {"egress_proxy_enabled": True}}})
        assert not e and any("行为变更" in x for x in w)
        e2, _ = validate_security_config({
            "sandbox": {"resource": {"egress_proxy_enabled": "yes"}}})
        assert any("应为 bool" in x for x in e2)


# ============================================================ 5 矩阵自洽
class TestMatrixStillHonest:
    def test_no_gap_padding(self):
        """partial→aligned 不减少 gap；不许靠改口径凑数。"""
        from tuan_cli.parity_claude import matrix, evidence
        assert matrix.validate() == []
        assert evidence.verify_evidence() == []
        s = matrix.summary()
        assert s["fully_superior"] is False
        assert s["gaps"] == 26            # 仍 26，本轮没清 gap
        assert s["by_status"]["aligned"] == 46
        assert s["by_status"]["partial"] == 9
        assert s["b_waves_done"] == ["B1"]
        assert s["superiority_criteria"]["external_adaptive_red_team"] is False
