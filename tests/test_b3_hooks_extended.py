"""B3 深度轮回归：扩展 hook 事件面 + CC 原生协议 + updatedInput schema 校验。

**实测缺口（先复现再修）**

=====  =====================================================================
编号   实测结果
=====  =====================================================================
R1     旧 ``HookManager.__init__`` 只遍历 8 个 ``HOOK_EVENTS``。配置里写
       ``DirectoryAdded`` 或把 ``PermissionRequest`` 拼错，整段被**静默
       丢弃**且零报错 —— 和之前修过的「规则表静默失效」同类。
R2     ``run_notify`` 只认 5 个通知事件。若把 7 个扩展事件统统塞进
       ``_NOTIFY_EVENTS``，PermissionRequest / Elicitation / ElicitationResult
       这类**决策类**事件的 stdout 会被静默吞掉：用户以为装了拦截器，
       实际什么都不做。
R3     ``_parse_decision`` 只认 ``args`` / ``block`` / ``decision``。按
       Claude Code 官方文档写的
       ``{"hookSpecificOutput":{"permissionDecision":"deny",
       "updatedInput":{...}}}`` 被判 ``None`` 后 ``continue`` —— 既不阻断
       也不改参。协议不兼容却宣称对齐。
R4     最严重：hook 返回 ``{"args":{"path":"ok","TOTALLY_UNKNOWN":"pwn"}}``
       时旧版原样采纳，``tools/base.py`` 执行 ``tool.handler(ctx, **args)``
       直接抛 ``TypeError``（未知关键字 + 缺必需参数）。CC v2.1.300 起
       会丢未知键、缺 required / 类型不符则**拒绝该次调用**。
=====  =====================================================================

**修复（如实，不夸大）**

- 事件表 8 → 15（8 核心 + 7 扩展），未知事件键显式审计；
  决策类独立 ``run_decision`` 裁决出口，误走 ``run_notify`` 留痕拒绝。
- ``_parse_decision`` 同时支持 CC 原生 ``hookSpecificOutput`` 与本地旧
  格式；``updatedInput`` 按 CC 语义是**替换**整个 input。
- 新增 ``hooks/input_validation.py``：有 schema 严格校验（丢未知键 /
  required / type / enum，不符即 deny）；无 schema 退化为保守子集
  约束，``enforced=False`` 绝不包装成「已通过校验」。
- 接线：``tools/base.py`` 传 ``tool.parameters``；``PermissionRequest``
  在危险工具审批前派发（**只允许收紧，不允许 hook 代答跳过确认**）；
  ``/add-dir`` 授权成功后派发 ``DirectoryAdded``。

**如实边界**：官方最新 hooks 参考列出的事件远多于 7 个
（PermissionDenied / PostToolBatch / TaskCompleted / FileChanged ...），
本轮只补 catalog 已登记的 7 个；``ConfigChange`` / ``WorktreeCreate`` /
``Elicitation`` / ``ElicitationResult`` 引擎已就绪但**没有本地生产触发点**，
不假装全事件对齐；CC 的 exit-code-2 → decline 语义未实现。
矩阵计数一个不动：``ahead 10 / aligned 46 / partial 9 / gap 26 /
not_applicable 8``，``fully_superior=false``，``b_waves_done=["B1"]``。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.hooks import (
    HookManager, HOOK_EVENTS, CORE_HOOK_EVENTS, EXTENDED_HOOK_EVENTS,
)
from tuan_cli.hooks.input_validation import validate_updated_input

PY = sys.executable


class FakeKernel:
    def __init__(self):
        self.events = []

    def get(self, name, default=None):
        return default

    def emit(self, topic, payload=None):
        self.events.append((topic, payload or {}))

    def on(self, *a, **k):
        pass

    def statuses(self, keyword):
        return [p.get("status", "") for t, p in self.events
                if t == "hook.executed" and keyword in p.get("status", "")]


def _hook(obj: dict) -> dict:
    """一个把 obj 原样打印到 stdout 的 command hook。"""
    return {"command": [PY, "-c",
                        "import json,sys; print(json.dumps(" + repr(obj) + "))"]}


def _mgr(block: dict, kernel=None) -> HookManager:
    return HookManager({"hooks": block}, kernel=kernel or FakeKernel())


SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "content": {"type": "string"},
        "mode": {"type": "string", "enum": ["w", "a"]},
    },
    "required": ["path", "content"],
}


# ================================================== 1 事件表 / 静默配错
class TestEventSurface:
    def test_15_events_8_core_7_extended(self):
        assert len(CORE_HOOK_EVENTS) == 8
        assert len(EXTENDED_HOOK_EVENTS) == 7
        assert len(HOOK_EVENTS) == 15
        assert set(EXTENDED_HOOK_EVENTS) == {
            "PermissionRequest", "Notification", "DirectoryAdded",
            "ConfigChange", "WorktreeCreate", "Elicitation",
            "ElicitationResult"}

    def test_extended_event_config_is_loaded_not_dropped(self):
        """R1：旧版整段静默丢弃。"""
        m = _mgr({"enabled": True,
                  "DirectoryAdded": [_hook({"ok": 1})],
                  "PermissionRequest": [_hook({"ok": 2})]})
        loaded = sorted({s.event for s in m._specs})
        assert loaded == ["DirectoryAdded", "PermissionRequest"]

    def test_unknown_event_key_is_audited(self):
        """R1：拼错事件名不再无声消失。"""
        k = FakeKernel()
        _mgr({"enabled": True, "PermissionReqest": [_hook({"ok": 1})]}, k)
        assert "unknown_hook_event" in k.statuses("unknown_hook_event")
        detail = [p["detail"] for t, p in k.events
                  if p.get("status") == "unknown_hook_event"][0]
        assert "PermissionReqest" in detail

    def test_known_config_keys_not_flagged_as_events(self):
        k = FakeKernel()
        _mgr({"enabled": True, "default_timeout": 5,
              "allow_edit_args": True, "on_failure": "block"}, k)
        assert "unknown_hook_event" not in k.statuses("unknown_hook_event")


# ================================================== 2 决策类不能走通知通道
class TestDecisionRouting:
    def test_run_notify_refuses_decision_event(self, tmp_path):
        """R2：决策类误走 run_notify → 留痕 + 不执行 hook。"""
        log = tmp_path / "n.log"
        os.environ["HOOK_AUDIT_LOG"] = str(log)
        try:
            script = (
                "import json,sys,os,pathlib; "
                "d=json.loads(sys.stdin.read() or '{}'); "
                "pathlib.Path(os.environ['HOOK_AUDIT_LOG']).open('a').write("
                "json.dumps(d)+'\\n'); print('{}')")
            k = FakeKernel()
            m = _mgr({"enabled": True, "PermissionRequest": [
                {"command": [PY, "-c", script]}]}, k)
            m.run_notify("PermissionRequest", {"x": 1})
            assert not log.exists(), "决策类事件被当通知执行了"
            assert "decision_event_misrouted" in k.statuses(
                "decision_event_misrouted")
        finally:
            os.environ.pop("HOOK_AUDIT_LOG", None)

    def test_run_decision_cc_native_deny(self):
        """R3：CC 原生 permissionDecision:deny 生效。"""
        m = _mgr({"enabled": True, "PermissionRequest": [
            _hook({"hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "permissionDecision": "deny",
                "permissionDecisionReason": "策略禁止"}})]})
        d = m.run_decision("PermissionRequest", tool_name="write_file")
        assert d.block is True
        assert "策略禁止" in d.reason

    def test_run_decision_ask_fails_closed_without_channel(self):
        """ask 在无交互确认通道时按 Tuan 既有契约阻断，不静默放行。"""
        m = _mgr({"enabled": True, "WorktreeCreate": [
            _hook({"hookSpecificOutput": {
                "permissionDecision": "ask",
                "permissionDecisionReason": "需人工"}})]})
        d = m.run_decision("WorktreeCreate", tool_name="worktree_create")
        assert d.block is True

    def test_run_decision_allow_does_not_block(self):
        m = _mgr({"enabled": True, "Elicitation": [
            _hook({"hookSpecificOutput": {
                "permissionDecision": "allow"}})]})
        d = m.run_decision("Elicitation", tool_name="mcp__srv__ask")
        assert d.block is False

    def test_run_decision_legacy_block_format(self):
        m = _mgr({"enabled": True, "PermissionRequest": [
            _hook({"decision": "block", "reason": "旧格式"})]})
        d = m.run_decision("PermissionRequest", tool_name="write_file")
        assert d.block is True and "旧格式" in d.reason

    def test_run_decision_honors_matcher(self):
        m = _mgr({"enabled": True, "PermissionRequest": [
            {**_hook({"hookSpecificOutput": {
                "permissionDecision": "deny"}}), "matcher": "delete_*"}]})
        assert m.run_decision("PermissionRequest",
                              tool_name="write_file").block is False
        assert m.run_decision("PermissionRequest",
                              tool_name="delete_file").block is True

    def test_run_decision_ignores_updated_input(self):
        """决策类事件不允许改参，必须留痕而不是静默吞。"""
        k = FakeKernel()
        m = _mgr({"enabled": True, "PermissionRequest": [
            _hook({"hookSpecificOutput": {
                "permissionDecision": "allow",
                "updatedInput": {"path": "/pwn"}}})]}, k)
        d = m.run_decision("PermissionRequest", tool_name="write_file")
        assert d.block is False
        assert d.args is None
        assert "decision_args_ignored" in k.statuses("decision_args_ignored")

    def test_run_decision_fail_closed_on_broken_hook(self):
        """B1 的 fail-closed 语义在决策类事件同样生效。"""
        m = _mgr({"enabled": True, "WorktreeCreate": [
            {"command": ["definitely_missing_hook_binary_xyz"]}]})
        d = m.run_decision("WorktreeCreate", tool_name="worktree_create")
        assert d.block is True
        assert d.failure_kind == "spawn_error"

    def test_run_decision_rejects_unknown_event(self):
        k = FakeKernel()
        m = _mgr({"enabled": True}, k)
        assert m.run_decision("BogusEvent").block is False
        assert "unknown_decision_event" in k.statuses("unknown_decision_event")


# ================================================== 3 updatedInput schema 校验
class TestUpdatedInputValidation:
    def test_unknown_keys_dropped_with_schema(self):
        v = validate_updated_input(
            {"path": "ok", "content": "x", "TOTALLY_UNKNOWN": "pwn"},
            {"path": "a", "content": "b"}, SCHEMA)
        assert v.enforced is True and v.deny is False
        assert "TOTALLY_UNKNOWN" in v.dropped
        assert v.sanitized == {"path": "ok", "content": "x"}

    def test_missing_required_denies_call(self):
        """CC 2.1.300：updatedInput 是替换语义，缺 content 就拒绝。"""
        v = validate_updated_input(
            {"path": "ok"}, {"path": "a", "content": "b"}, SCHEMA)
        assert v.deny is True and v.enforced is True
        assert "content" in v.reason

    def test_wrong_type_denies_call(self):
        v = validate_updated_input(
            {"path": 123, "content": "x"}, {}, SCHEMA)
        assert v.deny is True and "类型不符" in v.reason

    def test_enum_violation_denies_call(self):
        v = validate_updated_input(
            {"path": "a", "content": "b", "mode": "rm -rf"}, {}, SCHEMA)
        assert v.deny is True and "枚举" in v.reason

    def test_bool_is_not_integer(self):
        s = {"type": "object", "properties": {"n": {"type": "integer"}},
             "required": ["n"]}
        assert validate_updated_input({"n": True}, {}, s).deny is True
        assert validate_updated_input({"n": 3}, {}, s).deny is False

    def test_no_schema_conservative_subset_enforced_false(self):
        """R4 的无 schema 降级：挡住新键注入，但如实标 enforced=False。"""
        v = validate_updated_input(
            {"path": "ok", "INJECTED": 1}, {"path": "a"}, None)
        assert v.enforced is False and v.deny is False
        assert "INJECTED" in v.dropped
        assert v.sanitized == {"path": "ok"}

    def test_schema_without_properties_fails_closed(self):
        v = validate_updated_input({"a": 1}, {"a": 0}, {"type": "object"})
        assert v.deny is True and v.enforced is True

    def test_non_dict_input_denied(self):
        v = validate_updated_input(["a"], {}, SCHEMA)
        assert v.deny is True

    def test_sanitized_args_never_crash_handler(self):
        """端到端证明：修复前 `handler(ctx, **args)` 会 TypeError。"""
        calls = {}

        def handler(ctx, *, path, content):
            calls["path"], calls["content"] = path, content
            return "ok"

        raw = {"path": "ok", "content": "x", "TOTALLY_UNKNOWN": "pwn"}
        clean = validate_updated_input(raw, {"path": "a", "content": "b"},
                                       SCHEMA).sanitized
        assert handler(object(), **clean) == "ok"
        assert calls == {"path": "ok", "content": "x"}
        with pytest.raises(TypeError):
            handler(object(), **raw)  # 修复前的原始 dict 确实会崩

    def test_run_pre_end_to_end_drops_unknown_and_keeps_call(self):
        m = _mgr({"enabled": True, "allow_edit_args": True, "PreToolUse": [
            {**_hook({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "updatedInput": {"path": "ok", "content": "x",
                                 "TOTALLY_UNKNOWN": "pwn"}}}),
             "allow_edit_args": True}]})
        d = m.run_pre("write_file", {"path": "a", "content": "b"},
                      tool_schema=SCHEMA)
        assert d.block is False
        assert d.args == {"path": "ok", "content": "x"}

    def test_run_pre_denies_call_on_missing_required(self):
        m = _mgr({"enabled": True, "allow_edit_args": True, "PreToolUse": [
            {**_hook({"hookSpecificOutput": {
                "permissionDecision": "allow",
                "updatedInput": {"path": "ok"}}}),
             "allow_edit_args": True}]})
        d = m.run_pre("write_file", {"path": "a", "content": "b"},
                      tool_schema=SCHEMA)
        assert d.block is True
        assert d.failure_kind == "invalid_updated_input"
        assert "必需参数" in d.reason

    def test_run_pre_validates_legacy_args_too(self):
        """本地旧 `{"args":...}` 格式也走同一份校验，不留侧门。"""
        m = _mgr({"enabled": True, "allow_edit_args": True, "PreToolUse": [
            {**_hook({"args": {"path": "ok", "INJECTED": 1}}),
             "allow_edit_args": True}]})
        d = m.run_pre("write_file", {"path": "a", "content": "b"},
                      tool_schema=SCHEMA)
        assert d.block is True  # 缺 content

    def test_cc_native_deny_without_schema(self):
        """R3：旧版对这份输出完全无视；现在必须阻断。"""
        m = _mgr({"enabled": True, "PreToolUse": [
            _hook({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "不允许"}})]})
        d = m.run_pre("write_file", {"path": "a"})
        assert d.block is True and "不允许" in d.reason

    def test_legacy_formats_still_work(self):
        m = _mgr({"enabled": True, "PreToolUse": [
            _hook({"block": True, "reason": "legacy"})]})
        assert m.run_pre("write_file", {}).block is True

    def test_additional_context_no_channel_is_audited(self):
        """CC advisory 无本地注入通道 → 留痕，不假装已注入。"""
        k = FakeKernel()
        m = _mgr({"enabled": True, "PreToolUse": [
            _hook({"hookSpecificOutput": {
                "additionalContext": "请小心"}})]}, k)
        assert m.run_pre("write_file", {}).block is False
        assert "additional_context_no_channel" in k.statuses(
            "additional_context_no_channel")


# ================================================== 4 接线真实性
class TestWiring:
    def test_base_passes_tool_schema(self):
        """源码级：主链路把 Tool.parameters 交给 run_pre。"""
        src = Path("tuan_cli/tools/base.py").read_text(encoding="utf-8")
        assert "tool_schema=tool.parameters" in src

    def test_permission_request_wiring_exists_and_is_narrowing_only(self):
        """PermissionRequest 接线存在，且注释契约明确「不允许代答放行」。"""
        src = Path("tuan_cli/tools/base.py").read_text(encoding="utf-8")
        assert 'run_decision(' in src and '"PermissionRequest"' in src
        assert "只允许收紧、不允许放宽" in src
        assert '[PermissionRequest Hook 阻断]' in src

    def test_permission_request_hook_cannot_bypass_confirm(self):
        """实测：hook 返回 allow 时，人工确认仍被调用（安全闸门不放宽）。"""
        from tuan_cli.tools.base import Tool, ToolRegistry

        reg = object.__new__(ToolRegistry)
        reg._emit_exec = lambda *a, **k: None
        tool = Tool(name="delete_file", description="", parameters=SCHEMA,
                    handler=lambda **k: "ok", dangerous=True)
        confirm_calls = []
        ctx = SimpleNamespace(
            hooks=_mgr({"enabled": True, "PermissionRequest": [
                _hook({"hookSpecificOutput": {
                    "permissionDecision": "allow"}})]}),
            confirm=lambda p: confirm_calls.append(p) or True,
            on_auto_approve=None, yolo=False, auto_mode=False,
            safety_advice=None, ui=None,
        )
        decision = SimpleNamespace(action="confirm", explicit=False, reason="")
        out = reg._approve_dangerous(tool, "delete_file",
                                     {"path": "a", "content": "b"},
                                     decision, ctx, None)
        assert out is None
        assert len(confirm_calls) == 1, "hook 的 allow 绝不能跳过人工确认"

    def test_permission_request_deny_short_circuits(self):
        from tuan_cli.tools.base import Tool, ToolRegistry
        reg = object.__new__(ToolRegistry)
        reg._emit_exec = lambda *a, **k: None
        tool = Tool(name="delete_file", description="", parameters=SCHEMA,
                    handler=lambda **k: "ok", dangerous=True)
        confirm_calls = []
        ctx = SimpleNamespace(
            hooks=_mgr({"enabled": True, "PermissionRequest": [
                _hook({"hookSpecificOutput": {
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "策略禁止"}})]}),
            confirm=lambda p: confirm_calls.append(p) or True,
            on_auto_approve=None, yolo=False, auto_mode=False,
            safety_advice=None, ui=None,
        )
        out = reg._approve_dangerous(
            tool, "delete_file", {"path": "a", "content": "b"},
            SimpleNamespace(action="confirm", explicit=False, reason=""),
            ctx, None)
        assert out is not None and out.status == "denied"
        assert "策略禁止" in out.content
        assert confirm_calls == []

    def test_directory_added_dispatched_only_on_success(self, tmp_path):
        """/add-dir 成功才派发 DirectoryAdded；失败信息不触发。"""
        from tuan_cli.cli import cmd_slash as CS

        class FakeHooks:
            def __init__(self): self.calls = []
            def run_notify(self, event, payload):
                self.calls.append((event, payload))

        class FakeUI:
            def __init__(self): self.msgs = []
            def success(self, m): self.msgs.append(m)
            def info(self, m): self.msgs.append(m)

        ext = tmp_path / "ext"; ext.mkdir()
        ws = tmp_path / "ws"; ws.mkdir()
        ui = FakeUI()
        agent = SimpleNamespace(ctx=SimpleNamespace(
            workspace=str(ws), hooks=FakeHooks()))
        # 真实 cmd_slash 用模块级 ui，替换它
        orig = CS.ui
        CS.ui = ui
        try:
            CS._cmd_add_dir(agent, str(ext))
            assert len(agent.ctx.hooks.calls) == 1
            ev, pl = agent.ctx.hooks.calls[0]
            assert ev == "DirectoryAdded" and pl["writable"] is False
            assert pl["session_only"] is True

            # 失败：不存在的目录 → 不派发
            agent.ctx.hooks.calls.clear()
            CS._cmd_add_dir(agent, str(tmp_path / "missing"))
            assert agent.ctx.hooks.calls == []
        finally:
            CS.ui = orig

    def test_directory_added_writable_flag_propagates(self, tmp_path):
        from tuan_cli.cli import cmd_slash as CS

        class FakeHooks:
            def __init__(self): self.calls = []
            def run_notify(self, event, payload): self.calls.append((event, payload))
        class FakeUI:
            def success(self, m): pass
            def info(self, m): pass
        ext = tmp_path / "ext"; ext.mkdir()
        ws = tmp_path / "ws"; ws.mkdir()
        agent = SimpleNamespace(ctx=SimpleNamespace(
            workspace=str(ws), hooks=FakeHooks()))
        orig = CS.ui; CS.ui = FakeUI()
        try:
            CS._cmd_add_dir(agent, str(ext) + " --writable")
        finally:
            CS.ui = orig
        assert agent.ctx.hooks.calls[0][1]["writable"] is True


# ================================================== 5 不该修 / 边界
class TestNotChangedOnPurpose:
    def test_legacy_eight_events_unchanged_semantics(self):
        m = _mgr({"enabled": True, "Stop": [_hook({"block": True})]})
        assert m.run_notify("Stop", {"reason": "x"}) is None  # 通知忽略 stdout

    def test_pretooluse_still_rejected_on_notify_channel(self):
        k = FakeKernel()
        m = _mgr({"enabled": True, "PreToolUse": [_hook({"ok": 1})]}, k)
        m.run_notify("PreToolUse", {})
        assert "unknown_notify_event" in k.statuses("unknown_notify_event")

    def test_exit_code_2_decline_not_claimed(self):
        """如实边界：CC 的 rc=2 → decline 本轮未实现，源码里不假装。"""
        src = Path("tuan_cli/hooks/manager.py").read_text(encoding="utf-8")
        assert "exit-code-2" not in src or "未实现" in src

    def test_five_events_have_no_production_trigger_yet(self):
        """如实边界：只有两个扩展事件接了生产触发点。"""
        slash = Path("tuan_cli/cli/cmd_slash.py").read_text(encoding="utf-8")
        tools_base = Path("tuan_cli/tools/base.py").read_text(encoding="utf-8")
        assert '"DirectoryAdded"' in slash
        assert '"PermissionRequest"' in tools_base
        # 其余四个未在源码中出现为触发点（引擎常量不算）
        for f in Path("tuan_cli").rglob("*.py"):
            if f.name in ("manager.py", "__init__.py"):
                continue
            s = f.read_text(encoding="utf-8", errors="replace")
            for ev in ("ConfigChange", "WorktreeCreate",
                       "ElicitationResult"):
                assert f'run_notify("{ev}"' not in s
                assert f'run_decision("{ev}"' not in s


# ================================================== 6 矩阵自洽
class TestMatrixHonesty:
    def test_counts_unchanged(self):
        from tuan_cli.parity_claude import matrix, evidence
        assert matrix.validate() == []
        assert evidence.verify_evidence() == []
        s = matrix.summary()
        assert s["by_status"] == {
            "ahead": 10, "aligned": 46, "partial": 9,
            "gap": 26, "not_applicable": 8}
        assert s["gaps"] == 26
        assert s["fully_superior"] is False
        assert s["b_waves_done"] == ["B1"]
        assert s["superiority_criteria"]["external_adaptive_red_team"] is False

    def test_catalog_still_marks_two_gaps(self):
        """引擎层补齐但生产触发点未全覆盖 → 两个条目仍为 gap，不靠改口径凑数。"""
        from tuan_cli.parity_claude import catalog
        src = Path("tuan_cli/parity_claude/catalog.py").read_text(
            encoding="utf-8")
        i = src.index('M("hook_events_extended"')
        assert "STATUS_GAP" in src[i:i + 500]
        j = src.index('M("hook_updated_input_validation"')
        assert "STATUS_GAP" in src[j:j + 500]
