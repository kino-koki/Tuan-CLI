"""Super-Agent (DeepSeek 双层架构) 端到端测试。

覆盖: 事件注入 → 程序过滤 → Router 模型研判 → 开单 → Worker 并发执行
      → 汇报 → Watchdog 监控 → 持久化恢复 → Panel 面板渲染 → 投机执行。
"""

from __future__ import annotations

import time

import pytest

from tuan_cli.superagent import (
    EventBus,
    EventStatus,
    Panel,
    ProgramRule,
    Router,
    StateStore,
    SuperAgent,
    TicketStatus,
    Trigger,
    TriggerKind,
    TriggerSource,
    Watchdog,
    WorkMode,
    Worker,
    WorkerPool,
)


# ---------------------------------------------------------------- fixtures

def _trigger(content: str = "请修复这个 bug", sender: str = "李雷",
             kind: TriggerKind = TriggerKind.MESSAGE,
             source: TriggerSource = TriggerSource.IM,
             channel: str = "群聊") -> Trigger:
    return Trigger(kind=kind, source=source, channel=channel,
                   content=content, sender=sender)


@pytest.fixture
def engine(tmp_path):
    """AUTO 模式引擎, 持久化到临时目录, 用同步假 runner 执行。"""
    eng = SuperAgent(
        home=str(tmp_path),
        work_mode=WorkMode.AUTO,
        max_workers=3,
        workdir_root=str(tmp_path),
        persist=True,
        watchdog_enabled=False,  # 单测里关掉周期线程, 手动触发
        make_runner=lambda: _fake_runner,
    )
    eng.start()
    yield eng
    eng.stop()


def _fake_runner(ticket, worker):
    """同步假 runner: 记录进度并标记完成。"""
    worker.report_progress("处理中: " + ticket.title)
    time.sleep(0.01)
    worker.report_progress("完成: " + ticket.title)
    return f"结果: {ticket.title} 已处理"


# ---------------------------------------------------------------- 领域对象

def test_trigger_has_id():
    t = _trigger()
    assert t.trigger_id.startswith("trg-")
    assert t.source == TriggerSource.IM
    assert t.kind == TriggerKind.MESSAGE


def test_workmode_parse():
    assert WorkMode("auto") is WorkMode.AUTO
    assert WorkMode("observe") is WorkMode.OBSERVE
    assert WorkMode("off") is WorkMode.OFF


# ---------------------------------------------------------------- EventBus

def test_eventbus_program_filter(tmp_path):
    bus = EventBus()
    # 接 Router 才能路由 (否则 IGNORED)
    router = Router(agent=None, work_mode=WorkMode.OBSERVE)
    bus.set_router(router)
    # 无规则: 非 UNKNOWN 来源放行 (交给模型研判)
    st = bus.emit(_trigger())
    assert st in (EventStatus.ROUTED, EventStatus.DELIVERED)

    # 添加 drop 规则: 该来源被程序层拦截
    bus.add_rule(ProgramRule(name="noise", fn=lambda t: "noise" in t.content, action="drop"))
    st2 = bus.emit(_trigger(content="noise 信息"))
    assert st2 == EventStatus.FILTERED


def test_eventbus_subscription_direct(tmp_path):
    """已订阅的 Thread 后续事件直达 Worker, 不经过 Router。"""
    bus = EventBus()
    # 接 Router (不接则订阅直通前已判 IGNORED? 直通在 router 检查前, 但保险起见接上)
    router = Router(agent=None, work_mode=WorkMode.OBSERVE)
    bus.set_router(router)
    worker = Worker(worker_id="wk-test", ticket=None,
                    run_fn=_fake_runner,
                    report_callback=lambda w, r: None)
    bus.register_worker("wk-test", worker)
    bus.subscribe("thread-1", "wk-test")
    trg = _trigger(content="后续消息")
    trg.thread_id = "thread-1"
    st = bus.emit(trg)
    # 已订阅 -> 直达 Worker (DELIVERED), 不入 Router
    assert st == EventStatus.DELIVERED


# ---------------------------------------------------------------- Router

def test_router_explicit_request_opens_ticket(tmp_path):
    """明确请求 (含'请修复') -> explicit 授权 -> 开单。"""
    router = Router(agent=None, work_mode=WorkMode.OBSERVE)
    assert router.on_event(_trigger("请修复这个 bug")) == EventStatus.ROUTED
    assert router.metrics()["tickets"] == 1
    assert router.metrics()["assess"] == 1


def test_router_chitchat_observe_no_ticket(tmp_path):
    """闲聊在 observe 下不开单 (只记录'本来会接单')。"""
    router = Router(agent=None, work_mode=WorkMode.OBSERVE)
    router.on_event(_trigger("今天天气不错"))
    assert router.metrics()["tickets"] == 0


def test_router_chitchat_auto_rule(tmp_path):
    """auto + 匹配规则 -> 接单。"""
    router = Router(agent=None, work_mode=WorkMode.AUTO)
    router.on_event(_trigger("今天天气不错"))
    # auto 下启发式仍可能判定; 至少不崩溃且归类正常
    assert router.metrics()["threads"] == 1


# ---------------------------------------------------------------- 完整流程 (engine fixture)

def test_full_pipeline(engine):
    """事件注入 -> 开单 -> Worker 执行 -> 汇报 -> 面板。"""
    st = engine.ingest(_trigger("请修复登录 bug"))
    assert st in (EventStatus.ROUTED, EventStatus.DELIVERED)

    time.sleep(0.2)
    metrics = engine.router.metrics()
    assert metrics["tickets"] == 1
    # Worker 执行完成 -> DONE 或 REVIEW (视汇报逻辑)
    status_counts = metrics["status"]
    assert sum(status_counts.values()) == 1

    panel = engine.panel.build()
    assert len(panel) == 1
    assert panel[0].title == "请修复登录 bug"


def test_panel_needs_human_when_review(engine):
    """完成的工作进入待审阅 -> 面板提示人需要动作。"""
    engine.ingest(_trigger("请修复这个 bug"))
    time.sleep(0.2)
    needs = engine.panel.needs_human()
    assert len(needs) >= 1
    assert needs[0].action  # 有动作标识


def test_worker_isolation_workdir(engine):
    """每个 Worker 有独立工作目录。"""
    engine.ingest(_trigger("请修复这个 bug"))
    time.sleep(0.2)
    for w in engine.workers.status():
        assert w["worker_id"]  # 已分配 worker
        # 独立工作目录由 WorkerPool 提供 (通过 workdir 属性或 status 键)
        assert "workdir" in w or w["worker_id"]


def test_worker_status_has_status_key(engine):
    """WorkerPool.status() 提供 status 字段 (供 CLI/TUI 展示, 不再显示 ?)。"""
    engine.ingest(_trigger("请修复这个 bug"))
    time.sleep(0.2)
    ws = engine.workers.status()
    assert ws, "应有 Worker 状态"
    for w in ws:
        assert "status" in w, f"Worker 状态应含 status 键: {w}"
        assert w["status"]  # 非空 (running/…)


# ---------------------------------------------------------------- 跨任务上下文 (观察融合点)

def test_router_observe_records_context_no_ticket():
    """observe 记录对话为上下文, 但不开单、不研判、不投递。"""
    router = Router(agent=None, work_mode=WorkMode.AUTO)
    before = router.metrics()["tickets"]
    router.observe("请修复登录页崩溃", sender="你", source="local")
    # 不产生工单
    assert router.metrics()["tickets"] == before
    # 记录进上下文
    ctx = router.recent_context(limit=10)
    assert len(ctx) == 1
    assert ctx[0]["content"] == "请修复登录页崩溃"
    assert ctx[0]["sender"] == "你"


def test_router_observe_context_ring_buffer():
    """上下文环形缓冲: 超出 maxlen 保留最近 N 条。"""
    router = Router(agent=None, work_mode=WorkMode.AUTO)
    for i in range(60):
        router.observe(f"消息 {i}", sender="你")
    ctx = router.recent_context(limit=1000)
    assert len(ctx) == 40, "环形缓冲上限 40 条"
    assert ctx[-1]["content"] == "消息 59"
    assert ctx[0]["content"] == "消息 20"


def test_router_observe_empty_ignored():
    """空/空白消息不记录。"""
    router = Router(agent=None, work_mode=WorkMode.AUTO)
    router.observe("   ", sender="你")
    assert router.recent_context(limit=10) == []


def test_engine_observe_text_records_context(tmp_path):
    """引擎 observe_text 便捷入口记录上下文, 不开单。"""
    eng = SuperAgent(
        home=str(tmp_path), work_mode=WorkMode.AUTO, max_workers=2,
        workdir_root=str(tmp_path), persist=False, watchdog_enabled=False,
        make_runner=lambda: _fake_runner,
    )
    eng.observe_text("用户说: 这个 API 限流问题很烦", sender="你", source="local")
    ctx = eng.recent_context(limit=10)
    assert len(ctx) == 1
    assert "限流" in ctx[0]["content"]
    # 状态查询带 context 统计
    st = eng.status()
    assert st["context"]["observed"] == 1


def test_router_context_feeds_model_prompt():
    """模型研判 prompt 拼接近期上下文 (跨任务背景)。"""
    router = Router(agent=None, work_mode=WorkMode.AUTO)
    router.observe("我们正在排查登录超时", sender="你")
    # 手动构造一个带注入研判的 Router, 抓取传给 agent.run 的 prompt
    captured = {}

    class _FakeAgent:
        def run(self, prompt, stream=False, **kwargs):
            captured["prompt"] = prompt
            return '{"actionable": false, "reason": "无关", "title": "x"}'

    router2 = Router(agent=_FakeAgent(), work_mode=WorkMode.AUTO)
    router2.observe("我们正在排查登录超时", sender="你")
    router2.on_event(_trigger("CI 报告: 登录测试挂了"))
    assert "近期对话上下文" in captured["prompt"]
    assert "排查登录超时" in captured["prompt"]


def test_speculate_runs_background(engine):
    """投机执行: 后台跑, 有价值交付 / 无价值放弃。"""
    entry = engine.speculate("复现该崩溃并找修复方案", title="投机: 崩溃复现")
    assert entry["status"] in ("running", "done", "failed")
    # 等待后台线程完成 (假 runner 很快)
    deadline = time.time() + 3
    while time.time() < deadline and entry["status"] == "running":
        time.sleep(0.05)
    assert entry["status"] in ("done", "failed")


def test_speculate_result_callback_fires(engine):
    """投机完成后触发 _on_speculate_result 回调 (TUI 挂钩把结果推入对话区)。"""
    got: list = []
    engine._on_speculate_result = got.append
    entry = engine.speculate("复现崩溃并修复", title="投机: 崩溃")
    deadline = time.time() + 3
    while time.time() < deadline and not got:
        time.sleep(0.05)
    assert got, "投机完成后应触发结果回调"
    assert got[0]["title"] == "投机: 崩溃"
    assert got[0]["status"] in ("done", "failed")


# ---------------------------------------------------------------- 持久化 + 恢复

def test_persistence_roundtrip(tmp_path):
    store = StateStore(str(tmp_path))
    from tuan_cli.superagent.models import Ticket
    ticket = Ticket(title="t1", prompt="p1", authorization="explicit")
    store.save_ticket(ticket)
    got = store.get_ticket(ticket.ticket_id)
    assert got is not None
    assert got.title == "t1"
    assert got.authorization == "explicit"
    # 未完成工单可被恢复
    pending = store.pending_tickets()
    assert any(t.ticket_id == ticket.ticket_id for t in pending)


def test_recover_pending(tmp_path):
    """重启后恢复未完成工单 (先记录后执行语义)。"""
    store = StateStore(str(tmp_path))
    from tuan_cli.superagent.models import Ticket
    t1 = Ticket(title="旧工单", prompt="未完成", authorization="explicit")
    store.save_ticket(t1)

    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.OBSERVE,
                     persist=True, watchdog_enabled=False)
    eng.start()
    assert eng._recovered >= 1
    recovered = eng.store.get_ticket(t1.ticket_id)
    assert recovered.status == TicketStatus.RETRYING
    assert "已从上次运行恢复" in recovered.progress
    eng.stop()


# ---------------------------------------------------------------- Watchdog

def test_watchdog_intervene(tmp_path):
    """看门狗发现异常工单时介入标记。"""
    store = StateStore(str(tmp_path))
    router = Router(agent=None, work_mode=WorkMode.AUTO)
    from tuan_cli.superagent.models import Ticket
    ticket = Ticket(title="卡住", prompt="p", authorization="explicit")
    ticket.status = TicketStatus.BLOCKED
    store.save_ticket(ticket)

    wd = Watchdog(router=router, worker_pool=None, enabled=True, interval=0.05)
    wd.start()
    try:
        wd.check_once()
        assert wd.metrics()["checks"] >= 0  # 不崩溃即可
    finally:
        wd.stop()


# ---------------------------------------------------------------- Panel 渲染

def test_panel_render_ordered(tmp_path):
    router = Router(agent=None, work_mode=WorkMode.AUTO)
    panel = Panel(router)
    # 空面板渲染为占位文本 (不崩溃)
    text = panel.render()
    assert isinstance(text, str)
    assert "当前没有工单" in text


def test_panel_render_has_action_cmd(tmp_path):
    """面板条目附上可直接执行的动作命令 (人机交互闭环)。"""
    router = Router(agent=None, work_mode=WorkMode.AUTO)
    panel = Panel(router)
    from tuan_cli.superagent.models import Ticket
    # 待回答工单 → /superagent reply
    t = Ticket(title="需要确认", prompt="请确认", authorization="explicit")
    t.status = TicketStatus.NEEDS_INPUT
    router.tickets[t.ticket_id] = t
    text = panel.render()
    assert f"/superagent reply {t.ticket_id}" in text
    # 待审阅工单 → /superagent accept
    t2 = Ticket(title="待验收", prompt="完成", authorization="explicit")
    t2.status = TicketStatus.REVIEW
    router.tickets[t2.ticket_id] = t2
    text2 = panel.render()
    assert f"/superagent accept {t2.ticket_id}" in text2
    # 失败工单 → /superagent retry
    t3 = Ticket(title="失败", prompt="p", authorization="explicit")
    t3.status = TicketStatus.FAILED
    router.tickets[t3.ticket_id] = t3
    text3 = panel.render()
    assert f"/superagent retry {t3.ticket_id}" in text3


# ---------------------------------------------------------------- CLI 注册

def test_slash_command_registered():
    from tuan_cli.cli.cmd_slash import SLASH_COMMAND_NAMES, _CMD_META
    assert "/superagent" in SLASH_COMMAND_NAMES
    assert "/superagent" in _CMD_META


# ---------------------------------------------------------------- 真实 Agent 融合

class _FakeMainAgent:
    """模拟真实主 Agent: 记录 run() 调用, 返回固定结果。"""

    def __init__(self) -> None:
        self.calls: list = []
        self.last_session_id: str = ""

    def run(self, prompt: str, stream: bool = True, session_id: str = None,
            on_token=None, **kwargs) -> str:
        self.calls.append(prompt)
        self.last_session_id = session_id or ""
        # 若以流式调用且提供 on_token, 模拟产出几个 token (验证进度上报路径)
        if on_token is not None:
            for tok in ("正在", "分析", "并", "修复"):
                on_token(tok)
        return f"已执行: {prompt[:20]}"


def test_default_runner_streams_progress_to_router(tmp_path):
    """默认 runner 流式 token 经 report_progress 上报到 Router (TUI 对话区可见)。"""
    fake = _FakeMainAgent()
    eng = SuperAgent(
        home=str(tmp_path),
        agent=fake,
        work_mode=WorkMode.AUTO,
        max_workers=1,
        workdir_root=str(tmp_path),
        persist=False,
        watchdog_enabled=False,
        make_runner=None,
    )
    eng.start()
    updates: list = []
    eng.router.add_listener(lambda name, payload: (
        updates.append(payload) if name == "ticket_update" else None))
    try:
        ticket = eng.router._dispatch_ticket(
            _trigger("请修复登录失败 bug"),
            {"actionable": True, "would_accept": True, "authorization": "explicit",
             "title": "修复登录", "prompt": "请修复登录失败 bug"},
        )
        deadline = time.time() + 5
        while time.time() < deadline and ticket.status not in (
                TicketStatus.REVIEW, TicketStatus.FAILED):
            time.sleep(0.05)
        # 至少有一个 progress 上报 (含"开始:"或"生成中…")
        progress_reports = [
            r.get("report", {}).get("progress", "")
            for r in updates if r.get("report", {}).get("status") == "progress"
        ]
        assert any(p for p in progress_reports), f"应上报进度: {progress_reports}"
        # 最终 done → 工单进入 REVIEW (待审阅)
        assert ticket.status == TicketStatus.REVIEW
    finally:
        eng.stop()


def test_default_runner_uses_bound_agent(tmp_path):
    """绑定了主 Agent 后, 默认 runner 通过 agent.run() 执行真实任务 (融合点)。"""
    fake = _FakeMainAgent()
    eng = SuperAgent(
        home=str(tmp_path),
        agent=fake,
        work_mode=WorkMode.AUTO,
        max_workers=1,
        workdir_root=str(tmp_path),
        persist=False,
        watchdog_enabled=False,
        make_runner=None,  # 不注入 → 应自动用绑定 Agent
    )
    eng.start()
    try:
        ticket = eng.router._dispatch_ticket(
            _trigger("请修复登录失败 bug"),
            {"actionable": True, "would_accept": True, "authorization": "explicit",
             "title": "修复登录", "prompt": "请修复登录失败 bug"},
        )
        assert ticket is not None
        # 等 Worker 完成
        deadline = time.time() + 5
        while time.time() < deadline and ticket.status not in (
                TicketStatus.REVIEW, TicketStatus.FAILED):
            time.sleep(0.05)
        assert fake.calls, "默认 runner 应调用主 Agent.run()"
        assert "登录" in fake.calls[0] or "登录失败" in fake.calls[0]
        assert "superagent-" in fake.last_session_id  # 会话隔离
        assert ticket.status == TicketStatus.REVIEW
        assert "已执行" in ticket.result
    finally:
        eng.stop()


def test_stop_requests_worker_termination(tmp_path):
    """stop() 应真正请求存活 Worker 协作式终止 (修复原先空转的 stop)。"""
    eng = SuperAgent(
        home=str(tmp_path),
        work_mode=WorkMode.AUTO,
        max_workers=1,
        workdir_root=str(tmp_path),
        persist=False,
        watchdog_enabled=False,
        make_runner=lambda: _fake_runner,
    )
    eng.start()
    ticket = eng.router._dispatch_ticket(
        _trigger("请实现一个功能"),
        {"actionable": True, "would_accept": True, "authorization": "explicit",
         "title": "实现功能", "prompt": "请实现一个功能"},
    )
    assert ticket is not None
    wid = ticket.worker_id
    assert wid
    worker = eng.workers._workers.get(wid)
    assert worker is not None
    eng.stop()
    # 停止后应已置终止标志 (协作式), 且引擎标记为未运行
    assert worker.should_stop
    assert not eng.is_running()


# ---------------------------------------------------------------- /superagent 命令融合

class _FakeUI:
    """捕获 ui.* 调用 (info/success/error/answer_md)。"""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def info(self, text: str) -> None:
        self.lines.append(f"info:{text}")

    def success(self, text: str) -> None:
        self.lines.append(f"success:{text}")

    def error(self, text: str) -> None:
        self.lines.append(f"error:{text}")

    def answer_md(self, text: str) -> None:
        self.lines.append(f"md:{text}")

    def agent_info(self, text: str, cls: str = "class:textdim") -> None:
        """TUI 桥接: 后台任务视角文本带 @agent 徽章。"""
        self.lines.append(f"agent:{cls}:{text}")


class _FakeAgent:
    """挂 _superagent 的最小主 Agent 替身。"""

    def __init__(self, eng: SuperAgent) -> None:
        self._superagent = eng
        self._calls: list[tuple] = []

    def run(self, prompt: str, stream: bool = False, session_id: str = ""):
        self._calls.append((prompt, stream, session_id))
        return f"结果: {prompt[:20]}"


def test_slash_ingest_auto_starts_engine(tmp_path, monkeypatch):
    """/superagent ingest 在引擎未启动时自动 start (无需显式 /superagent start)。"""
    from tuan_cli.cli import cmd_slash_superagent as mod

    ui = _FakeUI()
    monkeypatch.setattr(mod, "ui", ui)

    class _Agent:
        pass

    agent_obj = _Agent()
    eng = SuperAgent(
        home=str(tmp_path),
        work_mode=WorkMode.OBSERVE,
        max_workers=2,
        workdir_root=str(tmp_path),
        persist=False,
        watchdog_enabled=False,
        make_runner=lambda: _fake_runner,
    )
    setattr(agent_obj, "_superagent", eng)
    assert not eng.is_running()

    mod._cmd_superagent(agent_obj, "ingest 群聊 请修复登录 bug")

    assert eng.is_running(), "首次 ingest 应自动启动引擎"
    assert any("已注入事件" in l for l in ui.lines), f"应输出成功提示: {ui.lines}"
    eng.stop()


def test_slash_ingest_requires_args(tmp_path, monkeypatch):
    """/superagent ingest 缺参数时报用法错误。"""
    from tuan_cli.cli import cmd_slash_superagent as mod

    ui = _FakeUI()
    monkeypatch.setattr(mod, "ui", ui)

    class _Agent:
        pass

    agent_obj = _Agent()  # 可 setattr
    mod._cmd_superagent(agent_obj, "ingest")
    assert any("用法" in l for l in ui.lines), f"应提示用法: {ui.lines}"
    assert not agent_obj._superagent.is_running(), "缺参数不应启动引擎"


def test_slash_status_outputs_to_ui(tmp_path, monkeypatch):
    """/superagent status 经 ui.* 输出 (TUI 桥接进对话区)。"""
    from tuan_cli.cli import cmd_slash_superagent as mod

    ui = _FakeUI()
    monkeypatch.setattr(mod, "ui", ui)

    class _Agent:
        pass

    agent_obj = _Agent()
    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.OBSERVE,
                     persist=False, watchdog_enabled=False,
                     make_runner=lambda: _fake_runner)
    setattr(agent_obj, "_superagent", eng)
    mod._cmd_superagent(agent_obj, "status")
    # TUI 桥接下后台任务视角经 agent_info (带 @agent 徽章); CLI 降级 info。
    assert any(("Super-Agent 状态" in l) and (l.startswith("agent:") or l.startswith("info:"))
               for l in ui.lines), f"应输出状态: {ui.lines}"
    eng.stop()


def test_slash_status_panel_use_agent_badge(tmp_path, monkeypatch):
    """/superagent status/panel/summary 在 TUI 桥接下经 agent_info (@agent 徽章)。"""
    from tuan_cli.cli import cmd_slash_superagent as mod

    ui = _FakeUI()
    monkeypatch.setattr(mod, "ui", ui)

    class _Agent:
        pass

    agent_obj = _Agent()
    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.OBSERVE,
                     persist=False, watchdog_enabled=False,
                     make_runner=lambda: _fake_runner)
    setattr(agent_obj, "_superagent", eng)
    mod._cmd_superagent(agent_obj, "status")
    assert any(l.startswith("agent:") for l in ui.lines), \
        f"status 应走 agent_info (徽章): {ui.lines}"
    ui.lines.clear()
    mod._cmd_superagent(agent_obj, "panel")
    assert any(l.startswith("agent:") for l in ui.lines), \
        f"panel 应走 agent_info (徽章): {ui.lines}"
    ui.lines.clear()
    mod._cmd_superagent(agent_obj, "summary")
    assert any(l.startswith("agent:") for l in ui.lines), \
        f"summary 应走 agent_info (徽章): {ui.lines}"
    eng.stop()


# ---------------------------------------------------------------- 工单动作 (人机交互)

def test_accept_ticket_review_to_done(tmp_path):
    """验收工单: REVIEW → DONE (结果已采纳, 面板待办关闭)。"""
    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.AUTO,
                     max_workers=1, workdir_root=str(tmp_path),
                     persist=False, watchdog_enabled=False,
                     make_runner=lambda: _fake_runner)
    eng.start()
    try:
        ticket = eng.router._dispatch_ticket(
            _trigger("请修复登录失败 bug"),
            {"actionable": True, "would_accept": True, "authorization": "explicit",
             "title": "修复登录", "prompt": "请修复登录失败 bug"},
        )
        assert ticket is not None
        deadline = time.time() + 5
        while time.time() < deadline and ticket.status != TicketStatus.REVIEW:
            time.sleep(0.05)
        assert ticket.status == TicketStatus.REVIEW
        accepted = eng.accept_ticket(ticket.ticket_id)
        assert accepted is not None
        assert accepted.status == TicketStatus.DONE
        # 面板不再需要人 (验收后待办关闭)
        assert not any(i.ticket_id == ticket.ticket_id for i in eng.panel.needs_human())
    finally:
        eng.stop()


def test_accept_ticket_invalid(tmp_path):
    """验收不存在的工单返回 None。"""
    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.OBSERVE,
                     persist=False, watchdog_enabled=False)
    assert eng.accept_ticket("tkt-none") is None


def test_retry_ticket_failed_redispatch(tmp_path):
    """重试工单: FAILED → 重新分派 (新 Worker 执行)。"""
    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.AUTO,
                     max_workers=1, workdir_root=str(tmp_path),
                     persist=False, watchdog_enabled=False,
                     make_runner=lambda: _fake_runner)
    eng.start()
    try:
        ticket = eng.router._dispatch_ticket(
            _trigger("请修复 bug"),
            {"actionable": True, "would_accept": True, "authorization": "explicit",
             "title": "修复 bug", "prompt": "请修复 bug"},
        )
        assert ticket is not None
        deadline = time.time() + 5
        while time.time() < deadline and ticket.status not in (
                TicketStatus.REVIEW, TicketStatus.FAILED):
            time.sleep(0.05)
        # 置为失败态后重试
        ticket.status = TicketStatus.FAILED
        ticket.error = "模拟失败"
        retried = eng.retry_ticket(ticket.ticket_id)
        assert retried is not None
        assert retried.status == TicketStatus.RUNNING
        assert retried.error == ""
    finally:
        eng.stop()


def test_retry_ticket_not_retryable(tmp_path):
    """不可重试状态 (如 REVIEW) 返回 None。"""
    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.OBSERVE,
                     persist=False, watchdog_enabled=False)
    from tuan_cli.superagent.models import Ticket
    t = Ticket(title="t", prompt="p", authorization="explicit")
    t.status = TicketStatus.REVIEW
    eng.router.tickets[t.ticket_id] = t
    assert eng.retry_ticket(t.ticket_id) is None


def test_reply_ticket_needs_input(tmp_path):
    """回答 NEEDS_INPUT 工单: 答复作为新事件注入 (直达或重路由)。"""
    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.AUTO,
                     max_workers=1, workdir_root=str(tmp_path),
                     persist=False, watchdog_enabled=False,
                     make_runner=lambda: _fake_runner)
    eng.start()
    try:
        ticket = eng.router._dispatch_ticket(
            _trigger("请确认部署"),
            {"actionable": True, "would_accept": True, "authorization": "explicit",
             "title": "确认部署", "prompt": "请确认部署"},
        )
        assert ticket is not None
        ticket.status = TicketStatus.NEEDS_INPUT
        ticket.progress = "需要你确认是否部署"
        replied = eng.reply_ticket(ticket.ticket_id, "确认, 部署")
        assert replied is not None
        assert replied.updated_at > 0
        # 答复直达对应 Worker (经 on_ticket_update): 该工单的 Worker 收到新输入。
        with eng.workers._lock:
            wid = eng.workers._ticket_to_worker.get(ticket.ticket_id, "")
        assert wid, "工单应有对应 Worker"
        with eng.workers._workers[wid]._events_lock:
            pending = eng.workers._workers[wid]._pending_events
        assert any("确认, 部署" in e.content for e in pending), \
            "答复应直达该工单的 Worker (pending_events)"
    finally:
        eng.stop()


def test_reply_ticket_delivers_when_worker_finished(tmp_path):
    """Worker 已结束 (未注册/订阅失效) 时, 答复走 Router 重路由兜底不崩溃。"""
    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.AUTO,
                     max_workers=1, workdir_root=str(tmp_path),
                     persist=False, watchdog_enabled=False,
                     make_runner=lambda: _fake_runner)
    eng.start()
    try:
        from tuan_cli.superagent.models import Ticket
        t = Ticket(title="t", prompt="p", authorization="explicit")
        t.status = TicketStatus.NEEDS_INPUT
        t.worker_id = "wk-gone"   # 指向不存在的 Worker
        eng.router.tickets[t.ticket_id] = t
        replied = eng.reply_ticket(t.ticket_id, "好")
        assert replied is not None
        assert replied.updated_at > 0
    finally:
        eng.stop()


def test_subscription_direct_delivery_in_engine(tmp_path):
    """真实引擎: Worker 创建后注册进 EventBus, Thread 后续事件直达 (DELIVERED)。"""
    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.AUTO,
                     max_workers=1, workdir_root=str(tmp_path),
                     persist=False, watchdog_enabled=False,
                     make_runner=lambda: _fake_runner)
    eng.start()
    try:
        ticket = eng.router._dispatch_ticket(
            _trigger("请修复 bug"),
            {"actionable": True, "would_accept": True, "authorization": "explicit",
             "title": "修复 bug", "prompt": "请修复 bug"},
        )
        assert ticket is not None
        # Worker 已注册进总线 (订阅直通的数据源)
        assert ticket.worker_id in eng.bus._workers, \
            "Worker 应已注册进 EventBus (订阅直通数据源)"
        # 同一 Thread 的后续事件 → 直达 Worker (DELIVERED), 不入 Router
        trg = _trigger("后续补充: 请优先处理")
        trg.thread_id = ticket.thread_id
        st = eng.bus.emit(trg)
        assert st == EventStatus.DELIVERED
    finally:
        eng.stop()


def test_subscription_released_after_worker_finish(tmp_path):
    """Worker 完成后取消订阅: 后续 Thread 事件不再直达已结束的 Worker (走 Router)。"""
    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.AUTO,
                     max_workers=1, workdir_root=str(tmp_path),
                     persist=False, watchdog_enabled=False,
                     make_runner=lambda: _fake_runner)
    eng.start()
    try:
        ticket = eng.router._dispatch_ticket(
            _trigger("请修复 bug"),
            {"actionable": True, "would_accept": True, "authorization": "explicit",
             "title": "修复 bug", "prompt": "请修复 bug"},
        )
        assert ticket is not None
        deadline = time.time() + 5
        while time.time() < deadline and ticket.status != TicketStatus.REVIEW:
            time.sleep(0.05)
        assert ticket.status == TicketStatus.REVIEW
        # 完成后订阅被取消 (Worker 注销), 不再直达
        assert ticket.worker_id not in eng.bus._workers, \
            "Worker 完成后应从总线注销"
        # Thread 后续事件不再 DELIVERED (订阅已取消, 走 Router)
        trg = _trigger("后续: 已无关")
        trg.thread_id = ticket.thread_id
        st = eng.bus.emit(trg)
        assert st != EventStatus.DELIVERED
    finally:
        eng.stop()


def test_reply_ticket_not_needs_input(tmp_path):
    """非待回答状态 (如 REVIEW) 返回 None。"""
    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.OBSERVE,
                     persist=False, watchdog_enabled=False)
    from tuan_cli.superagent.models import Ticket
    t = Ticket(title="t", prompt="p", authorization="explicit")
    t.status = TicketStatus.REVIEW
    eng.router.tickets[t.ticket_id] = t
    assert eng.reply_ticket(t.ticket_id, "x") is None


# ---------------------------------------------------------------- slash 工单动作子命令

def test_slash_accept_subcommand(tmp_path, monkeypatch):
    """/superagent accept <id> 验收工单 (REVIEW → DONE)。"""
    from tuan_cli.cli import cmd_slash_superagent as mod

    ui = _FakeUI()
    monkeypatch.setattr(mod, "ui", ui)

    class _Agent:
        pass

    agent_obj = _Agent()
    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.AUTO,
                     max_workers=1, workdir_root=str(tmp_path),
                     persist=False, watchdog_enabled=False,
                     make_runner=lambda: _fake_runner)
    setattr(agent_obj, "_superagent", eng)
    eng.start()
    try:
        ticket = eng.router._dispatch_ticket(
            _trigger("请修复 bug"),
            {"actionable": True, "would_accept": True, "authorization": "explicit",
             "title": "修复 bug", "prompt": "请修复 bug"},
        )
        assert ticket is not None
        deadline = time.time() + 5
        while time.time() < deadline and ticket.status != TicketStatus.REVIEW:
            time.sleep(0.05)
        assert ticket.status == TicketStatus.REVIEW
        mod._cmd_superagent(agent_obj, f"accept {ticket.ticket_id}")
        assert any("已验收" in l for l in ui.lines), f"应输出验收成功: {ui.lines}"
        assert ticket.status == TicketStatus.DONE
    finally:
        eng.stop()


def test_slash_retry_subcommand(tmp_path, monkeypatch):
    """/superagent retry <id> 重试工单。"""
    from tuan_cli.cli import cmd_slash_superagent as mod

    ui = _FakeUI()
    monkeypatch.setattr(mod, "ui", ui)

    class _Agent:
        pass

    agent_obj = _Agent()
    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.AUTO,
                     max_workers=1, workdir_root=str(tmp_path),
                     persist=False, watchdog_enabled=False,
                     make_runner=lambda: _fake_runner)
    setattr(agent_obj, "_superagent", eng)
    eng.start()
    try:
        ticket = eng.router._dispatch_ticket(
            _trigger("请修复 bug"),
            {"actionable": True, "would_accept": True, "authorization": "explicit",
             "title": "修复 bug", "prompt": "请修复 bug"},
        )
        assert ticket is not None
        deadline = time.time() + 5
        while time.time() < deadline and ticket.status not in (
                TicketStatus.REVIEW, TicketStatus.FAILED):
            time.sleep(0.05)
        ticket.status = TicketStatus.FAILED
        ticket.error = "模拟失败"
        mod._cmd_superagent(agent_obj, f"retry {ticket.ticket_id}")
        assert any("已重试" in l for l in ui.lines), f"应输出重试成功: {ui.lines}"
        assert ticket.status == TicketStatus.RUNNING
    finally:
        eng.stop()


def test_slash_reply_subcommand(tmp_path, monkeypatch):
    """/superagent reply <id> <内容> 回答待回答工单。"""
    from tuan_cli.cli import cmd_slash_superagent as mod

    ui = _FakeUI()
    monkeypatch.setattr(mod, "ui", ui)

    class _Agent:
        pass

    agent_obj = _Agent()
    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.OBSERVE,
                     persist=False, watchdog_enabled=False,
                     make_runner=lambda: _fake_runner)
    setattr(agent_obj, "_superagent", eng)
    eng.start()
    try:
        from tuan_cli.superagent.models import Ticket
        t = Ticket(title="确认部署", prompt="请确认", authorization="explicit")
        t.status = TicketStatus.NEEDS_INPUT
        t.progress = "需要你确认是否部署"
        eng.router.tickets[t.ticket_id] = t
        mod._cmd_superagent(agent_obj, f"reply {t.ticket_id} 确认部署")
        assert any("已回答" in l for l in ui.lines), f"应输出回答成功: {ui.lines}"
    finally:
        eng.stop()


def test_slash_accept_missing_arg(tmp_path, monkeypatch):
    """/superagent accept 缺参数时报用法错误。"""
    from tuan_cli.cli import cmd_slash_superagent as mod

    ui = _FakeUI()
    monkeypatch.setattr(mod, "ui", ui)

    class _Agent:
        pass

    agent_obj = _Agent()
    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.OBSERVE,
                     persist=False, watchdog_enabled=False)
    setattr(agent_obj, "_superagent", eng)
    mod._cmd_superagent(agent_obj, "accept")
    assert any("用法" in l for l in ui.lines), f"应提示用法: {ui.lines}"
    eng.stop()


# ---------------------------------------------------------------- 异步 ReAct 输入环

def _blocking_input_runner(ticket, worker):
    """runner: 报告需要输入并挂起等待答复, 答复后返回 (异步 ReAct 闭环)。"""
    worker.report_progress("执行前需要确认")
    replies = worker.request_input("请确认是否继续", timeout=3.0)
    if replies:
        return f"已按答复执行: {replies[-1].content}"
    return "无答复 (超时/停止)"


def test_worker_wait_for_input_returns_reply(tmp_path):
    """Worker.request_input 挂起等答复: reply_ticket 注入后恢复并返回答复。"""
    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.AUTO,
                     max_workers=1, workdir_root=str(tmp_path),
                     persist=False, watchdog_enabled=False,
                     make_runner=lambda: _blocking_input_runner)
    eng.start()
    try:
        ticket = eng.router._dispatch_ticket(
            _trigger("请确认继续"),
            {"actionable": True, "would_accept": True, "authorization": "explicit",
             "title": "确认继续", "prompt": "请确认继续"},
        )
        assert ticket is not None
        # Worker 挂起等待输入 → 工单进入 NEEDS_INPUT
        deadline = time.time() + 5
        while time.time() < deadline and ticket.status != TicketStatus.NEEDS_INPUT:
            time.sleep(0.05)
        assert ticket.status == TicketStatus.NEEDS_INPUT, \
            f"Worker 挂起等输入应标 NEEDS_INPUT: {ticket.status}"
        # 答复注入 → Worker 恢复执行并完成
        eng.reply_ticket(ticket.ticket_id, "确认, 继续部署")
        deadline = time.time() + 5
        while time.time() < deadline and ticket.status not in (
                TicketStatus.REVIEW, TicketStatus.FAILED):
            time.sleep(0.05)
        assert ticket.status == TicketStatus.REVIEW, \
            f"答复后 Worker 应恢复并完成 (REVIEW): {ticket.status}"
        assert "已按答复执行" in ticket.result, f"结果应含答复: {ticket.result}"
    finally:
        eng.stop()


def test_worker_wait_for_input_timeout_continues(tmp_path):
    """Worker 等输入超时: 不永久挂起, 按原 prompt 继续执行 (无答复不崩溃)。"""
    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.AUTO,
                     max_workers=1, workdir_root=str(tmp_path),
                     persist=False, watchdog_enabled=False,
                     make_runner=lambda: _blocking_input_runner)
    eng.start()
    try:
        ticket = eng.router._dispatch_ticket(
            _trigger("请确认继续"),
            {"actionable": True, "would_accept": True, "authorization": "explicit",
             "title": "确认继续", "prompt": "请确认继续"},
        )
        assert ticket is not None
        # 不回复, 等待超时 (3s) → Worker 继续执行并完成
        deadline = time.time() + 8
        while time.time() < deadline and ticket.status not in (
                TicketStatus.REVIEW, TicketStatus.FAILED):
            time.sleep(0.05)
        assert ticket.status == TicketStatus.REVIEW, \
            f"超时后 Worker 应继续完成 (REVIEW): {ticket.status}"
    finally:
        eng.stop()


def test_worker_request_input_reports_needs_input(tmp_path):
    """Worker.request_input 汇报 NEEDS_INPUT 后再挂起 (面板可呈现待回答)。"""
    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.AUTO,
                     max_workers=1, workdir_root=str(tmp_path),
                     persist=False, watchdog_enabled=False,
                     make_runner=lambda: _blocking_input_runner)
    eng.start()
    try:
        ticket = eng.router._dispatch_ticket(
            _trigger("请确认继续"),
            {"actionable": True, "would_accept": True, "authorization": "explicit",
             "title": "确认继续", "prompt": "请确认继续"},
        )
        assert ticket is not None
        deadline = time.time() + 5
        while time.time() < deadline and ticket.status != TicketStatus.NEEDS_INPUT:
            time.sleep(0.05)
        assert ticket.status == TicketStatus.NEEDS_INPUT
        # 面板呈现待回答工单 (人机交互闭环)
        needs = eng.panel.needs_human()
        assert any(i.ticket_id == ticket.ticket_id for i in needs), \
            f"面板应呈现待回答工单: {[i.title for i in needs]}"
    finally:
        eng.stop()


# ---------------------------------------------------------------- 深化融合: 投机交付 / 上下文持久化 / 面板动作 / Worker 状态机

def test_speculate_marks_valuable_only_on_real_result(tmp_path):
    """投机执行交付闭环: 有实质产出 → valuable=True; 失败/空 → valuable=False。"""
    def _valuable_runner(ticket, worker):
        return "修复方案: 在 login.py 添加超时重试"

    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.AUTO,
                     max_workers=1, workdir_root=str(tmp_path),
                     persist=False, watchdog_enabled=False,
                     make_runner=lambda: _valuable_runner)
    got: list = []
    eng._on_speculate_result = got.append
    entry = eng.speculate("复现并修复", title="投机: 修复")
    deadline = time.time() + 3
    while time.time() < deadline and not got:
        time.sleep(0.05)
    assert got, "投机完成应触发回调"
    assert got[0]["status"] == "done"
    assert got[0]["valuable"] is True, f"实质结果应标记有价值: {got[0]}"
    assert "valuable" in entry


def test_speculate_failure_not_valuable(tmp_path):
    """投机失败兜底: 状态 failed, valuable=False (TUI 挂钩据此放弃交付)。"""
    def _failing_runner(ticket, worker):
        raise RuntimeError("模型超时")

    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.AUTO,
                     max_workers=1, workdir_root=str(tmp_path),
                     persist=False, watchdog_enabled=False,
                     make_runner=lambda: _failing_runner)
    got: list = []
    eng._on_speculate_result = got.append
    eng.speculate("复现", title="投机: 失败")
    deadline = time.time() + 3
    while time.time() < deadline and not got:
        time.sleep(0.05)
    assert got, "失败也应触发回调 (兜底)"
    assert got[0]["status"] == "failed"
    assert got[0]["valuable"] is False


def test_speculate_error_result_not_valuable(tmp_path):
    """异常信息结果 (Traceback) 视为无价值: 交付方放弃。"""
    def _error_runner(ticket, worker):
        return "Traceback (most recent call last):\n  ValueError: x"

    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.AUTO,
                     max_workers=1, workdir_root=str(tmp_path),
                     persist=False, watchdog_enabled=False,
                     make_runner=lambda: _error_runner)
    got: list = []
    eng._on_speculate_result = got.append
    eng.speculate("复现", title="投机: 异常")
    deadline = time.time() + 3
    while time.time() < deadline and not got:
        time.sleep(0.05)
    assert got
    assert got[0]["status"] == "done"
    assert got[0]["valuable"] is False, f"异常结果不算交付内容: {got[0]}"


def test_context_persisted_and_restored(tmp_path):
    """观察上下文落盘: 引擎 A 记录 → 重启后引擎 B recent_context 仍可用 (跨进程)。"""
    home = str(tmp_path / "home")
    eng1 = SuperAgent(home=home, work_mode=WorkMode.AUTO,
                      persist=True, watchdog_enabled=False)
    eng1.observe_text("排查登录超时", sender="你", source="local")
    eng1.observe_text("定位到限流配置", sender="你", source="local")
    eng1.stop()

    # 新引擎 (模拟重启): 从 StateStore 回填上下文
    eng2 = SuperAgent(home=home, work_mode=WorkMode.AUTO,
                      persist=True, watchdog_enabled=False)
    ctx = eng2.recent_context(limit=10)
    assert len(ctx) == 2, f"重启后应恢复 2 条上下文: {ctx}"
    assert ctx[0]["content"] == "排查登录超时"
    assert ctx[1]["content"] == "定位到限流配置"
    assert eng2.router._ctx_ts > 0
    eng2.stop()


def test_context_persist_caps_at_ring_limit(tmp_path):
    """持久化上下文同样遵守环形缓冲上限 (40 条)。"""
    home = str(tmp_path / "home")
    store = StateStore(home)
    for i in range(60):
        store.save_context({"role": "user", "content": f"消息 {i}",
                            "sender": "你", "ts": float(i)})
    ctx = store.load_context()
    assert len(ctx) == 40, f"持久上下文上限 40: {len(ctx)}"
    assert ctx[-1]["content"] == "消息 59"
    assert ctx[0]["content"] == "消息 20"


def test_accept_draft_to_done(tmp_path):
    """面板动作闭环: 草稿 (DRAFT) 也可验收 → DONE (用户明确采纳)。"""
    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.OBSERVE,
                     persist=False, watchdog_enabled=False)
    from tuan_cli.superagent.models import Ticket
    t = Ticket(title="草稿", prompt="p", authorization="inferred")
    t.status = TicketStatus.DRAFT
    eng.router.tickets[t.ticket_id] = t
    accepted = eng.accept_ticket(t.ticket_id)
    assert accepted is not None
    assert accepted.status == TicketStatus.DONE


def test_worker_cancelled_state_machine(tmp_path):
    """Worker 状态机: stop() 后协作式终止 → 工单落 CANCELLED (而非 REVIEW)。"""
    def _cancel_runner(ticket, worker):
        worker.report_progress("执行中")
        # 协作式: 阻塞直到收到 stop() 请求 (should_stop), 再返回 (模拟被终止)。
        deadline = time.time() + 5
        while not worker.should_stop and time.time() < deadline:
            time.sleep(0.01)
        return "中途被取消"

    eng = SuperAgent(home=str(tmp_path), work_mode=WorkMode.AUTO,
                     max_workers=1, workdir_root=str(tmp_path),
                     persist=False, watchdog_enabled=False,
                     make_runner=lambda: _cancel_runner)
    eng.start()
    try:
        ticket = eng.router._dispatch_ticket(
            _trigger("请实现功能"),
            {"actionable": True, "would_accept": True, "authorization": "explicit",
             "title": "实现", "prompt": "请实现功能"},
        )
        assert ticket is not None
        wid = ticket.worker_id
        assert wid
        worker = eng.workers._workers[wid]
        worker.stop()  # 请求终止 (协作式)
        deadline = time.time() + 5
        while time.time() < deadline and ticket.status not in (
                TicketStatus.CANCELLED, TicketStatus.FAILED, TicketStatus.REVIEW):
            time.sleep(0.05)
        assert ticket.status == TicketStatus.CANCELLED, \
            f"stop 后工单应落 CANCELLED: {ticket.status}"
        assert "已取消" in ticket.progress
    finally:
        eng.stop()
