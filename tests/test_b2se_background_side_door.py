"""本轮深度修复回归：`! cmd` 后台侧门 + 后台子进程脱敏 env + 异常文本净化。

**实测缺口（先复现再修）**

前两轮（2108a541 / 1855ba08）把「是否回落」收口到
``SandboxExecResult.decided`` 单一契约，并把执行层异常消息接到
``safe_error_text``。这轮把镜头移到**路由之外、之前都存在的另一条执行
路径**：后台 shell。

=========  ==========================================================
编号       实测结果
=========  ==========================================================
B1        ``run_shell`` 开头 ``if is_bg_command(command): return
          _start_background(...)`` 位于 ``_pre_exec_guard`` 和
          ``_route_sandbox_isolation`` **之前**。实测带 ``isolate=True``
          裁决的 ``! curl https://evil.example``：隔离层调用 **0 次**、
          bare ``Popen`` **1 次**，返回「后台已启动」。整条
          plan_egress / 沙箱后端 / 出网合规裁决 / 凭据脱敏链路被绕过。
B2        ``BackgroundShellManager.start`` 的 ``subprocess.Popen``
          **完全不传 env**，后台子进程继承父进程完整环境。实测
          ``os.environ['GITHUB_TOKEN']='ghp_...'`` 时子进程拿到真实值；
          而后台分支又拿不到 plan_egress 的 sentinel 代理注入。
H1        上一轮所有错误路径写成
          ``f"{type(exc).__name__}: {safe_error_text(str(exc))}"``，
          但 ``str(exc)`` 在**调用方**就执行。异常对象的 ``__str__``
          抛错时整个 ``except`` 分支被掀翻，实测冒泡 RuntimeError。
H2        ``shell.py`` 还有 5 处裸 ``{exc}`` 回显（信任级别裁决异常、
          ``run_shell`` 主体、``_start_background`` 的 ValueError /
          通用异常、``bg_shell``），``background_shell.py`` 还有 1 处；
          实测 ``GITHUB_TOKEN=ghp_...`` 与 OSC/RLO 原样进用户终端。
=========  ==========================================================

**修复**

- ``_start_background``：裁决要求隔离时 **fail-closed 拒绝**（异步路径
  无法套用同步隔离执行器与 copy-diff-apply 确认，绝不假装隔离生效）；
  其余后台命令显式传 ``sanitize_env()`` 脱敏环境并补
  ``TUAN_WORKSPACE``。
- ``background_shell.py``：``start`` / ``run_in_background`` 增加
  ``env`` 形参（``None`` 保持既有继承语义），Popen 透传。
- ``core/security_utils.safe_exception_text()``：把 ``str(exc)`` 包进
  try，异常时丢弃原文只留类型名；正常时复用 ``safe_error_text``。
  全部 12 处错误回显统一走它。

**矩阵计数一个不动**（`ahead 10 / aligned 46 / partial 9 / gap 26 /
not_applicable 8`）—— 纯深度修复，不靠改口径凑数。
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tuan_cli.core import background_shell as BG
from tuan_cli.core.security_utils import (
    redact_sensitive, safe_error_text, safe_exception_text, sanitize_env,
)
from tuan_cli.sandbox.manager import SandboxExecResult, SandboxManager
from tuan_cli.sandbox.verdict import Verdict
from tuan_cli.tools import shell as SH


EVIL = "GITHUB_TOKEN=ghp_REAL_SECRET_VALUE /tmp/private/path"
SECRET = "ghp_REAL_SECRET_VALUE"


class _Ctx:
    workspace = "/tmp/w"
    kernel = None
    confirm = None
    yolo = False

    def __init__(self, verdict=None):
        self._sandbox_verdict = verdict

    def config(self, _key, default=60):
        return default


def _isolated_verdict() -> Verdict:
    v = Verdict()
    v.backend = "landlock"
    v.network = True
    v.isolate = True
    v.workspace_mode = "direct"
    v.enforced = False
    v.backend_available = False
    return v


class _FakePopen:
    def __init__(self, *_a, **kw):
        self.kw = kw
        self.pid = 1
        self.stdout = None
        self.stderr = None
        self.returncode = None

    def poll(self):
        return None

    def wait(self, **_kw):
        return 0

    def kill(self):
        pass


class _Proc:
    stdout = "ISOLATED_RAN"
    stderr = ""
    returncode = 0


# ================================================ 1 B1: 后台侧门
class TestBackgroundSideDoor:
    def test_isolated_background_command_is_refused(self):
        """实测旧行为：隔离层调用 0 次、bare Popen 1 次、返回「后台已启动」。"""
        v = _isolated_verdict()
        isolated_calls: list[str] = []
        with patch.object(SandboxManager, "execute_isolated",
                          side_effect=lambda *_a, **_k: (
                              isolated_calls.append("isolated"),
                              SandboxExecResult(stdout="ISOLATED", returncode=0))[1]), \
             patch("tuan_cli.tools.shell._pre_exec_guard", return_value=None), \
             patch("subprocess.Popen",
                   side_effect=AssertionError("不应裸跑")) as popen:
            out = SH.run_shell(_Ctx(v), "! curl https://evil.example", 60)
        assert isolated_calls == []
        assert popen.call_count == 0
        assert out.startswith("[错误]")
        assert "后台命令" in out and "不支持隔离执行" in out
        assert "去掉 `!`" in out

    def test_non_isolated_background_still_starts(self):
        """不带隔离裁决的后台命令保持既有行为（但 env 已脱敏，见下）。"""
        cap: dict = {}
        with patch("tuan_cli.tools.shell._pre_exec_guard", return_value=None), \
             patch("subprocess.Popen",
                   side_effect=lambda *a, **kw: (cap.update(kw), _FakePopen(**kw))[1]):
            out = SH.run_shell(_Ctx(None), "! echo hi", 60)
        assert out.startswith("[后台已启动]")
        assert cap.get("env") is not None

    def test_isolate_false_verdict_allows_background(self):
        v = Verdict()
        v.isolate = False
        with patch("tuan_cli.tools.shell._pre_exec_guard", return_value=None), \
             patch("subprocess.Popen", _FakePopen):
            out = SH.run_shell(_Ctx(v), "! echo hi", 60)
        assert out.startswith("[后台已启动]")

    def test_missing_verdict_is_not_treated_as_isolated(self):
        """如实边界：ctx 没有裁决对象时不拦（裁决链自身的上游边界）。

        本轮不伪造裁决，也不用文本层猜测命令是否高危 —— 那会重新引入
        「看字符串」的绕过面。回归锁住当前事实。
        """
        with patch("tuan_cli.tools.shell._pre_exec_guard", return_value=None), \
             patch("subprocess.Popen", _FakePopen):
            out = SH.run_shell(_Ctx(), "! echo hi", 60)
        assert out.startswith("[后台已启动]")


# ================================================ 2 B2: 脱敏 env
class TestBackgroundChildEnv:
    def test_child_env_has_no_real_secrets(self):
        cap: dict = {}
        with patch.dict(os.environ,
                        {"GITHUB_TOKEN": SECRET,
                         "OPENAI_API_KEY": "sk-REALVALUE123456"}, clear=False), \
             patch("tuan_cli.tools.shell._pre_exec_guard", return_value=None), \
             patch("subprocess.Popen",
                   side_effect=lambda *a, **kw: (cap.update(kw), _FakePopen(**kw))[1]):
            SH.run_shell(_Ctx(None), "! echo hi", 60)
        env = cap.get("env")
        assert env is not None
        assert env.get("GITHUB_TOKEN") == ""
        assert env.get("OPENAI_API_KEY") == ""
        assert SECRET not in str(env)
        assert "sk-REALVALUE123456" not in str(env)

    def test_child_env_keeps_path_and_workspace(self):
        cap: dict = {}
        with patch("tuan_cli.tools.shell._pre_exec_guard", return_value=None), \
             patch("subprocess.Popen",
                   side_effect=lambda *a, **kw: (cap.update(kw), _FakePopen(**kw))[1]):
            SH.run_shell(_Ctx(None), "! echo hi", 60)
        env = cap["env"]
        assert env.get("PATH")
        # SECRET_HINTS 含 "TUAN_" 会抹掉它，按 workspace 参数补回（同 §15）
        assert env.get("TUAN_WORKSPACE") == "/tmp/w"
        assert cap.get("cwd") == "/tmp/w"

    def test_manager_env_none_keeps_legacy_inheritance(self):
        """start(env=None) 不改变既有继承语义：Popen 显式传 env=None。"""
        seen: dict = {}

        def _popen(*_a, **kw):
            seen.update(kw)
            return _FakePopen(**kw)

        mgr = BG.BackgroundShellManager(home=Path("/tmp/tuan_bg_test_home"))
        with patch("subprocess.Popen", _popen):
            job = mgr.start("echo hi", cwd="/tmp", env=None)
        assert "env" in seen and seen["env"] is None
        assert job.job_id

    def test_run_in_background_forwards_env(self):
        """便捷入口把脱敏 env 透传到 manager.start。"""
        seen: dict = {}

        class _Mgr:
            def start(self, *_a, **kw):
                seen.update(kw)
                return type("J", (), {"job_id": "x", "pid": 1})()

        with patch.object(BG, "get_manager", return_value=_Mgr()):
            BG.run_in_background("echo hi", env={"PATH": "/bin"})
        assert seen.get("env") == {"PATH": "/bin"}


# ================================================ 3 H1: __str__ 抛错
class TestSafeExceptionText:
    def test_broken_dunder_str_never_raises(self):
        class BadExc(Exception):
            def __str__(self):
                raise RuntimeError("__str__ exploded")

        out = safe_exception_text(BadExc())
        assert "BadExc" in out
        assert "不可用" in out and "已丢弃" in out
        assert "exploded" not in out

    def test_normal_exception_redacts_secret(self):
        out = safe_exception_text(RuntimeError("boom: " + EVIL))
        assert "RuntimeError" in out
        assert SECRET not in out
        assert "[REDACTED]" in out

    def test_strips_terminal_controls(self):
        out = safe_exception_text(ValueError("\x1b]8;;https://evil\x07RLO\u202e中文"))
        assert "\x1b" not in out and "\x07" not in out and "\u202e" not in out
        assert "中文" in out

    def test_backend_error_path_does_not_raise(self):
        """_execute_backend 的 except 分支不再被损坏异常掀翻。"""
        class BadExc(Exception):
            def __str__(self):
                raise RuntimeError("nope")

        v = Verdict()
        v.backend = "local"
        v.network = True
        v.isolate = True
        with patch("tuan_cli.core.proc.run_with_tree_kill", side_effect=BadExc()):
            r = SandboxManager()._execute_backend("echo hi", v, "/tmp", 5.0)
        assert r.returncode == -1
        assert r.decided is True
        assert "不可用" in r.error

    def test_safe_error_text_itself_unchanged(self):
        """上一轮的原语行为不变，safe_exception_text 只是补了 str() 兜底。"""
        assert safe_error_text(EVIL).find(SECRET) == -1
        assert redact_sensitive(EVIL).find(SECRET) == -1


# ================================================ 4 H2: 全部异常回显点
class TestAllErrorEchoPoints:
    def test_start_background_runtime_error(self):
        with patch("tuan_cli.tools.shell._pre_exec_guard", return_value=None), \
             patch("tuan_cli.tools.shell.run_in_background",
                   side_effect=RuntimeError("bg exploded: " + EVIL)):
            out = SH.run_shell(_Ctx(None), "! echo hi", 60)
        assert SECRET not in out and "[REDACTED]" in out

    def test_start_background_value_error(self):
        with patch("tuan_cli.tools.shell._pre_exec_guard", return_value=None), \
             patch("tuan_cli.tools.shell.run_in_background",
                   side_effect=ValueError("bad: " + EVIL)):
            out = SH.run_shell(_Ctx(None), "! echo hi", 60)
        assert SECRET not in out

    def test_run_shell_main_exception(self):
        with patch("tuan_cli.tools.shell._pre_exec_guard", return_value=None), \
             patch("subprocess.Popen", side_effect=RuntimeError(EVIL)):
            out = SH.run_shell(_Ctx(None), "echo hi", 60)
        assert SECRET not in out and "shell 执行异常" in out

    def test_route_own_exception(self):
        v = _isolated_verdict()
        with patch.object(SandboxManager, "execute_isolated",
                          side_effect=RuntimeError("init: " + EVIL)):
            out = SH._route_sandbox_isolation(_Ctx(v), "echo hi", 60)
        assert SECRET not in out
        assert "沙箱隔离执行初始化异常" in out

    def test_no_bare_exc_fstring_left_in_shell(self):
        """源码级：shell.py 里不再有裸 {exc} 回显。"""
        src = Path(SH.__file__).read_text(encoding="utf-8")
        assert "{exc}" not in src
        assert "safe_error_text(str(exc))" not in src

    def test_no_bare_exc_fstring_left_in_manager_and_bg(self):
        root = Path(SH.__file__).resolve().parent.parent
        for rel in ("sandbox/manager.py", "core/background_shell.py"):
            src = (root / rel).read_text(encoding="utf-8")
            assert "{exc}" not in src, rel
            assert "safe_error_text(str(exc))" not in src, rel


# ================================================ 5 不该修的判定
class TestNotChangedOnPurpose:
    def test_ignored_field_has_no_constructor_and_no_conflict_with_decided(self):
        """`ignored` 是死字段（全仓零构造点）。

        上一轮把 `decided` 默认改成 True 后，曾怀疑 `ignored=True` 语义
        相反会冲突。实测构造点数量为 0，不存在冲突 —— 保留字段做向后
        兼容，本轮不动，用源码扫描锁住结论。
        """
        root = Path(SH.__file__).resolve().parent.parent
        hits = []
        for f in root.rglob("*.py"):
            s = f.read_text(encoding="utf-8", errors="replace")
            if "ignored=True" in s and "SandboxExecResult" in s:
                hits.append(str(f))
        assert hits == []
        assert SandboxExecResult().ignored is False
        assert SandboxExecResult().decided is True

    def test_verdict_enforced_no_longer_drives_routing(self):
        """`verdict.enforced = True` 现在全仓没有消费点。

        它只是 copy_diff_apply 成功后的审计状态，不再决定是否回落
        （§16 起由 res.decided 决定）。本轮**不删**：删除会改变 verdict
        对象状态，可能有外部集成读取。如实标注 + 源码扫描锁住。
        """
        src = Path(SH.__file__).read_text(encoding="utf-8")
        i = src.index("def _route_sandbox_isolation")
        window = src[i:i + 2600]
        # A′：初版直接在整个窗口里查 "verdict.enforced"，被**注释**
        # （§16 描述旧实现）误伤。只检查非注释代码行。
        code_lines = [l for l in window.splitlines()
                      if l.strip() and not l.strip().startswith("#")]
        code = "\n".join(code_lines)
        assert "verdict.enforced" not in code
        # 实际写法是 getattr(..., "decided", True)（向后兼容旧结果对象）
        assert 'getattr(res, "decided", True)' in code

    def test_plan_mode_branch_only_blocks_writes(self):
        """Plan 模式分支在 guard 之前，但只 return 写命令。

        只读命令会继续往下走 guard + 隔离路由，所以它不是执行侧门。
        """
        src = Path(SH.__file__).read_text(encoding="utf-8")
        i = src.index("def run_shell")
        window = src[i:i + 900]
        assert 'not _is_readonly_command(command)' in window
        assert "is_bg_command" in window  # 后台分支确实在更前面（已修）

    def test_artifact_and_editor_popens_are_not_shell_side_doors(self):
        """如实边界：artifact_tool.py / code.py 的 Popen 打开编辑器/文件。

        它们不执行用户提供的 shell 命令、不受 shell 裁决管辖，
        本轮不动。若未来改成执行任意命令，需重新评估。
        """
        root = Path(SH.__file__).resolve().parent.parent
        for rel in ("tools/artifact_tool.py", "tools/code.py"):
            src = (root / rel).read_text(encoding="utf-8", errors="replace")
            assert "subprocess.Popen" in src  # 存在，如实记录
        # 它们不出现在 shell 的裁决链里
        src = Path(SH.__file__).read_text(encoding="utf-8")
        assert "artifact_tool" not in src


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
