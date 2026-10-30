"""LoopRegistry / EventPipeline 专项测试 —— [已弃用] 事件管线 + loop 注册表。

覆盖 tuan_cli.core.loop_registry:
- PipelineStage 数据类
- EventPipeline: register_pre_execute/execute/post_execute/bail_guard/serial/parallel
  execute_waterfall (各阶段执行/deny/异常/bail guard)
  execute_parallel / execute_serial
- LoopRegistry: register/unregister/get/select/list_available/healthcheck/current_name/pipeline
  弃用警告
"""

from __future__ import annotations

import warnings

import pytest

from tuan_cli.core.loop_registry import (
    EventPipeline,
    LoopRegistry,
    PipelineStage,
)


# ---------------------------------------------------------------- PipelineStage

def test_pipeline_stage_defaults():
    def h(x):
        return x
    s = PipelineStage(name="n", handler=h)
    assert s.order == 0
    assert s.enabled is True


# ---------------------------------------------------------------- EventPipeline

def test_register_execute_and_waterfall_ok():
    p = EventPipeline()
    p.register_pre_execute("pre1", lambda ctx: {"extra": 1})
    p.register_execute(lambda ctx: {"result": "done"})
    p.register_post_execute("post1", lambda ctx: {"audit": True})
    res = p.execute_waterfall({"name": "x"})
    assert res["ok"] is True
    assert res["result"] == "done"
    assert res["stages_completed"] == ["pre1", "execute", "post1"]


def test_waterfall_pre_order_by_order_field():
    p = EventPipeline()
    order_calls = []
    p.register_pre_execute("late", lambda ctx: order_calls.append("late"), order=10)
    p.register_pre_execute("early", lambda ctx: order_calls.append("early"), order=0)
    p.register_execute(lambda ctx: {})
    p.execute_waterfall({})
    assert order_calls == ["early", "late"]


def test_waterfall_bail_guard_triggers():
    p = EventPipeline()
    p.register_bail_guard(lambda ctx: True)
    p.register_execute(lambda ctx: {"result": "should_not_run"})
    res = p.execute_waterfall({})
    assert res["ok"] is False
    assert res["error"] == "bail guard triggered"
    assert res["stages_completed"] == []


def test_waterfall_bail_guard_false_passes():
    p = EventPipeline()
    p.register_bail_guard(lambda ctx: False)
    p.register_execute(lambda ctx: {"result": "ok"})
    res = p.execute_waterfall({})
    assert res["ok"] is True


def test_waterfall_pre_deny_stops():
    p = EventPipeline()
    p.register_pre_execute("guard", lambda ctx: {"action": "deny"})
    p.register_execute(lambda ctx: {"result": "should_not_run"})
    res = p.execute_waterfall({})
    assert res["ok"] is False
    assert res["result"] == "denied"
    assert "execute" not in res["stages_completed"]


def test_waterfall_pre_exception_returns_error():
    p = EventPipeline()
    def boom(ctx):
        raise RuntimeError("pre fail")
    p.register_pre_execute("bad", boom)
    res = p.execute_waterfall({})
    assert res["ok"] is False
    assert "pre fail" in res["error"]


def test_waterfall_execute_exception_returns_error():
    p = EventPipeline()
    def boom(ctx):
        raise RuntimeError("exec fail")
    p.register_execute(boom)
    res = p.execute_waterfall({})
    assert res["ok"] is False
    assert "exec fail" in res["error"]


def test_waterfall_post_exception_does_not_block():
    p = EventPipeline()
    p.register_execute(lambda ctx: {"result": "ok"})
    def boom(ctx):
        raise RuntimeError("post fail")
    p.register_post_execute("bad", boom)
    res = p.execute_waterfall({})
    assert res["ok"] is True
    assert res["result"] == "ok"


def test_waterfall_disabled_stage_skipped():
    p = EventPipeline()
    calls = []
    def h(ctx):
        calls.append("x")
        return {}
    p.register_pre_execute("disabled", h)
    p._pre_execute[0].enabled = False
    p.register_execute(lambda ctx: {})
    res = p.execute_waterfall({})
    assert calls == []
    assert "disabled" not in res["stages_completed"]


def test_waterfall_context_carries_result():
    p = EventPipeline()
    p.register_pre_execute("pre", lambda ctx: {"pre_val": 42})
    p.register_execute(lambda ctx: {"result": ctx["pre_val"] * 2})
    res = p.execute_waterfall({})
    assert res["result"] == 84


def test_execute_parallel_returns_sorted_by_index():
    p = EventPipeline()
    def slow():
        import time
        time.sleep(0.02)
        return "slow"
    def fast():
        return "fast"
    results = p.execute_parallel([fast, slow])
    assert results == ["fast", "slow"]


def test_execute_parallel_handles_exceptions():
    p = EventPipeline()
    def boom():
        raise RuntimeError("x")
    results = p.execute_parallel([boom, lambda: "ok"])
    assert results[0] == {"error": "RuntimeError: x"} or results[0]["error"] != ""
    assert results[1] == "ok"


def test_execute_serial_orders_handlers():
    p = EventPipeline()
    calls = []
    p.register_serial_handler(lambda ev: calls.append(("h1", ev["id"])))
    p.register_serial_handler(lambda ev: calls.append(("h2", ev["id"])))
    results = p.execute_serial([{"id": 1}, {"id": 2}])
    assert calls == [("h1", 1), ("h2", 1), ("h1", 2), ("h2", 2)]
    assert len(results) == 4


def test_execute_serial_stops_on_error():
    p = EventPipeline()
    calls = []
    def h2(ev):
        calls.append("h2")
        return "ok"
    def h1(ev):
        calls.append("h1")
        raise RuntimeError("boom")
    p.register_serial_handler(h1)
    p.register_serial_handler(h2)
    results = p.execute_serial([{"id": 1}])
    # h1 抛错 -> 记录 error, break (不调 h2)
    assert calls == ["h1"]
    assert len(results) == 1
    assert "boom" in results[0]["error"]


# ---------------------------------------------------------------- LoopRegistry

class _FakeLoop:
    def __init__(self, name):
        self.description = f"loop {name}"


def _mk_registry() -> LoopRegistry:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return LoopRegistry()


def test_registry_emits_deprecation_warning():
    with pytest.warns(DeprecationWarning):
        LoopRegistry()


def test_register_and_get():
    r = _mk_registry()
    lp = _FakeLoop("react")
    r.register("react", lp)
    assert r.get("react") is lp
    assert r.get("nope") is None


def test_unregister():
    r = _mk_registry()
    lp = _FakeLoop("react")
    r.register("react", lp)
    assert r.unregister("react") is True
    assert r.unregister("react") is False
    assert r.get("react") is None


def test_unregister_clears_current():
    r = _mk_registry()
    r.register("react", _FakeLoop("react"))
    r.select({"loop.provider": "react"})
    assert r.current_name == "react"
    r.unregister("react")
    assert r.current_name == ""


def test_select_explicit_provider():
    r = _mk_registry()
    r.register("react", _FakeLoop("react"))
    r.register("plan_execute", _FakeLoop("pe"))
    lp = r.select({"loop.provider": "plan_execute"})
    assert lp.description == "loop pe"
    assert r.current_name == "plan_execute"


def test_select_plan_execute_mode():
    r = _mk_registry()
    r.register("react", _FakeLoop("react"))
    r.register("plan_execute", _FakeLoop("pe"))
    lp = r.select({"router.plan_execute": True})
    assert lp.description == "loop pe"


def test_select_devloop_mode():
    r = _mk_registry()
    r.register("react", _FakeLoop("react"))
    r.register("devloop", _FakeLoop("dev"))
    lp = r.select({"loop.devloop": True})
    assert lp.description == "loop dev"


def test_select_default_react():
    r = _mk_registry()
    r.register("react", _FakeLoop("react"))
    r.register("other", _FakeLoop("other"))
    lp = r.select({})
    assert lp.description == "loop react"


def test_select_fallback_any():
    r = _mk_registry()
    r.register("only", _FakeLoop("only"))
    lp = r.select(None)
    assert lp.description == "loop only"


def test_select_empty_raises():
    r = _mk_registry()
    with pytest.raises(RuntimeError, match="没有注册任何"):
        r.select(None)


def test_select_config_none():
    r = _mk_registry()
    r.register("react", _FakeLoop("react"))
    lp = r.select(None)
    assert lp.description == "loop react"


def test_list_available():
    r = _mk_registry()
    r.register("react", _FakeLoop("react"))
    r.register("devloop", _FakeLoop("dev"))
    avail = r.list_available()
    assert len(avail) == 2
    assert {"name": "react", "description": "loop react"} in avail


def test_healthcheck():
    r = _mk_registry()
    r.register("react", _FakeLoop("react"))
    hc = r.healthcheck()
    assert hc["total"] == 1
    assert hc["available"] == ["react"]
    assert hc["current"] == ""


def test_pipeline_property():
    r = _mk_registry()
    assert isinstance(r.pipeline, EventPipeline)
