"""最小 OpenAI SDK 替身 —— 只实现 OpenAICompatAdapter 真正用到的调用表面。

``openai`` 包及其传递依赖 (distro / jiter / tqdm / colorama / sniffio) 共占 6 个
安装包, 其中 jiter 是编译产物。而本仓库只用到一个入口:

    client = OpenAI(base_url=..., api_key=..., timeout=..., max_retries=0)
    resp   = client.chat.completions.create(model=..., messages=..., stream=...)
    for chunk in resp: ...   # stream=True 时返回可迭代的 SSE 块

本模块用 :mod:`tuan_cli._http` 实现同样的表面, 让 OpenAI 兼容传输层零额外依赖。

**扩展约定**: 以后若需要 SDK 的新能力 (embeddings / assistants / file 上传等),
先在这里按同样方式补, 而不是把 ``openai`` 重新加回核心依赖 —— 否则这次减依赖
的成果会被一个功能点整体抹掉。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List, Optional

from . import _http

# OpenAI SDK 的 base_url 语义: 用户给 "https://api.openai.com/v1", SDK 在其后拼接
# "/chat/completions"。这里保持一致, 不要替用户猜 /v1 是否存在。


# --------------------------------------------------------------------------- #
# 响应对象 —— 属性视图, 缺失字段返回 None (对齐 pydantic 模型的可选字段行为)
# --------------------------------------------------------------------------- #
class _Usage:
    """token 用量。用 getattr 读取, 因为上层 _extract_usage 按属性名逐个取。"""

    def __init__(self, data: Any) -> None:
        self._d: Dict[str, Any] = data if isinstance(data, dict) else {}

    def __getattr__(self, key: str) -> Any:
        if key.startswith("_"):
            raise AttributeError(key)
        return self._d.get(key)

    def __bool__(self) -> bool:
        return bool(self._d)

    def __repr__(self) -> str:  # pragma: no cover - 仅用于日志
        return f"_Usage({self._d!r})"


class _Function:
    def __init__(self, data: Any) -> None:
        d = data if isinstance(data, dict) else {}
        self.name = d.get("name")
        self.arguments = d.get("arguments")
        self.description = d.get("description")

    def __bool__(self) -> bool:
        return bool(self.name or self.arguments)


class _ToolCall:
    """消息里的完整工具调用, 或流式 delta 里的增量 (含 index)。"""

    def __init__(self, data: Any) -> None:
        d = data if isinstance(data, dict) else {}
        self.id = d.get("id")
        self.type = d.get("type") or "function"
        self.function = _Function(d.get("function"))
        self.index = d.get("index")


class _Message:
    """assistant 消息与流式 delta 共用同一形状 (delta 只是字段更少)。"""

    def __init__(self, data: Any) -> None:
        d = data if isinstance(data, dict) else {}
        self.role = d.get("role")
        self.content = d.get("content")
        self.name = d.get("name")
        self.tool_call_id = d.get("tool_call_id")
        self.refusal = d.get("refusal")
        # DeepSeek / OpenCode Zen 的推理内容字段, 非标准但广泛存在
        self.reasoning_content = d.get("reasoning_content")
        self.tool_calls: List[_ToolCall] = [_ToolCall(x) for x in (d.get("tool_calls") or [])]


class _Choice:
    def __init__(self, data: Any) -> None:
        d = data if isinstance(data, dict) else {}
        self.index = d.get("index", 0)
        self.finish_reason = d.get("finish_reason")
        self.logprobs = d.get("logprobs")
        if "delta" in d:
            self.delta = _Message(d.get("delta"))
            self.message = None
        else:
            self.delta = None
            self.message = _Message(d.get("message"))


class _Completion:
    """``create()`` 的返回值: 非流式是单个块, 流式是逐块的同一个类型。"""

    def __init__(self, data: Any) -> None:
        d = data if isinstance(data, dict) else {}
        self.id = d.get("id")
        self.object = d.get("object")
        self.model = d.get("model")
        self.system_fingerprint = d.get("system_fingerprint")
        self.choices: List[_Choice] = [_Choice(c) for c in (d.get("choices") or [])]
        self.usage = _Usage(d.get("usage"))


# --------------------------------------------------------------------------- #
# 异常 —— 带 status_code, 让上层 classify_error 的状态码分支生效
# --------------------------------------------------------------------------- #
class OpenAIError(Exception):
    def __init__(self, message: str, *, status_code: Optional[int] = None,
                 response: Optional[Any] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response


# --------------------------------------------------------------------------- #
# 客户端
# --------------------------------------------------------------------------- #
class _Completions:
    def __init__(self, client: "OpenAI") -> None:
        self._client = client

    def create(self, **kwargs: Any) -> Any:
        if kwargs.pop("stream", False):
            return self._stream(kwargs)
        body = dict(kwargs)
        body.pop("stream_options", None)
        resp = self._client._request("/chat/completions", body)
        if not resp.is_success:
            raise _status_error(resp)
        return _Completion(resp.json())

    def _stream(self, kwargs: Dict[str, Any]) -> Iterator[_Completion]:
        body = dict(kwargs)
        body["stream"] = True
        with self._client._http.stream(
            "POST", self._client._endpoint("/chat/completions"),
            json=body, headers=self._client._headers(),
            timeout=self._client._timeout,
        ) as resp:
            if not resp.is_success:
                raise _status_error(resp)
            yield from _iter_sse_completions(resp.iter_lines())


class _Chat:
    def __init__(self, client: "OpenAI") -> None:
        self.completions = _Completions(client)


def _status_error(resp: _http.Response) -> OpenAIError:
    """把非 2xx 响应转成带 status_code 的异常, 错误信息尽量透出服务端原因。"""
    text = ""
    try:
        text = resp.text[:400]
    except Exception:  # noqa: BLE001 - 错误信息缺失不应掩盖原始状态码
        pass
    detail = ""
    try:
        body = resp.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            detail = err.get("message") or err.get("code") or ""
        elif isinstance(err, str):
            detail = err
        elif isinstance(body.get("message"), str):
            detail = body["message"]
        elif isinstance(body.get("detail"), str):
            detail = body["detail"]
    except Exception:  # noqa: BLE001
        pass
    msg = detail or (text.strip()[:200] if text else "")
    return OpenAIError(
        f"OpenAI 兼容接口错误 (HTTP {resp.status_code}): {msg}".strip(": "),
        status_code=resp.status_code,
        response=resp,
    )


def _iter_sse_completions(lines: Iterator[str]) -> Iterator[_Completion]:
    """按 SSE 帧解析: 累积 data: 行, 空行结束一帧; ``data: [DONE]`` 结束流。"""
    data_lines: List[str] = []
    for raw in lines:
        line = raw.rstrip("\r")
        if not line:
            if data_lines:
                payload = "\n".join(data_lines)
                data_lines = []
                if payload.strip() == "[DONE]":
                    return
                try:
                    yield _Completion(json.loads(payload))
                except json.JSONDecodeError:
                    continue
            continue
        if line.startswith(":"):  # SSE 注释 / 心跳
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:  # 服务端未以空行结尾的最后一帧
        payload = "\n".join(data_lines)
        if payload.strip() != "[DONE]":
            try:
                yield _Completion(json.loads(payload))
            except json.JSONDecodeError:
                pass


class OpenAI:
    """``openai.OpenAI`` 的最小替身。

    参数只接受 OpenAICompatAdapter 实际传入的那几个; 未知参数一律忽略,
    这样以后 SDK 加了新参数也不会让这里崩溃。
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Any = None,
        max_retries: int = 0,
        **_: Any,
    ) -> None:
        self._base_url = (base_url or "").rstrip("/")
        self._api_key = api_key
        self._max_retries = max_retries
        if isinstance(timeout, _http.Timeout):
            self._timeout = timeout
        elif isinstance(timeout, (int, float)):
            self._timeout = _http.Timeout(float(timeout), connect=float(timeout))
        else:
            self._timeout = _http.Timeout(120.0, connect=10.0)
        self._http = _http.Client(
            base_url=self._base_url,
            timeout=self._timeout,
        )
        self.chat = _Chat(self)

    # -- 内部 ------------------------------------------------------------- #
    def _endpoint(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def _headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    def _request(self, path: str, body: Dict[str, Any]) -> _http.Response:
        return self._http.post(
            self._endpoint(path), json=body, headers=self._headers(),
            timeout=self._timeout,
        )

    def close(self) -> None:
        try:
            self._http.close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> "OpenAI":
        return self

    def __exit__(self, *exc: Any) -> bool:
        self.close()
        return False
