"""上下文三件套缺口补齐测试 —— 聚焦本轮唯一真实缺口: /add-dir 目录授权。

对标 Claude Code /add-dir: 把工作区外目录显式纳入本会话可读上下文。
钉死安全不变量 (任一被破坏即视为事故):
  1. 未授权时, 工作区外路径一律被 _resolve 拦截 (既有越界守卫不被削弱);
  2. /add-dir 拒绝不存在路径、非目录、以及系统关键目录 (盘符根 / Windows 目录);
  3. 授权后, read_file / list_dir 可读工作区外文件;
  4. 授权仅放宽"读取", 写操作仍受 Read-before-Edit 守卫约束 (未读先改照样拦);
  5. 授权为 per-session 内存态 (挂在 ctx 上), 不写入 config / 不落盘;
  6. 斜杠命令 /add-dir 接线正确 (无参列出, 带参授权)。
"""

from __future__ import annotations

import json
import os

import pytest

from tuan_cli.config import Config
from tuan_cli.cli.cmd_slash import SLASH_COMMAND_NAMES
from tuan_cli.core.kernel import Kernel
from tuan_cli.tools import ToolRegistryPlugin, builtin_tool_plugins
from tuan_cli.tools.base import ToolContext
from tuan_cli.tools.filesystem import (
    authorize_extra_dir,
    list_extra_dirs,
)


def _kernel():
    k = Kernel()
    k.provide("config", Config(), owner="test")
    k.register(ToolRegistryPlugin())
    for p in builtin_tool_plugins():
        if p.name in ("tools.filesystem",):
            k.register(p)
    k.activate_all()
    return k


def _ctx(k, workspace):
    return ToolContext(kernel=k, workspace=str(workspace), confirm=lambda _p: True)


def _outside(tmp_path_factory):
    """工作区之外的一个临时目录 (与工作区平级, 不在其下)。"""
    return tmp_path_factory.mktemp("outside_store")


# ---------------------------------------------------------------- 守卫不削弱

def test_read_outside_workspace_blocked_without_auth(tmp_path, tmp_path_factory):
    """未授权时, 读工作区外文件被 _resolve 拦截 (既有行为保持)。"""
    k = _kernel()
    registry = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    outside = _outside(tmp_path_factory)
    (outside / "note.txt").write_text("外部机密内容", encoding="utf-8")
    out = registry.dispatch("read_file", json.dumps(
        {"path": str(outside / "note.txt")}), ctx)
    assert "必须位于工作区内" in out
    assert "外部机密内容" not in out


def test_resolve_behavior_unchanged_when_no_auth(tmp_path):
    """授权列表为空时, _extra_allowed_roots 返回空, _resolve 与改动前完全一致。"""
    k = _kernel()
    ctx = _ctx(k, tmp_path)
    assert list_extra_dirs(ctx) == []


# ---------------------------------------------------------------- 授权校验

def test_authorize_rejects_nonexistent(tmp_path, tmp_path_factory):
    k = _kernel()
    ctx = _ctx(k, tmp_path)
    outside = _outside(tmp_path_factory)
    msg = authorize_extra_dir(ctx, str(outside / "no_such_dir"))
    assert "目录不存在" in msg
    assert list_extra_dirs(ctx) == []


def test_authorize_rejects_file_instead_of_dir(tmp_path, tmp_path_factory):
    k = _kernel()
    ctx = _ctx(k, tmp_path)
    outside = _outside(tmp_path_factory)
    f = outside / "a.txt"
    f.write_text("x", encoding="utf-8")
    msg = authorize_extra_dir(ctx, str(f))
    assert "不是目录" in msg
    assert list_extra_dirs(ctx) == []


def test_authorize_rejects_drive_root(tmp_path):
    k = _kernel()
    ctx = _ctx(k, tmp_path)
    anchor = str(tmp_path.anchor)  # e.g. 'C:\\' or '/'
    msg = authorize_extra_dir(ctx, anchor)
    assert "系统关键目录" in msg
    assert list_extra_dirs(ctx) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows SystemRoot 目录黑名单仅在 Windows 校验")
def test_authorize_rejects_windows_system_root(tmp_path):
    k = _kernel()
    ctx = _ctx(k, tmp_path)
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    msg = authorize_extra_dir(ctx, sysroot)
    assert "系统关键目录" in msg
    assert list_extra_dirs(ctx) == []


def test_authorize_workspace_internal_is_noop(tmp_path):
    k = _kernel()
    ctx = _ctx(k, tmp_path)
    sub = tmp_path / "sub"
    sub.mkdir()
    msg = authorize_extra_dir(ctx, str(sub))
    assert "已在工作区内" in msg
    assert list_extra_dirs(ctx) == []


def test_authorize_is_deduped(tmp_path, tmp_path_factory):
    k = _kernel()
    ctx = _ctx(k, tmp_path)
    outside = _outside(tmp_path_factory)
    m1 = authorize_extra_dir(ctx, str(outside))
    assert "已授权目录" in m1
    m2 = authorize_extra_dir(ctx, str(outside))
    assert "已在授权列表中" in m2
    assert len(list_extra_dirs(ctx)) == 1


# ---------------------------------------------------------------- 授权后可读

def test_read_outside_after_auth(tmp_path, tmp_path_factory):
    """授权后 read_file 可读工作区外文件。"""
    k = _kernel()
    registry = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    outside = _outside(tmp_path_factory)
    (outside / "note.txt").write_text("外部机密内容", encoding="utf-8")
    assert "已授权目录" in authorize_extra_dir(ctx, str(outside))
    out = registry.dispatch("read_file", json.dumps(
        {"path": str(outside / "note.txt")}), ctx)
    assert "外部机密内容" in out


def test_list_dir_outside_after_auth(tmp_path, tmp_path_factory):
    """授权后 list_dir 可列举工作区外目录。"""
    k = _kernel()
    registry = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    outside = _outside(tmp_path_factory)
    (outside / "mod.py").write_text("print(1)", encoding="utf-8")
    authorize_extra_dir(ctx, str(outside))
    out = registry.dispatch("list_dir", json.dumps({"path": str(outside), "depth": 1}), ctx)
    assert "mod.py" in out


# ---------------------------------------------------------------- 写仍受守卫

def test_write_guard_still_applies_to_authorized_dir(tmp_path, tmp_path_factory):
    """授权目录里的既有文件, 未先 read 就 edit 仍被 Read-before-Edit 守卫拦截。"""
    k = _kernel()
    registry = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    outside = _outside(tmp_path_factory)
    target = outside / "existing.txt"
    target.write_text("v1", encoding="utf-8")
    authorize_extra_dir(ctx, str(outside))
    # 未读先改 -> 守卫拦截 (授权不削弱守卫)
    out = registry.dispatch("edit_file", json.dumps(
        {"path": str(target), "old_string": "v1", "new_string": "v2"}), ctx)
    assert "请先 read_file" in out
    assert target.read_text(encoding="utf-8") == "v1"
    # 先读后改 -> 放行
    registry.dispatch("read_file", json.dumps({"path": str(target)}), ctx)
    out2 = registry.dispatch("edit_file", json.dumps(
        {"path": str(target), "old_string": "v1", "new_string": "v2"}), ctx)
    assert "已修改" in out2
    assert target.read_text(encoding="utf-8") == "v2"


# ---------------------------------------------------------------- 不落盘

def test_auth_is_session_memory_not_config(tmp_path, tmp_path_factory):
    """授权只挂在 ctx 内存态, 不写进 kernel config (避免落盘泄露)。"""
    k = _kernel()
    cfg = k.require("config")
    ctx = _ctx(k, tmp_path)
    outside = _outside(tmp_path_factory)
    authorize_extra_dir(ctx, str(outside))
    # ctx 上有, config 里没有
    assert str(outside) in list_extra_dirs(ctx)
    assert outside.name not in json.dumps(getattr(cfg, "data", {}), ensure_ascii=False)


# ---------------------------------------------------------------- 斜杠命令接线

class _FakeAgent:
    """仅承载 ctx 的最小 agent (供 _handle_slash 的 /add-dir 分支使用)。"""

    def __init__(self, ctx):
        self.ctx = ctx


def test_slash_add_dir_wires(tmp_path, tmp_path_factory, capsys):
    """/add-dir <路径> 授权, 无参列出; 且命令已注册进补全清单。"""
    from tuan_cli.cli.cmd_slash import _handle_slash
    k = _kernel()
    ctx = _ctx(k, tmp_path)
    agent = _FakeAgent(ctx)
    outside = _outside(tmp_path_factory)
    (outside / "x.txt").write_text("data", encoding="utf-8")

    # 无参 -> 提示用法
    assert _handle_slash("/add-dir", agent, None, str(tmp_path)) is True
    # 带参 -> 授权
    assert _handle_slash(f"/add-dir {outside}", agent, None, str(tmp_path)) is True
    # 再无参 -> 列出已授权
    assert _handle_slash("/add-dir", agent, None, str(tmp_path)) is True
    out = capsys.readouterr().out
    assert str(outside) in out

    # 注册进命令清单
    assert "/add-dir" in SLASH_COMMAND_NAMES
