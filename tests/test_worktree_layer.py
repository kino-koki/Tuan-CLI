"""B4: Worktree 层测试 —— create/list/remove (临时 git 仓库)、非 git 仓库处理。"""

from __future__ import annotations

import subprocess

import pytest

from qingxiaotuan.core.worktree_layer import WorktreeError, WorktreeLayer


def _git(args, cwd):
    return subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, text=True, timeout=30)


@pytest.fixture()
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], repo)
    _git(["config", "user.email", "test@qxt.dev"], repo)
    _git(["config", "user.name", "qxt-test"], repo)
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
    assert (git_repo / ".qxt" / "worktrees" / "exp1").is_dir()

    items = layer.list()
    names = [it.name for it in items]
    assert "exp1" in names

    path = layer.remove("exp1")
    assert not (git_repo / ".qxt" / "worktrees" / "exp1").exists()
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
