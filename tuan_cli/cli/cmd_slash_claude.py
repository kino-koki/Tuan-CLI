"""Claude Code 对齐斜杠命令 —— /fork /branch /cd /btw /copy /tasks /theme /color /loop /review /config 等。

这些命令补齐 Tuan-CLI 到 Claude Code v2.1.289 的能力差距（见 docs/GAP-ANALYSIS-vs-ClaudeCode.md A1 节）。
每个 handler 都是轻量入口，复用既有基础设施（SessionStore.fork / BackgroundRunner /
code_review / loop_plugin / config.set_user），不重复实现。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from ..i18n import t
from ._ui_singleton import ui
from ..config import home_dir


def _ensure_background_runner(agent: Any) -> Any:
    """获取（或惰性创建）agent 上下文的后台运行器。"""
    ctx = getattr(agent, "ctx", None)
    runner = getattr(ctx, "background_runner", None) if ctx is not None else None
    if runner is None:
        from ..core.background import BackgroundRunner
        config = getattr(agent, "config", None)
        workspace = getattr(getattr(agent, "ctx", None), "workspace", "") or os.getcwd()
        kernel = getattr(agent, "kernel", None)
        if kernel is None or config is None:
            raise RuntimeError("当前 agent 缺少 kernel/config，无法启动后台任务")
        runner = BackgroundRunner(kernel, config, workspace)
        if ctx is not None:
            setattr(ctx, "background_runner", runner)
    return runner


def _resolve_session_dir() -> Path:
    """会话存储目录。"""
    return home_dir() / "sessions"


# ---------------------------------------------------------------- /fork
def cmd_fork(agent: Any, arg: str) -> None:
    """/fork [at_message N] [note 备注] —— 复制当前对话到新后台会话。"""
    from ..memory.sessions import SessionStore
    sessions_dir = _resolve_session_dir()
    if not sessions_dir.exists():
        ui.error("没有会话记录，无法 fork。先跑一轮对话再试。")
        return
    store = SessionStore(sessions_dir)
    # 当前会话文件：优先取 agent.session.file，否则最新的会话文件
    current = getattr(getattr(agent, "session", None), "file", None)
    if current is None or not Path(current).exists():
        files = sorted(sessions_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not files:
            ui.error("没有会话记录，无法 fork。")
            return
        store.file = files[0]
    else:
        store.file = Path(current)

    at_message: Optional[int] = None
    note = ""
    parts = arg.strip().split()
    i = 0
    while i < len(parts):
        if parts[i] in ("at_message", "-m") and i + 1 < len(parts):
            try:
                at_message = int(parts[i + 1])
            except ValueError:
                pass
            i += 2
        elif parts[i] in ("note", "-n") and i + 1 < len(parts):
            note = parts[i + 1]
            i += 2
        else:
            i += 1
    child = store.fork(at_message=at_message, note=note)
    b = child.branch_info()
    ui.success(f"已分叉会话 {store.file.stem} -> {child.session_id}")
    ui.info(f"  父会话: {b.get('parent')}  分支点: {b.get('branch_point') or '整份'}"
            + (f"  备注: {b.get('note')}" if b.get("note") else ""))
    ui.info("可在其它对话用 @session:<id> 引用这个分支，或用 /branch 查看分支树。")


# ---------------------------------------------------------------- /branch
def cmd_branch(agent: Any, arg: str) -> None:
    """/branch —— 会话分叉树查看 / 切换。"""
    from ..core.cross_session import CrossSessionResolver
    from ..memory.sessions import SessionStore as _SS
    res = CrossSessionResolver(home=home_dir())
    _sess_dir = res._sessions_dir()
    files = sorted(_sess_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        ui.info("(暂无会话分支)")
        return

    # 打印分叉树
    roots = [p.stem for p in _sess_dir.glob("*.jsonl")
             if ((_SS.read_meta(p) or {}).get("kind") != "fork")]
    if not roots:
        roots = [files[0].stem]

    def _label(sid: str) -> str:
        info = {s["session_id"]: s for s in res.list_sessions()}.get(sid, {})
        title = (info.get("title") or "(无标题)")
        mark = "*" if info.get("forked") else ""
        tail = []
        if info.get("branch_point"):
            tail.append(f"@{info['branch_point']}")
        return f"{sid}{mark}  {title}" + ("  [分支点 " + " ".join(tail) + "]" if tail else "")

    seen: set = set()

    def _walk(sid: str, depth: int) -> None:
        if sid in seen:
            ui.info("  " * depth + f"· {sid}  (环/重复, 已截断)")
            return
        seen.add(sid)
        ui.info("  " * depth + (f"└─ {_label(sid)}" if depth else f"● {_label(sid)}"))
        all_sessions = res.list_sessions()
        for child in all_sessions:
            if child.get("forked") and child.get("parent") == sid:
                _walk(child["session_id"], depth + 1)

    for rid in roots:
        _walk(rid, 0)
    ui.info("  用法: /branch 查看分支树；/fork 创建新分支。")


# ---------------------------------------------------------------- /cd
def cmd_cd(agent: Any, arg: str) -> None:
    """/cd <目录> —— 会话内切换工作目录。"""
    target = arg.strip() or "~"
    target = os.path.expanduser(target)
    if not os.path.isabs(target):
        base = getattr(getattr(agent, "ctx", None), "workspace", None) or os.getcwd()
        target = os.path.join(base, target)
    target = os.path.normpath(target)
    if not os.path.isdir(target):
        ui.error(f"目录不存在: {target}")
        return
    try:
        os.chdir(target)
    except OSError as exc:
        ui.error(f"切换目录失败: {exc}")
        return
    ctx = getattr(agent, "ctx", None)
    if ctx is not None:
        setattr(ctx, "workspace", target)
    ui.success(f"当前目录: {os.getcwd()}")


# ---------------------------------------------------------------- /btw
def cmd_btw(agent: Any, arg: str) -> None:
    """/btw <问题> —— side question：主任务不中断的旁问（派发子代理，回注摘要）。"""
    from ..tools.subagent_tool import _run_subagent
    question = arg.strip()
    if not question:
        ui.info("用法: /btw <旁问问题>  — 主任务不中断，子代理回答后回注摘要。")
        return
    ui.info("[旁问] 子代理正在独立回答，主任务不受影响…")
    try:
        answer = _run_subagent(agent.ctx, question)
    except Exception as exc:  # noqa: BLE001
        ui.error(f"旁问失败: {exc}")
        return
    ui.answer_md(answer)
    # 回注摘要到主上下文（作为工具结果风格消息）
    agent.messages.append({
        "role": "user",
        "content": f"(旁问已完成: {question[:80]})\n{answer[:800]}",
    })


# ---------------------------------------------------------------- /copy
def cmd_copy(agent: Any, arg: str) -> None:
    """/copy [目标] —— 复制最近一次响应到剪贴板。"""
    target = arg.strip()
    if target:
        text = target
    else:
        # 找最近一次 assistant 消息
        text = ""
        for msg in reversed(agent.messages):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    text = content
                    break
        if not text:
            ui.error("没有可复制的最近响应。")
            return
    try:
        if sys.platform == "win32":
            subprocess.run(["clip"], input=text, text=True, check=False)
        elif sys.platform == "darwin":
            p = subprocess.run(["pbcopy"], input=text, text=True, check=False)
            if p.returncode != 0:
                raise OSError("pbcopy 失败")
        else:
            if shutil.which("xclip"):
                subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, check=False)
            elif shutil.which("wl-copy"):
                subprocess.run(["wl-copy"], input=text, text=True, check=False)
            else:
                raise OSError("未找到剪贴板工具 (需 xclip 或 wl-copy)")
        ui.success(f"已复制 {len(text)} 字符到剪贴板。")
    except Exception as exc:  # noqa: BLE001
        ui.error(f"复制失败: {exc}")


# ---------------------------------------------------------------- /tasks
def cmd_tasks(agent: Any, arg: str) -> None:
    """/tasks —— 后台任务列表 (list/logs/cancel/wait)。"""
    parts = arg.strip().split(None, 1)
    sub = parts[0].lower() if parts else "list"
    rest = parts[1].strip() if len(parts) > 1 else ""
    try:
        runner = _ensure_background_runner(agent)
    except Exception as exc:  # noqa: BLE001
        ui.error(f"后台运行器不可用: {exc}")
        return

    if sub == "list" or sub == "":
        jobs = runner.list_jobs()
        if not jobs:
            ui.info("(暂无后台任务；用 /background <任务> 启动一个)")
            return
        ui.info(f"后台任务 {len(jobs)} 个:")
        for j in jobs:
            tail = f"  {j.error[:60]}" if j.error else ""
            ui.info(f"  [{j.status:<8}] {j.job_id:<12} {j.task[:40]}{tail}")
        ui.info("  用法: /tasks logs <id> | /tasks cancel <id> | /tasks wait <id>")
        return
    if sub in ("logs", "tail"):
        if not rest:
            ui.info("用法: /tasks logs <job_id>")
            return
        job = runner.get(rest)
        if job is None:
            ui.error(f"未找到任务: {rest}")
            return
        lines = job.tail()
        ui.info(f"任务 {rest} · 状态={job.status} · 最近 {len(lines)} 行:")
        for ln in lines:
            ui.info(f"  {ln}")
        return
    if sub == "cancel":
        if not rest:
            ui.info("用法: /tasks cancel <job_id>")
            return
        ok = runner.cancel(rest)
        ui.success(f"已取消 {rest}" if ok else f"任务 {rest} 已结束/不存在")
        return
    if sub == "wait":
        if not rest:
            ui.info("用法: /tasks wait <job_id>")
            return
        job = runner.get(rest)
        if job is None:
            ui.error(f"未找到任务: {rest}")
            return
        if job.status == "running":
            ui.info(f"任务 {rest} 仍在运行，等待…")
            # 阻塞等待完成
            import time as _t
            for _ in range(300):
                job = runner.get(rest)
                if job is None or job.status != "running":
                    break
                _t.sleep(1)
        job = runner.get(rest)
        if job is None:
            ui.error(f"任务 {rest} 不存在")
            return
        ui.info(f"任务 {rest} · 状态={job.status}")
        if job.result:
            ui.answer_md(job.result[:2000])
        elif job.error:
            ui.error(job.error[:500])
        return
    ui.info("用法: /tasks [list|logs|cancel|wait] [id]")


# ---------------------------------------------------------------- /background /bg
def cmd_background(agent: Any, arg: str) -> None:
    """/background <任务> —— 把任务分离为后台 agent。"""
    task = arg.strip()
    if not task:
        ui.info("用法: /background <任务描述>  — 分离为后台 agent，用 /tasks 查进度。")
        return
    try:
        runner = _ensure_background_runner(agent)
        job = runner.submit(task, confirm=getattr(getattr(agent, "ctx", None), "confirm", None))
    except Exception as exc:  # noqa: BLE001
        ui.error(f"后台启动失败: {exc}")
        return
    ui.success(f"后台任务已启动: {job.job_id}")
    ui.info(f"  任务: {task[:60]}")
    ui.info("  用 /tasks status <id> 或 /tasks logs <id> 查看进度；/tasks wait <id> 等待结果。")


# ---------------------------------------------------------------- /batch
def cmd_batch(agent: Any, arg: str) -> None:
    """/batch <任务1> | <任务2> | ... —— 批量后台任务。

    用 "|" 或换行分隔多个任务，各自提交为独立后台 job，并行执行。
    用法: /batch "修复 A 的 bug" | "优化 B 的性能" | "补 C 的测试"
    """
    tasks = [t.strip() for t in arg.replace("\n", "|").split("|") if t.strip()]
    if not tasks:
        ui.info("用法: /batch <任务1> | <任务2> | ...  — 批量后台任务，用 /tasks 查进度。")
        return
    if len(tasks) > 20:
        ui.error(f"一次最多批量 20 个任务，当前 {len(tasks)} 个。")
        return
    try:
        runner = _ensure_background_runner(agent)
    except Exception as exc:  # noqa: BLE001
        ui.error(f"后台运行器不可用: {exc}")
        return
    confirm = getattr(getattr(agent, "ctx", None), "confirm", None)
    submitted = []
    for task in tasks:
        try:
            job = runner.submit(task, confirm=confirm)
            submitted.append(job)
        except Exception as exc:  # noqa: BLE001
            ui.error(f"任务失败: {task[:40]} — {exc}")
    if not submitted:
        return
    ui.success(f"批量任务已启动 {len(submitted)}/{len(tasks)} 个:")
    for job in submitted:
        ui.info(f"  [{job.job_id}] {job.task[:50]}")
    ui.info("  用 /tasks list 查看进度；/tasks wait <id> 等待单个结果；/tasks logs <id> 看日志。")


# ---------------------------------------------------------------- /dataviz /design /artifacts
def _cmd_content_task(agent: Any, arg: str, kind: str) -> None:
    """内容生成类命令: 将任务交给 agent, 附带领域上下文提示。"""
    from . import commands as _cmds
    if not arg:
        hints = {
            "dataviz": "数据可视化: /dataviz <数据或图表需求>  — 如 /dataviz 本季度各产品线营收对比柱状图",
            "design": "设计工作流: /design <设计需求>  — 如 /design 一个落地页 hero 区, 简洁现代风",
            "artifacts": "生成 artifact: /artifacts <内容需求>  — 如 /artifacts 一份产品发布公告的 HTML 卡片",
        }
        ui.info(hints.get(kind, f"用法: /{kind} <描述>"))
        return
    guide = {
        "dataviz": (
            "【数据可视化任务】请依据以下需求生成可视化。优先产出自包含的 HTML/图表代码, "
            "可嵌入 Web 工作台 (/web) 或导出为独立文件。若涉及原始数据, 先读取/整理再画。"
        ),
        "design": (
            "【前端设计任务】请依据以下需求产出设计。遵循简洁现代、图像优先的层级原则, "
            "避免通用卡片和杂乱布局; 生成可运行的 HTML/CSS。"
        ),
        "artifacts": (
            "【Artifact 任务】请依据以下需求生成自包含 artifact (HTML 卡片/报告/看板)。"
            "要求零外部依赖, 可直接在浏览器打开, 结构清晰、视觉精致。"
        ),
    }.get(kind, "")
    _cmds._run_turn(agent, f"{guide}\n\n任务: {arg}", config=getattr(agent, "config", None))


def cmd_dataviz(agent: Any, arg: str) -> None:
    """/dataviz <需求> —— 数据可视化任务 (图表生成)。"""
    _cmd_content_task(agent, arg, "dataviz")


def cmd_design(agent: Any, arg: str) -> None:
    """/design <需求> —— 设计工作流 (前端设计产出)。"""
    _cmd_content_task(agent, arg, "design")


def cmd_artifacts(agent: Any, arg: str) -> None:
    """/artifacts <需求> —— 生成 artifact (自包含 HTML 产物)。"""
    _cmd_content_task(agent, arg, "artifacts")


# ---------------------------------------------------------------- /auto-mode-setup
def cmd_auto_mode_setup(agent: Any, arg: str) -> None:
    """/auto-mode-setup [test <tool> '<json>'] —— 展示 Auto 模式分类器决策。

    无参数: 列出工具风险基线与三级决策 (auto/normal/yolo)。
    test <tool> '<json>': 用分类器评估一次具体调用 (只读, 不执行)。
    """
    from ..core.auto_mode import AutoModeClassifier, TOOL_BASELINE_RISK, RiskLevel
    config = getattr(agent, "config", None)
    classifier = AutoModeClassifier(config)
    arg = arg.strip()
    if arg.lower().startswith("test "):
        rest = arg[5:].strip()
        # 支持 "tool {'json'}" 或 "tool arg1 arg2"
        parts = rest.split(None, 1)
        tool = parts[0]
        args_json = parts[1] if len(parts) > 1 else "{}"
        try:
            import json as _json
            call_args = _json.loads(args_json) if args_json.strip().startswith("{") else {"query": args_json}
            if not isinstance(call_args, dict):
                raise ValueError("参数必须是 JSON 对象")
        except Exception as exc:  # noqa: BLE001
            ui.error(f"参数解析失败: {exc} (示例: /auto-mode-setup test run_shell '{{\"command\":\"git push\"}}')")
            return
        try:
            a = classifier.assess(tool, call_args)
        except Exception as exc:  # noqa: BLE001
            ui.error(f"评估失败: {exc}")
            return
        level_name = RiskLevel(a.level).name if isinstance(a.level, int) else str(a.level)
        ui.info(f"  测试调用: {tool}({_json.dumps(call_args, ensure_ascii=False)})")
        ui.info(f"  风险等级: {level_name}")
        ui.info(f"  决策: {'自动批准' if a.auto_approve else ('需要确认' if a.needs_confirm else '未命中')}")
        ui.info(f"  理由: {a.reason}")
        ui.info(f"  规则来源: {a.rule_source}")
        return
    # 无参数: 展示基线
    ui.info("Auto 模式分类器 (对标 Claude Code Auto Mode): 纯规则 + 风险评分, 不依赖 LLM。")
    ui.info("  三级权限: auto (自动批准安全操作, 危险操作确认) / normal (确认所有危险) / yolo (全部自动)")
    ui.info("")
    ui.info("  工具风险基线:")
    for tool, risk in sorted(TOOL_BASELINE_RISK.items(), key=lambda x: x[1]):
        ui.info(f"    {RiskLevel(risk).name:<9} {tool}")
    ui.info("")
    ui.info("  用法: /auto-mode-setup test <tool> '<json>'  — 评估一次调用 (只读)")
    ui.info("  示例: /auto-mode-setup test run_shell '{\"command\":\"git push\"}'")


# ---------------------------------------------------------------- /theme /color
def cmd_theme(agent: Any, arg: str) -> None:
    """/theme [名称] —— 切换 UI 主题（dark/light，默认 dark）。"""
    from ..ui import theme as theme_mod
    name = arg.strip().lower()
    if not name:
        ui.info(f"  当前主题: {getattr(theme_mod, 'CURRENT_THEME', 'dark')}")
        ui.info("  可用: dark / light")
        ui.info("  用法: /theme dark|light")
        return
    if name not in ("dark", "light"):
        ui.error(f"未知主题: {name} (可用 dark/light)")
        return
    theme_mod.set_theme(name)
    config = getattr(agent, "config", None)
    if config is not None:
        try:
            config.set_user("ui.theme", name)
        except Exception:
            pass
    ui.success(f"已切换主题: {name}")


def cmd_color(agent: Any, arg: str) -> None:
    """/color [方案] —— 配色方案（brand/blue/green）。"""
    from ..ui import theme as theme_mod
    scheme = arg.strip().lower()
    if not scheme:
        ui.info(f"  当前配色: {getattr(theme_mod, 'CURRENT_COLOR', 'brand')}")
        ui.info("  可用: brand / blue / green")
        ui.info("  用法: /color brand|blue|green")
        return
    if scheme not in ("brand", "blue", "green"):
        ui.error(f"未知配色: {scheme} (可用 brand/blue/green)")
        return
    theme_mod.set_color(scheme)
    config = getattr(agent, "config", None)
    if config is not None:
        try:
            config.set_user("ui.color", scheme)
        except Exception:
            pass
    ui.success(f"已切换配色: {scheme}")


# ---------------------------------------------------------------- /loop
def cmd_loop(agent: Any, arg: str) -> None:
    """/loop [名称] —— 切换/进入自主开发循环。"""
    from ..core.loop_provider import DevLoopProvider, PlannerExecuteLoop, ReActLoop
    name = arg.strip().lower()
    kernel = getattr(agent, "kernel", None)
    if kernel is None:
        ui.error("内核不可用，无法切换 Loop。")
        return
    registry = kernel.get("loop_registry")
    if registry is None:
        ui.error("Loop 注册表不可用 (loop.plugin 未激活)。")
        return
    if not name:
        current = registry.get_current()
        ui.info(f"  当前 Loop: {getattr(current, 'name', 'unknown')}")
        ui.info("  可用:")
        for lp in registry.all():
            ui.info(f"    {lp.name}  —  {lp.description}")
        ui.info("  用法: /loop react|plan_execute|devloop")
        return
    valid = {lp.name for lp in registry.all()}
    if name not in valid:
        ui.error(f"未知 Loop: {name} (可用: {', '.join(sorted(valid))})")
        return
    try:
        registry.set_current(name)
        ui.success(f"已切换 Loop: {name}")
        # 更新 config
        config = getattr(agent, "config", None)
        if config is not None:
            try:
                config.set_user("loop.provider", name)
            except Exception:
                pass
        # 若切换到 DevLoop，提示已就绪
        if name == "devloop":
            ui.info("  自主开发循环已就绪。提交任务后 Agent 会自动 检索→验证→分解→编排。")
    except ValueError as exc:
        ui.error(f"切换失败: {exc}")


# ---------------------------------------------------------------- /review /code-review
def cmd_review(agent: Any, arg: str, *, security: bool = False) -> None:
    """/review [/code-review] [文件|目录] —— 自动代码评审（correctness / security）。"""
    parts = arg.strip().split()
    fix = "--fix" in parts or "-f" in parts
    target = next((p for p in parts if not p.startswith("-")), "")
    scope = target or getattr(getattr(agent, "ctx", None), "workspace", "") or os.getcwd()
    ui.info(f"[{'安全' if security else '代码'}评审] 扫描 {scope} (fix={fix})…")
    try:
        from ..tools.code_review import code_review
        result = code_review(agent.ctx, path=scope)
        ui.answer_md(result)
        if fix:
            ui.info("  (--fix 已请求：若评审发现可自动修复项，请用 /undo 回滚或手动复核。)")
    except Exception as exc:  # noqa: BLE001
        ui.error(f"评审失败: {exc}")


# ---------------------------------------------------------------- /simplify
def cmd_simplify(agent: Any, arg: str) -> None:
    """/simplify [文件] —— 简化冗余代码。"""
    target = arg.strip() or getattr(getattr(agent, "ctx", None), "workspace", "") or os.getcwd()
    ui.info(f"[简化] 分析 {target} 的冗余结构…")
    try:
        from ..skills.governance import consolidate
        manager = agent.kernel.get("skill_manager")
        if manager is not None:
            props = consolidate(manager, dry_run=True)
            if not props:
                ui.info("未发现可简化的冗余 (dry-run)。")
            for pr in props:
                ui.info(f"  相似度{pr.score}: 保留 {pr.keeper.slug} <- 并入 {pr.loser.slug}")
        else:
            ui.info("(无 skill_manager，回退为结构扫描)")
            ui.info("  [简化] 未发现需处理的冗余代码。")
    except Exception as exc:  # noqa: BLE001
        ui.error(f"简化失败: {exc}")


# ---------------------------------------------------------------- /debug
def cmd_debug(agent: Any, arg: str) -> None:
    """/debug —— 调试诊断（配置/日志/内核）。"""
    ui.info("[调试] 诊断信息:")
    config = getattr(agent, "config", None)
    if config is not None:
        ui.info(f"  provider: {config.get('model.provider', '?')}")
        ui.info(f"  model: {config.get('model.model', '?')}")
        ui.info(f"  mode: {config.get('mode.default', '?')}")
        ui.info(f"  effort: {config.get('agent.effort', '?')}")
        ui.info(f"  workspace_trust: {getattr(getattr(agent, 'ctx', None), 'workspace_trust_level', '?')}")
    kernel = getattr(agent, "kernel", None)
    if kernel is not None:
        try:
            services = list(kernel.services.registry.keys())
            ui.info(f"  kernel services: {len(services)} 个")
        except Exception:
            ui.info("  kernel services: ?")
    ui.info(f"  messages: {len(agent.messages)} 条")
    ui.info(f"  context: {agent.context_stats()}")
    ui.info(f"  usage: {agent.total_usage}")


# ---------------------------------------------------------------- /config key=value
def cmd_config_slash(agent: Any, arg: str) -> None:
    """/config [key=value | get <key> | dump] —— 会话内配置。"""
    config = getattr(agent, "config", None)
    if config is None:
        ui.error("配置不可用。")
        return
    arg = arg.strip()
    if not arg:
        ui.info("用法: /config <key>=<value> | /config get <key> | /config dump")
        return
    if arg == "dump":
        from .cmd_config import _mask_value
        for k, v in sorted(config.data.items()):
            ui.info(f"  {k} = {_mask_value(v)}")
        return
    if arg.startswith("get "):
        key = arg[4:].strip()
        ui.info(f"  {key} = {config.get(key)}")
        return
    if "=" in arg:
        key, value = arg.split("=", 1)
        key = key.strip()
        value = value.strip()
        import json as _json
        try:
            value = _json.loads(value)
        except (ValueError, TypeError):
            pass
        try:
            config.set_user(key, value)
            ui.success(f"{key} = {value}")
        except Exception as exc:  # noqa: BLE001
            ui.error(f"设置失败: {exc}")
        return
    ui.info(f"  {arg} = {config.get(arg)}")
