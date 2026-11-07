"""/superagent 斜杠命令 —— DeepSeek Super-Agent 双层架构入口。

对标 DeepSeek《Super-agent 设计探索》的完整系统, 提供从 REPL 驱动
Super-Agent 引擎的子命令:

    /superagent start         启动引擎 (Watchdog + 恢复未完成工单)
    /superagent stop          停止引擎
    /superagent status        状态摘要 (Router/Worker/Watchdog/面板)
    /superagent panel         渲染「现在有什么需要我」面板
    /superagent mode <off|observe|auto>   切换接单模式
    /superagent ingest <来源> <内容>      注入一条外部事件 (便捷入口)
    /superagent speculate <提示> [标题]   投机执行 (后台提前尝试)
    /superagent source <name> [kwargs]    注册外部事件源
    /superagent rule <匹配> [action]      添加程序层过滤规则
    /superagent recover                   手动触发恢复未完成工单
    /superagent accept <ticket_id>        验收工单 (待审阅 → 完成)
    /superagent retry <ticket_id>         重试工单 (失败/受阻 → 重新分派)
    /superagent reply <ticket_id> <内容>  回答待回答工单
    /superagent list                      列出面板条目 (JSON)
"""

from __future__ import annotations

import json
from typing import Any, Optional

from ._ui_singleton import ui


def _get_engine(agent: Any) -> Any:
    """获取 (或首次惰性创建) 挂在 agent 上的 SuperAgent 单例。"""
    eng = getattr(agent, "_superagent", None)
    if eng is None:
        from ..superagent import SuperAgent, WorkMode
        eng = SuperAgent(home="~/.tuan", agent=agent, work_mode=WorkMode.OBSERVE)
        setattr(agent, "_superagent", eng)
    return eng


def _cmd_superagent(agent: Any, arg: str) -> None:
    """处理 /superagent 子命令。"""
    parts = arg.strip().split(None, 1)
    sub = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""

    if not sub or sub in ("help", "?"):
        _usage()
        return

    eng = _get_engine(agent)

    if sub == "start":
        eng.start()
        ui.success(f"Super-Agent 已启动: {eng.summary()}")
    elif sub == "stop":
        eng.stop()
        ui.success("Super-Agent 已停止")
    elif sub == "status":
        st = eng.status()
        # OpenCode 风格: 状态是「后台任务视角」, 经 @agent 徽章推入对话区,
        # 与普通命令输出区分 (有 TUI 桥接时走徽章; 否则纯文本)。
        lines = [f"Super-Agent 状态 (mode={st['work_mode']} · max_workers={st['max_workers']})",
                 f"  started={st['started']} · active_workers={st['active_workers']} "
                 f"· recovered={st['recovered']}",
                 f"  router: {json.dumps(st['router'], ensure_ascii=False)}"]
        for w in st["workers"]:
            lines.append(f"  worker[{w.get('worker_id','?')}] {w.get('status','?')} "
                         f"{w.get('progress','')[:60]}")
        wd = st.get("watchdog", {})
        lines.append(f"  watchdog: {json.dumps(wd, ensure_ascii=False)}")
        lines.append(f"  event_bus: {json.dumps(st['event_bus'], ensure_ascii=False)}")
        if hasattr(ui, "agent_info"):
            ui.agent_info("\n".join(lines), cls="class:text")
        else:
            ui.info("\n".join(lines))
    elif sub == "panel":
        # OpenCode 风格: 面板是「现在有什么需要我」的后台任务视角, 经 @agent 徽章
        # 推入对话区, 与普通命令输出区分 (有 TUI 桥接时走徽章; 否则纯文本)。
        if hasattr(ui, "agent_info"):
            ui.agent_info(eng.render_panel(), cls="class:text")
        else:
            ui.answer_md(eng.render_panel())
    elif sub == "list":
        items = eng.panel.build()
        if not items:
            # OpenCode 风格: 后台任务视角 (空态也带徽章, 保持一致)。
            if hasattr(ui, "agent_info"):
                ui.agent_info("(面板为空)", cls="class:textdim")
            else:
                ui.info("(面板为空)")
            return
        lines = [f"  [{i.priority}] {i.title} · {i.status}" for i in items]
        if hasattr(ui, "agent_info"):
            ui.agent_info("\n".join(lines), cls="class:text")
        else:
            ui.info("\n".join(lines))
    elif sub == "mode":
        from ..superagent import WorkMode
        if not rest:
            ui.info(f"当前模式: {eng.work_mode.value} (可选 off/observe/auto)")
            return
        try:
            eng.work_mode = WorkMode(rest.lower())
            eng.router.work_mode = eng.work_mode
            ui.success(f"接单模式已切换为 {eng.work_mode.value}")
        except ValueError:
            ui.error("模式必须是 off / observe / auto 之一")
    elif sub == "ingest":
        s = rest.split(None, 1)
        if len(s) < 2:
            ui.error("用法: /superagent ingest <来源> <内容>")
            return
        # 融合: 首次注入即自动启动引擎 (Watchdog + 恢复), 无需显式 /superagent start
        if not eng.is_running():
            eng.start()
        trg = eng.ingest_text(s[0], s[1])
        ui.success(f"已注入事件 #{trg.trigger_id} ({trg.source.value}/{trg.kind.value})")
    elif sub == "speculate":
        if not rest:
            ui.error("用法: /superagent speculate <提示> [标题]")
            return
        # 解析可选标题: 提示是第一个字段 (可含空格? 不支持, 用 | 分隔可选标题)。
        # 简化: 提示为整段 rest, 标题可选作为第二段 (用空格分隔, 与用法一致)。
        parts = rest.split(None, 1)
        prompt = rest
        title = ""
        if " | " in rest:
            prompt, title = rest.split(" | ", 1)
        entry = eng.speculate(prompt, title=title.strip())
        ui.info(f"投机执行已启动 [{entry['id']}]: {entry['title']}")
    elif sub == "source":
        if not rest:
            ui.info("当前注册的事件源:")
            for s in eng.bus.sources():
                ui.info(f"  {s.name} ({type(s).__name__})")
            return
        name = rest
        ui.info(f"事件源 {name} 注册说明: 用代码 add_source(EventSource) 接入具体实现")
    elif sub == "rule":
        s = rest.split(None, 1)
        if not s:
            ui.error("用法: /superagent rule <匹配词> [allow|drop]")
            return
        from ..superagent import ProgramRule
        action = s[1].strip() if len(s) > 1 else "allow"
        # ProgramRule 用 fn 谓词; 简化: 匹配词出现在 content 中即命中
        kw = s[0]
        eng.add_rule(ProgramRule(name=kw, fn=lambda t, k=kw: k in t.content, action=action))
        ui.success(f"已添加规则: match='{kw}' action={action}")
    elif sub == "recover":
        eng._recover_pending()
        ui.success(f"恢复检查完成: {eng._recovered} 个工单恢复")
    elif sub == "accept":
        # 验收工单: REVIEW → DONE (结果已采纳)
        if not rest:
            ui.error("用法: /superagent accept <ticket_id>")
            return
        ticket = eng.accept_ticket(rest.split()[0])
        if ticket is None:
            ui.error(f"工单不存在或不可验收: {rest.split()[0]}")
            return
        ui.success(f"已验收: {ticket.title} (结果已采纳)")
    elif sub == "retry":
        # 重试工单: FAILED/BLOCKED → 重新分派
        if not rest:
            ui.error("用法: /superagent retry <ticket_id>")
            return
        ticket = eng.retry_ticket(rest.split()[0])
        if ticket is None:
            ui.error(f"工单不存在或不可重试: {rest.split()[0]}")
            return
        ui.success(f"已重试: {ticket.title}")
    elif sub == "reply":
        # 回答 NEEDS_INPUT 工单: 把答复注入
        s = rest.split(None, 1)
        if len(s) < 2:
            ui.error("用法: /superagent reply <ticket_id> <内容>")
            return
        ticket = eng.reply_ticket(s[0], s[1])
        if ticket is None:
            ui.error(f"工单不存在或不在待回答状态: {s[0]}")
            return
        ui.success(f"已回答: {ticket.title}")
    elif sub == "summary":
        # OpenCode 风格: 一行摘要也属后台任务视角, 带 @agent 徽章。
        if hasattr(ui, "agent_info"):
            ui.agent_info(eng.summary(), cls="class:text")
        else:
            ui.info(eng.summary())
    else:
        ui.error(f"未知子命令: {sub}")
        _usage()


def _usage() -> None:
    ui.info("Super-Agent (DeepSeek 双层架构) 子命令:")
    ui.info("  /superagent start       启动引擎 (Watchdog + 恢复)")
    ui.info("  /superagent stop        停止引擎")
    ui.info("  /superagent status      状态摘要")
    ui.info("  /superagent panel       渲染待办面板")
    ui.info("  /superagent mode <off|observe|auto>   切换接单模式")
    ui.info("  /superagent ingest <来源> <内容>      注入外部事件")
    ui.info("  /superagent speculate <提示> [标题]   投机执行")
    ui.info("  /superagent source [name]             事件源管理")
    ui.info("  /superagent rule <匹配> [allow|drop]  程序层过滤规则")
    ui.info("  /superagent recover     手动恢复未完成工单")
    ui.info("  /superagent accept <ticket_id>   验收工单 (待审阅 → 完成)")
    ui.info("  /superagent retry <ticket_id>    重试工单 (失败/受阻 → 重新分派)")
    ui.info("  /superagent reply <ticket_id> <内容>  回答待回答工单")
    ui.info("  /superagent list        面板条目 (JSON)")
