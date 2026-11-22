"""tuan-reach (多平台联网读取能力层) 回归测试。

不触网: 用注入的假 backend 验证 路由 / 有序回退 / 留痕 / doctor 报告;
频道匹配规则与真实后端函数只做纯逻辑校验 (URL 识别、参数缺失 fail-closed)。
"""

import pytest

from tuan_cli.reach import doctor as reach_doctor
from tuan_cli.reach.base import Backend, Channel, ReachResult
from tuan_cli.reach.channels import _BILI_RE, _GH_REPO_RE, _YT_RE, build_channels
from tuan_cli.reach.registry import fetch, list_channels, route


# ------------------------------------------------------------------ 频道路由

def test_route_matches_platform_channels():
    assert route("https://github.com/owner/repo").name == "github"
    assert route("https://www.youtube.com/watch?v=abc123").name == "youtube"
    assert route("https://youtu.be/abc123").name == "youtube"
    assert route("https://www.bilibili.com/video/BV1xx411c7mD").name == "bilibili"
    assert route("https://example.com/feed.xml").name == "rss"
    assert route("https://example.com/blog/rss").name == "rss"


def test_route_falls_back_to_web():
    assert route("https://example.com/page").name == "web"
    assert route("随便什么文本").name == "web"


def test_list_channels_shape():
    chans = list_channels()
    names = [c["name"] for c in chans]
    assert names[-1] == "web", "web 必须是兜底频道"
    for c in chans:
        assert c["backends"], f"频道 {c['name']} 必须至少有一个后端"


# ------------------------------------------------------------------ 回退链

def _mk_channel(name, backends, probe=""):
    return Channel(name=name, description=name, match=lambda t: True,
                   backends=backends, probe_target=probe)


def test_fetch_uses_first_ok_backend(monkeypatch):
    calls = []

    def b1(target):
        calls.append("b1")
        return False, "", {"reason": "主用挂了"}

    def b2(target):
        calls.append("b2")
        return True, "备用成功", {}

    fake = [_mk_channel("web", [Backend("b1", b1), Backend("b2", b2)])]
    monkeypatch.setattr("tuan_cli.reach.registry._CHANNELS", fake)
    res = fetch("https://example.com")
    assert res.ok and res.backend == "b2" and "备用成功" in res.text
    assert calls == ["b1", "b2"], "必须按序回退"
    assert res.attempts[0]["ok"] is False and res.attempts[1]["ok"] is True


def test_fetch_all_backends_fail_records_attempts(monkeypatch):
    def bad(target):
        return False, "", {"reason": "不可达"}

    fake = [_mk_channel("web", [Backend("b1", bad), Backend("b2", bad)])]
    monkeypatch.setattr("tuan_cli.reach.registry._CHANNELS", fake)
    res = fetch("https://example.com")
    assert not res.ok
    assert len(res.attempts) == 2
    assert all(a["ok"] is False for a in res.attempts)
    assert "所有后端均失败" in res.error


def test_fetch_backend_exception_is_contained(monkeypatch):
    def boom(target):
        raise RuntimeError("网络炸了")

    def good(target):
        return True, "ok", {}

    fake = [_mk_channel("web", [Backend("boom", boom), Backend("good", good)])]
    monkeypatch.setattr("tuan_cli.reach.registry._CHANNELS", fake)
    res = fetch("https://example.com")
    assert res.ok and res.backend == "good"
    assert "RuntimeError" in res.attempts[0]["error"]


def test_fetch_empty_target_and_unknown_channel():
    assert not fetch("").ok
    res = fetch("https://example.com", channel="不存在的频道")
    assert not res.ok and "未知频道" in res.error


def test_fetch_explicit_channel_forces_route(monkeypatch):
    seen = {}

    def spy(target):
        seen["target"] = target
        return True, "内容", {}

    fake = [
        _mk_channel("github", [Backend("spy", spy)]),
        _mk_channel("web", [Backend("never", lambda t: (True, "不该走这", {}))]),
    ]
    monkeypatch.setattr("tuan_cli.reach.registry._CHANNELS", fake)
    res = fetch("https://example.com/x", channel="github")
    assert res.ok and res.channel == "github" and seen["target"] == "https://example.com/x"


# ------------------------------------------------------------------ 真实频道纯逻辑

def test_regex_extract_ids():
    assert _GH_REPO_RE.search("https://github.com/anthropics/claude-code").groups() == (
        "anthropics", "claude-code")
    assert _YT_RE.search("https://youtu.be/dQw4w9WgXcQ").group(1) == "dQw4w9WgXcQ"
    assert _BILI_RE.search("https://www.bilibili.com/video/BV1GJ411x7h7").group(1) == "BV1GJ411x7h7"


def test_real_github_backend_requires_repo_url():
    from tuan_cli.reach.channels import _gh_api
    ok, _text, meta = _gh_api("https://github.com/不合法")
    assert not ok and "owner/repo" in meta.get("reason", "")


# ------------------------------------------------------------------ doctor

def test_doctor_with_fake_prober():
    from tuan_cli.reach.doctor import doctor as doctor_fn
    from tuan_cli.reach.doctor import render as doctor_render

    def fake_prober(ch):
        if ch.name == "github":
            return {"channel": ch.name, "status": "ok", "backend": "api", "ms": 12, "backends": []}
        if ch.name == "rss":
            return {"channel": ch.name, "status": "skip", "note": "无轻量探测目标", "backends": []}
        return {"channel": ch.name, "status": "fail", "backends": [
            {"backend": "direct", "ok": False, "ms": 5, "error": "超时"}]}

    report = doctor_fn(prober=fake_prober)
    assert report["ok"] == 1 and report["fail"] >= 1 and report["skip"] >= 1
    text = doctor_render(report)
    assert "github" in text and "SKIP" in text and "FAIL" in text and "超时" in text


def test_doctor_real_channels_structure():
    report = reach_doctor(lambda ch: {"channel": ch.name, "status": "skip",
                                      "note": "测试禁网", "backends": []})
    assert report["total"] == len(build_channels())


# ------------------------------------------------------------------ 结果对象

def test_reach_result_summary_failure_lists_attempts():
    r = ReachResult(ok=False, text="", channel="youtube", attempts=[
        {"channel": "youtube", "backend": "yt-dlp", "ok": False, "error": "未安装"},
        {"channel": "youtube", "backend": "oembed", "ok": False, "error": "HTTP 403"},
    ], error="所有后端均失败")
    s = r.summary()
    assert "yt-dlp: 未安装" in s and "oembed: HTTP 403" in s


# ------------------------------------------------------------------ 工具层

def test_reach_tool_handlers_smoke():
    from tuan_cli.tools.reach_tool import reach_channels

    class _Ctx:
        workspace = "."

    out = reach_channels(_Ctx())
    assert "github" in out and "bilibili" in out
