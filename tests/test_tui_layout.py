"""TUI 对话区排版 + 双 ✨ 修复 + /命令 提示 回归测试。"""

from tuan_cli.tui.tui import QxtTUI, USER_MESSAGE_BULLET, USER_MESSAGE_BG


def _tui(**kw):
    kw.setdefault("on_submit", lambda _text: "ok")
    tui = QxtTUI(**kw)
    # 跳过加载屏状态, 直接测对话区渲染
    tui._booting = False
    tui._boot_error = None
    return tui


# ---------------------------------------------------------------- 双 ✨ 修复

def test_msg_to_lines_no_double_bullet():
    """用户消息已带 › 前缀 (事件角色标记) 时, 渲染不再叠加第二个。"""
    tui = _tui()
    # 事件写入时带前缀 (append_log 路径); 不重复叠加, 正文明细只有一个 ›
    lines = tui._msg_to_lines("user", f"{USER_MESSAGE_BULLET}你好")
    first = "".join(seg for _, seg in lines[0])
    assert first.count("›") == 1
    assert first == "› 你好"
    # 纯文本 (防御) 渲染时补一个
    lines2 = tui._msg_to_lines("user", "你好")
    first2 = "".join(seg for _, seg in lines2[0])
    assert first2 == "› 你好"


def test_msg_to_lines_user_block_bg():
    """用户消息块带 Codex 浅灰半透明底, 首行与续行一致。

    结构对齐 codex user_prompt_has_a_background...snap: "› " 前缀是 **dim**
    (messages.rs:266 `"› ".bold().dim()`), 正文带 accent + 浅灰底
    (user_message_element_style 把正文 fg 设成 accent)。快照 x=0 `›` 是
    BOLD|DIM、x=2 正文是 NONE(accent) —— 前缀不是蓝色高亮, 是灰色弱化。
    """
    tui = _tui()
    lines = tui._msg_to_lines("user", f"{USER_MESSAGE_BULLET}第一行\n第二行")
    assert lines[0][0] == ("class:textdim", "› ")  # 前缀: dim, 独立分段
    assert lines[0][1] == (f"class:primary bg:{USER_MESSAGE_BG}", "第一行")  # 正文 accent + 浅灰底
    assert any(f"bg:{USER_MESSAGE_BG}" in cls for cls, _ in lines[1])  # 续行浅灰底延续


# ---------------------------------------------------------------- mode 徽标 (五模式命名)

def test_set_mode_resolves_five_mode_aliases():
    """set_mode 统一解析旧三档别名 → 标准五模式 ID (yolo→boundless 等)。"""
    tui = _tui()
    # 旧三档别名
    tui.set_mode("yolo")
    assert tui._mode == "boundless"
    tui.set_mode("standard")
    assert tui._mode == "collaboration"
    tui.set_mode("plan")
    assert tui._mode == "plan"          # plan 是只读态, 保留独立徽标
    assert tui._plan_mode is True
    # 五模式 ID 直传
    tui.set_mode("boundless")
    assert tui._mode == "boundless"
    assert tui._plan_mode is False
    tui.set_mode("gantong")
    assert tui._mode == "gantong"
    tui.set_mode("chat")
    assert tui._mode == "chat"
    tui.set_mode("lingma")
    assert tui._mode == "lingma"
    tui.set_mode("collaboration")
    assert tui._mode == "collaboration"


def test_mode_badge_labels_and_styles():
    """徽标: 五模式中文名 + 按等级映射颜色; plan 用 magenta。"""
    tui = _tui()
    tui.set_mode("boundless")
    cls, label = tui._mode_badge()
    assert label == "无界"
    assert cls == "class:error"          # L4 → 红 (原 yolo)
    tui.set_mode("gantong")
    cls, label = tui._mode_badge()
    assert label == "感通"
    assert cls == "class:primary"        # L3 → 蓝
    tui.set_mode("lingma")
    cls, label = tui._mode_badge()
    assert label == "灵码"
    assert cls == "class:primary"
    tui.set_mode("collaboration")
    cls, label = tui._mode_badge()
    assert label == "协同"
    assert cls == "class:primary"        # L2 → 蓝
    tui.set_mode("chat")
    cls, label = tui._mode_badge()
    assert label == "闲聊"
    assert cls == "class:textdim"        # L0 → dim
    tui.set_mode("plan")
    cls, label = tui._mode_badge()
    assert label == "plan"
    assert cls == "class:plan"           # plan → magenta (codex footer.rs:164)


def test_mode_badge_unknown_falls_back_safely():
    """未知 mode (modes 不可用/非法) 不得抛给渲染帧, 回退 warning + 原文本。"""
    tui = _tui()
    tui._mode = "some_unknown_mode"
    cls, label = tui._mode_badge()
    assert label == "some_unknown_mode"
    assert cls == "class:warning"


# ---------------------------------------------------------------- 排版分组

def test_scrolled_lines_separates_message_blocks():
    """消息块之间的空行规则 (对标 Claude Code 的紧凑排版)。

    两条规则:
    1. 提问与其回答**之间不留空行** —— 一次问答是一个整体, 空行会把它拆成
       两个视觉区块, 这是"行距偏松"的最大来源;
    2. 其余块间仍留一个空行, 保证多轮对话可读。
    """
    tui = _tui()
    tui.append_log(f"{USER_MESSAGE_BULLET}第一问")
    tui.append_log("第一答")
    tui.append_log(f"{USER_MESSAGE_BULLET}第二问")
    screen = tui._scrolled_lines()

    # 问1→答1 不空行; 答1→问2 留 1 个空行
    blank_rows = sum(1 for line in screen if not line)
    assert blank_rows == 1, "问答之间不应有空行, 仅轮次之间保留一个"

    flat = ["".join(seg for _, seg in line) for line in screen]
    # 提问与紧邻的回答必须物理相邻
    i_q = next(i for i, r in enumerate(flat) if "第一问" in r)
    i_a = next(i for i, r in enumerate(flat) if "第一答" in r)
    assert i_a == i_q + 1, "提问与回答应紧邻, 中间不得有空行"


def test_scrolled_lines_no_double_sparkle_in_full_pipeline():
    """全链路 (append_log -> scrolled) 用户消息只渲染一个 › 前缀。"""
    tui = _tui()
    tui.append_log(f"{USER_MESSAGE_BULLET}你好")
    screen = tui._scrolled_lines()
    flat = "".join(seg for line in screen for _, seg in line)
    assert flat.count("›") == 1
    assert f"{USER_MESSAGE_BULLET}你好" in flat


def test_append_agent_line_renders_roleagent_badge():
    """后台自主任务 (@agent) 徽章用独立青绿, 正文用语义色 (OpenCode 风格)。"""
    tui = _tui()
    tui._append_agent_line("任务完成 · 已产出结果", cls="class:success")
    screen = tui._scrolled_lines()
    flat = "".join(seg for line in screen for _, seg in line)
    assert "@agent" in flat
    assert "任务完成 · 已产出结果" in flat
    # 徽章用 roleagent (青绿), 正文用成功色 —— 两段不同色, 一眼可辨。
    badge_cls = [cls for line in screen for cls, seg in line if "agent" in seg]
    assert any(c == "class:roleagent" for c in badge_cls)
    body_cls = [cls for line in screen for cls, seg in line
                if "任务完成" in seg]
    assert body_cls and body_cls[0] == "class:success"


def test_bind_superagent_forwards_events_to_conversation():
    """TUI↔Super-Agent 融合: _bind_superagent 后, Router 事件经 @agent 徽章进对话区。"""
    tui = _tui()

    class _FakeAgent:
        """可 setattr 的最小主 Agent (承载 _superagent 单例)。"""
        pass

    from tuan_cli.superagent import SuperAgent, WorkMode
    agent = _FakeAgent()
    eng = SuperAgent(home="~/.tuan-test-bind", agent=agent,
                     work_mode=WorkMode.OBSERVE, watchdog_enabled=False)
    setattr(agent, "_superagent", eng)
    tui._agent = agent
    tui._bind_superagent()
    # 触发一次 Router 事件 (开单 → dispatch), 应出现在对话区且带 @agent 徽章。
    from tuan_cli.superagent import Trigger, TriggerKind, TriggerSource
    trg = Trigger(kind=TriggerKind.MESSAGE, source=TriggerSource.IM,
                  channel="群聊", content="请修复这个 bug", sender="李雷")
    eng.router.on_event(trg)
    screen = tui._scrolled_lines()
    flat = "".join(seg for line in screen for _, seg in line)
    assert "@agent" in flat
    assert "后台任务已开单" in flat


def test_bind_superagent_needs_input_shows_reply_cmd():
    """needs_input 事件在对话区呈现「需要你回答」+ 可执行 reply 命令 (人机闭环)。"""
    tui = _tui()

    class _FakeAgent:
        pass

    from tuan_cli.superagent import SuperAgent, WorkMode
    agent = _FakeAgent()
    eng = SuperAgent(home="~/.tuan-test-needs-input", agent=agent,
                     work_mode=WorkMode.OBSERVE, watchdog_enabled=False)
    setattr(agent, "_superagent", eng)
    tui._agent = agent
    tui._bind_superagent()
    # 模拟 Worker 汇报 needs_input → Router 触发 ticket_update 事件。
    from tuan_cli.superagent.models import Ticket, TicketStatus
    t = Ticket(title="确认部署", prompt="请确认", authorization="explicit")
    t.status = TicketStatus.NEEDS_INPUT
    t.worker_id = "wk-test"
    eng.router.tickets[t.ticket_id] = t
    eng.router.on_worker_report("wk-test", {
        "ticket_id": t.ticket_id, "status": "needs_input",
        "progress": "需要你确认是否部署",
    })
    screen = tui._scrolled_lines()
    flat = "".join(seg for line in screen for _, seg in line)
    assert "@agent" in flat
    assert "需要你回答" in flat
    # 行动命令清晰可见: /superagent reply <ticket_id> <内容>
    assert f"/superagent reply {t.ticket_id}" in flat


# ---------------------------------------------------------------- /命令 提示

def test_slash_completer_uses_meta():
    """补全菜单 display_meta 取命令描述表。"""
    from tuan_cli.tui.tui import _SlashCompleter
    from prompt_toolkit.document import Document

    comp = _SlashCompleter(
        ["/help", "/tools"],
        {"/help": "显示帮助", "/tools": "列出可用工具"},
    )
    completions = list(comp.get_completions(Document("/"), None))
    meta = {c.text: str(c.display_meta) for c in completions}
    assert "显示帮助" in meta.get("/help", "")
    assert "列出可用工具" in meta.get("/tools", "")


def test_slash_command_meta_covers_major_commands():
    """命令描述表覆盖常用命令 (补全菜单与 /help 共用)。"""
    from tuan_cli.cli.cmd_slash import slash_command_meta, list_slash_commands

    meta = slash_command_meta()
    names = list_slash_commands()
    for essential in ("/help", "/model", "/effort", "/plan", "/mode", "/clear", "/compact"):
        assert essential in names, f"命令表缺 {essential}"
    for cmd in ("/help", "/model", "/effort", "/plan", "/mode", "/clear", "/compact"):
        assert meta.get(cmd), f"{cmd} 缺描述"


def test_help_text_covers_command_names():
    """/help 输出覆盖全部内置命令 (SLASH_COMMAND_NAMES 与 _HELP 同步)。"""
    from tuan_cli.cli.cmd_slash import _HELP, SLASH_COMMAND_NAMES

    for name in SLASH_COMMAND_NAMES:
        assert name in _HELP, f"/help 未收录 {name}"


# ---------------------------------------------------------------- Super-Agent 底栏徽标

def test_superagent_footer_seg_shows_activity():
    """绑定引擎运行且有待人工/存活 Worker 时, 底栏追加 SA 徽标; 否则为空。"""
    tui = _tui()
    # 无引擎: 空
    assert tui._superagent_footer_seg(None) == []

    class _FakePanel:
        def needs_human(self):
            return [object()]  # 1 项待人工

    class _FakeWorkers:
        def active_count(self):
            return 2

    class _FakeSA:
        def __init__(self):
            self.workers = _FakeWorkers()
            self.panel = _FakePanel()

    seg = tui._superagent_footer_seg(_FakeSA())
    text = "".join(s for _c, s in seg)
    assert "SA:2" in text   # 存活 Worker
    assert "SA!1" in text   # 待人工
    # 无活动时为空
    class _Idle:
        workers = type("W", (), {"active_count": lambda self: 0})()
        panel = type("P", (), {"needs_human": lambda self: []})()
    assert tui._superagent_footer_seg(_Idle()) == []


# ---------------------------------------------------------------- Super-Agent 引擎绑定

def test_bind_superagent_creates_and_wires_engine():
    """set_ready 绑定后, agent 挂上 _superagent 且 listener 把事件推入对话区。

    验证融合点: TUI 就绪时即创建引擎 (与 /superagent 复用同一单例), 并通过
    Router.add_listener 把 dispatch/ticket_update 事件转为对话区日志行。
    """
    tui = _tui()
    agent = type("A", (), {})()   # 无 _superagent → 应惰性创建
    tui._agent = agent

    tui._bind_superagent()

    eng = getattr(agent, "_superagent", None)
    assert eng is not None, "set_ready 后 agent 应挂上 _superagent 引擎"
    assert getattr(eng, "_tui_bound", False) is True, "listener 应只绑定一次"
    assert len(eng.router._listeners) == 1, "应注册一个 Router listener"

    # 直接调用 listener 验证 dispatch 事件进入对话区日志
    eng.router._listeners[0]("dispatch", {"title": "修复登录 bug", "worker_id": "wk-1"})
    flat = "".join("".join(seg for _, seg in line) for line in tui._scrolled_lines())
    assert "后台任务已开单" in flat and "修复登录 bug" in flat

    # ticket_update done → 完成日志
    eng.router._listeners[0]("ticket_update", {
        "ticket_id": "t1",
        "report": {"ticket_id": "t1", "status": "done", "result": "已修复并推送 PR"},
    })
    flat = "".join("".join(seg for _, seg in line) for line in tui._scrolled_lines())
    assert "任务完成" in flat and "已修复并推送 PR" in flat


def test_bind_superagent_idempotent_and_safe():
    """重复绑定不产生重复 listener; 无 agent / 异常时不抛。"""
    tui = _tui()
    # 无 agent: 安全返回, 不创建引擎
    tui._agent = None
    tui._bind_superagent()   # 不应抛

    agent = type("A", (), {})()
    tui._agent = agent
    tui._bind_superagent()
    eng = getattr(agent, "_superagent", None)
    assert eng is not None
    first = len(eng.router._listeners)
    # 二次绑定: 幂等, 不新增 listener
    tui._bind_superagent()
    assert len(eng.router._listeners) == first == 1


# ---------------------------------------------------------------- OpenCode 视觉对齐

def test_style_dict_border_weakened():
    """边框/分隔线色弱化为暗灰 —— 与面板背景区分但不抢眼 (OpenCode 克制边框)。"""
    from tuan_cli.tui.tui import _STYLE_DICT
    assert _STYLE_DICT["border"] == "#4A4A4A"


def test_style_dict_slashsel_restrained():
    """slash 选中行克制化: 柔和蓝底 + 常规亮度, 去掉纯白粗体反显。"""
    from tuan_cli.tui.tui import _STYLE_DICT
    sel = _STYLE_DICT["slashsel"]
    assert "bg:#234163" in sel
    assert "bold" not in sel
    assert "#FFFFFF" not in sel


def test_scroll_indicator_uses_accent_not_warning():
    """回卷指示位置用 accent 蓝 (非警示黄), 回底提示用弱灰。"""
    tui = _tui()
    for i in range(40):
        tui.append_log(f"MSG{i:03d}")
    vp = tui._viewport_rows()
    tui._scroll_log(-vp * 2)
    parts = tui._scroll_indicator()
    assert parts
    cls = parts[0][0]
    assert cls == "class:accent", f"位置应改用 accent, 实际 {cls}"
    assert parts[1][0] == "class:textmuted", "回底提示应弱化为 textmuted"
