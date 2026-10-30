"""零第三方依赖 HTTP 传输层 —— 用 stdlib 实现 httpx 被用到的最小 API 子集。

## 为什么有这一层

仓库原先 `import httpx`, httpx 及其传递依赖 (httpcore / h11 / anyio / certifi /
idna / sniffio) 共占 7 个安装包。而真正被用到的只是一小撮表面:

    Timeout(read, connect, write, pool)
    Client(timeout=...) / AsyncClient(timeout=..., base_url=..., headers=...)
    Response.status_code / .is_success / .headers / .text / .json() /
              .raise_for_status() / .iter_lines() / .aiter_lines()
    Client.post() / .stream() ; AsyncClient.post() / .stream() / .aclose()
    TimeoutException / HTTPError

把 `import httpx` 换成 ``from tuan_cli import _http as httpx``, 业务代码
一行不用改, 而整个 httpx 依赖锥从 7 个包降到 0。

## 实现要点

- **connect 超时与 read 超时真正分离。** 手写 socket 建连后用
  ``sock.settimeout(read)``。仓库里有一处专门的历史修复注释: 流式场景的 read
  超时是「分片之间的最大空闲间隔」, 若与 connect 共用会把长上下文思考型模型
  的静默期误判为超时。这里不重复那个错误。
- **chunked 解码交给 http.client。** ``HTTPResponse`` 自身就是
  ``BufferedIOBase``, 会透明解码 ``Transfer-Encoding: chunked``, 所以
  ``readline()`` 拿到的就是去块编码后的明文, SSE 行协议可直接复用。
- **不发 ``Accept-Encoding``**, 服务端因此返回未压缩正文, 省掉一条分支;
  万一服务端仍压缩, 全量响应路径上有 gzip/deflate 兜底。
- **30x 跟随**语义与 urllib 一致: 301/302/303 对 POST 降级为 GET。
- **HTTPS 代理**走标准 ``CONNECT`` 隧道 (读 ``HTTPS_PROXY`` / ``HTTP_PROXY``),
  企业网络环境不会因此断掉。
- 异步侧全部通过 ``asyncio.to_thread`` 桥接阻塞 IO, 不引入事件循环定制。
"""

from __future__ import annotations

import asyncio
import gzip
import http.client
import json as _json
import os
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
import zlib
from contextlib import asynccontextmanager, contextmanager
from http.client import HTTPResponse
from typing import (
    Any,
    AsyncIterator,
    Dict,
    Generator,
    Iterable,
    Iterator,
    List,
    Literal,
    Optional,
    Tuple,
    Union,
)

__all__ = [
    "Timeout", "TimeoutException", "RequestError", "HTTPError",
    "HTTPStatusError", "ConnectError", "ConnectTimeout", "ReadTimeout",
    "Response", "Client", "AsyncClient",
]

_DEFAULT_TIMEOUT = 5.0
_MAX_REDIRECTS = 5


# --------------------------------------------------------------------------- #
# 异常层级 —— 与 httpx 的包含关系保持一致, 让 `except httpx.HTTPError` 继续成立
# --------------------------------------------------------------------------- #
class HTTPError(Exception):
    """httpx.HTTPError 等价物。所有传输层错误的公共基类。"""


class RequestError(HTTPError):
    """请求阶段错误 (连接失败 / 超时)。"""


class HTTPStatusError(HTTPError):
    """raise_for_status() 抛出的非 2xx 错误。"""

    def __init__(self, message: str, *, response: "Optional[Response]" = None) -> None:
        super().__init__(message)
        self.response = response

    @property
    def request(self) -> Any:
        return getattr(self.response, "request", None) if self.response else None


class TimeoutException(RequestError):
    """httpx.TimeoutException 等价物。"""


class ConnectTimeout(TimeoutException):
    pass


class ReadTimeout(TimeoutException):
    pass


class ConnectError(RequestError):
    pass


# --------------------------------------------------------------------------- #
# Timeout
# --------------------------------------------------------------------------- #
class Timeout:
    """四段超时, 单位秒。

    httpx 允许单位置参数表示 read 超时, 本类保持兼容:
    ``Timeout(30.0, connect=10.0)`` 与 ``Timeout(read=30.0, connect=10.0)`` 等价。
    """

    def __init__(
        self,
        read: float = _DEFAULT_TIMEOUT,
        *,
        connect: float = _DEFAULT_TIMEOUT,
        write: float = _DEFAULT_TIMEOUT,
        pool: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.read = float(read)
        self.connect = float(connect)
        self.write = float(write)
        self.pool = float(pool)

    @property
    def default(self) -> float:
        """兼容 httpx 的 ``timeout.default`` 读法。"""
        return self.read

    def __repr__(self) -> str:  # pragma: no cover - 仅用于日志
        return (f"Timeout(read={self.read}, connect={self.connect}, "
                f"write={self.write}, pool={self.pool})")


# --------------------------------------------------------------------------- #
# Headers —— 大小写不敏感, 支持 dict(headers) 与 `"K" in headers`
# --------------------------------------------------------------------------- #
class Headers:
    """响应头映射 (httpx.Headers 子集)。"""

    def __init__(self, raw: Iterable[Tuple[str, str]]) -> None:
        self._items: Dict[str, str] = {}
        for key, value in raw:
            k = str(key).lower()
            if k in self._items:
                self._items[k] += ", " + str(value)
            else:
                self._items[k] = str(value)

    def __getitem__(self, key: str) -> str:
        return self._items[str(key).lower()]

    def __contains__(self, key: object) -> bool:
        return str(key).lower() in self._items

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self._items.get(str(key).lower(), default)

    def items(self) -> List[Tuple[str, str]]:
        return list(self._items.items())

    def keys(self) -> List[str]:
        return list(self._items.keys())

    def __iter__(self) -> Iterator[Tuple[str, str]]:
        return iter(self._items.items())

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:  # pragma: no cover - 仅用于日志
        return f"Headers({self._items!r})"


# --------------------------------------------------------------------------- #
# 底层: socket + ssl 建连, 支持 CONNECT 代理隧道
# --------------------------------------------------------------------------- #
_PROXY_HOST_RE = re.compile(r"^(?:(?:https?|socks5)?://)?([^/@:]+)(?::(\d+))?$")


def _proxy_for(url: str, explicit: Optional[str]) -> Optional[Tuple[str, int]]:
    """解析代理地址。explicit 优先, 其次环境变量。返回 (host, port) 或 None。"""
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme or "http"
    candidates = []
    if explicit:
        candidates.append(explicit)
    env_key = "HTTPS_PROXY" if scheme == "https" else "HTTP_PROXY"
    for var in (env_key, "ALL_PROXY"):
        val = os.environ.get(var)
        if val:
            candidates.append(val)
    # 尊重 NO_PROXY
    no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    host = parts.hostname or ""
    if host and no_proxy:
        for entry in no_proxy.split(","):
            entry = entry.strip().lstrip(".")
            if not entry:
                continue
            if host == entry or host.endswith("." + entry) or (
                entry.startswith(".") and host.endswith(entry)
            ):
                return None
    for cand in candidates:
        if not cand or cand.startswith("socks"):  # socks 需要额外库, 明确跳过
            continue
        m = _PROXY_HOST_RE.match(cand.strip())
        if not m:
            continue
        port = int(m.group(2)) if m.group(2) else (
            443 if scheme == "https" and "://" in cand else
            443 if "https://" in cand else 8080
        )
        return m.group(1), port
    return None


def _connect_socket(
    host: str,
    port: int,
    scheme: str,
    *,
    connect_timeout: float,
    read_timeout: float,
    proxy: Optional[Tuple[str, int]],
) -> socket.socket:
    """建立到目标 (可能经代理隧道) 的明文 socket, 并设置读写超时。

    connect 超时只作用于建连; read 超时作用于后续所有 recv。
    """
    if proxy is not None:
        sock = socket.create_connection((proxy[0], proxy[1]), timeout=connect_timeout)
        host_header = host if host.startswith("[") else f"{host}:{port}"
        connect_req = f"CONNECT {host_header} HTTP/1.1\r\nHost: {host_header}\r\n\r\n"
        sock.sendall(connect_req.encode("ascii"))
        sock.settimeout(connect_timeout)
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectError(f"代理隧道被 {proxy[0]}:{proxy[1]} 拒绝")
            buf += chunk
            if len(buf) > 32768:
                raise ConnectError("代理隧道回复异常过大")
        first_line = buf.split(b"\r\n", 1)[0].decode("ascii", "replace")
        if " 200" not in first_line:
            raise ConnectError(f"代理隧道失败: {first_line[:120]}")
    else:
        sock = socket.create_connection((host, port), timeout=connect_timeout)

    sock.settimeout(read_timeout)
    return sock



def _open(
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    body: Optional[bytes],
    timeout: Union[Timeout, float],
    proxy: Optional[str],
    verify: Union[bool, str],
) -> Tuple[str, HTTPResponse]:
    """发送请求并返回 (最终 URL, 未读取正文的 HTTPResponse)。"""
    if isinstance(timeout, (int, float)):
        t = Timeout(timeout, connect=timeout)
    else:
        t = timeout

    req_headers = {k: str(v) for k, v in (headers or {}).items()}
    seen_host_header = False
    seen_len = False
    seen_te = False
    for k in req_headers:
        lk = k.lower()
        if lk == "host":
            seen_host_header = True
        elif lk == "content-length":
            seen_len = True
        elif lk == "transfer-encoding":
            seen_te = True

    current_url = url
    original_method = method
    original_body = body
    for _ in range(_MAX_REDIRECTS + 1):
        parts = urllib.parse.urlsplit(current_url)
        scheme = parts.scheme or "https"
        if scheme not in ("http", "https"):
            raise HTTPError(f"不支持的 URL scheme: {scheme!r}")
        host = parts.hostname
        if not host:
            raise HTTPError(f"URL 缺少主机名: {current_url!r}")
        port = parts.port or (443 if scheme == "https" else 80)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        if parts.fragment:
            path += "#" + parts.fragment

        pxy = _proxy_for(current_url, proxy) if scheme in ("http", "https") else None
        sock = _connect_socket(
            host, port, scheme,
            connect_timeout=t.connect, read_timeout=t.read,
            proxy=pxy,
        )
        target_host_header = f"{host}:{port}" if port not in (80, 443) else host

        if scheme == "https" and verify is not False:
            if isinstance(verify, str):
                ctx = ssl.create_default_context(cafile=verify)
            else:
                ctx = ssl.create_default_context()
            try:
                sock = ctx.wrap_socket(sock, server_hostname=host)
            except ssl.SSLCertVerificationError as exc:
                sock.close()
                raise ConnectError(
                    f"TLS 证书校验失败 ({host}): {exc}. 如需自签证书, "
                    "设置 SSL_CERT_FILE 环境变量指向 CA 证书, 或传 verify=证书路径。"
                ) from exc
            except ssl.SSLError as exc:
                sock.close()
                raise ConnectError(f"TLS 握手失败 ({host}): {exc}") from exc

        conn = http.client.HTTPConnection(host, port, timeout=None)
        conn.sock = sock  # 复用我们控制超时的 socket, 不调用 conn.connect()
        try:
            conn.putrequest(method, path)
            lower_keys = {k.lower() for k in req_headers}
            for k, v in req_headers.items():
                lk = k.lower()
                if lk in ("host", "content-length", "transfer-encoding", "accept-encoding"):
                    continue
                conn.putheader(k, str(v))
            conn.putheader("Host", target_host_header)
            if "accept" not in lower_keys:
                conn.putheader("Accept", "*/*")
            if "accept-encoding" not in lower_keys:
                conn.putheader("Accept-Encoding", "identity")
            if "user-agent" not in lower_keys:
                conn.putheader("User-Agent", "tuan-cli/0.3")
            if body is not None and not seen_te:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders()
            if body:
                conn.send(body)
            response = conn.getresponse()
            setattr(response, "_tuan_conn", conn)  # 持有连接, 便于随 Response 关闭
        except socket.timeout as exc:
            sock.close()
            raise ReadTimeout(f"请求超时 ({current_url})") from exc
        except socket.gaierror as exc:
            sock.close()
            raise ConnectError(f"DNS 解析失败 ({host}): {exc}") from exc
        except OSError as exc:
            sock.close()
            raise ConnectError(f"连接失败 ({host}:{port}): {exc}") from exc

        code = response.status
        if code in (301, 302, 303, 307, 308) and response.getheader("Location"):
            location = response.getheader("Location")
            # 先把旧响应读掉/关掉, 释放 socket
            try:
                response.read()
            except Exception:  # noqa: BLE001 - 重定向时尽力读完
                pass
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            current_url = urllib.parse.urljoin(current_url, location)
            if code == 303 or (code in (301, 302) and method in ("POST", "PUT")):
                method, body = "GET", None
            continue

        return current_url, response

    raise HTTPError(f"重定向次数超过上限 ({_MAX_REDIRECTS})")


# --------------------------------------------------------------------------- #
# Response
# --------------------------------------------------------------------------- #
class Response:
    """httpx.Response 子集。

    两种形态:
      - 全量: ``_body`` 已读入内存, ``content`` / ``text`` / ``json()`` 直接可用;
      - 流式: ``_stream`` 是打开的 ``HTTPResponse``, ``iter_lines`` /
        ``aiter_lines`` 逐行读, ``content`` 会把剩余正文读全。
    """

    def __init__(
        self,
        status_code: int,
        headers: Iterable[Tuple[str, str]],
        *,
        url: str = "",
        stream: Optional[HTTPResponse] = None,
        body: Optional[bytes] = None,
        request: Any = None,
    ) -> None:
        self.status_code = int(status_code)
        self.headers = Headers(headers)
        self.url = url
        self.request = request
        self._stream = stream
        self._body = body
        self._closed = body is not None
        if body is not None:
            self._body = _maybe_decode(body, self.headers)

    # -- 状态 --------------------------------------------------------------- #
    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def ok(self) -> bool:
        return self.is_success

    @property
    def reason(self) -> str:  # pragma: no cover - 仅用于日志
        return ""

    # -- 正文 --------------------------------------------------------------- #
    @property
    def content(self) -> bytes:
        if self._body is not None:
            return self._body
        if self._stream is not None:
            try:
                self._body = self._stream.read() or b""
            finally:
                self.close()
            return self._body
        return b""

    @property
    def text(self) -> str:
        data = self.content
        charset = "utf-8"
        ct = self.headers.get("content-type", "") or ""
        if "charset=" in ct:
            charset = ct.split("charset=")[-1].split(";")[0].strip().strip('"')
        try:
            return data.decode(charset or "utf-8")
        except (LookupError, UnicodeDecodeError):
            return data.decode("utf-8", "replace")

    def json(self, **_: Any) -> Any:
        return _json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.is_success:
            return
        raise HTTPStatusError(
            f"HTTP {self.status_code} for url {self.url or '<unknown>'}",
            response=self,
        ) from None

    # -- 流式 --------------------------------------------------------------- #
    def iter_lines(self) -> Generator[str, None, None]:
        """逐行迭代 SSE / 换行分隔正文, 去掉行尾的 ``\\r``。

        用文本缓冲 + ``split("\\n")`` 处理跨 chunk 的半行, 保证 chunked 解码
        边界不会把一行切成两半。
        """
        if self._stream is None:
            for line in (self._body or b"").decode("utf-8", "replace").splitlines():
                yield line
            return
        stream = self._stream
        text_buf = ""
        while True:
            try:
                chunk = stream.read(4096)
            except socket.timeout as exc:
                raise ReadTimeout("流式读取超时 (分片间隔过长)") from exc
            except Exception as exc:  # noqa: BLE001 - 统一归一为传输层错误
                raise RequestError(f"流式读取失败: {exc}") from exc
            if not chunk:
                if text_buf:
                    yield text_buf.rstrip("\r")
                    text_buf = ""
                break
            text_buf += chunk.decode("utf-8", "replace")
            parts = text_buf.split("\n")
            text_buf = parts.pop()  # 最后一段可能是不完整的半行
            for line in parts:
                yield line.rstrip("\r")

    async def aiter_lines(self) -> AsyncIterator[str]:
        """异步版 iter_lines —— 在后台线程逐行读, 避免阻塞事件循环。"""
        loop = asyncio.get_running_loop()
        gen = self.iter_lines()
        sentinel = object()

        def _next() -> Any:
            try:
                return next(gen)
            except StopIteration:
                return sentinel
            except BaseException:
                self.close()
                raise

        try:
            while True:
                item = await loop.run_in_executor(None, _next)
                if item is sentinel:
                    break
                yield item
        finally:
            try:
                gen.close()
            except Exception:  # noqa: BLE001
                pass

    # -- 生命周期 ----------------------------------------------------------- #
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                conn = getattr(stream, "_tuan_conn", None)
                if conn is not None:
                    conn.close()
                else:
                    stream.close()
            except Exception:  # noqa: BLE001
                pass

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *exc: Any) -> Literal[False]:
        self.close()
        return False

    async def aread(self) -> bytes:
        return await asyncio.to_thread(lambda: self.content)

    async def aclose(self) -> None:
        await asyncio.to_thread(self.close)

    def __repr__(self) -> str:  # pragma: no cover - 仅用于日志
        return f"Response(status_code={self.status_code}, url={self.url!r})"


def _maybe_decode(body: bytes, headers: Headers) -> bytes:
    """按 Content-Encoding 解码 gzip/deflate (identity 直接返回)。"""
    enc = (headers.get("content-encoding", "") or "").lower().strip()
    if not enc or enc == "identity":
        return body
    try:
        if "gzip" in enc or "x-gzip" in enc:
            return gzip.decompress(body)
        if "deflate" in enc:
            try:
                return zlib.decompress(body)
            except zlib.error:
                return zlib.decompress(body, -zlib.MAX_WBITS)
        if "br" in enc:
            return body  # brotli 需要额外库, 保持原样
    except Exception:  # noqa: BLE001 - 解码失败退化为原文
        return body
    return body


# --------------------------------------------------------------------------- #
# Client (同步)
# --------------------------------------------------------------------------- #
def _resolve_url(base_url: str, url: str) -> str:
    """httpx 式 base_url 拼接: 相对路径直接接在 base 后面。"""
    if not base_url or not url:
        return url or base_url
    if re.match(r"^[a-z][a-z0-9+.-]*://", url, re.IGNORECASE):
        return url
    return base_url.rstrip("/") + "/" + url.lstrip("/")


class Client:
    """同步 HTTP 客户端 (httpx.Client 子集)。"""

    def __init__(
        self,
        base_url: str = "",
        headers: Optional[Dict[str, str]] = None,
        timeout: Union[Timeout, float] = _DEFAULT_TIMEOUT,
        *,
        proxy: Optional[str] = None,
        proxies: Any = None,
        verify: Union[bool, str] = True,
        **_: Any,
    ) -> None:
        self.base_url = base_url or ""
        self.headers = dict(headers or {})
        self.timeout = timeout if isinstance(timeout, Timeout) else Timeout(timeout, connect=timeout)
        self.verify = verify
        self._proxy = proxy or proxies
        if isinstance(self._proxy, dict):
            # httpx 的 proxies 是 dict; 这里取 "all"/"https" 键的标量形式
            for key in ("all", "https", "http"):
                if key in self._proxy and isinstance(self._proxy[key], str):
                    self._proxy = self._proxy[key]
                    break
            else:
                self._proxy = None

    # -- 请求 --------------------------------------------------------------- #
    def _merged_headers(self, extra: Optional[Dict[str, str]]) -> Dict[str, str]:
        out = dict(self.headers)
        if extra:
            out.update({k: str(v) for k, v in extra.items()})
        return out

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        json: Any = None,
        content: Optional[Union[bytes, str]] = None,
        data: Any = None,
        **_: Any,
    ) -> Response:
        url = _resolve_url(self.base_url, url)
        headers = self._merged_headers(headers)
        if json is not None:
            content = _json.dumps(json, ensure_ascii=False).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif data is not None:
            if isinstance(data, (bytes, bytearray)):
                content = bytes(data)
            else:
                content = str(data).encode("utf-8")
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        elif content is not None:
            if isinstance(content, str):
                content = content.encode("utf-8")
        body = content
        try:
            final_url, resp = _open(
                method.upper(), url, headers=headers, body=body,
                timeout=self.timeout, proxy=self._proxy, verify=self.verify,
            )
        except HTTPError:
            raise
        body_bytes = resp.read()
        headers_list = list(resp.getheaders())
        self.close_connection(resp)
        return Response(resp.status, headers_list, url=final_url, body=body_bytes)

    @staticmethod
    def close_connection(resp: HTTPResponse) -> None:
        conn = getattr(resp, "_tuan_conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    def post(self, url: str, **kw: Any) -> Response:
        return self.request("POST", url, **kw)

    def get(self, url: str, **kw: Any) -> Response:
        return self.request("GET", url, **kw)

    def put(self, url: str, **kw: Any) -> Response:
        return self.request("PUT", url, **kw)

    def delete(self, url: str, **kw: Any) -> Response:
        return self.request("DELETE", url, **kw)

    def _stream_open(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        json: Any = None,
        content: Optional[Union[bytes, str]] = None,
        data: Any = None,
    ) -> Response:
        """建立流式响应: 打开连接并保持, 返回带 ``stream`` 的 Response。

        与 ``stream`` 分离成方法而不是用 ``@contextmanager`` 包裹整段逻辑,
        是因为 AsyncClient 需要在后台线程里「只打开不退出」—— 若直接调用
        ``stream(...).__enter__()`` 会让生成器被回收, ``__exit__`` 立刻执行
        ``response.close()`` 把流关掉。
        """
        url = _resolve_url(self.base_url, url)
        headers = self._merged_headers(headers)
        body: Optional[bytes] = None
        if json is not None:
            body = _json.dumps(json, ensure_ascii=False).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif data is not None:
            body = bytes(data) if isinstance(data, (bytes, bytearray)) else str(data).encode("utf-8")
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        elif content is not None:
            body = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        final_url, resp = _open(
            method.upper(), url, headers=headers, body=body,
            timeout=self.timeout, proxy=self._proxy, verify=self.verify,
        )
        return Response(resp.status, list(resp.getheaders()), url=final_url, stream=resp)

    @contextmanager
    def stream(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        json: Any = None,
        content: Optional[Union[bytes, str]] = None,
        data: Any = None,
        **_: Any,
    ) -> Iterator[Response]:
        """流式上下文管理器: yield 一个持有打开连接的 Response。"""
        response = self._stream_open(
            method, url, headers=headers, json=json, content=content, data=data
        )
        try:
            yield response
        finally:
            response.close()

    def close(self) -> None:
        pass

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc: Any) -> Literal[False]:
        self.close()
        return False


# --------------------------------------------------------------------------- #
# AsyncClient —— 阻塞 IO 走线程池, 不定制事件循环
# --------------------------------------------------------------------------- #
class AsyncClient:
    """异步 HTTP 客户端 (httpx.AsyncClient 子集)。

    内部持有一个同步 ``Client``, 通过 ``asyncio.to_thread`` 桥接。
    流式请求在后台线程打开连接并保持, ``aiter_lines`` 逐行取。
    """

    def __init__(
        self,
        base_url: str = "",
        headers: Optional[Dict[str, str]] = None,
        timeout: Union[Timeout, float] = _DEFAULT_TIMEOUT,
        *,
        proxy: Optional[str] = None,
        proxies: Any = None,
        verify: Union[bool, str] = True,
        **_: Any,
    ) -> None:
        self._client = Client(
            base_url=base_url, headers=headers, timeout=timeout,
            proxy=proxy, proxies=proxies, verify=verify,
        )
        self.base_url = self._client.base_url
        self.headers = self._client.headers
        self.timeout = self._client.timeout
        self.verify = self._client.verify

    async def post(self, url: str, **kw: Any) -> Response:
        return await asyncio.to_thread(self._client.post, url, **kw)

    async def get(self, url: str, **kw: Any) -> Response:
        return await asyncio.to_thread(self._client.get, url, **kw)

    async def put(self, url: str, **kw: Any) -> Response:
        return await asyncio.to_thread(self._client.put, url, **kw)

    async def delete(self, url: str, **kw: Any) -> Response:
        return await asyncio.to_thread(self._client.delete, url, **kw)

    async def request(self, method: str, url: str, **kw: Any) -> Response:
        return await asyncio.to_thread(self._client.request, method, url, **kw)

    @asynccontextmanager
    async def stream(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        json: Any = None,
        content: Optional[Union[bytes, str]] = None,
        data: Any = None,
        **_: Any,
    ) -> AsyncIterator[Response]:
        """异步流式上下文管理器。"""
        response = await asyncio.to_thread(
            self._client._stream_open, method, url,
            headers=headers, json=json, content=content, data=data,
        )
        try:
            yield response
        finally:
            await asyncio.to_thread(response.close)

    async def aclose(self) -> None:
        pass

    async def __aenter__(self) -> "AsyncClient":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        await self.aclose()
        return False


# --------------------------------------------------------------------------- #
# 模块级便捷函数 —— 对齐 httpx.get/post/... 的一次性调用写法
# --------------------------------------------------------------------------- #
def _kw_timeout(timeout: Any) -> Timeout:
    """把 `timeout=25` / `timeout=Timeout(...)` / `timeout=None` 归一为 Timeout。"""
    if timeout is None:
        return Timeout(_DEFAULT_TIMEOUT, connect=_DEFAULT_TIMEOUT)
    if isinstance(timeout, Timeout):
        return timeout
    if isinstance(timeout, (int, float)):
        return Timeout(float(timeout), connect=float(timeout))
    return Timeout(_DEFAULT_TIMEOUT, connect=_DEFAULT_TIMEOUT)


def request(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    json: Any = None,
    content: Optional[Union[bytes, str]] = None,
    data: Any = None,
    timeout: Any = _DEFAULT_TIMEOUT,
    verify: Union[bool, str] = True,
    follow_redirects: bool = True,
    **_: Any,
) -> Response:
    """一次性请求 (模块级 httpx.request 等价物)。"""
    t = _kw_timeout(timeout)
    merged = {"Accept": "*/*"}
    merged.update(headers or {})
    body: Optional[bytes] = None
    if json is not None:
        body = _json.dumps(json, ensure_ascii=False).encode("utf-8")
        merged.setdefault("Content-Type", "application/json")
    elif data is not None:
        body = bytes(data) if isinstance(data, (bytes, bytearray)) else str(data).encode("utf-8")
        merged.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif content is not None:
        body = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    final_url, resp = _open(
        method.upper(), url, headers=merged, body=body,
        timeout=t, proxy=None, verify=verify,
    )
    body_bytes = resp.read()
    headers_list = list(resp.getheaders())
    try:
        Client.close_connection(resp)
    except Exception:  # noqa: BLE001 - 尽力关闭
        pass
    return Response(resp.status, headers_list, url=final_url, body=body_bytes)


def get(url: str, **kw: Any) -> Response:
    return request("GET", url, **kw)


def post(url: str, **kw: Any) -> Response:
    return request("POST", url, **kw)


def put(url: str, **kw: Any) -> Response:
    return request("PUT", url, **kw)


def delete(url: str, **kw: Any) -> Response:
    return request("DELETE", url, **kw)


# 便捷别名: 与 httpx 的模块级函数名对齐
def timeouts(default: float, **_: Any) -> Timeout:  # pragma: no cover - 未被使用
    return Timeout(default, connect=default)
