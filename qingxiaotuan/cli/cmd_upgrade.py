"""qxt upgrade —— 自动更新青小团 CLI。

用法:
    qxt upgrade              检查 PyPI 并升级到最新版 (交互确认)
    qxt upgrade --check      仅检查是否有新版本, 不安装
    qxt upgrade --yes        跳过确认直接更新
    qxt upgrade --version 0.3.0      安装指定版本

网络失败时优雅降级, 提示手动更新命令。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any, List, Tuple

from .. import __version__

PACKAGE_NAME = "qingxiaotuan"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"


# ---------------------------------------------------------------- 版本比较

def _vparts(v: str) -> List[Tuple[int, int, str]]:
    """把版本号拆成可比较段, 容忍零填充数字 (0.2.017 == 数字 17) 与预览后缀。"""
    parts: List[Tuple[int, int, str]] = []
    for seg in re.split(r"[.\-_+]", (v or "").strip().lower()):
        if not seg:
            continue
        m = re.match(r"^(\d+)(.*)$", seg)
        if m:
            parts.append((0, int(m.group(1)), m.group(2)))
        else:
            parts.append((1, 0, seg))
    return parts


def compare_versions(a: str, b: str) -> int:
    """比较版本号 a vs b: 返回 -1 (a<b) / 0 / 1 (a>b)。"""
    pa, pb = _vparts(a), _vparts(b)
    n = max(len(pa), len(pb))
    pad = (0, 0, "")
    pa += [pad] * (n - len(pa))
    pb += [pad] * (n - len(pb))
    for x, y in zip(pa, pb):
        if x < y:
            return -1
        if x > y:
            return 1
    return 0


# ---------------------------------------------------------------- PyPI 查询

def fetch_latest(timeout: float = 10.0) -> Tuple[str, str]:
    """从 PyPI 查询最新版本与一句话简介。

    Raises:
        urllib.error.URLError / OSError: 网络失败, 由调用方优雅降级。
    """
    req = urllib.request.Request(
        PYPI_URL,
        headers={"Accept": "application/json", "User-Agent": f"qxt/{__version__}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (PyPI 官方源)
        data = json.loads(resp.read().decode("utf-8"))
    info = data.get("info", {}) or {}
    return str(info.get("version", "")).strip(), str(info.get("summary", "")).strip()


def _pip_install_cmd(target: str) -> List[str]:
    """用当前解释器对应的 pip 安装 (venv 隔离正确)。"""
    return [sys.executable, "-m", "pip", "install", "--upgrade",
            f"{PACKAGE_NAME}=={target}" if target else PACKAGE_NAME]


# ---------------------------------------------------------------- 命令入口

def cmd_upgrade(args: Any) -> int:
    """`qxt upgrade` 主入口。"""
    current = __version__
    print(f"当前版本: qxt {current}")

    target = getattr(args, "version", None)
    check_only = bool(getattr(args, "check", False))
    assume_yes = bool(getattr(args, "yes", False))

    # 指定版本时直接安装, 不必查 PyPI
    if not target:
        try:
            latest, summary = fetch_latest()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"检查更新失败 (网络不可达): {exc}")
            print(f"可手动更新: {sys.executable} -m pip install --upgrade {PACKAGE_NAME}")
            return 1
        if not latest:
            print("PyPI 未返回版本信息, 请检查网络后重试。")
            return 1
        if compare_versions(latest, current) <= 0:
            print(f"已是最新版本: qxt {current}")
            return 0
        target = latest
        print(f"发现新版本: qxt {current} -> {latest}")
        if summary:
            print(f"简介: {summary}")
    else:
        print(f"指定安装版本: {target}")

    if check_only:
        print("(--check 模式, 不执行安装)")
        return 0

    if not assume_yes:
        try:
            ans = input(f"是否现在更新到 {target}? [y/N] ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("y", "yes"):
            print("已取消。")
            return 1

    cmd = _pip_install_cmd(target)
    print("执行:", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except OSError as exc:
        print(f"pip 启动失败: {exc}")
        print(f"可手动更新: {' '.join(cmd)}")
        return 1
    if proc.stdout:
        print(proc.stdout)
    if proc.returncode != 0:
        print(proc.stderr or "pip 安装失败")
        print(f"可手动重试: {' '.join(cmd)}")
        return proc.returncode
    print(f"更新完成: qxt {target} (重启后生效)")
    return 0


__all__ = ["cmd_upgrade", "compare_versions", "fetch_latest", "_pip_install_cmd"]
