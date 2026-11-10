"""B3 续轮 XII：hooks exit-code-2 深度真实性 + 两个模块级探针。

用户约束：「确保深度的真实复现，而非仅仅广度；开始做到百分百」。
这一轮**没有把任何 gap 数字往下刷**（B 线仍 ``gap 26``），而是先
实测复现并修掉一个真实安全洞，再给两条 B3 gap 各注册一个**真调
代码**的模块级运行时探针。

### 实测复现的真实缺陷（全部先跑通旧行为再修）

H1（最毒）：``exit 2 + stderr="BLOCKED: 禁止写 /etc"`` + stdout 一行
``{"hookSpecificOutput":{"permissionDecision":"allow"}}`` → 旧版
``block=False, reason="", failure_kind=""``。**失败闭合被一行 JSON
打穿，stderr 阻断原因彻底丢失**。这不是文档口径问题。

H2：CC 官方 PermissionRequest 格式
``hookSpecificOutput.decision.behavior="deny"`` → 旧版只认
``permissionDecision`` 字符串，dict 被整个忽略 → 静默放行。

H3：官方 ``behavior="allow" + updatedInput`` → 旧版不识别且决策类
一律忽略 args。

H4：``WorktreeCreate`` rc=1 + JSON allow → 旧版放行；CC 里任何非零
rc 都使创建失败，JSON 说了不算。

H5：官方事件面 33 项，旧表只有 15 —— 实测 18 个官方事件配置
**全部 0 加载**（只进 ``unknown_hook_event`` 审计）。

H6：``ToolPipeline`` 全仓扫描**生产构造方 0 个**（只有测试构造）。

H7：``runtime/tools/bridge.py::_run_base_handler`` 是真实生产旁路，
却直接 ``handler(ctx, **args)`` —— 外部多给一个未知键就抛
``TypeError``，缺 required / 类型不符也无人校验。主链路
``tools/base.py`` 早就修好了，这条漏了。

### A′（自己写错自己抓回）

1. ``module_probes.py`` 初版写了一个不存在的 ``exit_semantics_bridge``
   哨兵 import → 模块刚加载就 ImportError，两个探针一个注册不上。
2. ``classify()`` 初版对 rc=1 也把 JSON 全忽略 → 旧回归
   ``test_nonzero_rc_with_valid_decision_still_honors_decision`` 变红
   （``reason`` 从 ``"rc1"`` 变成 Tuan 闭合文案）。CC 在**非 2** 的
   非零退出码下仍读取有效 JSON decision；已加 ``json_may_override``
   字段，只有 exit 2 / any_nonzero_fails 才锁死 JSON 覆盖。
3. 事件表断言从 15 同步到 33 时，import 路径写错（从 ``hooks`` 包
   取未导出的名字）→ 改从 ``hooks.manager`` 取。

### 如实边界

- **两条 gap 状态一个没动**：新增 18 个事件仍只有通知通道、无生产
  触发点、无 JSON decision 裁决；Elicitation 语义刻意不等价（Tuan
  不允许模型自问自答）；CC 事件面持续演进。硬理由被收窄但未消除，
  不靠改状态定义凑数。
- ``ToolPipeline`` 是**可选执行通道**，主链路仍是 ``execute_batch``；
  它提供「全路径 schema 证据」的可核销生产实例，不假称所有调用改走
  pipeline。
- ``exit_semantics`` 的逐事件表来自官方 Hooks 参考 + 逐事件表交叉
  核对；CC 不同页面对「exit 2 时 stdout JSON 是否被读取」措辞有差异，
  锁死的是所有来源一致的硬规则：**allow 不能覆盖 exit 2**。
- Tuan ``on_failure=block`` 出厂默认比 CC 更严（CC 里 exit 1 是非
  阻断错误），这是 B1 既有安全立场，**不因为对标就放宽**；
  ``compare_with_tuan_policy()`` 把差异逐项列出来。
- 标语引擎 / 净化层 / ``mapping.py`` / ``tui.py`` /
  ``runtime_slogans.py`` / ``catalog.py`` 状态字段逐字节未改。
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from tuan_cli.hooks import exit_semantics as XS
from tuan_cli.hooks import manager as HM
from tuan_cli.hooks.input_validation import validate_updated_input
from tuan_cli.parity_claude import depth as BD, catalog as C, matrix as BM

PY = sys.executable
ALLOW = json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse", "permissionDecision": "allow"}})


class _K:
    def __init__(self):
        self.events = []

    def get(self, n, d=None):
        return d

    def emit(self, t, p=None):
        self.events.append((t, p or {}))

    def on(self, *a, **k):
        pass


def _script(rc, stdout="", stderr=""):
    d = tempfile.mkdtemp(prefix="tuan_xii_")
    p = Path(d) / "h.py"
    p.write_text("import sys\nsys.stdout.write(%r)\nsys.stderr.write(%r)\n"
                 "sys.exit(%d)\n" % (stdout, stderr, rc), encoding="utf-8")
    return {"command": [PY, str(p)]}


def _mgr(block):
    return HM.HookManager({"hooks": dict(block)}, kernel=_K())


# ================================================== 真值表
class TestExitSemanticsTable:
    def test_validate_clean(self):
        assert XS.validate() == []

    def test_official_surface(self):
        assert len(XS.OFFICIAL_EVENTS) == 33
        assert set(HM.HOOK_EVENTS) == set(XS.OFFICIAL_EVENTS)
        assert XS.ANY_NONZERO_FAILS_EVENTS == frozenset(
            {"WorktreeCreate", "WorktreeRemove"})
        assert XS.EXIT_IGNORED_EVENTS == frozenset(
            {"PermissionDenied", "StopFailure", "InstructionsLoaded"})
        assert len(XS.NO_MATCHER_EVENTS) == 10

    def test_per_event_exit2(self):
        cases = [
            ("PreToolUse", True), ("UserPromptSubmit", True),
            ("UserPromptExpansion", True), ("Stop", True),
            ("SubagentStop", True), ("TeammateIdle", True),
            ("TaskCreated", True), ("TaskCompleted", True),
            ("ConfigChange", True), ("PostToolBatch", True),
            ("PreCompact", True), ("Elicitation", True),
            ("ElicitationResult", True), ("WorktreeCreate", True),
            ("WorktreeRemove", True), ("PreModelSwitch", True),
            ("PermissionRequest", False), ("PermissionDenied", False),
            ("StopFailure", False), ("InstructionsLoaded", False),
            ("PostToolUse", False), ("PostToolUseFailure", False),
            ("PostModelSwitch", False), ("SessionStart", False),
            ("Setup", False), ("SubagentStart", False),
            ("SessionEnd", False), ("Notification", False),
            ("CwdChanged", False), ("FileChanged", False),
            ("DirectoryAdded", False), ("PostCompact", False),
            ("MessageDisplay", False),
        ]
        for ev, expect in cases:
            v = XS.classify(ev, 2, "boom", tuan_policy="block")
            assert v.block is expect, (ev, v.code_path)

    def test_tuan_policy_difference_is_explicit(self):
        cmp = XS.compare_with_tuan_policy()
        assert cmp["events"] == 33
        assert cmp["exit2_always_blocks_when_preventable"] is True
        assert len(cmp["non2_nonzero_differences"]) > 0

    def test_exit2_json_override_locked(self):
        v = XS.classify("PreToolUse", 2, "boom", tuan_policy="allow")
        assert v.block and v.json_ignored and not v.json_may_override
        v1 = XS.classify("PreToolUse", 1, "boom")
        assert v1.json_may_override and not v1.json_ignored


# ================================================== H1-H5 真实复现修复
class TestRealHookBehaviour:
    def test_h1_exit2_cannot_be_overridden_by_json_allow(self):
        m = _mgr({"enabled": True, "PreToolUse": [
            _script(2, ALLOW, "BLOCKED: 禁止写 /etc")]})
        d = m.run_pre("write_file", {"path": "/etc/passwd"})
        assert d.block is True
        assert "BLOCKED" in d.reason
        assert d.failure_kind == "exit_2"

    def test_h1_with_allow_policy_still_blocks(self):
        m = _mgr({"enabled": True, "on_failure": "allow",
                  "PreToolUse": [_script(2, ALLOW, "boom")]})
        assert m.run_pre("write_file", {}).block is True

    def test_h2_official_permission_request_deny(self):
        out = json.dumps({"hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "deny", "message": "策略禁止"}}})
        m = _mgr({"enabled": True, "PermissionRequest": [_script(0, out)]})
        d = m.run_decision("PermissionRequest", tool_name="write_file")
        assert d.block is True and "策略禁止" in d.reason

    def test_h3_official_allow_with_updated_input(self):
        out = json.dumps({"hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "allow",
                         "updatedInput": {"plan": "new"}}}})
        m = _mgr({"enabled": True, "PermissionRequest": [_script(0, out)]})
        d = m.run_decision("PermissionRequest", tool_name="ExitPlanMode")
        assert d.block is False and d.args == {"plan": "new"}

    def test_h3_allow_without_updated_input_drops_args(self):
        out = json.dumps({"hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "allow"}}})
        m = _mgr({"enabled": True, "PermissionRequest": [_script(0, out)]})
        assert m.run_decision("PermissionRequest",
                              tool_name="ExitPlanMode").args is None

    def test_h4_worktree_any_nonzero_fails(self):
        m = _mgr({"enabled": True, "WorktreeCreate": [
            _script(1, ALLOW, "create failed")]})
        d = m.run_decision("WorktreeCreate")
        assert d.block is True and "create failed" in d.reason

    def test_h5_18_official_events_load(self):
        blk = {"enabled": True}
        for e in HM.OFFICIAL_EXTRA_EVENTS:
            blk[e] = [_script(0, "{}")]
        m = _mgr(blk)
        loaded = {s.event for s in m._specs}
        assert set(HM.OFFICIAL_EXTRA_EVENTS) <= loaded

    def test_rc1_valid_json_reason_honored(self):
        """A′ #2：非 2 的非零 rc 下 hook 自己的 reason 不能被吞。"""
        m = _mgr({"enabled": True, "PreToolUse": [
            _script(1, json.dumps({"block": True, "reason": "rc1"}))]})
        d = m.run_pre("write_file", {})
        assert d.block is True and d.reason == "rc1"
        assert d.failure_kind == ""

    def test_permission_request_exit2_not_honored(self):
        """CC: PermissionRequest 的 exit 2 不生效，权限流照旧。"""
        m = _mgr({"enabled": True, "PermissionRequest": [
            _script(2, "{}", "boom")]})
        d = m.run_decision("PermissionRequest", tool_name="write_file")
        assert d.block is False

    def test_exit_ignored_events_never_block(self):
        for name in ("PermissionDenied", "StopFailure",
                     "InstructionsLoaded"):
            for rc in (0, 1, 2, 7):
                assert XS.classify(name, rc, "boom").block is False


# ================================================== H6/H7 全路径 schema
SCHEMA = {"type": "object", "properties": {
    "path": {"type": "string"}, "content": {"type": "string"}},
    "required": ["path", "content"]}


class _FakeTool:
    name = "write_file"
    parameters = SCHEMA
    dangerous = False
    read_only = False

    def handler(self, ctx, path, content):
        return "OK:" + path


class _Reg:
    def get(self, n):
        return _FakeTool() if n == "write_file" else None


class TestAllPathSchema:
    def test_validate_core_cases(self):
        base = {"path": "x", "content": "ok"}
        r = validate_updated_input({**base, "UNKNOWN": 1}, base,
                                   SCHEMA, "write_file")
        assert not r.deny and "UNKNOWN" not in r.sanitized
        assert validate_updated_input({"path": "x"}, base, SCHEMA,
                                      "write_file").deny
        assert validate_updated_input({"path": 1, "content": "ok"},
                                      base, SCHEMA, "write_file").deny
        assert validate_updated_input("x", base, SCHEMA, "w").deny
        assert validate_updated_input({**base, "Z": 1}, base, None,
                                      "w").enforced is False

    def test_h7_bridge_no_longer_expands_unknown_keys(self):
        from tuan_cli.runtime.tools import bridge
        cases = [
            ({"path": "x", "content": "ok", "UNKNOWN": "pwn"}, False),
            ({"path": "x"}, True),
            ({"path": 123, "content": "ok"}, True),
            ({"path": "x", "content": "ok"}, False),
        ]
        for raw, expect_err in cases:
            out = asyncio.run(bridge._run_base_handler(
                _FakeTool(), raw, "/tmp"))
            assert out.is_error is expect_err, (raw, out.output)
            if not expect_err:
                assert "TypeError" not in out.output

    def test_h6_real_production_pipeline(self):
        from tuan_cli.core.tool_executor import ToolExecutor
        ex = ToolExecutor(registry=_Reg())
        assert ex.pipeline is not None
        got = ex.pipeline.schema_resolver("write_file")
        assert isinstance(got, dict) and "required" in got
        assert ex.pipeline.schema_resolver("nope") is None

    def test_source_level_evidence(self):
        root = Path(__file__).resolve().parents[1]
        assert "tool_schema=tool.parameters" in (
            root / "tuan_cli/tools/base.py").read_text(encoding="utf-8")
        assert "tool_schema=schema" in (
            root / "tuan_cli/cli/cmd_hooks.py").read_text(encoding="utf-8")
        assert "ToolPipeline(" in (
            root / "tuan_cli/core/tool_executor.py").read_text(
                encoding="utf-8")
        assert "validate_updated_input" in (
            root / "tuan_cli/runtime/tools/bridge.py").read_text(
                encoding="utf-8")


# ================================================== 模块级探针 + 矩阵不动
class TestModuleProbesAndHonestMatrix:
    def test_gap_probes_registered_and_green(self):
        r = BD.gap_probe_audit()
        assert r["registered"] == 2 and r["verified"] == 2 and r["ok"]
        for name in ("hook_events_extended",
                     "hook_updated_input_validation"):
            assert r["results"][name]["ok"]
            assert r["results"][name]["checks"] >= 18

    def test_module_depth_still_honest(self):
        """非 gap 模块仍 0 个模块级探针 —— 不把 gap 探针混进这个数字。"""
        m = BD.module_depth_audit()
        assert m["claimed"] == 65 and m["probe_verified"] == 0
        assert m["runtime_verified_pct"] == 0.0

    def test_probe_failure_is_not_swallowed(self):
        from tuan_cli.parity_claude import module_probes as MP
        old = BD.MODULE_PROBES["hook_events_extended"]
        try:
            BD.MODULE_PROBES["hook_events_extended"] = lambda: {
                "ok": False, "checks": 0, "evidence": "forced",
                "problems": ["forced_failure"]}
            assert BD.gap_probe_audit()["ok"] is False
        finally:
            BD.MODULE_PROBES["hook_events_extended"] = old
        assert BD.gap_probe_audit()["ok"] is True

    def test_b_matrix_unchanged(self):
        s = BM.summary()
        assert s["by_status"] == {
            "ahead": 10, "aligned": 46, "partial": 9,
            "gap": 26, "not_applicable": 8}
        assert s["gaps"] == 26
        assert s["fully_superior"] is False
        assert s["b_waves_done"] == ["B1"]
        assert BM.validate() == []

    def test_two_gaps_still_gap(self):
        for name in ("hook_events_extended",
                     "hook_updated_input_validation"):
            m = next(x for x in C.MODULES if x.name == name)
            assert m.status == C.STATUS_GAP

    def test_gap_queue_unchanged(self):
        q = BD.gap_queue()
        assert q["gaps"] == 26
        assert q["by_wave"] == {
            "B10": 5, "B2": 1, "B3": 2, "B4": 1, "B5": 1,
            "B6": 4, "B7": 8, "B8": 1, "B9": 3}
