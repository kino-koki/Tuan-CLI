# -*- coding: utf-8 -*-
"""视频渲染工作台后端测试 (自研 code_anim_render 路径)。

自研后端不再调用外部 ``mh`` CLI / Node 子进程。render / preview 走
``tuan_cli.web.code_anim_render`` (Pillow + ffmpeg), 测试通过 monkeypatch
``mh_runner._renderer.render_video`` 隔离真实渲染, 不依赖 ffmpeg / Pillow。

覆盖:
  * /api/mh/status 不可用路径返回 ``{available:false}``
  * scaffold → write_scene_js → read_project 落盘往返
  * scene_js 静态校验 (拒绝缺 prepareFrame / export default / 含 eval)
  * project_id / media 路径穿越拒绝
  * render job 生命周期 (start → running → done) 用 fake renderer 驱动
  * /api/mh/media 路径护栏
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from tuan_cli.web import mh_runner
from tuan_cli.web import server as ws_mod
from tuan_cli.web.server import WebServer


class _FakeAgent:
    def run(self, *a, **k):
        return "ok"

    def cancel(self):
        pass


@pytest.fixture()
def server(tmp_path, monkeypatch):
    """启动真实 WebServer (端口 0), 但把 mh_runner 的所有子进程替换为桩。"""
    ws_mod._SESSIONS.clear()
    mh_runner._reset_jobs()
    # 强制 status = 不可用 (默认环境未装 mh), 单测再按需 monkeypatch resolve_mh
    monkeypatch.setenv("TUAN_MH_HOME", str(tmp_path / "no-such-mh"))
    monkeypatch.setenv("TUAN_MH_NODE", str(tmp_path / "no-such-node"))
    srv = WebServer(kernel=None, workspace=str(tmp_path), port=0)
    srv.set_agent_factory(_FakeAgent)
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
    mh_runner._reset_jobs()


# ---------------------------------------------------------------- HTTP helpers
def _get(url, expect_error=False):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if expect_error:
            return e.read().decode("utf-8")
        raise


def _getj(url, expect_error=False):
    return json.loads(_get(url, expect_error))


def _req(url, body=None, method="POST", expect_error=False):
    data = json.dumps(body or {}).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if expect_error:
            return json.loads(e.read().decode("utf-8"))
        raise


def _url(server, path):
    return f"http://127.0.0.1:{server.port}{path}"


# ---------------------------------------------------------------- 纯函数: 校验 / 路径
def test_scene_js_validation_rejects_missing_prepareframe():
    err = mh_runner.validate_scene_js("export default () => ({})")
    assert err and "prepareFrame" in err


def test_scene_js_validation_rejects_missing_export_default():
    err = mh_runner.validate_scene_js("const f = { prepareFrame(){} };")
    assert err and "export default" in err


def test_scene_js_validation_rejects_empty():
    assert mh_runner.validate_scene_js("")
    assert mh_runner.validate_scene_js("   \n  ")


def test_scene_js_validation_rejects_eval():
    bad = "export default { prepareFrame(){ eval('1+1') } }"
    err = mh_runner.validate_scene_js(bad)
    assert err and "eval" in err.lower()


def test_scene_js_validation_accepts_minimal_scene():
    scene = (
        "export default ({root, width, height}) => ({\n"
        "  prepareFrame(time){ root.innerHTML = `<b>${time}</b>`; },\n"
        "  dispose(){}\n"
        "});"
    )
    assert mh_runner.validate_scene_js(scene) is None


def test_mh_json_validation_requires_positive_numbers():
    assert mh_runner.validate_mh_json({"width": 0, "height": 100, "fps": 30, "duration": 1})
    assert mh_runner.validate_mh_json({"width": 100, "height": 100, "fps": 30})
    assert mh_runner.validate_mh_json({"width": "100", "height": 100, "fps": 30, "duration": 1})
    ok = {"width": 1280, "height": 720, "fps": 30, "duration": 4.0}
    assert mh_runner.validate_mh_json(ok) is None


def test_resolve_project_dir_rejects_traversal(tmp_path):
    root = tmp_path / ".tuan" / "mh"
    root.mkdir(parents=True)
    assert mh_runner.resolve_project_dir(str(tmp_path), "..") is None
    assert mh_runner.resolve_project_dir(str(tmp_path), "../escape") is None
    assert mh_runner.resolve_project_dir(str(tmp_path), "a/b") is None
    assert mh_runner.resolve_project_dir(str(tmp_path), "a\\b") is None
    assert mh_runner.resolve_project_dir(str(tmp_path), "") is None
    ok = mh_runner.resolve_project_dir(str(tmp_path), "proj1")
    assert ok is not None and str(ok).startswith(str(root))


def test_resolve_media_path_rejects_traversal(tmp_path):
    assert mh_runner.resolve_media_path(str(tmp_path), "../../etc/passwd") is None
    assert mh_runner.resolve_media_path(str(tmp_path), "/abs") is None
    assert mh_runner.resolve_media_path(str(tmp_path), "") is None
    ok = mh_runner.resolve_media_path(str(tmp_path), "proj/out.mp4")
    assert ok is not None and str(ok).startswith(str(tmp_path / ".tuan" / "mh"))


# ---------------------------------------------------------------- 单元: resolve_mh 不可用
def test_resolve_mh_reports_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("TUAN_MH_HOME", str(tmp_path / "no-mh"))
    monkeypatch.setenv("TUAN_MH_NODE", str(tmp_path / "no-node"))
    monkeypatch.delenv("PATH", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))  # 空 PATH, 没有可用的 mh
    res = mh_runner.resolve_mh()
    assert res["ok"] is False
    assert res["reason"]


# ---------------------------------------------------------------- HTTP: status unavailable
def test_status_unavailable(server):
    data = _getj(_url(server, "/api/mh/status"))
    assert data["ok"] is True
    assert data["available"] is False
    assert data["reason"]


# ---------------------------------------------------------------- HTTP: scaffold (mock mh new)
def test_scaffold_write_read_roundtrip(server, monkeypatch, tmp_path):
    """桩 scaffold_project: 直接在 mh 根下创建项目目录 + 写出 mh.json + scene.js。"""

    def fake_scaffold(base_dir, name=None):
        root = mh_runner._mh_root(base_dir)
        root.mkdir(parents=True, exist_ok=True)
        proj = root / "proj-x"
        proj.mkdir(parents=True, exist_ok=True)
        (proj / "mh.json").write_text(
            json.dumps({"width": 1280, "height": 720, "fps": 30, "duration": 4}),
            encoding="utf-8")
        (proj / "src").mkdir(exist_ok=True)
        (proj / "src" / "scene.js").write_text(
            "export default { prepareFrame(t){} }", encoding="utf-8")
        return {"project_id": "proj-x", "project_dir": str(proj),
                "mh_json_path": str(proj / "mh.json")}

    monkeypatch.setattr(mh_runner, "scaffold_project", fake_scaffold)

    data = _req(_url(server, "/api/mh/project"), body={"name": "demo"})
    assert data["ok"] is True
    assert data["project_id"] == "proj-x"
    assert data["mh_json"]["width"] == 1280
    assert "prepareFrame" in data["scene_js"]

    # 写 scene_js: 通过 PUT
    new_scene = (
        "export default ({root}) => ({\n"
        "  prepareFrame(t){ root.textContent = String(t); }\n"
        "});"
    )
    put = _req(_url(server, "/api/mh/scene"),
               body={"project_id": "proj-x", "scene_js": new_scene},
               method="PUT")
    assert put["ok"] is True

    # 读回
    got = _getj(_url(server, "/api/mh/project?id=proj-x"))
    assert got["ok"] is True
    assert "root.textContent" in got["scene_js"]

    # 列表
    listed = _getj(_url(server, "/api/mh/projects"))
    ids = [p["project_id"] for p in listed["projects"]]
    assert "proj-x" in ids

    # 写 mh_json: 缺字段 → 400
    bad = _req(_url(server, "/api/mh/mhjson"),
               body={"project_id": "proj-x", "mh_json": {"width": 0}},
               method="PUT", expect_error=True)
    assert bad["ok"] is False
    # 合法写入
    ok = _req(_url(server, "/api/mh/mhjson"),
              body={"project_id": "proj-x",
                    "mh_json": {"width": 1920, "height": 1080, "fps": 60, "duration": 6}},
              method="PUT")
    assert ok["ok"] is True
    got2 = _getj(_url(server, "/api/mh/project?id=proj-x"))
    assert got2["mh_json"]["fps"] == 60


# ---------------------------------------------------------------- HTTP: scene_js 校验拒绝
def test_scene_put_rejects_bad_payload(server, monkeypatch, tmp_path):
    # 准备一个已存在的项目目录
    root = tmp_path / ".tuan" / "mh" / "proj-y"
    (root / "src").mkdir(parents=True)
    (root / "mh.json").write_text("{}", encoding="utf-8")
    bad = _req(_url(server, "/api/mh/scene"),
               body={"project_id": "proj-y", "scene_js": "const x = 1;"},
               method="PUT", expect_error=True)
    assert bad["ok"] is False
    assert "prepareFrame" in bad["error"]

    # 路径穿越的 project_id → 400
    traversal = _req(_url(server, "/api/mh/scene"),
                     body={"project_id": "../escape", "scene_js": "x"},
                     method="PUT", expect_error=True)
    assert traversal["ok"] is False


# ---------------------------------------------------------------- render job 生命周期

def test_render_job_lifecycle(server, monkeypatch, tmp_path):
    # 准备项目目录 (自研后端: mh.json 需含 nodes 字段以通过 validate_project)
    proj = tmp_path / ".tuan" / "mh" / "proj-r"
    (proj / "src").mkdir(parents=True)
    (proj / "mh.json").write_text(
        json.dumps({
            "width": 1280, "height": 720, "fps": 30, "duration": 2,
            "nodes": [{"type": "bg", "start": 0.0, "end": 2.0, "color": "#10121a"}],
        }),
        encoding="utf-8")

    # 让 resolve_mh 报可用
    monkeypatch.setattr(mh_runner, "resolve_mh", lambda: {
        "ok": True, "mh_cmd": "ffmpeg", "node_dir": "",
        "mh_home": "mh_home", "reason": ""})

    # 自研路径: monkeypatch render_video 返回假结果, 避免 mock Popen
    fake_result = {"out_path": str(proj / "out.mp4"), "frames": 60,
                   "fps": 30, "elapsed": 0.1, "size_bytes": 1024}
    monkeypatch.setattr(mh_runner._renderer, "render_video",
                        lambda *args, **kwargs: fake_result)

    resp = _req(_url(server, "/api/mh/render"),
                body={"project_id": "proj-r", "out": "out.mp4"})
    assert resp["ok"] is True
    job_id = resp["job_id"]
    assert resp["out_rel"] == "proj-r/out.mp4"

    # 立即查: job 应该存在, status 是 running 或 done (race)
    job = _getj(_url(server, f"/api/mh/job?id={job_id}"))["job"]
    assert job["id"] == job_id
    assert job["kind"] == "render"
    assert job["status"] in ("running", "done")

    # 让后台线程跑完
    for _ in range(50):
        job = _getj(_url(server, f"/api/mh/job?id={job_id}"))["job"]
        if job["status"] == "done":
            break
        time.sleep(0.05)
    assert job["status"] == "done"
    assert job["returncode"] == 0

    # jobs 列表能看到这条
    jobs = _getj(_url(server, "/api/mh/jobs"))["jobs"]
    assert any(j["id"] == job_id for j in jobs)

    # 未知 job → 404
    miss = _getj(_url(server, "/api/mh/job?id=nope"), expect_error=True)
    assert miss["ok"] is False


def test_render_rejects_bad_out(server):
    bad = _req(_url(server, "/api/mh/render"),
               body={"project_id": "whatever", "out": "../evil.mp4"},
               expect_error=True)
    # project_id 无效优先 → invalid project_id
    assert bad["ok"] is False


def test_render_rejects_when_mh_missing(server, tmp_path):
    # 不 monkeypatch resolve_mh; 默认 fixture 已把它设为不可用
    proj = tmp_path / ".tuan" / "mh" / "proj-z"
    proj.mkdir(parents=True)
    resp = _req(_url(server, "/api/mh/render"),
                body={"project_id": "proj-z"}, expect_error=True)
    assert resp["ok"] is False


def test_media_serves_only_under_mh_root(server, tmp_path):
    # 建一个 mp4 文件
    proj = tmp_path / ".tuan" / "mh" / "proj-m"
    proj.mkdir(parents=True)
    mp4 = proj / "out.mp4"
    mp4.write_bytes(b"fake-mp4-bytes")

    raw = _get(_url(server, "/api/mh/media?path=proj-m/out.mp4"))
    assert raw == "fake-mp4-bytes"

    # 路径穿越 → 400
    bad = _getj(_url(server, "/api/mh/media?path=../../secret"),
                expect_error=True)
    assert bad["ok"] is False
    # 不存在的文件 → 404
    miss = _getj(_url(server, "/api/mh/media?path=proj-m/nope.mp4"),
                 expect_error=True)
    assert miss["ok"] is False


def test_invalid_project_id_returns_error(server):
    bad = _getj(_url(server, "/api/mh/project?id=../escape"),
                expect_error=True)
    assert bad["ok"] is False
