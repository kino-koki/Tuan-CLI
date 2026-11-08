"""Worktree 层 —— git worktree 集成 (四层边界 · 第四层)。

理念: "Worktree 层 = 并行修改时使用"。
想同时试两个方向 (方案 A / 方案 B), 又不想 stash 来 stash 去、互相污染工作区?
给每个实验开一个 git worktree, 各自独立目录、独立分支, 跑完合并或丢弃。

命令:
- /worktree create <name>   git worktree add .tuan/worktrees/<name>
- /worktree list            列出所有 worktree
- /worktree remove <name>   git worktree remove
- /worktree switch <name>   切换当前工作目录到指定 worktree (返回路径, 由 TUI 执行 chdir)

非 git 仓库时友好提示先 git init。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# ---- OP-1: 子代理 ephemeral worktree 常量 ----------------------------------
# ephemeral slug 前缀: 精确圈定可自动清理的子代理 worktree, 绝不碰用户命名。
# agent- 后必须跟 >=7 位 hex (防误伤 "agent-work" 这类用户命名);
# wf_/bridge-/job- 为宽前缀 (worktree 名不含路径分隔符, 后缀任意非 /)。
_EPHEMERAL_SLUG_RE = re.compile(
    r"^(?:agent-[0-9a-f]{7,}|wf_|bridge-|job-)[^/]*$"
)
# git 子进程防挂起: 凭据提示 / ssh 交互都会让 worktree 命令永远等待。
_GIT_NO_PROMPT_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
    "GIT_SSH_COMMAND": "ssh -o BatchMode=yes",
}
_SESSION_FILE_NAME = "worktree_sessions.json"


def _flatten_slug(slug: str) -> str:
    """把可能含路径分隔符的 slug 拍平为合法 git ref 名。

    对标 Claude Code flattenSlug: user/feature -> user+feature
    (规避 git ref 的 D/F 冲突与非法字符)。
    """
    flat = re.sub(r"[/\\_]+", "+", slug or "")
    flat = re.sub(r"[~^:?*\[\]\\\s]+", "-", flat)
    return flat.strip("+.-") or "default"


class WorktreeError(Exception):
    """worktree 操作失败 (非 git 仓库 / 名字冲突 / git 命令失败)。"""


@dataclass
class WorktreeInfo:
    name: str
    path: str
    head: str = ""
    branch: str = ""


@dataclass
class WorktreeSession:
    """会话级 worktree 状态 (对标 Claude Code WorktreeSession)。

    记录进入 worktree 前的现场, 供退出时干净回原态 / 崩溃后恢复:
      original_cwd / original_branch / original_head
    """
    session_id: str
    spec_id: str                 # 绑定的子代理/会话 id
    worktree_path: str
    branch: str
    original_cwd: str
    original_branch: str
    original_head: str
    created_at: float = 0.0
    status: str = "active"       # active | finished | orphaned

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "spec_id": self.spec_id,
            "worktree_path": self.worktree_path,
            "branch": self.branch,
            "original_cwd": self.original_cwd,
            "original_branch": self.original_branch,
            "original_head": self.original_head,
            "created_at": self.created_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorktreeSession":
        return cls(
            session_id=data.get("session_id", ""),
            spec_id=data.get("spec_id", ""),
            worktree_path=data.get("worktree_path", ""),
            branch=data.get("branch", ""),
            original_cwd=data.get("original_cwd", ""),
            original_branch=data.get("original_branch", ""),
            original_head=data.get("original_head", ""),
            created_at=data.get("created_at", 0.0),
            status=data.get("status", "orphaned"),
        )


def _sessions_path(home: Optional[str | Path] = None) -> Path:
    base = Path(home) if home else Path.home() / ".tuan"
    return base / _SESSION_FILE_NAME


def save_worktree_state(session: WorktreeSession, home: Optional[str | Path] = None) -> None:
    """持久化 worktree 会话状态 (崩溃后可恢复现场)。"""
    path = _sessions_path(home)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        data[session.session_id] = session.to_dict()
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass  # 状态持久化是增强项, 失败不阻断工作流


def load_worktree_states(home: Optional[str | Path] = None) -> dict:
    """读取全部持久化 worktree 会话状态。"""
    path = _sessions_path(home)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {sid: WorktreeSession.from_dict(d) for sid, d in raw.items()}
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}


def delete_worktree_state(session_id: str, home: Optional[str | Path] = None) -> None:
    """删除一条持久化 worktree 会话状态 (清理完成后)。"""
    path = _sessions_path(home)
    try:
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop(session_id, None)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        pass


class WorktreeLayer:
    """git worktree 管理层 (每个项目一份)。"""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.dir = self.workspace / ".tuan" / "worktrees"

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
        """创建 worktree: git worktree add .tuan/worktrees/<name> [-b <name>]。"""
        self._require_git()
        target = self._wt_path(name)
        # B2: 证明创建目标本身在 workspace 边界内（含 symlink 祖先解析）。
        # 放在 exists 检查之前，避免「已存在的越界路径」被直接复用。
        from ..sandbox.worktree_boundary import assert_worktree_target
        try:
            self.last_boundary_proof = assert_worktree_target(self.workspace, target)
        except ValueError as exc:
            raise WorktreeError(f"worktree 边界校验失败: {exc}") from exc
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

    # ------------------------------------------------------------ 子代理 (OP-1)

    def _agent_wt_name(self, spec_id: str, slug: str = "work") -> str:
        """ephemeral 命名: agent-<spec 尾 7 位>-<flattened slug>。"""
        tail = re.sub(r"[^0-9a-fA-F]", "", str(spec_id))[-7:] or "0" * 7
        return f"agent-{tail.lower()}-{_flatten_slug(slug)}"

    def _branch_exists(self, branch: str) -> bool:
        r = self._git(["branch", "--list", branch])
        return r.returncode == 0 and bool(r.stdout.strip())

    def create_agent_worktree(
        self, spec_id: str, slug: str = "work",
        original_cwd: Optional[str] = None,
    ) -> WorktreeInfo:
        """为子代理创建/复用隔离 worktree (对标 Claude Code createAgentWorktree)。

        - 不触碰全局会话状态 (不 chdir、不写 project config);
        - 已存在即复用 (fast-resume: .git 指针存在即视为有效);
        - 分支已存在时不带 -b 直接挂 (跨进程复用同一 worktree 的场景)。
        """
        self._require_git()
        name = self._agent_wt_name(spec_id, slug)
        target = self._wt_path(name)
        # B2: fast-resume 分支在下方直接 return，边界断言必须放在它之前，
        # 否则已注册的越界路径会绕过校验被复用。
        from ..sandbox.worktree_boundary import assert_worktree_target
        try:
            self.last_boundary_proof = assert_worktree_target(self.workspace, target)
        except ValueError as exc:
            raise WorktreeError(f"worktree 边界校验失败: {exc}") from exc
        # fast-resume: worktree 已注册 (路径存在且含 .git 指针) 直接复用
        if target.exists() and (target / ".git").exists():
            return WorktreeInfo(name=name, path=str(target), branch=name)

        self.dir.mkdir(parents=True, exist_ok=True)
        if self._branch_exists(name):
            cmd = ["worktree", "add", str(target), name]
        else:
            cmd = ["worktree", "add", "-b", name, str(target)]
        r = self._git(cmd)
        if r.returncode != 0:
            raise WorktreeError(
                f"git worktree add 失败: {r.stderr.strip() or r.stdout.strip()}"
            )
        info = WorktreeInfo(name=name, path=str(target), branch=name)

        # 持久化会话状态 (崩溃后 cleanup 可定位/恢复)
        session = WorktreeSession(
            session_id=uuid.uuid4().hex[:12],
            spec_id=spec_id,
            worktree_path=str(target),
            branch=name,
            original_cwd=str(original_cwd or self.workspace),
            original_branch=self._current_branch(),
            original_head=self._current_head(),
        )
        save_worktree_state(session)
        return info

    def _current_branch(self) -> str:
        r = self._git(["rev-parse", "--abbrev-ref", "HEAD"], check=False)
        return r.stdout.strip() if r.returncode == 0 else ""

    def _current_head(self) -> str:
        r = self._git(["rev-parse", "HEAD"], check=False)
        return r.stdout.strip() if r.returncode == 0 else ""

    def remove_agent_worktree(self, name: str) -> str:
        """清理子代理 worktree, fail-closed:

        - 非 ephemeral 前缀绝不自动删 (不碰用户命名 worktree);
        - 有未提交改动 / 未推送提交 -> 跳过并说明 (交给 cleanup 兜底或人工处理);
        - remove 后 sleep(100ms) 再删分支 (Windows 文件句柄释放时序)。
        """
        self._require_git()
        if not _EPHEMERAL_SLUG_RE.match(name):
            return f"跳过: {name} 非 ephemeral worktree, 不自动清理"
        target = self._wt_path(name)
        if not target.exists():
            return f"跳过: {name} 不存在"

        # 未提交改动检测 (在 worktree 内跑, 而非主工作区)
        st = self._git(["status", "--porcelain"], cwd=target, check=False)
        if st.stdout.strip():
            return f"跳过: {name} 有未提交改动, 不自动清理"

        # 未推送检测: 有 upstream 且本地领先 -> 跳过
        br = self._git(["status", "-sb"], cwd=target, check=False)
        ahead = "ahead" in br.stdout or "[ahead" in br.stdout
        if ahead:
            return f"跳过: {name} 有未推送提交, 不自动清理"

        r = self._git(["worktree", "remove", "--force", str(target)], check=False)
        if r.returncode != 0:
            return f"跳过: {name} remove 失败: {r.stderr.strip()[:200]}"
        time.sleep(0.1)
        # 分支删除: 若已被合并/引用则 -D 兜底 (该分支只属于此 ephemeral worktree)
        self._git(["branch", "-D", name], check=False)
        return f"已清理: {name}"

    def cleanup_stale_agent_worktrees(self) -> List[str]:
        """清理全部 ephemeral 子代理 worktree (agent-*/wf_*/bridge-*/job-*)。

        只按前缀精确圈定; 用户命名 worktree 一律不动; 每个清理独立 fail-closed。
        """
        out: List[str] = []
        for item in self.list():
            if item.name == "(主工作区)":
                continue
            if not _EPHEMERAL_SLUG_RE.match(item.name):
                continue
            out.append(self.remove_agent_worktree(item.name))
        return out

    # ------------------------------------------------------------ git 封装

    def _git(
        self, args: List[str], check: bool = True,
        cwd: Optional[str | Path] = None, timeout: int = 30,
    ) -> "subprocess.CompletedProcess":
        # B2: 拒绝可把仓库/工作树/对象库重定向到边界外的 argv 与环境变量。
        # 真实凭据由 sandbox/egress.py 在统一执行层处理，这里只守 git 元数据边界。
        from ..sandbox.worktree_boundary import (
            inspect_git_command, sanitize_git_env,
        )
        argv_ok, argv_reason = inspect_git_command(args)
        if not argv_ok:
            raise WorktreeError(f"git 参数越界: {argv_reason}")
        env, stripped = sanitize_git_env({**os.environ, **_GIT_NO_PROMPT_ENV})
        self.last_git_stripped_env = stripped
        r = subprocess.run(
            ["git"] + args,
            cwd=str(cwd or self.workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        if check and r.returncode != 0:
            # 让调用方决定怎么报错; 这里抛一次便于快速失败
            pass
        return r
