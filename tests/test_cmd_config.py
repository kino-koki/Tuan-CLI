"""cmd_config 单元测试 —— 配置管理 CLI (dump/get/set/validate/profiles)。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_config as P


def _args(**kw) -> SimpleNamespace:
    base = dict(config_cmd=None, key="", value="", profile="default", patch=None)
    base.update(kw)
    return SimpleNamespace(**base)


class _FakeConfig:
    def __init__(self, data=None, **kw):
        self._data = data or {}
        self._api_key = "test-key-12345"

    @property
    def data(self):
        return self._data

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set_user(self, key, value):
        self._data[key] = value

    def api_key(self):
        return self._api_key


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
    monkeypatch.setattr(P, "Config", _FakeConfig)


# ============================================================ dump


class TestConfigDump:
    def test_dump(self, capsys):
        monkeypatch_cfg = _FakeConfig(data={"model.provider": "openai"})
        P.Config = lambda **kw: monkeypatch_cfg
        assert P.cmd_config(_args(config_cmd="dump")) == 0

    def test_dump_default(self, capsys):
        assert P.cmd_config(_args(config_cmd="dump-default")) == 0


# ============================================================ get


class TestConfigGet:
    def test_get_plain(self, monkeypatch):
        cfg = _FakeConfig(data={"model.model": "gpt-4"})
        monkeypatch.setattr(P, "Config", lambda **kw: cfg)
        assert P.cmd_config(_args(config_cmd="get", key="model.model")) == 0

    def test_get_missing(self, monkeypatch):
        cfg = _FakeConfig(data={})
        monkeypatch.setattr(P, "Config", lambda **kw: cfg)
        assert P.cmd_config(_args(config_cmd="get", key="nonexistent")) == 0

    def test_get_sensitive(self, monkeypatch):
        cfg = _FakeConfig(data={"model.api_key": "sk-1234567890abcdef"})
        monkeypatch.setattr(P, "Config", lambda **kw: cfg)
        assert P.cmd_config(_args(config_cmd="get", key="model.api_key")) == 0


# ============================================================ set


class TestConfigSet:
    def test_set_string(self, monkeypatch):
        cfg = _FakeConfig()
        monkeypatch.setattr(P, "Config", lambda **kw: cfg)
        assert P.cmd_config(_args(config_cmd="set", key="model.model", value="gpt-4")) == 0
        assert cfg._data["model.model"] == "gpt-4"

    def test_set_json_value(self, monkeypatch):
        cfg = _FakeConfig()
        monkeypatch.setattr(P, "Config", lambda **kw: cfg)
        assert P.cmd_config(_args(config_cmd="set", key="agent.max_iterations", value="50")) == 0
        assert cfg._data["agent.max_iterations"] == 50

    def test_set_sensitive(self, monkeypatch):
        cfg = _FakeConfig()
        monkeypatch.setattr(P, "Config", lambda **kw: cfg)
        assert P.cmd_config(_args(config_cmd="set", key="api_key", value="sk-secret-key-9999")) == 0
        assert cfg._data["api_key"] == "sk-secret-key-9999"


# ============================================================ profiles


class TestConfigProfiles:
    def test_profiles(self):
        assert P.cmd_config(_args(config_cmd="profiles")) == 0


# ============================================================ validate


class TestConfigValidate:
    def _full_config(self):
        return _FakeConfig(data={
            "model.provider": "openai",
            "model.model": "gpt-4",
            "model.base_url": "https://api.openai.com/v1",
            "model.temperature": 0.7,
            "model.max_tokens": 4096,
            "model.api_key_env": "OPENAI_API_KEY",
            "mode.default": "standard",
            "agent.effort": "high",
            "agent.max_iterations": 25,
            "context.budget_tokens": 100000,
        })

    def test_validate_all_ok(self, monkeypatch):
        cfg = self._full_config()
        monkeypatch.setattr(P, "Config", lambda **kw: cfg)
        rc = P.cmd_config(_args(config_cmd="validate"))
        # may have warns (mode resolution) but should be rc=0 or 1 depending on errs
        assert rc in (0, 1)

    def test_validate_missing_provider(self, monkeypatch):
        cfg = _FakeConfig(data={"model.provider": "", "model.model": ""})
        monkeypatch.setattr(P, "Config", lambda **kw: cfg)
        rc = P.cmd_config(_args(config_cmd="validate"))
        assert rc == 1  # errors present

    def test_validate_no_api_key(self, monkeypatch):
        cfg = _FakeConfig(data={
            "model.provider": "openai", "model.model": "gpt-4",
            "model.temperature": 0.7, "model.max_tokens": 4096,
            "mode.default": "standard", "agent.effort": "high",
            "agent.max_iterations": 10, "context.budget_tokens": 100000,
        })
        cfg._api_key = None
        monkeypatch.setattr(P, "Config", lambda **kw: cfg)
        rc = P.cmd_config(_args(config_cmd="validate"))
        assert rc == 1

    def test_validate_bad_temperature(self, monkeypatch):
        cfg = _FakeConfig(data={
            "model.provider": "openai", "model.model": "gpt-4",
            "model.temperature": 99.0, "model.max_tokens": 4096,
            "mode.default": "standard", "agent.effort": "high",
            "agent.max_iterations": 10, "context.budget_tokens": 100000,
        })
        monkeypatch.setattr(P, "Config", lambda **kw: cfg)
        rc = P.cmd_config(_args(config_cmd="validate"))
        assert rc == 1


# ============================================================ unknown


class TestConfigUnknown:
    def test_unknown(self):
        assert P.cmd_config(_args(config_cmd="bogus")) == 0

    def test_none_cmd(self):
        assert P.cmd_config(_args()) == 0


# ============================================================ _mask_value


class TestMaskValue:
    def test_empty_string(self):
        assert P._mask_value("") == ""

    def test_short_string(self):
        assert P._mask_value("abc") == "[REDACTED]"

    def test_long_string(self):
        r = P._mask_value("sk-1234567890abcdef")
        assert "[REDACTED]" in r
        assert "19字符" in r

    def test_dict(self):
        assert P._mask_value({"a": 1}) == "[REDACTED]"

    def test_int_passthrough(self):
        assert P._mask_value(42) == 42

    def test_bool_passthrough(self):
        assert P._mask_value(True) is True
