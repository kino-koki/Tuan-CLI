"""B4: Worktree 层测试 —— create/list/remove (临时 git 仓库)、非 git 仓库处理。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tuan_cli.core.worktree_layer import WorktreeError, WorktreeLayer


def _git(args, cwd):
    return subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, text=True, timeout=30)


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


def test_not_git_repo(tmp_path):
    layer = WorktreeLayer(tmp_path / "notrepo")
    assert layer.is_git_repo() is False
    with pytest.raises(WorktreeError, match="git init"):
        layer.create("exp")


def test_subdirectory_of_git_repo_is_not_root(git_repo):
    """回归: git 仓库内的子目录不应被误判为仓库根。

    ``git rev-parse --is-inside-work-tree`` 对仓库内任意子目录都返回 true,
    会导致把"仓库内子目录"误判为仓库根。修复后用 ``--show-toplevel`` 与
    workspace 绝对路径比对, 仅当 workspace 自身就是仓库根时才返回 True。
    """
    sub = git_repo / "subdir"
    sub.mkdir()
    # 仓库根本身: 是仓库
    assert WorktreeLayer(git_repo).is_git_repo() is True
    # 仓库内子目录: 不是仓库根, 应返回 False
    assert WorktreeLayer(sub).is_git_repo() is False


def test_create_list_remove(git_repo):
    layer = WorktreeLayer(git_repo)
    assert layer.is_git_repo() is True
    info = layer.create("exp1")
    assert info.name == "exp1"
    assert info.path.endswith("exp1")
    assert (git_repo / ".tuan" / "worktrees" / "exp1").is_dir()

    items = layer.list()
    names = [it.name for it in items]
    assert "exp1" in names

    path = layer.remove("exp1")
    assert not (git_repo / ".tuan" / "worktrees" / "exp1").exists()
    items = layer.list()
    assert "exp1" not in [it.name for it in items]


def test_switch_returns_path(git_repo):
    layer = WorktreeLayer(git_repo)
    layer.create("exp2")
    p = layer.switch("exp2")
    assert p.endswith("exp2")
    with pytest.raises(WorktreeError):
        layer.switch("not-exist")


def test_create_duplicate_fails(git_repo):
    layer = WorktreeLayer(git_repo)
    layer.create("dup")
    with pytest.raises(WorktreeError, match="已存在"):
        layer.create("dup")


def test_invalid_name_rejected(git_repo):
    layer = WorktreeLayer(git_repo)
    with pytest.raises(WorktreeError):
        layer.create("../evil")


def test_created_worktree_has_own_branch(git_repo):
    """回归证据: create 必须产出真实独立分支的 git worktree (非模拟目录)。"""
    layer = WorktreeLayer(git_repo)
    info = layer.create("iso1")
    # worktree 内 checkout 的分支应等于创建名
    r = _git(["rev-parse", "--abbrev-ref", "HEAD"], Path(info.path))
    assert r.stdout.strip() == "iso1"
    # 主仓库分支列表里能看到新分支
    branches = _git(["branch", "--list"], git_repo).stdout
    assert "iso1" in branches


def test_switch_returns_real_worktree_path(git_repo):
    """switch 返回的路径必须真实存在于磁盘, 且是 git 识别的工作树。"""
    layer = WorktreeLayer(git_repo)
    layer.create("iso2")
    p = layer.switch("iso2")
    wt = Path(p)
    assert wt.is_dir(), "switch 返回路径必须真实存在"
    # git worktree list 应包含该路径
    listed = [it.path for it in layer.list()]
    assert any(Path(x).resolve() == wt.resolve() for x in listed)


def test_worktree_isolation_between_main_and_exp(git_repo):
    """主工作区与实验 worktree 相互隔离: 在实验目录写文件不影响主工作区。"""
    layer = WorktreeLayer(git_repo)
    info = layer.create("iso3")
    wt = Path(info.path)
    # 在实验 worktree 里新建文件
    (wt / "exp_note.txt").write_text("experiment A\n", encoding="utf-8")
    # 主工作区不应出现该文件
    assert not (git_repo / "exp_note.txt").exists()
    # 实验 worktree 里能看到主工作区原有的 main.py (共享同一仓库对象库)
    assert (wt / "main.py").exists()
