"""本轮深度修复回归：对外 MCP `run_shell` 不再绕过整套闸门。

**实测缺口（先复现再修）**

前十几轮把 `tools/shell.py` 主链路的 `plan_egress` / `decided` /
脱敏 env / 异常文本净化逐层接好，但 `ecosystem/mcp_server.py` 的
`_h_run_shell` 是**全仓唯一一处「外部 Agent 直接提供 command、
用 shell=True 执行」的入口**，完全没接：

=========  ==========================================================
编号       实测结果
=========  ==========================================================
M1        只做 ``is_hard_redline`` / ``is_redline`` **文本判定**，
          不经过 ``SandboxManager.assess_command`` / ``plan_egress``。
          深度轮 fuzz 已证明零宽字符 / ANSI-C / 注释换行能绕过文本层。
M2        ``subprocess.run`` **不传 env**，子进程继承父进程完整环境，
          实测 ``GITHUB_TOKEN=ghp_REAL_SECRET_VALUE`` 原样进入，
          与 §13/§15 刚落地的「子进程不持密钥」直接矛盾。
M3        异常分支把 ``str(exc)`` 原样回显给外部 Agent：实测真实密钥串、
          OSC / RLO 控制字符都会外泄（执行失败与安全判定失败两处）。
=========  ==========================================================

**修复（如实，不夸大）**

- 接 ``SandboxManager.assess_command`` 四层滤网裁决：DENY / CONFIRM /
  ``isolate=True`` 一律 fail-closed 拒绝（MCP 无确认通道、套不上同步
  隔离执行器），与后台 ``! cmd`` 同一契约。
- 接 ``plan_egress(verdict, "local", ...)``：``allowed=False`` 拒绝；
  ``plan.env``（sentinel 脱敏）显式传给 subprocess，并补回
  ``TUAN_WORKSPACE``。
- 所有异常出口过 ``safe_exception_text`` / ``safe_error_text``。
- 工具描述如实标注：**MCP 通道没有 OS 级隔离 / 逐命令域名强绑定 /
  副本确认**；backend 固定 ``local``，绝不拿 verdict 里的强后端名字
  假装已隔离。
- 默认 ``allow_dangerous_tools=false`` 仍不暴露该工具，行为不变。

**顺带修的口径缺陷**：``tools/shell.py`` 后台分支注释曾引用一个章节
编号，但仓库里存在多套编号体系、那一节讲的是标语线而非后台修复。
改成自足描述，不做全局重编号（会动大量既有交叉引用）。

**矩阵计数一个不动**（`ahead 10 / aligned 46 / partial 9 / gap 26 /
not_applicable 8`）—— 纯深度修复，不靠改口径凑数。
"""
from __future__ import annotations

import os
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest

from tuan_cli.ecosystem import mcp_server as MS
from tuan_cli.sandbox.egress import SENTINEL_PREFIX
from tuan_cli.sandbox.verdict import Action, Verdict


SECRET = "ghp_REAL_SECRET_VALUE"
SECRET2 = "sk-REALKEY0123456789ABCDEFG"


@pytest.fixture(autouse=True)
def _dirty_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", SECRET)
    monkeypatch.setenv("OPENAI_API_KEY", SECRET2)


class _Proc:
    stdout = "RAN"
    stderr = ""
    returncode = 0


def _server() -> MS.McpToolServer:
    s = MS.McpToolServer.__new__(MS.McpToolServer)
    s.workspace = Path("/tmp/ws")
    s.home = Path("/tmp/home")
    s.allow_dangerous_tools = True
    s._tools = []
    return s


def _call(srv, command="echo hi", *, verdict=None,
          redline_exc=None, run_exc=None, assess_exc=None):
    """返回 (text, err_flag, captured_calls)。"""
    calls: list = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        if run_exc is not None:
            raise run_exc
        return _Proc()

    patches = [
        patch("subprocess.run", fake_run),
        patch("tuan_cli.ext.safety_engine.is_redline", return_value=False),
    ]
    if redline_exc is not None:
        patches.append(patch("tuan_cli.ext.safety_engine.is_hard_redline",
                             side_effect=redline_exc))
    else:
        patches.append(patch("tuan_cli.ext.safety_engine.is_hard_redline",
                             return_value=False))
    if assess_exc is not None:
        patches.append(patch("tuan_cli.sandbox.manager.SandboxManager.assess_command",
                             side_effect=assess_exc))
    elif verdict is not None:
        patches.append(patch("tuan_cli.sandbox.manager.SandboxManager.assess_command",
                             return_value=verdict))
    with ExitStack() as st:
        for p in patches:
            st.enter_context(p)
        text, err = srv._h_run_shell({"command": command})
    return text, err, calls


def _verdict(*, action=Action.ALLOW, isolate=False, network=True):
    v = Verdict()
    v.action = action
    v.isolate = isolate
    v.network = network
    return v


# ================================================ 1 M2: 脱敏 env
class TestSanitizedChildEnv:
    def test_subprocess_receives_env_not_inherited(self):
        text, err, calls = _call(_server())
        assert err is False
        assert len(calls) == 1
        assert "env" in calls[0][1], "不传 env = 继承父进程真实密钥"

    def test_no_real_secret_in_child_env(self):
        _, _, calls = _call(_server())
        env = calls[0][1]["env"]
        assert SECRET not in str(env)
        assert SECRET2 not in str(env)
        assert env["GITHUB_TOKEN"].startswith(SENTINEL_PREFIX)
        assert env["OPENAI_API_KEY"].startswith(SENTINEL_PREFIX)

    def test_workspace_indicator_restored(self):
        """SECRET_HINTS 含 TUAN_，必须按 workspace 参数补回（同 §15）。"""
        _, _, calls = _call(_server())
        assert calls[0][1]["env"]["TUAN_WORKSPACE"] == "/tmp/ws"

    def test_sentinel_count_matches_sensitive_keys(self):
        _, _, calls = _call(_server())
        env = calls[0][1]["env"]
        n = sum(1 for x in env.values()
                if isinstance(x, str) and SENTINEL_PREFIX in x)
        assert n >= 2

    def test_cwd_still_honored(self):
        _, _, calls = _call(_server())
        assert calls[0][1]["cwd"] == "/tmp/ws"


# ================================================ 2 M3: 异常文本净化
class TestErrorTextSanitization:
    def test_subprocess_oserror_hides_secret(self):
        text, err, calls = _call(
            _server(), run_exc=OSError(f"GITHUB_TOKEN={SECRET} /tmp/private"))
        assert err is True
        assert SECRET not in text
        assert "[REDACTED]" in text

    def test_redline_engine_exception_hides_secret(self):
        text, err, calls = _call(
            _server(), redline_exc=RuntimeError(f"GITHUB_TOKEN={SECRET} boom"))
        assert err is True
        assert SECRET not in text
        assert len(calls) == 0

    def test_assessor_exception_is_fail_closed_and_sanitized(self):
        text, err, calls = _call(
            _server(), assess_exc=RuntimeError(f"GITHUB_TOKEN={SECRET}"))
        assert err is True
        assert SECRET not in text
        assert len(calls) == 0

    def test_control_characters_stripped(self):
        text, _, _ = _call(
            _server(),
            run_exc=OSError("x\x1b]8;;https://evil\x07RLO\u202e中文"))
        assert "\x1b" not in text and "\x07" not in text
        assert "\u202e" not in text
        assert "中文" in text

    def test_timeout_branch_is_terminal(self):
        import subprocess
        text, err, calls = _call(
            _server(), run_exc=subprocess.TimeoutExpired(cmd="echo", timeout=60))
        assert err is True and "超时" in text


# ================================================ 3 M1: 统一裁决
class TestVerdictGate:
    @pytest.mark.parametrize("action,label", [
        (Action.DENY, "DENY"),
        (Action.CONFIRM, "人工确认"),
    ])
    def test_deny_and_confirm_never_execute(self, action, label):
        text, err, calls = _call(_server(), verdict=_verdict(action=action))
        assert err is True
        assert len(calls) == 0
        assert label in text or "拒绝" in text

    def test_isolate_requirement_never_executes(self):
        text, err, calls = _call(_server(), verdict=_verdict(isolate=True))
        assert err is True
        assert len(calls) == 0
        assert "强隔离" in text

    def test_network_denied_never_executes(self):
        """plan_egress 的禁网 fail-closed 裁决在 MCP 通道同样生效。"""
        text, err, calls = _call(_server(), verdict=_verdict(network=False))
        assert err is True
        assert len(calls) == 0
        assert "出网合规拒绝" in text

    def test_empty_command_rejected(self):
        srv = _server()
        text, err = srv._h_run_shell({"command": "   "})
        assert err is True

    def test_hard_redline_still_first_layer(self):
        """既有文本红线防护保留，不因接入滤网而删除。"""
        srv = _server()
        with patch("tuan_cli.ext.safety_engine.is_hard_redline",
                   return_value=True), \
             patch("tuan_cli.ext.safety_engine.is_redline",
                   return_value=False), \
             patch("subprocess.run") as fr:
            text, err = srv._h_run_shell({"command": "echo hi"})
        assert err is True and "硬红线" in text
        assert not fr.called


# ================================================ 4 工具暴露与边界声明
class TestToolExposure:
    def test_not_exposed_by_default(self):
        s = MS.McpToolServer(home=Path("/tmp/home"),
                             workspace=Path("/tmp/ws"),
                             allow_dangerous_tools=False)
        names = [t["name"] for t in s.tools()]
        assert "run_shell" not in names
        assert "tuan_run" in names

    def test_exposed_when_opted_in(self):
        s = MS.McpToolServer(home=Path("/tmp/home"),
                             workspace=Path("/tmp/ws"),
                             allow_dangerous_tools=True)
        assert "run_shell" in [t["name"] for t in s.tools()]

    def test_description_states_no_os_isolation(self):
        """如实边界：绝不宣称 MCP 通道有 OS 级隔离。"""
        s = MS.McpToolServer(home=Path("/tmp/home"),
                             workspace=Path("/tmp/ws"),
                             allow_dangerous_tools=True)
        desc = [t["description"] for t in s.tools()
                if t["name"] == "run_shell"][0]
        assert "没有 OS 级隔离" in desc
        assert "脱敏 env" in desc
        assert "fail-closed" in desc

    def test_handler_not_leaked_in_tools_list(self):
        s = MS.McpToolServer(home=Path("/tmp/home"),
                             workspace=Path("/tmp/ws"),
                             allow_dangerous_tools=True)
        assert all("_handler" not in t for t in s.tools())


# ================================================ 5 不该修的判定
class TestNotChangedOnPurpose:
    def test_backend_is_always_local(self):
        """MCP 是同步裸 subprocess，如实申报 local，不拿强后端名假装隔离。

        verdict 里写 landlock 也不改 plan_egress 的 backend 实参。
        """
        src = Path(MS.__file__).read_text(encoding="utf-8")
        i = src.index("def _h_run_shell")
        window = src[i:i + 4200]
        assert 'plan_egress(verdict, "local"' in window

    def test_no_global_section_renumbering(self):
        """多套章节编号体系共存，本轮只把代码注释改成自足描述。"""
        src = Path("tuan_cli/tools/shell.py").read_text(encoding="utf-8")
        # 注释里不再引用任何具体章节编号
        assert "§17" not in src
        assert "后台分支实测缺口" in src

    def test_no_direct_provider_run_outside_manager(self):
        """沿用前两轮源码扫描：没有绕过 plan_egress 的执行侧门。"""
        import re
        from tuan_cli.core import sandbox_provider as sp
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

    def test_background_still_fail_closed_on_isolate(self):
        """后台 `! cmd` 的既有 fail-closed 契约未被本轮改动破坏。"""
        from tuan_cli.tools import shell as SH
        v = Verdict()
        v.isolate = True
        v.backend = "local"
        v.network = True

        class Ctx:
            workspace = "/tmp/w"
            kernel = None
            confirm = None
            yolo = False
            plan_mode = False
            _sandbox_verdict = v

        with patch("tuan_cli.tools.shell._pre_exec_guard", return_value=None), \
             patch("tuan_cli.tools.shell.run_in_background") as rb:
            out = SH._start_background(Ctx(), "! echo hi", 60)
        assert "不支持隔离执行" in out
        assert not rb.called


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
