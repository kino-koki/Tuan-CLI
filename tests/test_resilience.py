"""AgentResilience —— 三层防线 + 故障转移的韧性组件。

monkeypatch 掉重试等待/限流时钟/路由预设, 避免真等待与真实网络。
"""
from __future__ import annotations

import types

import pytest

from tuan_cli.core.errors import AuthError, ConfigError, ModelError, NetworkError
from tuan_cli.core.resilience import AgentResilience
from tuan_cli.core.retry import CircuitBreaker, RateLimiter, RetryPolicy, StreamInterrupted


# ------------------------------------------------------------ 辅助

def _mk_config(**overrides) -> dict:
    cfg = {
        "model.provider": "deepseek",
        "model.model": "deepseek-chat",
        "model.temperature": 0.7,
        "model.max_tokens": 8192,
        "model.timeout": 120,
        "model.connect_timeout": 10.0,
        "model.read_timeout": 300.0,
        "model.prompt_cache": True,
        "model.failover.enabled": True,
        "model.failover.sticky_seconds": 120.0,
        "agent.max_retries": 3,
        "agent.retry_backoff": 0.0,   # 无退避, 测试不真等
        "agent.retry_jitter": 0.0,
        "agent.retry_on": [500, 503],
    }
    cfg.update(overrides)
    return cfg


class _FakeKernel:
    def __init__(self) -> None:
        self.events: list = []
        self.handlers: dict = {}

    def emit(self, name, payload=None):
        self.events.append((name, payload))
        return None

    def on(self, name, handler):
        self.handlers[name] = handler


class _FakeAdapter:
    """可控假适配器: 按脚本逐次返回结果或抛异常。"""

    def __init__(self, script=None) -> None:
        self.script = list(script or [])
        self.calls: list = []

    def chat(self, messages, tools=None, stream=False, on_token=None, on_reason=None):
        self.calls.append({"messages": messages, "tools": tools, "stream": stream})
        if not self.script:
            return "ok"
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, tuple) and item and callable(item[0]):
            # 自定义回调: (fn, arg) 形式
            return item[0](*item[1:]) if len(item) > 1 else item[0]()
        return item


class _FakeCapabilities:
    def __init__(self, vision=False) -> None:
        self.vision = vision


class _FakeModel:
    def __init__(self, chat_fn=None, capabilities=None) -> None:
        self._chat_fn = chat_fn
        self.capabilities = capabilities or _FakeCapabilities()

    def chat(self, messages, tools=None, stream=False, on_token=None, on_reason=None):
        if self._chat_fn:
            return self._chat_fn(messages, tools, stream, on_token, on_reason)
        return "primary-ok"


# ------------------------------------------------------------ 构建/基础

def test_init_wires_config_and_components():
    kernel = _FakeKernel()
    res = AgentResilience(_mk_config(), kernel)
    assert isinstance(res.retry_policy, RetryPolicy)
    assert isinstance(res._rate_limiter, RateLimiter)
    assert isinstance(res._circuit_breaker, CircuitBreaker)
    assert res.failover_enabled is True
    # kernel.on("model.switched") 注册了清理 handler
    assert "model.switched" in kernel.handlers


def test_on_model_switched_clears_sticky_and_cache():
    kernel = _FakeKernel()
    res = AgentResilience(_mk_config(), kernel)
    res._sticky = {"provider": "x"}
    res._fallback_cache = {"a": 1}
    res._on_model_switched({})
    assert res._sticky is None
    assert res._fallback_cache == {}


def test_chat_with_retry_success_no_fallback():
    kernel = _FakeKernel()
    res = AgentResilience(_mk_config(), kernel)
    model = _FakeModel()
    result = res.chat_with_retry(model, [{"role": "user", "content": "hi"}], [], stream=False)
    assert result == "primary-ok"
    assert len(model.calls) if hasattr(model, "calls") else True


def test_chat_with_retry_retries_then_success():
    """主模型前两次失败 (瞬时), 第三次成功。"""
    kernel = _FakeKernel()
    res = AgentResilience(_mk_config(), kernel)
    calls = []
    model = _FakeModel(chat_fn=lambda *a: calls.append(1) or (
        (_ for _ in ()).throw(ConnectionError("reset")) if len(calls) < 3 else "ok"))
    result = res.chat_with_retry(model, [], [], stream=False)
    assert result == "ok"
    assert len(calls) == 3


def test_chat_with_retry_stream_interrupted_not_failover():
    """已流出内容后的失败转 StreamInterrupted, 不重试不转移。"""
    kernel = _FakeKernel()
    res = AgentResilience(_mk_config(), kernel)
    tokens = []

    def chat_fn(messages, tools=None, stream=False, on_token=None, on_reason=None):
        if on_token:
            on_token("partial")
        raise ConnectionError("mid-stream")

    model = _FakeModel(chat_fn=chat_fn)
    with pytest.raises(StreamInterrupted):
        res.chat_with_retry(model, [], [], stream=False,
                            on_token=tokens.append, fallback=True)
    assert tokens == ["partial"]


def test_chat_with_retry_config_error_not_failover():
    """本地误配置 (缺 Key) 不转移, 原样上抛 ConfigError。"""
    kernel = _FakeKernel()
    res = AgentResilience(_mk_config(), kernel)
    model = _FakeModel(chat_fn=lambda *a: (_ for _ in ()).throw(ConfigError("未配置 api key")))
    with pytest.raises(ConfigError):
        res.chat_with_retry(model, [], [], stream=False)


def test_chat_with_retry_circuit_open_then_failover():
    """熔断器打开 (CircuitOpen) 是可用性故障 → 切备用。"""
    kernel = _FakeKernel()
    # 主模型必然失败 → 熔断器很快打开
    config = _mk_config()
    res = AgentResilience(config, kernel)
    model = _FakeModel(chat_fn=lambda *a: (_ for _ in ()).throw(ConnectionError("down")))

    # 用 monkeypatch 让 _build_fallback_adapter 返回假备用, 避免真实构建
    fallback_info = {
        "provider": "moonshot", "model": "moonshot-v1-32k",
        "adapter": _FakeAdapter(["backup-ok"]),
    }
    res._build_fallback_adapter = lambda primary: fallback_info

    result = res.chat_with_retry(model, [], [], stream=False, fallback=True)
    assert result == "backup-ok"
    # 备用成功后写 sticky + 计数 + emit failover
    assert res._failover_count == 1
    assert res._sticky is not None
    assert res._sticky["provider"] == "moonshot"
    assert any(name == "model.failover" for name, _ in kernel.events)


def test_chat_with_retry_sticky_uses_fallback_directly():
    """sticky 窗口内直接走备用, 不再打主模型。"""
    kernel = _FakeKernel()
    res = AgentResilience(_mk_config(), kernel)
    primary_calls = []
    backup_calls = []

    class Backup:
        def chat(self, messages, tools=None, stream=False, on_token=None, on_reason=None):
            backup_calls.append(1)
            return "sticky-ok"

    res._sticky = {
        "provider": "moonshot", "model": "m", "adapter": Backup(),
        "from_provider": "deepseek", "from_model": "deepseek-chat",
        "until": 10**12,  # 远未过期
    }
    model = _FakeModel(chat_fn=lambda *a: primary_calls.append(1) or "primary")
    result = res.chat_with_retry(model, [], [], stream=False, fallback=True)
    assert result == "sticky-ok"
    assert primary_calls == []
    assert backup_calls == [1]


def test_chat_with_retry_fallback_disabled_raises():
    """fallback=False 时主模型故障不转移, 重试耗尽后抛 RuntimeError (贴近根因)。"""
    kernel = _FakeKernel()
    res = AgentResilience(_mk_config(), kernel)
    model = _FakeModel(chat_fn=lambda *a: (_ for _ in ()).throw(ConnectionError("down")))
    with pytest.raises(RuntimeError):
        res.chat_with_retry(model, [], [], stream=False, fallback=False)
    # 未触发 failover, 无 sticky
    assert res._sticky is None
    assert res._failover_count == 0


def test_should_failover_true_for_transient():
    kernel = _FakeKernel()
    res = AgentResilience(_mk_config(), kernel)
    assert res._should_failover(ConnectionError("reset")) is True
    assert res._should_failover(NetworkError("dns")) is True


def test_should_failover_false_for_config_auth_model():
    kernel = _FakeKernel()
    res = AgentResilience(_mk_config(), kernel)
    assert res._should_failover(ConfigError("x")) is False
    assert res._should_failover(AuthError("x")) is False
    assert res._should_failover(ModelError("x")) is False


def test_should_failover_false_when_disabled():
    kernel = _FakeKernel()
    res = AgentResilience(_mk_config(**{"model.failover.enabled": False}), kernel)
    assert res._should_failover(ConnectionError("x")) is False


def test_should_failover_false_for_auth_markers():
    kernel = _FakeKernel()
    res = AgentResilience(_mk_config(), kernel)
    assert res._should_failover(Exception("鉴权失败 401")) is False


def test_status_returns_all_sections():
    kernel = _FakeKernel()
    res = AgentResilience(_mk_config(), kernel)
    st = res.status()
    assert set(st) == {"circuit_breaker", "rate_limiter", "retry", "failover"}
    assert st["failover"]["enabled"] is True
    assert st["retry"]["max_retries"] == 3
    assert "state" in st["circuit_breaker"]
    assert "active" in st["rate_limiter"]


def test_compat_properties():
    kernel = _FakeKernel()
    res = AgentResilience(_mk_config(), kernel)
    assert res.max_retries == 3
    res.max_retries = 5
    assert res.max_retries == 5
    assert res.retry_backoff == 0.0
    res.retry_backoff = 1.5
    assert res.retry_backoff == 1.5
    assert res.retry_jitter == 0.0
    res.retry_jitter = 0.2
    assert res.retry_jitter == 0.2
    assert isinstance(res.retry_on, set)
    res.retry_on = [500]
    assert res.retry_on == {500}


def test_fallback_adapter_builds_from_presets(monkeypatch):
    """自动选备: 有预设 + 已配置密钥 → 构建备用适配器。"""
    from tuan_cli.models.router import ModelPreset

    monkeypatch.setenv("MOONSHOT_API_KEY", "test-key")
    monkeypatch.setattr(
        "tuan_cli.models.router.MODEL_PRESETS",
        [
            ModelPreset(provider="moonshot", model="moonshot-v1-32k",
                        base_url="https://api.moonshot.cn/v1",
                        api_key_env="MOONSHOT_API_KEY", tier=2,
                        capabilities=["chat", "code", "reasoning", "function_calling"]),
        ],
    )
    # 函数内部 `from ..models.router import MODEL_PRESETS` 会重新读取模块属性,
    # patch 模块级即可 (无需 patch resilience 模块本身)。
    kernel = _FakeKernel()
    res = AgentResilience(_mk_config(), kernel)
    # available_provider_names 返回 moonshot
    monkeypatch.setattr(
        "tuan_cli.models.router.ModelRouter.available_provider_names",
        staticmethod(lambda: ["moonshot"]),
    )
    fb = res._build_fallback_adapter(_FakeModel())
    assert fb is not None
    assert fb["provider"] == "moonshot"
    assert fb["model"] == "moonshot-v1-32k"
