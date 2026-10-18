"""OpenAI Chat Completions provider（chat/completions + tools + 流式）。

覆盖所有 OpenAI 兼容端点：OpenAI、DeepSeek、Kimi、通义、GLM、本地网关(Ollama/vLLM) 等。
httpx 直连，零额外依赖。

上游缺陷修复：
- nvidia 系 provider 在请求发出前剔除 `prompt_cache_key`（is_nvidia 构造参数控制）。
- 空值保护：_http.strip_prompt_cache_key 在 body 为空/非 dict/字段缺失时直接跳过。
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, AsyncIterator, Dict, List, Optional

from ..contract import (
    ChatProvider,
    FinishReason,
    GenerateOptions,
    Message,
    Role,
    StreamedMessage,
    StreamedMessagePart,
    Tool,
    Usage,
)
from ._http import build_client, is_nvidia_provider, iter_sse, raise_for_status, strip_prompt_cache_key


def _convert_tool(tool: Tool) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _sanitize_outgoing(d: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """发送前清洗单条 OpenAI 兼容消息 (防 HTTP 400 粘性)。

    空 content ("" / [] / None) 会被严格端点 (DeepSeek/商汤等) 直接 400;
    若坏消息已进会话, 后续每轮都带上 → 触发一次后连续 400。这里统一兜底:
    - tool 消息: content 必须为非空字符串
    - assistant 空消息且无工具调用: 无意义, 直接过滤
    - 其余: 空列表/None 归一为字符串
    """
    role = d.get("role", "")
    content = d.get("content")
    tool_calls = d.get("tool_calls")
    if role == "tool":
        if content is None or content == "":
            d["content"] = "[empty]"
        elif not isinstance(content, str):
            d["content"] = str(content)
        return d
    if content is None:
        content = ""
    if isinstance(content, list):
        content = [p for p in content if p is not None]
        if not content:
            content = ""
    if isinstance(content, str) and content == "":
        if tool_calls:
            # 带工具调用的 assistant 通常无文本 (纯思考/纯工具轮):
            # content 空字符串会被严格端点 (DeepSeek/商汤等) 判 400,
            # OpenAI 官方格式允许 content=null; 置 None 而非留空串。
            d["content"] = None
        else:
            return None  # 空 assistant 消息 (纯思考/空响应), 无信息量, 过滤
    else:
        d["content"] = content
    return d


def _audit_history(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """多轮历史结构审计 —— 400 粘性的根治兜底。

    严格端点 (OpenAI 官方 / DeepSeek / 商汤 / Agnes 等) 对消息序列有硬性要求,
    而 agent 循环中断 (工具执行异常 / Ctrl+C / 流式失败) 会在历史里残留坏配对:
    - assistant(tool_calls) 无后继 tool 消息 → 400 (tool_calls 未闭合);
    - tool 消息无前驱 assistant(tool_calls) → 400 (tool_call_id 无对应);
    - 每轮都带上坏消息 → 触发一次后粘性复发。

    规则 (按 OpenAI chat/completions 协议):
    1. system 只允许一条: 由调用方注入, history 中多余的 system 一律丢弃;
    2. assistant 的 tool_calls 必须与后继 tool 消息配对 (id 精确匹配);
       未配对的 tool_calls 剥离 (保留文本), 剥离后既无文本又无 tool_calls 则整条丢弃;
    3. tool 消息的 tool_call_id 必须存在于某个 assistant 的 tool_calls 中,
       孤儿 tool 消息直接丢弃;
    4. arguments 必须是 JSON 字符串: dict/list 强制 json.dumps;
    5. tool 消息 content 必须是非空字符串。
    """
    hist = [d for d in history if d.get("role") != "system"]
    # 第一遍: 收集 assistant 声明的 tool_call ids (待配对) 与 tool 消息引用的 ids
    declared: set = set()
    referenced: set = set()
    for d in hist:
        role = d.get("role", "")
        if role == "assistant":
            for tc in d.get("tool_calls") or []:
                if tc.get("id"):
                    declared.add(tc["id"])
        elif role == "tool":
            cid = d.get("tool_call_id")
            if cid:
                referenced.add(cid)
    paired = declared & referenced

    out: List[Dict[str, Any]] = []
    for d in hist:
        role = d.get("role", "")
        if role == "tool":
            cid = d.get("tool_call_id")
            # 孤儿 tool 消息 (无前驱 assistant) → 丢弃, 否则严格端点 400
            if cid not in declared:
                continue
            content = d.get("content")
            if content is None or content == "":
                d["content"] = "[empty]"
            elif not isinstance(content, str):
                d["content"] = str(content)
            out.append(d)
            continue
        if role == "assistant":
            tcs = d.get("tool_calls") or []
            if tcs:
                kept = [tc for tc in tcs if tc.get("id") in paired]
                if not kept:
                    d.pop("tool_calls", None)  # 无后继 tool 消息 → 剥离, 防 400
                else:
                    for tc in kept:
                        args = tc.get("function", {}).get("arguments")
                        if args is not None and not isinstance(args, str):
                            try:
                                tc["function"]["arguments"] = json.dumps(
                                    args, ensure_ascii=False)
                            except (TypeError, ValueError):
                                tc["function"]["arguments"] = str(args)
                    d["tool_calls"] = kept
            text = d.get("content")
            if isinstance(text, list):
                text = [p for p in text if p is not None]
                if not text:
                    text = ""
            if isinstance(text, str) and text == "" and not d.get("tool_calls"):
                continue  # 空且无工具 → 过滤
            d["content"] = text
            out.append(d)
            continue
        # user 等其余角色
        content = d.get("content")
        if isinstance(content, list):
            content = [p for p in content if p is not None]
            if not content:
                content = ""
        if isinstance(content, str) and content == "":
            continue
        d["content"] = content
        out.append(d)
    return out


def _convert_messages(system_prompt: str, history: List[Message]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if system_prompt:
        out.append({"role": "system", "content": system_prompt})
    raw = []
    for m in history:
        cleaned = _sanitize_outgoing(m.to_dict())
        if cleaned is not None:
            raw.append(cleaned)
    out.extend(_audit_history(raw))
    return out


def _debug_dump_body(body: Dict[str, Any]) -> None:
    """TUAN_DEBUG_BODY=1 时向 stderr 打印请求体结构摘要 (定位 HTTP 400 用)。"""
    if not os.environ.get("TUAN_DEBUG_BODY"):
        return
    lines = ["[tuan-debug] POST /chat/completions body:"]
    msgs = body.get("messages") or []
    lines.append(f"  messages={len(msgs)} tools={len(body.get('tools') or [])} "
                 f"keys={sorted(body.keys())}")
    for i, m in enumerate(msgs):
        role = m.get("role", "?")
        content = m.get("content")
        if isinstance(content, str):
            c = f"str({len(content)})={content[:48]!r}"
        elif isinstance(content, list):
            c = f"list({len(content)})={[p.get('type') for p in content if isinstance(p, dict)][:5]}"
        else:
            c = repr(content)[:48]
        tcs = m.get("tool_calls")
        tc_s = ""
        if tcs:
            tc_s = " tool_calls=" + json.dumps(
                [{"id": t.get("id"), "name": t.get("function", {}).get("name"),
                  "args_len": len(t.get("function", {}).get("arguments", ""))}
                 for t in tcs], ensure_ascii=False)
        tcid = f" tool_call_id={m.get('tool_call_id')!r}" if m.get("tool_call_id") else ""
        lines.append(f"  [{i}] {role}{tcid}: {c}{tc_s}")
    print("\n".join(lines), file=sys.stderr, flush=True)


def _map_finish_reason(raw: Optional[str]) -> FinishReason:
    if raw is None:
        return FinishReason.OTHER
    return {
        "stop": FinishReason.COMPLETED,
        "tool_calls": FinishReason.TOOL_CALLS,
        "length": FinishReason.TRUNCATED,
        "content_filter": FinishReason.FILTERED,
    }.get(raw, FinishReason.OTHER)


class OpenAILegacyChatProvider(ChatProvider):
    """OpenAI chat/completions 协议适配。"""

    name = "openai-legacy"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: Optional[str],
        model: str,
        max_tokens: int = 8192,
        temperature: float = 0.7,
        is_nvidia: bool = False,
        extra_headers: Optional[Dict[str, str]] = None,
        timeout: float = 120.0,
        connect_timeout: float = 10.0,
        read_timeout: float = 300.0,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self.model_name = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._is_nvidia = is_nvidia
        self._extra_headers = extra_headers
        self._timeout = timeout
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self.thinking_effort = None
        self.max_completion_tokens = max_tokens

    def _build_body(
        self,
        system_prompt: str,
        tools: List[Tool],
        history: List[Message],
        options: Optional[GenerateOptions],
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": self.model_name,
            "messages": _convert_messages(system_prompt, history),
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = [_convert_tool(t) for t in tools]
            body["tool_choice"] = "auto"
        if options and options.max_completion_tokens:
            body["max_tokens"] = options.max_completion_tokens
        # prompt 缓存键：nvidia 不支持 → 由下方 strip 处理；其它 provider 注入
        if options and options.cache_key and not self._is_nvidia:
            body["prompt_cache_key"] = options.cache_key
        return body

    async def generate(
        self,
        system_prompt: str,
        tools: List[Tool],
        history: List[Message],
        options: Optional[GenerateOptions] = None,
        callbacks: Optional[Any] = None,
    ) -> StreamedMessage:
        body = self._build_body(system_prompt, tools, history, options)
        _debug_dump_body(body)
        # ---- 上游 0.29→0.39 缺陷修复：nvidia 剔除 prompt_cache_key ----
        if self._is_nvidia:
            strip_prompt_cache_key(body)

        client = build_client(
            self._base_url,
            self._api_key,
            timeout=self._timeout,
            connect_timeout=self._connect_timeout,
            read_timeout=self._read_timeout,
            extra_headers=self._extra_headers,
        )

        sm = StreamedMessage.__new__(StreamedMessage)
        sm.id = None
        sm.usage = None
        sm.finish_reason = None
        sm.raw_finish_reason = None
        sm.trace_id = None
        sm.request_id = None

        async def _gen() -> AsyncIterator[StreamedMessagePart]:
            try:
                async with client.stream(
                    "POST", "/chat/completions", json=body
                ) as resp:
                    raise_for_status(resp)
                    async for _event, data_str in iter_sse(resp):
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        if callbacks and callbacks.on_trace_id and chunk.get("id") and not sm.trace_id:
                            sm.trace_id = chunk.get("id")
                            callbacks.on_trace_id(chunk["id"])
                        choices = chunk.get("choices") or []
                        if choices:
                            delta = choices[0].get("delta") or {}
                            if delta.get("content"):
                                yield StreamedMessagePart(type="text_delta", text=delta["content"])
                            for tc in delta.get("tool_calls") or []:
                                yield StreamedMessagePart(
                                    type="tool_call_part",
                                    id=tc.get("id"),
                                    name=(tc.get("function") or {}).get("name"),
                                    arguments_delta=(tc.get("function") or {}).get("arguments", ""),
                                    index=tc.get("index"),
                                )
                            raw_fr = choices[0].get("finish_reason")
                            if raw_fr:
                                sm.raw_finish_reason = raw_fr
                                sm.finish_reason = _map_finish_reason(raw_fr)
                        if chunk.get("usage"):
                            u = chunk["usage"]
                            sm.usage = Usage(
                                input_tokens=u.get("prompt_tokens", 0),
                                output_tokens=u.get("completion_tokens", 0),
                                input_cache_read_tokens=u.get("prompt_tokens_details", {}).get(
                                    "cached_tokens", 0
                                )
                                if isinstance(u.get("prompt_tokens_details"), dict)
                                else 0,
                            )
                        if sm.finish_reason and sm.usage:
                            yield StreamedMessagePart(type="finish", finish_reason=sm.finish_reason)
            finally:
                await client.aclose()

        sm._aiter = _gen()
        return sm
