"""OpenAI 兼容协议适配器 —— 一套代码适配 DeepSeek / OpenAI / OpenRouter / Moonshot / OpenCode Zen 等。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from .base import ModelAdapter, ModelCapabilities, ModelResponse, ToolCall
from ..core.errors import ConfigError

if TYPE_CHECKING:
    from .. import _openai_sdk

# OpenAI 推理模型 (o1/o3/o4/gpt-5/codex-mini 系列) 的 Chat Completions 参数限制:
# - 只接受默认 temperature (1), 传 0.7 等 → 400 Unsupported value;
# - 不接受 max_tokens, 必须改用 max_completion_tokens → 400 Unsupported parameter。
# 网关常带 "openai/" 之类前缀 (如 OpenRouter 的 openai/gpt-5.6-sol), 判定前先剥离。
_OPENAI_REASONING_RE = re.compile(r"^(?:o[1-9]|gpt-5|codex-mini)(?:$|[-._])")


def _is_openai_reasoning_model(model: Optional[str]) -> bool:
    """按模型名判定是否需要使用推理模型的参数口径。"""
    name = (model or "").strip().lower()
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    return bool(_OPENAI_REASONING_RE.match(name))


class OpenAICompatAdapter(ModelAdapter):
    name = "openai-compat"
    capabilities = ModelCapabilities(
        tool_calling=True, function_calling=True, streaming=True,
        vision=True, json_mode=True,
    )

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: Optional[str],
        temperature: float = 0.7,
        max_tokens: int = 8192,
        timeout: float = 120,
        connect_timeout: float = 10.0,
        read_timeout: float = 120.0,
        prompt_cache: bool = True,
    ) -> None:
        base = (base_url or "").rstrip("/")
        # 修复: snowflake 等目录条目的 base_url 已含完整 /chat/completions 路径,
        # 传输层还会再拼一次 → 双重路径必 404。这里剥掉尾段, 保证恰好拼接一次。
        if base.endswith("/chat/completions"):
            base = base[: -len("/chat/completions")]
        # 修复: cloudflare 目录条目的 base_url 含 {account_id} 模板, 旧代码
        # 原样上送必 404。此处用 CLOUDFLARE_ACCOUNT_ID 环境变量实例化模板。
        if "{account_id}" in base:
            import os as _os
            _account = _os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
            if not _account:
                raise ConfigError(
                    "cloudflare 供应商需要账户 ID: 请设置环境变量 CLOUDFLARE_ACCOUNT_ID "
                    "(base_url 中的 {account_id} 模板将用它实例化)。"
                )
            base = base.replace("{account_id}", _account)
        self.base_url = base
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        # 保留配置位以兼容既有 model.prompt_cache 设置。OpenAI 兼容端点的前缀缓存
        # 由服务端自动生效, 不再上送 Anthropic 风格的 cache_control (会触发 400)。
        self.prompt_cache = prompt_cache
        self._client: Optional[Any] = None
        # 防御历史脏数据: 误粘 "Bearer " 前缀的 key 剥离, 避免双重 Bearer 头
        if api_key and str(api_key).strip().lower().startswith("bearer "):
            api_key = str(api_key).strip()[7:].strip()
        self._api_key = api_key

    @property
    def client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                # 本地/自托管端点 (Ollama / llama.cpp / LM Studio / vLLM 等 OpenAI 兼容服务)
                # 通常不需要真实密钥, 缺失时回落一个占位 key, 避免本地测试被卡在鉴权。
                # 远程端点仍严格要求真实密钥 (下方发请求后由服务端返回 401)。
                if "localhost" in self.base_url or "127.0.0.1" in self.base_url:
                    self._api_key = "sk-local-llm"
                else:
                    # ConfigError (业务错误 kind="config"): 重试策略据此快速失败,
                    # 不再按瞬时网络错误白等十几秒; 文案供 C-2 模板渲染。
                    raise ConfigError(
                        "未配置 API Key。请运行 `tuan setup`, 或设置环境变量 "
                        "DEEPSEEK_API_KEY / OPENCODE_ZEN_API_KEY / TUAN_API_KEY。"
                    )
            # 延迟导入: 只在真正发请求时加载传输层。
            # 注意: 我们用的是 tuan_cli._openai_sdk 的极简替身而不是 PyPI 的 openai ——
            # openai 包连带 distro / jiter(编译产物) / tqdm / colorama / sniffio 共 6 个包,
            # 而这里只用到 client.chat.completions.create() 一个入口。见 _openai_sdk 模块头。
            from .. import _http as httpx
            from .. import _openai_sdk

            # 分离连接与读超时; 流式场景读超时作为分片间最大空闲
            timeout_cfg: Any
            if self.connect_timeout and self.read_timeout:
                timeout_cfg = httpx.Timeout(
                    connect=self.connect_timeout,
                    read=self.read_timeout,
                    write=self.connect_timeout,
                    pool=self.connect_timeout,
                )
            else:
                timeout_cfg = self.timeout
            self._client = _openai_sdk.OpenAI(
                base_url=self.base_url,
                api_key=self._api_key,
                timeout=timeout_cfg,
                max_retries=0,  # 重试用 agent 层统一控制, 避免传输层与业务逻辑双重重试
            )
        return self._client

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
        on_token: Optional[Callable[[str], None]] = None,
        on_reason: Optional[Callable[[str], None]] = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> ModelResponse:
        # 纵深防御: 统一补齐 assistant.tool_calls 的 type="function" 字段。
        # 这是所有 OpenAI 兼容端点的唯一出口, 在此规范化可保证无论上游哪个构造点
        # 遗漏, 落到线上请求体里的结构都合规 (严格端点如 SenseNova 会以 400 拒绝
        # 缺 type 的 tool_call)。
        messages = self._ensure_tool_call_types(messages)
        messages = self._sanitize_outbound(messages)
        # 参数口径按模型区分: OpenAI 推理模型 (o 系列 / gpt-5) 拒收 temperature 与
        # max_tokens —— 发送即 400。其余模型维持 temperature + max_tokens。
        # 注: 不再向 OpenAI 兼容端点注入 Anthropic 风格的 cache_control —— 该字段
        # 不属于 chat/completions 协议, 严格端点 (OpenAI/通义/智谱等) 会以
        # "Unrecognized request argument" 400 拒绝; 各家的前缀缓存均为服务端自动
        # 生效 (DeepSeek/OpenAI/Moonshot 等), 无需显式断点。
        kwargs: Dict[str, Any] = {"model": self.model, "messages": messages}
        if _is_openai_reasoning_model(self.model):
            kwargs["max_completion_tokens"] = self.max_tokens
        else:
            kwargs["temperature"] = self.temperature
            kwargs["max_tokens"] = self.max_tokens
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        # 结构化输出 (json_schema): 透传 response_format; 仅当调用方显式提供才注入。
        # 这是"文本模型→自动化视频 AI 制作"的关键: 约束模型输出为给定 schema。
        if response_format:
            kwargs["response_format"] = response_format

        if stream:
            return self._chat_stream(kwargs, on_token, on_reason)
        resp = self.client.chat.completions.create(**kwargs)
        return self._parse(resp.choices[0], getattr(resp, "usage", None))

    @staticmethod
    def _ensure_tool_call_types(
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """确保 assistant.tool_calls 每项含 ``type="function"`` (OpenAI 兼容规范必需)。

        严格端点 (如 SenseNova) 会对缺 ``type`` 的 tool_call 返回 400
        (``invalid tool_call type``)。本方法只**补齐缺失字段**, 不改动已合规项;
        仅在确有修改时才复制 (copy-on-write), 不污染调用方持有的原始 messages
        (Agent 的会话历史仍需保持原对象身份)。
        """
        out: Optional[List[Dict[str, Any]]] = None
        for i, m in enumerate(messages):
            if not isinstance(m, dict) or m.get("role") != "assistant":
                continue
            tcs = m.get("tool_calls")
            if not isinstance(tcs, list) or not tcs:
                continue
            fixed = None
            for j, tc in enumerate(tcs):
                if not isinstance(tc, dict) or tc.get("type") == "function":
                    continue
                if fixed is None:
                    fixed = list(tcs)
                tc2 = dict(tc)
                tc2["type"] = "function"
                fixed[j] = tc2
            if fixed is not None:
                if out is None:
                    out = list(messages)
                m2 = dict(m)
                m2["tool_calls"] = fixed
                out[i] = m2
        return out if out is not None else messages

    @staticmethod
    def _sanitize_outbound(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """发送前按 chat/completions 协议清洗消息, 消除常见的 400 参数/结构问题。

        - 剔除非协议字段 (如本地记录用的 ``status``), 严格端点会以
          "unknown field" 400 拒绝;
        - tool 消息 content 必须是非空字符串 (None/"" 会被严格端点 400);
        - assistant 带 tool_calls 时 content 空串归一为 None (协议允许 null);
        - assistant.tool_calls 必须与后继 tool 消息成对, 未配对的剥离;
          无前驱 assistant 的孤儿 tool 消息丢弃 —— 工具中断后残留的坏历史
          会让后续每轮都 400 (粘性)。

        返回新列表, 不修改调用方持有的会话历史。
        """
        allowed = {"role", "content", "name", "tool_calls", "tool_call_id"}
        cleaned: List[Dict[str, Any]] = []
        declared: set = set()
        referenced: set = set()
        for raw in messages:
            if not isinstance(raw, dict):
                continue
            m = {k: v for k, v in raw.items() if k in allowed}
            if m.get("role") == "assistant":
                for tc in m.get("tool_calls") or []:
                    if tc.get("id"):
                        declared.add(tc["id"])
            elif m.get("role") == "tool" and m.get("tool_call_id"):
                referenced.add(m["tool_call_id"])
            cleaned.append(m)
        paired = declared & referenced

        out: List[Dict[str, Any]] = []
        for m in cleaned:
            role = m.get("role")
            if role == "tool":
                if not m.get("tool_call_id") or m["tool_call_id"] not in declared:
                    continue  # 孤儿 tool 消息 → 400, 丢弃
                if not isinstance(m.get("content"), str) or m["content"] == "":
                    m["content"] = "[empty]"
                out.append(m)
                continue
            if role == "assistant":
                tcs = m.get("tool_calls") or []
                if tcs:
                    kept = [tc for tc in tcs if tc.get("id") in paired]
                    if kept:
                        m["tool_calls"] = kept
                        if m.get("content") == "":
                            m["content"] = None
                    else:
                        m.pop("tool_calls", None)
                        if not m.get("content"):
                            continue  # 纯空 assistant 消息, 无信息量
                elif not m.get("content"):
                    continue
            out.append(m)
        return out

    # ------------------------------------------------------------------ 内部

    def _chat_stream(self, kwargs: Dict[str, Any], on_token: Any, on_reason: Any) -> ModelResponse:
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}
        content_parts: List[str] = []
        reasoning_parts: List[str] = []
        tool_acc: Dict[int, Dict[str, str]] = {}
        finish_reason = "stop"
        usage: Dict[str, int] = {}

        for chunk in self.client.chat.completions.create(**kwargs):
            if getattr(chunk, "usage", None):
                usage = _extract_usage(chunk.usage)
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason
            if getattr(delta, "reasoning_content", None):
                reasoning_parts.append(delta.reasoning_content)
                if on_reason:
                    on_reason(delta.reasoning_content)
            if delta.content:
                content_parts.append(delta.content)
                if on_token:
                    on_token(delta.content)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    slot = tool_acc.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] += tc.id
                    if tc.function and tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["arguments"] += tc.function.arguments

        return ModelResponse(
            content="".join(content_parts),
            reasoning="".join(reasoning_parts),
            tool_calls=[ToolCall(**tool_acc[i]) for i in sorted(tool_acc)],
            finish_reason=finish_reason,
            usage=usage,
        )

    # ------------------------------------------------------------ 错误分类

    @staticmethod
    def classify_error(exc: Exception) -> Tuple[str, Optional[int]]:
        """把异常归类为 ('rate_limit'|'timeout'|'server'|'auth'|'other', status_code)。"""
        from .. import _http as httpx
        # 传输层异常 (可能包在业务异常里)
        status = getattr(exc, "status_code", None)
        if status is None:
            # httpx 异常可能包在 openai 异常里
            cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
            status = getattr(cause, "status_code", None)
        msg = str(exc).lower()
        if status == 429 or "rate" in msg or "too many requests" in msg:
            return "rate_limit", status or 429
        if status in (401, 403) or "auth" in msg or "unauthorized" in msg or "invalid api key" in msg:
            return "auth", status or 401
        if status in (500, 502, 503, 504) or "server error" in msg:
            return "server", status
        if isinstance(exc, (httpx.TimeoutException,)) or "timeout" in msg or status in (408, 409):
            return "timeout", status or 408
        return "other", status

    @staticmethod
    def _parse(choice: Any, usage: Any) -> ModelResponse:
        msg = choice.message
        tool_calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments or "")
            for tc in (msg.tool_calls or [])
        ]
        return ModelResponse(
            content=msg.content or "",
            reasoning=getattr(msg, "reasoning_content", "") or "",
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=_extract_usage(usage),
        )


def _extract_usage(usage: Any) -> Dict[str, int]:
    """统一抽取 token 用量, 含 DeepSeek 的 prompt cache 命中字段。

    DeepSeek / OpenCode Zen 在 usage 里返回:
        prompt_tokens, completion_tokens,
        prompt_cache_hit_tokens, prompt_cache_miss_tokens
        (部分版本还有 cache_write_token)。
    我们把它们全部归一化进 dict, 供 UI 计算命中率。
    """
    if not usage:
        return {}
    src = usage if isinstance(usage, dict) else usage
    out: Dict[str, int] = {}
    for key in (
        "prompt_tokens", "completion_tokens",
        "prompt_cache_hit_tokens", "prompt_cache_miss_tokens",
        "cache_write_token", "total_tokens",
    ):
        val = getattr(src, key, None)
        if val is None and isinstance(src, dict):
            val = src.get(key)
        if isinstance(val, (int, float)):
            out[key] = int(val)
    return out
