# -*- coding: utf-8 -*-
"""阶段 13 —— 数据流图前端闭环测试 (/web/graph 页面 + /api/media 媒体回放护栏)。"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

from tuan_cli.web.graph_frontend import GRAPH_HTML


def _make_server(tmp_path):
    from tuan_cli.web import server as ws_mod
    from tuan_cli.web.server import WebServer

    ws_mod._SESSIONS.clear()
    srv = WebServer(kernel=None, workspace=str(tmp_path), port=0)
    srv.set_agent_factory(lambda: None)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    for _ in range(50):
        if srv._httpd is not None:
            break
        time.sleep(0.05)
    return srv


def _get(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


def test_graph_frontend_served(tmp_path):
    """GET /web/graph → 200 + 三栏工作台 HTML (含画布/结果面板)。"""
    srv = _make_server(tmp_path)
    try:
        status, body = _get(f"http://127.0.0.1:{srv.port}/web/graph")
        assert status == 200
        text = body.decode("utf-8")
        assert "数据流图工作台" in text
        assert 'id="canvas"' in text
        assert 'id="results"' in text
        assert "/api/graph/run" in text
        assert "/api/graph/save" in text
        assert "/api/graph/list" in text
        assert "llm_call" in text and "codeanim" in text
    finally:
        srv._httpd.shutdown()
        srv._httpd.server_close()


def test_graph_frontend_no_cdn():
    """页面零外部 CDN (断网可用, 自包含)。"""
    assert "cdn." not in GRAPH_HTML.lower()
    assert "https://" not in GRAPH_HTML.replace("https://www.w3.org", "")


def test_api_media_serves_workspace_file(tmp_path):
    """GET /api/media?path=<rel> 回放 workspace/media/ 下产物 (png 200)。"""
    srv = _make_server(tmp_path)
    try:
        media = tmp_path / "media"
        media.mkdir(parents=True, exist_ok=True)
        png = media / "frame.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        status, body = _get(
            f"http://127.0.0.1:{srv.port}/api/media?path=frame.png")
        assert status == 200
        assert body.startswith(b"\x89PNG")
    finally:
        srv._httpd.shutdown()
        srv._httpd.server_close()


def test_api_media_path_traversal_rejected(tmp_path):
    """GET /api/media?path=../ → 400 (路径逃逸护栏)。"""
    srv = _make_server(tmp_path)
    try:
        try:
            status, _ = _get(
                f"http://127.0.0.1:{srv.port}/api/media?path=..%2Fsecret.txt")
        except urllib.error.HTTPError as e:
            status = e.code
        assert status == 400
    finally:
        srv._httpd.shutdown()
        srv._httpd.server_close()


def test_api_media_missing_404(tmp_path):
    """GET /api/media?path=ghost.mp4 → 404。"""
    srv = _make_server(tmp_path)
    try:
        try:
            status, _ = _get(
                f"http://127.0.0.1:{srv.port}/api/media?path=ghost.mp4")
        except urllib.error.HTTPError as e:
            status = e.code
        assert status == 404
    finally:
        srv._httpd.shutdown()
        srv._httpd.server_close()
