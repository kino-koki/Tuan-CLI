"""cmd_resilience tests -- resilience observability CLI."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from tuan_cli.cli import cmd_resilience as P


class FakeConfig:
    def __init__(self, data: dict | None = None):
        self._data = data or {}

    def get(self, key, default=None):
        return self._data.get(key, default)


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr("tuan_cli.config.Config", lambda *a, **kw: FakeConfig())
    monkeypatch.setattr(P, "Config", FakeConfig)


def _args(**kw):
    base = dict(resilience_cmd=None, json=False, limit=20, reset=False,
                error=None, type=None)
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------- config helpers

class TestConfigHelpers:
    def test_cfg_retry_defaults(self):
        # 空配置时用 fallback 默认值
        c = P._cfg_retry(FakeConfig())
        assert c["max_retries"] == 3
        assert c["backoff"] == 2.0
        assert c["jitter"] == 0.3
        assert c["retry_on"] == []

    def test_cfg_retry_zero_values(self):
        cfg = FakeConfig({"agent.max_retries": 0, "agent.retry_backoff": 0.0,
                          "agent.retry_jitter": 0.0})
        c = P._cfg_retry(cfg)
        assert c["max_retries"] == 0

    def test_cfg_retry_values(self):
        cfg = FakeConfig({"agent.max_retries": 5, "agent.retry_backoff": 3.0,
                          "agent.retry_jitter": 0.5, "agent.retry_on": [429, 500]})
        c = P._cfg_retry(cfg)
        assert c["max_retries"] == 5
        assert c["backoff"] == 3.0
        assert c["retry_on"] == [429, 500]

    def test_cfg_ratelimit_dict(self):
        cfg = FakeConfig({"model.rate_limit": {"enabled": True, "max_rpm": 60, "max_concurrent": 2}})
        c = P._cfg_ratelimit(cfg)
        assert c["enabled"] is True
        assert c["max_rpm"] == 60

    def test_cfg_ratelimit_non_dict(self):
        c = P._cfg_ratelimit(FakeConfig({"model.rate_limit": "bad"}))
        assert c["enabled"] is False

    def test_cfg_breaker(self):
        cfg = FakeConfig({"circuit_breaker": {"enabled": True, "failure_threshold": 3}})
        c = P._cfg_breaker(cfg)
        assert c["enabled"] is True
        assert c["failure_threshold"] == 3

    def test_cfg_failover(self):
        cfg = FakeConfig({"model.failover": {"enabled": True},
                          "model.fallbacks": ["gpt-4", "claude"]})
        c = P._cfg_failover(cfg)
        assert c["fallbacks"] == ["gpt-4", "claude"]


# ---------------------------------------------------------------- helpers

class TestHelpers:
    def test_fmt_ts(self):
        out = P._fmt_ts(1700000000.0)
        assert isinstance(out, str) and len(out) >= 16


# ---------------------------------------------------------------- dispatch

class TestDispatch:
    def test_unknown_sub(self, capsys):
        rc = P.cmd_resilience(_args(resilience_cmd="nope"))
        assert rc == 1
        assert "未知子命令" in capsys.readouterr().out

    def test_default_status(self, capsys, monkeypatch):
        monkeypatch.setattr(P, "_runtime_status",
                            lambda: {"circuit_breaker": {}, "rate_limiter": {},
                                     "retry": {}, "failover": {}})
        rc = P.cmd_resilience(_args())
        assert rc == 0
        assert "韧性状态" in capsys.readouterr().out


# ---------------------------------------------------------------- config

class TestConfigCmd:
    def test_config_text(self, capsys):
        rc = P.cmd_resilience(_args(resilience_cmd="config"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "韧性配置" in out
        assert "重试" in out

    def test_config_json(self, capsys):
        rc = P.cmd_resilience(_args(resilience_cmd="config", json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert "retry" in d
        assert "circuit_breaker" in d
        assert "failover" in d


# ---------------------------------------------------------------- breaker

class TestBreaker:
    def test_breaker_text(self, capsys, monkeypatch):
        class FakeBreaker:
            failure_threshold = 5
            success_threshold = 1
            cooldown = 30.0
            def stats(self):
                return {"state": "closed", "failures": 0, "successes": 0, "opened_at": 0}
            def reset(self):
                pass
        monkeypatch.setattr("tuan_cli.core.retry.CircuitBreaker",
                            SimpleNamespace(from_config=lambda c: FakeBreaker()))
        rc = P.cmd_resilience(_args(resilience_cmd="breaker"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "熔断器" in out
        assert "CLOSED" in out

    def test_breaker_json(self, capsys, monkeypatch):
        class FakeBreaker:
            failure_threshold = 5
            success_threshold = 1
            cooldown = 30.0
            def stats(self):
                return {"state": "closed", "failures": 2, "successes": 0, "opened_at": 0}
            def reset(self):
                pass
        monkeypatch.setattr("tuan_cli.core.retry.CircuitBreaker",
                            SimpleNamespace(from_config=lambda c: FakeBreaker()))
        rc = P.cmd_resilience(_args(resilience_cmd="breaker", json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["stats"]["state"] == "closed"
        assert d["threshold"]["failure"] == 5


# ---------------------------------------------------------------- classify

class TestClassify:
    def test_classify_text(self, capsys):
        rc = P.cmd_resilience(_args(resilience_cmd="classify",
                                     error="connection timeout", type="timeout"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "错误分类" in out

    def test_classify_json(self, capsys):
        rc = P.cmd_resilience(_args(resilience_cmd="classify",
                                     error="bad config", type="config", json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert "kind" in d
        assert "fatal" in d
        assert "verdict" in d

    def test_classify_empty_error(self, capsys):
        rc = P.cmd_resilience(_args(resilience_cmd="classify", json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["error"] == ""
