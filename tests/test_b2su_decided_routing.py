"""本轮深度修复回归：是否回落由结果自身决定 + 执行层异常文本净化。

**实测缺口（先复现再修）**

上一轮（2108a541）用 ``terminal_refusal`` 堵住了「plan 拒绝结果被当成
隔离没生效而回落裸跑」。这轮继续往下挖，发现那个修法只覆盖了**一条**
拒绝分支，而回落开关本身就用错了字段：

=========  ==========================================================
编号       实测结果
=========  ==========================================================
G         ``tools/shell.py::_route_sandbox_isolation`` 用
          ``verdict.enforced or verdict.backend_available`` 判断是否采纳
          结果。降级部署（两者皆 False）里 ``_execute_backend`` 的 local
          分支**已经真实执行了命令**，路由却返回 ``None``，
          ``run_shell`` 再 ``subprocess.Popen`` 在真实工作区跑**第二遍**
          —— 命令双重执行，隔离层的脱敏 env / 出网裁决结果被整个丢弃。
          实测隔离层 1 次 + bare Popen 1 次，返回的是第二次的结果。
F1        ``_run_provider`` 强后端抛异常 → 捕获后返回
          ``returncode=-1, enforced=False`` → 同样回落裸跑。
F2        ``subprocess.TimeoutExpired`` → 同样回落裸跑。
F3        ``copy_diff_apply`` 的 ``isolate_workdir`` 抛异常 → 外层
          ``except`` 返回 ``enforced=True`` **宣称已隔离执行**（一个副本
          都没建、命令根本没跑），但路由只看 ``verdict.enforced``
          （仍 False）→ 同样回落裸跑。
F4        ``build_diff_preview`` 失败时 ``error`` 直接拼 ``str(exc)``，
          实测 ``GITHUB_TOKEN=ghp_REAL_SECRET_VALUE`` **原样回显**给用户；
          OSC 8 / RLO 也会进终端。
F5        ``copy_diff_apply`` 只拦了 ``terminal_refusal``；执行层超时 /
          崩溃返回 ``returncode=-1`` 时仍走 diff → confirm，让用户确认
          写回一个**根本没成功执行**的副本。
=========  ==========================================================

**修复**

- ``SandboxExecResult.decided: bool = True``（默认 fail-closed）：只要
  ``execute_isolated`` 真的被调用，任何结果都是终态。唯一合法的回落是
  执行层显式 ``decided=False``（``not verdict.isolate`` 分支）。
- 路由不再看 ``verdict.enforced`` / ``backend_available``，只问
  ``res.decided``。
- ``core/security_utils.safe_error_text()``：异常消息在**来源处**
  脱敏 + 剥离控制字符 + 限长；出口不二次净化，避免破坏 diff 预览可读性。
- ``copy_diff_apply`` 对 ``returncode < 0`` 也立刻返回；外层异常如实
  ``enforced=False``。

**矩阵计数一个不动**（`ahead 10 / aligned 46 / partial 9 / gap 26 /
not_applicable 8`）—— 纯深度修复，不靠改口径凑数。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tuan_cli.core import sandbox_provider as sp
from tuan_cli.core.security_utils import (
    redact_sensitive, safe_error_text,
)
from tuan_cli.sandbox.egress_allowlist import (
    claim_from_values, claim_to_verdict_extra,
)
from tuan_cli.sandbox.manager import SandboxExecResult, SandboxManager
from tuan_cli.sandbox.verdict import Verdict
from tuan_cli.tools import shell as SH


EVIL = "GITHUB_TOKEN=ghp_REAL_SECRET_VALUE /tmp/private/path"
SECRET = "ghp_REAL_SECRET_VALUE"


def _verdict(*, backend="landlock", isolate=True, workspace_mode="direct",
             enforced=False, backend_available=False) -> Verdict:
    v = Verdict()
    v.backend = backend
    v.network = True
    v.isolate = isolate
    v.workspace_mode = workspace_mode
    v.enforced = enforced
    v.backend_available = backend_available
    return v


class _Ctx:
    workspace = "/tmp/w"
    kernel = None
    confirm = None
    yolo = False

    def __init__(self, verdict):
        self._sandbox_verdict = verdict

    def config(self, _key, default=60):
        return default


class _WD:
    path = "/tmp/copy_wd"

    def cleanup(self):
        pass


class _Proc:
    stdout = "ISOLATED_RAN"
    stderr = ""
    returncode = 0


# ================================================ 1 decided 单一契约
class TestDecidedContract:
    def test_default_is_fail_closed(self):
        """任何真实结果默认都必须被采纳。"""
        assert SandboxExecResult().decided is True
        assert SandboxExecResult(returncode=-1, error="超时").decided is True

    def test_only_no_isolation_is_not_decided(self):
        """唯一合法的回落：执行层明确声明什么都没做。"""
        v = Verdict()
        v.isolate = False
        r = SandboxManager().execute_isolated("echo hi", v, _Ctx(v), 5.0)
        assert r.decided is False
        assert r.returncode == 0 and r.stdout == ""

    def test_route_falls_back_only_on_decided_false(self):
        v = _verdict()
        r = SandboxExecResult(decided=False)
        with patch.object(SandboxManager, "execute_isolated", return_value=r):
            assert SH._route_sandbox_isolation(_Ctx(v), "echo hi", 60) is None

    def test_result_defaults_backward_compatible(self):
        r = SandboxExecResult(stdout="x", returncode=0)
        assert r.as_shell_text() == "x"
        assert r.terminal_refusal is False
        assert r.enforced is False


# ================================================ 2 G: 不再双重执行
class TestNoDoubleExecution:
    def test_degraded_deployment_accepts_isolated_result(self):
        """降级部署里隔离层已执行，路由必须采纳而不是再跑一遍。"""
        v = _verdict(backend="local")
        calls: list[str] = []

        def fake_run(*_a, **_kw):
            calls.append("isolated")
            return _Proc()

        with patch("tuan_cli.core.proc.run_with_tree_kill", fake_run):
            out = SH._route_sandbox_isolation(_Ctx(v), "echo hi", 60)
        assert calls == ["isolated"]
        assert out is not None
        assert "ISOLATED_RAN" in out

    def test_run_shell_does_not_bare_popen_after_isolation(self):
        """端到端：run_shell 里 bare Popen 一次都不该发生。"""
        v = _verdict(backend="local")
        bare = []

        class _FakePopen:
            def __init__(self, *_a, **_kw):
                bare.append("bare")

            def communicate(self, **_kw):
                return ("BARE_RAN", "")

            def kill(self):
                pass

        with patch("tuan_cli.core.proc.run_with_tree_kill",
                   return_value=_Proc()), \
             patch("subprocess.Popen", _FakePopen), \
             patch("tuan_cli.tools.shell._pre_exec_guard", return_value=None):
            out = SH.run_shell(_Ctx(v), "echo hi", 60)
        assert bare == []
        assert "ISOLATED_RAN" in (out or "")

    @pytest.mark.parametrize("enforced,backend_available", [
        (False, False), (False, True), (True, False), (True, True),
    ])
    def test_all_verdict_flags_accept_result(self, enforced, backend_available):
        """四种裁决标志组合下都采纳结果，不再依赖 verdict 字段。"""
        v = _verdict(backend="local", enforced=enforced,
                     backend_available=backend_available)
        with patch("tuan_cli.core.proc.run_with_tree_kill",
                   return_value=_Proc()):
            out = SH._route_sandbox_isolation(_Ctx(v), "echo hi", 60)
        assert out is not None and "ISOLATED_RAN" in out


# ================================================ 3 F1/F2/F3: 失败不回落
class TestFailuresAreTerminal:
    def test_strong_backend_crash_does_not_fall_back(self):
        v = _verdict(backend="landlock")
        with patch.object(sp.SandboxProvider, "create",
                          side_effect=RuntimeError("backend exploded: " + EVIL)):
            out = SH._route_sandbox_isolation(_Ctx(v), "curl https://evil", 60)
        assert out is not None
        assert "错误" in out
        assert SECRET not in out
        assert "[REDACTED]" in out

    def test_timeout_does_not_fall_back(self):
        v = _verdict(backend="local")
        with patch("tuan_cli.core.proc.run_with_tree_kill",
                   side_effect=subprocess.TimeoutExpired(cmd="echo", timeout=5.0)):
            out = SH._route_sandbox_isolation(_Ctx(v), "echo hi", 60)
        assert out is not None and "超时" in out

    def test_copy_create_failure_does_not_fall_back(self):
        v = _verdict(workspace_mode="copy_diff_apply")
        with patch("tuan_cli.sandbox.isolation.isolate_workdir",
                   side_effect=OSError("cannot create copy: " + EVIL)):
            out = SH._route_sandbox_isolation(_Ctx(v), "echo hi", 60)
        assert out is not None
        assert "副本隔离执行失败" in out
        assert SECRET not in out

    def test_copy_create_failure_does_not_claim_enforced(self):
        """F3 语义谎言：一个副本都没建，不许写 enforced=True。"""
        v = _verdict(workspace_mode="copy_diff_apply")
        with patch("tuan_cli.sandbox.isolation.isolate_workdir",
                   side_effect=OSError("boom")):
            r = SandboxManager().execute_isolated("echo hi", v, _Ctx(v), 5.0)
        assert r.enforced is False
        assert r.decided is True
        assert r.applied is False

    def test_route_own_exception_does_not_fall_back_and_is_sanitized(self):
        """路由自身 except 分支也净化，且返回终态错误文本。"""
        v = _verdict()
        with patch.object(SandboxManager, "execute_isolated",
                          side_effect=RuntimeError("init failed: " + EVIL)):
            out = SH._route_sandbox_isolation(_Ctx(v), "echo hi", 60)
        assert out is not None
        assert SECRET not in out
        assert "沙箱隔离执行初始化异常" in out


# ================================================ 4 F4/F5: 净化与早返回
class TestErrorTextSanitization:
    def test_diff_preview_failure_hides_secret(self):
        v = _verdict(workspace_mode="copy_diff_apply")
        with patch("tuan_cli.sandbox.isolation.isolate_workdir",
                   return_value=_WD()), \
             patch.object(SandboxManager, "_execute_backend",
                          return_value=SandboxExecResult(stdout="ok", returncode=0)), \
             patch("tuan_cli.sandbox.isolation.build_diff_preview",
                   side_effect=RuntimeError("preview failed: " + EVIL)):
            out = SH._route_sandbox_isolation(_Ctx(v), "echo hi", 60)
        assert SECRET not in (out or "")
        assert "生成变更预览失败" in (out or "")

    def test_backend_crash_hides_secret(self):
        v = _verdict(backend="landlock")
        with patch.object(sp.SandboxProvider, "create",
                          side_effect=RuntimeError(EVIL)):
            r = SandboxManager()._execute_backend("echo hi", v, "/tmp", 5.0)
        assert SECRET not in r.error
        assert r.decided is True

    def test_execution_failure_skips_diff_and_confirmation(self):
        """F5: 执行失败不生成 diff、不要确认、不宣称已隔离。"""
        v = _verdict(workspace_mode="copy_diff_apply")
        with patch("tuan_cli.sandbox.isolation.isolate_workdir",
                   return_value=_WD()), \
             patch.object(SandboxManager, "_execute_backend",
                          return_value=SandboxExecResult(
                              returncode=-1, error="超时", enforced=False)), \
             patch("tuan_cli.sandbox.isolation.build_diff_preview",
                   side_effect=AssertionError("不应生成 diff")), \
             patch("tuan_cli.sandbox.isolation.confirm_apply",
                   side_effect=AssertionError("不应确认")):
            r = SandboxManager().execute_isolated("echo hi", v, _Ctx(v), 5.0)
        assert r.returncode == -1
        assert r.applied is False and r.applied_files == []
        assert r.diff_preview is None
        assert v.enforced is False

    def test_user_decline_still_shows_preview(self):
        """用户主动拒绝写回时，预览仍要原样可见（出口不二次净化）。"""
        v = _verdict(workspace_mode="copy_diff_apply")

        class _Out:
            applied = False
            files: list[str] = []
            reason = "user declined"
            preview = None

        class _Preview:
            def to_dict(self):
                return {"f.py": "changed"}

            def to_text(self):
                return "--- a/f.py\n+++ b/f.py\n+print('hi')"

        with patch("tuan_cli.sandbox.isolation.isolate_workdir",
                   return_value=_WD()), \
             patch.object(SandboxManager, "_execute_backend",
                          return_value=SandboxExecResult(stdout="ok", returncode=0)), \
             patch("tuan_cli.sandbox.isolation.build_diff_preview",
                   return_value=_Preview()), \
             patch("tuan_cli.sandbox.isolation.confirm_apply",
                   return_value=_Out()), \
             patch("tuan_cli.ui.approval_overlay.make_confirm_callable",
                   return_value=(None, lambda *_a, **_k: False)):
            out = SH._route_sandbox_isolation(_Ctx(v), "echo hi", 60)
        assert out is not None
        assert "user declined" in out
        assert "+print('hi')" in out


# ================================================ 5 safe_error_text 单元
class TestSafeErrorText:
    def test_redacts_secret_values(self):
        assert SECRET not in safe_error_text(EVIL)
        assert "[REDACTED]" in safe_error_text(EVIL)
        assert "[REDACTED]" in safe_error_text("OPENAI_API_KEY=sk-abcdefghijklmnopqrst")

    def test_strips_terminal_controls(self):
        out = safe_error_text("RuntimeError: \x1b]8;;https://evil\x07RLO\u202e中文")
        assert "\x1b" not in out
        assert "\x07" not in out
        assert "\u202e" not in out
        assert "中文" in out

    def test_non_str_uses_type_name_only(self):
        """不 str() 未知对象，避免 repr 泄露。"""
        assert safe_error_text(123) == "int"
        assert safe_error_text(["a"]) == "list"
        assert safe_error_text(None) == ""

    def test_limit_and_dirty_limit(self):
        assert len(safe_error_text("A" * 900)) < 500
        for bad in (None, 0, -1, True, "400", float("nan"), 10 ** 9):
            out = safe_error_text("A" * 900, bad)
            assert len(out) < 500 and "截断" in out

    def test_never_raises(self):
        class _Bad:
            def __str__(self):
                raise RuntimeError("nope")

        # 非 str 走类型名，根本不调 __str__
        assert safe_error_text(_Bad()) == "_Bad"

    def test_global_redact_sensitive_unchanged(self):
        """本轮没改全局脱敏原语，避免影响其它调用点。"""
        assert redact_sensitive(EVIL).find(SECRET) == -1
        # 控制字符剥离是 safe_error_text 的职责，不在全局原语里
        assert "\x1b" in redact_sensitive("x\x1by")


# ================================================ 6 不该修的判定
class TestNotChangedOnPurpose:
    def test_unterminated_osc_params_remain_readable(self):
        """OSC 参数残留是如实边界，不是 bug。

        ESC / BEL / RLO 已剥离，终端不会再解释它；残留 ``]8;;`` 只是
        可读性略差。彻底删掉会误伤合法文本，且错误文本不参与 UI 宽度
        判定，不与标语净化层构成重复真值。
        """
        out = safe_error_text("\x1b]8;;https://evil.example\x07END")
        assert "\x1b" not in out and "END" in out

    def test_no_second_sanitization_at_route_exit(self):
        """出口不二次净化：diff 预览必须原样可读（见 test_user_decline）。

        A′：初版断言写成 ``count == 1``，实测是 2 —— 因为同一个 except
        分支里既有 ``from ... import safe_error_text`` 又有一次调用。
        两处都在**自身异常分支**内，不是出口二次净化。断言改成检查
        结果的返回语句原样使用 ``res.error``，并锁定出现次数。
        """
        src = Path(SH.__file__).read_text(encoding="utf-8")
        i = src.index("def _route_sandbox_isolation")
        window = src[i:i + 2600]
        assert window.count("safe_error_text") == 2  # import + 自身 except 调用
        assert 'f"[错误] {res.error or' in window  # 出口原样使用 res.error
        assert "safe_error_text(res.error" not in window

    def test_no_direct_provider_run_outside_manager(self):
        """沿用上一轮源码扫描：没有绕过 plan_egress 的执行侧门。"""
        import re
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


# ================================================ 7 矩阵自洽
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
