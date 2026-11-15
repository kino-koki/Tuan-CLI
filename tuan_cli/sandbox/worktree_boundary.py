"""B2: worktree 创建路径的沙箱边界守卫。

对齐 Claude Code v2.1.319 修复的「沙箱内命令借 worktree 创建逃逸」。
目录里 ``worktree`` 已标 aligned（四子命令 + 隔离证明测试），但
``worktree_sandbox_escape`` 一直是 gap：需要证明**创建路径本身**在隔离
边界内，且 git 环境不被劫持到工作区之外。

实测的两个真实向量（都在远端主线上）：

1. ``WorktreeLayer._git`` 用 ``{**os.environ, **_GIT_NO_PROMPT_ENV}``
   继承完整父进程环境。``GIT_WORK_TREE`` / ``GIT_DIR`` /
   ``GIT_OBJECT_DIRECTORY`` / ``GIT_COMMON_DIR`` / ``GIT_INDEX_FILE``
   若指向工作区外，``git worktree add`` 会把元数据或对象写到边界外。
2. ``create()`` / ``create_agent_worktree()`` 只校验 ``name`` 不含路径
   分隔符，没有校验**解析后的 target** 仍在 workspace 之下（symlink
   祖先 / 绝对路径注入可越界）。

本模块提供：
  - :func:`assert_worktree_target`：解析后路径必须落在 workspace 内；
  - :func:`sanitize_git_env`：剥离可重定向 git 元数据位置的变量；
  - :func:`inspect_git_command`：拒绝 ``git -C <outside>`` 等显式越界参数。

**接线是真的**：``worktree_layer.py`` 的 ``create`` /
``create_agent_worktree`` / ``_git`` 都调用本模块，不是只写文档。
"""
from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

# 能把 git 的「仓库 / 工作树 / 对象库」重定向到别处的环境变量。
# 这些变量一旦带外部路径，worktree 创建就不再发生在 workspace 边界内。
_REDIRECT_ENV = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CEILING_DIRECTORIES", "GIT_NAMESPACE",
)


@dataclass(frozen=True)
class BoundaryProof:
    """可审计的边界证明；只记路径与理由，不记任何凭据。"""

    within: bool
    workspace: str
    target: str
    reason: str = ""
    stripped_env: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {"within": self.within, "workspace": self.workspace,
                "target": self.target, "reason": self.reason,
                "stripped_env": list(self.stripped_env)}


def _resolve(path: Any) -> Path:
    """解析路径；``strict=False`` 允许目标尚不存在（创建前校验）。

    对**已存在的祖先**做 symlink 解析，这样 ``.tuan/worktrees`` 若被换成
    指向外部的软链，也能被检出。
    """
    return Path(path).expanduser().resolve(strict=False)


def assert_worktree_target(workspace: Any, target: Any) -> BoundaryProof:
    """断言 worktree 目标目录在 workspace 边界内，越界直接抛 ValueError。

    调用方应把 ValueError 转成自己的领域异常；这里不 import worktree_layer
    避免循环依赖。
    """
    try:
        ws = _resolve(workspace)
        tg = _resolve(target)
    except (TypeError, ValueError, OSError) as exc:
        raise ValueError(f"worktree 边界校验失败（路径不可解析）: "
                         f"{type(exc).__name__}") from exc
    try:
        tg.relative_to(ws)
    except ValueError as exc:
        proof = BoundaryProof(False, str(ws), str(tg),
                              "worktree 目标解析后位于 workspace 之外")
        raise ValueError(proof.reason + f": target={tg} workspace={ws}") from exc
    # target 不能就是 workspace 根（那等于在主工作区里开 worktree）
    if tg == ws:
        raise ValueError("worktree 目标不能等于 workspace 根")
    return BoundaryProof(True, str(ws), str(tg), "target 在 workspace 边界内")


def sanitize_git_env(env: Any) -> Tuple[Dict[str, str], Tuple[str, ...]]:
    """剥离可重定向 git 元数据位置的变量。

    返回 ``(clean_env, stripped_names)``。脏输入（非 Mapping / 非 str
    键值）一律丢弃该条目，不静默继承；这与 egress.py 的口径一致。
    """
    if not isinstance(env, Mapping):
        return {}, tuple(_REDIRECT_ENV)
    out: Dict[str, str] = {}
    for k, v in env.items():
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        if k.upper() in _REDIRECT_ENV:
            continue
        out[k] = v
    stripped = tuple(k for k in _REDIRECT_ENV if k in env)
    return out, stripped


def inspect_git_command(args: Iterable[str]) -> Tuple[bool, str]:
    """拒绝显式把 git 切到别处的参数（``-C <path>`` / ``--git-dir`` 等）。

    这是**辅助**防线：主要边界靠 ``cwd=workspace`` + ``sanitize_git_env``
    + ``assert_worktree_target`` 三件事。本函数只检查 argv 形态，不解析路径。
    """
    if isinstance(args, (str, bytes)) or not isinstance(args, Iterable):
        return False, "git 参数不是可迭代的 argv 列表"
    seq = list(args)
    for a in seq:
        if not isinstance(a, str):
            return False, "git 参数含非字符串"
        low = a.strip()
        if low in ("-C", "--git-dir", "--work-tree", "--namespace"):
            return False, f"git 参数 {a!r} 可把仓库/工作树重定向到边界外"
        if low.startswith("--git-dir=") or low.startswith("--work-tree="):
            return False, f"git 参数 {a!r} 可把仓库/工作树重定向到边界外"
        if low == "--" :
            break
    return True, ""


def strip_credentials_from_git_env(env: Any) -> Dict[str, str]:
    """便捷入口：先按 egress 口径净化凭据，再剥离 git 重定向变量。

    真实凭据交给 ``egress.build_child_env`` 处理（sentinel），这里只做
    git 元数据边界；两层互不替代。
    """
    from .egress import build_child_env
    clean, _masked, _dropped, _invalid = build_child_env(env)
    out, _stripped = sanitize_git_env(clean)
    return out


def current_git_redirect_vars() -> Tuple[str, ...]:
    """可观测：当前进程环境里有哪些重定向变量（只记名字，不记值）。"""
    return tuple(k for k in _REDIRECT_ENV if k in os.environ)
