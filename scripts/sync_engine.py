#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine 双源同步工具 (Task D).

把根目录 ``tuan_cli/`` 同步到 ``Tuan-App/engine/tuan_cli/``.

背景
----
``Tuan-App/engine/tuan_cli/`` 是 ``tuan_cli`` 的完整第二份拷贝 —— Tauri 打包把
``engine/tuan_cli`` 作为 resource 打进安装包, 桌面版应用实际跑的是这份副本.
它靠手工拷贝, 与根目录已经漂移 (web/frontend.py / tui/tui.py 等文件字节数差
几百到几千, 安全修复不会同步过去).

设计要点
--------
1. **文件级 rsync 语义**: 新增/更新/删除; 双向比对, 以根目录为真源.
2. **只处理受管后缀**: 只同步 MANAGED_SUFFIX 中的文件 (源码/文档/配置),
   避免误删引擎目录里可能有但未在源里存在的运行时产物.
3. **跳过 ``__pycache__`` / ``*.pyc``**: 可再生, 不同解释器版本的字节码
   留在包体里是遮蔽风险, 且纯浪费体积.
4. **纯 stdlib**: 无第三方依赖, CI 无安装环境也能跑.
5. **两种模式**:
     ``python scripts/sync_engine.py``          实际同步
     ``python scripts/sync_engine.py --check``  只比对, 漂移则 exit 1
     ``python scripts/sync_engine.py --dry-run`` 预览将要发生的改动

退出码
------
  0  同步成功 / --check 无差异
  1  --check 检测到漂移
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tuan_cli"
DEST = ROOT / "Tuan-App" / "engine" / "tuan_cli"

# 不同步的目录 (缓存 / 虚拟环境 / 运行时状态)
SKIP_DIRS = {
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis",
    "htmlcov", "coverage", ".venv", "venv", "env", ".git", "node_modules",
    ".tox", ".nox", "dist", "build", ".runtime-home", ".runtime-ws",
}

# 受管后缀: 只有这些类型才参与同步与删除比对 (避免误删引擎目录里的手工产物)
MANAGED_SUFFIX = {
    ".py", ".pyi", ".md", ".rst", ".txt", ".yaml", ".yml", ".json", ".toml",
    ".ini", ".cfg", ".lock", ".css", ".html", ".svg", ".png", ".jpg", ".jpeg",
    ".gif", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".xml", ".env",
}


def _skip_dir_name(name: str) -> bool:
    return name in SKIP_DIRS


def _managed_file(p: Path) -> bool:
    if p.suffix.lower() in {".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib",
                            ".db", ".sqlite"}:
        return False
    return p.suffix.lower() in MANAGED_SUFFIX


def _iter_managed_files(root: Path) -> dict[str, Path]:
    """遍历 root, 返回 {相对 posix 路径: 绝对 Path} 映射 (只含受管文件)."""
    out: dict[str, Path] = {}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if not _managed_file(p):
            continue
        out[p.relative_to(root).as_posix()] = p
    return out


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def plan_sync() -> tuple[list[str], list[str], list[str]]:
    """返回 (to_add, to_update, to_delete) —— 相对路径列表.

    - to_add:    源里有, 目标没有
    - to_update: 两边都有但内容 (sha256) 不一致
    - to_delete: 目标里有, 源里没有 (只处理受管后缀)
    """
    src_files = _iter_managed_files(SRC)
    if not DEST.exists():
        # 目标目录不存在: 视为空, 所有源文件都要 add
        dest_files: dict[str, Path] = {}
    else:
        dest_files = _iter_managed_files(DEST)

    add: list[str] = []
    update: list[str] = []
    delete: list[str] = []

    for rel, src_p in src_files.items():
        if rel not in dest_files:
            add.append(rel)
        elif _sha256(src_p) != _sha256(dest_files[rel]):
            update.append(rel)

    for rel, _ in dest_files.items():
        if rel not in src_files:
            delete.append(rel)

    return sorted(add), sorted(update), sorted(delete)


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KiB"
    return f"{n / 1024 / 1024:.2f} MiB"


def apply_sync(add: list[str], update: list[str], delete: list[str],
               dry_run: bool = False) -> None:
    for rel in add:
        src = SRC / rel
        dst = DEST / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        action = "would add" if dry_run else "add"
        print(f"  {action}: {rel}  ({_fmt_size(src.stat().st_size)})")
        if not dry_run:
            shutil.copy2(src, dst)
    for rel in update:
        src = SRC / rel
        dst = DEST / rel
        action = "would update" if dry_run else "update"
        print(f"  {action}: {rel}  ({_fmt_size(src.stat().st_size)})")
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    for rel in delete:
        dst = DEST / rel
        action = "would delete" if dry_run else "delete"
        print(f"  {action}: {rel}")
        if not dry_run:
            dst.unlink(missing_ok=True)
            # 回收空目录
            d = dst.parent
            for _ in range(20):
                if d == DEST or d == DEST.parent or not d.exists():
                    break
                try:
                    if any(d.iterdir()):
                        break
                    d.rmdir()
                except OSError:
                    break
                d = d.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sync tuan_cli/ to Tuan-App/engine/tuan_cli/.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="Only compare; exit 1 on any drift (CI gate).")
    mode.add_argument("--dry-run", action="store_true",
                      help="Preview changes without touching the filesystem.")
    args = parser.parse_args(argv)

    add, update, delete = plan_sync()

    if args.check:
        if not (add or update or delete):
            print("engine bundle in sync: no drift detected.")
            return 0
        print(
            f"engine bundle DRIFT DETECTED: "
            f"+{len(add)} new, ~{len(update)} modified, -{len(delete)} stale"
        )
        if add:
            print("\n[NEW] (in tuan_cli/ but missing in engine/tuan_cli/)")
            for rel in add:
                print(f"  + tuan_cli/{rel}")
        if update:
            print("\n[MODIFIED] (content differs between source and engine)")
            for rel in update:
                print(f"  ~ tuan_cli/{rel}")
        if delete:
            print("\n[STALE] (in engine/tuan_cli/ but not in tuan_cli/)")
            for rel in delete:
                print(f"  - Tuan-App/engine/tuan_cli/{rel}")
        print(
            "\nRun `python scripts/sync_engine.py` to bring the engine "
            "bundle back in sync."
        )
        return 1

    # 实际同步 / dry-run
    total = len(add) + len(update) + len(delete)
    if total == 0:
        print("engine bundle already in sync; nothing to do.")
        return 0
    verb = "Planned changes:" if args.dry_run else "Syncing..."
    print(verb)
    apply_sync(add, update, delete, dry_run=args.dry_run)
    print(f"\nDone. {len(add)} added, {len(update)} updated, {len(delete)} deleted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
