#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为 Tuan-App 打包引擎准备可运行的 Python 环境。

解决什么问题
------------
打包后的 Tuan-App 依赖一个 Python 环境来跑内嵌引擎（`tuan_cli web`）。
`resolve_python()` 的查找顺序是：`engine/python/python.exe`（便携运行时）→
`TUAN_PYTHON` → PATH → 注册表 → 常见安装目录。

但真实情况是：
  * 目标机器往往**没有** Python，PATH 里的 `python` 只是 Microsoft Store 的
    引导存根（`--version` 直接返回 9009）；
  * 即便装了真 Python，引擎的第三方依赖（rich / httpx / openai …）也**没有**，
    引擎会在 `import rich` 处崩溃，用户只看到一段看不懂的栈：

      ModuleNotFoundError: No module named 'rich'

本脚本就是补上这一块：在 `Tuan-App/engine/.venv` 里建一个干净的虚拟环境、
装上 `engine/requirements.txt`、逐个验证模块可导入，最后把该设置成
`TUAN_PYTHON` 的解释器路径打出来。

用法
----
  python scripts/install_engine_env.py                # 创建/更新环境
  python scripts/install_engine_env.py --python EXE   # 指定基础解释器
  python scripts/install_engine_env.py --check        # 只校验，不安装
  python scripts/install_engine_env.py --print-python # 打印解释器路径后退出
  python scripts/install_engine_env.py --skip-boot    # 跳过引擎启动自检

退出码：0 = 环境可用；1 = 校验失败；2 = 环境未就绪（需要安装）。
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENGINE = REPO / "Tuan-App" / "engine"
PKG = ENGINE / "tuan_cli"
VENV = ENGINE / ".venv"
REQS = ENGINE / "requirements.txt"

# 版本门槛：`resolve_python` 的报错文案承诺 Python 3.10+
MIN_VERSION = (3, 10)

# 引擎启动自检用的端口偏移；实际端口动态探测
BOOT_TIMEOUT_S = 45


def venv_python() -> Path:
    """返回虚拟环境里的解释器路径（跨平台）。"""
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def run(argv: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=kw.pop("timeout", 300), **kw)


def is_store_stub(exe: str) -> bool:
    """Windows 应用商店的 python.exe 只是个跳转器，不能用它建环境。"""
    return "WindowsApps" in exe.replace("/", "\\")


def parse_version(text: str) -> tuple[int, ...] | None:
    m = re.search(r"Python\s+(\d+(?:\.\d+)+)", text)
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def probe(exe: str) -> tuple[bool, str]:
    """解释器能否真正建环境：版本达标 **且** 自带 pip。"""
    try:
        r = run([exe, "--version"], timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False, "无法执行"
    text = (r.stdout or "") + (r.stderr or "")
    ver = parse_version(text)
    if ver is None:
        return False, "不是 Python（可能是 Microsoft Store 存根）"
    if ver < MIN_VERSION:
        return False, f"版本过低 {ver[0]}.{ver[1]}（需要 {MIN_VERSION[0]}.{MIN_VERSION[1]}+）"
    try:
        p = run([exe, "-m", "pip", "--version"], timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False, "无 pip 且无法调用"
    if p.returncode != 0:
        return False, "无 pip（该发行版的解释器不带 ensurepip 入口）"
    return True, f"Python {ver[0]}.{ver[1]} 可用"


def find_base_python(explicit: str | None) -> tuple[str | None, str]:
    """找一个能建虚拟环境的基础解释器。"""
    cands: list[tuple[str, str]] = []
    if explicit:
        cands.append((explicit, "--python 指定"))
    if os.environ.get("TUAN_PYTHON"):
        cands.append((os.environ["TUAN_PYTHON"], "TUAN_PYTHON"))
    cands += [("python", "PATH"), ("python3", "PATH"),
              ("py", "PATH"), ("py -3", "PATH")]

    tried: list[str] = []
    for c, _src in cands:
        exe = c.split()[0]
        try:
            resolved = shutil.which(exe)
        except Exception:  # noqa: BLE001
            resolved = None
        target = resolved or exe
        if resolved and is_store_stub(resolved):
            tried.append(f"{exe} ({resolved}) -> 商店存根，跳过")
            continue
        ok, msg = probe(target)
        tried.append(f"{exe} -> {'可用' if ok else msg}")
        if ok:
            return target, f"（来源：{_src}）"
    return None, "；".join(tried) if tried else "无候选"


def ensure_venv(base: str) -> int:
    """创建虚拟环境并装依赖。"""
    py = venv_python()
    if py.is_file():
        print(f"[info] 环境已存在：{py}")
    else:
        print(f"[..] 创建虚拟环境：{VENV}")
        r = run([base, "-m", "venv", str(VENV)], timeout=600)
        if not py.is_file():
            print(f"[error] 创建失败：{(r.stdout + r.stderr).strip()[:600]}")
            return 2
        # 极少数发行版的 venv 不含 pip，用 ensurepip 引导
        p = run([str(py), "-m", "pip", "--version"], timeout=60)
        if p.returncode != 0:
            print("[..] venv 内未检测到 pip，尝试 ensurepip 引导")
            e = run([str(py), "-m", "ensurepip", "--upgrade"], timeout=600)
            if e.returncode != 0:
                print(f"[error] ensurepip 失败：{(e.stdout + e.stderr).strip()[:400]}")
                return 2
    print("[..] 升级 pip / setuptools / wheel")
    run([str(py), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
         "--upgrade", "pip", "setuptools", "wheel"], timeout=900)
    if not REQS.is_file():
        print(f"[error] 缺少依赖清单：{REQS}")
        return 2
    print(f"[..] 安装依赖：{REQS.name}")
    r = run([str(py), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
             "-r", str(REQS)], timeout=1800)
    if r.returncode != 0:
        tail = "\n".join((r.stdout + r.stderr).splitlines()[-15:])
        print(f"[error] 依赖安装失败：\n{tail}")
        return 1
    print("[ok] 依赖安装完成")
    return 0


def _venv_version() -> tuple[int, ...]:
    """取虚拟环境解释器的版本（marker 求值要用它，不能用本脚本自己的版本）。"""
    py = venv_python()
    if not py.is_file():
        return sys.version_info[:3]
    try:
        r = run([str(py), "-c", "import sys;print('.'.join(map(str,sys.version_info[:3])))"],
                timeout=30)
        return tuple(int(x) for x in r.stdout.strip().split("."))
    except Exception:  # noqa: BLE001
        return sys.version_info[:3]


def _marker_applies(marker: str, pyver: tuple[int, ...]) -> bool:
    """极简 marker 求值：只处理脚本实际用到的 `python_version` 比较。

    不认识的 marker 一律放行 —— 依赖装没装由 pip 说了算，这里只做导入验证，
    误放行最多是多报一个缺模块，不会误判环境可用。
    """
    m = re.search(r"python_version\s*(==|>=|<=|>|<)\s*[\"']?(\d+(?:\.\d+)*)", marker)
    if not m:
        return True
    op = m.group(1)
    ver = tuple(int(x) for x in m.group(2).split("."))
    n = max(len(pyver), len(ver))
    a = pyver + (0,) * (n - len(pyver))
    b = ver + (0,) * (n - len(ver))
    return {"==": a == b, ">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b}[op]


def _required_modules() -> list[str]:
    """从 requirements.txt 提取需要验证的顶层模块名（包名已映射为模块名）。

    带环境标记（如 `tomli>=2.0; python_version < "3.11"`）且标记不适用于当前
    解释器时跳过 —— 否则 pip 正确跳过的包会被误报为"缺少模块"。
    """
    pyver = _venv_version()
    aliases = {"pyyaml": "yaml"}
    out: list[str] = []
    for line in REQS.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("-"):
            continue
        spec, _, marker = s.partition(";")
        if marker and not _marker_applies(marker.strip(), pyver):
            continue
        name = re.split(r"[><=!~\s]", spec.strip(), 1)[0].strip().lower()
        if not name:
            continue
        mod = name.replace("-", "_")
        mod = aliases.get(mod, mod)
        if mod not in out:
            out.append(mod)
    return out


def check_env(boot: bool = True) -> int:
    """校验当前环境是否可跑引擎。"""
    py = venv_python()
    if not py.is_file():
        print(f"[fail] 环境不存在：{py}")
        print("       运行 `python scripts/install_engine_env.py` 创建。")
        return 2
    bad: list[str] = []
    for mod in _required_modules():
        r = run([str(py), "-c", f"import {mod}"], timeout=30)
        if r.returncode != 0:
            bad.append(mod)
    if bad:
        print(f"[fail] 缺少模块：{', '.join(bad)}")
        return 1
    print(f"[ok] {len(_required_modules())} 个依赖模块全部可导入")

    if not PKG.is_dir():
        print(f"[fail] 引擎代码不存在：{PKG}")
        print("       先运行 `python scripts/sync_engine_bundle.py`。")
        return 1

    if boot:
        return boot_check(py)
    return 0


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def boot_check(py: Path) -> int:
    """真正拉起引擎并访问 /api/info —— 这是唯一能证明"能跑"的方式。"""
    port = _free_port()
    home = ENGINE / ".runtime-home"
    ws = ENGINE / ".runtime-ws"
    home.mkdir(parents=True, exist_ok=True)
    ws.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["TUAN_HOME"] = str(home)
    cmd = [str(py), "-X", "utf8", "-m", "tuan_cli", "web",
           "--host", "127.0.0.1", "--port", str(port),
           "--workspace", str(ws)]
    proc = subprocess.Popen(
        cmd, cwd=str(ENGINE), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
    )
    url = f"http://127.0.0.1:{port}/api/info"
    deadline = time.time() + BOOT_TIMEOUT_S
    body = ""
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                err = (proc.stderr.read() or "") if proc.stderr else ""
                print(f"[fail] 引擎进程提前退出（状态 {proc.returncode}）")
                print("       " + "\n       ".join(err.strip().splitlines()[-12:]))
                return 1
            try:
                with urllib.request.urlopen(url, timeout=3) as resp:
                    if resp.status == 200:
                        body = resp.read().decode("utf-8", "replace")
                        break
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
        if proc.stderr:
            proc.stderr.close()
        if proc.stdout:
            proc.stdout.close()

    if not body:
        print(f"[fail] 引擎就绪超时（{BOOT_TIMEOUT_S}s），未响应 {url}")
        return 1
    print(f"[ok] 引擎启动成功，GET {url} 返回 {len(body)} 字节")
    for key in ("version", "name", "port"):
        m = re.search(rf'"{key}"\s*:\s*"([^"]*)"', body)
        if m:
            print(f"     {key} = {m.group(1)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="为 Tuan-App 打包引擎准备 Python 环境")
    ap.add_argument("--python", dest="base", default=None, help="基础解释器路径（优先于 TUAN_PYTHON 与 PATH）")
    ap.add_argument("--check", action="store_true", help="只校验现有环境，不安装")
    ap.add_argument("--print-python", action="store_true", help="只打印解释器路径（用于设置 TUAN_PYTHON）")
    ap.add_argument("--skip-boot", action="store_true", help="--check 时跳过引擎启动自检")
    args = ap.parse_args(argv)

    if args.print_python:
        print(venv_python())
        return 0

    if not ENGINE.is_dir():
        print(f"[error] 引擎目录不存在：{ENGINE}")
        return 2
    if not PKG.is_dir():
        print(f"[error] 引擎代码不存在：{PKG}")
        print("       先运行 `python scripts/sync_engine_bundle.py` 同步引擎副本。")
        return 2

    if args.check:
        return check_env(boot=not args.skip_boot)

    py = venv_python()
    if py.is_file():
        ok, msg = probe(str(py))
        if ok:
            print(f"[info] 环境已就绪：{py}（{msg}）")
    else:
        base, why = find_base_python(args.base)
        if not base:
            print(f"[error] 未找到可建环境的 Python 3.10+：{why}")
            print("        可用 --python 指定，例如：")
            print("          python scripts/install_engine_env.py --python C:\\Python312\\python.exe")
            return 2
        ok, msg = probe(base)
        print(f"[..] 使用解释器：{base}（{msg}）")
        if ensure_venv(base) != 0:
            return 1

    rc = check_env(boot=True)

    print()
    print("环境可用。应用通过环境变量 TUAN_PYTHON 指定解释器（resolve_python 第 2 步）。")
    print(f"  setx TUAN_PYTHON \"{venv_python()}\"")
    print("  （已打开的终端不会自动读取，需重新打开；或在启动应用前于同进程内设置。）")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
