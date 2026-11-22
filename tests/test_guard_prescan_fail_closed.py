"""审计 #14 回归: 构建文件内容预扫描 (_guard_build_prescan) 的异常路径 fail-closed。

背景: commit 3474705 的提交信息是「构建文件预扫描的命令解析异常补日志
(恢复护栏 silent=0)」—— 说明预扫描的异常路径曾被静默处理。本文件钉死四条契约:

1. 良性前缀命令 (make/npm/pytest) 的构建文件里藏危险内容 → 预扫描拦截 (P1-07 主路径);
2. 命令解析异常 (command 非 str) → 按无构建文件处理返回 None, 不得误拦正常流程
   (后续阶段仍会对原命令做完整评估, 不是放行口子);
3. 红线引擎内部异常 (注入 RuntimeError) → 异常**向上传播**, 绝不吞成 None
   (吞掉 = 静默跳过预扫描 = silent 放行, 正是 #14 要杜绝的形态);
4. 护栏链任何异常传播到 run_shell 时, 命令**绝不执行** (subprocess.Popen 零调用)。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tuan_cli.tools import shell as shell_module
from tuan_cli.tools.base import ToolContext
from tuan_cli.tools.shell import (
    _guard_build_prescan,
    _pre_exec_guard,
    run_shell,
)


def _ctx(tmp_path) -> ToolContext:
    return ToolContext(kernel=None, workspace=str(tmp_path))


def _make_makefile(tmp_path, body: str) -> None:
    (tmp_path / "Makefile").write_text(body, encoding="utf-8")


# ---------------------------------------------------------------- 1) 主路径: 构建文件藏刀被拦

def test_prescan_blocks_dangerous_makefile(tmp_path):
    """Makefile 里藏 `rm -rf /` → 预扫描直接拦截, 不等运行时。"""
    _make_makefile(tmp_path, "test:\n\techo hello\n\trm -rf /\n")
    ctx = _ctx(tmp_path)
    verdict = _guard_build_prescan(ctx, "make test", {})
    assert verdict is not None
    assert "构建文件" in str(verdict) and "红线" in str(verdict)


def test_prescan_clean_makefile_passes(tmp_path):
    """良性 Makefile → 预扫描不拦 (返回 None, 交给后续阶段)。"""
    _make_makefile(tmp_path, "test:\n\techo hello\n")
    ctx = _ctx(tmp_path)
    assert _guard_build_prescan(ctx, "make test", {}) is None


def test_prescan_ignores_non_build_prefix(tmp_path):
    """非构建前缀命令 (git status) → 预扫描不介入。"""
    _make_makefile(tmp_path, "test:\n\trm -rf /\n")
    ctx = _ctx(tmp_path)
    assert _guard_build_prescan(ctx, "git status", {}) is None


# ---------------------------------------------------------------- 2) 命令解析异常: 按无构建文件处理

def test_prescan_parse_exception_returns_none_not_crash(tmp_path):
    """command 非 str (None) → 解析异常按「无构建文件」处理, 返回 None。

    这是 commit 3474705 补日志的路径: 允许降级为 None, 但必须有日志 (silent=0)。
    返回 None 不是放行口子 —— 后续阶段 (红线/分类器/污点追踪) 仍会评估原命令。
    """
    ctx = _ctx(tmp_path)
    assert _guard_build_prescan(ctx, None, {}) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------- 3) 引擎异常: 必须传播, 不许吞

def test_prescan_engine_exception_propagates(tmp_path, monkeypatch):
    """红线引擎 (is_redline) 内部异常 → 异常向上抛, 绝不静默返回 None。"""
    _make_makefile(tmp_path, "test:\n\techo hello\n")
    ctx = _ctx(tmp_path)

    def _boom(_chunk: str) -> bool:
        raise RuntimeError("injected safety engine failure")

    monkeypatch.setattr(shell_module, "_engine_is_redline", _boom)
    with pytest.raises(RuntimeError, match="injected safety engine failure"):
        _guard_build_prescan(ctx, "make test", {})


def test_prescan_hard_redline_exception_propagates(tmp_path, monkeypatch):
    """硬红线入口 (is_hard_redline) 异常 → 同样向上抛。"""
    _make_makefile(tmp_path, "test:\n\techo hello\n")
    ctx = _ctx(tmp_path)

    def _boom(_chunk: str) -> bool:
        raise RuntimeError("injected hard redline failure")

    import tuan_cli.ext.safety_engine as se
    monkeypatch.setattr(shell_module, "_engine_is_redline", lambda c: False)
    monkeypatch.setattr(se, "is_hard_redline", _boom)
    with pytest.raises(RuntimeError, match="injected hard redline failure"):
        _guard_build_prescan(ctx, "make test", {})


# ---------------------------------------------------------------- 4) 护栏异常 → 命令绝不执行

def test_run_shell_never_executes_when_guard_raises(tmp_path, monkeypatch):
    """护栏链抛异常 → run_shell 直接向上传播, subprocess.Popen 零调用。"""
    ctx = _ctx(tmp_path)

    def _boom(_ctx, _cmd):
        raise RuntimeError("injected guard failure")

    monkeypatch.setattr(shell_module, "_pre_exec_guard", _boom)
    popen = MagicMock(side_effect=AssertionError("护栏异常时绝不允许 spawn 进程"))
    monkeypatch.setattr(shell_module.subprocess, "Popen", popen)

    with pytest.raises(RuntimeError, match="injected guard failure"):
        run_shell(ctx, "make test")
    assert popen.call_count == 0


def test_pre_exec_guard_does_not_swallow_stage_exception(tmp_path, monkeypatch):
    """管线级: 任一阶段抛异常 → _pre_exec_guard 原样传播 (无 per-stage 吞异常)。

    注意: _GUARD_STAGES 在导入时绑定阶段函数, 因此这里直接替换整个阶段元组,
    而不是替换单个阶段函数 (那只改模块属性, 不影响已绑定的元组)。
    """
    ctx = _ctx(tmp_path)

    def _boom(_ctx, _cmd, _state):
        raise RuntimeError("injected stage failure")

    monkeypatch.setattr(shell_module, "_GUARD_STAGES", (_boom,))
    with pytest.raises(RuntimeError, match="injected stage failure"):
        _pre_exec_guard(ctx, "make test")
