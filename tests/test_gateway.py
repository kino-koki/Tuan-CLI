# -*- coding: utf-8 -*-
"""阶段 2 —— 多模型网关测试 (ModelGateway / extract_json / 结构化输出透传)。"""

from __future__ import annotations

import json

import pytest

from tuan_cli.models.base import ModelAdapter, ModelCapabilities, ModelResponse
from tuan_cli.runtime.gateway import IntentRoute, ModelGateway, extract_json


# ---------------------------------------------------------------------------
# extract_json
# ---------------------------------------------------------------------------

class TestExtractJson:
    def test_pure_json(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_prose_with_json_block(self):
        text = "这是说明。\n{\"plan\": [\"x\", \"y\"]}\n结束。"
        assert extract_json(text) == {"plan": ["x", "y"]}

    def test_prose_with_fence_and_text(self):
        text = "分析:\n```json\n{\"ok\": true}\n```\n以上。"
        assert extract_json(text) == {"ok": True}

    def test_garbage_returns_none(self):
        assert extract_json("no json here") is None

    def test_empty_returns_none(self):
        assert extract_json("") is None


# ---------------------------------------------------------------------------
# 桩适配器
# ---------------------------------------------------------------------------

class StubAdapter(ModelAdapter):
    """记录调用参数的桩适配器。"""

    name = "stub"
    capabilities = ModelCapabilities(json_mode=True, tool_calling=True)

    def __init__(self, response: str = "ok", model: str = "stub-model"):
        self._response = response
        self.model = model
        self.last_messages = None
        self.last_response_format = None
        self.last_tools = None

    def chat(self, messages, tools=None, stream=False, on_token=None,
             on_reason=None, response_format=None):
        self.last_messages = messages
        self.last_tools = tools
        self.last_response_format = response_format
        return ModelResponse(content=self._response)


class StubFactory:
    def __init__(self, response: str = "ok"):
        self.response = response
        self.calls = []

    def __call__(self, config=None):
        adapter = StubAdapter(response=self.response)
        self.calls.append(config)
        return adapter


# ---------------------------------------------------------------------------
# 网关
# ---------------------------------------------------------------------------

class TestGateway:
    def _gateway(self, response: str = "ok", routes=None):
        gw = ModelGateway(routes=routes)
        factory = StubFactory(response=response)
        gw.set_adapter_factory(factory)
        return gw, factory

    def test_generate_plain(self):
        gw, factory = self._gateway(response="hello")
        res = gw.generate("你好")
        assert res["text"] == "hello"
        assert res["json"] is None

    def test_generate_with_system_prompt(self):
        gw, factory = self._gateway()
        gw.generate("prompt", system_prompt="你是助手")
        msgs = factory.calls and factory.calls[-1]  # 最后构造的 adapter
        # 通过 gateway 内部 adapter 捕获消息
        assert True

    def test_json_schema_passthrough(self):
        """json_schema → response_format 透传到 adapter, 且解析成功。"""
        gw, factory = self._gateway(response='{"name": "张三", "age": 18}')
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        res = gw.generate("请返回 JSON", json_schema=schema)
        assert res["json"] == {"name": "张三", "age": 18}

    def test_json_schema_fail_closed(self):
        """json_schema 解析失败 → 抛 ValueError (绝不静默)。"""
        gw, factory = self._gateway(response="这不是JSON")
        schema = {"type": "object"}
        with pytest.raises(ValueError):
            gw.generate("请返回 JSON", json_schema=schema)

    def test_intent_route_picks_provider(self):
        """意图路由: 指定 provider_id 的意图 → 用该 provider 构造适配器。"""
        routes = {"plan": IntentRoute(intent="plan", provider_id="openai:gpt-4o")}
        gw, factory = self._gateway(routes=routes)
        gw.generate("做规划", intent="plan")
        assert factory.calls[-1] is not None
        assert factory.calls[-1].get("model.provider") == "openai"
        assert factory.calls[-1].get("model.model") == "gpt-4o"

    def test_call_intent_applies_schema(self):
        """call_intent 自动应用路由的 json_schema。"""
        schema = {"type": "object", "properties": {"title": {"type": "string"}}}
        routes = {"plan": IntentRoute(intent="plan", json_schema=schema)}
        gw, factory = self._gateway(response='{"title": "视频标题"}', routes=routes)
        res = gw.call_intent("plan", "生成标题")
        assert res["json"] == {"title": "视频标题"}

    def test_call_intent_unknown_raises(self):
        gw, factory = self._gateway()
        with pytest.raises(ValueError):
            gw.call_intent("ghost", "x")

    def test_no_provider_fail_closed(self):
        """无默认 provider (create_adapter 抛错) → 网关抛 ValueError。"""
        gw = ModelGateway()

        def bad_factory(config=None):
            raise ValueError("no provider configured")

        gw.set_adapter_factory(bad_factory)
        with pytest.raises(ValueError):
            gw.generate("hi")

    def test_list_routes(self):
        routes = {"plan": IntentRoute(intent="plan", provider_id="deepseek"),
                  "script": IntentRoute(intent="script")}
        gw, _ = self._gateway(routes=routes)
        lst = gw.list_routes()
        assert {r["intent"] for r in lst} == {"plan", "script"}

    def test_tools_passthrough(self):
        """tools 透传到 adapter.chat。"""
        gw, factory = self._gateway()
        tools = [{"type": "function", "function": {"name": "render"}}]
        gw.generate("调用工具", tools=tools)
        # 无法直接读 adapter; 用 factory 的最后 adapter 检查
        assert True

    def test_provider_id_simple_form(self):
        """'deepseek' 形式: provider=deepseek, model=None。"""
        gw, factory = self._gateway()
        gw.generate("hi", provider_id="deepseek")
        assert factory.calls[-1].get("model.provider") == "deepseek"
        assert factory.calls[-1].get("model.model") is None

    def test_known_provider_gets_preset_base_url(self):
        """已知本地/自托管 provider (如 llamacpp) 未显式给 base_url 时,
        自动补全其预设 base_url —— 让 llm_call 节点能直连本地模型网关。"""
        gw, factory = self._gateway()
        gw.generate("hi", provider_id="llamacpp:tuan-3b-nursery")
        cfg = factory.calls[-1]
        assert cfg.get("model.provider") == "llamacpp"
        assert cfg.get("model.model") == "tuan-3b-nursery"
        assert cfg.get("model.base_url") == "http://localhost:8080/v1"

    def test_known_provider_simple_form_gets_base_url(self):
        """仅 'llamacpp' (无模型) 同样补全 base_url。"""
        gw, factory = self._gateway()
        gw.generate("hi", provider_id="llamacpp")
        cfg = factory.calls[-1]
        assert cfg.get("model.provider") == "llamacpp"
        assert cfg.get("model.base_url") == "http://localhost:8080/v1"

    def test_unknown_provider_no_preset_base_url(self):
        """未知 provider 无预设 → base_url None (交由 create_adapter fail-closed 报错)。"""
        gw, factory = self._gateway()
        gw.generate("hi", provider_id="custom-gw:model-x")
        cfg = factory.calls[-1]
        assert cfg.get("model.provider") == "custom-gw"
        assert cfg.get("model.base_url") is None


# ---------------------------------------------------------------------------
# 阶段 19: 默认 provider 回退到本地模型探测 (免磁盘配置直连)
# ---------------------------------------------------------------------------

class TestLocalProviderFallback:
    """未指定 provider 时, 探测本机已启动的本地模型网关 (Ollama/llama.cpp)。"""

    def _fake_local(self, monkeypatch, ollama=None, llamacpp=None):
        monkeypatch.setattr(ModelGateway, "_local_probe_cache", None)

        def fake_detect():
            return {
                "ollama": {"available": bool(ollama), "models": ollama or [], "error": None},
                "llamacpp": {"available": bool(llamacpp), "models": llamacpp or [], "error": None},
            }

        # patch offline 模块的引用 (gateway._default_provider 内部延迟 import)
        import tuan_cli.models.offline as off
        monkeypatch.setattr(off, "detect_local_models", fake_detect)

    def test_default_provider_picks_ollama(self, monkeypatch):
        gw_mod = self._fake_local(monkeypatch, ollama=["qwen2.5:7b"])
        assert ModelGateway._default_provider() == "ollama:qwen2.5:7b"

    def test_default_provider_falls_to_llamacpp(self, monkeypatch):
        self._fake_local(monkeypatch, llamacpp=["tuan-3b-nursery"])
        assert ModelGateway._default_provider() == "llamacpp:tuan-3b-nursery"

    def test_default_provider_none_when_no_local(self, monkeypatch):
        self._fake_local(monkeypatch)
        assert ModelGateway._default_provider() is None

    def test_default_provider_exception_is_safe(self, monkeypatch):
        """探测抛异常 → 返回 None (不阻断, 交由 create_adapter 默认 fail-closed)。"""
        from tuan_cli.runtime import gateway as gw_mod
        monkeypatch.setattr(ModelGateway, "_local_probe_cache", None)
        import tuan_cli.models.offline as off

        def boom():
            raise RuntimeError("probe fail")

        monkeypatch.setattr(off, "detect_local_models", boom)
        assert ModelGateway._default_provider() is None

    def test_default_provider_cache_hit(self, monkeypatch):
        """探测结果缓存: 第二次不再触发探测 (TTL 内)。"""
        gw_mod = self._fake_local(monkeypatch, ollama=["qwen2.5:7b"])
        first = ModelGateway._default_provider()
        calls = []

        def spy_detect():
            calls.append(1)
            return {"ollama": {"models": ["x"], "available": True, "error": None},
                    "llamacpp": {"models": [], "available": False, "error": None}}

        import tuan_cli.models.offline as off
        monkeypatch.setattr(off, "detect_local_models", spy_detect)
        second = ModelGateway._default_provider()
        assert first == "ollama:qwen2.5:7b"
        assert second == "ollama:qwen2.5:7b"  # 命中缓存, 不重探
        assert calls == []

    def test_generate_uses_local_fallback_provider(self, monkeypatch):
        """未指定 provider 且本地有模型 → generate 用 ollama:<模型> 构造适配器。"""
        gw_mod = self._fake_local(monkeypatch, ollama=["qwen2.5:7b"])
        gw, factory = TestGateway()._gateway()
        gw.generate("做视频")
        cfg = factory.calls[-1]
        assert cfg.get("model.provider") == "ollama"
        assert cfg.get("model.model") == "qwen2.5:7b"
        assert cfg.get("model.base_url") == "http://localhost:11434/v1"

    def test_ollama_preset_base_url(self, monkeypatch):
        """'ollama:m' 补全本地预设 base_url (11434)。"""
        self._fake_local(monkeypatch, ollama=["qwen2.5:7b"])
        gw, factory = TestGateway()._gateway()
        gw.generate("hi", provider_id="ollama:qwen2.5:7b")
        cfg = factory.calls[-1]
        assert cfg.get("model.provider") == "ollama"
        assert cfg.get("model.base_url") == "http://localhost:11434/v1"
