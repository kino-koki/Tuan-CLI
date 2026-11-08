"""OS 抽象与 syscall 级沙箱原语。

提供:
- 平台探测 (is_linux / is_windows / is_macos)
- 安全 syscall 白名单 (供 seccomp BPF 使用)
- Windows Job Object 封装 (OS 级资源/进程隔离)
- Linux seccomp 过滤器安装 (当 libseccomp 可用时)

设计原则:
- 任何平台相关能力都做"能力探测 + 优雅降级", 绝不在不支持时抛未捕获异常。
- syscall 级拦截在 Linux 上走 seccomp (libseccomp 提供), 在 Windows 上走 Job Object
  (OS 提供的进程/资源隔离原语; 用户态无法逐 syscall 拦截, 这是平台限制, 非取舍)。
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from typing import List, Optional

IS_WINDOWS = os.name == "nt" or sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")
IS_MACOS = sys.platform == "darwin"


# ----------------------------------------------------------------- 安全 syscall 白名单
# 仅允许"无害"的基础 syscall; 其余一律 SECCOMP_RET_KILL (或 ERRNO)。
# 覆盖典型 Python/编译型子进程所需的最小集。
SAFE_SYSCALL_ALLOWLIST: List[str] = [
    # 进程/内存
    "read", "write", "close", "fstat", "mmap", "mprotect", "munmap",
    "brk", "rt_sigaction", "rt_sigprocmask", "sigreturn", "clone",
    "exit", "exit_group", "wait4", "kill", "tgkill", "gettid",
    # 文件
    "open", "openat", "lseek", "access", "stat", "lstat", "readlink",
    "fcntl", "dup", "dup2", "getdents64", "ioctl", "poll", "select",
    # 调度/时间
    "sched_yield", "clock_gettime", "gettimeofday", "nanosleep", "times",
    # 线程/同步
    "futex", "set_tid_address", "set_robust_list", "get_robust_list",
    "restart_syscall", "rseq",
    # 网络 (白名单内允许; 若策略禁网则由架构层在 fork 前 unshare -n)
    "socket", "connect", "sendto", "recvfrom", "shutdown", "bind",
    "listen", "accept", "getsockname", "getpeername", "setsockopt",
    "getsockopt", "recvmsg", "sendmsg",
]

# 默认拦截并杀掉的"高危" syscall (即便不在显式拒绝列表, 白名单之外的也杀)
# 这些通常不应出现在常规 Agent 子任务中:
DANGEROUS_SYSCALLS: List[str] = [
    "ptrace", "mount", "umount2", "kexec_load", "reboot", "swapon",
    "swapoff", "setuid", "setgid", "setns", "unshare", "personality",
    "bpf", "userfaultfd", "perf_event_open", "fanotify_init",
    "init_module", "finit_module", "delete_module", "lookup_dcookie",
    "process_vm_readv", "process_vm_writev", "name_to_handle_at",
]


@dataclass
class SyscallResult:
    """单次沙箱执行的结果。"""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    blocked: bool = False        # True = 被 seccomp 拦截 (SIGSYS)
    blocked_syscalls: List[str] = field(default_factory=list)
    mechanism: str = "none"  # seccomp | job-object | fallback
    # E3: 是否真的拿到了 OS 级强制隔离。降级到普通子进程时必须为 False,
    # 否则上层 (SandboxManager._run_syscall) 会把它当成"已强隔离执行"放行,
    # 这是比"没有配额"更危险的 fail-open: 宣称隔离, 实际裸跑。
    enforced: bool = True
    degraded_reason: str = ""   # 降级/失败原因 (可观测)
    error: str = ""             # 执行层错误 (如 AssignProcessToJobObject 失败)


# ----------------------------------------------------------------- E3: Job Object 限制参数
@dataclass(frozen=True)
class JobObjectLimits:
    """Windows Job Object 资源配额 (纯数据, 非 Windows 平台也可校验/测试)。

    Windows API 单位说明:
    - 内存: ``JobMemoryLimit`` / ``ProcessMemoryLimit`` 用字节;
    - CPU: ``JOBOBJECT_CPU_RATE_CONTROL_INFORMATION.CpuRate`` 用 **百分数的 100 倍**
      (50% -> 5000), 且需 ``ENABLE | HARD_CAP`` 才是硬上限 (否则只是权重调度);
    - 进程数: ``ActiveProcessLimit`` 限制 Job 内同时存活的进程数,
      是防止 fork 炸弹 / 派生进程逃离配额的关键。
    """

    memory_limit_mb: int = 512
    cpu_rate_pct: int = 50
    active_process_limit: int = 16
    kill_timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        # 上限收紧: 防止误配导致宿主被吃满, 也防止 0 / 负值让 API 静默忽略限制
        if not (16 <= self.memory_limit_mb <= 65536):
            raise ValueError("memory_limit_mb 必须在 16..65536 之间")
        if not (1 <= self.cpu_rate_pct <= 100):
            raise ValueError("cpu_rate_pct 必须在 1..100 之间")
        if not (1 <= self.active_process_limit <= 1024):
            raise ValueError("active_process_limit 必须在 1..1024 之间")
        if not (0.5 <= self.kill_timeout_seconds <= 60.0):
            raise ValueError("kill_timeout_seconds 必须在 0.5..60 之间")

    @property
    def memory_bytes(self) -> int:
        return self.memory_limit_mb * 1024 * 1024

    @property
    def cpu_rate_units(self) -> int:
        """Windows CpuRate 字段单位: 百分数的 100 倍。"""
        return self.cpu_rate_pct * 100

    @property
    def basic_limit_flags(self) -> int:
        """JOBOBJECT_EXTENDED_LIMIT_INFORMATION.BasicLimitInformation.LimitFlags。"""
        return (
            0x00000008  # JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            | 0x00000010  # JOB_OBJECT_LIMIT_WORKINGSET (让 MaximumWorkingSetSize 真正生效)
            | 0x00000100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | 0x00000200  # JOB_OBJECT_LIMIT_JOB_MEMORY
            | 0x00004000  # JOB_OBJECT_LIMIT_CPU_RATE (配合 class 15 的 CPU 硬上限)
        )

    @property
    def cpu_control_flags(self) -> int:
        """JobObjectCpuRateControlInformation.ControlFlags: ENABLE | HARD_CAP。"""
        return 0x1 | 0x4  # JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | _HARD_CAP


def job_object_limits(memory_limit_mb: int = 512, cpu_rate_pct: int = 50,
                      active_process_limit: int = 16,
                      kill_timeout_seconds: float = 5.0) -> JobObjectLimits:
    """从配置构造 (并校验) Job Object 限制; 非法值直接抛错, 绝不静默用默认值。"""
    return JobObjectLimits(
        memory_limit_mb=int(memory_limit_mb),
        cpu_rate_pct=int(cpu_rate_pct),
        active_process_limit=int(active_process_limit),
        kill_timeout_seconds=float(kill_timeout_seconds),
    )


# ----------------------------------------------------------------- Windows Job Object
# 用 ctypes 直接调用 kernel32, 无需 pywin32。
def _set_job_limits(kernel32: Any, job: Any, limits: JobObjectLimits) -> None:
    """E3: 把资源配额真正写进 Job Object (拆出来便于用 fake kernel32 做单测)。

    两次 SetInformationJobObject:
      1) class 9  (JobObjectExtendedLimitInformation): 内存 / workingset / 进程数 / CPU_RATE flag
      2) class 15 (JobObjectCpuRateControlInformation): CPU 百分比硬上限
    任何一次失败都抛错 -> 上层 fail-closed, 不允许"配额没设上却照跑"。
    """
    import ctypes  # noqa: WPS433
    from ctypes import wintypes

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_void_p),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("ControlFlags", wintypes.DWORD),
            ("CpuRate", wintypes.DWORD),
            ("Weight", wintypes.DWORD),
        ]

    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = limits.basic_limit_flags
    info.BasicLimitInformation.ActiveProcessLimit = limits.active_process_limit
    info.BasicLimitInformation.MaximumWorkingSetSize = limits.memory_bytes
    info.ProcessMemoryLimit = limits.memory_bytes
    info.JobMemoryLimit = limits.memory_bytes
    if not kernel32.SetInformationJobObject(
            job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError("SetInformationJobObject(ExtendedLimit) 失败")

    cpu = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
    cpu.ControlFlags = limits.cpu_control_flags
    cpu.CpuRate = limits.cpu_rate_units
    cpu.Weight = 0
    if not kernel32.SetInformationJobObject(
            job, 15, ctypes.byref(cpu), ctypes.sizeof(cpu)):
        raise OSError("SetInformationJobObject(CpuRateControl) 失败")


def _terminate_job_tree(kernel32: Any, job: Any, proc: Any,
                        limits: JobObjectLimits) -> str:
    """E3: 进程树击杀 + 超时兜底。

    TerminateJobObject 是首选 (一次杀掉 Job 内所有派生进程); 若它失败或调用
    抛异常, 用 taskkill /T /F 按 PID 树补刀, 最后再 proc.kill() 兜底。
    返回实际采用的机制描述, 供审计定位"为什么这次降级了"。
    """
    try:
        if kernel32.TerminateJobObject(job, 1):
            return "TerminateJobObject"
    except Exception:
        pass
    # 兜底 1: taskkill /T (整树) /F (强制), 不依赖 Job 句柄是否仍有效
    try:
        done = subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=limits.kill_timeout_seconds,
        )
        if done.returncode == 0:
            return "taskkill /T /F"
    except Exception:
        pass
    # 兜底 2: 至少杀掉直接子进程, 绝不返回"已清理"却留孤儿
    try:
        proc.kill()
    except Exception:
        pass
    return "proc.kill (Job 终止失败)"


def _windows_job_object_sandbox(
    cmd: List[str],
    timeout: float,
    memory_limit_mb: int = 512,
    cpu_rate_pct: int = 50,
    active_process_limit: int = 16,
    kill_timeout_seconds: float = 5.0,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> SyscallResult:
    """Windows: 用 Job Object 限制子进程的 CPU/内存/活跃进程数。

    E3 修复要点 (旧实现只是"存在性探测 + 名义上的配额"):
    - ``cpu_rate_pct`` 参数此前**完全没被使用**: 只有内存/进程数, 没有 CPU 硬上限。
      现在通过 JobObjectCpuRateControlInformation (class 15) + ENABLE|HARD_CAP 落地。
    - ``MaximumWorkingSetSize`` 此前没带 ``JOB_OBJECT_LIMIT_WORKINGSET`` flag, 不生效。
    - ``AssignProcessToJobObject`` 失败时旧实现 ``pass`` 静默退化为裸子进程, 却仍
      返回 ``mechanism="job-object"`` —— 宣称已隔离、实际无配额。现在 fail-closed:
      杀掉子进程并返回 ``enforced=False / blocked=True``, 交由上层拒绝。
    - 配额设置任一步失败都抛错, 不再"配额没设上却照跑"。
    - 超时用 TerminateJobObject 整树击杀, 失败时 taskkill /T /F + proc.kill 兜底。
    """
    import ctypes  # noqa: WPS433

    limits = job_object_limits(memory_limit_mb, cpu_rate_pct,
                               active_process_limit, kill_timeout_seconds)
    kernel32 = ctypes.windll.kernel32
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError()

    try:
        _set_job_limits(kernel32, job, limits)

        proc = subprocess.Popen(  # noqa: S603
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, creationflags=0, cwd=cwd, env=env,
        )
        # fail-closed: 挂不上 Job = 拿不到任何资源约束与进程树归属, 绝不放行。
        if not kernel32.AssignProcessToJobObject(job, int(proc._handle)):  # type: ignore[attr-defined]
            reason = "AssignProcessToJobObject 失败: 子进程未纳入 Job, 无资源配额"
            try:
                proc.kill()
                out, err = proc.communicate(timeout=limits.kill_timeout_seconds)
            except Exception:
                out, err = "", ""
            return SyscallResult(
                returncode=-1, stdout=out or "", stderr=err or "",
                blocked=True, enforced=False, mechanism="job-object",
                degraded_reason=reason, error=reason,
            )

        try:
            out, err = proc.communicate(timeout=timeout)
            return SyscallResult(
                returncode=proc.returncode or 0,
                stdout=out or "", stderr=err or "",
                timed_out=False, mechanism="job-object", enforced=True,
            )
        except subprocess.TimeoutExpired:
            kill_via = _terminate_job_tree(kernel32, job, proc, limits)
            try:
                out, err = proc.communicate(timeout=limits.kill_timeout_seconds)
            except Exception:
                out, err = "", ""
            return SyscallResult(
                returncode=proc.returncode or -1,
                stdout=out or "", stderr=err or "",
                timed_out=True, mechanism="job-object", enforced=True,
                degraded_reason=f"超时, 已整树终止 ({kill_via})",
            )
    finally:
        try:
            kernel32.CloseHandle(job)
        except Exception:
            pass


# ----------------------------------------------------------------- Linux seccomp
def _linux_seccomp_sandbox(
    cmd: List[str],
    timeout: float,
    allowlist: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
) -> SyscallResult:
    """Linux: 在 fork 出的子进程里安装 seccomp 白名单过滤器, 再 exec 目标命令。

    需要 libseccomp (`pip install libseccomp`); 若不可用则抛 RuntimeError,
    由调用方降级到 fallback 路径。
    """
    try:
        import seccomp
    except Exception as exc:  # pragma: no cover - 依赖缺失
        raise RuntimeError("libseccomp 不可用, 无法启用 syscall 级拦截") from exc

    allow = set(allowlist or SAFE_SYSCALL_ALLOWLIST)

    pid = os.fork()  # type: ignore[attr-defined]
    if pid == 0:
        # 子进程: 安装过滤器后 exec
        try:
            os.setsid()  # type: ignore[attr-defined]  # 独立会话, 超时 killpg 只杀本子树, 不波及父进程组
        except Exception:
            pass
        try:
            f = seccomp.SyscallFilter(seccomp.DEF_ALLOW)
            # DEF_ALLOW 默认放行; 这里改为默认拒绝, 仅白名单放行
            f = seccomp.SyscallFilter(seccomp.KILL)
            for name in allow:
                try:
                    f.add_rule(seccomp.ALLOW, name)
                except Exception:
                    pass
            # 放行架构必需的几个
            for must in ("execve", "execveat", "arch_prctl", "prctl", "rt_sigreturn"):
                try:
                    f.add_rule(seccomp.ALLOW, must)
                except Exception:
                    pass
            f.load()
        except Exception:
            os._exit(127)  # 过滤器安装失败, 直接失败 (fail-closed)
        try:
            # 本轮: 传入脱敏后的环境, 不再让 seccomp 子进程继承父进程裸环境。
            # env=None 时保持原 execvp 语义 (继承), 向后兼容所有既有调用点。
            if env is not None:
                os.execvpe(cmd[0], cmd, env)  # type: ignore[attr-defined]
            else:
                os.execvp(cmd[0], cmd)
        except Exception:
            os._exit(127)
    else:
        import signal as _signal
        import time
        deadline = time.time() + timeout
        # SIGSYS (signal 31 on Linux) = seccomp 杀掉了子进程
        _SIGSYS = getattr(_signal, "SIGSYS", 31)
        while True:
            wpid, status = os.waitpid(pid, os.WNOHANG)  # type: ignore[attr-defined]
            if wpid != 0:
                if os.WIFSIGNALED(status):  # type: ignore[attr-defined]
                    sig = os.WTERMSIG(status)  # type: ignore[attr-defined]
                    if sig == _SIGSYS:
                        # seccomp 杀掉了子进程: 可能是白名单拦截, 也可能是命令不存在
                        # 退出码 127 = 命令不存在 (shell 惯例); 其他信号码 = 拦截
                        return SyscallResult(
                            returncode=127, blocked=True,
                            mechanism="seccomp",
                        )
                    # 其他信号杀死 (OOM/kill 等)
                    return SyscallResult(
                        returncode=128 + sig, blocked=True,
                        mechanism="seccomp",
                    )
                rc = os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else status >> 8
                return SyscallResult(returncode=rc, mechanism="seccomp")
            if time.time() > deadline:
                # 超时: 杀掉整个进程组 (含其派生); 子进程已 setsid, pid 即进程组 id
                try:
                    os.killpg(pid, 9)  # type: ignore[attr-defined]
                except Exception:
                    os.kill(pid, 9)
                os.waitpid(pid, 0)
                return SyscallResult(returncode=-1, timed_out=True, mechanism="seccomp")
            time.sleep(0.02)


# 网络相关 syscall (禁网时从白名单中移除)
_NET_SYSCALLS = frozenset({
    "socket", "connect", "sendto", "recvfrom", "shutdown", "bind",
    "listen", "accept", "getsockname", "getpeername", "setsockopt",
    "getsockopt", "recvmsg", "sendmsg",
})


# ----------------------------------------------------------------- 统一入口
def run_syscall_sandboxed(
    cmd: List[str],
    timeout: float = 30.0,
    memory_limit_mb: int = 512,
    cpu_rate_pct: int = 50,
    active_process_limit: int = 16,
    kill_timeout_seconds: float = 5.0,
    allowlist: Optional[List[str]] = None,
    block_network: bool = False,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> SyscallResult:
    """跨平台 syscall 级沙箱执行。

    - Windows:     Job Object 隔离 (资源/进程数限制)
    - Linux:       seccomp 白名单拦截 (libseccomp 可用时); 否则 fallback
    - 禁网:        Linux 尝试 `unshare -n` 进入无网络命名空间 (需要权限, 失败则降级;
                   降级时从 seccomp 白名单中移除网络 syscall 作为兜底)
    - cwd:         子进程工作目录 (None = 继承父进程)
    - env:         子进程环境 (None = 继承父进程). 本轮由 SandboxManager 传入
                   EgressGuard 脱敏/sentinel 后的环境, 覆盖 Windows Job Object /
                   Linux seccomp / 所有 fallback 路径; 旧调用点不传时行为不变。
    """
    # 如果禁网, 先构建过滤后的白名单 (移除网络 syscall)
    filtered_allowlist = list(allowlist) if allowlist is not None else None
    if block_network and filtered_allowlist is not None:
        filtered_allowlist = [s for s in filtered_allowlist if s not in _NET_SYSCALLS]
    elif block_network and filtered_allowlist is None:
        filtered_allowlist = [s for s in SAFE_SYSCALL_ALLOWLIST if s not in _NET_SYSCALLS]

    if block_network and IS_LINUX:
        # 用 nsenter/unshare 进入无网命名空间再跑 (需要 CAP_SYS_ADMIN, 普通用户常失败)
        try:
            return _linux_seccomp_sandbox(
                ["unshare", "-n", "--"] + cmd, timeout=timeout,
                allowlist=filtered_allowlist, env=env,
            )
        except Exception:
            # unshare 失败 -> 降级但仍然从白名单移除网络 syscall (兜底)
            pass

    if IS_WINDOWS:
        try:
            return _windows_job_object_sandbox(
                cmd, timeout, memory_limit_mb=memory_limit_mb,
                cpu_rate_pct=cpu_rate_pct,
                active_process_limit=active_process_limit,
                kill_timeout_seconds=kill_timeout_seconds, cwd=cwd, env=env,
            )
        except Exception as exc:
            # E3: Job Object 不可用 -> 普通子进程。必须显式标记 enforced=False,
            # 旧实现这里返回 mechanism="fallback" 却被 SandboxManager 当成
            # enforced=True, 等于"宣称 OS 级隔离、实际裸跑"。
            reason = f"Job Object 不可用, 降级为普通子进程: {type(exc).__name__}"
            from ..core.proc import run_with_tree_kill
            try:
                proc = run_with_tree_kill(
                    cmd, capture_output=True, text=True,
                    timeout=timeout, cwd=cwd, env=env,
                )
                return SyscallResult(
                    returncode=proc.returncode, stdout=proc.stdout or "",
                    stderr=proc.stderr or "", mechanism="fallback",
                    enforced=False, degraded_reason=reason,
                )
            except subprocess.TimeoutExpired:
                return SyscallResult(
                    returncode=-1, stdout="", stderr="",
                    timed_out=True, mechanism="fallback",
                    enforced=False, degraded_reason=reason,
                )

    if IS_LINUX:
        try:
            return _linux_seccomp_sandbox(
                cmd, timeout=timeout, allowlist=filtered_allowlist, env=env,
            )
        except Exception:
            # 降级: 普通子进程 + 资源限制 (preexec 建新会话, 超时可整树清理)
            import resource

            def _prep() -> None:
                # 限制子进程地址空间, 防 OOM 炸宿主
                try:
                    mb = memory_limit_mb * 1024 * 1024
                    resource.setrlimit(resource.RLIMIT_AS, (mb, mb))  # type: ignore[attr-defined]
                except Exception:
                    pass
                try:
                    os.setsid()  # type: ignore[attr-defined]  # 新会话: 超时 killpg 只杀本子树
                except Exception:
                    pass

            lx_proc = subprocess.Popen(  # noqa: S603
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, preexec_fn=_prep, cwd=cwd, env=env,
            )
            try:
                out, err = lx_proc.communicate(timeout=timeout)
                return SyscallResult(
                    returncode=lx_proc.returncode or 0,
                    stdout=out or "", stderr=err or "",
                    mechanism="fallback", enforced=False,
                    degraded_reason="seccomp/libseccomp 不可用, 降级为 rlimit + 普通子进程",
                )
            except subprocess.TimeoutExpired:
                from ..core.proc import wait_with_tree_kill
                wait_with_tree_kill(lx_proc, 5)
                return SyscallResult(
                    returncode=-1, stdout="", stderr="",
                    timed_out=True, mechanism="fallback", enforced=False,
                    degraded_reason="seccomp 不可用且执行超时",
                )

    # 其他平台
    from ..core.proc import run_with_tree_kill
    try:
        proc = run_with_tree_kill(
            cmd, capture_output=True, text=True,
            timeout=timeout, cwd=cwd, env=env,
        )
        return SyscallResult(
            returncode=proc.returncode, stdout=proc.stdout or "",
            stderr=proc.stderr or "", mechanism="fallback",
            enforced=False, degraded_reason="平台无 syscall 级隔离原语, 降级为普通子进程",
        )
    except subprocess.TimeoutExpired:
        return SyscallResult(
            returncode=-1, stdout="", stderr="",
            timed_out=True, mechanism="fallback", enforced=False,
            degraded_reason="平台无 syscall 级隔离原语且执行超时",
        )
