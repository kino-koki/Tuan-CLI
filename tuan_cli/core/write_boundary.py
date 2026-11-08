"""工具层写路径硬边界 —— 对标 Claude Code
``permissions.blockWritesOutsideWorkingDirectories`` (v2.1.314，默认关)。

**为什么单独一个模块**

`tools/filesystem.py::_resolve` 是**读路径**裁决：路径必须落在工作区或
本会话 ``/add-dir`` 授权的目录里。但 ``/add-dir`` 的 REPL 帮助、函数
docstring 与模块注释三处都写「仅读 / 可读上下文」，实测却同时放宽了
``write_file`` / ``edit_file`` / ``move_file`` / ``delete_file`` /
``delete_dir`` —— 一条 ``/add-dir /tmp/ext`` 之后，Agent 能在工作区外
创建、改名、删除文件。确认对话（dangerous 提示）不是路径硬边界：
无人值守 / YOLO / 直接函数调用都不经过它。

Claude Code 的做法是在 **Write / Edit / NotebookEdit 工具层**硬拒绝
越出工作目录的写（配置开关，默认关闭）。本模块把这个约束做成
**可显式开启、默认不改既有行为**的单一裁决出口：

- ``False``（出厂默认，与 CC 一致）：保留既有 ``_resolve`` 语义，
  ``/add-dir`` 授权目录仍可写。**不做破坏性默认变更**。
- ``True``：所有写路径必须落在 ``工作区 ∪ 显式 writable 授权根`` 内；
  ``/add-dir`` 默认只授读，写要由用户在 REPL 显式
  ``/add-dir <path> --writable`` 授予。
- 配置值非 bool（拼错成 ``"true"`` / ``1``）→ **fail-closed 启用**并
  在 reason 里说明，绝不把 ``bool("false")`` 的 Python 陷阱变成静默放行。

**刻意不做的两件事（如实）**

1. 不管命令层重定向（``echo x > /tmp/out``）。那是 shell 命令文本 /
   OS 沙箱的职责，本模块只管文件系统工具层；CC 也靠 sandbox 规则覆盖
   命令层，不是靠这个开关。
2. 不宣称消除 TOCTOU。写入前会**重新解析父目录链**（能抓住
   ``_resolve`` 之后被换成 symlink 的常见竞态），但检查与
   ``os.replace`` 之间仍有窗口；彻底消除需要 ``O_NOFOLLOW`` + ``dir_fd``
   系列，会改动既有原子写实现，本轮不做。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Tuple

FLAG = "permissions.blockWritesOutsideWorkingDirectories"
WRITABLE_DIRS_ATTR = "extra_writable_dirs"

#: 受边界管辖的操作名（仅用于诊断文本，不改变判定）
WRITE_OPS = frozenset({
    "write", "edit", "edit_batch", "move_dst", "delete", "delete_dir",
})


@dataclass(frozen=True)
class WriteDecision:
    """一次写路径裁决的结果。

    ``enforced`` 表示边界是否真的被求值（开关开启 / 配置非法时 fail-closed
    开启）。``False`` 时 ``allowed`` 恒为 True 且只是兼容旧行为，调用方
    不能把它当成「已通过安全检查」来宣称。
    """

    allowed: bool
    enforced: bool
    reason: str = ""
    resolved: Optional[Path] = None


def _cfg(ctx: Any, dotted: str, default: Any) -> Any:
    try:
        return ctx.config(dotted, default)
    except Exception:  # noqa: BLE001 - 配置对象损坏时不掀翻裁决
        return default


def boundary_enabled(ctx: Any) -> Tuple[bool, str]:
    """返回 (是否启用, 额外说明)。配置非法按 fail-closed 启用。"""
    raw = _cfg(ctx, FLAG, False)
    if raw is None:
        return False, ""
    if isinstance(raw, bool):
        return raw, ""
    return True, (
        f"{FLAG}={raw!r} 类型非法 (应为 bool); 按 fail-closed 启用写边界"
    )


def writable_roots(ctx: Any) -> List[Path]:
    """显式授予可写的额外根（per-session 内存态，Agent 不能自助授权）。"""
    raw = getattr(ctx, WRITABLE_DIRS_ATTR, None) or []
    out: List[Path] = []
    for d in raw:
        try:
            out.append(Path(d).resolve())
        except (OSError, TypeError, ValueError):  # noqa: BLE001
            continue
    return out


def allowed_roots(ctx: Any) -> List[Path]:
    try:
        ws = Path(ctx.workspace).resolve()
    except (OSError, TypeError, ValueError):  # noqa: BLE001
        return []
    return [ws] + writable_roots(ctx)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _roots_contain(path: Path, roots: List[Path]) -> bool:
    return bool(roots) and any(_inside(path, r) for r in roots)


def recheck_write(ctx: Any, resolved: Path, *, op: str = "write") -> Optional[str]:
    """对**已解析**的写目标做边界裁决；返回错误串表示应拒绝，``None`` 放行。

    供 ``filesystem._resolve_write`` 与 ``edit_files`` 写入阶段复用，
    保证「检查点」和「实际写入点」用的是同一份真值（单一出口）。
    """
    enabled, note = boundary_enabled(ctx)
    if not enabled:
        return None
    roots = allowed_roots(ctx)
    if not roots:
        return (f"[已拒绝] 写边界无法解析工作区 (fail-closed): {op}; "
                f"{note}" if note else
                f"[已拒绝] 写边界无法解析工作区 (fail-closed): {op}")
    if not _roots_contain(resolved, roots):
        return (
            f"[已拒绝] 写路径越出工作目录 ({op}): {resolved}\n"
            f"permissions.blockWritesOutsideWorkingDirectories=true 时，"
            f"写/改/移/删只能落在工作区或显式 writable 授权根内。\n"
            f"如需可写，请在 REPL 用 `/add-dir <绝对路径> --writable` 显式授权；"
            f"普通 `/add-dir` 只授予读取上下文。" +
            (f"\n配置提示: {note}" if note else "")
        )
    # TOCTOU 二次复检：父目录链在 _resolve 之后可能被替换成 symlink。
    # 只重新解析父目录，不缓存、不依赖文件系统时间点做业务判定。
    try:
        fresh_parent = resolved.parent.resolve()
    except (OSError, ValueError, TypeError) as exc:  # noqa: BLE001
        return (f"[已拒绝] 写目标父目录重新解析失败 (fail-closed, {op}): "
                f"{type(exc).__name__}")
    if not _roots_contain(fresh_parent, roots):
        return (
            f"[已拒绝] 写目标父目录已越出可写根 ({op}): {fresh_parent}\n"
            f"疑似 symlink 替换 / 路径竞态 (TOCTOU)，按 fail-closed 拒绝。"
        )
    return None


def decide_write(ctx: Any, raw_path: str, *, op: str = "write") -> WriteDecision:
    """从原始路径串做完整裁决（解析 + 边界），供外部调用与测试。"""
    enabled, note = boundary_enabled(ctx)
    try:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = Path(ctx.workspace).resolve() / candidate
        resolved = candidate.resolve()
    except (OSError, ValueError, TypeError) as exc:  # noqa: BLE001
        return WriteDecision(
            allowed=False, enforced=True,
            reason=f"写路径无法解析 (fail-closed): {type(exc).__name__}")
    if not enabled:
        # 出厂默认：保留既有行为，明确标记「边界未求值」，绝不宣称已受保护
        return WriteDecision(allowed=True, enforced=False, reason="", resolved=resolved)
    err = recheck_write(ctx, resolved, op=op)
    if err:
        return WriteDecision(False, True, err, resolved)
    return WriteDecision(True, True, note, resolved)
