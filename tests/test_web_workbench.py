# -*- coding: utf-8 -*-
"""Web 工作台增强能力测试: 文件树 / Diff / 上下文 / MCP / 安全详情 / shell / fork / 审批 / i18n。

覆盖本轮新增的右侧工作面板与安全呈现, 以及"无缝升级"约束
(旧接口行为不变, 新能力为纯增量)。
"""
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from tuan_cli.web import server as ws_mod
from tuan_cli.web.server import WebServer, is_loopback, non_loopback_warning


class _FakeAgent:
    def __init__(self):
        self.messages = []

    def run(self, user_input, stream=True, on_token=None, on_tool=None,
            on_tool_result=None, on_reason=None, on_error=None):
        if on_token:
            on_token("ok")
        return "ok"

    def cancel(self):
        pass


@pytest.fixture()
def server(tmp_path):
    ws_mod._SESSIONS.clear()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    srv = WebServer(kernel=None, workspace=str(tmp_path), port=0)
    srv.set_agent_factory(_FakeAgent)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    for _ in range(50):
        if srv._httpd is not None:
            break
        time.sleep(0.05)
    yield srv
    if srv._httpd is not None:
        try:
            srv._httpd.shutdown()
        except Exception:  # noqa: BLE001
            pass
        srv._httpd.server_close()
    ws_mod._SESSIONS.clear()


def _get(url, expect_error=False):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if expect_error:
            return e.read().decode("utf-8")
        raise


def _getj(url, expect_error=False):
    return json.loads(_get(url, expect_error))


def _post(url, body, expect_error=False):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if expect_error:
            return json.loads(e.read().decode("utf-8"))
        raise


def _url(server, path):
    return f"http://127.0.0.1:{server.port}{path}"


# ---------------------------------------------------------------- 绑定安全
def test_is_loopback_detection():
    assert is_loopback("127.0.0.1")
    assert is_loopback("127.0.0.5")
    assert is_loopback("::1")
    assert is_loopback("localhost")
    assert is_loopback("")
    assert not is_loopback("0.0.0.0")
    assert not is_loopback("192.168.1.10")


def test_non_loopback_warning_mentions_no_auth():
    w = non_loopback_warning("0.0.0.0", 8090)
    assert "0.0.0.0" in w and "没有鉴权" in w


def test_server_defaults_to_loopback(tmp_path):
    srv = WebServer(kernel=None, workspace=str(tmp_path), port=0)
    assert srv.host == "127.0.0.1"
    assert srv.insecure_binding is False


def test_server_flags_insecure_binding(tmp_path):
    srv = WebServer(kernel=None, workspace=str(tmp_path), host="0.0.0.0", port=0)
    assert srv.insecure_binding is True


# ---------------------------------------------------------------- 文件树
def test_files_lists_workspace(server):
    j = _getj(_url(server, "/api/files?path="))
    assert j["ok"]
    names = {e["name"] for e in j["entries"]}
    assert "src" in names and "README.md" in names
    src = [e for e in j["entries"] if e["name"] == "src"][0]
    assert src["dir"] is True


def test_files_subdirectory(server):
    j = _getj(_url(server, "/api/files?path=src"))
    assert j["ok"]
    assert {e["name"] for e in j["entries"]} == {"main.py"}


def test_files_rejects_traversal(server):
    """路径穿越必须被拒绝 (接口只服务本工作区)。"""
    assert _getj(_url(server, "/api/files?path=../"), expect_error=True)["ok"] is False
    assert _getj(_url(server, "/api/files?path=../../"), expect_error=True)["ok"] is False


def test_file_read_and_guard(server):
    j = _getj(_url(server, "/api/file?path=README.md"))
    assert j["ok"] and "# demo" in j["content"] and j["binary"] is False
    assert _getj(_url(server, "/api/file?path=../../etc/passwd"), expect_error=True)["ok"] is False
    assert _getj(_url(server, "/api/file?path=nope.txt"), expect_error=True)["ok"] is False


# ---------------------------------------------------------------- 上下文 / MCP / 安全
def test_context_info_shape(server):
    j = _getj(_url(server, "/api/context"))
    assert j["ok"] and isinstance(j["window"], int) and j["window"] > 0
    assert "sessions" in j and "total_est_tokens" in j


def test_mcp_status_shape(server):
    j = _getj(_url(server, "/api/mcp"))
    assert j["ok"] and isinstance(j["servers"], list)


def test_security_detail_has_gates(server):
    """安全详情必须给出闸门清单 (把引擎真实结构呈现出来)。"""
    j = _getj(_url(server, "/api/security"))
    assert j["ok"]
    labels = [g["label"] for g in j["gates"]]
    assert len(labels) >= 4
    assert any("红线" in x for x in labels)
    assert "recent" in j


def test_diff_endpoint(server):
    j = _getj(_url(server, "/api/diff"))
    assert j["ok"] and isinstance(j["diff"], str)


# ---------------------------------------------------------------- shell (! 执行)
def test_shell_benign_runs(server):
    j = _post(_url(server, "/api/shell"), {"command": "echo tuan-web-ok"})
    assert j["ok"] and j["needs_approval"] is False
    assert "tuan-web-ok" in j["output"]


def test_shell_dangerous_requires_approval(server):
    """高危命令不得直接执行 —— 必须先回审批, 且带上引擎的判定信息。"""
    j = _post(_url(server, "/api/shell"), {"command": "rm -rf /"})
    assert j["ok"] and j["needs_approval"] is True
    v = j["verdict"]
    assert v["risk"] in ("critical", "high") and v["block"] is True
    assert v["reasons"] and isinstance(v["blast_radius"], dict)


def test_shell_approved_executes(server):
    j = _post(_url(server, "/api/shell"), {"command": "echo approved-ok", "approved": True})
    assert j["ok"] and "approved-ok" in j["output"]


def test_shell_empty_rejected(server):
    j = _post(_url(server, "/api/shell"), {"command": "   "}, expect_error=True)
    assert j["ok"] is False


# ---------------------------------------------------------------- fork / 审批
def test_fork_session_copies_history(server):
    # 直接注入一条源会话 (走内部结构, 避免依赖 SSE 解析)
    with ws_mod._SESSIONS_LOCK:
        ws_mod._SESSIONS["src1"] = {"id": "src1", "title": "原始会话", "created": 1,
                                    "messages": [{"role": "user", "content": "a"},
                                                 {"role": "assistant", "content": "b"}],
                                    "agent": None, "lock": threading.Lock()}
    j = _post(_url(server, "/api/sessions/fork"), {"session": "src1"})
    assert j["ok"] and j["id"] != "src1" and j["messages"] == 2
    with ws_mod._SESSIONS_LOCK:
        assert "src1" in ws_mod._SESSIONS                      # 原会话保留
        new = ws_mod._SESSIONS[j["id"]]
    assert new["forked_from"] == "src1"
    assert len(new["messages"]) == 2
    assert new["messages"][0]["content"] == "a"


def test_fork_missing_session(server):
    assert _post(_url(server, "/api/sessions/fork"), {"session": "nope"}, expect_error=True)["ok"] is False


def test_fork_upto_truncates(server):
    with ws_mod._SESSIONS_LOCK:
        ws_mod._SESSIONS["src2"] = {"id": "src2", "title": "t", "created": 1,
                                    "messages": [{"role": "user", "content": str(i)} for i in range(5)],
                                    "agent": None, "lock": threading.Lock()}
    j = _post(_url(server, "/api/sessions/fork"), {"session": "src2", "upto": 1})
    assert j["ok"] and j["messages"] == 2


def test_resolve_approval_roundtrip(server):
    """审批回填: allow 置真, 未知 id 返回 False。"""
    ev = threading.Event()
    with ws_mod._APPROVALS_LOCK:
        ws_mod._APPROVALS["rq1"] = {"event": ev, "result": False}
    assert server.resolve_approval("rq1", "allow") is True
    assert ev.is_set()
    with ws_mod._APPROVALS_LOCK:
        assert ws_mod._APPROVALS["rq1"]["result"] is True
        ws_mod._APPROVALS.pop("rq1", None)
    assert server.resolve_approval("nope", "allow") is False


def test_ask_approval_fails_closed_without_ui(server):
    """无 UI 上下文 (非 chat 线程) 时审批必须 fail-closed 拒绝。"""
    assert server._ask_approval("rm -rf /") is False


# ---------------------------------------------------------------- i18n / 前端
def test_info_exposes_i18n(server):
    j = _getj(_url(server, "/api/info"))
    assert j["ok"] and isinstance(j.get("i18n"), dict)
    assert "web.new_session" in j["i18n"]
    assert "insecure_binding" in j


def test_web_locale_complete_across_languages():
    """10 语言都必须提供全部 web.* 键 (对外宣称 10 语言本地化)。"""
    import importlib

    from tuan_cli.i18n import LANGUAGES

    ref = None
    for code in LANGUAGES:
        mod = importlib.import_module("tuan_cli.i18n.locales." + code.replace("-", "_"))
        keys = {k for k in mod.TRANSLATIONS if k.startswith("web.")}
        assert keys, f"{code} 缺 web.* 键"
        if ref is None:
            ref = keys
        else:
            assert keys == ref, f"{code} 的 web.* 键与 {LANGUAGES[0]} 不一致"


def test_frontend_has_workbench_features(server):
    html = _get(_url(server, "/"))
    for token in ("id=\"rpanel\"", "loadFiles", "loadDiff", "loadCtx", "loadMcp", "loadSec",
                  "updateMention", "runShell", "forkSession", "showApproval",
                  "data-i18n=\"web.tab_sec\"", "<table>"):
        assert token in html, f"前端缺: {token}"


def test_frontend_markdown_table_renderer(server):
    html = _get(_url(server, "/"))
    assert "thead" in html and "tbody" in html
    assert "|[" in html  # 表格分隔行正则


def test_plugins_endpoint_lists_tools_and_plugins(server):
    """可视化插件面板数据: 工具 + 内核插件, 且都带 enabled 状态。"""
    j = _getj(_url(server, "/api/plugins"))
    assert j["ok"]
    kinds = {g["kind"] for g in j["groups"]}
    assert kinds == {"tool", "plugin"}
    for g in j["groups"]:
        assert "title" in g
        for it in g["items"]:
            assert "name" in it and "enabled" in it


def test_plugin_toggle_hotplug(server):
    """工具热插拔: 关掉即进 disabled 集合 (Agent 侧 exclude_tools), 再开恢复。"""
    j = _getj(_url(server, "/api/plugins"))
    tools = [g for g in j["groups"] if g["kind"] == "tool"][0]["items"]
    if not tools:
        pytest.skip("无可用工具")
    name = tools[0]["name"]

    r = _post(_url(server, "/api/plugins/toggle"), {"kind": "tool", "name": name, "enabled": False})
    assert r["ok"] and r["enabled"] is False
    assert name in server._disabled_tools

    r2 = _post(_url(server, "/api/plugins/toggle"), {"kind": "tool", "name": name, "enabled": True})
    assert r2["ok"] and name not in server._disabled_tools


def test_plugin_toggle_rejects_unknown(server):
    r = _post(_url(server, "/api/plugins/toggle"),
              {"kind": "nope", "name": "x", "enabled": True}, expect_error=True)
    assert r["ok"] is False


def test_plugin_toggle_unknown_plugin_name(server):
    """kernel=None (测试双) 时应给出明确失败而非抛异常。"""
    r = _post(_url(server, "/api/plugins/toggle"),
              {"kind": "plugin", "name": "nope", "enabled": False}, expect_error=True)
    assert r["ok"] is False and "error" in r


def test_frontend_hero_layout(server):
    """Kimi 式空状态: 粒子在上、输入框居中 (body.hero 驱动)。"""
    html = _get(_url(server, "/"))
    assert "body.hero" in html
    assert "classList.add('hero')" in html
    assert "classList.remove('hero')" in html


def test_frontend_particles_are_fine_grained(server):
    """粒子应细砂化 (半径小、采样密), 不再是粗颗粒。"""
    html = _get(_url(server, "/"))
    assert "r:0.5+Math.random()*0.8" in html   # 半径 0.5~1.3px
    assert "step=3" in html                    # 采样步长 3 (更密)


def test_frontend_plugin_panel(server):
    html = _get(_url(server, "/"))
    assert 'data-tab="plugins"' in html
    assert "function loadPlugins" in html
    assert "/api/plugins/toggle" in html
    assert 'class="sw' in html  # 开关样式


def test_share_generates_standalone_html(server):
    """会话分享: 生成自包含静态 HTML (无 JS / 无鉴权信息, 离线可读)。"""
    with ws_mod._SESSIONS_LOCK:
        ws_mod._SESSIONS["sh1"] = {"id": "sh1", "title": "分享测试", "created": 1,
                                   "messages": [
                                       {"role": "user", "content": "帮我写个函数"},
                                       {"role": "assistant", "content": "# 已完成\n\n```python\nprint(1)\n```",
                                        "tools": [{"name": "write_file", "args": "{}", "out": "ok"}]}],
                                   "agent": None, "lock": threading.Lock()}
    html = _get(_url(server, "/api/share?session=sh1"))
    assert "<!DOCTYPE html>" in html
    assert "分享测试" in html and "帮我写个函数" in html
    assert "print(1)" in html and "write_file" in html
    assert "<script" not in html.lower()          # 静态快照, 不带任何可执行脚本
    assert "TUAN 会话分享" in html


def test_share_missing_session(server):
    assert _getj(_url(server, "/api/share?session=nope"), expect_error=True)["ok"] is False


def test_sessions_list_includes_fork_relation(server):
    """分支可视化数据源: 列表必须带 forked_from。"""
    with ws_mod._SESSIONS_LOCK:
        ws_mod._SESSIONS["p1"] = {"id": "p1", "title": "父", "created": 1,
                                  "messages": [], "agent": None, "lock": threading.Lock()}
        ws_mod._SESSIONS["c1"] = {"id": "c1", "title": "子", "created": 2,
                                  "messages": [], "agent": None, "lock": threading.Lock(),
                                  "forked_from": "p1"}
    j = _getj(_url(server, "/api/sessions"))
    m = {s["id"]: s for s in j["sessions"]}
    assert m["c1"]["forked_from"] == "p1"
    assert m["p1"]["forked_from"] is None


def test_frontend_share_and_branch_ui(server):
    html = _get(_url(server, "/"))
    assert "/api/share?session=" in html          # 分享入口
    assert "forked_from" in html                  # 分支标记


def test_render_history_hides_welcome(server):
    """重开有历史的会话时必须隐藏欢迎屏。

    回归: `clearMessages()` 按设计保留 `#welcome` 之后, `renderHistory` 漏了
    `hideWelcome()` —— 消息被追加进去而粒子 canvas 仍在占位, 叠在对话上方,
    观感"一坨大的"。现在 renderHistory 显式隐藏, 且 msgEl 里有兜底。
    """
    html = _get(_url(server, "/"))
    seg = html.split("function renderHistory")[1][:600]
    assert "hideWelcome();" in seg, "renderHistory 必须隐藏欢迎屏"
    seg2 = html.split("function msgEl")[1][:300]
    assert "welcomeEl.style.display" in seg2, "msgEl 应有隐藏欢迎屏的兜底"


def test_frontend_js_parses():
    """前端主脚本必须语法正确。

    一处字符串错误就会让**整个 IIFE 解析失败 → 页面所有交互全部失效**
    (曾因 i18n 替换吃掉收尾引号, 表现为"深浅色切换无反应"。
    整页 JS 静默不执行, 排查成本很高, 故用真实 JS 引擎钉死。)
    """
    import re
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    from tuan_cli.web.frontend import FRONTEND_HTML

    blocks = re.findall(r"<script>(.*?)</script>", FRONTEND_HTML, re.S)
    assert blocks, "前端应含 <script>"
    main = max(blocks, key=len)

    node = shutil.which("node")
    if not node:
        for cand in (r"D:\node.exe", "/usr/bin/node", "/usr/local/bin/node"):
            if Path(cand).exists():
                node = cand
                break
    if not node:
        pytest.skip("node 不可用, 跳过 JS 语法校验")

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(main)
        tmp = f.name
    try:
        p = subprocess.run([node, "--check", tmp], capture_output=True, text=True, timeout=60)
        assert p.returncode == 0, f"前端 JS 语法错误 (整页交互会全失效):\n{p.stderr[:1200]}"
    finally:
        Path(tmp).unlink(missing_ok=True)
