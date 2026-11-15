"""cmd_model 单元测试 —— 模型配置/热切换 CLI 纯函数与子命令。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_model as P


def _args(**kw) -> SimpleNamespace:
    base = dict(model_cmd=None, provider=None, model=None, base_url=None,
                api_key_env=None, provider_name="", profile="default",
                patch=None, check=False, background=False)
    base.update(kw)
    return SimpleNamespace(**base)


class _FakeConfig:
    def __init__(self, data=None, **kw):
        self._data = data or {}
        self.home = kw.get("home")

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set_user(self, key, value):
        self._data[key] = value

    def api_key(self):
        return self._data.get("api_key", "")


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
    monkeypatch.setattr(P, "Config", _FakeConfig)
    monkeypatch.setattr("tuan_cli.models.local_catalog.load_catalog", lambda home: None)
    # stub provider catalog
    import tuan_cli.models.provider_catalog as pc
    monkeypatch.setattr(pc, "PROVIDER_BY_NAME", {
        "openai": SimpleNamespace(
            name="openai", desc="OpenAI", model="gpt-4",
            base_url="https://api.openai.com/v1", api_key_env="OPENAI_API_KEY",
            recommended_models=["gpt-4|paid", "gpt-3.5-turbo|paid"], category="云端"),
        "deepseek": SimpleNamespace(
            name="deepseek", desc="DeepSeek", model="deepseek-chat",
            base_url="https://api.deepseek.com", api_key_env="DEEPSEEK_API_KEY",
            recommended_models=["deepseek-chat|paid"], category="云端"),
    })
    monkeypatch.setattr(pc, "PROVIDER_CATEGORIES", {"云端": [
        pc.PROVIDER_BY_NAME["openai"], pc.PROVIDER_BY_NAME["deepseek"]]})
    monkeypatch.setattr(pc, "ALL_PROVIDERS", list(pc.PROVIDER_BY_NAME.values()))


# ============================================================ _strip_model_label


class TestStripModelLabel:
    def test_with_label(self):
        assert P._strip_model_label("gpt-4|paid") == "gpt-4"

    def test_no_label(self):
        assert P._strip_model_label("gpt-4") == "gpt-4"

    def test_free(self):
        assert P._strip_model_label("llama3|free") == "llama3"


# ============================================================ _ellipsize


class TestEllipsize:
    def test_short(self):
        assert P._ellipsize("hello", 40) == "hello"

    def test_long_english(self):
        r = P._ellipsize("a" * 100, 40)
        assert len(r) <= 41
        assert r.endswith("…")

    def test_long_chinese(self):
        r = P._ellipsize("中文" * 50, 40)
        assert r.endswith("…")

    def test_break_at_space(self):
        r = P._ellipsize("hello world " + "x" * 50, 20)
        assert "…" in r


# ============================================================ current


class TestModelCurrent:
    def test_current(self, monkeypatch):
        cfg = _FakeConfig(data={
            "model.provider": "openai", "model.model": "gpt-4",
            "model.base_url": "https://api.openai.com/v1",
            "model.api_key_env": "OPENAI_API_KEY", "api_key": "sk-1234567890",
        })
        monkeypatch.setattr(P, "Config", lambda **kw: cfg)
        assert P.cmd_model(_args(model_cmd="current")) == 0

    def test_current_no_key(self, monkeypatch):
        cfg = _FakeConfig(data={"model.provider": "openai", "model.model": "gpt-4"})
        monkeypatch.setattr(P, "Config", lambda **kw: cfg)
        assert P.cmd_model(_args(model_cmd="current")) == 0


# ============================================================ list / info


class TestModelList:
    def test_list_known(self):
        assert P.cmd_model(_args(model_cmd="list", provider_name="openai")) == 0

    def test_list_unknown(self):
        assert P.cmd_model(_args(model_cmd="list", provider_name="bogus")) == 0


class TestModelInfo:
    def test_info_known(self):
        assert P.cmd_model(_args(model_cmd="info", provider_name="openai")) == 0

    def test_info_unknown(self):
        assert P.cmd_model(_args(model_cmd="info", provider_name="bogus")) == 0


# ============================================================ list-providers


class TestModelListProviders:
    def test_list_providers(self):
        assert P.cmd_model(_args(model_cmd="list-providers")) == 0


# ============================================================ set


class TestModelSet:
    def test_set_provider_model(self, monkeypatch):
        cfg = _FakeConfig()
        monkeypatch.setattr(P, "Config", lambda **kw: cfg)
        assert P.cmd_model(_args(model_cmd="set", provider="openai",
                                model="gpt-4")) == 0
        assert cfg._data["model.provider"] == "openai"
        assert cfg._data["model.model"] == "gpt-4"

    def test_set_with_base_url(self, monkeypatch):
        cfg = _FakeConfig()
        monkeypatch.setattr(P, "Config", lambda **kw: cfg)
        assert P.cmd_model(_args(model_cmd="set", provider="openai",
                                model="gpt-4",
                                base_url="https://custom.api.com/v1")) == 0
        assert cfg._data["model.base_url"] == "https://custom.api.com/v1"

    def test_set_uses_preset_base_url(self, monkeypatch):
        cfg = _FakeConfig()
        monkeypatch.setattr(P, "Config", lambda **kw: cfg)
        assert P.cmd_model(_args(model_cmd="set", provider="openai",
                                model="gpt-4")) == 0
        assert cfg._data.get("model.base_url") == "https://api.openai.com/v1"

    def test_set_uses_preset_api_key_env(self, monkeypatch):
        cfg = _FakeConfig()
        monkeypatch.setattr(P, "Config", lambda **kw: cfg)
        assert P.cmd_model(_args(model_cmd="set", provider="deepseek",
                                model="deepseek-chat")) == 0
        assert cfg._data.get("model.api_key_env") == "DEEPSEEK_API_KEY"

    def test_set_explicit_api_key_env(self, monkeypatch):
        cfg = _FakeConfig()
        monkeypatch.setattr(P, "Config", lambda **kw: cfg)
        assert P.cmd_model(_args(model_cmd="set", provider="openai",
                                model="gpt-4", api_key_env="CUSTOM_KEY")) == 0
        assert cfg._data["model.api_key_env"] == "CUSTOM_KEY"


# ============================================================ test


class TestModelTest:
    def test_no_api_key(self, monkeypatch):
        cfg = _FakeConfig(data={"model.provider": "openai", "model.model": "gpt-4"})
        monkeypatch.setattr(P, "Config", lambda **kw: cfg)
        assert P.cmd_model(_args(model_cmd="test")) == 1

    def test_with_overrides(self, monkeypatch):
        cfg = _FakeConfig(data={"api_key": "sk-test-key"})
        monkeypatch.setattr(P, "Config", lambda **kw: cfg)
        monkeypatch.setattr("tuan_cli.models.create_adapter",
                            lambda cfg: (_ for _ in ()).throw(RuntimeError("no net")))
        assert P.cmd_model(_args(model_cmd="test", provider="openai",
                                 model="gpt-4")) == 1


# ============================================================ _ConfigOverride


class TestConfigOverride:
    def test_override_get(self):
        base = _FakeConfig(data={"model.provider": "openai"})
        ov = P._ConfigOverride(base, {"model.provider": "deepseek"})
        assert ov.get("model.provider") == "deepseek"

    def test_override_fallback(self):
        base = _FakeConfig(data={"model.model": "gpt-4"})
        ov = P._ConfigOverride(base, {"model.provider": "deepseek"})
        assert ov.get("model.model") == "gpt-4"

    def test_override_api_key_env(self):
        import os
        base = _FakeConfig(data={})
        ov = P._ConfigOverride(base, {"model.api_key_env": "TEST_ENV_XYZ"})
        os.environ["TEST_ENV_XYZ"] = "test-key-value"
        try:
            assert ov.api_key() == "test-key-value"
        finally:
            os.environ.pop("TEST_ENV_XYZ", None)

    def test_override_api_key_fallback(self):
        base = _FakeConfig(data={"api_key": "fallback-key"})
        ov = P._ConfigOverride(base, {"model.provider": "x"})
        assert ov.api_key() == "fallback-key"


# ============================================================ _show_provider_models


class TestShowProviderModels:
    def test_known(self):
        assert P._show_provider_models("openai") is None

    def test_unknown(self):
        assert P._show_provider_models("bogus") is None
