"""OP-1: Git Worktree 会话状态机测试。

覆盖:
- _flatten_slug 拍平 (路径分隔符/非法字符 -> 合法 ref);
- create_agent_worktree: 命名 agent-<7hex>-<flat>、fast-resume 复用、分支挂载;
- remove_agent_worktree: fail-closed (非 ephemeral 跳过 / 未提交改动跳过 / 未推送跳过),
  干净 worktree 删除 + 分支 -D;
- cleanup_stale_agent_worktrees: 只清理 ephemeral, 不碰用户命名;
- WorktreeSession 持久化 save/load/delete;
- orchestration 集成: git 仓库内子代理用真 worktree 隔离, 完成后自动清理。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tuan_cli.arch.orchestration import AgentSpec, SubAgent, default_executor
from tuan_cli.core.worktree_layer import (
    WorktreeLayer,
    WorktreeSession,
    _EPHEMERAL_SLUG_RE,
    _flatten_slug,
    delete_worktree_state,
    load_worktree_states,
    save_worktree_state,
)


def _git(args, cwd):
    return subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True,
                          text=True, timeout=30)


@pytest.fixture()
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], repo)
    _git(["config", "user.email", "test@tuan.dev"], repo)
    _git(["config", "user.name", "tuan-test"], repo)
    (repo / "main.py").write_text("print('hi')\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "initial"], repo)
    return repo


# ------------------------------------------------------------------ 拍平


def test_flatten_slug():
    assert _flatten_slug("user/feature") == "user+feature"
    assert _flatten_slug("a\\b_c") == "a+b+c"
    assert _flatten_slug("has:space name") == "has-space-name"
    assert _flatten_slug("") == "default"
    assert _flatten_slug("..") == "default"  # 全非法字符兜底


def test_ephemeral_regex():
    assert _EPHEMERAL_SLUG_RE.match("agent-1a2b3c4-work")
    assert _EPHEMERAL_SLUG_RE.match("agent-0000000")
    assert _EPHEMERAL_SLUG_RE.match("wf_xyz")
    assert _EPHEMERAL_SLUG_RE.match("bridge-main")
    assert _EPHEMERAL_SLUG_RE.match("job-42")
    # 用户命名绝不匹配
    assert not _EPHEMERAL_SLUG_RE.match("feature-x")
    assert not _EPHEMERAL_SLUG_RE.match("agent-work")       # 缺 7 位 hex
    assert not _EPHEMERAL_SLUG_RE.match("my-agent-abc")


# ------------------------------------------------------------------ 会话持久化


def test_session_save_load_delete(tmp_path):
    s = WorktreeSession(
        session_id="s1", spec_id="agent-abc1234", worktree_path=str(tmp_path / "wt"),
        branch="agent-abc1234-work", original_cwd=str(tmp_path),
        original_branch="main", original_head="a" * 40,
        created_at=123.0, status="active",
    )
    save_worktree_state(s, home=tmp_path)
    loaded = load_worktree_states(home=tmp_path)
    assert "s1" in loaded
    assert loaded["s1"].branch == "agent-abc1234-work"
    assert loaded["s1"].original_branch == "main"
    assert loaded["s1"].status == "active"

    delete_worktree_state("s1", home=tmp_path)
    assert "s1" not in load_worktree_states(home=tmp_path)


# ------------------------------------------------------------------ 子代理 worktree CRUD


def test_create_agent_worktree_and_reuse(git_repo):
    layer = WorktreeLayer(git_repo)
    info = layer.create_agent_worktree("agent-1234abcd", slug="research")
    assert info.name.startswith("agent-")
    assert "research" in info.name
    assert Path(info.path).is_dir()
    # worktree 内 HEAD 分支 = 创建的 ephemeral 分支
    r = _git(["rev-parse", "--abbrev-ref", "HEAD"], Path(info.path))
    assert r.stdout.strip() == info.name

    # fast-resume: 再次创建同一 spec/slug 复用同一路径
    info2 = layer.create_agent_worktree("agent-1234abcd", slug="research")
    assert info2.path == info.path


def test_remove_agent_worktree_clean(git_repo):
    layer = WorktreeLayer(git_repo)
    info = layer.create_agent_worktree("agent-0000aaaa")
    out = layer.remove_agent_worktree(info.name)
    assert out.startswith("已清理")
    assert not Path(info.path).exists()
    # 分支被删
    branches = _git(["branch", "--list"], git_repo).stdout
    assert info.name not in branches


def test_remove_agent_worktree_fail_closed_dirty(git_repo):
    layer = WorktreeLayer(git_repo)
    info = layer.create_agent_worktree("agent-0000bbbb")
    wt = Path(info.path)
    (wt / "dirty.txt").write_text("未提交改动\n", encoding="utf-8")
    out = layer.remove_agent_worktree(info.name)
    assert out.startswith("跳过")
    assert "未提交改动" in out
    assert wt.exists()  # 没删


def test_remove_agent_worktree_refuses_user_worktree(git_repo):
    layer = WorktreeLayer(git_repo)
    layer.create("user-feature")  # 用户命名 (create 走 -b <name>)
    out = layer.remove_agent_worktree("user-feature")
    assert out.startswith("跳过")
    assert (git_repo / ".tuan" / "worktrees" / "user-feature").exists()


def test_cleanup_stale_agent_worktrees(git_repo):
    layer = WorktreeLayer(git_repo)
    layer.create_agent_worktree("agent-11112222", slug="t1")
    layer.create_agent_worktree("agent-33334444", slug="t2")
    layer.create("user-keep")  # 用户命名, 必须保留

    outs = layer.cleanup_stale_agent_worktrees()
    assert any("已清理" in o for o in outs)
    names = [it.name for it in layer.list()]
    assert not any(n.startswith("agent-") for n in names)
    assert "user-keep" in names  # 用户 worktree 不动


# ------------------------------------------------------------------ orchestration 集成


def test_orchestration_uses_real_worktree_in_git_repo(git_repo):
    spec = AgentSpec(id="agent-abc12345", goal="写文件")
    sub = SubAgent(spec, executor=default_executor, base_workspace=str(git_repo))
    result = sub.run()

    assert result.error is None
    assert result.worktree
    wt = Path(result.worktree)
    assert (wt / "result.txt").exists()          # executor 确实在 worktree 里写了
    # 真 ephemeral worktree: agent-<尾7位hex>-<slug>
    assert _EPHEMERAL_SLUG_RE.match(wt.name)
    assert "bc12345" in wt.name                 # spec id 尾 7 位 hex 截断
    assert wt.name.endswith("work")
    # 隔离: 主仓库不受污染
    assert not (git_repo / "result.txt").exists()
    # fail-closed 清理: executor 留下了未跟踪文件 (有改动) -> 不自动删除,
    # 但被登记为可清理项 (cleanup_stale_agent_worktrees 会再尝试并说明跳过)
    assert wt.exists()
    outs = WorktreeLayer(git_repo).cleanup_stale_agent_worktrees()
    assert any("跳过" in o and "未提交改动" in o for o in outs)


def test_orchestration_falls_back_to_tempdir(tmp_path):
    spec = AgentSpec(id="agent-xyz99999", goal="非仓库")
    sub = SubAgent(spec, executor=default_executor,
                   base_workspace=str(tmp_path / "notrepo"))
    result = sub.run()
    assert result.error is None
    # 非 git 仓库: 降级 tempdir, 跑完即删
    assert not Path(result.worktree).exists()
