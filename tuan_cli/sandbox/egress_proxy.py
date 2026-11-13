"""B2 收尾: 本地回环出网代理 —— 把域名强绑定放到**出网路径**上。

**为什么必须是代理，不能再加一层文本规则**

``TrustFilter`` 的全局白名单只看命令文本；前几轮 fuzz 已证明零宽字符、
ANSI-C ``$'\\x20…'``、注释换行、变量间接引用都能让文本识别失效。
bwrap / seatbelt 只有 network namespace / IP 级规则，**没有域名级过滤能力**，
所以「逐命令声明所需主机、其余一律拒绝」要真正强制，唯一可落地的位置是
子进程出网时必经的本地回环代理。

本模块是**真实可运行**的 stdlib 代理（不是预留接口）：

- ``CONNECT host:port``：按 :class:`NetworkClaim` 校验主机；声明外 → 403；
  允许 → 建立 TCP 隧道（HTTPS）。
- 明文 HTTP 绝对 URI：同样校验主机；转发请求时把 header 里的
  ``tuan-egress-sentinel-v1:<fp>`` 用 :meth:`CredentialBroker.inject_headers`
  还原成真实值 —— 这就是 CC「子进程不持密钥 / 出网代理注入」的落地。
- 子进程通过 ``env_overrides`` 拿到 ``HTTP_PROXY`` / ``HTTPS_PROXY`` /
  ``ALL_PROXY``，``NO_PROXY`` 清空，避免绕过。

**如实的技术边界（决定 catalog 仍标 partial）**

HTTPS 走 CONNECT 隧道后，代理只转发加密字节，**看不到**隧道内的
HTTP header，因此无法注入真实密钥。明文 HTTP 可以。要覆盖 HTTPS 需要
TLS 中间人 + 本地 CA 信任，那会显著扩大攻击面，本轮**不做**，也不谎称
已与 CC 的 credential masking 完整对等。

**审计只记主机名 / 端口 / 决定 / 计数**，绝不记 header 值、body 或真实凭据。
默认不启用；启用是显式行为变更（改变所有子进程的网络出口）。
"""
from __future__ import annotations

import http.client
import select
import socket
import socketserver
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from .egress import CredentialBroker, SENTINEL_PREFIX
from .egress_allowlist import NetworkClaim, claim_matches

_HOP_BY_HOP = frozenset({
    "proxy-connection", "proxy-authorization", "proxy-authenticate",
    "connection", "keep-alive", "transfer-encoding", "te", "trailer",
    "upgrade", "host", "content-length",
})


@dataclass(frozen=True)
class ProxyAuditRecord:
    """脱敏审计记录；真实值 / header / body 一律不进这里。"""

    kind: str                 # connect | plain_http | parse_error
    host: str
    port: int
    allowed: bool
    reason: str = ""
    injected_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "host": self.host, "port": self.port,
                "allowed": self.allowed, "reason": self.reason,
                "injected_count": self.injected_count}


class _ProxyHandler(socketserver.BaseRequestHandler):
    """每个连接一个线程；异常一律关闭连接并留痕，绝不静默放行。"""

    def handle(self) -> None:
        proxy: "EgressProxy" = self.server.proxy  # type: ignore[attr-defined]
        try:
            self.request.settimeout(proxy.timeout)
            fp = self.request.makefile("rb")
            line = fp.readline(65536)
            if not line:
                return
            try:
                parts = line.decode("iso-8859-1").rstrip("\r\n").split(" ")
            except UnicodeDecodeError:
                proxy._audit(ProxyAuditRecord("parse_error", "", 0, False,
                                              "请求行不可解码"))
                return
            if len(parts) < 3:
                proxy._audit(ProxyAuditRecord("parse_error", "", 0, False,
                                              "请求行格式非法"))
                self._send(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
                return
            method, target, _version = parts[0].upper(), parts[1], parts[2]
            headers = self._read_headers(fp)
            if method == "CONNECT":
                self._handle_connect(proxy, target, headers)
            elif target.startswith("http://"):
                self._handle_plain_http(proxy, fp, method, target, headers)
            else:
                proxy._audit(ProxyAuditRecord("parse_error", "", 0, False,
                                              "非绝对 URI 的代理请求已拒绝"))
                self._send(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
        except (socket.timeout, OSError, ValueError):
            proxy._audit(ProxyAuditRecord("parse_error", "", 0, False,
                                          "连接异常, 已关闭而非放行"))
        except Exception as exc:  # noqa: BLE001 - 闸门异常必须闭合
            proxy._audit(ProxyAuditRecord("parse_error", "", 0, False,
                                          f"{type(exc).__name__}"))

    @staticmethod
    def _read_headers(fp: Any) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for _ in range(256):
            raw = fp.readline(65536)
            if raw in (b"\r\n", b"\n", b""):
                break
            if b":" not in raw:
                continue
            k, v = raw.split(b":", 1)
            out[k.strip().lower().decode("iso-8859-1")] = \
                v.strip().decode("iso-8859-1")
        return out

    def _send(self, data: bytes) -> None:
        try:
            self.request.sendall(data)
        except OSError:
            pass

    def _deny(self, proxy: "EgressProxy", rec: ProxyAuditRecord) -> None:
        proxy._audit(rec)
        body = b"blocked by tuan egress allowlist\n"
        self._send(b"HTTP/1.1 403 Forbidden\r\n"
                   b"Content-Type: text/plain\r\n"
                   b"Content-Length: " + str(len(body)).encode() +
                   b"\r\nConnection: close\r\n\r\n" + body)

    def _handle_connect(self, proxy: "EgressProxy", target: str,
                        headers: Dict[str, str]) -> None:
        host, port = self._split_authority(target)
        if not host:
            self._deny(proxy, ProxyAuditRecord("connect", target[:64], 0,
                                               False, "CONNECT 目标不可解析"))
            return
        allowed = proxy.claim.allows_host(host)
        if not allowed:
            self._deny(proxy, ProxyAuditRecord(
                "connect", host, port, False,
                "CONNECT 主机不在逐命令声明内"))
            return
        proxy._audit(ProxyAuditRecord("connect", host, port, True))
        try:
            upstream = socket.create_connection((host, port), proxy.timeout)
        except OSError as exc:
            proxy._audit(ProxyAuditRecord("connect", host, port, True,
                                          f"上游连接失败: {type(exc).__name__}"))
            self._send(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            return
        self._send(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        self._relay(self.request, upstream, proxy.timeout)
        try:
            upstream.close()
        except OSError:
            pass

    def _handle_plain_http(self, proxy: "EgressProxy", fp: Any, method: str,
                           target: str, headers: Dict[str, str]) -> None:
        try:
            u = urlsplit(target)
        except ValueError:
            self._deny(proxy, ProxyAuditRecord("plain_http", "", 0, False,
                                               "绝对 URI 不可解析"))
            return
        host = u.hostname or ""
        port = u.port or 80
        if not proxy.claim.allows_host(host):
            self._deny(proxy, ProxyAuditRecord(
                "plain_http", host, port, False, "HTTP 主机不在逐命令声明内"))
            return
        body = b""
        try:
            n = int(headers.get("content-length", "0"))
            if 0 < n <= 8 * 1024 * 1024:
                body = fp.read(n)
        except (ValueError, OSError):
            body = b""

        # 真正的凭据注入点：子进程只持有 sentinel，代理在转发时还原。
        injected = proxy.broker.inject_headers(headers)
        count = sum(1 for v in headers.values()
                    if isinstance(v, str) and SENTINEL_PREFIX in v)
        fwd = {k: v for k, v in injected.items() if k not in _HOP_BY_HOP}
        fwd["Host"] = host if port == 80 else f"{host}:{port}"
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
        try:
            conn = http.client.HTTPConnection(host, port, timeout=proxy.timeout)
            conn.request(method, path, body=body or None, headers=fwd)
            resp = conn.getresponse()
            payload = resp.read()
            status = resp.status
            reason = resp.reason
            resp_headers = [(k, v) for k, v in resp.getheaders()
                            if k.lower() not in ("transfer-encoding", "connection")]
            conn.close()
        except (OSError, http.client.HTTPException) as exc:
            proxy._audit(ProxyAuditRecord("plain_http", host, port, True,
                                          f"上游失败: {type(exc).__name__}"))
            self._send(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            return
        head = f"HTTP/1.1 {status} {reason}\r\n".encode("iso-8859-1")
        for k, v in resp_headers:
            head += f"{k}: {v}\r\n".encode("iso-8859-1")
        head += b"Content-Length: " + str(len(payload)).encode() + \
                b"\r\nConnection: close\r\n\r\n"
        self._send(head + payload)
        proxy._audit(ProxyAuditRecord("plain_http", host, port, True,
                                      "", injected_count=count))

    @staticmethod
    def _split_authority(target: str) -> Tuple[str, int]:
        try:
            if ":" not in target:
                return target, 443
            host, p = target.rsplit(":", 1)
            if host.startswith("[") and host.endswith("]"):
                host = host[1:-1]
            return host, int(p)
        except (ValueError, TypeError):
            return "", 0

    @staticmethod
    def _relay(a: socket.socket, b: socket.socket, timeout: float) -> None:
        """双向转发加密隧道字节；代理不解析内容，也不注入 header。"""
        while True:
            try:
                readable, _, _ = select.select([a, b], [], [], timeout)
            except (OSError, ValueError):
                return
            if not readable:
                return
            for src in readable:
                try:
                    data = src.recv(65536)
                except OSError:
                    return
                if not data:
                    return
                dst = b if src is a else a
                try:
                    dst.sendall(data)
                except OSError:
                    return


class _ProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr: Tuple[str, int], proxy: "EgressProxy") -> None:
        self.proxy = proxy
        super().__init__(addr, _ProxyHandler)


class EgressProxy:
    """本地回环出网代理。默认不构造；显式启用才改变子进程网络出口。"""

    def __init__(self, claim: NetworkClaim, broker: Optional[CredentialBroker] = None,
                 *, host: str = "127.0.0.1", port: int = 0,
                 timeout: float = 5.0, audit_cap: int = 256) -> None:
        self.claim = claim
        self.broker = broker if broker is not None else CredentialBroker()
        # 真实转发点才有资格启用注入；默认关闭的预留接口在这里被显式打开。
        self.broker.enable_injection()
        self.timeout = float(timeout) if isinstance(timeout, (int, float)) \
            and 0 < timeout <= 120 else 5.0
        self._host = host
        self._port = port
        self._audit_log: List[Dict[str, Any]] = []
        self._audit_cap = audit_cap
        self._lock = threading.Lock()
        self._server: Optional[_ProxyServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        if self._server is None:
            return ""
        return f"http://{self._host}:{self._server.server_address[1]}"

    @property
    def running(self) -> bool:
        return self._server is not None and self._thread is not None \
            and self._thread.is_alive()

    def start(self) -> str:
        if self._server is not None:
            return self.url
        self._server = _ProxyServer((self._host, self._port), self)
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        name="tuan-egress-proxy", daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        srv, thr = self._server, self._thread
        if srv is not None:
            try:
                srv.shutdown()
                srv.server_close()
            except OSError:
                pass
        if thr is not None:
            thr.join(timeout=2.0)
        self._server = None
        self._thread = None

    def __enter__(self) -> "EgressProxy":
        self.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.stop()

    @property
    def env_overrides(self) -> Dict[str, str]:
        """注入子进程环境，强制出网经过本代理；NO_PROXY 清空防绕过。"""
        u = self.url
        if not u:
            return {}
        return {"HTTP_PROXY": u, "http_proxy": u,
                "HTTPS_PROXY": u, "https_proxy": u,
                "ALL_PROXY": u, "all_proxy": u,
                "NO_PROXY": "", "no_proxy": ""}

    def _audit(self, rec: ProxyAuditRecord) -> None:
        with self._lock:
            self._audit_log.append(rec.to_dict())
            if len(self._audit_log) > self._audit_cap:
                del self._audit_log[:-self._audit_cap]

    def audit(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(x) for x in self._audit_log]

    def __repr__(self) -> str:
        return (f"<EgressProxy running={self.running} "
                f"claim_domains={len(self.claim.required_domains)} "
                f"strict={self.claim.strict}>")
