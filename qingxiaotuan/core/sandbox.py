"""进程级沙箱子 Agent 拉起器 —— 让"多双手"在隔离世界里挥, 主仓库零风险。

注意: 此模块提供「进程级」沙箱 (复制工作区到临时目录, subprocess 隔离)。
OS 级沙箱 (seccomp/bwrap/seatbelt/token-acl) 见 core.sandbox_provider。

核心思路:
- 主进程为每个子任务建一个**临时沙箱目录** (主工作区的副本);
- 用 subprocess 拉起 `_sandbox_entry` 子进程, 在沙箱目录里独立 build_kernel + run;
- 子进程的工具调用 (shell/写文件/web) 全部发生在沙箱内, 结束后沙箱清理,
  **主仓库与世界状态不被回写** —— 这才是真·进程级隔离 (线程级做不到);
- 子进程把 SubResult 写成 JSON 文件, 主进程读取并汇总。

为什么不用 multiprocessing: subprocess 隔离最干净 (独立解释器、独立内存、独立文件句柄),
且能直接复用 `python -m` 入口, 不需要 pickle 整个 kernel/Agent (它们本就不可 pickle)。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .subagents import SubResult, SubTask
from .security_utils import sanitize_env as _sanitize_sandbox_env  # noqa: F401,F811


def prepare_sandbox(
    workspace: str,
    task_id: str,
    parent: Optional[Path] = None,
    ignore: Optional[List[str]] = None,
) -> Path:
    """复制工作区到临时沙箱目录, 返回沙箱根。主仓库绝不被改动。"""
    src = Path(workspace).resolve()
    if not src.is_dir():
        raise NotADirectoryError(f"工作区不存在: {workspace}")
    base = parent or Path(tempfile.gettempdir())
    sandbox = base / f"qxt-sandbox-{task_id}-{uuid.uuid4().hex[:8]}"
    sandbox.mkdir(parents=True, exist_ok=True)
    _SKIP = set(ignore or [".git", "__pycache__", ".venv", "node_modules", ".qxt-sandbox"])
    # 用 shutil.copytree 逐文件复制 (比符号链接安全: 子进程写沙箱不影响源)
    for item in src.iterdir():
        if item.name in _SKIP:
            continue
        dst = sandbox / item.name
        try:
            if item.is_dir():
                shutil.copytree(item, dst, ignore=shutil.ignore_patterns(*_SKIP))
            else:
                shutil.copy2(item, dst)
        except (OSError, shutil.Error):
            # 单个文件/目录复制失败不应拖垮整个沙箱准备
            continue
    return sandbox


def run_in_sandbox(
    task: SubTask,
    workspace: str,
    profile: str = "default",
    qxt_home: Optional[str] = None,
    exclude_tools: tuple = (),
    yolo: bool = False,
    timeout: float = 180.0,
    model_overrides: Optional[Dict[str, Any]] = None,
    cleanup: bool = True,
    worker_module: str = "qingxiaotuan.core._sandbox_entry",
    system_extra: str = "",
) -> SubResult:
    """在进程级沙箱里跑一个子任务, 返回 SubResult。

    沙箱 = 工作区副本; 子进程内发生的所有写操作只落在沙箱; 结束清理沙箱。
    """
    started = time.time()
    sandbox: Optional[Path] = None
    req_path = resp_path = None
    try:
        sandbox = prepare_sandbox(workspace, task.task_id)
        tmpdir = sandbox.parent
        # 请求/响应/错误文件使用与沙箱目录一致的唯一后缀: task_id 是外部传入的
        # (如 make_tasks 固定生成 T1/T2...), 多任务并发或先后执行时会在共享系统
        # 临时目录里互相覆盖/误删同名文件, 导致子进程读到缺失或损坏的请求文件
        # 而崩溃 (exit=1)。suffix 由 prepare_sandbox 生成的 uuid 派生, 每次调用唯一。
        suffix = sandbox.name[len("qxt-sandbox-"):]
        req_path = tmpdir / f"qxt-req-{suffix}.json"
        resp_path = tmpdir / f"qxt-resp-{suffix}.json"
        err_path = tmpdir / f"qxt-err-{suffix}.log"
        if resp_path.exists():
            resp_path.unlink()
        req: Dict[str, Any] = {
            "profile": profile,
            "task": task.prompt,
            "workspace": str(sandbox),
            "exclude_tools": list(exclude_tools) + list(task.exclude_tools),
            "yolo": yolo,
            "qxt_home": qxt_home,
            "model_overrides": model_overrides or {},
            "system_extra": system_extra,
        }
        req_path.write_text(json.dumps(req, ensure_ascii=False), encoding="utf-8")

        # worker_module 可以是 "-m 模块" 形式, 也可以是直接脚本路径 (.py 文件)
        if worker_module.endswith(".py") and Path(worker_module).exists():
            cmd = [sys.executable, worker_module, str(req_path), str(resp_path)]
        else:
            cmd = [sys.executable, "-m", worker_module, str(req_path), str(resp_path)]
        # 独立进程组启动 + 整树清理: 超时杀 worker 时连它派生的 shell 孙进程一起清,
        # 防止子 Agent 后台命令 (npm install / sleep 等) 变孤儿泄漏。
        # stderr 落盘到唯一 err 文件 (不 capture 管道: Windows 下超时杀进程时
        # 读管道可能死锁); 子进程异常退出时错误信息可带回 stderr 内容。
        from .proc import popen_new_session, wait_with_tree_kill
        err_file = open(err_path, "wb")
        proc = popen_new_session(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=err_file,
            env=_sanitize_sandbox_env(dict(os.environ)),  # 默认抹除密钥, 防泄漏到沙箱
        )
        rc = wait_with_tree_kill(proc, timeout)
        if rc is None:
            return SubResult(
                task_id=task.task_id, prompt=task.prompt, ok=False,
                output="", elapsed=time.time() - started,
                error=f"沙箱子进程超时 (>{timeout:.0f}s)",
            )
        if not resp_path.exists():
            exit_code = rc
            stderr_tail = ""
            try:
                if err_path.exists():
                    stderr_tail = err_path.read_text(encoding="utf-8", errors="replace")[-500:]
            except OSError:
                pass
            return SubResult(
                task_id=task.task_id, prompt=task.prompt, ok=False,
                output="", elapsed=time.time() - started,
                error=(f"子进程无响应 (exit={exit_code}); "
                       f"stderr: {stderr_tail.strip() or '(无输出)'}"),
            )
        data = json.loads(resp_path.read_text(encoding="utf-8"))
        return SubResult(
            task_id=task.task_id,
            prompt=task.prompt,
            ok=bool(data.get("ok", False)),
            output=data.get("output", "") or "",
            turns=int(data.get("turns", 0) or 0),
            elapsed=time.time() - started,
            error=data.get("error"),
            tool_calls=data.get("tool_calls", []) or [],
        )
    except Exception as exc:  # noqa: BLE401
        return SubResult(
            task_id=task.task_id, prompt=task.prompt, ok=False,
            output="", elapsed=time.time() - started,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        # 清理: 请求/响应/错误文件 + 沙箱目录
        for p in (req_path, resp_path, err_path):
            try:
                if p and p.exists():
                    p.unlink()
            except OSError:
                pass
        try:
            err_file.close()
        except (NameError, OSError):
            pass
        if cleanup and sandbox is not None:
            try:
                shutil.rmtree(sandbox, ignore_errors=True)
            except OSError:
                pass
