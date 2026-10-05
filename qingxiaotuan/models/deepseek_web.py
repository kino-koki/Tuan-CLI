# -*- coding: utf-8 -*-
"""DeepSeek 网页登录适配器 (provider=deepseek-web, 实验性)。

使用 ``qxt login deepseek`` 保存的网页会话令牌, 直接调用 chat.deepseek.com 的
网页私有接口 (与社区 DSH-webtokens 同源思路): 免 API Key、使用网页账号额度。

**实验性声明**:
- 网页接口为私有端点, 不对外承诺稳定, DeepSeek 改版可能随时失效;
- 失效或 401/403 时, 请重新 ``qxt login deepseek`` 取新令牌;
- 生产/工具调用场景请回退官方 API (provider=deepseek + DEEPSEEK_API_KEY)。
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from .base import ModelAdapter, ModelCapabilities, ModelResponse

_WEB_BASE = "https://chat.deepseek.com/api/v0"
_WEB_MODEL = "deepseek-chat"


class DeepSeekWebAdapter(ModelAdapter):
    """DeepSeek 网页登录适配器: OpenAI 兼容 message 结构, 走网页私有端点。"""

    name = "deepseek-web"
    # 网页接口实验性: 不承诺 tools / vision, 以纯对话为主
    capabilities = ModelCapabilities(
        tool_calling=False,
        function_calling=False,
        streaming=True,
        vision=False,
        json_mode=False,
    )

    def __init__(
        self,
        token: str,
        model: str = _WEB_MODEL,
        base_url: str = _WEB_BASE,
        timeout: float = 120.0,
        read_timeout: float = 300.0,
    ) -> None:
        self.token = token
        self.model = model or _WEB_MODEL
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.read_timeout = read_timeout

    # ------------------------------------------------------------------ 接口
    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
        on_token: Optional[Callable[[str], None]] = None,
        on_reason: Optional[Callable[[str], None]] = None,
    ) -> ModelResponse:
        if tools:
            raise ValueError(
                "deepseek-web (网页登录) 暂不支持工具调用。"
                "请使用官方 API (provider=deepseek + DEEPSEEK_API_KEY) 或离线模式。"
            )
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": bool(stream),
        }
        if stream:
            return self._chat_stream(payload, on_token, on_reason)
        return self._chat_once(payload)

    # ------------------------------------------------------------------ 内部
    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    def _post(self, payload: Dict[str, Any]):
        import httpx

        try:
            return httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
                timeout=httpx.Timeout(self.timeout, read=self.read_timeout),
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"请求 DeepSeek 网页接口失败: {exc}") from exc

    def _chat_once(self, payload: Dict[str, Any]) -> ModelResponse:
        resp = self._post(payload)
        if resp.status_code != 200:
            raise self._http_error(resp)
        data = resp.json()
        try:
            choice = data["choices"][0]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError(f"DeepSeek 网页接口返回异常: {str(data)[:300]}") from None
        msg = choice.get("message") or {}
        return ModelResponse(
            content=msg.get("content") or "",
            reasoning=msg.get("reasoning_content") or "",
            finish_reason=choice.get("finish_reason") or "stop",
            usage=_usage(data.get("usage")),
        )

    def _chat_stream(
        self,
        payload: Dict[str, Any],
        on_token: Optional[Callable[[str], None]],
        on_reason: Optional[Callable[[str], None]],
    ) -> ModelResponse:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        parts: List[str] = []
        reasoning: List[str] = []
        finish_reason = "stop"
        usage: Dict[str, int] = {}

        resp = self._post(payload)
        if resp.status_code != 200:
            raise self._http_error(resp)
        resp.raise_for_status()
        for raw in resp.iter_lines():
            if not raw:
                continue
            line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            if line.startswith("data:"):
                line = line[5:].strip()
            if not line or line == "[DONE]":
                continue
            try:
                chunk = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if chunk.get("usage"):
                usage = _usage(chunk["usage"])
            for choice in chunk.get("choices") or []:
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
                delta = choice.get("delta") or {}
                if delta.get("reasoning_content"):
                    reasoning.append(delta["reasoning_content"])
                    if on_reason:
                        on_reason(delta["reasoning_content"])
                if delta.get("content"):
                    parts.append(delta["content"])
                    if on_token:
                        on_token(delta["content"])
        return ModelResponse(
            content="".join(parts),
            reasoning="".join(reasoning),
            finish_reason=finish_reason,
            usage=usage,
        )

    def _http_error(self, resp) -> RuntimeError:
        body = resp.text[:300]
        if resp.status_code in (401, 403):
            hint = (
                "DeepSeek 网页会话令牌无效或已过期: 请重新运行 `qxt login deepseek` "
                "从浏览器开发者工具粘贴最新令牌"
            )
        elif resp.status_code in (404, 405):
            hint = (
                "DeepSeek 网页接口路径已变更 (实验性接口, 网页改版可能失效); "
                "建议回退官方 API: qxt models set deepseek 后设置 DEEPSEEK_API_KEY"
            )
        else:
            hint = f"DeepSeek 网页接口 HTTP {resp.status_code}"
        return RuntimeError(f"{hint}: {body}")


def _usage(usage: Any) -> Dict[str, int]:
    if not usage or not isinstance(usage, dict):
        return {}
    out: Dict[str, int] = {}
    for key in (
        "prompt_tokens", "completion_tokens",
        "prompt_cache_hit_tokens", "prompt_cache_miss_tokens", "total_tokens",
    ):
        val = usage.get(key)
        if isinstance(val, (int, float)):
            out[key] = int(val)
    return out
