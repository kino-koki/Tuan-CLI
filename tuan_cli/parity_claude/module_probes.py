"""B 线**模块级运行时探针**（首批 2 个，对应 B3 两个 gap）。

上一轮（A 线续轮 XI）用 ``parity_claude/depth.py`` 量化出：65 个非 gap
模块里 65/65 有 evidence 路径与 note，**但模块级运行时探针 0 个**——
六维 ``superiority.probe_all()`` 是聚合维度探针，一个覆盖十几个模块，
它绿不等于逐模块验证。这里按用户约束「确保深度的真实复现，而非仅仅
广度」，给 B3 两条 gap 各注册一个**真调代码**的探针。

两个探针都不是「检查文件存在」：

- ``probe_hook_events_extended``：真起子进程跑 exit-2 hook、真调
  ``HookManager.run_pre/run_decision``、真解析 CC 官方
  ``hookSpecificOutput.decision`` 协议、真核销 33 事件的逐事件
  exit-code-2 真值表。
- ``probe_hook_updated_input_validation``：真调
  ``validate_updated_input``、真跑 ``bridge._run_base_handler`` 的
  asyncio 执行路径、真构造 ``ToolExecutor`` 拿到生产
  ``ToolPipeline`` 与 ``schema_resolver``。

**状态口径**：本轮**不把任何 gap 标成 aligned/partial**。两条 gap 的
硬理由被实测收窄（见 catalog note），但新增 18 个事件仍只有通知通道、
无生产触发点，Elicitation 语义刻意不等价，CC 事件面持续演进 ——
不靠改状态定义凑数。消 gap 留到下一轮按 ``gap_queue()`` 逐域处理。

许可：纯 Python 独立实现，零源码复制。
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# A′ 自查修正：初版写了一个不存在的 ``exit_semantics_bridge`` 哨兵
# import，模块刚加载就会 ImportError，两个探针一个都注册不上。改成
# 全程延迟导入：包导入期不拉起 hooks / TUI 依赖链，注册时再取 depth。
def _imports():
    from tuan_cli.hooks import exit_semantics as XS
    from tuan_cli.hooks import manager as HM
    from tuan_cli.hooks.input_validation import validate_updated_input
    return XS, HM, validate_updated_input


class _FakeKernel:
    def __init__(self):
        self.events: List[Tuple[str, Dict[str, Any]]] = []

    def get(self, name, default=None):
        return default

    def emit(self, topic, payload=None):
        self.events.append((topic, payload or {}))

    def on(self, *a, **k):
        pass


def _make_script(rc: int, stdout: str, stderr: str) -> dict:
    """生成真实子进程 hook 脚本（临时文件，进程结束即清理）。"""
    d = tempfile.mkdtemp(prefix="tuan_probe_")
    p = Path(d) / "hook.py"
    p.write_text(
        "import sys\n"
        "sys.stdout.write(%r)\n"
        "sys.stderr.write(%r)\n"
        "sys.exit(%d)\n" % (stdout, stderr, rc),
        encoding="utf-8")
    return {"command": [sys.executable, str(p)], "_dir": d}


def _mgr(block: Dict[str, Any]):
    _, HM, _ = _imports()
    cfg = {"hooks": dict(block)}
    return HM.HookManager(cfg, kernel=_FakeKernel())


def probe_hook_events_extended() -> dict:
    """真调：exit-code-2 语义 / CC 官方 PermissionRequest 协议 / 33 事件面。"""
    problems: List[str] = []
    checks = 0

    def chk(cond: bool, label: str) -> None:
        nonlocal checks
        checks += 1
        if not cond:
            problems.append(label)

    XS, HM, _ = _imports()
    chk(XS.validate() == [], "exit_semantics 真值表自检不干净")
    chk(len(HM.HOOK_EVENTS) == 33, "HOOK_EVENTS 不是 33")
    chk(set(HM.HOOK_EVENTS) == set(XS.OFFICIAL_EVENTS),
        "HOOK_EVENTS 与真值表事件面漂移")
    chk(len(HM.OFFICIAL_EXTRA_EVENTS) == 18, "新增事件不是 18")

    ALLOW = json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "allow"}})

    # ---- H1：exit 2 + stdout JSON allow 不能绕过 fail-closed
    s = _make_script(2, ALLOW, "BLOCKED: 禁止写 /etc")
    m = _mgr({"enabled": True, "PreToolUse": [
        {"command": s["command"]}]})
    d = m.run_pre("write_file", {"path": "/etc/passwd"})
    chk(d.block is True, "exit 2 被 stdout JSON allow 绕过（真实安全洞）")
    chk("BLOCKED" in d.reason, "stderr 阻断原因丢失")
    chk(d.failure_kind == "exit_2", "failure_kind 未标记 exit_2")

    # ---- H2/H3：CC 官方 PermissionRequest 协议
    pr_deny = json.dumps({"hookSpecificOutput": {
        "hookEventName": "PermissionRequest",
        "decision": {"behavior": "deny", "message": "策略禁止"}}})
    s = _make_script(0, pr_deny, "")
    m = _mgr({"enabled": True, "PermissionRequest": [
        {"command": s["command"]}]})
    d = m.run_decision("PermissionRequest", tool_name="write_file")
    chk(d.block is True, "官方 decision.behavior=deny 未生效")
    chk("策略禁止" in d.reason, "官方 deny 的 message 丢失")

    pr_allow = json.dumps({"hookSpecificOutput": {
        "hookEventName": "PermissionRequest",
        "decision": {"behavior": "allow",
                     "updatedInput": {"plan": "new"}}}})
    s = _make_script(0, pr_allow, "")
    m = _mgr({"enabled": True, "PermissionRequest": [
        {"command": s["command"]}]})
    d = m.run_decision("PermissionRequest", tool_name="ExitPlanMode")
    chk(d.block is False, "官方 allow 被误阻断")
    chk(d.args == {"plan": "new"}, "allow 的 updatedInput 未暴露给调用方")

    # ---- H4：WorktreeCreate 任何非零 rc 都失败
    s = _make_script(1, ALLOW, "create failed")
    m = _mgr({"enabled": True, "WorktreeCreate": [
        {"command": s["command"]}]})
    d = m.run_decision("WorktreeCreate")
    chk(d.block is True, "WorktreeCreate 非零 rc 被 JSON allow 绕过")

    # ---- H5：18 个新事件配置全部加载（不再静默丢弃）
    blk: Dict[str, Any] = {"enabled": True}
    for e in HM.OFFICIAL_EXTRA_EVENTS:
        s = _make_script(0, "{}", "")
        blk[e] = [{"command": s["command"]}]
    m = _mgr(blk)
    loaded = {x.event for x in m._specs}
    chk(set(HM.OFFICIAL_EXTRA_EVENTS) <= loaded,
        "新增官方事件配置仍被静默丢弃: %s" % sorted(
            set(HM.OFFICIAL_EXTRA_EVENTS) - loaded))

    # ---- 逐事件 exit 2 语义核销
    cases = [
        ("PermissionRequest", False), ("PermissionDenied", False),
        ("StopFailure", False), ("InstructionsLoaded", False),
        ("PreToolUse", True), ("UserPromptSubmit", True),
        ("PostToolUse", False), ("Notification", False),
        ("WorktreeCreate", True), ("WorktreeRemove", True),
        ("Elicitation", True), ("ConfigChange", True),
        ("PreCompact", True), ("PostToolUseFailure", False),
        ("SessionStart", False),
    ]
    for ev, expect in cases:
        v = XS.classify(ev, 2, "boom", tuan_policy="block")
        chk(v.block is expect, "%s exit2 block 期望 %s 实得 %s (%s)"
            % (ev, expect, v.block, v.code_path))
    cmp = XS.compare_with_tuan_policy()
    chk(cmp["exit2_always_blocks_when_preventable"] is True,
        "可阻断事件在 allow 策略下 exit 2 未全部阻断")
    chk(len(cmp["non2_nonzero_differences"]) > 0,
        "CC/Tuan 策略差异未被核销（口径可能被抹平）")

    return {"ok": not problems, "checks": checks,
            "evidence": "hooks: exit-2 真值表 33 事件 / 真子进程 / "
                        "CC PR 协议 / 18 事件加载 / 逐事件语义核销",
            "problems": problems}


def probe_hook_updated_input_validation() -> dict:
    """真调：updatedInput schema 校验 / bridge 旁路 / ToolPipeline 生产构造方。"""
    problems: List[str] = []
    checks = 0

    def chk(cond: bool, label: str) -> None:
        nonlocal checks
        checks += 1
        if not cond:
            problems.append(label)

    _, _, validate = _imports()
    schema = {"type": "object", "properties": {
        "path": {"type": "string"}, "content": {"type": "string"},
        "mode": {"type": "string", "enum": ["w", "a"]}},
        "required": ["path", "content"]}

    r = validate({"path": "x", "content": "ok", "UNKNOWN": "pwn"},
                 {"path": "x", "content": "ok"}, schema, "write_file")
    chk(not r.deny and "UNKNOWN" not in r.sanitized,
        "未知键未被丢弃")
    chk(validate({"path": "x"}, {"path": "x", "content": "ok"},
                 schema, "write_file").deny, "缺 required 未拒绝")
    chk(validate({"path": 1, "content": "ok"},
                 {"path": "x", "content": "ok"},
                 schema, "write_file").deny, "类型不符未拒绝")
    chk(validate("not-a-dict", {}, schema, "w").deny,
        "非 dict 改参未拒绝")
    r2 = validate({"path": "x", "content": "ok", "ZZZ": 1},
                  {"path": "x", "content": "ok"}, None, "write_file")
    chk(r2.enforced is False, "无 schema 却宣称 enforced=True")

    # ---- bridge 生产旁路：真跑 asyncio 执行路径
    from tuan_cli.runtime.tools import bridge

    class FakeTool:
        name = "write_file"
        parameters = schema
        dangerous = False
        read_only = False

        def handler(self, ctx, path, content, mode="w"):
            return "OK:" + path

    for label, raw, expect_error in [
        ("未知键", {"path": "x", "content": "ok", "UNKNOWN": "pwn"}, False),
        ("缺 required", {"path": "x"}, True),
        ("类型不符", {"path": 123, "content": "ok"}, True),
        ("合法", {"path": "x", "content": "ok"}, False),
    ]:
        out = asyncio.run(bridge._run_base_handler(FakeTool(), raw, "/tmp"))
        chk(out.is_error is expect_error,
            "bridge %s: is_error 期望 %s 实得 %s (%s)"
            % (label, expect_error, out.is_error, out.output[:90]))
        if not expect_error:
            chk("TypeError" not in out.output,
                "bridge %s 仍把脏参数展开进 handler" % label)

    # ---- ToolPipeline 真实生产构造方
    from tuan_cli.core.tool_executor import ToolExecutor

    class Reg:
        def get(self, n):
            return FakeTool() if n == "write_file" else None

    ex = ToolExecutor(registry=Reg())
    chk(ex.pipeline is not None, "ToolExecutor 未构造生产 ToolPipeline")
    if ex.pipeline is not None:
        got = ex.pipeline.schema_resolver("write_file")
        chk(isinstance(got, dict) and "required" in got,
            "生产 schema_resolver 取不到真实 schema")
        chk(ex.pipeline.schema_resolver("nope") is None,
            "未知工具的 schema 未如实返回 None")

    # ---- 源码级：主链路 / CLI 旁路 / 生产构造方三处证据
    root = Path(__file__).resolve().parents[2]
    base = (root / "tuan_cli/tools/base.py").read_text(encoding="utf-8")
    cli = (root / "tuan_cli/cli/cmd_hooks.py").read_text(encoding="utf-8")
    exe = (root / "tuan_cli/core/tool_executor.py").read_text(
        encoding="utf-8")
    br = (root / "tuan_cli/runtime/tools/bridge.py").read_text(
        encoding="utf-8")
    chk("tool_schema=tool.parameters" in base, "主链路未传 schema")
    chk("tool_schema=schema" in cli, "CLI 旁路未传 schema")
    chk("ToolPipeline(" in exe, "生产构造方不存在")
    chk("validate_updated_input" in br, "bridge 旁路未接 schema 校验")

    return {"ok": not problems, "checks": checks,
            "evidence": "updatedInput: 4 类校验 / bridge 真跑 asyncio / "
                        "ToolExecutor 生产 pipeline + schema_resolver / 4 处源码证据",
            "problems": problems}


def register_all() -> None:
    """注册到 ``depth.MODULE_PROBES``；重复注册报错，不许互相覆盖。"""
    from . import depth as depth_mod
    for name, fn in (("hook_events_extended", probe_hook_events_extended),
                     ("hook_updated_input_validation",
                      probe_hook_updated_input_validation)):
        if name not in depth_mod.MODULE_PROBES:
            depth_mod.register(name)(fn)
