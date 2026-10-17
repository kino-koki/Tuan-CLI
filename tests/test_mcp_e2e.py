"""MCP 端到端连通测试 —— 本地起真实进程/本地 HTTP 服务, 不连任何外部服务器。

覆盖:
- stdio 传输: MCPClient 启动本地 python MCP server 子进程, 完成
  initialize -> notifications/initialized -> tools/list -> tools/call 全协议握手与调用。
- http 传输: HttpMcpClient 对本地 mock HTTP MCP 端点完成握手 + tools/list + tools/call。
- 融合层: MultiTransportMCP 经本地 http 端点注册工具并调用 (端到端打通远程传输)。

测试中启动的本地服务全部在 fixture/teardown 中关闭, 不残留进程/端口。
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tuan_cli.tools.mcp.client import MCPClient
from tuan_cli.tools.mcp.multitransport import MultiTransportMCP

PY = sys.executable

# --------------------------------------------------------------------- stdio 本地 server 脚本
# 一个极简 JSON-RPC over stdio 的 MCP server: 暴露一个 echo 工具。
_STDIO_SERVER = r'''
import sys, json

def send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()

tools = [
    {"name": "echo", "description": "回显输入", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}},
]

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    mid = msg.get("id")
    method = msg.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "local-stdio", "version": "1.0"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}})
    elif method == "tools/call":
        params = msg.get("params", {})
        text = (params.get("arguments") or {}).get("text", "")
        send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": "ECHO:" + text}], "isError": False}})
    elif method == "shutdown":
        send({"jsonrpc": "2.0", "id": mid, "result": {}})
'''


@pytest.fixture()
def stdio_server_script(tmp_path: Path) -> Path:
    p = tmp_path / "local_stdio_server.py"
    p.write_text(_STDIO_SERVER, encoding="utf-8")
    return p


# --------------------------------------------------------------------- http 本地 mock server
class _MockMCPHTTPHandler(BaseHTTPRequestHandler):
    """极简 Streamable-HTTP MCP 端点: 按 JSON-RPC method 应答。"""

    def log_message(self, *args):  # 静默
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            req = {}
        method = req.get("method")
        mid = req.get("id")
        resp = {"jsonrpc": "2.0"}
        if method == "initialize":
            resp["result"] = {"protocolVersion": "2024-11-05", "capabilities": {},
                              "serverInfo": {"name": "local-http", "version": "1.0"}}
        elif method == "notifications/initialized":
            # 通知无需 id, 直接 200 空体
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")
            return
        elif method == "tools/list":
            resp["result"] = {"tools": [
                {"name": "ping", "description": "返回 pong",
                 "inputSchema": {"type": "object", "properties": {}}},
            ]}
        elif method == "tools/call":
            resp["result"] = {"content": [{"type": "text", "text": "pong"}],
                              "isError": False}
        elif method == "shutdown":
            resp["result"] = {}
        else:
            resp["result"] = {}
        if mid is not None:
            resp["id"] = mid
        data = json.dumps(resp, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture()
def http_mcp_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockMCPHTTPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


# --------------------------------------------------------------------- stdio e2e
def test_stdio_client_handshake_and_call(stdio_server_script: Path):
    client = MCPClient(
        name="local",
        command=PY,
        args=[str(stdio_server_script)],
        timeout=10.0,
    )
    client.start()
    try:
        tools = client.list_tools()
        names = [t.get("name") for t in tools]
        assert "echo" in names
        out = client.call_tool("echo", {"text": "hi"})
        assert "ECHO:hi" in out
    finally:
        client.stop()


def test_stdio_client_unknown_tool_and_security_deny(stdio_server_script: Path):
    from tuan_cli.tools.mcp.client import MCPSecurityPolicy

    policy = MCPSecurityPolicy(denied_tools={"echo"})
    client = MCPClient(
        name="local", command=PY, args=[str(stdio_server_script)],
        timeout=10.0, security_policy=policy,
    )
    client.start()
    try:
        # 黑名单工具应被本地安全策略拦截, 不真正发往子进程
        out = client.call_tool("echo", {"text": "x"})
        assert "安全拦截" in out or "黑名单" in out
    finally:
        client.stop()


# --------------------------------------------------------------------- http e2e
def test_multitransport_http_end_to_end(http_mcp_server: str):
    """融合层经本地 http 端点: start 连接 -> register_tools -> 调用注册后的工具。

    生产路径里远程 http server 一律经 MultiTransportMCP(同步门面) 接入, 其内部
    驱动 HttpMcpClient 的握手/发现/调用, 因此这里覆盖了 http 传输的完整链路。
    """
    from tuan_cli.tools.base import Tool
    from tuan_cli.tools.mcp.plugin import register_mcp_tool

    class _Registry:
        def __init__(self):
            self.tools = {}

        def register(self, tool: Tool):
            self.tools[tool.name] = tool

    mt = MultiTransportMCP(timeout=8.0)
    mt.start({"api": {"transport": "http", "url": http_mcp_server}})
    try:
        # 远程 server 应连接成功
        statuses = {e.name: e.status for e in mt.status()}
        assert statuses.get("api") == "connected", statuses
        reg = _Registry()
        mt.register_tools(reg, {"api": None}, register_mcp_tool)
        names = list(reg.tools.keys())
        assert names, "应至少注册一个远程工具"
        # 调用注册后的工具 handler -> 经融合层路由到本地 http server
        tool = next(iter(reg.tools.values()))
        out = tool.handler(None)
        assert "pong" in out
    finally:
        mt.shutdown()
