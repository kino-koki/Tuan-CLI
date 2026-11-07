"""E3 回归: Job Object 资源配额真正落地 + 降级不再被误报为"已强隔离"。

在 Linux 上用 fake kernel32 / fake Popen 覆盖 Windows 路径:
ctypes.wintypes 在非 Windows 上也可导入, ctypes.windll 由 monkeypatch 注入。
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import types

import pytest

from tuan_cli.arch.platform import (
    JobObjectLimits, SyscallResult, job_object_limits,
    run_syscall_sandboxed, _set_job_limits, _terminate_job_tree,
    _windows_job_object_sandbox,
)


# ------------------------------------------------------------------ 纯数据层
class TestJobObjectLimits:
    def test_defaults(self):
        lim = job_object_limits()
        assert lim.memory_bytes == 512 * 1024 * 1024
        assert lim.cpu_rate_units == 5000          # 50% -> 5000 (百分数的 100 倍)
        assert lim.active_process_limit == 16

    def test_cpu_rate_units(self):
        assert job_object_limits(cpu_rate_pct=25).cpu_rate_units == 2500
        assert job_object_limits(cpu_rate_pct=100).cpu_rate_units == 10000

    def test_flags_include_workingset_and_cpu(self):
        flags = job_object_limits().basic_limit_flags
        assert flags & 0x00000010, "缺少 JOB_OBJECT_LIMIT_WORKINGSET"
        assert flags & 0x00004000, "缺少 JOB_OBJECT_LIMIT_CPU_RATE"
        assert flags & 0x00000008, "缺少 JOB_OBJECT_LIMIT_ACTIVE_PROCESS"
        assert flags & 0x00000100 and flags & 0x00000200

    def test_cpu_hard_cap_flags(self):
        assert job_object_limits().cpu_control_flags == 0x5  # ENABLE | HARD_CAP

    @pytest.mark.parametrize("kwargs", [
        {"memory_limit_mb": 0}, {"memory_limit_mb": 999999},
        {"cpu_rate_pct": 0}, {"cpu_rate_pct": 101},
        {"active_process_limit": 0}, {"active_process_limit": 5000},
        {"kill_timeout_seconds": 0.1},
    ])
    def test_invalid_values_raise_not_silently_default(self, kwargs):
        with pytest.raises(ValueError):
            job_object_limits(**kwargs)

    def test_custom_values(self):
        lim = job_object_limits(memory_limit_mb=256, cpu_rate_pct=30,
                                active_process_limit=4, kill_timeout_seconds=2.0)
        assert lim.memory_bytes == 256 * 1024 * 1024
        assert lim.cpu_rate_units == 3000
        assert lim.active_process_limit == 4
        assert lim.kill_timeout_seconds == 2.0


# ------------------------------------------------------------------ fake kernel32
class _FakeKernel32:
    def __init__(self, *, set_ok=True, assign_ok=True, terminate_ok=True):
        self.set_ok = set_ok
        self.assign_ok = assign_ok
        self.terminate_ok = terminate_ok
        self.set_calls = []
        self.close_calls = 0
        self.terminate_calls = 0
        self.create_calls = 0

    def CreateJobObjectW(self, *_a):
        self.create_calls += 1
        return 4242

    def SetInformationJobObject(self, job, cls, info, size):
        self.set_calls.append((job, cls, size))
        return 1 if self.set_ok else 0

    def AssignProcessToJobObject(self, job, handle):
        return 1 if self.assign_ok else 0

    def TerminateJobObject(self, job, code):
        self.terminate_calls += 1
        return 1 if self.terminate_ok else 0

    def CloseHandle(self, job):
        self.close_calls += 1
        return 1


def _patch_windll(monkeypatch, fake):
    windll = types.SimpleNamespace(kernel32=fake)
    monkeypatch.setattr(ctypes, "windll", windll, raising=False)


class _FakeProc:
    def __init__(self, *, timeout_on_communicate=False):
        self.pid = 9999
        self._handle = 7777
        self.returncode = 0
        self.killed = False
        self.timeout_on_communicate = timeout_on_communicate
        self.communicate_calls = 0

    def communicate(self, timeout=None):
        self.communicate_calls += 1
        if self.timeout_on_communicate and self.communicate_calls == 1:
            raise subprocess.TimeoutExpired(cmd="x", timeout=timeout or 1)
        return ("hello", "")

    def kill(self):
        self.killed = True
        self.returncode = -1


class TestSetJobLimits:
    def test_both_information_classes_are_set(self, monkeypatch):
        """class 9 (内存/进程数) + class 15 (CPU 硬上限), 缺一不可。"""
        fake = _FakeKernel32()
        _patch_windll(monkeypatch, fake)
        from tuan_cli.arch import platform as plat
        # _set_job_limits 直接用传入的 kernel32, 不需要 windll
        lim = job_object_limits(cpu_rate_pct=30)
        _set_job_limits(fake, 4242, lim)
        classes = [c[1] for c in fake.set_calls]
        assert classes == [9, 15], classes

    def test_cpu_failure_raises(self):
        """CPU 配额设不上时绝不静默继续执行。"""
        class _FailCPU(_FakeKernel32):
            def SetInformationJobObject(self, job, cls, info, size):
                self.set_calls.append((job, cls, size))
                return 0 if cls == 15 else 1
        with pytest.raises(OSError):
            _set_job_limits(_FailCPU(), 4242, job_object_limits())

    def test_extended_limit_failure_raises(self):
        with pytest.raises(OSError):
            _set_job_limits(_FakeKernel32(set_ok=False), 4242,
                            job_object_limits())


class TestWindowsJobObjectSandbox:
    def test_assign_failure_is_fail_closed(self, monkeypatch):
        """最值钱的一条: 挂不上 Job 旧实现 pass 后照跑, 现在拒绝且标记未隔离。"""
        fake = _FakeKernel32(assign_ok=False)
        _patch_windll(monkeypatch, fake)
        proc = _FakeProc()
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: proc)

        res = _windows_job_object_sandbox(["cmd", "/c", "echo hi"], timeout=5)

        assert res.blocked is True
        assert res.enforced is False
        assert "AssignProcessToJobObject" in res.degraded_reason
        assert proc.killed, "未纳入 Job 的子进程必须被杀掉, 不能留着裸跑"
        assert fake.close_calls == 1

    def test_success_path_is_enforced(self, monkeypatch):
        fake = _FakeKernel32()
        _patch_windll(monkeypatch, fake)
        proc = _FakeProc()
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: proc)

        res = _windows_job_object_sandbox(["cmd", "/c", "echo hi"], timeout=5)

        assert res.returncode == 0 and res.stdout == "hello"
        assert res.enforced is True and res.mechanism == "job-object"
        assert [c[1] for c in fake.set_calls] == [9, 15]

    def test_quota_setup_failure_is_fail_closed(self, monkeypatch):
        """配额设不上 -> 抛错 -> 统一入口降级并标记 enforced=False。"""
        fake = _FakeKernel32(set_ok=False)
        _patch_windll(monkeypatch, fake)
        monkeypatch.setattr(subprocess, "Popen",
                            lambda *a, **k: pytest.fail("配额失败时不应启动子进程"))
        from tuan_cli.arch import platform as plat
        monkeypatch.setattr(plat, "IS_WINDOWS", True)
        monkeypatch.setattr(plat, "IS_LINUX", False)
        monkeypatch.setattr(plat, "run_with_tree_kill", None, raising=False)
        # 直接验证内部函数抛错即可 (统一入口的降级由下面的 test 覆盖)
        with pytest.raises(OSError):
            _windows_job_object_sandbox(["cmd", "/c", "echo"], timeout=5)

    def test_timeout_uses_job_tree_kill(self, monkeypatch):
        fake = _FakeKernel32()
        _patch_windll(monkeypatch, fake)
        proc = _FakeProc(timeout_on_communicate=True)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: proc)

        res = _windows_job_object_sandbox(["cmd", "/c", "sleep"], timeout=1)

        assert res.timed_out is True
        assert fake.terminate_calls == 1
        assert "TerminateJobObject" in res.degraded_reason
        assert res.enforced is True   # 隔离本身生效, 只是执行超时

    def test_terminate_failure_falls_back_to_taskkill(self, monkeypatch):
        fake = _FakeKernel32(terminate_ok=False)
        proc = _FakeProc()
        calls = []

        def _fake_run(args, **kwargs):
            calls.append(args)
            return types.SimpleNamespace(returncode=0)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        via = _terminate_job_tree(fake, 4242, proc, job_object_limits())
        assert via == "taskkill /T /F"
        assert calls and calls[0][0] == "taskkill" and "/T" in calls[0]

    def test_terminate_total_failure_still_kills_direct_child(self, monkeypatch):
        fake = _FakeKernel32(terminate_ok=False)
        proc = _FakeProc()

        def _fake_run(args, **kwargs):
            return types.SimpleNamespace(returncode=1)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        via = _terminate_job_tree(fake, 4242, proc, job_object_limits())
        assert "proc.kill" in via
        assert proc.killed


# ------------------------------------------------------------------ 统一入口降级标记
class TestFallbackIsNotReportedAsEnforced:
    @pytest.mark.skipif(sys.platform != "linux", reason="requires Linux resource module")
    def test_linux_fallback_marks_not_enforced(self, monkeypatch):
        from tuan_cli.arch import platform as plat
        monkeypatch.setattr(plat, "IS_WINDOWS", False)
        monkeypatch.setattr(plat, "IS_LINUX", True)
        monkeypatch.setattr(plat, "_linux_seccomp_sandbox",
                            lambda *a, **k: (_ for _ in ()).throw(
                                RuntimeError("libseccomp 不可用")))
        res = run_syscall_sandboxed([sys.executable, "-c", "print('ok')"],
                                    timeout=10)
        assert res.returncode == 0
        assert res.enforced is False
        assert "降级" in res.degraded_reason

    def test_windows_fallback_marks_not_enforced(self, monkeypatch):
        from tuan_cli.arch import platform as plat
        monkeypatch.setattr(plat, "IS_WINDOWS", True)
        monkeypatch.setattr(plat, "IS_LINUX", False)
        monkeypatch.setattr(plat, "_windows_job_object_sandbox",
                            lambda *a, **k: (_ for _ in ()).throw(
                                RuntimeError("CreateJobObjectW 失败")))
        res = run_syscall_sandboxed([sys.executable, "-c", "print('ok')"],
                                    timeout=10)
        assert res.returncode == 0
        assert res.enforced is False
        assert "Job Object 不可用" in res.degraded_reason


class TestBackendProbe:
    def test_jobobject_not_available_on_linux(self):
        from tuan_cli.sandbox.backends import _jobobject_available
        if sys.platform != "win32":
            assert _jobobject_available() is False

    def test_detect_backends_never_raises(self):
        from tuan_cli.sandbox.backends import detect_backends
        out = detect_backends()
        assert any(b["name"] == "local" and b["available"] for b in out)
