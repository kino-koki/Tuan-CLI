"""proc —— subprocess 工业级增强: 进程组隔离 + 超时整树清理。

背景: 裸 `subprocess.run(cmd, shell=True, timeout=...)` 超时只杀 shell 本身,
孙进程 (pytest 的 worker、mypy 的 daemon 等) 变孤儿, 反复超时积累失控进程。

本模块统一替代 verify_loop / codedev.verify / code_edit.verify_loop 的执行点:
- POSIX: `start_new_session=True` 使子进程成为新进程组组长, 超时后 `killpg(SIGKILL)`。
- Windows: 超时后 `taskkill /F /T /PID` 按父子关系整树清理。
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """终止整棵进程树, 不抛异常 (best-effort)。"""
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, timeout=10,
            )
        else:
            # start_new_session=True → proc.pid 即进程组 id
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
    except Exception as exc:  # noqa: BLE001
        log.debug("进程树清理失败: %s", exc)
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def run_with_tree_kill(
    cmd: str | list[str],
    *,
    cwd: Optional[str] = None,
    timeout: float,
    capture_output: bool = True,
    text: bool = True,
    shell: bool = False,
    env: Optional[Dict[str, str]] = None,
    errors: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """执行命令; 超时/异常时整树清理后重抛 (语义与 subprocess.run 一致)。"""
    kwargs: Dict[str, Any] = dict(cwd=cwd, text=text, env=env, errors=errors)
    if capture_output:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    if sys.platform != "win32":
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, shell=shell, **kwargs)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        raise
    return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)


def popen_new_session(cmd: str | list[str], **kwargs: Any) -> subprocess.Popen:
    """以独立进程组启动子进程 (POSIX start_new_session; Windows 兼容)。

    配合 ``wait_with_tree_kill`` 使用: 超时可按进程组整树清理, 不留孤儿孙进程。
    沙箱/后台命令等不捕获输出的场景用它替代裸 Popen。
    """
    if sys.platform != "win32":
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def wait_with_tree_kill(proc: subprocess.Popen, timeout: float) -> Optional[int]:
    """等待子进程结束; 超时则整树清理并返回 None (不抛异常)。

    ``proc`` 须以独立进程组启动 (见 ``popen_new_session``), 否则 POSIX 的
    ``killpg`` 无法按组清理; Windows 走 taskkill /T 按父子关系递归。
    """
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
            proc.wait()
        return None
