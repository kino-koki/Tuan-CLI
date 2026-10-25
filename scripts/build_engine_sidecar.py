# -*- coding: utf-8 -*-
"""冻结 tuan_cli 引擎为独立 tuan_engine.exe (Windows).

把 app_desktop.py 入口 + 所有 plugin + 工具 + 依赖 冻结成单文件 sidecar,
Tauri bundle 时一并打入 .msi / .nsis 安装包, 用户机零 Python 依赖.

用法:
  python scripts/build_engine_sidecar.py          # 完整冻结
  python scripts/build_engine_sidecar.py --clean  # 先删旧产物再冻结
  python scripts/build_engine_sidecar.py --skip-install  # 已装过 pyinstaller/依赖, 跳过 pip

产物:
  Tuan/dist/tuan_engine/
    tuan_engine.exe          ← Tauri sidecar 直接 spawn
    _internal/               ← PyInstaller 运行时 + 所有 pip 依赖 + tuan_cli 源码
    engine_version.json      ← 引擎版本信息 (方便 Rust 侧打印)

依赖 (首次运行自动 pip install):
  pyinstaller>=6.0
  -r tuan_cli/requirements.txt  (pip install 主依赖)
  可选: Pillow, mss, browser-use (用户按需装, 冻结时 --collect-all 收进去)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TUAN_PKG = ROOT / "tuan_cli"
ENTRY = TUAN_PKG / "app_desktop.py"
DIST_DIR = ROOT / "Tuan" / "dist" / "tuan_engine"
BUILD_DIR = ROOT / "Tuan" / "build" / "pyinstaller"
SPEC_FILE = ROOT / "Tuan" / "tuan_engine.spec"


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> int:
    print(f"\n[sidecar] $ {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    if check and r.returncode != 0:
        print(f"[sidecar] ❌ 命令失败 (exit {r.returncode})")
        sys.exit(r.returncode)
    return r.returncode


def ensure_pyinstaller() -> None:
    """确认 pyinstaller 已装; 没装就 pip install."""
    try:
        import PyInstaller  # noqa: F401
        print(f"[sidecar] ✅ PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("[sidecar] PyInstaller 未安装, 正在 pip install...")
        run([sys.executable, "-m", "pip", "install", "--upgrade", "pyinstaller>=6.0"])


def ensure_deps() -> None:
    """装核心依赖 (requirements.txt). 可选依赖不强制 —— 冻结时 --collect-all 兜底."""
    req = ROOT / "requirements.txt"
    if req.exists():
        print("[sidecar] pip install -r requirements.txt")
        run([sys.executable, "-m", "pip", "install", "-r", str(req)], check=False)
    # 几个核心可选库: 有就装, 没有 PyInstaller 会跳过
    for opt in ("Pillow", "mss"):
        print(f"[sidecar] 尝试 pip install {opt} (可选)...")
        run([sys.executable, "-m", "pip", "install", opt], check=False)


def _optional_pkg(pkg: str) -> bool:
    """检查可选包是否已装 (PyInstaller --collect-all 只对装了的加)."""
    try:
        import importlib.util
        return importlib.util.find_spec(pkg) is not None
    except Exception:
        return False


def _collect_all() -> list[str]:
    """--collect-all 参数列表: 仅对已安装的可选包收全量资源."""
    out: list[str] = ["--collect-all", "tuan_cli"]
    for opt in ("PIL", "mss", "playwright", "browser_use", "tesseract", "uvicorn", "httpx", "aiohttp"):
        if _optional_pkg(opt):
            out += ["--collect-all", opt]
        else:
            print(f"[sidecar] 📎 可选依赖 {opt} 未安装, 跳过 --collect-all (运行时按需 pip install)")
    return out


def _hidden_imports() -> list[str]:
    """显式 hidden-import: PyInstaller 静态分析抓不到的插件模式加载."""
    hi: list[str] = [
        # Kernel / Plugin 入口
        "--hidden-import", "tuan_cli.app_desktop",
        "--hidden-import", "tuan_cli.app",
        "--hidden-import", "tuan_cli.web.server",
        # 所有 tools (动态加载 via entry_points 或 importlib)
        "--hidden-import", "tuan_cli.tools",
        # MCP runtime
        "--hidden-import", "tuan_cli.runtime.mcp",
        "--hidden-import", "tuan_cli.runtime.mcp.client",
        "--hidden-import", "tuan_cli.runtime.mcp.plugin",
        # Agent / Router
        "--hidden-import", "tuan_cli.core.agent",
        "--hidden-import", "tuan_cli.core.model_router",
        "--hidden-import", "tuan_cli.agents",
        "--hidden-import", "tuan_cli.agents.adapters",
        # Skills
        "--hidden-import", "tuan_cli.skills",
        "--hidden-import", "tuan_cli.skills.manager",
        # 常见第三方 (PyInstaller 经常漏)
        "--hidden-import", "uvicorn",
        "--hidden-import", "httpx",
        "--hidden-import", "aiohttp",
        "--hidden-import", "websockets",
        "--hidden-import", "PIL.ImageGrab",
    ]
    return hi


def build(clean: bool = True, skip_install: bool = False) -> None:
    print("=" * 60)
    print("Tuan Engine Sidecar 冻结 (PyInstaller)")
    print(f"  entry : {ENTRY}")
    print(f"  dist  : {DIST_DIR}")
    print("=" * 60)

    if clean:
        for d in (DIST_DIR, BUILD_DIR):
            if d.exists():
                print(f"[sidecar] 🧹 清理旧产物: {d}")
                shutil.rmtree(d, ignore_errors=True)
        if SPEC_FILE.exists():
            SPEC_FILE.unlink()

    if not skip_install:
        ensure_pyinstaller()
        ensure_deps()

    # PyInstaller 命令
    pyinstaller = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name", "tuan_engine",
        # 输出位置: Tuan/dist/tuan_engine/tuan_engine.exe
        "--distpath", str(DIST_DIR.parent),     # Tuan/dist/  → 里面会有 tuan_engine/ 子目录
        "--workpath", str(BUILD_DIR),
        "--specpath", str(SPEC_FILE.parent),
        # 单目录模式 (onefile 启动慢, onedir 秒开)
        # 注意: onedir 会生成 tuan_engine/tuan_engine.exe + _internal/
        # Tauri bundle 时整个 tuan_engine/ 目录作为 resource 拷进去
        # 但 sidecar 配置只指向 tuan_engine.exe 即可, Rust 自动找 _internal/
        # 等等 —— PyInstaller 默认 onedir 模式是 <name>/<name>.exe
        # 我们要 dist/tuan_engine/tuan_engine.exe (sidecar 名字叫 tuan_engine.exe)
        # PyInstaller 6.x 用 --contents-directory _internal 把运行时集中放一个子目录
        "--contents-directory", "_internal",
        # 入口
        str(ENTRY),
    ]
    pyinstaller += _collect_all()
    pyinstaller += _hidden_imports()

    print(f"\n[sidecar] 🚀 PyInstaller 开始冻结...")
    run(pyinstaller, cwd=ROOT)

    # PyInstaller 实际产物路径: Tuan/dist/tuan_engine/tuan_engine.exe
    # 确认存在
    exe = DIST_DIR / "tuan_engine.exe"
    if not exe.exists():
        # 也可能是 Tuan/dist/tuan_engine.exe (--distpath 行为差异)
        flat = ROOT / "Tuan" / "dist" / "tuan_engine.exe"
        if flat.exists():
            # 把 flat 搬到子目录, 保持路径一致
            flat.parent.mkdir(parents=True, exist_ok=True)
            flat.rename(exe)
            print(f"[sidecar] 📦 扁平化产物已搬到: {exe}")
        else:
            print(f"[sidecar] ❌ 找不到 tuan_engine.exe, 检查 {ROOT}/Tuan/dist/")
            sys.exit(1)

    print(f"\n[sidecar] ✅ 冻结完成!")
    print(f"  EXE : {exe} ({exe.stat().st_size // (1024*1024)} MB)")
    internal = DIST_DIR / "_internal"
    if internal.exists():
        total = sum(p.stat().st_size for p in internal.rglob("*") if p.is_file())
        print(f"  _internal : {internal} ({total // (1024*1024)} MB, 含 pip 依赖 + tuan_cli 源码)")

    # 写 engine_version.json (Rust 侧可以读)
    try:
        sys.path.insert(0, str(TUAN_PKG.parent))
        from tuan_cli import __version__
        info = {
            "version": __version__,
            "build": "pyinstaller-sidecar",
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "frozen_at": __import__("datetime").datetime.now().isoformat(),
        }
        (DIST_DIR / "engine_version.json").write_text(
            json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  version : {info}")
    except Exception as e:  # noqa: BLE001
        print(f"  (version 文件跳过: {e})")


def main() -> int:
    args = [a for a in sys.argv[1:]]
    clean = "--clean" in args
    skip = "--skip-install" in args
    help_ = "--help" in args or "-h" in args
    if help_:
        print(__doc__)
        return 0
    build(clean=clean, skip_install=skip)
    return 0


if __name__ == "__main__":
    sys.exit(main())
