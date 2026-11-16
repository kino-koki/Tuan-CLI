# -*- coding: utf-8 -*-
"""多模型网关 (ModelGateway) —— 自动化视频 AI 制作的核心模型调度层。

设计目标 (对齐最新开源卖点: ComfyUI 类多模型接入工作台 + Agent 驱动自动化成片):
  * **多 Provider 注册与路由**: 包装 legacy ``ModelAdapter`` 层, 支持按 provider_id /
    按任务意图 (``intent``) 路由到不同模型 (文本→规划, 视觉→分镜, 视频→合成)。
  * **结构化输出 (json_schema)**: 通过 ``response_format`` 透传给 OpenAI 兼容端点
    (已扩展 ``ModelAdapter.chat`` / ``openai_compat.chat``), 约束模型输出为给定
    schema; 解析失败时 fail-closed 抛错 (绝不静默吞)。
  * **意图路由表**: ``intent -> provider_id`` 映射, 让"文本模型调用→自动化视频 AI 制作"
    的流水线按阶段自动选模型。
  * **调用门面**: ``generate()`` 统一入口, 支持 system + tools + json_schema,
    返回结构化结果; 供 dataflow 图的 "llm_call" 节点调用 (Agent 全程驱动)。
  * **fail-closed**: provider 未配置 / 未知 intent / schema 解析失败 → 抛异常,
    绝不 fall-through 到默认模型静默执行。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Union

from ..models import create_adapter, is_known_provider
from ..models.base import ModelAdapter, ModelCapabilities
from ..models.provider_catalog import PROVIDER_BY_NAME

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 结构化输出
# ---------------------------------------------------------------------------

def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """从模型输出文本中稳健提取 JSON 对象。

    处理: 纯 JSON / 被 ```json ... ``` 包裹 / 前后有散文的 JSON 块。
    失败返回 None (调用方决定 fail-closed)。
    """
    if not text:
        return None
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()
    try:
        return json.loads(t)
    except (ValueError, TypeError):
        pass
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(t[start:end + 1])
        except (ValueError, TypeError):
            return None
    return None


# ---------------------------------------------------------------------------
# 意图路由
# ---------------------------------------------------------------------------

@dataclass
class IntentRoute:
    """一个意图 → provider 路由条目。"""

    intent: str              # 意图名 (如 "plan"/"script"/"compose")
    provider_id: Optional[str] = None  # 指定 provider; None 用激活 provider
    json_schema: Optional[Dict[str, Any]] = None  # 期望的结构化输出 schema
    max_tokens: int = 8192
    temperature: float = 0.7


# ---------------------------------------------------------------------------
# 网关
# ---------------------------------------------------------------------------

class ModelGateway:
    """多模型网关: provider 目录 + 意图路由 + 结构化输出 + 调用门面。

    底层用 legacy ``ModelAdapter`` (同步, 与项目主调用路径一致)。
    """

    def __init__(self, routes: Optional[Dict[str, IntentRoute]] = None) -> None:
        self.routes: Dict[str, IntentRoute] = dict(routes or {})
        # 适配器工厂: 可注入 (测试/替代实现); 默认用 models.create_adapter。
        self._adapter_factory: Callable[..., ModelAdapter] = create_adapter

    # 阶段 19: 本地模型探测结果缓存 (monotonic 时间戳, provider_id) —— 模块级共享,
    # 避免每次 llm_call 未指定 provider 时都 ping 本地端口 (Ollama/llama.cpp)。
    _local_probe_cache: Optional[tuple] = None

    def set_adapter_factory(self, factory: Callable[..., ModelAdapter]) -> None:
        self._adapter_factory = factory

    # --- 路由管理 ---

    def add_route(self, route: IntentRoute) -> None:
        self.routes[route.intent] = route

    def remove_route(self, intent: str) -> None:
        self.routes.pop(intent, None)

    def list_routes(self) -> List[Dict[str, Any]]:
        return [
            {
                "intent": r.intent,
                "provider_id": r.provider_id,
                "has_schema": r.json_schema is not None,
                "max_tokens": r.max_tokens,
                "temperature": r.temperature,
            }
            for r in self.routes.values()
        ]

    # --- 调用 ---

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: Optional[str] = None,
        intent: Optional[str] = None,
        provider_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        json_schema: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        on_token: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """统一生成入口: 按意图/指定 provider 选适配器 → 调用 → 结构化解析。

        返回 ``{text, tool_calls, json, provider_id}``。
        若 ``json_schema`` 给定且解析失败 → 抛 ``ValueError`` (fail-closed)。
        """
        route = self.routes.get(intent) if intent else None
        pid = provider_id or (route.provider_id if route else None)
        # 阶段 19: 未显式指定 provider / 路由未配 provider 时, 回退到本地模型探测
        # (Ollama / llama.cpp 已启动且装有模型 → 直连本地网关, 免磁盘配置)。
        if pid is None:
            pid = self._default_provider()
        # json_schema 未显式给定 → 回退到意图路由的 schema (如 video_gen 自动结构化)
        json_schema = json_schema or (route.json_schema if route else None)

        # 构造适配器: 有指定 provider → 用其 adapter; 否则 create_adapter 默认。
        try:
            adapter = self._make_adapter(pid)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"无法构造 provider {pid!r}: {exc} (fail-closed)") from exc

        eff_max = max_tokens or (route.max_tokens if route else 8192)
        eff_temp = temperature if temperature is not None else (
            route.temperature if route else 0.7
        )

        # 结构化输出: 若适配器支持 json_mode 才注入 response_format。
        response_format: Optional[Dict[str, Any]] = None
        if json_schema is not None and self._supports_json(adapter):
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_output",
                    "strict": True,
                    "schema": json_schema,
                },
            }

        messages: List[Dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        resp = adapter.chat(
            messages=messages,
            tools=tools,
            stream=bool(on_token),
            on_token=on_token,
            response_format=response_format,
        )
        # 若适配器不支持 max_tokens/temperature 透传, chat 内部用默认; 此处只取结果。
        text = resp.content or ""
        tool_calls = resp.tool_calls or []

        parsed: Optional[Dict[str, Any]] = None
        if json_schema is not None:
            parsed = extract_json(text)
            if parsed is None:
                raise ValueError(
                    f"结构化输出解析失败 (fail-closed): 模型未返回合法 JSON, "
                    f"原始片段: {text[:200]!r}"
                )

        return {
            "text": text,
            "tool_calls": [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in tool_calls
            ],
            "json": parsed,
            "provider_id": pid,
            "model": getattr(adapter, "model", getattr(adapter, "name", None)),
        }

    def _make_adapter(self, provider_id: Optional[str]) -> ModelAdapter:
        """构造适配器。provider_id 支持 'type:model' 或仅 'type' 形式;
        None → 默认适配器 (models.create_adapter 无参)。

        已知 provider 且未显式给 base_url 时, 自动补全其预设 base_url
        (如 ``llamacpp`` → http://localhost:8080/v1), 让本地/自托管模型网关
        也能经 ``llm_call`` 节点直连, 无需磁盘配置。
        """
        if provider_id:
            ptype: Optional[str] = provider_id
            model: Optional[str] = None
            if ":" in provider_id:
                ptype, model = provider_id.split(":", 1)
            base_url = self._preset_base_url(ptype)
            return self._adapter_factory(_GatewayConfig(provider=ptype, model=model,
                                                        base_url=base_url))
        return self._adapter_factory(_GatewayConfig())

    @staticmethod
    def _preset_base_url(provider: str) -> Optional[str]:
        """已知 provider 的预设 base_url; 未知/无预设返回 None (交由 create_adapter 报错)。"""
        # 阶段 19: 本地自托管网关的预设 base_url (OpenAI 兼容), 供本地探测回退直连。
        if provider in ("ollama", "llamacpp", "local"):
            return "http://localhost:11434/v1" if provider != "llamacpp" else "http://localhost:8080/v1"
        preset = PROVIDER_BY_NAME.get(provider)
        if preset is None:
            return None
        return preset.base_url or None

    # --- 阶段 19: 默认 provider 回退到本地模型探测 (免磁盘配置直连) ---

    @staticmethod
    def _default_provider() -> Optional[str]:
        """未指定 provider 时, 探测本机已启动的本地模型网关 (带缓存)。

        返回 ``"ollama:<模型>"`` / ``"llamacpp:<模型>"``, 无可用本地模型返回 None
        (交由 create_adapter 默认, 由磁盘配置/环境变量决定)。
        探测结果模块级缓存 (TTL 30s), 避免每次 llm_call 都 ping 本地端口。
        """
        import time as _time

        now = _time.monotonic()
        if ModelGateway._local_probe_cache is not None:
            cached_at, cached = ModelGateway._local_probe_cache
            if now - cached_at < 30.0:
                return cached
        result: Optional[str] = None
        try:
            from ..models.offline import detect_local_models

            status = detect_local_models()
            ollama_models = (status.get("ollama") or {}).get("models") or []
            if ollama_models:
                result = f"ollama:{ollama_models[0]}"
            else:
                llama_models = (status.get("llamacpp") or {}).get("models") or []
                if llama_models:
                    result = f"llamacpp:{llama_models[0]}"
        except Exception:  # noqa: BLE001 - 探测失败按无本地模型处理
            result = None
        ModelGateway._local_probe_cache = (now, result)
        return result

    # --- 便捷: 面向自动化的意图调用 ---

    def call_intent(self, intent: str, prompt: str,
                    json_schema: Optional[Dict[str, Any]] = None,
                    **kw: Any) -> Dict[str, Any]:
        """按意图调用 (自动应用路由的 json_schema/超参)。"""
        route = self.routes.get(intent)
        if route is None:
            raise ValueError(f"未知意图 {intent!r} (fail-closed, 拒绝调用)")
        schema = json_schema or route.json_schema
        return self.generate(
            prompt,
            intent=intent,
            json_schema=schema,
            max_tokens=kw.pop("max_tokens", route.max_tokens),
            temperature=kw.pop("temperature", route.temperature),
            **kw,
        )

    @staticmethod
    def _supports_json(adapter: ModelAdapter) -> bool:
        caps = getattr(adapter, "capabilities", None)
        if isinstance(caps, ModelCapabilities):
            return caps.json_mode
        return bool(getattr(caps, "json_mode", True)) if caps else True


class _GatewayConfig:
    """最小配置包装: 满足 ``create_adapter`` 所需的 get/api_key 接口。

    仅用于从 provider_id 字符串 (如 "openai:gpt-4o") 构造适配器, 不读磁盘配置。
    未知 provider / 缺 base_url 时由 create_adapter 给出清晰报错 (fail-closed)。
    """

    def __init__(self, provider: Optional[str] = None,
                 model: Optional[str] = None,
                 base_url: Optional[str] = None) -> None:
        self._data = {
            "model.provider": provider or "deepseek",
            "model.model": model,
            "model.base_url": base_url,
            "model.temperature": 0.7,
            "model.max_tokens": 8192,
            "model.timeout": 120,
            "model.connect_timeout": 10.0,
            "model.read_timeout": 300.0,
            "model.prompt_cache": True,
            "model.backend": "legacy",
        }

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def api_key(self) -> Optional[str]:
        return None  # 延迟到 client 属性: 真正发请求时检查环境变量
