# -*- coding: utf-8 -*-
"""WebUI 思考过程可见性 + 流式慢/中断修复 回归测试。

覆盖:
- ChunkFlusher: token 分片合并落盘 (批量/顺序/尾部 flush)
- StreamInterrupted: 已流出部分 token 后失败不重试 (防重复输出)
- AgentResilience: partial-then-fail → StreamInterrupted 单次调用; 未流出 → 照常重试
- Web 服务端: TCP_NODELAY / SSE 心跳常量 / save_sessions 防抖 / reason 事件端到端
- 前端静态: 思考过程累积渲染 / 思考状态 pill / i18n 键
"""
from __future__ import annotations

import inspect
import json
import re
import threading
import time
import urllib.request

import pytest

from tuan_cli.config import Config
from tuan_cli.core.agent_helpers import ChunkFlusher
from tuan_cli.core.resilience import AgentResilience
from tuan_cli.core.retry import RetryPolicy, StreamInterrupted
from tuan_cli.web import server as ws_mod
from tuan_cli.web.frontend import FRONTEND_HTML
from tuan_cli.web.server import WebServer


# ---------------------------------------------------------------- ChunkFlusher

class TestChunkFlusher:
    def test_batches_by_size_and_order(self):
        got = []
        f = ChunkFlusher(got.append, max_chars=10)
        for i in range(100):
            f.add("x")
        assert "".join(got) == "x" * 100
        assert all(len(c) <= 10 for c in got)     # 每批 <= 阈值 (尾部除外由 flush 补)
        assert len(got) >= 10                      # 确实发生了合并 (不是 100 次)

    def test_flush_emits_remainder(self):
        got = []
        f = ChunkFlusher(got.append, max_chars=1000)
        f.add("abc")
        assert got == []                # 不满阈值不落
        f.flush()
        assert got == ["abc"]           # 尾部被冲出

    def test_flush_idempotent(self):
        got = []
        f = ChunkFlusher(got.append, max_chars=1000)
        f.add("a")
        f.flush()
        f.flush()
        assert got == ["a"]

    def test_empty_add_ignored(self):
        got = []
        f = ChunkFlusher(got.append)
        f.add("")
        f.flush()
        assert got == []

    def test_concatenation_equals_stream(self):
        """合并落盘的语义: 拼接结果与逐 delta 完全一致。"""
        import random
        rng = random.Random(42)
        deltas = ["".join(rng.choice("你好abc\n") for _ in range(rng.randint(1, 9)))
                  for _ in range(500)]
        got = []
        f = ChunkFlusher(got.append, max_chars=64)
        for d in deltas:
            f.add(d)
        f.flush()
        assert "".join(got) == "".join(deltas)

    def test_sink_failure_does_not_raise(self):
        def _bad(_t):
            raise OSError("disk full")
        f = ChunkFlusher(_bad, max_chars=1)
        f.add("x")     # 不抛即通过
        f.flush()


# ---------------------------------------------------------------- StreamInterrupted

class TestStreamInterrupted:
    def test_no_retry_after_partial_stream(self):
        calls = []

        def _fn():
            calls.append(1)
            raise StreamInterrupted("conn reset mid-stream")

        p = RetryPolicy(max_retries=3, backoff=0.0, jitter=0.0, sleep=lambda s: None)
        with pytest.raises(StreamInterrupted):
            p.call(_fn)
        assert len(calls) == 1          # 一次都不多重试

    def test_plain_error_still_retried(self):
        calls = []

        def _fn():
            calls.append(1)
            raise TimeoutError("read timeout")

        p = RetryPolicy(max_retries=3, backoff=0.0, jitter=0.0,
                        retry_on={408, 429, 500, 502, 503, 504}, sleep=lambda s: None)
        with pytest.raises(RuntimeError):
            p.call(_fn)
        assert len(calls) == 3          # 普通瞬时错误照常满额重试


# ---------------------------------------------------------------- AgentResilience

class _FakeKernel:
    def emit(self, *_a, **_k):
        pass


class _FlakyModel:
    """第一次调用流出半个回答后炸掉; 记录调用次数。"""

    def __init__(self, fail_before_token: bool):
        self.fail_before_token = fail_before_token
        self.calls = 0

    def chat(self, messages, tools=None, stream=False, on_token=None, on_reason=None):
        self.calls += 1
        if not self.fail_before_token:
            if on_reason:
                on_reason("思考中...")
            if on_token:
                on_token("半截回答")
        raise TimeoutError("read timeout")


def _resilience():
    cfg = Config(bare=True)
    cfg.data["agent"] = {"max_retries": 3, "retry_backoff": 0.0,
                         "retry_jitter": 0.0,
                         "retry_on": [408, 429, 500, 502, 503, 504]}
    return AgentResilience(cfg, _FakeKernel())


class TestResilienceStreamGuard:
    def test_partial_then_fail_is_fatal(self):
        m = _FlakyModel(fail_before_token=False)
        r = _resilience()
        with pytest.raises(StreamInterrupted):
            r.chat_with_retry(m, [], [], True, on_token=lambda t: None)
        assert m.calls == 1             # 不重试 → 不会重复输出

    def test_fail_before_token_retries(self):
        m = _FlakyModel(fail_before_token=True)
        r = _resilience()
        with pytest.raises(Exception):
            r.chat_with_retry(m, [], [], True, on_token=lambda t: None)
        assert m.calls == 3             # 未流出 → 照常重试

    def test_reasoning_counts_as_emitted(self):
        """只流出了思考 (无正文) 后失败, 同样不应重试。"""
        class _M:
            def __init__(self):
                self.calls = 0
            def chat(self, messages, tools=None, stream=False, on_token=None, on_reason=None):
                self.calls += 1
                if on_reason:
                    on_reason("思考")
                raise TimeoutError("reset")
        m = _M()
        r = _resilience()
        with pytest.raises(StreamInterrupted):
            r.chat_with_retry(m, [], [], True, on_token=lambda t: None,
                              on_reason=lambda t: None)
        assert m.calls == 1


# ---------------------------------------------------------------- Web 服务端

class _ReasonAgent:
    """ emits reasoning then text then tool — 模拟思考型模型的完整回合。"""

    def __init__(self):
        self.cancelled = False

    def run(self, user_input, stream=True, on_token=None, on_tool=None,
            on_tool_result=None, on_reason=None, on_error=None):
        if on_reason:
            on_reason("先想一下")
            on_reason("再想一下")
        if on_tool:
            on_tool("read_file", "a.py")
        if on_tool_result:
            on_tool_result("read_file", "file body")
        if on_token:
            on_token("最终")
            on_token("答案")
        return "最终答案"

    def cancel(self):
        self.cancelled = True


@pytest.fixture()
def server(tmp_path):
    ws_mod._SESSIONS.clear()
    srv = WebServer(kernel=None, workspace=str(tmp_path), port=0)
    srv.set_agent_factory(_ReasonAgent)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    for _ in range(50):
        if srv._httpd is not None:
            break
        time.sleep(0.05)
    yield srv
    if srv._httpd is not None:
        try:
            srv._httpd.shutdown()
        except Exception:  # noqa: BLE001
            pass
        srv._httpd.server_close()
    ws_mod._SESSIONS.clear()


class TestWebStreamHardening:
    def test_nodelay_enabled(self):
        from tuan_cli.web.server import _WebHandler
        assert _WebHandler.disable_nagle_algorithm is True

    def test_heartbeat_constant(self):
        assert 1.0 <= ws_mod._SSE_HEARTBEAT_SEC <= 30.0

    def test_reason_events_streamed(self, server):
        """端到端: 思考 delta 以独立 SSE 事件下发 (前端据此累积渲染)。"""
        url = f"http://{server.host}:{server.port}/api/chat"
        req = urllib.request.Request(
            url, data=json.dumps({"message": "hi"}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        events = []
        with urllib.request.urlopen(req, timeout=15) as resp:
            buf = b""
            while True:
                chunk = resp.read(256)
                if not chunk:
                    break
                buf += chunk
                while b"\n\n" in buf:
                    raw, buf = buf.split(b"\n\n", 1)
                    text = raw.decode("utf-8")
                    ev = [l[6:].strip() for l in text.split("\n") if l.startswith("event:")]
                    if ev:
                        events.append(ev[0])
        assert "reason" in events
        assert events.count("reason") == 2       # 两个思考 delta 各自成事件
        assert "delta" in events and "done" in events
        assert events.index("reason") < events.index("delta")  # 思考先于正文

    def test_history_parts_merge_reasoning(self, server):
        """落盘 parts 把连续思考 delta 合并成一段 (重开历史不碎片化)。"""
        url = f"http://{server.host}:{server.port}/api/chat"
        req = urllib.request.Request(
            url, data=json.dumps({"message": "hi"}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        sid = next(iter(ws_mod._SESSIONS))
        msgs = ws_mod._SESSIONS[sid]["messages"]
        assistant = [m for m in msgs if m.get("role") == "assistant"][-1]
        reasons = [p for p in assistant.get("parts", []) if p.get("type") == "reason"]
        assert len(reasons) == 1                  # 合并为一段
        assert reasons[0]["text"] == "先想一下再想一下"

    def test_save_sessions_soon_debounces(self, server, monkeypatch):
        calls = []
        monkeypatch.setattr(server, "save_sessions", lambda: calls.append(1))
        server.save_sessions_soon(delay=0.05)
        server.save_sessions_soon(delay=0.05)
        server.save_sessions_soon(delay=0.05)
        time.sleep(0.25)
        assert len(calls) == 1                    # 三次请求合并成一次落盘


# ---------------------------------------------------------------- 前端静态检查

class TestFrontendReasoningUI:
    def test_reason_accumulated_not_fragmented(self):
        """reason 事件必须累积进单个块 (而非每 delta 新建 appendReason)。"""
        assert "curReasonText" in FRONTEND_HTML
        assert "ensureReasonBlock" in FRONTEND_HTML
        assert "closeReasonBlock" in FRONTEND_HTML

    def test_thinking_pill_present(self):
        assert 'id="think-pill"' in FRONTEND_HTML
        assert "startThinkPill" in FRONTEND_HTML
        assert "stopThinkPill" in FRONTEND_HTML

    def test_interrupted_marker(self):
        assert "web.interrupted" in FRONTEND_HTML
        assert "web.stopped" in FRONTEND_HTML

    def test_export_includes_reasoning(self):
        assert "p.type==='reason'" in FRONTEND_HTML

    def test_i18n_keys_both_locales(self):
        from tuan_cli.i18n.locales import zh_CN, en
        for mod in (zh_CN, en):
            table = mod.TRANSLATIONS if hasattr(mod, "TRANSLATIONS") else mod.LOCALE
            for key in ("web.thinking", "web.thinking_process",
                        "web.interrupted", "web.stopped"):
                assert key in table, f"{mod.__name__} 缺 {key}"
