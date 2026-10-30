"""AgentModelRouter —— 任务难度驱动的自动模型路由组件。"""
from __future__ import annotations

import pytest

from tuan_cli.core.model_router import AgentModelRouter


class _FakeKernel:
    def __init__(self) -> None:
        self.events: list = []

    def emit(self, name, payload=None):
        self.events.append((name, payload))
        return None


def _mk_config(**overrides) -> dict:
    cfg = {
        "router.enabled": True,
        "router.auto_switch": True,
        "router.difficulty_override": 0,
        "model.provider": "deepseek",
        "model.model": "deepseek-chat",
    }
    cfg.update(overrides)
    return cfg


class _FakeDecision:
    """构造一个路由决策 dict (与 ModelRouter.decide 返回同构)。"""

    @staticmethod
    def make(switch=True, provider="openai", model="gpt-4o", base_url="", api_key_env=""):
        return {
            "difficulty": 7,
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "api_key_env": api_key_env,
            "capabilities": ["chat"],
            "switch": switch,
            "reason": "测试决策",
        }


def test_maybe_route_disabled_when_router_off():
    kernel = _FakeKernel()
    router = AgentModelRouter(_mk_config(**{"router.enabled": False}), kernel)
    called = []
    router._model_switcher = lambda *a, **k: called.append(a)
    router.maybe_route("hello world")
    assert called == []
    assert router.last_route is None


def test_maybe_route_disabled_when_auto_switch_off():
    kernel = _FakeKernel()
    router = AgentModelRouter(_mk_config(**{"router.auto_switch": False}), kernel)
    called = []
    router._model_switcher = lambda *a, **k: called.append(a)
    router.maybe_route("hello world")
    assert called == []
    assert router.last_route is None


def test_maybe_route_no_switch_keeps_model(monkeypatch):
    kernel = _FakeKernel()
    router = AgentModelRouter(_mk_config(), kernel)
    called = []

    class FakeModelRouter:
        def __init__(self, **kw):
            pass

        @staticmethod
        def available_provider_names():
            return ["deepseek", "openai"]

        def decide(self, *a, **kw):
            return _FakeDecision.make(switch=False)

    monkeypatch.setattr("tuan_cli.models.router.ModelRouter", FakeModelRouter)
    router._model_switcher = lambda *a, **k: called.append(a)
    router.maybe_route("analyze this codebase")
    assert called == []  # switch=False 不切换
    assert router.last_route is not None
    assert router.last_route["switch"] is False


def test_maybe_route_switches_and_emits(monkeypatch):
    kernel = _FakeKernel()
    router = AgentModelRouter(_mk_config(), kernel)
    called = []
    switched_overrides = []

    class FakeModelRouter:
        def __init__(self, **kw):
            self.kw = kw

        @staticmethod
        def available_provider_names():
            return ["deepseek", "openai"]

        def decide(self, *a, **kw):
            return _FakeDecision.make(switch=True, provider="openai", model="gpt-4o",
                                      base_url="https://api.openai.com/v1",
                                      api_key_env="OPENAI_API_KEY")

    def fake_switcher(kernel, overrides):
        switched_overrides.append(overrides)
        called.append(1)

    monkeypatch.setattr("tuan_cli.models.router.ModelRouter", FakeModelRouter)
    router._model_switcher = fake_switcher
    router.maybe_route("design a large distributed system")
    assert called == [1]
    assert switched_overrides[0]["provider"] == "openai"
    assert switched_overrides[0]["model"] == "gpt-4o"
    assert switched_overrides[0]["base_url"] == "https://api.openai.com/v1"
    assert switched_overrides[0]["api_key_env"] == "OPENAI_API_KEY"
    # emit model.routed
    assert any(name == "model.routed" for name, _ in kernel.events)


def test_maybe_route_uses_injected_switcher(monkeypatch):
    """_model_switcher 已注入时直接使用, 不再 import ModelPlugin。"""
    kernel = _FakeKernel()
    router = AgentModelRouter(_mk_config(), kernel)
    called = []

    class FakeModelRouter:
        def __init__(self, **kw):
            pass

        @staticmethod
        def available_provider_names():
            return ["openai"]

        def decide(self, *a, **kw):
            return _FakeDecision.make(switch=True)

    monkeypatch.setattr("tuan_cli.models.router.ModelRouter", FakeModelRouter)
    router._model_switcher = lambda *a, **k: called.append(a)
    router.maybe_route("task")
    assert len(called) == 1
    assert called[0][0] is kernel  # 第一个参数是 kernel
    assert "provider" in called[0][1]


def test_maybe_route_fail_safe_on_switch_exception(monkeypatch):
    """切换抛异常 → fail-safe, 不打断, 不 emit routed。"""
    kernel = _FakeKernel()
    router = AgentModelRouter(_mk_config(), kernel)

    class FakeModelRouter:
        def __init__(self, **kw):
            pass

        @staticmethod
        def available_provider_names():
            return ["openai"]

        def decide(self, *a, **kw):
            return _FakeDecision.make(switch=True)

    monkeypatch.setattr("tuan_cli.models.router.ModelRouter", FakeModelRouter)

    def bad_switcher(kernel, overrides):
        raise RuntimeError("switch failed")

    router._model_switcher = bad_switcher
    # 不抛异常
    router.maybe_route("task")
    assert not any(name == "model.routed" for name, _ in kernel.events)


def test_maybe_route_has_images_inferred_from_pending(monkeypatch):
    """has_images=None 时从 pending_images 推断。"""
    kernel = _FakeKernel()
    router = AgentModelRouter(_mk_config(), kernel)
    seen = {}

    class FakeModelRouter:
        def __init__(self, **kw):
            pass

        @staticmethod
        def available_provider_names():
            return ["openai"]

        def decide(self, *a, **kw):
            seen.update(kw)
            return _FakeDecision.make(switch=False)

    monkeypatch.setattr("tuan_cli.models.router.ModelRouter", FakeModelRouter)
    router.maybe_route("task", pending_images=[{"path": "x.png"}])
    assert seen["has_images"] is True


def test_maybe_route_difficulty_override_merge(monkeypatch):
    """override=0 时叠加 router.difficulty_override。"""
    kernel = _FakeKernel()
    router = AgentModelRouter(_mk_config(**{"router.difficulty_override": 9}), kernel)
    seen = {}

    class FakeModelRouter:
        def __init__(self, **kw):
            pass

        @staticmethod
        def available_provider_names():
            return ["openai"]

        def decide(self, *a, **kw):
            seen.update(kw)
            return _FakeDecision.make(switch=False)

    monkeypatch.setattr("tuan_cli.models.router.ModelRouter", FakeModelRouter)
    router.maybe_route("task", override=0)
    assert seen["difficulty_override"] == 9
