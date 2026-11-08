"""用户级 Hooks 测试 (零网络, 纯标准库 fixture)。

覆盖:
- manager 解析 / matcher / 字符串命令拒绝 (fail closed)
- PreToolUse 阻断 (全局 allow_blocking 开/关, fail-safe)
- 审计 hook 不改写
- 参数改写 (allow_edit_args 开/关)
- 超时强杀不阻塞主流程
- dispatch_result 集成: 阻断返回 denied 且 handler 不执行
- PostToolUse / SessionStart / SessionEnd 触发
- DEFAULT_CONFIG 的 hooks 块默认值
"""

import json
import os
import sys
import time

import pytest

from tuan_cli.hooks import HookManager
from tuan_cli.tools.base import Tool, ToolContext, ToolRegistry

PY = sys.executable
FIX = os.path.join(os.path.dirname(__file__), "fixtures")
BLOCK = os.path.join(FIX, "hook_block.py")
AUDIT = os.path.join(FIX, "hook_audit.py")
ARGS = os.path.join(FIX, "hook_args.py")
TIMEOUT = os.path.join(FIX, "hook_timeout.py")


class FakeKernel:
    def __init__(self):
        self.events = []
    def get(self, name, default=None):
        return default
    def require(self, name):
        return None
    def emit(self, t, p=None):
        self.events.append((t, p))
    def on(self, *a, **k):
        pass


def make_cfg(block: dict) -> dict:
    return {"hooks": block}


# ------------------------------------------------------------------ 解析

def test_parse_and_matcher():
    mgr = HookManager(make_cfg({
        "enabled": True,
        "PreToolUse": [
            {"matcher": "delete_*", "command": [PY, BLOCK], "blocking": True},
            {"matcher": "*", "command": [PY, AUDIT]},
        ],
    }))
    assert len(mgr.list_hooks()) == 2
    assert mgr._match("delete_file", "delete_file")
    assert not mgr._match("write_file", "delete_file")
    assert mgr._match("*", "write_file")
    # 排除语法
    assert not mgr._match("!delete_*", "delete_file")
    assert mgr._match("!delete_*", "write_file")


def test_string_command_rejected_fail_closed():
    # 裸字符串命令必须被拒绝, 绝不执行 (防 shell 注入)
    mgr = HookManager(make_cfg({"PreToolUse": [{"matcher": "*", "command": "echo bad"}]}))
    d = mgr.run_pre("write_file", {"path": "/x"})
    assert d.block is False  # 命令被拒, 不阻断、不执行


def test_disabled_hooks_noop():
    mgr = HookManager(make_cfg({
        "enabled": False,
        "PreToolUse": [{"matcher": "*", "command": [PY, BLOCK], "blocking": True}],
    }))
    d = mgr.run_pre("delete_file", {"path": "/x"})
    assert d.block is False


# ------------------------------------------------------------------ PreToolUse 阻断

def test_pre_block_when_allowed():
    mgr = HookManager(make_cfg({
        "allow_blocking": True,
        "PreToolUse": [{"matcher": "delete_*", "command": [PY, BLOCK], "blocking": True}],
    }))
    d = mgr.run_pre("delete_file", {"path": "/x"}, dangerous=True)
    assert d.block is True
    assert "delete_file" in (d.reason or "")


def test_pre_block_denied_when_global_off_fail_safe():
    # 全局关闭阻断 → hook 即便声明 blocking 也不生效 (fail-safe)
    mgr = HookManager(make_cfg({
        "allow_blocking": False,
        "PreToolUse": [{"matcher": "delete_*", "command": [PY, BLOCK], "blocking": True}],
    }))
    d = mgr.run_pre("delete_file", {"path": "/x"})
    assert d.block is False


def test_audit_hook_no_block():
    mgr = HookManager(make_cfg({
        "PreToolUse": [{"matcher": "*", "command": [PY, AUDIT]}],
    }))
    d = mgr.run_pre("write_file", {"path": "/x"})
    assert d.block is False
    assert d.args is None


# ------------------------------------------------------------------ 参数改写

def test_args_rewrite_allowed():
    # B3 契约同步（断言更强，不是放宽）：hook 仍可改写**既有**参数，
    # 但不得注入原 args 里没有的新键 —— 旧行为会把 `_hook_injected`
    # 原样交给 `tool.handler(ctx, **args)` 并抛 TypeError。
    # 无 schema 时走保守子集过滤；有 schema 时按 properties 白名单丢弃。
    mgr = HookManager(make_cfg({
        "allow_edit_args": True,
        "PreToolUse": [{"matcher": "*", "command": [PY, ARGS], "allow_edit_args": True}],
    }))
    d = mgr.run_pre("write_file", {"path": "/x", "content": "a"})
    assert d.args is not None
    assert d.args.get("path") == "/x"
    assert d.args.get("content") == "a"
    assert "_hook_injected" not in d.args
    assert d.block is False


def test_args_rewrite_denied_when_not_authorized():
    mgr = HookManager(make_cfg({
        "allow_edit_args": False,
        "PreToolUse": [{"matcher": "*", "command": [PY, ARGS]}],  # hook 未声明 allow_edit_args
    }))
    d = mgr.run_pre("write_file", {"path": "/x"})
    assert d.args is None


# ------------------------------------------------------------------ 超时

def test_timeout_kills_hook():
    # B1 行为变更（超 Claude Code v2.1.319）：hook 故障默认 fail-closed。
    # 旧断言是「超时不转化为阻断」——那正是 CC 需要显式
    # onFailure:"block" 才关掉的静默 fail-open 侧门。现在默认阻断，
    # 并带结构化原因与可查询的失败记录。
    mgr = HookManager(make_cfg({
        "default_timeout": 1,
        "PreToolUse": [{"matcher": "*", "command": [PY, TIMEOUT], "timeout": 1}],
    }), workspace=os.getcwd())
    t0 = time.time()
    d = mgr.run_pre("write_file", {})  # 超时强杀 -> fail-closed 阻断
    dt = time.time() - t0
    assert dt < 10
    assert d.block is True
    assert d.failure_kind == "timeout"
    assert "fail-closed" in d.reason
    assert any(f["kind"] == "timeout" for f in mgr.failures())


def test_timeout_can_be_explicitly_allowed():
    """显式 on_failure=allow 仍可恢复旧行为（逃生口必须可达且留痕）。"""
    mgr = HookManager(make_cfg({
        "default_timeout": 1,
        "on_failure": "allow",
        "PreToolUse": [{"matcher": "*", "command": [PY, TIMEOUT], "timeout": 1}],
    }), workspace=os.getcwd())
    d = mgr.run_pre("write_file", {})
    assert d.block is False
    assert any(f["kind"] == "timeout" for f in mgr.failures())


# ------------------------------------------------------------------ dispatch 集成

def test_dispatch_block_integration():
    reg = ToolRegistry()
    executed = []
    def fake_delete(ctx, path):
        executed.append(path)
        return "deleted"
    reg.register(Tool(name="delete_file", description="d", handler=fake_delete,
                      parameters={}, dangerous=True, read_only=False))
    mgr = HookManager(make_cfg({
        "allow_blocking": True,
        "PreToolUse": [{"matcher": "delete_*", "command": [PY, BLOCK], "blocking": True}],
    }))
    ctx = ToolContext(kernel=FakeKernel(), workspace=os.getcwd(), hooks=mgr)
    ctx.confirm = lambda p: True  # 模拟用户批准, 让流程走到 hook 阻断
    res = reg.dispatch_result("delete_file", json.dumps({"path": "/x"}), ctx)
    assert res.status == "denied"
    assert executed == []  # handler 未执行


def test_dispatch_post_audit_triggered(tmp_path):
    reg = ToolRegistry()
    def fake_read(ctx, path):
        return "data"
    reg.register(Tool(name="read_file", description="r", handler=fake_read,
                      parameters={}, dangerous=False, read_only=True))
    audit_log = os.path.join(str(tmp_path), "audit.log")
    os.environ["HOOK_AUDIT_LOG"] = audit_log
    try:
        mgr = HookManager(make_cfg({
            "PostToolUse": [{"matcher": "*", "command": [PY, AUDIT]}],
        }), workspace=str(tmp_path))
        ctx = ToolContext(kernel=FakeKernel(), workspace=str(tmp_path), hooks=mgr)
        res = reg.dispatch_result("read_file", json.dumps({"path": "/x"}), ctx)
        assert res.status == "ok"
        assert os.path.exists(audit_log)
        lines = [json.loads(l) for l in open(audit_log, encoding="utf-8") if l.strip()]
        assert any(e.get("hook_event_name") == "PostToolUse" for e in lines)
    finally:
        os.environ.pop("HOOK_AUDIT_LOG", None)


def test_session_hooks_triggered(tmp_path):
    audit_log = os.path.join(str(tmp_path), "sess.log")
    os.environ["HOOK_AUDIT_LOG"] = audit_log
    try:
        mgr = HookManager(make_cfg({
            "SessionStart": [{"matcher": "*", "command": [PY, AUDIT]}],
            "SessionEnd": [{"matcher": "*", "command": [PY, AUDIT]}],
        }), workspace=str(tmp_path))
        mgr.run_session("SessionStart", {"workspace": str(tmp_path)})
        mgr.run_session("SessionEnd", {"workspace": str(tmp_path)})
        lines = [json.loads(l) for l in open(audit_log, encoding="utf-8") if l.strip()]
        events = {e.get("hook_event_name") for e in lines}
        assert "SessionStart" in events and "SessionEnd" in events
    finally:
        os.environ.pop("HOOK_AUDIT_LOG", None)


# ------------------------------------------------------------------ 配置块默认值

def test_default_config_hooks_block():
    from tuan_cli.config import DEFAULT_CONFIG
    h = DEFAULT_CONFIG["hooks"]
    assert h["enabled"] is True
    assert h["allow_blocking"] is True
    assert h["allow_edit_args"] is False
    assert "default_timeout" in h
