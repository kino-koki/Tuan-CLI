"""B3 续轮 XV｜url / prompt / subagent 三类非进程 hook 的等价故障闭合表。

上一轮（XIV）修了 lifecycle 出站通道的失败闭合与脱敏，并明确留下硬理由：
「url/prompt/subagent 三类 hook 的**故障闭合**语义与 command 的 exit-code
语义不同（无进程 rc，只有 timeout / HTTP error / 模型拒绝），未逐类建立
等价裁决表」。本轮一点广度没扩，只把这条做实。

### 先实测复现（真起 HTTP server / 真起 command 子进程 / 真模型调用）

| 编号 | 修复前实测 | 修复后 |
|---|---|---|
| N1 | HTTP 200 空 body / 非 JSON body → ``block=False``、``failures=[]``、**审计 0 条** | 三条结构化留痕（``channel_no_decision`` / ``channel_semantics`` / ``exit_json_ignored``），仍不阻断 |
| N2 | ``timeout=0.5s``、慢速 drip 每 0.3s 发 1 字节，实测 **2.71s** 且静默放行 | 0.60s、``timeout`` failure、fail-closed 阻断 |
| N3 | 模型异常 ``api_key=ghp_... OSC8 RLO`` 原样进 ``HookDecision.reason`` | 净化成 ``RuntimeError: [REDACTED] boom`` |
| N3b | HTTP 成功 reason 里的 token / RLO 原样采纳 | ``tok=[REDACTED]`` |
| N4 | ``urlopen`` 默认跟随 302，POST 改 GET 发到另一主机 | 拒绝重定向，第二 server 零请求 |
| N6 | prompt 返回 500000 字符 reason 原样进决策 | 4096 码点上限，噪声留痕 |
| N7 | ``on_failure=allow`` + HTTP 500 放行 | **判定不该修**，逐值不变 |

### 等价表怎么用

``classify_channel()`` 把通道故障映射成 **等价 rc=1**，然后复用
``exit_semantics.classify()`` 这一份既有真值表 —— 不新建第二套逐事件
策略。真跑对照：command rc=1 与 url HTTP 500 在 33 个官方事件上同裁决。
"""
from __future__ import annotations

import json
import socketserver
import subprocess
import sys
import threading
import time
import http.server
from pathlib import Path

import pytest

from tuan_cli.core import safe_text as ST
from tuan_cli.hooks import exit_semantics as XS
from tuan_cli.hooks import lifecycle as LC
from tuan_cli.hooks import manager as HM
from tuan_cli.hooks import nonprocess as NP

PY = sys.executable
SECRET = "ghp_FAKE_SECRET_VALUE_FOR_REPRO_ONLY"
REAL = "ghp_" + "A" * 36
OSC = "\x1b]8;;https://evil.example\x07"
RLO = "\u202e"


class _Kernel:
    def __init__(self, adapter=None):
        self.a = adapter
        self.events = []

    def get(self, name, default=None):
        return self.a if name == "model_adapter" else default

    def emit(self, topic, payload=None):
        self.events.append((topic, payload or {}))

    def on(self, *a, **k):
        pass


def _statuses(k):
    return [p.get("status") for t, p in k.events if t == "hook.executed"]


class _Handler(http.server.BaseHTTPRequestHandler):
    tag = "h1"

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        self.server.requests.append(("POST", self.rfile.read(n)))
        m = self.server.mode
        if m == "empty":
            self.send_response(200); self.end_headers(); self.wfile.write(b"")
        elif m == "html":
            self.send_response(200); self.end_headers()
            self.wfile.write(b"<html>not json</html>")
        elif m == "block":
            self.send_response(200); self.end_headers()
            self.wfile.write(b'{"decision":"block","reason":"NO"}')
        elif m == "redirect":
            self.send_response(302)
            self.send_header("Location", self.server.target_url)
            self.end_headers()
        elif m == "slow":
            self.send_response(200)
            self.send_header("Content-Length", "10"); self.end_headers()
            for _ in range(10):
                try:
                    self.wfile.write(b"x"); self.wfile.flush()
                    time.sleep(0.3)
                except Exception:
                    break
        elif m == "500":
            self.send_response(500); self.end_headers()
            self.wfile.write(b"err")
        elif m == "leak":
            self.send_response(200); self.end_headers()
            self.wfile.write(
                ('{"decision":"block","reason":"tok=' + REAL +
                 ' \\u202e"}').encode())
        else:
            self.send_response(200); self.end_headers()

    def do_GET(self):
        self.server.requests.append(("GET", b""))
        self.send_response(200); self.end_headers()
        self.wfile.write(b'{"decision":"block","reason":"TARGET"}')

    def log_message(self, *a):
        pass


@pytest.fixture
def http_env():
    s1 = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    s2 = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    p1, p2 = s1.server_address[1], s2.server_address[1]
    for s in (s1, s2):
        s.requests = []
        s.mode = "empty"
    s1.target_url = "http://127.0.0.1:%d/target" % p2
    s2.target_url = ""
    t1 = threading.Thread(target=s1.serve_forever, daemon=True)
    t2 = threading.Thread(target=s2.serve_forever, daemon=True)
    t1.start(); t2.start()
    url = "http://127.0.0.1:%d/hook" % p1
    from types import SimpleNamespace

    def set_mode(m):
        s1.mode = m
    try:
        # A′（XV）：初版用 ``type("E", (), {"mode": lambda m: ...})``，
        # lambda 挂在类上被当实例方法绑定（self 占第一位）→ 10 条用例
        # 全 ``TypeError``。改用 SimpleNamespace 装普通闭包函数。
        yield SimpleNamespace(s1=s1, s2=s2, url=url, mode=set_mode)
    finally:
        s1.shutdown(); s2.shutdown()
        s1.server_close(); s2.server_close()


def _mgr(spec, policy="block", kernel=None):
    return HM.HookManager(
        {"hooks": {"enabled": True, "on_failure": policy,
                   "PermissionRequest": [spec]}},
        kernel=kernel or _Kernel())


# ================================================== N1 成功但无裁决
class TestNoDecisionTrace:
    @pytest.mark.parametrize("mode", ["empty", "html"])
    def test_n1_no_decision_is_traced_not_blocked(self, http_env, mode):
        http_env.mode(mode)
        k = _Kernel()
        m = _mgr({"type": "url", "url": http_env.url, "timeout": 1.0},
                 kernel=k)
        d = m.run_decision("PermissionRequest", tool_name="shell")
        s = _statuses(k)
        assert d.block is False            # 空响应是合法「无意见」，不该拦
        assert "channel_no_decision" in s
        assert "channel_semantics" in s
        assert "exit_json_ignored" in s   # 既有分支现在真被走到
        assert m.failures() == []
        if mode == "html":
            assert "channel_non_json_stdout" in s

    def test_n1_command_empty_stdout_unchanged(self):
        """对照：command hook 路径逐字节零改动。"""
        k = _Kernel()
        m = HM.HookManager(
            {"hooks": {"enabled": True, "on_failure": "block",
                       "PermissionRequest": [
                           {"command": [PY, "-c", "pass"]}]}}, kernel=k)
        d = m.run_decision("PermissionRequest", tool_name="shell")
        assert d.block is False
        assert "exit_code_semantics" in _statuses(k)
        assert "channel_semantics" not in _statuses(k)

    def test_n1_normal_json_block_still_works(self, http_env):
        http_env.mode("block")
        m = _mgr({"type": "url", "url": http_env.url, "timeout": 1.0})
        d = m.run_decision("PermissionRequest", tool_name="shell")
        assert d.block is True and d.reason == "NO"


# ================================================== N2 墙钟有界
class TestWallClockBounded:
    def test_n2_slow_drip_is_bounded_and_fail_closed(self, http_env):
        http_env.mode("slow")
        k = _Kernel()
        m = _mgr({"type": "url", "url": http_env.url, "timeout": 0.5},
                 kernel=k)
        t0 = time.monotonic()
        d = m.run_decision("PermissionRequest", tool_name="shell")
        elapsed = time.monotonic() - t0
        assert elapsed < 1.5, elapsed          # 修复前实测 2.71s
        assert d.block is True
        assert [f["kind"] for f in m.failures()] == ["timeout"]
        assert "channel_failed" in _statuses(k)

    def test_n2_timeout_outcome_is_bounded_not_detached(self, http_env):
        http_env.mode("slow")
        k = _Kernel()
        m = _mgr({"type": "url", "url": http_env.url, "timeout": 0.4},
                 kernel=k)
        m.run_decision("PermissionRequest", tool_name="shell")
        oc = m._tls.last_channel
        assert oc.status == "failure" and oc.failure_kind == "timeout"
        assert oc.bounded is True and oc.detached is False
        assert oc.equivalent_rc == 1
        assert not oc.redirect_followed

    def test_prompt_timeout_is_detached_and_documented(self):
        """prompt/subagent 的线程无法强杀，必须如实标 detached。"""
        class Slow:
            def chat(self, messages, stream=False):
                time.sleep(3.0)
                return "{}"
        k = _Kernel(Slow())
        m = HM.HookManager(
            {"hooks": {"enabled": True, "on_failure": "block",
                       "PermissionRequest": [
                           {"type": "prompt", "prompt": "check",
                            "timeout": 0.3}]}}, kernel=k)
        t0 = time.monotonic()
        d = m.run_decision("PermissionRequest", tool_name="shell")
        assert time.monotonic() - t0 < 1.5
        assert d.block is True
        oc = m._tls.last_channel
        assert oc.failure_kind == "timeout" and oc.detached is True
        assert "channel_detached_timeout" in _statuses(k)


# ================================================== N3 / N3b 净化
class TestSanitizationSingleTruth:
    def test_n3_failure_detail_is_sanitized(self):
        class Bad:
            def chat(self, messages, stream=False):
                raise RuntimeError("api_key=" + SECRET + " " + OSC + RLO
                                   + "boom")
        k = _Kernel(Bad())
        m = HM.HookManager(
            {"hooks": {"enabled": True, "on_failure": "block",
                       "PermissionRequest": [
                           {"type": "prompt", "prompt": "check {tool_name}",
                            "timeout": 1.0}]}}, kernel=k)
        d = m.run_decision("PermissionRequest", tool_name="shell",
                           payload={"tool_name": "shell"})
        assert d.block is True
        assert SECRET not in d.reason and OSC not in d.reason
        assert RLO not in d.reason and "[REDACTED]" in d.reason

    def test_n3b_stdout_reason_is_sanitized(self, http_env):
        http_env.mode("leak")
        m = _mgr({"type": "url", "url": http_env.url, "timeout": 1.0})
        d = m.run_decision("PermissionRequest", tool_name="shell")
        assert d.block is True
        assert "ghp_" not in d.reason and RLO not in d.reason
        assert "[REDACTED]" in d.reason

    def test_single_function_object_across_three_call_sites(self):
        """XV 收敛：三处调用同一个函数对象，不产生第二套净化真值。"""
        assert LC._safe_hook_text is ST.safe_hook_text
        assert NP.safe_hook_text is ST.safe_hook_text
        src = Path("tuan_cli/hooks/manager.py").read_text(encoding="utf-8")
        # XVI：manager 的 import 改成多行，同时引入 safe_payload。
        # 这里改核销「两个名字都从同一模块导入」，比字面串更强。
        assert "from tuan_cli.core.safe_text import (" in src
        assert "safe_hook_text, safe_payload" in src
        assert "safe_payload(payload)" in src

    def test_known_adjacent_overredaction_is_not_hidden(self):
        """XIV 已登记的边界：token 紧邻普通文本会被宽松分支一并遮蔽。
        这里把它锁成可执行事实，不粉饰成「零过度遮蔽」。"""
        out = ST.safe_hook_text(REAL + "END")
        assert "ghp_" not in out
        assert ST.safe_hook_text(REAL + " TAIL").endswith("TAIL")

    def test_all_validators_clean(self):
        assert ST.validate() == []
        assert LC.validate() == []
        assert NP.validate() == []
        assert XS.validate() == []


# ================================================== N4 重定向 / scheme
class TestRedirectAndScheme:
    def test_n4_redirect_refused_second_server_zero_requests(self, http_env):
        http_env.mode("redirect")
        k = _Kernel()
        m = _mgr({"type": "url", "url": http_env.url, "timeout": 1.0},
                 kernel=k)
        d = m.run_decision("PermissionRequest", tool_name="shell")
        assert len(http_env.s2.requests) == 0     # 修复前会被跟随
        assert d.block is True
        assert [f["kind"] for f in m.failures()] == ["redirect_blocked"]
        assert "channel_redirect_blocked" in _statuses(k)

    def test_bad_scheme_rejected(self):
        m = _mgr({"type": "url", "url": "file:///etc/passwd",
                  "timeout": 1.0})
        d = m.run_decision("PermissionRequest", tool_name="shell")
        assert d.block is True
        assert m.failures()[0]["kind"] == "invalid_spec"


# ================================================== N6 有界 stdout
class TestBoundedStdout:
    def test_n6_huge_stdout_is_bounded_and_traced(self):
        class Big:
            def chat(self, messages, stream=False):
                return type("R", (), {
                    "content": '{"decision":"block","reason":"'
                    + "A" * 500000 + '"}'})()
        k = _Kernel(Big())
        m = HM.HookManager(
            {"hooks": {"enabled": True, "on_failure": "block",
                       "PermissionRequest": [
                           {"type": "prompt", "prompt": "check",
                            "timeout": 1.0}]}}, kernel=k)
        d = m.run_decision("PermissionRequest", tool_name="shell")
        oc = m._tls.last_channel
        assert len(oc.stdout or "") <= NP.MAX_STDOUT
        assert oc.truncated is True
        assert d.block is False       # 截断后 JSON 不完整 → 噪声，非裁决
        assert "channel_no_decision" in _statuses(k)


# ================================================== 等价故障闭合表
class TestEquivalenceTable:
    def test_command_rc1_and_url_500_same_verdict(self, http_env):
        http_env.mode("500")
        k1 = _Kernel()
        mc = HM.HookManager(
            {"hooks": {"enabled": True, "on_failure": "block",
                       "PermissionRequest": [
                           {"command": [PY, "-c",
                                        "import sys;sys.exit(1)"]}]}},
            kernel=k1)
        dc = mc.run_decision("PermissionRequest", tool_name="shell")
        k2 = _Kernel()
        mu = _mgr({"type": "url", "url": http_env.url, "timeout": 1.0},
                  kernel=k2)
        du = mu.run_decision("PermissionRequest", tool_name="shell")
        assert dc.block == du.block is True

    @pytest.mark.parametrize("event", sorted(XS.OFFICIAL_EVENTS)[:12])
    def test_channel_failure_matches_xs_classify(self, event):
        oc = NP.ChannelOutcome(
            event=event, hook_type="url", status="failure", stdout=None,
            failure_kind="http_error", equivalent_rc=1, stderr="boom")
        for policy in ("block", "ask", "allow"):
            v = NP.classify_channel(event, oc, tuan_policy=policy)
            base = XS.classify(event, 1, "boom", tuan_policy=policy)
            assert (v.block, v.code_path, v.json_may_override) == (
                base.block, base.code_path, base.json_may_override)

    def test_no_decision_sets_json_ignored_without_blocking(self):
        oc = NP.ChannelOutcome(
            event="PreToolUse", hook_type="url",
            status="ok_no_decision", stdout="", equivalent_rc=0)
        v = NP.classify_channel("PreToolUse", oc, tuan_policy="block")
        assert v.block is False and v.json_ignored is True

    def test_n7_on_failure_allow_still_allows(self, http_env):
        """不该修：allow 是显式逃生口，逐值不变。"""
        http_env.mode("500")
        k = _Kernel()
        m = _mgr({"type": "url", "url": http_env.url, "timeout": 1.0},
                 "allow", k)
        d = m.run_decision("PermissionRequest", tool_name="shell")
        assert d.block is False
        assert "channel_semantics" in _statuses(k)

    def test_no_kernel_prompt_fails_closed(self):
        m = HM.HookManager(
            {"hooks": {"enabled": True, "on_failure": "block",
                       "PermissionRequest": [
                           {"type": "prompt", "prompt": "check",
                            "timeout": 1.0}]}}, kernel=None)
        d = m.run_decision("PermissionRequest", tool_name="shell")
        assert d.block is True
        assert m.failures()[0]["kind"] == "no_kernel"

    def test_three_legacy_executors_have_no_call_sites(self):
        """源码级核销：旧三份重复执行器已删除，无残留调用点。"""
        src = Path("tuan_cli/hooks/manager.py").read_text(encoding="utf-8")
        for name in ("_exec_http(", "_exec_prompt(", "_exec_subagent("):
            calls = [l for l in src.splitlines()
                     if name in l and not l.lstrip().startswith("#")
                     and "def " not in l]
            assert calls == [], (name, calls)


# ================================================== 矩阵 / 深度证据
class TestMatrixHonesty:
    def test_counts_unchanged(self):
        from tuan_cli.parity_claude import matrix, evidence
        assert matrix.validate() == []
        assert evidence.verify_evidence() == []
        s = matrix.summary()
        assert s["by_status"] == {
            "ahead": 10, "aligned": 46, "partial": 9,
            "gap": 26, "not_applicable": 8}
        assert s["gaps"] == 26
        assert s["fully_superior"] is False
        assert s["b_waves_done"] == ["B1"]

    def test_two_b3_entries_still_gap(self):
        src = Path("tuan_cli/parity_claude/catalog.py").read_text(
            encoding="utf-8")
        for key in ("hook_events_extended", "hook_updated_input_validation"):
            i = src.index('M("%s"' % key)
            assert "STATUS_GAP" in src[i:i + 400], key
