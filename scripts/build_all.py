# -*- coding: utf-8 -*-
"""Tuan 统一构建脚本 — 一条命令完成 .exe + sidecar + 前端。

用法:
  python scripts/build_all.py                        # 标准 (sidecar + 前端 + Rust)
  python scripts/build_all.py --skip-sidecar         # sidecar 已构建过, 直接打 Tauri
  python scripts/build_all.py --skip-frontend        # 前端 dist 已构建
  python scripts/build_all.py --skip-rust            # 只打 sidecar + 前端 (没 cargo 时用)
  python scripts/build_all.py --platform android      # Android APK (独立 toolchain)
  python scripts/build_all.py --check                # 只检查依赖, 不构建

Windows .exe 完整构建 (推荐顺序):
  1. pip install pyinstaller Pillow mss       # 冻结 sidecar
  2. python scripts/build_engine_sidecar.py  # → Tuan/dist/tuan_engine/tuan_engine.exe
  3. cd Tuan && npm install && npm run build  # → Tuan/dist/ 前端产物
  4. rustup install stable && cargo build --release  # Rust (需要 cargo)
  5. npx tauri build                          # → Tuan/src-tauri/target/release/bundle/nsis/Tuan_0.3.2_x64-setup.exe

  最终安装包体积: 前端 ~3MB + Rust ~12MB + sidecar ~60MB + _internal 依赖 ~100MB = ~175MB
  用户安装后双击 Tuan.exe, 零 Python 依赖, sidecar 自动启动.

Android APK 构建 (完全独立):
  rustup target add aarch64-linux-android
  tauri android init
  tauri android build
  # 产物: Tuan/src-tauri/gen/android/app/build/outputs/apk/release/app-release.apk
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TUAN_DIR = ROOT / "Tuan"


def run(cmd: list[str], cwd: Path | None = None, check: bool = True, desc: str = "") -> int:
    print(f"\n{'='*50}")
    print(f"[build-all] {desc or '命令'}: {' '.join(cmd)}")
    if cwd:
        print(f"  cwd: {cwd}")
    print(f"{'='*50}")
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, shell=(sys.platform == "win32"))
    if check and r.returncode != 0:
        print(f"[build-all] ❌ 失败 (exit {r.returncode})")
        sys.exit(r.returncode)
    return r.returncode


def check_deps() -> bool:
    ok = True
    checks = [
        ("Python", sys.executable),
        ("PyInstaller", f"{sys.executable} -c 'import PyInstaller; print(PyInstaller.__version__)'"),
        ("Node.js", "node --version"),
        ("npm", "npm --version"),
        ("Rust", "rustc --version"),
        ("Cargo", "cargo --version"),
    ]
    print("[build-all] 依赖检查:\n")
    for label, cmd in checks:
        r = subprocess.run(cmd, capture_output=True, text=True, shell=(sys.platform == "win32"))
        version = (r.stdout or r.stderr).strip().splitlines()[0] if r.returncode == 0 else "(未找到)"
        status = "✅" if r.returncode == 0 else "❌"
        print(f"  {status} {label:10s} {version}")
        if r.returncode != 0:
            ok = False
    return ok


def build_sidecar() -> None:
    run([sys.executable, str(ROOT / "scripts" / "build_engine_sidecar.py"), "--clean"],
        desc="冻结 Python 引擎为 sidecar .exe")


def build_frontend() -> None:
    if not (TUAN_DIR / "node_modules").exists():
        run(["npm.cmd", "install"], cwd=TUAN_DIR, desc="npm install 前端依赖")
    run(["npm.cmd", "run", "build"], cwd=TUAN_DIR, desc="vite build 前端")
    run(["npm.cmd", "run", "sync:engine"], cwd=TUAN_DIR, desc="sync_engine_bundle.py")


def build_rust() -> None:
    run(["cargo", "build", "--release"], cwd=TUAN_DIR / "src-tauri", desc="Rust release build")


def build_tauri() -> None:
    run(["npx.cmd", "tauri", "build"], cwd=TUAN_DIR, desc="Tauri bundle (NSIS)")


def build_android() -> None:
    run(["rustup", "target", "add", "aarch64-linux-android"], desc="加 Android target")
    if not (TUAN_DIR / "src-tauri" / "gen" / "android").exists():
        run(["npx.cmd", "tauri", "android", "init"], cwd=TUAN_DIR, desc="初始化 Android 项目")
    run(["npx.cmd", "tauri", "android", "build"], cwd=TUAN_DIR, desc="Android APK release 构建")


def print_manifest() -> None:
    sidecar = TUAN_DIR / "dist" / "tuan_engine"
    exe = sidecar / "tuan_engine.exe"
    nsis = TUAN_DIR / "src-tauri" / "target" / "release" / "bundle" / "nsis"

    print(f"\n{'='*50}")
    print("📦 构建产物清单")
    print(f"{'='*50}")
    if sidecar.exists():
        print(f"  📂 Sidecar: {sidecar}")
        for p in sorted(sidecar.iterdir()):
            tag = "📦" if p.is_dir() else "   "
            size = p.stat().st_size // (1024*1024) if p.is_file() else ""
            print(f"    {tag} {p.name} {size}{'MB' if size else ''}")
    if nsis.exists():
        for p in sorted(nsis.glob("*.exe")):
            print(f"  ✅ NSIS 安装包: {p} ({p.stat().st_size // (1024*1024)} MB)")
    apk = TUAN_DIR / "src-tauri" / "gen" / "android" / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"
    if apk.exists():
        print(f"  ✅ Android APK: {apk} ({apk.stat().st_size // (1024*1024)} MB)")


def main() -> int:
    args = [a for a in sys.argv[1:]]
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0
    if "--check" in args:
        ok = check_deps()
        return 0 if ok else 1

    platform = "windows"
    if "--platform" in args:
        idx = args.index("--platform")
        platform = args[idx + 1] if idx + 1 < len(args) else "windows"

    skip_sidecar = "--skip-sidecar" in args
    skip_frontend = "--skip-frontend" in args
    skip_rust = "--skip-rust" in args

    if platform == "android":
        print("\n🚀 Android APK 构建路径 (完全独立 toolchain)")
        build_android()
        print_manifest()
        return 0

    # 默认 Windows .exe 完整链路
    print("\n🚀 Windows .exe 完整构建")
    if not skip_sidecar:
        build_sidecar()
    if not skip_frontend:
        build_frontend()
    if not skip_rust:
        build_rust()
        build_tauri()
    print_manifest()
    return 0


if __name__ == "__main__":
    sys.exit(main())
