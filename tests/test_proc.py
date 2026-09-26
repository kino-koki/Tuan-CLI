"""proc 模块测试: 进程组隔离 + 超时整树清理。"""

from __future__ import annotations

import os
import sys

import pytest

from qingxiaotuan.core.proc import (
    popen_new_session,
    run_with_tree_kill,
    wait_with_tree_kill,
)


def test_run_with_tree_kill_capture_ok():
    r = run_with_tree_kill(
        [sys.executable, "-c", "print('hello')"],
        timeout=30,
        capture_output=True,
    )
    assert r.returncode == 0
    assert r.stdout.strip() == "hello"


def test_run_with_tree_kill_timeout_raises():
    with pytest.raises(Exception):
        run_with_tree_kill(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=1,
            capture_output=True,
        )


def test_wait_returns_exitcode():
    proc = popen_new_session([sys.executable, "-c", "import sys; sys.exit(3)"])
    assert wait_with_tree_kill(proc, 10) == 3


def test_wait_timeout_kills_child():
    proc = popen_new_session([sys.executable, "-c", "import time; time.sleep(30)"])
    rc = wait_with_tree_kill(proc, timeout=1)
    assert rc is None  # 超时被识别为失败
    assert proc.poll() is not None  # 直接子进程已死, 不留孤儿


@pytest.mark.skipif(os.name == "nt", reason="POSIX 进程组语义")
def test_wait_timeout_kills_whole_group():
    """超时后孙进程 (同进程组) 一并被杀, 进程组整体消亡。"""
    proc = popen_new_session([
        sys.executable, "-c",
        "import subprocess, sys, time;"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']);"
        "time.sleep(30)",
    ])
    rc = wait_with_tree_kill(proc, timeout=1)
    assert rc is None
    assert proc.poll() is not None
    with pytest.raises(ProcessLookupError):
        os.killpg(proc.pid, 0)  # 组内已无存活成员
