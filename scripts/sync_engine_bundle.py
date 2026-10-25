#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步打包引擎副本：`tuan_cli/` → `Tuan/engine/tuan_cli/`。

为什么要这个脚本
----------------
`Tuan/src-tauri/tauri.conf.json` 把 `../engine/tuan_cli` 作为 resource 打进
安装包；开发时 `engine_chat::engine_root()` 也按 `Tuan/engine` 解析。
也就是说**应用运行的引擎代码来自 `Tuan/engine/tuan_cli/` 这份副本，
而不是仓库根的 `tuan_cli/`**。

这份副本过去靠手工拷贝，已经落后主分支：23 个文件内容不一致、2 个文件整个缺失
（`core/output_sanitize.py` —— 输出净化层，负责硬移除 emoji / pictograph，
避免在 HTML/PPT 里渲染成豆腐方框；`models/timeout_policy.py` —— 读超时单一真相源）。
而 `version.py` 两边的 `__version__` 都是 0.3.1，所以界面显示的引擎版本号
**完全无法暴露这个差异** —— 这是最危险的部分：用户看到 0.3.1，实际跑的是旧代码。

设计要点
--------
1. **只同步源码**：排除 `__pycache__` / `*.pyc`（可再生、且来自别的解释器版本，
   留在包体里既占体积又有极小概率的字节码遮蔽风险）、测试缓存、venv。
2. **会清理陈旧文件**：删除副本里有、源里没有的文件（限受管扩展名），并回收空目录。
3. **留下指纹**：写 `Tuan/engine/.bundle_manifest.json`（逐文件 sha256），
   之后即使没人记得跑本脚本，也能一键发现漂移（见 `--check` 与
   `Tuan/scripts/sync-engine.mjs`）。

用法
----
  python scripts/sync_engine_bundle.py              # 执行同步
  python scripts/sync_engine_bundle.py --check      # 只比对，漂移则退出码 1
  python scripts/sync_engine_bundle.py --dry-run    # 预览将要发生的改动
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tuan_cli"
# 目的地解析：桌面端工程原名 Tuan-App，已更名为 Tuan。优先 Tuan/engine；
# 旧名目录仍存在时（并行任务/历史布局）自动回退，两条布局都能同步。
DEST_ROOT = ROOT / "Tuan" / "engine"
if not DEST_ROOT.is_dir() and (ROOT / "Tuan-App" / "engine").is_dir():
    DEST_ROOT = ROOT / "Tuan-App" / "engine"
DEST = DEST_ROOT / "tuan_cli"
MANIFEST = DEST_ROOT / ".bundle_manifest.json"
MANIFEST_SCHEMA = "tuan-engine-bundle-v1"

# 不同步的目录（缓存 / 虚拟环境 / 测试产物）
SKIP_DIRS = {
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis",
    "htmlcov", "coverage", ".venv", "venv", "env", ".git", "node_modules",
    ".tox", ".nox", "dist", "build",
    # 运行时状态（应用自建虚拟环境与运行数据），不属于源码，不参与同步与校验
    ".runtime-home", ".runtime-ws",
    # ---- Tuan 桌面壳枝剪：引擎不需要的 CLI/TUI/开发工具模块 ----
    # 判定标准（三重验证）：
    #   1. 绝对导入 grep: 无 `from tuan_cli.<mod>` 其他子目录
    #   2. 相对导入 grep: 无 `from ..<mod>` / `from .<mod>` 硬依赖
    #   3. runtime 隔离: 仅被 cli/* 命令惰性引用（python -m tuan_cli web 路径不触发）
    # 注意: 曾误将 vision/ports/harden 纳入，实测 core/agent.py 硬依赖 vision，
    #       core/telemetry.py 惰性引用 ports，core/security_auditor.py 惰性引用 harden
    #       —— 这些一旦剥离，-S 模式 (无 site-packages) 下引擎启动直接崩溃。
    "tui",       # 终端 TUI 界面。引用链: cli/user_commands.py → ui/fullscreen.py → tui.win_compat（CLI 专用）
    "gh",        # GitHub CLI 集成。唯一引用: cli/cmd_gh.py（纯 CLI）
    "code_edit", # 代码编辑子代理。零外部 import（仅 self-reference）
    "acp",       # 顶层 ACP 协议入口。唯一引用: cli/cmd_acp.py（runtime/acp 独立保留）
}
# 按 glob 匹配的目录后缀（如 *.egg-info）
SKIP_DIR_GLOBS = ("*.egg-info",)
# 不同步的文件后缀（字节码可再生，不该进包体）
SKIP_SUFFIX = {".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib", ".db", ".sqlite"}
# 允许从副本中删除的后缀（受管文件类型；其余一律不动，避免误删用户文件）
MANAGED_SUFFIX = {
    ".py", ".pyi", ".md", ".rst", ".txt", ".yaml", ".yml", ".json", ".toml",
    ".ini", ".cfg", ".lock", ".css", ".html", ".svg", ".png", ".jpg", ".jpeg",
    ".gif", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".xml", ".env",
}


def _skip_dir(name: str) -> bool:
    """按目录名判断是否跳过（纯字符串判断，不做任何文件系统调用）。"""
    if name in SKIP_DIRS:
        return True
    return any(fnmatch.fnmatch(name, g) for g in SKIP_DIR_GLOBS)


def _skip_file(p: Path) -> bool:
    if p.suffix.lower() in SKIP_SUFFIX:
        return True
    return p.name in {"MANIFEST.in", "build.log"}


def walk(root: Path) -> dict[str, Path]:
    """收集 {相对路径(POSIX 形式): 绝对路径}。"""
    out: dict[str, Path] = {}
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        # 注意: rel.parents 返回 Path 对象，而 _skip_dir 按字符串匹配 SKIP_DIRS。
        # Python 的 Path('foo') != 'foo' 且 hash 不同，必须显式 str() 转换。
        if any(_skip_dir(str(part)) for part in rel.parents):
            continue
        if _skip_file(p):
            continue
        out[rel.as_posix()] = p
    return out


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_engine_version(pkg: Path) -> str:
    try:
        text = (pkg / "version.py").read_text(encoding="utf-8")
    except OSError:
        return ""
    # 必须锚定行首 (re.M)：version.py 的 docstring 里写着历史版本号
    # (如 "主包 tuan_cli.__version__ = \"0.3.1\"" 的演进说明), 不锚定会
    # 把注释里的旧版本号当成真实版本 —— 那正是本脚本要暴露的漂移本身。
    m = re.search(r"^__version__\s*=\s*[\"']([^\"']+)", text, re.M)
    return m.group(1) if m else ""


def fingerprint(root: Path) -> dict[str, dict]:
    return {rel: {"sha256": sha256(p), "size": p.stat().st_size}
            for rel, p in walk(root).items()}


def collect_problems() -> dict[str, list[str]]:
    """比对源与副本，返回 {问题类型: [相对路径...]}。"""
    if not SRC.is_dir():
        return {"missing_source": [str(SRC)]}
    if not DEST.is_dir():
        return {"missing_bundle": [str(DEST)]}
    src, dst = walk(SRC), walk(DEST)

    problems: dict[str, list[str]] = {"missing": [], "stale": [], "extra": []}
    for rel in sorted(src):
        if rel not in dst:
            problems["missing"].append(rel)
        elif sha256(src[rel]) != sha256(dst[rel]):
            problems["stale"].append(rel)
    for rel in sorted(dst):
        if rel not in src:
            if Path(rel).suffix.lower() in MANAGED_SUFFIX:
                problems["extra"].append(rel)

    # 副本里不该存在的缓存 / 字节码（跳过 SKIP_DIRS：虚拟环境等自带大量 .pyc）
    junk = []
    for p in sorted(DEST.rglob("*")):
        if not p.is_file():
            continue
        if any(_skip_dir(part) for part in p.relative_to(DEST).parts[:-1]):
            continue
        if p.suffix.lower() in SKIP_SUFFIX or "__pycache__" in p.parts:
            junk.append(p.relative_to(DEST).as_posix())
    if junk:
        problems["junk"] = junk

    # 指纹文件是否过期
    if MANIFEST.is_file():
        try:
            data = json.loads(MANIFEST.read_text(encoding="utf-8"))
            drift = []
            for rel, info in (data.get("files") or {}).items():
                fp = DEST / rel
                if not fp.is_file() or sha256(fp) != info.get("sha256"):
                    drift.append(rel)
            if drift:
                problems["manifest_drift"] = drift
            if data.get("engineVersion") != read_engine_version(DEST):
                problems["manifest_version_mismatch"] = ["engineVersion"]
        except Exception:  # noqa: BLE001
            problems["manifest_unreadable"] = [str(MANIFEST)]
    else:
        problems["manifest_missing"] = [str(MANIFEST)]

    return problems


def prune_empty_dirs(root: Path) -> int:
    """自底向上回收空目录；保留 root 本身。"""
    removed = 0
    dirs = sorted((p for p in root.rglob("*") if p.is_dir()),
                  key=lambda p: -len(p.parts))
    for p in dirs:
        try:
            if p.is_dir() and not any(p.iterdir()):
                p.rmdir()
                removed += 1
        except OSError:
            continue
    return removed


def sync(dry_run: bool = False) -> int:
    if not SRC.is_dir():
        print(f"[error] 源目录不存在：{SRC}", file=sys.stderr)
        return 2
    if not DEST.is_dir() and not dry_run:
        DEST.mkdir(parents=True, exist_ok=True)
    if dry_run:
        DEST.mkdir(parents=True, exist_ok=True)

    src, dst = walk(SRC), walk(DEST)
    added, updated, same, deleted = [], [], [], []

    for rel in sorted(src):
        s, d = src[rel], (DEST / rel)
        if not d.is_file() or sha256(s) != sha256(d):
            if not d.is_file():
                added.append(rel)
            else:
                updated.append(rel)
            if not dry_run:
                d.parent.mkdir(parents=True, exist_ok=True)
                d.write_bytes(s.read_bytes())
        else:
            same.append(rel)

    removed_stale = []
    for rel in sorted(dst):
        if rel not in src and Path(rel).suffix.lower() in MANAGED_SUFFIX:
            removed_stale.append(rel)
            if not dry_run:
                dst[rel].unlink(missing_ok=True)

    junk = []
    if not dry_run:
        for p in sorted(DEST.rglob("*")):
            if not p.is_file():
                continue
            # 跳过虚拟环境等目录：它们自带大量 .pyc，不能当成缓存清掉
            if any(_skip_dir(part) for part in p.relative_to(DEST).parts[:-1]):
                continue
            if p.suffix.lower() in SKIP_SUFFIX or "__pycache__" in p.parts:
                p.unlink(missing_ok=True)
                junk.append(p.relative_to(DEST).as_posix())

    emptied = 0
    if not dry_run:
        emptied = prune_empty_dirs(DEST)

    if not dry_run:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps({
            "schema": MANIFEST_SCHEMA,
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source": "tuan_cli/",
            "engineVersion": read_engine_version(DEST),
            "files": fingerprint(DEST),
        }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    tag = "[dry-run] 将" if dry_run else "[ok]"
    print(f"{tag} 引擎副本同步完成 -> {DEST}")
    print(f"  新增 {len(added)} / 更新 {len(updated)} / 一致 {len(same)} / "
          f"删除陈旧 {len(removed_stale)} / 清理缓存 {len(junk)} / 回收空目录 {emptied}")
    for label, items in (("新增", added), ("更新", updated), ("删除陈旧", removed_stale)):
        if items:
            print(f"  {label}：")
            for it in items[:25]:
                print(f"    {it}")
            if len(items) > 25:
                print(f"    ... 及另外 {len(items) - 25} 个")
    if junk:
        print(f"  清理缓存（__pycache__ / *.pyc）{len(junk)} 个")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="同步 Tuan 桌面端打包引擎副本")
    ap.add_argument("--check", action="store_true", help="只比对，不写盘；发现漂移退出码 1")
    ap.add_argument("--dry-run", action="store_true", help="预览改动，不写盘")
    args = ap.parse_args(argv)

    if args.check:
        problems = collect_problems()
        total = sum(len(v) for v in problems.values())
        if total == 0:
            ver = read_engine_version(DEST) or "(未知)"
            print(f"校验通过：引擎副本与 tuan_cli/ 一致，版本号 {ver}。")
            return 0
        print("引擎副本已漂移：")
        for kind, items in problems.items():
            if not items:
                continue
            label = {
                "missing": "副本缺失", "stale": "内容过期", "extra": "副本多余",
                "junk": "缓存残留", "manifest_drift": "指纹不符",
                "manifest_missing": "缺少指纹", "manifest_unreadable": "指纹损坏",
                "manifest_version_mismatch": "指纹版本号不符",
                "missing_source": "源目录缺失", "missing_bundle": "副本目录缺失",
            }.get(kind, kind)
            print(f"  [{label}] {len(items)} 项")
            for it in items[:20]:
                print(f"    {it}")
            if len(items) > 20:
                print(f"    ... 及另外 {len(items) - 20} 项")
        print(f"\n共 {total} 项差异。运行 `python scripts/sync_engine_bundle.py` 同步。")
        return 1

    return sync(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
