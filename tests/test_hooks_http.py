"""Hooks http 执行类型 + 启用/禁用 CLI 测试 (本地起 HTTP 服务, 不连外部)。

覆盖:
- url 类型 hook (PreToolUse): 本地 HTTP 端点收到 JSON-RPC 风格 payload,
  返回决策 JSON, run_pre 正确解析 block / modified_args。
- url 类型 hook 的 PostToolUse / 通知事件: 正常 POST 不报错。
- `tuan hooks enable/disable`: 写入 hooks.enabled 用户层配置。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tuan_cli.hooks import HookManager


class _Recorder:
    """收集 hook 请求并按脚本返回响应。"""

    def __init__(self, response: dict):
        self.response = response
        self.requests: list[dict] = []
        self.lock = threading.Lock()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        rec: _Recorder = self.server.recorder  # type: ignore[attr-defined]
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        with rec.lock:
            rec.requests.append(payload)
        data = json.dumps(rec.response, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture()
def http_endpoint():
    def _start(response: dict) -> tuple:
        rec = _Recorder(response)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        srv.recorder = rec  # type: ignore[attr-defined]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        return srv, f"http://127.0.0.1:{srv.server_address[1]}"

    yield _start


import pytest  # noqa: E402


def _cfg(block: dict) -> dict:
    return {"hooks": block}


# ------------------------------------------------------------------ http PreToolUse 阻断
def test_http_hook_pre_block(http_endpoint):
    srv, url = http_endpoint({"decision": "block", "reason": "blocked-by-http"})
    try:
        mgr = HookManager(_cfg({
            "allow_blocking": True,
            "PreToolUse": [{"matcher": "delete_*", "type": "url", "url": url,
                            "blocking": True}],
        }))
        d = mgr.run_pre("delete_file", {"path": "/x"})
        assert d.block is True
        assert "blocked-by-http" in d.reason
        # 确认本地端点确实收到了 PreToolUse payload
        rec = srv.recorder  # type: ignore[attr-defined]
        assert rec.requests, "HTTP hook 应发出请求"
        assert rec.requests[0].get("hook_event_name") == "PreToolUse"
        assert rec.requests[0].get("tool_name") == "delete_file"
    finally:
        srv.shutdown()
        srv.server_close()


def test_http_hook_pre_modify_args(http_endpoint):
    srv, url = http_endpoint({"args": {"path": "/safe", "_hook_injected": "yes"}})
    try:
        mgr = HookManager(_cfg({
            "allow_edit_args": True,
            "PreToolUse": [{"matcher": "*", "type": "url", "url": url}],
        }))
        d = mgr.run_pre("write_file", {"path": "/x"})
        assert d.block is False
        assert d.args is not None
        assert d.args.get("_hook_injected") == "yes"
        assert d.args.get("path") == "/safe"
    finally:
        srv.shutdown()
        srv.server_close()


def test_http_hook_post_notification(http_endpoint):
    srv, url = http_endpoint({})
    try:
        mgr = HookManager(_cfg({
            "PostToolUse": [{"matcher": "*", "type": "url", "url": url}],
        }))
        mgr.run_post("read_file", {"path": "/x"}, None)
        rec = srv.recorder  # type: ignore[attr-defined]
        assert rec.requests, "PostToolUse http hook 应发出请求"
        assert rec.requests[0].get("hook_event_name") == "PostToolUse"
    finally:
        srv.shutdown()
        srv.server_close()


# ------------------------------------------------------------------ enable / disable CLI
def test_hooks_set_enabled_writes_config(tuan_home):
    from tuan_cli.cli.cmd_hooks import _hooks_set_enabled

    # 禁用后应写入 hooks.enabled=false
    assert _hooks_set_enabled(False) == 0
    from tuan_cli.config import Config
    cfg = Config()
    assert cfg.get("hooks.enabled") is False
    # 重新启用
    assert _hooks_set_enabled(True) == 0
    cfg2 = Config()
    assert cfg2.get("hooks.enabled") is True
