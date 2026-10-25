# -*- coding: utf-8 -*-
"""T-2.6/T-3.6/T-5.2/T-5.3 切片回归测试。

覆盖:
- GET  /api/settings            读取 Web UI 用户偏好
- POST /api/settings            任意键合并写入并落盘, 重启后保留
- DELETE /api/sessions          带 session 删单条; 不带参数删全部
- WebServer.check_budget_alert 上下文用量达阈值/用满时各告警一次 (档位去重)
- core.remote_control.notify    无配对设备时优雅返回 False 且不抛异常
"""
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from tuan_cli.web import server as ws_mod
from tuan_cli.web.server import WebServer


class _FakeKernel:
    """极简 kernel: 提供 config (与 test_web_settings.py 同一桩)。"""

    def __init__(self):
        self._cfg = None

    def require(self, name: str):
        if name == "config":
            if self._cfg is None:
                from tuan_cli.config.loader import Config
                self._cfg = Config()
            return self._cfg
        raise KeyError(name)

    def provide(self, service: str, impl, owner: str = "") -> None:
        pass

    def unprovide(self, service: str) -> None:
        pass


@pytest.fixture()
def server(tmp_path, tuan_home):
    ws_mod._SESSIONS.clear()
    srv = WebServer(kernel=_FakeKernel(), workspace=str(tmp_path), port=0)
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


def _url(srv) -> str:
    return f"http://127.0.0.1:{srv._httpd.server_address[1]}"


def _get(srv, path):
    with urllib.request.urlopen(_url(srv) + path, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(srv, path, body):
    req = urllib.request.Request(
        _url(srv) + path, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def _delete(srv, path):
    req = urllib.request.Request(_url(srv) + path, method="DELETE")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------------------------------------------------------------- T-2.6 /api/settings


def test_settings_get_empty_initially(server, tuan_home):
    j = _get(server, "/api/settings")
    assert j["ok"] is True
    assert j["settings"] == {}


def test_settings_post_accepts_arbitrary_keys(server, tuan_home):
    j = _post(server, "/api/settings", {
        "theme": "dark", "accentColor": "#1783FF", "fontSize": 15,
        "safetyLevel": "strict", "notifyEnabled": True,
        "doNotDisturbStart": "23:00", "doNotDisturbEnd": "08:00",
        "budgetAlertPct": 80,
    })
    assert j["ok"] is True
    # 任意键均接受并原样返回
    assert j["settings"]["theme"] == "dark"
    assert j["settings"]["budgetAlertPct"] == 80
    assert j["settings"]["doNotDisturbEnd"] == "08:00"


def test_settings_persists_and_survives_restart(server, tmp_path, tuan_home):
    _post(server, "/api/settings", {"theme": "dark", "budgetAlertPct": 80})
    # 落盘文件存在且内容正确
    disk = (tmp_path / ".tuan" / "web_settings.json").read_text(encoding="utf-8")
    assert "dark" in disk
    # 新实例同 workspace 再读 = 重启后保留
    ws_mod._SESSIONS.clear()
    srv2 = WebServer(kernel=_FakeKernel(), workspace=str(tmp_path), port=0)
    assert srv2._settings.get("theme") == "dark"
    assert srv2._settings.get("budgetAlertPct") == 80


# ---------------------------------------------------------------- T-3.6 会话增删查列


def _seed(sid: str, title: str):
    ws_mod._SESSIONS[sid] = {"id": sid, "title": title, "created": 1, "messages": []}


def test_delete_single_session(server, tuan_home):
    _seed("a1", "会话甲")
    _seed("a2", "会话乙")
    assert len(_get(server, "/api/sessions")["sessions"]) == 2
    j = _delete(server, "/api/sessions?session=a1")
    assert j["ok"] is True
    left = _get(server, "/api/sessions")["sessions"]
    assert {s["id"] for s in left} == {"a2"}


def test_delete_all_sessions(server, tuan_home):
    _seed("a1", "会话甲")
    _seed("a2", "会话乙")
    _seed("a3", "会话丙")
    j = _delete(server, "/api/sessions")  # 不带 session 参数 = 删全部
    assert j["ok"] is True and j["deleted"] == 3
    assert _get(server, "/api/sessions")["sessions"] == []


# ---------------------------------------------------------------- T-5.2 预算告警


def _stub_context(srv, used: int, window: int = 1000):
    srv.context_info = lambda: {"window": window, "sessions": [], "total_est_tokens": used}


def test_budget_alert_fires_once_at_threshold_and_once_at_full(server, tuan_home):
    srv = server
    srv._settings["budgetAlertPct"] = 80
    _stub_context(srv, 900)          # 90% ≥ 80 → 首次告警, 档位 80
    srv.check_budget_alert("s1")
    assert srv._budget_notified["s1"] == 80
    srv.check_budget_alert("s1")     # 同档位不重复告警
    assert srv._budget_notified["s1"] == 80
    _stub_context(srv, 1000)         # 100% → 升档再告警一次
    srv.check_budget_alert("s1")
    assert srv._budget_notified["s1"] == 100


def test_budget_alert_resets_when_usage_drops(server, tuan_home):
    srv = server
    srv._settings["budgetAlertPct"] = 80
    _stub_context(srv, 900)
    srv.check_budget_alert("s1")
    assert srv._budget_notified["s1"] == 80
    _stub_context(srv, 100)          # 10% < 阈值-10 → 复位
    srv.check_budget_alert("s1")
    assert srv._budget_notified["s1"] == 0
    _stub_context(srv, 850)           # 再次爬升过阈值 → 重新告警
    srv.check_budget_alert("s1")
    assert srv._budget_notified["s1"] == 80


# ---------------------------------------------------------------- T-5.3 推送通道


def test_notify_graceful_without_paired_device():
    """无配对远程设备时 notify 落日志并返回 False, 绝不抛异常。"""
    from tuan_cli.core.remote_control import notify
    assert notify("测试标题", "测试正文", kind="info") is False
