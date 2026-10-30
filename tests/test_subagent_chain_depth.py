"""subagent 递归链深 (chain depth) 测试 —— 对标 Claude Code subagents can spawn subagents 的有限深度。

覆盖:
- _resolve_subagent_params: 链深 < 上限时不排除 subagent (允许递归); 链深 >= 上限时排除 (禁止孙代理)。
- _run_subagent: 达到 _MAX_CHAIN_DEPTH 时返回错误提示, 不再递归 spawn。
"""

from __future__ import annotations

from unittest.mock import MagicMock

from tuan_cli.tools.base import ToolContext
from tuan_cli.tools.subagent_tool import (
    _MAX_CHAIN_DEPTH,
    _resolve_subagent_params,
    _run_subagent,
)


def _mock_kernel():
    """带 config 的 mock kernel (kernel.require("config") 可解析)。"""
    kernel = MagicMock()
    config = MagicMock()
    config.home = "."
    config.get.return_value = 15  # agent.subagent_max_iterations
    kernel.require.return_value = config
    kernel.get.return_value = None
    return kernel


def _ctx(chain_depth: int = 0, kernel=None) -> ToolContext:
    ctx = ToolContext(kernel=kernel if kernel is not None else _mock_kernel(), workspace=".")
    ctx.chain_depth = chain_depth
    return ctx


# ------------------------------------------------------------ 链深边界 (参数解析)

def test_depth_below_limit_allows_recursive_spawn():
    """链深 < 上限: subagent 不被排除, 子代理可再 spawn 孙代理。"""
    ctx = _ctx(chain_depth=1)
    excluded, _ = _resolve_subagent_params(ctx, "", "", "", depth=1)
    assert "subagent" not in excluded
    assert "session_list" in excluded  # 会话管理仍被排除


def test_depth_at_limit_forbids_recursive_spawn():
    """链深 == 上限: subagent 被排除, 子代理不能再 spawn 孙代理 (防无限递归)。"""
    ctx = _ctx(chain_depth=_MAX_CHAIN_DEPTH)
    excluded, _ = _resolve_subagent_params(ctx, "", "", "", depth=_MAX_CHAIN_DEPTH)
    assert "subagent" in excluded


def test_depth_beyond_limit_forbids_recursive_spawn():
    """链深 > 上限 (防御性): 同样排除 subagent。"""
    excluded, _ = _resolve_subagent_params(_ctx(), "", "", "", depth=_MAX_CHAIN_DEPTH + 2)
    assert "subagent" in excluded


# ------------------------------------------------------------ 链深上限 (运行时拒绝)

def test_run_subagent_rejects_beyond_depth_limit():
    """链深达到上限时, _run_subagent 直接返回错误提示, 不创建子代理 (防无限递归)。"""
    ctx = _ctx(chain_depth=_MAX_CHAIN_DEPTH)
    out = _run_subagent(ctx, task="再 spawn 一层", timeout=0)
    assert isinstance(out, str)
    assert "递归链深上限" in out
    assert str(_MAX_CHAIN_DEPTH) in out


def test_run_subagent_depth_below_limit_passes_chain_check():
    """链深 < 上限时, _run_subagent 不触发链深拒绝分支。

    create_agent 被 mock 为抛错对象 (无 .run / .ctx), 但链深检查在 create_agent
    之前完成; 只要没抛出链深错误提示, 即证明主会话 (或浅层子代理) 可正常 spawn。
    这验证 depth=0 默认从 ctx.chain_depth 推断的正确性。
    """
    ctx = _ctx(chain_depth=1)  # 子代理链深 1 (< 上限 5)
    import tuan_cli.app as app

    orig = app.create_agent
    app.create_agent = MagicMock(
        side_effect=RuntimeError("sentinel-no-run"))  # 链深检查之后才触达
    try:
        out = _run_subagent(ctx, task="浅层子代理再 spawn", timeout=0)
    except RuntimeError as exc:
        # 触达 create_agent 且被 sentinel 拦住 → 证明没在链深检查处提前 return
        assert "sentinel-no-run" in str(exc)
        assert app.create_agent.called, "浅层 spawn 应创建子代理"
    else:
        # 不应出现链深错误 (链深 1 < 5); 若返回的是链深错误说明逻辑有误
        assert "递归链深上限" not in out
    finally:
        app.create_agent = orig


def test_run_subagent_injects_incremented_chain_depth():
    """子代理创建后, 其 ctx.chain_depth 被注入为父链深 + 1 (孙代理据此继续)。"""
    ctx = _ctx(chain_depth=2)
    import tuan_cli.app as app

    sub = MagicMock()
    sub.ctx = MagicMock()
    sub.ctx.chain_depth = 0
    sub.run = MagicMock(return_value="摘要")
    sub.total_usage = {"prompt_tokens": 1, "completion_tokens": 1}
    sub.turn_count = 1
    orig = app.create_agent
    app.create_agent = MagicMock(return_value=sub)
    try:
        out = _run_subagent(ctx, task="孙代理任务", timeout=0)
        assert "摘要" in out
        assert sub.ctx.chain_depth == 3, f"期望 3, 实际 {sub.ctx.chain_depth}"
    finally:
        app.create_agent = orig
