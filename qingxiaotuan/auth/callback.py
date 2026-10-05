# -*- coding: utf-8 -*-
"""本机 OAuth 回调服务器 (127.0.0.1 + 固定端口)。

第三方 OAuth (GitHub / Apple) 需要注册精确的回调地址, 因此本项目约定
默认回调端口 8765, 回调路径 /callback; redirect_uri 可在凭证配置中覆盖。

用法::
    with LocalCallbackServer(port=8765) as cb:
        webbrowser.open(authorize_url(cb.redirect_uri))
        code = cb.wait(timeout=180)   # 用户授权后回调携带 code
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .base import AuthError

DEFAULT_CALLBACK_PORT = 8765
DEFAULT_CALLBACK_PATH = "/callback"

_SUCCESS_PAGE = (
    "<html><body style='font-family:sans-serif;text-align:center;margin-top:15%'>"
    "<h2>✓ 登录成功</h2>"
    "<p>已收到授权码, 可以关闭此页面并返回终端。</p>"
    "</body></html>"
)
_ERROR_PAGE = (
    "<html><body style='font-family:sans-serif;text-align:center;margin-top:15%'>"
    "<h2>✗ 授权失败</h2><p>{error}</p></body></html>"
)


class _CallbackHandler(BaseHTTPRequestHandler):
    """收到任意 GET 即解析 code/error 并完成回调。"""

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        code = qs.get("code", [None])[0]
        error = qs.get("error", [None])[0]
        owner = getattr(self.server, "owner", None)
        if owner is not None:
            owner._complete(code, error)
        if error:
            body = _ERROR_PAGE.format(error=error)
        else:
            body = _SUCCESS_PAGE
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return  # 静默访问日志 (回调端口不打印)


class LocalCallbackServer:
    """本地回调: 上下文管理器, 进入时启动监听, 退出时关闭。"""

    def __init__(
        self,
        port: int = DEFAULT_CALLBACK_PORT,
        path: str = DEFAULT_CALLBACK_PATH,
        timeout: float = 180.0,
    ) -> None:
        self.port = port
        self.path = path
        self.timeout = timeout
        self._result: Optional[Tuple[Optional[str], Optional[str]]] = None
        self._event = threading.Event()
        self._httpd: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def __enter__(self) -> "LocalCallbackServer":
        try:
            self._httpd = HTTPServer(("127.0.0.1", self.port), _CallbackHandler)
        except OSError as exc:
            raise AuthError(
                f"无法监听回调端口 {self.port} ({exc}); 请关闭占用该端口的程序, "
                "或在凭证配置中换用其他端口"
            ) from exc
        self._httpd.owner = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True, name="oauth-callback"
        )
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.port}{self.path}"

    def _complete(self, code: Optional[str], error: Optional[str]) -> None:
        self._result = (code, error)
        self._event.set()

    def wait(self, timeout: Optional[float] = None) -> str:
        """等待用户完成授权; 返回授权码。超时/拒绝抛 AuthError。"""
        if not self._event.wait(timeout if timeout is not None else self.timeout):
            raise AuthError(
                f"等待授权回调超时 ({int(self.timeout)}s); 请确认浏览器已完成授权"
            )
        code, error = self._result  # type: ignore[misc]
        if error:
            raise AuthError(f"授权被拒绝: {error}")
        if not code:
            raise AuthError("回调未携带授权码 (code)")
        return code
