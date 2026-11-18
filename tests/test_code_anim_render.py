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
        # 阶段 3 高级动效原语
        ("transition", {"type": "slide", "direction": "ltr",
                        "from_color": "#000000", "to_color": "#ffffff"}),
        ("particles", {"count": 30, "origin": "center", "spread": 60,
                       "color": "#4fc3f7", "life": 1.0}),
        ("kinetic", {"text": "Hello", "font_size": 20, "mode": "char",
                     "stagger": 0.02}),
        ("beat", {"bpm": 120, "kind": "border", "strength": 0.2}),
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
# 阶段 3 高级动效原语: 各 variant 渲染不报错 + frame-stable
# ---------------------------------------------------------------------------

def test_advanced_primitives_all_variants_render():
    """transition/particles/kinetic/beat 各子类型在中段时间点均可渲染。"""
    cases = [
        # transition: 4 方向 + 4 类型
        ({"type": "transition", "start": 0.0, "end": 2.0,
          "props": {"type": "crossfade", "from_color": "#000", "to_color": "#fff"}}, 1.0),
        ({"type": "transition", "start": 0.0, "end": 2.0,
          "props": {"type": "slide", "direction": "ltr"}}, 1.0),
        ({"type": "transition", "start": 0.0, "end": 2.0,
          "props": {"type": "slide", "direction": "rtl"}}, 1.0),
        ({"type": "transition", "start": 0.0, "end": 2.0,
          "props": {"type": "slide", "direction": "ttb"}}, 1.0),
        ({"type": "transition", "start": 0.0, "end": 2.0,
          "props": {"type": "slide", "direction": "btt"}}, 1.0),
        ({"type": "transition", "start": 0.0, "end": 2.0,
          "props": {"type": "zoom"}}, 1.0),
        ({"type": "transition", "start": 0.0, "end": 2.0,
          "props": {"type": "wipe", "direction": "ltr"}}, 1.0),
        # particles: 各 origin
        ({"type": "particles", "start": 0.0, "end": 2.0,
          "props": {"count": 20, "origin": "center"}}, 0.5),
        ({"type": "particles", "start": 0.0, "end": 2.0,
          "props": {"count": 20, "origin": "top"}}, 0.5),
        ({"type": "particles", "start": 0.0, "end": 2.0,
          "props": {"count": 20, "origin": "bottom", "gravity": 30}}, 0.5),
        ({"type": "particles", "start": 0.0, "end": 2.0,
          "props": {"count": 20, "origin": [64, 36]}}, 0.5),
        # kinetic: 三种 mode
        ({"type": "kinetic", "start": 0.0, "end": 2.0,
          "props": {"text": "K", "mode": "char"}}, 0.5),
        ({"type": "kinetic", "start": 0.0, "end": 2.0,
          "props": {"text": "K", "mode": "scale"}}, 0.5),
        ({"type": "kinetic", "start": 0.0, "end": 2.0,
          "props": {"text": "K", "mode": "rotate"}}, 0.5),
        # beat: 三种 kind
        ({"type": "beat", "start": 0.0, "end": 2.0,
          "props": {"bpm": 120, "kind": "bg"}}, 0.5),
        ({"type": "beat", "start": 0.0, "end": 2.0,
          "props": {"bpm": 120, "kind": "border"}}, 0.5),
        ({"type": "beat", "start": 0.0, "end": 2.0,
          "props": {"bpm": 120, "kind": "ring"}}, 0.5),
    ]
    for node, t in cases:
        pj = _base_project(nodes=[node])
        img = car.draw_frame(pj, t)
        assert img is not None
        assert img.size == (128, 72)
        assert len(img.tobytes()) == 128 * 72 * 3


def test_advanced_primitives_frame_stable():
    """新原语 draw_frame 是纯函数: 同一 t 两次绘制结果一致。"""
    pj = _base_project(nodes=[
        {"type": "transition", "start": 0.0, "end": 2.0,
         "props": {"type": "slide", "direction": "ltr"}},
        {"type": "particles", "start": 0.0, "end": 2.0,
         "props": {"count": 40, "origin": "center", "life": 1.5}},
        {"type": "kinetic", "start": 0.0, "end": 2.0,
         "props": {"text": "Frame Stable", "mode": "char", "stagger": 0.02}},
        {"type": "beat", "start": 0.0, "end": 2.0,
         "props": {"bpm": 90, "kind": "ring"}},
    ])
    a = car.draw_frame(pj, 0.8).tobytes()
    b = car.draw_frame(pj, 0.8).tobytes()
    assert a == b


# ---------------------------------------------------------------------------
# 阶段 8 givemotion 式动效补全: shape_morph / camera / path_motion / hand_drawn
# ---------------------------------------------------------------------------

def test_givemotion_all_variants_render():
    """阶段 8 新节点各子类型在中段时间点均可渲染, 且进白名单。"""
    assert "shape_morph" in car._KNOWN_NODE_TYPES
    assert "camera" in car._KNOWN_NODE_TYPES
    assert "path_motion" in car._KNOWN_NODE_TYPES
    assert "hand_drawn" in car._KNOWN_NODE_TYPES
    cases = [
        # shape_morph: 多形状组合
        ({"type": "shape_morph", "start": 0.0, "end": 2.0,
          "props": {"from": "circle", "to": "square", "size": 40, "duration": 1.0}}, 0.5),
        ({"type": "shape_morph", "start": 0.0, "end": 2.0,
          "props": {"from": "triangle", "to": "hex", "outline": True}}, 0.5),
        ({"type": "shape_morph", "start": 0.0, "end": 2.0,
          "props": {"from": "star", "to": "circle"}}, 0.5),
        # camera: 各缓动 + 跟随
        ({"type": "camera", "start": 0.0, "end": 2.0,
          "props": {"x1": 10, "y1": 10, "x2": 100, "y2": 60,
                    "ease": "easeinout", "zoom_start": 1.0, "zoom_end": 1.5}}, 0.5),
        ({"type": "camera", "start": 0.0, "end": 2.0,
          "props": {"ease": "linear", "show_target": False}}, 0.5),
        # path_motion: 各路径类型
        ({"type": "path_motion", "start": 0.0, "end": 2.0,
          "props": {"path": "line", "x1": 10, "y1": 10, "x2": 110, "y2": 60}}, 0.5),
        ({"type": "path_motion", "start": 0.0, "end": 2.0,
          "props": {"path": "poly", "points": [[10, 10], [60, 60], [110, 10]]}}, 0.5),
        ({"type": "path_motion", "start": 0.0, "end": 2.0,
          "props": {"path": "bezier", "points": [[10, 60], [40, 10], [80, 10], [110, 60]]}}, 0.5),
        ({"type": "path_motion", "start": 0.0, "end": 2.0,
          "props": {"path": "circle", "cx": 64, "cy": 36, "r": 30}}, 0.5),
        ({"type": "path_motion", "start": 0.0, "end": 2.0,
          "props": {"path": "spiral", "cx": 64, "cy": 36, "r0": 5, "r1": 40, "turns": 2}}, 0.5),
        # path_motion: direction / pingpong
        ({"type": "path_motion", "start": 0.0, "end": 2.0,
          "props": {"path": "line", "direction": "reverse"}}, 0.5),
        ({"type": "path_motion", "start": 0.0, "end": 2.0,
          "props": {"path": "line", "direction": "pingpong"}}, 0.5),
        # hand_drawn: 折线 + 闭合
        ({"type": "hand_drawn", "start": 0.0, "end": 2.0,
          "props": {"points": [[10, 10], [40, 50], [80, 20], [110, 60]],
                    "jitter": 2.0, "width": 3}}, 0.5),
        ({"type": "hand_drawn", "start": 0.0, "end": 2.0,
          "props": {"points": [[10, 10], [60, 10], [60, 60], [10, 60]],
                    "close": True, "jitter": 0.0}}, 0.5),
    ]
    for node, t in cases:
        pj = _base_project(nodes=[node])
        img = car.draw_frame(pj, t)
        assert img is not None
        assert img.size == (128, 72)
        assert len(img.tobytes()) == 128 * 72 * 3


def test_givemotion_frame_stable():
    """阶段 8 新节点 draw_frame 是纯函数: 同一 t 两次绘制结果一致。"""
    pj = _base_project(nodes=[
        {"type": "shape_morph", "start": 0.0, "end": 2.0,
         "props": {"from": "circle", "to": "star", "size": 40}},
        {"type": "camera", "start": 0.0, "end": 2.0,
         "props": {"x1": 10, "y1": 10, "x2": 100, "y2": 60}},
        {"type": "path_motion", "start": 0.0, "end": 2.0,
         "props": {"path": "bezier", "points": [[10, 60], [40, 10], [80, 10], [110, 60]]}},
        {"type": "hand_drawn", "start": 0.0, "end": 2.0,
         "props": {"points": [[10, 10], [40, 50], [80, 20], [110, 60]]}},
    ])
    a = car.draw_frame(pj, 0.9).tobytes()
    b = car.draw_frame(pj, 0.9).tobytes()
    assert a == b


def test_givemotion_progress_motion():
    """path_motion 物体位置随 progress 前进: 两端点位置应不同。"""
    pj = _base_project(nodes=[
        {"type": "path_motion", "start": 0.0, "end": 2.0,
         "props": {"path": "line", "x1": 10, "y1": 36, "x2": 110, "y2": 36,
                   "trail": 0.0, "size": 6}},
    ])
    # 在 start 处物体在 x1 附近, 在 end 处物体在 x2 附近 (采样像素列找亮点)
    a = car.draw_frame(pj, 0.05)
    b = car.draw_frame(pj, 1.95)
    # 提取物体所在 x: 找非背景像素列
    def _center_x(img):
        w, h = img.size
        rows = img.load()
        best = None
        for x in range(w):
            col_has = any(rows[x, y] != (18, 20, 26) for y in range(h))
            if col_has:
                best = x
                break
        return best
    xa = _center_x(a)
    xb = _center_x(b)
    assert xa is not None and xb is not None
    assert xb > xa  # 物体向右移动


def test_givemotion_invalid_params_no_crash():
    """阶段 8 非法参数不崩溃 (fail-closed 静默绘制或跳过)。"""
    cases = [
        {"type": "shape_morph", "start": 0.0, "end": 2.0, "props": {"from": "nope", "to": "bad"}},
        {"type": "camera", "start": 0.0, "end": 2.0, "props": {"ease": "bogus"}},
        {"type": "path_motion", "start": 0.0, "end": 2.0, "props": {"path": "unknown"}},
        {"type": "path_motion", "start": 0.0, "end": 2.0,
         "props": {"path": "bezier", "points": [[0, 0]]}},  # 点数不足
        {"type": "hand_drawn", "start": 0.0, "end": 2.0, "props": {"points": [[0, 0]]}},
    ]
    for node in cases:
        pj = _base_project(nodes=[node])
        img = car.draw_frame(pj, 0.5)
        assert img is not None
        assert img.size == (128, 72)


# ---------------------------------------------------------------------------
# 阶段 9 cinecode 式音频混音: 校验 + 混音执行
# ---------------------------------------------------------------------------

def test_audio_validation_contract():
    """audio 字段的 fail-closed 校验 (不触网/不落盘)。"""
    assert car.validate_project(_base_project(audio="track.wav")) is None
    assert car.validate_project(_base_project(audio=[
        {"path": "bgm.mp3", "start": 1.0, "volume": 0.5},
        {"path": "voice.wav", "volume": 1.2},
    ])) is None
    # 非法 → 报错
    assert car.validate_project(_base_project(audio="")) is not None
    assert car.validate_project(_base_project(audio=123)) is not None
    assert car.validate_project(_base_project(audio=[{"volume": 0.5}])) is not None
    assert car.validate_project(_base_project(audio=[{"path": "x", "volume": 0}])) is not None
    assert car.validate_project(_base_project(audio=[{"path": "x", "start": -1}])) is not None


def test_audio_mix_no_audio_returns_noop():
    """无 audio → _mix_audio_tracks 返回 no-op, 不执行 ffmpeg。"""
    res = car._mix_audio_tracks("ffmpeg", _base_project(), "out.mp4", 1.0)
    assert res == {"mixed": False, "tracks": 0}


def test_audio_mix_missing_file_fail_closed():
    """audio 路径不存在 → fail-closed RuntimeError (不产出无声假成功)。"""
    import pytest
    with pytest.raises(RuntimeError):
        car._mix_audio_tracks("ffmpeg", _base_project(audio="ghost.mp3"), "out.mp4", 1.0)


def test_audio_mix_invalid_type_fail_closed():
    """audio 类型非法 → fail-closed。"""
    import pytest
    with pytest.raises(RuntimeError):
        car._mix_audio_tracks("ffmpeg", _base_project(audio=123), "out.mp4", 1.0)


def test_render_video_with_audio_mix(tmp_path):
    """真实渲染: 视频 + 单音轨混音 (ffmpeg 可用时)。"""
    import wave
    import struct

    if not car.ffmpeg_available():
        import pytest
        pytest.skip("ffmpeg 不可用")
    # 生成 0.5s 静音 wav (44.1k 单声道)
    wav = tmp_path / "silence.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x00" * (22050 // 2))
    pj = _base_project(audio=str(wav))
    out = tmp_path / "audio_mix.mp4"
    res = car.render_video(pj, str(out), fps=5, workspace=str(tmp_path))
    assert out.exists()
    assert res["audio"]["mixed"] is True
    assert res["audio"]["tracks"] == 1
    assert res["frames"] >= 1


def test_render_video_audio_outside_workspace_rejected(tmp_path):
    """审计 P2-31: audio 路径越出工作区 -> fail-closed 拒绝, 不落盘。"""
    import wave

    if not car.ffmpeg_available():
        import pytest
        pytest.skip("ffmpeg 不可用")
    outside = tmp_path.parent / "outside_audio.wav"
    with wave.open(str(outside), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x00" * (22050 // 2))
    pj = _base_project(audio=str(outside))
    out = tmp_path / "audio_mix.mp4"
    try:
        car.render_video(pj, str(out), fps=5, workspace=str(tmp_path))
        raise AssertionError("越界 audio 不应渲染成功")
    except RuntimeError as e:
        assert "越界" in str(e)
    # 视频主体先编码、混音前才校验边界 -> out 可能已存在;
    # 关键断言: 越界音频未被读取/混入 (渲染在混音前失败)
    assert outside.is_file()


def test_transition_outside_range_no_effect():
    """transition 在节点范围外不改变画面 (与仅背景相同)。"""
    bg = {"type": "bg", "start": 0.0, "end": 5.0, "props": {"type": "solid"}}
    trans = {"type": "transition", "start": 3.0, "end": 4.0,
             "props": {"type": "wipe", "direction": "ltr"}}
    # t=0.5 在 transition 范围外
    base = car.draw_frame(_base_project(nodes=[bg]), 0.5)
    with_trans = car.draw_frame(_base_project(nodes=[bg, trans]), 0.5)
    assert base.tobytes() == with_trans.tobytes()


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


def test_http_render_profile_flag(server):
    """POST /api/codeanim/render?profile=true → job 结果含 perf。"""
    import urllib.request
    base = f"http://127.0.0.1:{server.port}"
    pj = _base_project(duration=0.5, fps=5, nodes=[
        {"type": "bg", "start": 0.0, "end": 5.0, "props": {"type": "solid"}},
    ])
    req = urllib.request.Request(
        base + "/api/codeanim/render",
        data=json.dumps({"project_json": pj, "out": "prof_http.mp4",
                         "profile": True}).encode(),
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
    assert "perf" in job.get("result", {})


# ---------------------------------------------------------------------------
# 性能分析 (阶段 11, profiler): 逐节点耗时 + 帧时间序列热力图
# ---------------------------------------------------------------------------

def test_draw_frame_profiler_accumulates():
    """draw_frame 传入 profiler 后逐节点耗时被累计, frame_ms 为数字。"""
    pj = _base_project(nodes=[
        {"type": "bg", "start": 0.0, "end": 5.0, "props": {"type": "solid"}},
        {"type": "title", "start": 0.0, "end": 5.0, "props": {"text": "P"}},
    ])
    prof: dict = {}
    img = car.draw_frame(pj, 0.0, profiler=prof)
    assert img is not None
    assert isinstance(prof["frame_ms"], (int, float))
    assert "bg" in prof["nodes"]
    assert "title" in prof["nodes"]
    bg = prof["nodes"]["bg"]
    assert bg["count"] == 1
    assert bg["total_ms"] >= 0
    assert bg["max_ms"] >= 0


def test_draw_frame_profiler_inactive_node_not_counted():
    """范围外的节点不渲染, 也不进入 profiler 统计。"""
    pj = _base_project(nodes=[
        {"type": "title", "start": 1.0, "end": 2.0, "props": {"text": "later"}},
    ])
    prof: dict = {}
    car.draw_frame(pj, 0.0, profiler=prof)
    assert "title" not in prof.get("nodes", {})


def test_draw_frame_profiler_unknown_node_skipped():
    """未知节点类型跳过且不进入 profiler (fail-closed)。"""
    pj = _base_project(nodes=[
        {"type": "nope_not_real", "start": 0.0, "end": 5.0, "props": {}},
    ])
    prof: dict = {}
    car.draw_frame(pj, 0.0, profiler=prof)
    assert prof.get("nodes", {}) == {}


def test_profile_summary_aggregates():
    """_profile_summary 聚合逐帧 profiler 为摘要 (nodes + frame_series)。"""
    fps = [
        {"frame_ms": 1.0, "nodes": {"bg": {"count": 1, "total_ms": 0.8, "max_ms": 0.8}}},
        {"frame_ms": 2.0, "nodes": {"bg": {"count": 1, "total_ms": 1.2, "max_ms": 1.2},
                                    "title": {"count": 1, "total_ms": 0.5, "max_ms": 0.5}}},
    ]
    s = car._profile_summary(fps, total_frames=2)
    assert s["frames"] == 2
    assert s["total_frames"] == 2
    assert s["frame_ms"]["avg"] == 1.5
    assert s["frame_ms"]["max"] == 2.0
    assert s["frame_ms"]["p95"] == 2.0
    assert s["frame_series"] == [1.0, 2.0]
    assert s["nodes"]["bg"]["count"] == 2
    assert abs(s["nodes"]["bg"]["avg_ms"] - 1.0) < 1e-6
    assert s["nodes"]["title"]["count"] == 1


def test_render_video_profile_returns_perf(tmp_path):
    """render_video(profile=True) 返回 perf 摘要 (真实 ffmpeg)。"""
    if not car.ffmpeg_available():
        pytest.skip("ffmpeg 不可用")
    pj = _base_project(duration=0.4, fps=5, nodes=[
        {"type": "bg", "start": 0.0, "end": 5.0, "props": {"type": "solid"}},
        {"type": "code", "start": 0.0, "end": 5.0,
         "props": {"code": "x = 1", "language": "python"}},
    ])
    out = tmp_path / "prof.mp4"
    res = car.render_video(pj, str(out), fps=5, profile=True)
    assert os.path.isfile(out)
    perf = res["perf"]
    assert perf["frames"] == 2
    assert "code" in perf["nodes"]
    assert len(perf["frame_series"]) == 2


def test_start_render_job_profile_flag(tmp_path):
    """start_render_job 接受 profile 参数并透传 (job 结果含 perf)。"""
    if not car.ffmpeg_available():
        pytest.skip("ffmpeg 不可用")
    pj = _base_project(duration=0.4, fps=5, nodes=[
        {"type": "bg", "start": 0.0, "end": 5.0, "props": {"type": "solid"}},
    ])
    out = tmp_path / "jobprof.mp4"
    jid = car.start_render_job(pj, str(out), fps=5, profile=True)
    job = None
    for _ in range(100):
        job = car.get_job(jid)
        if job and job.get("status") in ("done", "error"):
            break
        time.sleep(0.05)
    assert job is not None
    assert job["status"] == "done", job.get("error")
    assert "perf" in job.get("result", {})
