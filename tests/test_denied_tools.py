"""--disallowed-tools / settings.json disallowedTools 硬拒语义回归。

对标 Claude Code: 用户显式禁用的工具/命令, 即便在白名单/YOLO 下也不放行。
覆盖: DeniedTools 解析匹配 + 工具级硬拒 (base.dispatch_result) + Bash 作用域
硬拒 (shell._pre_exec_check)。
"""

from __future__ import annotations

import json
import os
import tempfile
import textwrap

from tuan_cli.core.allowed_tools import DeniedTools
from tuan_cli.tools.base import ToolContext, ToolRegistry, ToolResult
from tuan_cli.tools.shell import _pre_exec_guard


class _FakeKernel:
    """最小内核桩: 提供 get('config') 供 ToolContext 构造。"""
    def __init__(self):
        self._services = {"config": _FakeConfig()}

    def get(self, name):
        return self._services.get(name)

    def require(self, name):
        return self._services.get(name)


class _FakeConfig:
    def __init__(self):
        self.data = {}

    def get(self, key, default=None):
        cur = self.data
        for part in str(key).split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur if cur is not None else default


def _mk_ctx(**kw) -> ToolContext:
    kw.setdefault("kernel", _FakeKernel())
    kw.setdefault("workspace", ".")
    return ToolContext(**kw)


def _mk_dispatcher() -> ToolRegistry:
    d = ToolRegistry()
    # 注册一个真实工具 (read_file), 让 dispatch_result 能走到 _pre_exec_check
    from tuan_cli.tools.base import Tool
    d.register(Tool(
        name="read_file",
        description="读文件 (测试桩)",
        handler=lambda ctx, path, offset=0, limit=0: "x",
        parameters={"type": "object", "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer"},
            "limit": {"type": "integer"},
        }},
        read_only=True,
    ))
    return d


# ---------- DeniedTools 解析/匹配 ----------

def test_denied_parse_plain_tool():
    d = DeniedTools.parse("WebFetch,Read")
    assert d.denies_tool("WebFetch") is True
    assert d.denies_tool("Read") is True
    assert d.denies_tool("Write") is False


def test_denied_parse_bash_scopes():
    d = DeniedTools.parse("Bash(git push:*),Bash(rm -rf:*)")
    assert d.denies_bash("git push origin main") is True
    assert d.denies_bash("rm -rf /tmp/x") is True
    assert d.denies_bash("git status") is False


def test_denied_bash_star_disables_all():
    d = DeniedTools.parse("Bash(*)")
    assert d.denies_bash("echo hi") is True


def test_denied_empty_denies_nothing():
    d = DeniedTools.parse("")
    assert d.denies_tool("Read") is False
    assert d.denies_bash("rm -rf /") is False


def test_denied_scopes_text():
    d = DeniedTools.parse("WebFetch,Bash(git push:*)")
    txt = d.scopes_text()
    assert "web_fetch" in txt and "Bash(git push:*)" in txt


# ---------- 工具级硬拒 (base.dispatch_result 分发) ----------

def test_base_denied_tool_blocked():
    disp = _mk_dispatcher()
    ctx = _mk_ctx()
    ctx.denied_tools = DeniedTools.parse("Read")
    r = disp.dispatch_result("read_file", json.dumps({"path": "/tmp/x"}), ctx)
    assert r.status == "denied"
    assert "已禁用" in r.content


def test_base_denied_tool_bypasses_yolo():
    disp = _mk_dispatcher()
    ctx = _mk_ctx()
    ctx.denied_tools = DeniedTools.parse("Read")
    ctx.auto_mode = True  # 模拟 YOLO
    r = disp.dispatch_result("read_file", json.dumps({"path": "/tmp/x"}), ctx)
    assert r.status == "denied"


def test_base_denied_unknown_tool_passthrough():
    """未在 disallowedTools 的工具不受影响。"""
    disp = _mk_dispatcher()
    ctx = _mk_ctx()
    ctx.denied_tools = DeniedTools.parse("WebFetch")
    # Read 未禁用 → 不会 status denied (可能因缺文件报别的错, 但不是 denied)
    r = disp.dispatch_result("read_file", json.dumps({"path": ".__nope__"}), ctx)
    assert r.status != "denied"


# ---------- Bash 作用域硬拒 (shell._pre_exec_check) ----------

def test_shell_denied_bash_scope_blocked():
    ctx = _mk_ctx()
    ctx.denied_tools = DeniedTools.parse("Bash(git push:*)")
    result = _pre_exec_guard(ctx, "git push origin main")
    assert "已禁用" in result


def test_shell_denied_not_matching_allowed():
    ctx = _mk_ctx()
    ctx.denied_tools = DeniedTools.parse("Bash(git push:*)")
    result = _pre_exec_guard(ctx, "git status")
    assert result is None  # 未被禁用 → 继续走后续白名单/确认


# ---------- settings.json disallowedTools 端到端 ----------

def test_settings_disallowed_tools_roundtrip():
    from tuan_cli.config.settings_file import load_settings

    with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write(textwrap.dedent("""\
            {
              "disallowedTools": ["WebFetch", "Bash(git push:*)"]
            }
            """))
        path = f.name
    try:
        res = load_settings(path)
        assert res.disallowed_tools == ["WebFetch", "Bash(git push:*)"]
        d = DeniedTools.parse(",".join(res.disallowed_tools))
        assert d.denies_tool("WebFetch") is True
        assert d.denies_bash("git push origin main") is True
    finally:
        os.unlink(path)


def test_settings_allowed_disallowed_roundtrip():
    from tuan_cli.config.settings_file import load_settings

    with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write(textwrap.dedent("""\
            {
              "allowedTools": ["Read", "Grep"],
              "disallowedTools": ["WebFetch"]
            }
            """))
        path = f.name
    try:
        res = load_settings(path)
        assert res.allowed_tools == ["Read", "Grep"]
        assert res.disallowed_tools == ["WebFetch"]
    finally:
        os.unlink(path)


def test_top_level_flags_register_and_default():
    from tuan_cli.cli.parser import build_parser

    p = build_parser()
    # 顶层 flag 放在子命令**之前** (argparse 语义); 注册后可达而非 AttributeError。
    args = p.parse_args(["safe", "status"])
    assert getattr(args, "disallowed_tools", None) is None
    assert getattr(args, "add_dir", None) is None
    assert getattr(args, "settings", None) is None
    args2 = p.parse_args(["--disallowed-tools", "WebFetch", "safe", "status"])
    assert args2.disallowed_tools == "WebFetch"
    args3 = p.parse_args(["--add-dir", "D:\\shared", "safe", "status"])
    assert args3.add_dir == ["D:\\shared"]
    args4 = p.parse_args(["--settings", "settings.json", "safe", "status"])
    assert args4.settings == "settings.json"


def test_settings_file_applies_to_session():
    """_apply_settings_file 把 settings.json 翻译进 agent.ctx (不写盘)。"""
    from tuan_cli.cli.cmd_chat import _apply_settings_file

    class _Cfg:
        data = {"permissions": {"rules": []}}

        def get(self, k):
            cur = self.data
            for part in k.split("."):
                cur = cur.get(part, None)
                if cur is None:
                    return None
            return cur

    class _Ctx:
        def __init__(self):
            self.allowed_tools = None
            self.denied_tools = None
            self.settings_mode = None
            self.workspace = "."  # authorize_extra_dir 需要

    class _Agent:
        def __init__(self):
            self.ctx = _Ctx()

    agent = _Agent()
    cfg = _Cfg()
    with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write(textwrap.dedent("""\
            {
              "allowedTools": ["Read"],
              "disallowedTools": ["WebFetch"],
              "permissions": {"additionalDirectories": ["../shared"]}
            }
            """))
        path = f.name
    try:
        _apply_settings_file(agent, cfg, path)
        assert agent.ctx.allowed_tools is not None
        assert agent.ctx.allowed_tools.allows_tool("Read") is True
        assert agent.ctx.denied_tools is not None
        assert agent.ctx.denied_tools.denies_tool("WebFetch") is True
    finally:
        os.unlink(path)
