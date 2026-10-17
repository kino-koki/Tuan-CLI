"""青小团桌面端 (claude-desktop-app 壳) 启动器。

用法:
  python scripts/tuan_desktop.py              # 启动桌面端 (开发模式)
  python scripts/tuan_desktop.py --install    # 构建 Windows 独立安装包 (electron-builder)
  python scripts/tuan_desktop.py --check      # 依赖检查 (node / npm / 依赖目录)
  python scripts/tuan_desktop.py --help       # 帮助

说明:
- 桌面壳位于 <项目根>/claude-desktop-app/, 引擎已切换为青小团 Python
  引擎 (bridge-server.cjs 查找顺序: TUAN_PYTHON -> 项目 .venv python -> bun)。
- 开发模式直接启动; 首次运行会自动 npm install (含 engine 的 bun install)。
- --install 产出安装包到 claude-desktop-app/release/; 安装版默认用 bun 引擎,
  如需 Python 引擎请在系统环境变量设置 TUAN_PYTHON 指向青小团 python.exe。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_DIR_NAME = "claude-desktop-app"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _app_dir() -> Path:
    return _project_root() / APP_DIR_NAME


def _has_node_modules() -> bool:
    return (_app_dir() / "node_modules").is_dir()


def _node_version() -> str:
    node = shutil.which("node")
    if not node:
        return ""
    try:
        r = subprocess.run([node, "--version"], capture_output=True, text=True,
                           timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


def _npm_cmd() -> str:
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    return npm or ""


def check_deps() -> str:
    """返回依赖检查报告文本。"""
    lines = [f"桌面壳目录: {_app_dir()}", f"node: {_node_version() or '(未安装)'}"]
    npm = _npm_cmd()
    lines.append(f"npm: {npm or '(未安装)'}")
    if npm:
        try:
            r = subprocess.run([npm, "--version"], capture_output=True, text=True,
                               timeout=10)
            lines.append(f"npm version: {r.stdout.strip()}")
        except Exception:  # noqa: BLE001
            lines.append("npm version: (探测失败)")
    lines.append(f"node_modules: {'存在' if _has_node_modules() else '缺失 (首次启动会自动安装)'}")
    py = _project_root() / ".venv" / "Scripts" / "python.exe"
    lines.append(f"青小团 venv python: {'存在' if py.exists() else '缺失'}")
    lines.append(f"TUAN_PYTHON: {os.environ.get('TUAN_PYTHON', '(未设置, 使用默认查找)')}")
    return "\n".join(lines)


def install_deps() -> bool:
    """npm install (含 postinstall 的 engine bun install)。"""
    npm = _npm_cmd()
    if not npm:
        print("[青小团桌面端] 未找到 npm, 请先安装 Node.js (https://nodejs.org/)")
        return False
    print("[青小团桌面端] 首次运行, 正在安装依赖 (npm install)...")
    r = subprocess.run([npm, "install"], cwd=str(_app_dir()))
    return r.returncode == 0


def launch_dev() -> int:
    """启动开发模式 (vite build + electron)。"""
    npm = _npm_cmd()
    if not npm:
        print("[青小团桌面端] 未找到 npm, 请先安装 Node.js (https://nodejs.org/)")
        return 1
    if not _has_node_modules():
        if not install_deps():
            return 1
    print("[青小团桌面端] 正在启动桌面端 (首次构建需数秒)...")
    env = dict(os.environ)
    if sys.platform == "win32":
        # 让 electron 主进程能找到青小团 Python 引擎 (默认查找已含 .venv, 显式设置更稳)
        env.setdefault("TUAN_PYTHON", str(_project_root() / ".venv" / "Scripts" / "python.exe"))
    # electron:dev = vite build && electron . ; 独立进程, 不阻塞终端
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    try:
        subprocess.Popen(
            [npm, "run", "electron:dev"],
            cwd=str(_app_dir()),
            env=env,
            creationflags=creationflags,
            close_fds=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[青小团桌面端] 启动失败: {exc}")
        return 1
    print("[青小团桌面端] 已在独立进程中启动。关闭窗口即退出; 重新启动用同一命令。")
    return 0


def build_installer() -> int:
    """构建 Windows 独立安装包 (electron-builder --win)。"""
    npm = _npm_cmd()
    if not npm:
        print("[青小团桌面端] 未找到 npm, 请先安装 Node.js")
        return 1
    if not _has_node_modules():
        if not install_deps():
            return 1
    print("[青小团桌面端] 正在构建 Windows 安装包 (electron-builder)...")
    print("  提示: 安装版默认使用 bun 引擎; 用 Python 引擎请设 TUAN_PYTHON 环境变量。")
    r = subprocess.run([npm, "run", "electron:build:win"], cwd=str(_app_dir()))
    if r.returncode != 0:
        print("[青小团桌面端] 构建失败, 详见上方输出。")
        return r.returncode
    release = _app_dir() / "release"
    print(f"[青小团桌面端] 构建完成, 安装包位于: {release}")
    if release.is_dir():
        for p in sorted(release.glob("*.exe")):
            print(f"  - {p.name} ({p.stat().st_size // (1024 * 1024)} MB)")
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:] if a]
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0
    if "--check" in args:
        print(check_deps())
        return 0
    if "--install" in args:
        return build_installer()
    return launch_dev()


if __name__ == "__main__":
    sys.exit(main())
