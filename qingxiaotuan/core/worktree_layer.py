"""Worktree 层 —— git worktree 集成 (四层边界 · 第四层)。

理念: "Worktree 层 = 并行修改时使用"。
想同时试两个方向 (方案 A / 方案 B), 又不想 stash 来 stash 去、互相污染工作区?
给每个实验开一个 git worktree, 各自独立目录、独立分支, 跑完合并或丢弃。

命令:
- /worktree create <name>   git worktree add .qxt/worktrees/<name>
- /worktree list            列出所有 worktree
- /worktree remove <name>   git worktree remove
- /worktree switch <name>   切换当前工作目录到指定 worktree (返回路径, 由 TUI 执行 chdir)

非 git 仓库时友好提示先 git init。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


class WorktreeError(Exception):
    """worktree 操作失败 (非 git 仓库 / 名字冲突 / git 命令失败)。"""


@dataclass
class WorktreeInfo:
    name: str
    path: str
    head: str = ""
    branch: str = ""


class WorktreeLayer:
    """git worktree 管理层 (每个项目一份)。"""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.dir = self.workspace / ".qxt" / "worktrees"

    # ------------------------------------------------------------ 前置检查

    def is_git_repo(self) -> bool:
        """当前工作区是否为 git 仓库根目录。

        判定标准: ``git rev-parse --show-toplevel`` 返回的仓库根路径必须与
        ``self.workspace`` 解析后的绝对路径一致 —— 即"工作区自身就是仓库根",
        而非"工作区只是某个仓库的子目录"。后者 (例如 pytest 临时目录落在
        项目根下) 不应被当作仓库根去创建 worktree。

        git 不存在 / 超时 / 其他异常时按"非仓库"处理 (返回 False):
        worktree 属于可选增强, 探针失败应优雅跳过, 不应让异常冒泡打断主流程。
        """
        if not self.workspace.exists():
            return False
        try:
            r = self._git(["rev-parse", "--show-toplevel"], check=False)
        except Exception:  # noqa: BLE001  (TimeoutExpired / FileNotFoundError 等)
            return False
        if r.returncode != 0:
            return False
        toplevel = r.stdout.strip()
        if not toplevel:
            return False
        try:
            return Path(toplevel).resolve() == self.workspace
        except Exception:  # noqa: BLE001  (路径解析异常兜底)
            return False

    def _require_git(self) -> None:
        if not self.is_git_repo():
            raise WorktreeError(
                "当前目录不是 git 仓库。请先初始化:\n"
                "  git init && git add -A && git commit -m 'initial'\n"
                "然后再创建 worktree 做并行实验。"
            )

    def _wt_path(self, name: str) -> Path:
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            raise WorktreeError(f"非法 worktree 名: {name!r} (不能含路径分隔符)")
        return self.dir / name

    # ------------------------------------------------------------ 操作

    def create(self, name: str, base: Optional[str] = None) -> WorktreeInfo:
        """创建 worktree: git worktree add .qxt/worktrees/<name> [-b <name>]。"""
        self._require_git()
        target = self._wt_path(name)
        if target.exists():
            raise WorktreeError(f"worktree 已存在: {target}")
        self.dir.mkdir(parents=True, exist_ok=True)
        # 新分支 <name> 挂在当前 HEAD 上
        cmd = ["worktree", "add", "-b", name, str(target)]
        if base:
            cmd.append(base)
        r = self._git(cmd)
        if r.returncode != 0:
            raise WorktreeError(
                f"git worktree add 失败: {r.stderr.strip() or r.stdout.strip()}"
            )
        return WorktreeInfo(name=name, path=str(target), branch=name)

    def list(self) -> List[WorktreeInfo]:
        """列出所有 worktree (含主工作区)。"""
        if not self.is_git_repo():
            return []
        r = self._git(["worktree", "list", "--porcelain"])
        if r.returncode != 0:
            raise WorktreeError(f"git worktree list 失败: {r.stderr.strip()}")
        out: List[WorktreeInfo] = []
        cur: dict = {}
        for line in r.stdout.splitlines():
            if not line.strip():
                if cur:
                    out.append(self._parse(cur))
                    cur = {}
                continue
            if line.startswith("worktree "):
                cur["path"] = line[len("worktree ") :]
            elif line.startswith("HEAD "):
                cur["head"] = line[len("HEAD ") :][:8]
            elif line.startswith("branch "):
                cur["branch"] = line[len("branch refs/heads/") :]
        if cur:
            out.append(self._parse(cur))
        return out

    def _parse(self, cur: dict) -> WorktreeInfo:
        path = cur.get("path", "")
        name = (
            Path(path).name if Path(path).resolve() != self.workspace else "(主工作区)"
        )
        return WorktreeInfo(
            name=name,
            path=path,
            head=cur.get("head", ""),
            branch=cur.get("branch", ""),
        )

    def remove(self, name: str) -> str:
        """删除 worktree: git worktree remove。"""
        self._require_git()
        target = self._wt_path(name)
        if not target.exists():
            raise WorktreeError(f"worktree 不存在: {target}")
        r = self._git(["worktree", "remove", str(target)])
        if r.returncode != 0:
            raise WorktreeError(
                f"git worktree remove 失败: {r.stderr.strip() or r.stdout.strip()}\n"
                f"(worktree 内有未提交改动时需先处理, 或用 --force)"
            )
        return str(target)

    def switch(self, name: str) -> str:
        """返回指定 worktree 的绝对路径 (真正 chdir 由 TUI/调用方执行)。"""
        self._require_git()
        target = self._wt_path(name)
        if not target.exists():
            raise WorktreeError(
                f"worktree 不存在: {target} (先 /worktree create {name})"
            )
        return str(target)

    # ------------------------------------------------------------ git 封装

    def _git(
        self, args: List[str], check: bool = True
    ) -> "subprocess.CompletedProcess":
        r = subprocess.run(
            ["git"] + args,
            cwd=str(self.workspace),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if check and r.returncode != 0:
            # 让调用方决定怎么报错; 这里抛一次便于快速失败
            pass
        return r
