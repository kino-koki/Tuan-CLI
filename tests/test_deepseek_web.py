# -*- coding: utf-8 -*-
"""DeepSeek 网页登录 (deepseek-web) 适配器测试。"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from qingxiaotuan.config import Config
from qingxiaotuan.models import create_adapter
from qingxiaotuan.models.deepseek_web import DeepSeekWebAdapter

# --------------------------------------------------------------------- 桩


class FakeResp:
    """模拟 httpx.Response。"""

    status_code = 200
    text = ""

    def __init__(
        self,
        status_code: int = 200,
        payload: Optional[Dict[str, Any]] = None,
        sse_lines: Optional[List[str]] = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self._sse_lines = sse_lines
        self.text = text

    def json(self) -> Dict[str, Any]:
        if self._payload is not None:
            return self._payload
        raise ValueError("no json payload")

    def iter_lines(self) -> List[str]:
        return list(self._sse_lines or [])

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _once_payload(content: str = "你好") -> Dict[str, Any]:
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    }


def _make_adapter(monkeypatch, resp: FakeResp, token: str = "tok-abc") -> DeepSeekWebAdapter:
    adapter = DeepSeekWebAdapter(token=token)
    monkeypatch.setattr(adapter, "_post", lambda payload: resp)
    return adapter


# --------------------------------------------------------------------- 用例


def test_once_non_stream(monkeypatch) -> None:
    """非流式: 解析 choices[0].message.content 与 usage。"""
    adapter = _make_adapter(monkeypatch, FakeResp(payload=_once_payload("你好, 世界")))
    out = adapter.chat([{"role": "user", "content": "hi"}])
    assert out.content == "你好, 世界"
    assert out.finish_reason == "stop"
    assert out.usage["prompt_tokens"] == 10
    assert out.usage["total_tokens"] == 13
    assert out.tool_calls == []


def test_once_reasoning_content(monkeypatch) -> None:
    """思考模型: reasoning_content 归入 ModelResponse.reasoning。"""
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "final",
                    "reasoning_content": "think...",
                },
                "finish_reason": "stop",
            }
        ]
    }
    adapter = _make_adapter(monkeypatch, FakeResp(payload=payload))
    out = adapter.chat([{"role": "user", "content": "q"}])
    assert out.content == "final"
    assert out.reasoning == "think..."


def test_stream_sse(monkeypatch) -> None:
    """流式: 解析 data: 行, on_token 回调逐片触发。"""
    lines = [
        "data: " + json.dumps({"choices": [{"delta": {"content": "你"}, "finish_reason": None}]}),
        "data: " + json.dumps({"choices": [{"delta": {"content": "好"}}]}),
        "data: " + json.dumps({"choices": [{"delta": {}}], "usage": {"total_tokens": 5}}),
        "data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
        "data: [DONE]",
    ]
    adapter = _make_adapter(monkeypatch, FakeResp(sse_lines=lines))
    got: List[str] = []
    out = adapter.chat(
        [{"role": "user", "content": "hi"}],
        stream=True,
        on_token=got.append,
    )
    assert out.content == "你好"
    assert out.finish_reason == "stop"
    assert out.usage["total_tokens"] == 5
    assert got == ["你", "好"]


def test_stream_reasoning_callback(monkeypatch) -> None:
    lines = [
        "data: " + json.dumps({"choices": [{"delta": {"reasoning_content": "R1"}}]}),
        "data: " + json.dumps({"choices": [{"delta": {"content": "A"}}]}),
        "data: [DONE]",
    ]
    adapter = _make_adapter(monkeypatch, FakeResp(sse_lines=lines))
    reason: List[str] = []
    out = adapter.chat(
        [{"role": "user", "content": "q"}],
        stream=True,
        on_reason=reason.append,
    )
    assert reason == ["R1"]
    assert out.content == "A"
    assert out.reasoning == "R1"


def test_tools_rejected(monkeypatch) -> None:
    """实验性适配器暂不支持工具调用: 传入 tools 必须明确报错。"""
    adapter = _make_adapter(monkeypatch, FakeResp(payload=_once_payload()))
    with pytest.raises(ValueError, match="暂不支持工具调用"):
        adapter.chat(
            [{"role": "user", "content": "q"}],
            tools=[{"type": "function", "function": {"name": "f", "parameters": {}}}],
        )


def test_http_401_hint(monkeypatch) -> None:
    """401: 给出重新登录的明确提示。"""
    adapter = _make_adapter(
        monkeypatch, FakeResp(status_code=401, text='{"error":"unauthorized"}')
    )
    with pytest.raises(RuntimeError, match="qxt login deepseek"):
        adapter.chat([{"role": "user", "content": "q"}])


def test_http_404_hint(monkeypatch) -> None:
    """404: 提示网页接口可能改版, 建议回退官方 API。"""
    adapter = _make_adapter(
        monkeypatch, FakeResp(status_code=404, text="not found")
    )
    with pytest.raises(RuntimeError, match="回退官方 API"):
        adapter.chat([{"role": "user", "content": "q"}])


def test_malformed_payload(monkeypatch) -> None:
    """网页接口返回非预期结构: 报错而非崩溃。"""
    adapter = _make_adapter(monkeypatch, FakeResp(payload={"foo": 1}))
    with pytest.raises(RuntimeError, match="返回异常"):
        adapter.chat([{"role": "user", "content": "q"}])


# ------------------------------------------------------------------ 集成


def test_create_adapter_deepseek_web_with_env_token(monkeypatch) -> None:
    """环境变量 QXT_DEEPSEEK_WEB_TOKEN 优先: create_adapter 构造网页适配器。"""
    monkeypatch.setenv("QXT_DEEPSEEK_WEB_TOKEN", "env-tok")
    cfg = Config(profile="default")
    cfg.data["model"].update(
        {
            "provider": "deepseek-web",
            "model": "deepseek-chat",
            "base_url": "https://chat.deepseek.com/api/v0",
        }
    )
    adapter = create_adapter(cfg)
    assert isinstance(adapter, DeepSeekWebAdapter)
    assert adapter.token == "env-tok"


def test_create_adapter_deepseek_web_from_auth_store(monkeypatch) -> None:
    """无环境变量时回退 AuthStore 登录态 (qxt login deepseek 保存的 token)。"""
    monkeypatch.delenv("QXT_DEEPSEEK_WEB_TOKEN", raising=False)

    class FakeStore:
        def get(self, provider: str) -> Optional[dict]:
            assert provider == "deepseek"
            return {"token": "stored-tok", "login": "user@deepseek"}

    monkeypatch.setattr("qingxiaotuan.auth.AuthStore", FakeStore)
    cfg = Config(profile="default")
    cfg.data["model"].update({"provider": "deepseek-web", "model": "deepseek-chat"})
    adapter = create_adapter(cfg)
    assert isinstance(adapter, DeepSeekWebAdapter)
    assert adapter.token == "stored-tok"


def test_create_adapter_deepseek_web_without_token(monkeypatch) -> None:
    """既无环境变量也无登录态: 给出运行 qxt login deepseek 的明确报错。"""
    monkeypatch.delenv("QXT_DEEPSEEK_WEB_TOKEN", raising=False)

    class EmptyStore:
        def get(self, provider: str) -> Optional[dict]:
            return None

    monkeypatch.setattr("qingxiaotuan.auth.AuthStore", EmptyStore)
    cfg = Config(profile="default")
    cfg.data["model"].update({"provider": "deepseek-web", "model": "deepseek-chat"})
    with pytest.raises(ValueError, match="qxt login deepseek"):
        create_adapter(cfg)


def test_catalog_contains_deepseek_web() -> None:
    """deepseek-web 已注册进供应商目录 (models set / 命令补全可见)。"""
    from qingxiaotuan.models import get_provider

    p = get_provider("deepseek-web")
    assert p is not None
    assert p.name == "deepseek-web"
    assert p.base_url == "https://chat.deepseek.com/api/v0"
    assert p.api_key_env == "QXT_DEEPSEEK_WEB_TOKEN"
