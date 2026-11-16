# -*- coding: utf-8 -*-
"""阶段20: 数据流图运行历史持久化 + HTTP 路由。"""
import json
import shutil
import threading
import urllib.request
import urllib.error
import pathlib

import pytest

from tuan_cli.web.graph_api import RunLog


@pytest.fixture()
def ws(tmp_path):
    """临时 workspace (隔离运行记录)。"""
    w = tmp_path / "ws"
    w.mkdir()
    return str(w)


def test_runlog_record_and_list(ws):
    rl = RunLog(ws)
    rec = rl.record("demo", "演示", True, None, {"ok_nodes": 1, "media": ["a.mp4"]},
                    {"nodes": [{"node_id": "a", "ntype": "text"}], "edges": []})
    assert rec["run_id"].startswith("run_")
    assert rec["ok"] is True
    assert rec["name"] == "演示"
    runs = rl.list_runs()
    assert len(runs) == 1
    assert runs[0]["graph_id"] == "demo"
    assert runs[0]["summary"]["ok_nodes"] == 1


def test_runlog_failure_recorded(ws):
    rl = RunLog(ws)
    rl.record("demo", "演示", False, "provider 未配置", {},
              {"nodes": [], "edges": []})
    runs = rl.list_runs()
    assert len(runs) == 1
    assert runs[0]["ok"] is False
    assert runs[0]["error"] == "provider 未配置"


def test_runlog_load_and_missing(ws):
    rl = RunLog(ws)
    rec = rl.record("g", "名字", True, None, {}, {"nodes": [], "edges": []})
    loaded = rl.load(rec["run_id"])
    assert loaded["name"] == "名字"
    assert loaded["data"]["nodes"] == []
    assert rl.load("run_9999999999999") is None
    assert rl.load("../etc/passwd") is None  # 路径护栏
    assert rl.load("") is None


def test_runlog_prune_keeps_max(ws):
    rl = RunLog(ws)
    for i in range(5):
        rl.record(f"g{i}", f"图{i}", True, None, {}, {"nodes": [], "edges": []})
    # 塞入 MAX_RUNS+2 条, 超出清理最旧
    rl2 = RunLog(ws)
    for i in range(102):
        rl2.record(f"g{i}", f"图{i}", True, None, {}, {"nodes": [], "edges": []})
    runs = rl2.list_runs()
    assert len(runs) <= 100


def test_runlog_order_newest_first(ws):
    rl = RunLog(ws)
    for i in range(3):
        rl.record(f"g{i}", f"图{i}", True, None, {}, {"nodes": [], "edges": []})
    runs = rl.list_runs()
    names = [r["name"] for r in runs]
    assert names == sorted(names, reverse=True) or len(set(names)) == 3
    # 时间戳非递增 → 最新在首位 (ts 以毫秒递增)
    ts = [r["ts"] for r in runs]
    assert ts == sorted(ts, reverse=True)


# ---------------------------------------------------------------------------
# HTTP 路由: /api/graph/runs (list) + /api/graph/runlog (单条)
# ---------------------------------------------------------------------------

def _make_server(ws):
    from tuan_cli.web.server import WebServer
    srv = WebServer(kernel=None, workspace=ws, port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    for _ in range(200):
        if getattr(srv, "_httpd", None) is not None:
            break
        import time
        time.sleep(0.02)
    return srv, srv.port, t


def _get(port, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def test_http_runs_routes(ws):
    srv, port, t = _make_server(ws)
    try:
        # 先通过 run 路由触发一次成功记录 (用最小 text 图)
        import json as _json
        body = _json.dumps({
            "data": {"nodes": [{"node_id": "a", "ntype": "text",
                                "params": {"content": "历史测试"},
                                "inputs": [], "outputs": [{"name": "out", "ptype": "any"}]}],
                     "edges": []},
            "graph_id": "hist", "name": "历史测试图"}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/graph/run", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=20) as r:
            run_res = json.loads(r.read().decode())
        assert run_res.get("ok") is True
        # list runs
        st, res = _get(port, "/api/graph/runs")
        assert st == 200 and res["ok"] is True
        runs = res["runs"]
        assert len(runs) == 1
        assert runs[0]["graph_id"] == "hist"
        assert runs[0]["ok"] is True
        assert runs[0]["summary"]["ok_nodes"] >= 1
        rid = runs[0]["run_id"]
        # single runlog
        st2, res2 = _get(port, f"/api/graph/runlog?id={rid}")
        assert st2 == 200 and res2["ok"] is True
        assert res2["run"]["name"] == "历史测试图"
        assert res2["run"]["data"]["nodes"][0]["ntype"] == "text"
        # missing runlog → 404
        st3, res3 = _get(port, "/api/graph/runlog?id=run_404")
        assert st3 == 404 and res3["ok"] is False
    finally:
        if getattr(srv, "_httpd", None) is not None:
            srv._httpd.shutdown()
            srv._httpd.server_close()
        t.join(timeout=5)


def test_http_runs_records_failure(ws):
    """失败运行也记录 (llm_call 无 provider → fail-closed, 记录 ok=False)。"""
    srv, port, t = _make_server(ws)
    try:
        body = json.dumps({
            "data": {"nodes": [{"node_id": "llm", "ntype": "llm_call",
                                "params": {"prompt": "hi"},
                                "inputs": [], "outputs": [{"name": "out", "ptype": "any"}]}],
                     "edges": []},
            "graph_id": "bad", "name": "失败图"}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/graph/run", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=20) as r:
            run_res = json.loads(r.read().decode())
        assert run_res.get("ok") is False
        st, res = _get(port, "/api/graph/runs")
        assert st == 200
        runs = res["runs"]
        assert len(runs) == 1
        assert runs[0]["ok"] is False
        assert runs[0]["graph_id"] == "bad"
    finally:
        if getattr(srv, "_httpd", None) is not None:
            srv._httpd.shutdown()
            srv._httpd.server_close()
        t.join(timeout=5)


# ---------------------------------------------------------------------------
# 前端断言
# ---------------------------------------------------------------------------

def test_frontend_has_runs_controls():
    from tuan_cli.web.graph_frontend import GRAPH_HTML
    assert "运行历史" in GRAPH_HTML
    assert 'id="runsBtn"' in GRAPH_HTML
    assert 'id="runsList"' in GRAPH_HTML
    assert "refreshRuns" in GRAPH_HTML
    assert 'api("/api/graph/runs")' in GRAPH_HTML
    assert 'api("/api/graph/runlog?id="' in GRAPH_HTML
    # run 请求带 graph_id/name (供后端记录)
    assert "graph_id: $(\"#gname\").value" in GRAPH_HTML
    assert "refreshRuns();" in GRAPH_HTML
