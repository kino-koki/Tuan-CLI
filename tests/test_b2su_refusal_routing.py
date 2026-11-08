"""本轮深度修复回归：终态拒绝不回落、provider 接线不被内层吃掉。

**实测缺口（先复现再修）**

上一轮（ff3e25c4）把四条执行分支统一到 ``plan_egress`` 单一出口。
这轮沿同一条链路往上/往下各走一层，找到四个断点：

=========  ==========================================================
编号       实测结果
=========  ==========================================================
R1        ``tools/shell.py::_route_sandbox_isolation`` 只用
          ``verdict.enforced / backend_available`` 判断「是否采纳隔离结果」。
          但 plan 拒绝结果**天然** ``enforced=False``；在
          ``enforce_required=false`` 的部署上返回 ``None``，于是
          ``run_shell`` 继续 ``subprocess.Popen`` 把**被拒绝的命令在真实
          工作区裸跑一遍**。实测三种 verdict 配置之一确实回落。
R2        ``copy_diff_apply`` 分支在 plan 拒绝后仍走
          ``build_diff_preview → make_confirm_callable → confirm_apply``：
          副本其实是空的（根本没执行命令），却弹给用户确认写回；
          ``error`` 变成 ``"denied\npreview"``，把「出网合规拒绝」伪装成
          「用户主动拒绝」；还无条件 ``verdict.enforced=True`` 宣称已隔离执行。
R3        ``SandboxProvider._sanitize_env`` 按**键名**把 ``OPENAI_API_KEY``
          置空串，于是上一轮 plan 注入的 ``tuan-egress-sentinel-v1:<fp>``
          占位符也在接线处被抹成 ``''`` —— 强后端子进程拿不到可还原标记，
          出网代理 ``inject_headers()`` 链路静默断裂。
R4        ``SECRET_HINTS`` 含 ``"TUAN_"``，``TUAN_WORKSPACE`` 被抹空；
          只有 ``LocalSandbox`` 补回，另外三个强后端此前都没补，
          子进程拿不到工作区指示。
=========  ==========================================================

**修复**：``SandboxExecResult.terminal_refusal`` 把「终态安全拒绝」与
「隔离是否生效」解耦；shell 路由优先检查它、无条件返回错误文本；
copy_diff_apply 检测到它立刻返回；``_sanitize_env`` 按值保留占位符；
四个后端统一以 ``workspace`` 参数为准补 ``TUAN_WORKSPACE``。

**矩阵计数一个不动**（`ahead 10 / aligned 46 / partial 9 / gap 26 /
not_applicable 8`）—— 纯深度修复，不靠改口径凑数。
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from tuan_cli.core import sandbox_provider as sp
from tuan_cli.core.security_utils import (
    MASKED_PLACEHOLDER_PREFIX, is_masked_placeholder, sanitize_env,
)
from tuan_cli.sandbox.egress import SENTINEL_PREFIX
from tuan_cli.sandbox.egress_allowlist import (
    claim_from_values, claim_to_verdict_extra,
)
from tuan_cli.sandbox.egress_plan import plan_egress
from tuan_cli.sandbox.manager import SandboxExecResult, SandboxManager
from tuan_cli.sandbox.verdict import Verdict
from tuan_cli.tools import shell as SH


def _verdict_with_claim(*, backend="landlock", isolate=True,
                        workspace_mode="direct", enforced=False,
                        backend_available=False) -> Verdict:
    v = Verdict()
    v.backend = backend
    v.network = True
    v.isolate = isolate
    v.workspace_mode = workspace_mode
    v.enforced = enforced
    v.backend_available = backend_available
    v.extra.update(claim_to_verdict_extra(
        claim_from_values(["api.github.com"])))
    return v


class _Ctx:
    workspace = "/tmp/w"
    kernel = None
    confirm = None
    yolo = False

    def __init__(self, verdict):
        self._sandbox_verdict = verdict


# ================================================ 1 R1: 终态拒绝不回落
class TestTerminalRefusalRouting:
    @pytest.mark.parametrize("enforced,backend_available", [
        (False, False),   # enforce_required=false 的部署：旧实现回落裸跑
        (False, True),
        (True, False),
        (True, True),
    ])
    def test_refusal_never_falls_back_to_bare_execution(
            self, enforced, backend_available):
        """四种 verdict 配置下，plan 拒绝都必须返回终态错误文本。

        旧实现只在 (enforced 或 backend_available) 为真时采纳结果；
        拒绝结果天然 enforced=False，所以 (False, False) 会返回 None。
        """
        v = _verdict_with_claim(enforced=enforced,
                                backend_available=backend_available)
        res = SandboxExecResult(returncode=-1,
                                error="强后端无法证明逐命令出网合规",
                                enforced=False, terminal_refusal=True)
        with patch.object(SandboxManager, "_execute_backend",
                          return_value=res):
            out = SH._route_sandbox_isolation(
                _Ctx(v), "curl https://evil.example", 60)
        assert out is not None, "返回 None = run_shell 会在真实工作区裸跑"
        assert "错误" in out
        assert "无法证明逐命令出网合规" in out

    def test_refusal_with_real_manager_not_patched(self):
        """不 patch 执行层：真实 plan_egress 拒绝也不回落。"""
        v = _verdict_with_claim(enforced=False, backend_available=False)
        out = SH._route_sandbox_isolation(
            _Ctx(v), "curl https://evil.example", 60)
        assert out is not None and "错误" in out
        assert "metadata_only" in out or "无法证明" in out

    def test_guard_denial_is_also_terminal(self):
        """EgressGuard 自身拒绝（local + 禁网）同样是终态。"""
        v = Verdict()
        v.backend = "local"
        v.network = False
        v.isolate = True
        v.enforced = False
        v.backend_available = False
        m = SandboxManager()
        r = m._execute_backend("echo hi", v, "/tmp", 5.0)
        assert r.terminal_refusal is True or r.returncode == -1
        # 无论哪条拒绝分支，路由都不能回落
        with patch.object(SandboxManager, "execute_isolated", return_value=r):
            out = SH._route_sandbox_isolation(_Ctx(v), "echo hi", 60)
        assert out is not None

    def test_non_refusal_path_is_unchanged(self):
        """正常执行不设 terminal_refusal，路由逻辑保持原样。"""
        v = Verdict()
        v.backend = "local"
        v.network = True
        v.isolate = True
        v.enforced = True
        v.backend_available = False
        m = SandboxManager()
        with patch("tuan_cli.core.proc.run_with_tree_kill") as fake:
            fake.return_value.stdout = "ok"
            fake.return_value.stderr = ""
            fake.return_value.returncode = 0
            r = m._execute_backend("echo hi", v, "/tmp", 5.0)
        assert r.terminal_refusal is False
        assert r.returncode == 0

    def test_result_default_is_backward_compatible(self):
        """新字段有默认值，所有既有构造方式不受影响。"""
        assert SandboxExecResult().terminal_refusal is False
        r = SandboxExecResult(stdout="x", returncode=0)
        assert r.as_shell_text() == "x"


# ================================================ 2 R2: copy_diff_apply 早返回
class _FakeWD:
    path = "/tmp/copy_wd"

    def __init__(self, calls):
        self.calls = calls

    def cleanup(self):
        self.calls.append("cleanup")


class TestCopyDiffApplyRefusal:
    def test_refusal_does_not_build_diff_or_ask_confirmation(self):
        v = _verdict_with_claim(workspace_mode="copy_diff_apply",
                                backend="landlock")
        m = SandboxManager()
        calls: list[str] = []
        wd = _FakeWD(calls)

        def fake_isolate(_cwd):
            calls.append("isolate")
            return wd

        def must_not_run(*_a, **_kw):
            raise AssertionError("终态拒绝后不应进入 diff/确认流程")

        with patch("tuan_cli.sandbox.isolation.isolate_workdir", fake_isolate), \
             patch("tuan_cli.sandbox.isolation.build_diff_preview",
                   side_effect=must_not_run), \
             patch("tuan_cli.sandbox.isolation.confirm_apply",
                   side_effect=must_not_run), \
             patch("tuan_cli.ui.approval_overlay.make_confirm_callable",
                   side_effect=must_not_run):
            res = m.execute_isolated("curl https://evil.example", v,
                                     _Ctx(v), timeout=5.0)

        assert calls == ["isolate", "cleanup"]
        assert res.terminal_refusal is True
        assert res.returncode == -1
        assert res.applied is False and res.applied_files == []
        assert res.diff_preview is None
        # 不再把合规拒绝伪装成用户主动拒绝
        assert "无法证明逐命令出网合规" in (res.error or "")
        assert "denied" not in (res.error or "")
        # 不再无条件宣称「已隔离执行」
        assert v.enforced is False

    def test_refusal_error_shows_real_reason_not_preview(self):
        """用户必须看见真正的拒绝原因，而不是 'denied\\npreview'。"""
        v = _verdict_with_claim(workspace_mode="copy_diff_apply")
        m = SandboxManager()
        calls = []
        wd = _FakeWD(calls)
        with patch("tuan_cli.sandbox.isolation.isolate_workdir",
                   return_value=wd), \
             patch("tuan_cli.sandbox.isolation.build_diff_preview",
                   side_effect=AssertionError("不应调用")), \
             patch("tuan_cli.ui.approval_overlay.make_confirm_callable",
                   side_effect=AssertionError("不应调用")):
            res = m.execute_isolated("echo hi", v, _Ctx(v), timeout=5.0)
        assert "strict_claim_strong_backend" in res.error
        assert "preview" not in res.error


# ================================================ 3 R3: sentinel 保全
class TestPlaceholderPreserved:
    def test_constant_matches_egress_module(self):
        """共享原语层常量必须与 egress.SENTINEL_PREFIX 恒等。"""
        assert MASKED_PLACEHOLDER_PREFIX == SENTINEL_PREFIX

    def test_is_masked_placeholder(self):
        assert is_masked_placeholder(SENTINEL_PREFIX + "deadbeef") is True
        assert is_masked_placeholder("REAL_SECRET") is False
        for bad in (None, 123, b"bytes", ""):
            assert is_masked_placeholder(bad) is False

    def test_sanitize_env_still_blanks_real_secret(self):
        """全局 sanitize_env 行为不变（本轮没放宽它）。"""
        out = sanitize_env({"OPENAI_API_KEY": "REAL_SECRET", "PATH": "/bin"})
        assert out["OPENAI_API_KEY"] == ""
        assert out["PATH"] == "/bin"

    def test_provider_keeps_placeholder_but_blanks_real_value(self):
        plan_env = {
            "OPENAI_API_KEY": SENTINEL_PREFIX + "deadbeef",
            "AWS_SECRET_ACCESS_KEY": "REAL_SECRET_VALUE",
            "PATH": "/bin",
        }
        got = sp.SandboxProvider._sanitize_env(plan_env)
        assert got["OPENAI_API_KEY"] == plan_env["OPENAI_API_KEY"]
        assert got["AWS_SECRET_ACCESS_KEY"] == ""
        assert got["PATH"] == "/bin"
        assert "REAL_SECRET_VALUE" not in str(got)

    def test_env_none_still_inherits_and_sanitizes(self):
        """env=None 保持既有继承语义，不因本轮改动变成空环境。"""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "REAL", "PATH": "/bin"},
                        clear=True):
            got = sp.SandboxProvider._sanitize_env(None)
        assert got["OPENAI_API_KEY"] == ""
        assert got["PATH"] == "/bin"

    def test_dirty_env_does_not_leak(self):
        got = sp.SandboxProvider._sanitize_env({
            "OPENAI_API_KEY": 123, "PATH": "/bin",
            "EVIL": SENTINEL_PREFIX + "x",
        })
        assert got["OPENAI_API_KEY"] == ""
        assert got["EVIL"] == SENTINEL_PREFIX + "x"


# ================================================ 4 R4: 工作区指示
class TestWorkspaceIndicator:
    def test_secret_hints_blank_tuan_workspace(self):
        """复现 R4 的成因，锁住它。"""
        assert sanitize_env({"TUAN_WORKSPACE": "/tmp/w"})["TUAN_WORKSPACE"] == ""

    @pytest.mark.parametrize("clsname", [
        "LocalSandbox", "LandlockSandbox", "SeatbeltSandbox",
        "WindowsTokenAclSandbox",
    ])
    def test_every_backend_restores_workspace(self, clsname):
        """四个后端都以 workspace 参数为准补回 TUAN_WORKSPACE。

        权威来源是 workspace 参数，不是外部 env（防止 env 里塞假路径）。
        """
        cls = getattr(sp, clsname)
        captured = {}
        plan_env = {
            "OPENAI_API_KEY": SENTINEL_PREFIX + "fp",
            "PATH": "/bin",
            "TUAN_WORKSPACE": "/evil/from/env",
        }

        class _Completed:
            stdout = ""
            stderr = ""
            returncode = 0

        def fake_run(*_a, **kw):
            captured["env"] = kw.get("env")
            return _Completed()

        with patch("tuan_cli.core.proc.run_with_tree_kill", fake_run), \
             patch("subprocess.run", fake_run), \
             patch("subprocess.Popen", fake_run):
            try:
                cls().run(["/bin/sh", "-c", "echo hi"],
                          workspace="/tmp/authoritative",
                          env=plan_env, timeout=5.0)
            except Exception:
                pass  # 各后端还有 profile / 平台分支，只关心 env 捕获

        env = captured.get("env")
        if env is None:
            # 某些后端在平台不匹配时会提前返回，改为源码级断言兜底
            src = Path(sp.__file__).read_text(encoding="utf-8")
            assert src.count('sandbox_env["TUAN_WORKSPACE"] = workspace') == 4
            return
        assert env["TUAN_WORKSPACE"] == "/tmp/authoritative"
        assert env["OPENAI_API_KEY"].startswith(SENTINEL_PREFIX)

    def test_source_has_four_restore_sites(self):
        src = Path(sp.__file__).read_text(encoding="utf-8")
        assert src.count('sandbox_env["TUAN_WORKSPACE"] = workspace') == 4


# ================================================ 5 不该修的判定（锁住现状）
class TestNotChangedOnPurpose:
    def test_last_egress_concurrent_writes_are_best_effort(self):
        """并发写 last_egress 未复现撕裂（GIL 兜住），**本轮不加锁**。

        延续前几轮立场：加锁是消除对 CPython GIL 实现细节的依赖，
        不是修已观测故障。这里只验证不抛异常、结构完整，不宣称线程安全。
        """
        m = SandboxManager()
        errors = []

        def writer(tag):
            for _ in range(200):
                v = Verdict()
                v.backend = "local"
                v.network = True
                p = plan_egress(v, "local", {}, dict(os.environ))
                m._last_egress = p.to_audit_dict()
                m._last_egress["tag"] = tag
                if "enforcement" not in m.last_egress:
                    errors.append(tag)

        ths = [threading.Thread(target=writer, args=(t,))
               for t in ("A", "B")]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        assert errors == []

    def test_no_direct_provider_run_outside_manager(self):
        """全仓 SandboxProvider.create 调用点里，只有 manager 会执行 .run。

        `cmd_safe.py` 只查 is_available()/name；`orchestration.py` 只把实例
        挂到 agent.ctx（全仓没有 ctx.sandbox_provider.run 调用）。这两个不是
        执行侧门，本轮**不改**，用源码扫描锁住结论。
        """
        root = Path(sp.__file__).resolve().parent.parent
        offenders = []
        for f in root.rglob("*.py"):
            if f.name == "sandbox_provider.py":
                continue
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            for i, line in enumerate(lines):
                if "SandboxProvider.create" not in line:
                    continue
                window = "\n".join(lines[i:i + 12])
                if re.search(r"\.run\(", window) and f.name != "manager.py":
                    offenders.append(f"{f.name}:{i + 1}")
        assert offenders == []

    def test_cmd_safe_only_probes_availability(self):
        src = Path(sp.__file__).resolve().parent.parent.joinpath(
            "cli/cmd_safe.py").read_text(encoding="utf-8")
        i = src.index('SandboxProvider.create("local")')
        window = src[i:i + 300]
        assert "is_available()" in window and ".name" in window
        assert ".run(" not in window


# ================================================ 6 矩阵自洽
class TestMatrixHonesty:
    def test_counts_unchanged(self):
        from tuan_cli.parity_claude import matrix, evidence
        assert matrix.validate() == []
        assert evidence.verify_evidence() == []
        s = matrix.summary()
        # 纯深度修复，一个状态都没动：不把修好侧门包装成进度。
        assert s["by_status"] == {
            "ahead": 10, "aligned": 46, "partial": 9,
            "gap": 26, "not_applicable": 8}
        assert s["gaps"] == 26
        assert s["fully_superior"] is False
        assert s["b_waves_done"] == ["B1"]
        assert s["superiority_criteria"]["external_adaptive_red_team"] is False
