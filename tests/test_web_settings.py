# -*- coding: utf-8 -*-
"""Web 工作台「设置」面板 API 测试。

对标 TUI 的 /config /model /permissions 控制面:
- GET  /api/config          快照 (值 + 元数据 + 58 家供应商 + 当前模型)
- POST /api/config/set      单键写入 (白名单 + 类型/枚举校验 + 持久化)
- POST /api/config/model    切换供应商/模型
- POST /api/config/apikey   写入/清除某个供应商的 API Key

回归背景: 早期 WebUI 的 /mode /effort 只有 TUI 一半能力, 且没有任何
设置入口, 用户必须在命令行里手改 ~/.tuan/config.yaml 才能换模型。
"""
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from tuan_cli.config.loader import Config
from tuan_cli.web import server as ws_mod
from tuan_cli.web.server import WebServer


class _FakeKernel:
    """极简 kernel: 提供 config, 并支持 model_adapter 热切换 (provide/unprovide)。

    模型切换接口 (web/server.py::_set_model) 会 ``kernel.unprovide("model_adapter")``
    再 ``kernel.provide("model_adapter", ..., owner="web")`` 重建适配器, 因此桩对象
    必须实现这两个方法, 否则该路径会以 "适配器重建失败: ... has no attribute
    'unprovide'" 失败。签名与 core/kernel.py 保持一致。
    """

    def __init__(self):
        self._cfg: Config | None = None
        self._services: dict = {}

    def require(self, name: str):
        if name in self._services:
            return self._services[name]
        if name == "config":
            if self._cfg is None:
                self._cfg = Config()
            return self._cfg
        raise KeyError(name)

    def provide(self, service: str, impl, owner: str = "") -> None:
        self._services[service] = impl

    def unprovide(self, service: str) -> None:
        self._services.pop(service, None)


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


def _post(srv, path, body, expect_error=False):
    req = urllib.request.Request(
        _url(srv) + path, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        assert expect_error, f"unexpected HTTP {e.code}: {e.read().decode('utf-8')}"
        return json.loads(e.read().decode("utf-8"))


# ---------------------------------------------------------------- 快照


def test_config_snapshot_shape(server, tuan_home):
    j = _get(server, "/api/config")
    assert j["ok"] is True
    assert len(j["providers"]) >= 40           # 供应商目录 (当前 58 家)
    assert {"name", "base_url", "models", "key_set", "api_key_env"} <= set(j["providers"][0])
    assert {"sec", "key", "label", "type"} <= set(j["meta"][0])
    assert set(j["values"]) == {m["key"] for m in j["meta"]}
    assert j["model"]["provider"] and j["model"]["model"]
    assert j["workspace"] == server.workspace
    assert j["engine"]


def test_provider_models_are_clean_ids(server, tuan_home):
    """模型清单必须剥掉 |free/|paid 标注, 否则前端下拉值会带竖线尾巴。"""
    j = _get(server, "/api/config")
    moonshot = next(p for p in j["providers"] if p["name"] == "moonshot")
    assert "moonshot-v1-8k" in moonshot["models"]
    assert all("|" not in m for m in moonshot["models"])
    assert moonshot["tags"].get("kimi-k3") in ("free", "paid")


def test_snapshot_reports_key_state(server, tuan_home, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    j = _get(server, "/api/config")
    ds = next(p for p in j["providers"] if p["name"] == "deepseek")
    assert ds["key_set"] is True
    other = next(p for p in j["providers"] if p["name"] != "deepseek" and p["api_key_env"])
    assert other["key_set"] is False


# ---------------------------------------------------------------- set


def test_set_rejects_non_whitelisted_key(server, tuan_home):
    j = _post(server, "/api/config/set", {"key": "model.provider", "value": "evil"}, True)
    assert j["ok"] is False
    assert "不允许" in j["error"]


def test_set_enum_validated(server, tuan_home):
    assert _post(server, "/api/config/set", {"key": "mode.default", "value": "yolo"})["ok"]
    j = _post(server, "/api/config/set", {"key": "mode.default", "value": "nope"}, True)
    assert j["ok"] is False and "可选值" in j["error"]
    # 非法值不得落盘
    cfg = Config()
    assert cfg.get("mode.default") == "yolo"


def test_set_int_and_bool_and_list(server, tuan_home):
    assert _post(server, "/api/config/set",
                 {"key": "agent.max_iterations", "value": "7"})["value"] == 7
    j = _post(server, "/api/config/set", {"key": "agent.max_iterations", "value": "x"}, True)
    assert j["ok"] is False and "类型错误" in j["error"]
    assert _post(server, "/api/config/set",
                 {"key": "agent.auto_memory", "value": False})["value"] is False
    assert _post(server, "/api/config/set",
                 {"key": "permissions.network.allow_domains",
                  "value": "a.com, b.com"})["value"] == ["a.com", "b.com"]


def test_set_persists_to_user_config(server, tuan_home):
    _post(server, "/api/config/set", {"key": "context.budget_tokens", "value": 64000})
    cfg = Config()
    assert cfg.get("context.budget_tokens") == 64000
    disk = (tuan_home / "config.yaml").read_text(encoding="utf-8")
    assert "64000" in disk


@pytest.mark.parametrize("key,value", [
    ("agent.max_iterations", 0),            # 下限 1
    ("agent.max_iterations", 999),          # 上限 200
    ("context.budget_tokens", 999),         # 下限 1000
    ("model.temperature", 3.0),             # 上限 2.0
    ("model.temperature", -0.5),            # 下限 0
    ("router.stuck_threshold", 0),          # 下限 1
])
def test_set_rejects_out_of_range(server, tuan_home, key, value):
    j = _post(server, "/api/config/set", {"key": key, "value": value}, True)
    assert j["ok"] is False
    assert "过小" in j["error"] or "过大" in j["error"]
    assert Config().get(key) != value


def test_set_float(server, tuan_home):
    j = _post(server, "/api/config/set", {"key": "model.temperature", "value": "1.2"})
    assert j["ok"] and j["value"] == 1.2
    j = _post(server, "/api/config/set", {"key": "mcp.timeout", "value": 45}, True)
    assert j["ok"] and j["value"] == 45.0


def test_every_setting_key_exists_in_config(server, tuan_home):
    """_SETTINGS_META 里的键必须都是真实存在的配置项 (防止写进从不被读取的死键)。"""
    from tuan_cli.config.loader import DEFAULT_CONFIG

    def _has(dotted):
        node = DEFAULT_CONFIG
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return False
            node = node[part]
        return True

    j = _get(server, "/api/config")
    missing = [m["key"] for m in j["meta"] if not _has(m["key"])]
    assert missing == [], f"这些设置键在配置里不存在: {missing}"


def test_mode_setting_flips_live_session(server, tuan_home):
    """mode.default 的改动应实时作用到已存在的会话 agent (对标 TUI 的 /mode)。"""
    from tuan_cli.web import server as ws

    class _A:
        plan_mode = False
        yolo = False

        def __init__(self):
            self.ctx = type("C", (), {"plan_mode": False, "yolo": False})()

        def effective_tool_set(self):
            return "standard"

    agent = _A()
    with ws._SESSIONS_LOCK:
        ws._SESSIONS["s1"] = {"agent": agent}
    try:
        _post(server, "/api/config/set", {"key": "mode.default", "value": "plan"})
        assert agent.plan_mode is True and agent.yolo is False
        assert agent.ctx.plan_mode is True
        _post(server, "/api/config/set", {"key": "mode.default", "value": "yolo"})
        assert agent.plan_mode is False and agent.yolo is True
    finally:
        with ws._SESSIONS_LOCK:
            ws._SESSIONS.pop("s1", None)


def test_info_reflects_settings(server, tuan_home):
    _post(server, "/api/config/set", {"key": "agent.effort", "value": "low"})
    info = _get(server, "/api/info")
    assert info["effort"] == "low"


# ---------------------------------------------------------------- model


def test_model_switch_writes_config(server, tuan_home):
    j = _post(server, "/api/config/model", {"provider": "moonshot", "model": "moonshot-v1-8k"}, True)
    assert j["ok"] is True
    cfg = Config()
    assert cfg.get("model.provider") == "moonshot"
    assert cfg.get("model.model") == "moonshot-v1-8k"
    assert cfg.get("model.base_url")
    assert cfg.get("model.api_key_env") == "MOONSHOT_API_KEY"
    snap = _get(server, "/api/config")
    assert snap["model"]["provider"] == "moonshot"


def test_model_switch_rejects_unknown_provider(server, tuan_home):
    j = _post(server, "/api/config/model", {"provider": "nope", "model": "m"}, True)
    assert j["ok"] is False
    cfg = Config()
    assert cfg.get("model.provider") != "nope"


def test_model_switch_rejects_unknown_model(server, tuan_home):
    j = _post(server, "/api/config/model",
              {"provider": "deepseek", "model": "deepseek-typo"}, True)
    assert j["ok"] is False
    cfg = Config()
    assert cfg.get("model.model") != "deepseek-typo"


def test_model_switch_with_key_persists(server, tuan_home):
    j = _post(server, "/api/config/model",
              {"provider": "deepseek", "model": "deepseek-chat", "api_key": "sk-web-1"})
    assert j["ok"] and "sk" not in j["note"]
    import os
    assert os.environ.get("DEEPSEEK_API_KEY") == "sk-web-1"
    from tuan_cli.config.loader import read_api_key
    assert read_api_key("DEEPSEEK_API_KEY", tuan_home) == "sk-web-1"


# ---------------------------------------------------------------- apikey


def test_apikey_set_and_clear(server, tuan_home):
    j = _post(server, "/api/config/apikey", {"env": "MOONSHOT_API_KEY", "key": "sk-abc"})
    assert j["ok"] and j["set"] is True
    assert _get(server, "/api/config")["providers"]
    j = _post(server, "/api/config/apikey", {"env": "MOONSHOT_API_KEY", "key": ""})
    assert j["ok"] and j["set"] is False
    from tuan_cli.config.loader import read_api_key
    assert read_api_key("MOONSHOT_API_KEY", tuan_home) is None


def test_apikey_rejects_bad_env(server, tuan_home):
    for env in ("", "A=B", None):
        j = _post(server, "/api/config/apikey", {"env": env, "key": "x"}, True)
        assert j["ok"] is False
