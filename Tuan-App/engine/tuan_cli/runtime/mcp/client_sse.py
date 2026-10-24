"""MCP SSE 客户端 —— 通过 Server-Sent Events 与 MCP server 通信。

标准 MCP SSE 传输要求 client->server 走 POST、server->client 走一条长连接
``GET`` SSE 流（且首包通常是 ``endpoint`` 事件给出回调 POST 地址）。本模块在
``HttpMcpClient`` 之上实现：

- 握手前先 GET 打开 SSE 流并等待 ``endpoint`` 事件自动发现回调靶点；
- 发现后切换 POST 靶点（initialize / tools/list / tools/call / ping 均复用
  POST + JSON-RPC，与 HTTP 一致），并保持 GET 流消费 server 主动推送；
- 未发现 ``endpoint`` 事件时回退为原始 URL（兼容 Streamable HTTP 风格）。
- 流断开时触发 ``on_unexpected_close``。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Dict, List, Optional

import httpx

from .client_http import HttpMcpClient
from .errors import McpError
from .types import UnexpectedCloseReason


class SseMcpClient(HttpMcpClient):
    """SSE 传输客户端：优先做 endpoint 发现，再以 POST 发请求 + 后台 GET SSE 收通知。

    标准 MCP SSE 传输第一步是 GET 打开一条 SSE 流，server 首包以 ``endpoint`` 事件
    返回 JSON ``{"uri": ...}`` 作为后续 POST 的回调靶点。本实现：
    1. 握手前先建立 GET SSE 流并等待 ``endpoint`` 事件；
    2. 发现后把 ``self._url`` 切换为回调靶点，POST（initialize/tools/*）发往该址；
    3. 未发现 ``endpoint`` 事件时回退为原始 URL（Streamable HTTP 风格，同 URL 走 POST）。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._sse_task: Optional[asyncio.Task] = None
        self._sse_headers: Dict[str, str] = {}
        self._endpoint_fut: Optional[asyncio.Future] = None

    async def connect(self) -> None:
        if self._closed:
            raise McpError("MCP SSE client is closed")
        if self._ready:
            return
        # 1) 先建立 GET SSE 流并尝试发现 endpoint 回调靶点。
        self._sse_headers = {"Accept": "text/event-stream"}
        self._sse_headers.update(self._headers)
        loop = asyncio.get_event_loop()
        self._endpoint_fut = loop.create_future()
        self._sse_task = asyncio.ensure_future(self._sse_listen())
        try:
            discovered = await asyncio.wait_for(
                asyncio.shield(self._endpoint_fut), timeout=self.startup_timeout
            )
        except asyncio.TimeoutError:
            # 未发现 endpoint 事件：回退原 URL（Streamable HTTP）。
            pass
        else:
            if discovered and isinstance(discovered, str) and discovered:
                self._url = discovered
        # 2) 握手（POST initialize / notifications/initialized）发往最终靶点。
        await super().connect()

    async def close(self) -> None:
        if self._sse_task is not None and not self._sse_task.done():
            self._sse_task.cancel()
        self._sse_task = None
        if self._endpoint_fut is not None and not self._endpoint_fut.done():
            self._endpoint_fut.cancel()
        self._endpoint_fut = None
        await super().close()

    async def _sse_listen(self) -> None:
        try:
            async with self._client.stream(
                "GET", self._url, headers=self._sse_headers
            ) as resp:
                event_type = ""
                data_lines: List[str] = []
                async for _raw in resp.aiter_lines():
                    line = _raw.rstrip("\r")
                    if line == "":
                        # 空行 = 事件结束，派发累积的 event/data。
                        if data_lines:
                            self._dispatch_sse_event(event_type, "\n".join(data_lines))
                        event_type = ""
                        data_lines = []
                        continue
                    if line.startswith(":"):  # SSE 注释行
                        continue
                    field, _, value = line.partition(":")
                    if value.startswith(" "):
                        value = value[1:]
                    if field == "event":
                        event_type = value.strip()
                    elif field == "data":
                        data_lines.append(value)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # 流异常断开
            self._last_error = exc
            if not self._closed:
                listener: Optional[Callable[[UnexpectedCloseReason], None]] = self._unexpected_close_listener
                if listener is not None:
                    try:
                        listener({"error": exc, "stderr": None})
                    except Exception:
                        pass

    def _dispatch_sse_event(self, event_type: str, data: str) -> None:
        """根据 SSE 事件类型分派：``endpoint`` 事件把回调靶点写回 ``_endpoint_fut``。"""
        if not data:
            return
        stripped = data.strip()
        is_endpoint = event_type == "endpoint" or (event_type == "" and stripped.startswith("{"))
        if not is_endpoint:
            return
        try:
            uri = json.loads(stripped).get("uri")
        except (json.JSONDecodeError, ValueError):
            uri = None
        if uri and isinstance(uri, str) and uri:
            fut = self._endpoint_fut
            if fut is not None and not fut.done():
                fut.set_result(uri)
