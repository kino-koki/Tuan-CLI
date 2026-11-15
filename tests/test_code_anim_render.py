# -*- coding: utf-8 -*-
"""code_anim_render 渲染后端测试。

覆盖: 每类节点绘制 / 帧稳定 / 越界节点跳过 / 真实 ffmpeg 渲染 mp4 /
非法 project_json 拒绝 / 未知节点类型跳过。
"""
import json
import os
import threading
import time
import urllib.request

import pytest

from tuan_cli.web import code_anim_render as car


# ---------------------------------------------------------------------------
# 本地 HTTP server fixture (与 test_web_server 同款模式, 避免跨文件依赖)
# ---------------------------------------------------------------------------

@pytest.fixture()
def server(tmp_path):
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
    yield srv
    if srv._httpd is not None:
        try:
            srv._httpd.shutdown()
        except Exception:  # noqa: BLE001
            pass
        srv._httpd.server_close()
    ws_mod._SESSIONS.clear()


def _base_project(**overrides):
    pj = {
        "width": 128,
        "height": 72,
        "fps": 5,
        "duration": 0.5,
        "nodes": [],
    }
    pj.update(overrides)
    return pj


# ---------------------------------------------------------------------------
# draw_frame: 每类节点渲染不报错
# ---------------------------------------------------------------------------

def test_draw_frame_each_node_type():
    node_specs = [
        ("code", {"code": "def f(x):\n    return x + 1", "language": "python",
                  "title": "demo.py", "highlight": [[0, 0]], "caret": True}),
        ("title", {"text": "Big Title", "font_size": 24}),
        ("subtitle", {"text": "caption text", "typewriter": True}),
        ("box", {"x": 10, "y": 10, "w": 60, "h": 40, "label": "L"}),
        ("dataflow", {"x1": 5, "y1": 5, "x2": 100, "y2": 60, "dash": True, "dot": True}),
        ("bg", {"type": "gradient"}),
    ]
    for ntype, props in node_specs:
        pj = _base_project(nodes=[{"type": ntype, "start": 0.0, "end": 5.0,
                                   "props": props}])
        img = car.draw_frame(pj, 1.5)
        assert img is not None
        assert img.size == (128, 72)
        assert len(img.tobytes()) == 128 * 72 * 3


def test_draw_frame_bg_grid_and_solid():
    for btype in ("solid", "grid", "gradient"):
        pj = _base_project(nodes=[{"type": "bg", "start": 0.0, "end": 5.0,
                                   "props": {"type": btype}}])
        img = car.draw_frame(pj, 0.5)
        assert img.size == (128, 72)


# ---------------------------------------------------------------------------
# 帧稳定: draw_frame(pj, t) 是纯函数
# ---------------------------------------------------------------------------

def test_draw_frame_frame_stable():
    pj = _base_project(nodes=[
        {"type": "code", "start": 0.0, "end": 5.0,
         "props": {"code": "for i in range(10):\n    print(i)", "language": "python"}},
        {"type": "title", "start": 0.0, "end": 5.0, "props": {"text": "Stable"}},
        {"type": "box", "start": 0.0, "end": 5.0, "props": {"x": 4, "y": 4, "w": 30, "h": 20}},
        {"type": "dataflow", "start": 0.0, "end": 5.0,
         "props": {"x1": 0, "y1": 0, "x2": 120, "y2": 70, "dot": True}},
    ])
    a = car.draw_frame(pj, 1.5).tobytes()
    b = car.draw_frame(pj, 1.5).tobytes()
    assert a == b


# ---------------------------------------------------------------------------
# 越界节点跳过
# ---------------------------------------------------------------------------

def test_node_outside_range_skipped():
    bg = {"type": "bg", "start": 0.0, "end": 5.0, "props": {"type": "solid"}}
    # 节点 start=10 > t=1.5, 应跳过
    out_node = {"type": "title", "start": 10.0, "end": 20.0, "props": {"text": "X"}}
    only_bg = car.draw_frame(_base_project(nodes=[bg]), 1.5)
    with_node = car.draw_frame(_base_project(nodes=[bg, out_node]), 1.5)
    assert only_bg.tobytes() == with_node.tobytes()


def test_unknown_node_type_skipped():
    bg = {"type": "bg", "start": 0.0, "end": 5.0, "props": {"type": "solid"}}
    evil = {"type": "exec", "start": 0.0, "end": 5.0,
            "props": {"cmd": "import os; os.system('echo pwned')"}}
    base = car.draw_frame(_base_project(nodes=[bg]), 1.0)
    with_evil = car.draw_frame(_base_project(nodes=[bg, evil]), 1.0)
    assert base.tobytes() == with_evil.tobytes()


# ---------------------------------------------------------------------------
# render_video: 真实 ffmpeg 渲染 mp4
# ---------------------------------------------------------------------------

def test_render_video_produces_mp4(tmp_path):
    if not car.ffmpeg_available():
        pytest.skip("ffmpeg 不可用")
    pj = _base_project(duration=0.5, fps=5, nodes=[
        {"type": "bg", "start": 0.0, "end": 5.0, "props": {"type": "solid"}},
        {"type": "code", "start": 0.0, "end": 5.0,
         "props": {"code": "x = 1\nprint(x)", "language": "python"}},
    ])
    out = tmp_path / "out.mp4"
    res = car.render_video(pj, str(out), fps=5)
    assert os.path.isfile(out)
    assert out.stat().st_size > 0
    assert res["frames"] == 3
    assert res["out_path"] == str(out)


def test_render_contact_sheet(tmp_path):
    pj = _base_project(nodes=[
        {"type": "bg", "start": 0.0, "end": 5.0, "props": {"type": "gradient"}},
        {"type": "title", "start": 0.0, "end": 5.0, "props": {"text": "Sheet"}},
    ])
    out = tmp_path / "sheet.png"
    res = car.render_contact_sheet(pj, [0.0, 0.25, 0.5], str(out))
    assert os.path.isfile(out)
    assert out.stat().st_size > 0
    assert res["times"] == [0.0, 0.25, 0.5]


# ---------------------------------------------------------------------------
# 非法 project_json 拒绝
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mutate,expect_err", [
    (lambda p: p.update(duration=-1), True),
    (lambda p: p.update(width=0), True),
    (lambda p: p.pop("width"), True),
    (lambda p: p.update(nodes="notalist"), True),
    (lambda p: p.update(fps=0), True),
])
def test_invalid_project_rejected(mutate, expect_err):
    pj = _base_project()
    mutate(pj)
    err = car.validate_project(pj)
    if expect_err:
        assert err is not None
    else:
        assert err is None


def test_render_video_invalid_raises(tmp_path):
    with pytest.raises(ValueError):
        car.render_video({"width": -5, "height": 10, "fps": 5, "duration": 1,
                          "nodes": []}, str(tmp_path / "x.mp4"))


# ---------------------------------------------------------------------------
# 服务器方法: 状态 / 渲染 / 接触表
# ---------------------------------------------------------------------------

def test_status_available():
    st = car.status()
    assert "available" in st
    # 环境已验证 Pillow+ffmpeg, 应当 available
    assert st["available"] is True
    assert st["ffmpeg"]


def test_web_methods_render_and_contact(tmp_path):
    from tuan_cli.web.server import WebServer

    ws = WebServer.__new__(WebServer)  # 不跑 __init__, 只测方法
    ws.workspace = str(tmp_path)

    pj = _base_project(nodes=[
        {"type": "bg", "start": 0.0, "end": 5.0, "props": {"type": "solid"}},
    ])
    # 非法输入 → ok False
    bad = ws.codeanim_render({"width": -1, "height": 10, "fps": 5,
                              "duration": 1, "nodes": []})
    assert bad["ok"] is False
    # 合法 → 后台 job
    res = ws.codeanim_render(pj, out="test.mp4")
    assert res["ok"] is True
    assert res["job_id"]
    assert res["out_rel"] == "test.mp4"
    # 轮询等待完成
    job = None
    for _ in range(50):
        job = car.get_job(res["job_id"])
        if job and job.get("status") in ("done", "error"):
            break
        time.sleep(0.1)
    assert job is not None
    assert job["status"] == "done", job.get("error")
    out_abs = os.path.join(str(tmp_path), ".tuan", "codeanim", "test.mp4")
    assert os.path.isfile(out_abs)

    # 接触表
    cres = ws.codeanim_contact(pj, times=[0.0, 0.2])
    assert cres["ok"] is True
    cjob = None
    for _ in range(50):
        cjob = car.get_job(cres["job_id"])
        if cjob and cjob.get("status") in ("done", "error"):
            break
        time.sleep(0.1)
    assert cjob is not None
    assert cjob["status"] == "done", cjob.get("error")


# ---------------------------------------------------------------------------
# 端到端 HTTP 路由 (复用 test_web_server 的 server fixture)
# ---------------------------------------------------------------------------

def test_http_status_route(server):
    import urllib.request
    url = f"http://127.0.0.1:{server.port}/api/codeanim/status"
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.loads(r.read().decode("utf-8"))
    assert data["ok"] is True
    assert data["available"] is True


def test_http_render_and_media_route(server):
    import urllib.request
    base = f"http://127.0.0.1:{server.port}"
    pj = _base_project(duration=0.5, fps=5, nodes=[
        {"type": "bg", "start": 0.0, "end": 5.0, "props": {"type": "solid"}},
    ])
    # 非法输入 → 400
    req = urllib.request.Request(
        base + "/api/codeanim/render",
        data=json.dumps({"project_json": {"width": -1, "height": 1, "fps": 5,
                                          "duration": 1, "nodes": []}}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        assert data["ok"] is False
    except urllib.error.HTTPError as e:
        assert e.code == 400
        assert json.loads(e.read().decode())["ok"] is False
    # 合法 → 后台 job
    req = urllib.request.Request(
        base + "/api/codeanim/render",
        data=json.dumps({"project_json": pj, "out": "http_test.mp4"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode())
    assert data["ok"] is True
    jid = data["job_id"]
    # 轮询 job
    job = None
    for _ in range(50):
        with urllib.request.urlopen(
                f"{base}/api/codeanim/job?id={jid}", timeout=10) as r:
            job = json.loads(r.read().decode())["job"]
        if job and job.get("status") in ("done", "error"):
            break
        time.sleep(0.1)
    assert job is not None
    assert job["status"] == "done", job.get("error")
    assert job["out_path"]
    # media 路由: 用相对路径 (文件名) 访问
    rel = os.path.basename(job["out_path"])
    media_url = f"{base}/api/codeanim/media?path={rel}"
    with urllib.request.urlopen(media_url, timeout=10) as r:
        raw = r.read()
    assert len(raw) > 0
    assert r.headers.get("Content-Type") == "video/mp4"
    # 路径护栏: `..` 被拒绝
    req = urllib.request.Request(
        base + "/api/codeanim/media?path=..%2F..%2Fetc%2Fpasswd")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        assert data["ok"] is False
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_http_contact_route(server):
    import urllib.request
    base = f"http://127.0.0.1:{server.port}"
    pj = _base_project(nodes=[
        {"type": "bg", "start": 0.0, "end": 5.0, "props": {"type": "solid"}},
    ])
    req = urllib.request.Request(
        base + "/api/codeanim/contact",
        data=json.dumps({"project_json": pj, "times": [0.0, 0.2]}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode())
    assert data["ok"] is True
    jid = data["job_id"]
    job = None
    for _ in range(50):
        with urllib.request.urlopen(
                f"{base}/api/codeanim/job?id={jid}", timeout=10) as r:
            job = json.loads(r.read().decode())["job"]
        if job and job.get("status") in ("done", "error"):
            break
        time.sleep(0.1)
    assert job is not None
    assert job["status"] == "done", job.get("error")
    assert job["out_path"].endswith(".png")
