"""隔离后端自动选择: docker → landlock(bwrap) → seatbelt → jobobject → local。

对比 TraeWork / CodeX 的单后端"硬切换":
  - CodeX sandbox*(bwrap/seatbelt/token-acl) 通常"选中一个就用它, 缺依赖即整体失效"。
  - 这里是"当前机器能拿到的最强隔离"按强度自动降序探测 —— 不会因为缺某一运行时
    就放弃隔离, 而是拿到可用的最强一个; 全部缺失时仍有 local 兜底(可用但无 OS 级隔离,
    由上层策略决定是否 fail-closed).
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from typing import Callable, Dict, List, Tuple

log = logging.getLogger(__name__)


def _sh_ok(args: List[str], timeout: float = 5.0) -> bool:
    try:
        proc = subprocess.run(args, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=timeout)
        return proc.returncode == 0
    except Exception as exc:  # pragma: no cover
        log.debug("沙箱后端探测/执行异常(设计内降级): %s", exc)
        return False


def _docker_available() -> bool:
    return _sh_ok(["docker", "info"])


def _bwrap_available() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    if shutil.which("bwrap") is None:
        return False
    try:
        return _sh_ok([shutil.which("bwrap"), "--ro-bind", "/", "/", "true"])
    except Exception as exc:
        log.debug("沙箱后端探测/执行异常(设计内降级): %s", exc)
        return False


def _seatbelt_available() -> bool:
    if sys.platform != "darwin":
        return False
    return shutil.which("sandbox-exec") is not None


def _jobobject_available() -> bool:
    """E3: 真实能力探测 —— 旧实现只判断 ``sys.platform == "win32"``,
    于是"Windows 上就一定宣称可用", 实际 CreateJobObjectW / 配额设置可能失败
    (权限受限、策略禁用、远程会话)。探测失败时不能把 jobobject 列为强后端,
    否则 auto 会选一个随后必然降级的后端, 上层却以为隔离已生效。
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return False
        try:
            # 只验证句柄可用与信息类可查询, 不在这里设配额 (配额由执行层设置)
            class _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
                _fields_ = [("TotalUserTime", ctypes.c_longlong),
                            ("TotalKernelTime", ctypes.c_longlong),
                            ("ThisPeriodTotalUserTime", ctypes.c_longlong),
                            ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                            ("TotalPageFaultCount", ctypes.c_ulong),
                            ("TotalProcesses", ctypes.c_ulong),
                            ("ActiveProcesses", ctypes.c_ulong),
                            ("TotalTerminatedProcesses", ctypes.c_ulong)]
            info = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
            ok = k32.QueryInformationJobObject(
                job, 1, ctypes.byref(info), ctypes.sizeof(info), None)
            return bool(ok)
        finally:
            k32.CloseHandle(job)
    except Exception as exc:  # noqa: BLE001
        log.debug("沙箱后端探测/执行异常(设计内降级): %s", exc)
        return False


def _token_acl_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin() != 0)
    except Exception as exc:
        log.debug("沙箱后端探测/执行异常(设计内降级): %s", exc)
        return False


# 强度降序: landlock(linux bwrap) → docker → seatbelt(mac) → token-acl/win → jobobject
_BACKENDS: List[Tuple[str, Callable[[], bool]]] = [
    ("landlock", _bwrap_available),
    ("docker", _docker_available),
    ("seatbelt", _seatbelt_available),
    ("token-acl", _token_acl_available),
    ("jobobject", _jobobject_available),
]


# 探测结果缓存 (进程级): 后端可用性是 OS 属性, 进程内不变。探测会起
# 子进程, 安全护栏逐命令重复探测会拖慢整条链 (实测把审计密集测试拖过
# 超时线) —— 首次探测后缓存, 测试用 monkeypatch 替换 pick_backend 时不受影响。
_PROBE_CACHE: Dict[str, bool] = {}
_DETECTED: Optional[List[Dict[str, object]]] = None


def detect_backends() -> List[Dict[str, object]]:
    """探测所有后端的可用性, 返回降序列表 (可靠, 不抛异常)。

    结果按进程缓存 (后端可用性是 OS 属性, 进程内不变) —— 探测会起子进程,
    逐命令重复探测会拖慢安全护栏 (实测把审计密集测试拖过超时线)。
    """
    global _DETECTED
    if _DETECTED is not None:
        return list(_DETECTED)
    out: List[Dict[str, object]] = []
    for name, probe in _BACKENDS:
        ok = _probe_cached(name, probe)
        out.append({"name": name, "available": ok,
                    # WSL2 docker 在提供强隔离的同时可能较慢, 并入候选中
                    "detail": _probe_detail(name, ok)})
    out.append({"name": "local", "available": True, "detail": "本地执行(无 OS 级隔离, 兜底)"})
    _DETECTED = out
    return list(_DETECTED)


def _probe_cached(name: str, probe: Callable[[], bool]) -> bool:
    """单后端探测 (带进程级缓存)。"""
    if name in _PROBE_CACHE:
        return _PROBE_CACHE[name]
    try:
        ok = bool(probe())
    except Exception:  # pragma: no cover
        ok = False
    _PROBE_CACHE[name] = ok
    return ok


def _probe_detail(name: str, ok: bool) -> str:
    hint = {
        "landlock": "Linux bubblewrap/seccomp",
        "docker": "Docker 容器",
        "seatbelt": "macOS sandbox-exec",
        "token-acl": "Windows 受限令牌+ACL(需管理员)",
        "jobobject": "Windows Job Object(资源/进程隔离)",
    }.get(name, "")
    return f"{hint} {'可用' if ok else '不可用'}"


def pick_backend(prefer: str = "auto") -> Tuple[str, bool]:
    """选择要用的后端, 返回 (name, available)。

    - prefer == 'local' → 强制 local (总有兜底).
    - prefer 指定具体名 → 该后端可用则用; 不可用则返回 (prefer, False), 不回落.
    - prefer == 'auto' 或其它 → 按强度降序返回首个可用; local 永远兜底.
    """
    if prefer == "local":
        return "local", True

    if prefer and prefer != "auto":
        # 显式指定: 必须存在且探测通过
        probe = dict(_BACKENDS).get(prefer)
        if probe is not None and _probe_cached(prefer, probe):
            return prefer, True
        # 显式指定的强后端不可用: 绝不静默降级到其它后端(尤其 local)。
        # 返回 (prefer, False) 交由 HardIsolationFilter 的 enforce 策略做 fail-closed 拒绝。
        log.warning("指定的沙箱后端 %r 不可用; 不回落, 交由上层 fail-closed 裁决", prefer)
        return prefer, False

    for name, probe in _BACKENDS:
        if _probe_cached(name, probe):
            return name, True
    return "local", True
