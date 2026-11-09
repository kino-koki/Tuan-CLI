"""交互式对话 + 模型配置 + 配置管理 CLI 命令。

拆分自 commands.py (原 3105 行), 负责:
- cmd_chat: 交互式对话 (REPL / TUI / --print)
- cmd_mode: 查看/切换运行模式
- cmd_model: 配置/热切换模型供应商
- cmd_config: 配置管理
- cmd_doctor: 环境健康检查
- 相关辅助函数
"""

from __future__ import annotations
from ..paths import default_workspace

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import __version__
from ..config import Config, home_dir
from ..models.provider_catalog import (
    get_provider,
)
from ..logging_conf import log
from ..i18n import (
    ensure_language, t, choose_language_interactive, normalize_language,
    DEFAULT_LANGUAGE, get_language,
)
from ..ui.plain_console import console
from ._ui_singleton import ui
from .cmd_config import _validate_config
from .cmd_slash import list_slash_commands, slash_command_meta, slash_command_tiers


# ---- app 链惰性加载: 构建内核 (~1s) 只在真正进入交互/需要内核时才付出 ----
def build_kernel(*a: Any, **k: Any) -> Any:
    from ..app import build_kernel as _f
    return _f(*a, **k)


def create_agent(*a: Any, **k: Any) -> Any:
    from ..app import create_agent as _f
    return _f(*a, **k)


def seed_builtin_skills(*a: Any, **k: Any) -> Any:
    from ..app import seed_builtin_skills as _f
    return _f(*a, **k)


def _run_json_schema(agent: Any, task_text: str, json_schema_spec: str,
                     args: Any, session_id: str) -> int:
    """--json-schema 结构化输出: 注入指令 -> 跑任务 -> 校验 -> 失败修复重试。

    返回进程退出码 (0=校验通过; 1=任务/校验失败)。
    """
    from ..core.json_schema import (
        build_instruction, load_schema, run_structured,
    )
    import json as _json

    schema, err = load_schema(json_schema_spec)
    if err:
        print(f"[错误] json-schema: {err}", file=sys.stderr)
        return 1
    strict = bool(getattr(args, "json_schema_strict", True))
    retries = max(0, int(getattr(args, "json_schema_retries", 3)))

    # 结构化输出指令注入会话: 追加为 system 消息, 紧随内置系统提示
    instruction = build_instruction(schema, strict=strict)
    if agent.messages and agent.messages[0].get("role") == "system":
        agent.messages.insert(1, {"role": "system", "content": instruction})
    else:
        agent.messages.insert(0, {"role": "system", "content": instruction})

    def _executor(task: str) -> str:
        try:
            return agent.run(task, stream=False, session_id=session_id) or ""
        except Exception as exc:  # noqa: BLE001
            return f"[错误] {exc}"

    result = run_structured(_executor, schema, max_attempts=retries + 1,
                            strict=strict, initial_task=task_text)
    if not result.ok:
        print(_json.dumps({
            "ok": False, "error": result.error, "attempts": result.attempts,
            "raw": result.raw,
        }, ensure_ascii=False, indent=2))
        return 1

    print(_json.dumps(result.value, ensure_ascii=False, indent=2))
    return 0





# ===================================================================== 会话辅助

def _load_session_into_agent(agent: Any, path: Path) -> str:
    """把会话文件的消息重建进 agent.messages (补回系统提示)。返回会话文件名。"""
    from ..memory.sessions import SessionStore
    messages = SessionStore.load_messages(path)
    agent.messages = [{"role": "system", "content": agent._system_prompt}] + messages
    return path.name


def _resume_session(agent: Any, arg: str) -> Optional[str]:
    """从历史会话恢复上下文 (--continue/--resume)。"""
    store = agent.session
    if store is None:
        console.print("会话存储未初始化")
        return None
    candidates = store.list_sessions()
    if arg.isdigit() and 1 <= int(arg) <= len(candidates):
        return _load_session_into_agent(agent, candidates[int(arg) - 1])
    path = Path(arg).expanduser()
    if path.suffix == ".jsonl" and path.exists():
        return _load_session_into_agent(agent, path)
    if arg in ("latest", "last"):
        if candidates:
            return _load_session_into_agent(agent, candidates[0])
    else:
        for p in candidates:
            if p.stem.startswith(arg):
                return _load_session_into_agent(agent, p)
    console.print(f"未找到会话: {arg}")
    return None


def _list_sessions(agent: Any) -> None:
    """列出最近会话 (编号 + 标题 + 时间), 供 /resume 选择。"""
    import datetime as _dt
    store = agent.session
    if store is None:
        console.print("会话存储未初始化")
        return
    from ..memory.sessions import SessionStore
    sessions = store.list_sessions()[:10]
    if not sessions:
        console.print("没有历史会话")
        return
    for i, p in enumerate(sessions, 1):
        title = SessionStore.peek_title(p)
        ts = _dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%m-%d %H:%M")
        console.print(f"  {i:2d}. {p.stem}  {ts}  {title}")
    console.print("输入 /resume <编号|会话id|latest> 恢复")


# ===================================================================== 首次运行

def _auto_first_run() -> bool:
    """首次运行检测: 若家目录不存在或无 API Key, 自动引导快速设置。"""
    from .cmd_setup import cmd_setup  # 局部导入, 避免循环依赖
    home = home_dir()
    if (home / "config.yaml").exists():
        return False
    console.print("首次使用青小团? 让我们快速设置一下…")
    return cmd_setup(type("Args", (), {"quick": True})()) == 0


# ===================================================================== cmd_chat

def _preselect_language() -> None:
    """TUI 首启语言预置 (主线程、进入全屏前调用)。

    根因修复: 此前 ``ensure_language`` 在 ``_boot`` 后台线程里、prompt_toolkit
    ``app.run()`` 全屏渲染期间调用原生 ``input()``, 与 TUI 的终端重绘状态
    冲突 → 表现为"语言输入后无响应卡死 + 第二次启动渲染错乱"。

    这里在 TUI 进入全屏**之前**于主线程同步完成交互式选择: 此时终端仍由
    CLI 控制, ``input()`` 安全。选择结果写盘后, ``_boot`` 里的 ``ensure_language``
    命中"已配置"分支直接返回, 不再触碰原生 input。

    非交互 / 已配置 / 非 TTY: 直接返回, 零开销。
    """
    try:
        cfg = Config()
        if normalize_language(str(cfg.get("language", "") or "")):
            return  # 已配置, 无需询问
        try:
            interactive = sys.stdin.isatty() and sys.stdout.isatty()
        except Exception:  # noqa: BLE001
            interactive = False
        if not interactive:
            return  # 非 TTY (管道/CI/重定向): 让 _boot 走默认 zh-CN
        chosen = choose_language_interactive()
        set_language_global(chosen)
        cfg.set_user("language", chosen)
    except Exception:  # noqa: BLE001 - 语言预置绝不阻断 TUI 启动
        pass


def set_language_global(lang: str) -> None:
    """把语言写进 i18n 全局态 (等价 set_language, 供预置路径复用)。"""
    from ..i18n import set_language as _set
    _set(lang)


def _prepare_agent(args: Any, workspace: str, session_id: str, on_progress: Any = None) -> Any:
    """构建内核 + Agent + 会话钩子 + 内置技能 (TUI / REPL / --print 共用)。

    返回 (kernel, config, agent, mode, effort); 会话恢复失败时返回 None。
    异常由调用方处理 (TUI 走加载屏错误态, REPL/print 直接报错)。
    on_progress(pct, status) 可选, 用于 TUI 加载屏进度反馈。
    """
    # ---- 四层边界 · Project 层自动生效: 会话启动即确保 .tuan/ 存在 (幂等) ----
    # 在 build_kernel 之前执行, 保证任何交互会话 (REPL/TUI/--print) 启动时工作区已就绪。
    # bare 模式仍初始化 (.tuan/ 落在工作区内, 不污染用户全局配置)。失败静默, 不阻断启动。
    try:
        from ..core.boundary_auto import ensure_project_context
        ensure_project_context(
            workspace, config=None, bare=bool(getattr(args, "bare", False)))
    except Exception:  # noqa: BLE001
        pass
    if on_progress:
        on_progress(30, "构建内核…")
    kernel = build_kernel(
        bare=bool(getattr(args, "bare", False)),
        safe_mode=bool(getattr(args, "safe_mode", False)),
    )
    config = kernel.require("config")
    ensure_language(config)
    # 显式 --mode 优先, 否则 fallback 到 --permission-mode 映射
    eff_mode = getattr(args, "mode", None) or resolve_mode_from_permission(args)
    mode = _apply_mode_override(kernel, eff_mode,
                                yes=getattr(args, "yolo", False))
    if getattr(args, "effort", None):
        clamped = clamp_effort(config, args.effort)
        if clamped:
            config.set_user("agent.effort", clamped)
    # --fallback-model: 接线到 model.fallbacks (对标 Claude Code fallbackModel)
    _apply_fallback_model(config, getattr(args, "fallback_model", None))
    if on_progress:
        on_progress(55, "创建 Agent…")
    agent = create_agent(kernel, workspace, user_mode=True)
    # 会话级工具暴露档位 (--tools): 仅本会话生效, 不写盘。
    # minimal / standard / full / auto (auto 按模型能力解析)。
    tools_mode = getattr(args, "tools", None)
    if tools_mode:
        from ..tools.tiers import resolve_exposure
        agent.exposure = resolve_exposure(
            tools_mode, config.get("model.model", "") or "")
    # 会话级 allowedTools (--allowedTools): 命中者免确认; 仅本会话生效
    at = getattr(args, "allowed_tools", None)
    if at:
        from ..core.allowed_tools import AllowedTools
        agent.ctx.allowed_tools = AllowedTools.parse(at)
    # Plan 模式启动: 窗口 Agent 只读 (工具分发层硬拒写操作, 见 tools/base.py:230)
    plan_requested = bool(getattr(args, "plan", False)) or (mode == "plan")
    if plan_requested:
        agent.plan_mode = True
        agent.ctx.plan_mode = True
    # Auto 模式 (对标 Claude Code): 内部标记, 由 ToolExecutor 经分类器按风险分级决策。
    if mode == "auto":
        agent.ctx.auto_mode = True
    _setup_security_alerts()
    _run_session_hooks(agent, "SessionStart", {
        "workspace": workspace,
        "model": config.get("model.model"),
        "provider": config.get("model.provider"),
    })
    if on_progress:
        on_progress(80, "注册会话/技能…")
    seed_builtin_skills(kernel)
    resume_arg = getattr(args, "resume", None)
    if resume_arg:
        loaded = _resume_session(agent, resume_arg)
        if loaded is None:
            return None
    if on_progress:
        on_progress(95, "就绪…")
    return kernel, config, agent, mode, config.get("agent.effort", "high")


def cmd_chat(args: Any) -> int:
    """交互式对话 (默认命令)。"""
    _auto_first_run()
    workspace = getattr(args, "workspace", None) or default_workspace()
    # A4 事件溯源: 为本次会话(REPL/TUI/print 整体)生成一个独立可回放的 session_id
    session_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]

    # --print 非交互模式 (headless, 同步构建)
    is_print = getattr(args, "print_mode", False)
    if is_print:
        prep = _prepare_agent(args, workspace, session_id)
        if prep is None:
            return 1
        kernel, config, agent, mode, effort = prep
        task_text = getattr(args, "task", "") or ""
        if not task_text and not sys.stdin.isatty():
            task_text = sys.stdin.read().strip()
        if not task_text:
            print("[错误] --print 模式需要提供任务描述 (tuan --print chat \"任务\") 或通过 stdin 输入")
            return 1
        max_cost = getattr(args, "max_cost", 0.0)
        if max_cost > 0:
            config.set_user("router.budget_limit", max_cost)
        max_turns = getattr(args, "max_turns", 0)
        if max_turns > 0:
            config.set_user("agent.max_iterations", max_turns)
        def _print_token(t: str) -> None:
            sys.stdout.write(t)
            sys.stdout.flush()

        json_schema_spec = getattr(args, "json_schema", None)
        if json_schema_spec:
            return _run_json_schema(agent, task_text, json_schema_spec, args, session_id)

        answer = agent.run(
            task_text, stream=not getattr(args, "no_stream", False),
            on_token=_print_token, session_id=session_id,
        )
        if answer:
            print(answer)
        usage = agent.total_usage
        prompt_t = usage.get("prompt_tokens", 0)
        compl_t = usage.get("completion_tokens", 0)
        cache_hit = usage.get("prompt_cache_hit_tokens", 0)
        cost = agent._estimate_total_cost()
        cost_str = f" | cost=${cost:.4f}" if cost else ""
        print(f"\n--- tokens: {prompt_t}+{compl_t}, cache_hit={cache_hit}{cost_str} ---", file=sys.stderr)
        return 0

    # 全屏 TUI 模式 (青小团 kimi-fusion: 单 Application, 加载屏内嵌, 无双屏切换崩溃)
    if getattr(args, "tui", False):
        from ..tui.tui import QxtTUI
        state: Dict[str, Any] = {"agent": None, "kernel": None, "config": None, "mode": "standard"}

        def submit_in_tui(text: str) -> Optional[str]:
            agent = state["agent"]
            if agent is None:
                return t("tui.booting_wait")
            if text.strip().startswith("!"):
                # `!` shell 快捷模式: 不经 LLM 直接执行, 输出落日志并注入下一轮上下文
                from .cmd_bang import run_bang_command
                out = run_bang_command(agent, text, display=False)
                tui.append_log(out)
                return t("tui.cmd_done")
            def on_tool(name: str, arguments: str) -> None:
                tui.begin_tool(name)
            def on_tool_result(name: str, result: str) -> None:
                tui.end_tool(name, ok=True)
            def on_token(delta: str) -> None:
                tui.stream_assistant(delta)
            def on_reason(delta: str) -> None:
                tui.stream_reason(delta)
            def on_error(message: str) -> None:
                # 已是 C-2 友好模板 (❌ 开头) 则原样展示, 避免 "[错误] ❌" 双重前缀
                text = message if message.lstrip().startswith("❌") else f"[错误] {message}"
                tui.append_log(text)
                tui.audit("warning", f"[错误] {message}")
                tui.end_any_tool()
            answer = agent.run(
                text,
                stream=True,
                on_token=on_token,
                on_reason=on_reason,
                on_tool=on_tool,
                on_tool_result=on_tool_result,
                on_error=on_error,
                session_id=session_id,
            )
            tui.end_stream()
            # 每轮结束后用真实上下文用量刷新占用条; 只更新已用量、保持分母为模型
            # 上下文窗口, 避免分母在"模型窗口/配置预算"间切换导致的百分比跳变。
            # 优先取 API 返回的真实 prompt_tokens (与模型计费口径一致), 拿不到时
            # 才回落本地字符估算, 杜绝"context: 显示随机数"的观感。
            try:
                st = agent.context_stats()
                if st.get("budget_tokens"):
                    _usage = getattr(agent, "total_usage", {}) or {}
                    _real = int(_usage.get("prompt_tokens", 0) or 0)
                    _est = int(st.get("estimated_tokens", 0) or 0)
                    tui.set_context_used(_real if _real > 0 else _est)
            except Exception:
                pass
            # Super-Agent 融合 (观察, 非接单): 用户对话消息记录进 Router 的
            # 跨任务上下文。只记录不研判不开单 —— 用户消息已由主 Agent 处理,
            # 不能再喂给 Router 开单 (否则双份执行工具)。引擎若尚未创建则跳过
            # (用户未用 /superagent 时零开销, 也不因普通聊天意外开单)。
            try:
                _sa = getattr(agent, "_superagent", None)
                if _sa is not None:
                    _sa.observe_text(text, sender="你", source="local")
            except Exception:  # noqa: BLE001 - 观察失败不阻断对话
                pass
            return answer or t("tui.no_output")

        def command_in_tui(text: str) -> Optional[str]:
            agent = state["agent"]
            if text.strip() in ("/exit", "/quit"):
                tui.close()
                return t("tui.exiting")
            if agent is None:
                return t("tui.booting_wait")
            from .cmd_slash import _handle_slash
            handled = _handle_slash(text, agent,
                                    state["config"], workspace)
            tui.set_plan_mode(agent.plan_mode)
            # 同步五模式徽标: /mode <id> 切换后底部状态栏徽标随之更新
            # (plan 只读态仍由 set_plan_mode 主导, 非 plan 时用 current_mode 刷新)。
            try:
                if not agent.plan_mode:
                    from ..modes.switcher import current_mode
                    tui.set_mode(current_mode())
            except Exception:
                pass
            # 若刚通过 /provider 设置密钥, 立即清除"未配置"横幅 (无需重启)
            try:
                tui.set_no_key(not state["config"].api_key(),
                                   env=_no_key_env(state["config"]))
            except Exception:
                pass
            return t("tui.cmd_done") if handled else t("tui.exiting")

        tui = QxtTUI(submit_in_tui, title="青小团", workspace=workspace,
                     on_cancel=lambda: state["agent"].cancel() if state["agent"] else None,
                     on_command=command_in_tui,
                     commands=list_slash_commands(),
                     command_meta=slash_command_meta(),
                     command_tiers=slash_command_tiers())
        # 立即接管 UI 与日志: 在 _boot 线程 (内核构建 → MCP 接入) 之前完成
        # logging 重定向, 否则 MCP 接入失败等 stdout 输出会在加载动画期间
        # 裸写终端污染全屏 (观感"被报错刷屏")。
        tui.attach_ui()
        tui.set_boot_progress(5, "正在启动青小团…")

        def _boot() -> None:
            try:
                prep = _prepare_agent(args, workspace, session_id,
                                      on_progress=tui.set_boot_progress)
                if prep is None:
                    tui.boot_error(t("tui.resume_fail"))
                    return
                kernel, config, agent, mode, effort = prep
                state.update(agent=agent, kernel=kernel, config=config, mode=mode)
                # 把内核已注册的内置工具名喂给 TUI 侧栏 TOOLS 标签 (防御式: 取不到则跳过)
                try:
                    _reg = kernel.require("tool_registry")
                    _names = [t.name for t in _reg.tools]
                except Exception:
                    _names = []

                def _finish_ready() -> None:
                    # 幂等: 信任确认回调与常规就绪路径都可能触发, 只生效一次
                    if getattr(tui, "_tuan_ready_done", False):
                        return
                    setattr(tui, "_tuan_ready_done", True)
                    tui.set_ready(config, agent, workspace, tools=_names,
                                  no_key=not config.api_key(),
                                  no_key_env=_no_key_env(config), mode=mode)

                # 首次访问新文件夹: Kimi/Claude Code 风格信任确认。
                # **关键: 挂出确认卡片后仍然照常 set_ready** —— 输入框与 Agent 都必须可用。
                # 早期实现此处 `return` 且不调 set_ready, 导致确认态下 TUI 既不能正常对话、
                # 一旦用户没按 y/n 就永久卡住 (表现即"所有 TUI 都没有输入框")。
                # 现在的语义: 确认卡片只是"提示 + 可选的 y/n 回答"; 用户直接打字即视为信任。
                try:
                    from ..config.loader import home_dir
                    from ..core.workspace_trust import TrustLevel, WorkspaceTrust
                    _trust = WorkspaceTrust(home_dir())
                    _level = _trust.check_trust(workspace)
                    # E2: 衰减后的级别必须让用户看见, 否则"权限悄悄收紧"会让人困惑。
                    _decay_reason = _trust.get_project_info(workspace).get("decay_reason", "")
                    if _decay_reason:
                        _notify = getattr(tui, "warning", None) or getattr(tui, "info", None)
                        if callable(_notify):
                            try:
                                _notify(f"工作区信任已自动降级为 limited: {_decay_reason}")
                            except Exception:  # noqa: BLE001
                                pass
                    if _level == TrustLevel.UNKNOWN:
                        def _on_trust(trusted: bool) -> None:
                            try:
                                _trust.set_trust(
                                    workspace,
                                    TrustLevel.TRUSTED if trusted else TrustLevel.UNTRUSTED,
                                    project_name=os.path.basename(os.path.normpath(workspace)),
                                )
                                setattr(agent.ctx, "workspace_trust_level",
                                        TrustLevel.TRUSTED if trusted else TrustLevel.UNTRUSTED)
                            except Exception:  # noqa: BLE001
                                pass
                        if hasattr(tui, "prompt_trust"):
                            tui.prompt_trust(workspace, on_confirm=_on_trust)
                    setattr(agent.ctx, "workspace_trust_level", _level)
                except Exception:  # noqa: BLE001
                    pass
                _finish_ready()
            except Exception as exc:
                import traceback as _tb
                _tb.print_exc()
                tui.boot_error(f"{type(exc).__name__}: {exc}")

        # 语言预置必须在 _boot 线程启动前、主线程同步完成 —— 否则 _boot 里的
        # ensure_language 会在 app.run() 全屏渲染期间用原生 input() 抢终端,
        # 导致"输入后卡死 + 二次启动渲染错乱"。见 _preselect_language 注释。
        _preselect_language()

        threading.Thread(target=_boot, name="tuan-boot", daemon=True).start()
        try:
            tui.run()
        except BaseException as exc:
            import traceback as _tb2
            _tb_text = _tb2.format_exc()
            _tb2.print_exc()
            # 把崩溃 traceback 落到日志文件, 方便在特殊终端下复现排查
            try:
                _crash_log = os.path.join(
                    os.path.expanduser("~"), ".tuan", "tui_crash.log")
                os.makedirs(os.path.dirname(_crash_log), exist_ok=True)
                with open(_crash_log, "w", encoding="utf-8") as _cf:
                    _cf.write(_tb_text)
                console.print(
                    f"[青小团] TUI 运行异常, 已回退到普通 REPL。\n"
                    f"          错误详情已保存到: {_crash_log}\n"
                    f"          请把该文件内容发我, 以便精准修复。")
            except Exception:
                console.print(
                    f"[青小团] TUI 运行异常, 已回退到普通 REPL: {exc}")
            # 兜底: 即便花哨 TUI 在特殊终端下崩溃, 也绝不静默闪退, 给用户可用的界面
            if state["agent"] is not None and state["config"] is not None:
                try:
                    _run_chat_repl(state["agent"], state["config"], workspace,
                                  state.get("mode", "standard"),
                                  state["config"].get("agent.effort", "high"),
                                  session_id=session_id)
                except Exception:
                    pass
        finally:
            if state["agent"] is not None:
                _run_session_hooks(state["agent"], "SessionEnd",
                                   {"workspace": workspace})
                _close_agent_session(state["agent"])
        return 0

    # 普通 REPL 模式
    prep = _prepare_agent(args, workspace, session_id)
    if prep is None:
        return 1
    kernel, config, agent, mode, effort = prep
    try:
        rc = _run_chat_repl(agent, config, workspace, mode, effort, session_id=session_id,
                            bare=bool(getattr(args, "bare", False)))
    finally:
        _run_session_hooks(agent, "SessionEnd", {"workspace": workspace})
        _close_agent_session(agent)
    return rc


def _close_agent_session(agent: Any) -> None:
    """会话结束（SessionEnd 之后）注销 hooks 会话槽，异常隔离。

    B3 续轮 IX（Q6）：上一轮 ``deactivate_session`` 在生产代码里
    **零调用点**，registry 只增不减；这里接上 CLI 主路径的两个
    finally（TUI 分支 + 普通 REPL 分支）。顺序刻意放在
    ``_run_session_hooks(..., "SessionEnd")`` **之后** —— SessionEnd
    钩子还要用 ``ctx.hooks``。

    如实边界：ACP server / web / stream_json / TUI.close 等宿主仍
    未接线，回归里逐项锁住，不宣称「全部宿主已覆盖」。
    """
    handle = getattr(getattr(agent, "ctx", None), "session_handle", None)
    if handle is None:
        return
    try:
        from ..hooks.triggers import deactivate_session
        deactivate_session(handle)
    except Exception:  # noqa: BLE001 - 关闭路径不得掀翻 CLI 退出
        pass


def _run_session_hooks(agent: Any, event: str, payload: Optional[Dict[str, Any]]) -> None:
    """触发会话级 Hooks (SessionStart/SessionEnd), 异常隔离、不影响主流程。"""
    ctx = getattr(agent, "ctx", None)
    hooks = getattr(ctx, "hooks", None) if ctx is not None else None
    if hooks is not None:
        try:
            hooks.run_session(event, payload)
        except Exception as exc:  # noqa: BLE001
            log.debug("会话钩子 %s 执行失败: %s", event, exc)


def _security_alerter(event: Any) -> None:
    """安全事件 -> 桌面实时告警 (吞异常, 绝不干扰主流程)。"""
    try:
        from ..ext.notify_engine import NotifyEngine
        eng = NotifyEngine()
        etype = str(event.event_type).split(".")[-1]
        cmd = (event.payload.get("command") or "")[:80]
        reason = event.payload.get("reason") or etype
        msg = f"{reason}: {cmd}" if cmd else reason
        eng.notify({"title": "青小团 · 安全事件", "message": msg})
    except Exception:  # noqa: BLE001
        pass


def _setup_security_alerts() -> None:
    """为安全事件总线注册桌面实时告警 (仅交互式会话启用, 测试不受影响)。

    默认把审计事件持久化到 ~/.tuan/security-audit.jsonl, 这样拦截 / 放行
    等关键安全事件落盘可追溯 (tuan safe status 可看到落盘路径)。
    """
    try:
        from ..config.loader import home_dir
        from ..core.security_bus import get_security_bus
        get_security_bus(persist_path=home_dir() / "security-audit.jsonl", async_alerter=True).set_alerter(
            _security_alerter
        )
    except Exception:  # noqa: BLE001
        pass


def _run_chat_repl(agent: Any, config: Config, workspace: str, mode: str, effort: str,
                   session_id: Optional[str] = None, bare: bool = False) -> int:
    """普通 REPL 对话循环 (cmd_chat 与 session resume 共用)。"""
    ui.banner(config, workspace, f"{config.get('model.provider')}/{config.get('model.model')}",
              mode=mode, effort=effort)
    # 安全多阶段确认的交互入口 (令牌 + 屏幕位置变化)
    agent.ctx.confirm = ui.confirm
    ui.status_bar(mode, effort, workspace)
    if not config.api_key():
        console.print(f"{t('chat.no_api_key')}")

    while True:
        try:
            user_input = ui.prompt()
        except (EOFError, KeyboardInterrupt):
            console.print("\n再见！")
            break
        if not user_input:
            continue
        if user_input.strip() in ("/exit", "/quit"):
            console.print("再见！")
            break
        if user_input.strip().startswith("/"):
            from .cmd_slash import _handle_slash
            _handle_slash(user_input.strip(), agent, config, workspace)
            ui.status_bar(mode, effort, workspace, plan=agent.plan_mode)
            continue
        if user_input.strip().startswith("!"):
            # `!` shell 快捷模式: 不经 LLM 直接执行, 结果自动注入下一轮上下文
            from .cmd_bang import run_bang_command
            run_bang_command(agent, user_input)
            ui.status_bar(mode, effort, workspace, plan=agent.plan_mode)
            continue
        # 四层边界: 若本轮结束触发自动交接, 用返回的新 session_id 接管后续轮次
        new_id = _run_turn(agent, user_input, config, session_id=session_id, bare=bare)
        if new_id:
            session_id = new_id
        ui.status_bar(mode, effort, workspace, plan=agent.plan_mode)

    return 0


def _run_turn(agent: Any, user_input: str, config: Config, stream: bool | None = None,
              session_id: Optional[str] = None, bare: bool = False) -> Optional[str]:
    """执行一轮对话 (模型 → 工具 → 观察 → 回答)。

    四层边界自动 hook (全部附加、可关、失败静默回退):
    - Worktree 层: 检测到并行实验意图自动开 worktree (非 git 仓库静默跳过);
    - Subagent 层: 重任务自动隔离执行, 失败回退主会话;
    - Chat 层: 本轮结束后若上下文超阈值, 自动交接并把新 session_id 返回给 REPL。

    返回: 若发生自动交接, 返回新 session_id (由调用方注入后续轮次); 否则 None。
    """
    # Rewind (A2): 每次用户输入前自动保存会话快照到 .tuan/snapshots/
    try:
        from ..core.rewind import RewindManager
        _ws = getattr(getattr(agent, "ctx", None), "workspace", None) or default_workspace()
        _sid = getattr(getattr(agent, "session", None), "session_id", "")
        RewindManager(_ws, config=config).snapshot(
            agent.messages, reason="user_input", session_id=_sid)
    except Exception:  # noqa: BLE001
        _ws = os.getcwd()

    # ---- 四层边界 · Worktree 层: 并行实验意图自动创建 worktree ----
    try:
        from ..core.boundary_auto import auto_create_parallel_worktree
        wt = auto_create_parallel_worktree(_ws, user_input, config=config, bare=bare)
        if wt is not None:
            console.print(f"[四层边界] 检测到并行实验意图, 已为你创建 worktree: {wt.path}")
    except Exception:  # noqa: BLE001
        pass

    # ---- 四层边界 · Subagent 层: 重任务自动隔离执行; 失败回退主会话 ----
    try:
        from ..core.boundary_auto import try_run_isolated
        isolated = try_run_isolated(agent, user_input, config=config, bare=bare)
    except Exception:  # noqa: BLE001
        isolated = None
    if isolated is not None:
        # 走了隔离通道: 把子代理摘要作为本轮回答展示, 不再 agent.run (主上下文不被污染)
        if config.get("ui.markdown", True):
            ui.answer_md(isolated)
        else:
            ui.info(isolated)
        console.print()
        return _maybe_auto_handoff(agent, config, _ws, session_id, bare=bare)

    def on_tool(name: str, arguments: str) -> None:
        ui.tool_call(name, _parse_args(arguments))

    answer = agent.run(
        user_input,
        stream=stream if stream is not None else config.get("model.stream", True),
        on_token=lambda t: ui.stream(t),
        on_tool=on_tool,
        on_reason=lambda r: ui.reason(r),
        on_tool_result=lambda n, r: ui.tool_result(n, r),
        on_error=lambda m: ui.error(m),
        session_id=session_id,
    )
    if answer:
        if config.get("ui.markdown", True):
            ui.answer_md(answer)
        else:
            ui.info(answer)
    else:
        console.print()
    ui.add_tokens(agent.total_usage.get("prompt_tokens", 0) + agent.total_usage.get("completion_tokens", 0))
    st = agent.context_stats()
    if st.get("budget_tokens"):
        ui.set_context_pct(st["estimated_tokens"] / st["budget_tokens"] * 100,
                           used=st["estimated_tokens"], budget=st["budget_tokens"])
    if config.get("ui.show_token_usage", True):
        ui.usage(agent.total_usage)
    console.print()
    return _maybe_auto_handoff(agent, config, _ws, session_id, bare=bare)


def _maybe_auto_handoff(agent: Any, config: Config, workspace: str,
                        session_id: Optional[str], bare: bool = False) -> Optional[str]:
    """本轮结束后检查是否达到交接阈值; 达阈值则自动交接并打印报告, 返回新 session_id。

    bare 模式跳过 (评测可复现); 任何异常静默返回 None, 不影响后续对话。
    """
    if bare:
        return None
    try:
        st = agent.context_stats()
        budget = int(st.get("budget_tokens", 0) or 0)
        estimated = int(st.get("estimated_tokens", 0) or 0)
        if budget <= 0:
            return None
        from ..core.chat_handoff import ChatHandoff
        # 项目 ID 取 .tuan/project.json (best-effort, 取不到为空串)
        try:
            from ..core.project_layer import ProjectLayer
            proj_id = ProjectLayer(workspace, config).info().project_id
        except Exception:  # noqa: BLE001
            proj_id = ""
        report = ChatHandoff(workspace, config=config).auto_handoff_if_needed(
            estimated, budget, session_id or "", agent.messages, project_id=proj_id)
        if report is None:
            return None
        console.print("\n[四层边界] 上下文已达交接阈值, 已自动交接:")
        console.print(f"  旧会话: {report.old_session_id}")
        console.print(f"  新会话: {report.new_session_id}")
        console.print(f"  摘要预览: {report.preview(200)}")
        return report.new_session_id
    except Exception:  # noqa: BLE001
        return None


def _parse_args(a: Any) -> Any:
    try:
        return json.loads(a)
    except Exception:
        return a


# ===================================================================== cmd_model
# cmd_model 及其辅助函数已拆分至 cmd_model.py (职责: 模型配置/热切换);
# 此处 re-export, 保持 `from .cmd_chat import _pick_model_interactive` 等既有引用不变。
from .cmd_model import (  # noqa: F401
    _ConfigOverride,
    _ellipsize,
    _model_local,
    _model_test,
    _model_update,
    _no_key_env,
    _offer_keep_original_config,
    _pick_api_key_interactive,
    _pick_model_interactive,
    _print_update_done,
    _show_provider_models,
    _strip_model_label,
    cmd_model,
)

# ===================================================================== cmd_doctor

def cmd_doctor(args: Any) -> int:
    """环境健康检查: 配置 / 依赖 / 引擎 / 网络 / 模型连通 / 工作区, 分级输出。"""
    issues: List[tuple] = []

    def mark(level: str) -> str:
        return {"ok": "✓", "warn": "!", "err": "✗"}[level]

    console.print("环境检查")
    console.print(f"  Python: {sys.version.split()[0]} ({sys.executable})")
    console.print(f"  版本: {__version__}")

    # ---- 依赖版本检查 ----
    console.print("\n依赖")
    dep_checks = [
        ("openai", "openai", "OpenAI 兼容传输层 (可选)"),
        ("yaml", "pyyaml", "YAML 配置解析"),
        ("rich", "rich", "终端 UI 渲染"),
        ("httpx", "httpx", "HTTP 客户端 (模型适配器)") ,
        ("prompt_toolkit", "prompt_toolkit", "交互式输入"),
    ]
    for mod_name, pkg_name, desc in dep_checks:
        try:
            mod = __import__(mod_name)
            ver = getattr(mod, "__version__", "?")
            console.print(f"  {mark('ok')} {pkg_name} {ver} — {desc}")
        except ImportError:
            # openai 为可选传输层 (OpenAI 兼容适配器惰性导入), 缺失仅提示不报错;
            # rich/httpx/prompt_toolkit 为核心 UI/HTTP 依赖, 缺失同样降级为警告而非致命错误。
            optional = pkg_name in ("rich", "httpx", "prompt_toolkit", "openai")
            level = "warn" if optional else "err"
            console.print(f"  {mark(level)} {pkg_name} 未安装 — {desc}" + (" (可选)" if optional else ""))
            if not optional:
                issues.append((level, pkg_name, f"未安装: {desc}"))

    try:
        kernel = build_kernel()
    except Exception as exc:  # noqa: BLE001
        console.print(f"启动失败: {exc}")
        return 1
    config = kernel.require("config")

    # ---- 配置健康 ----
    console.print("\n配置")
    for level, section, msg in _validate_config(config):
        console.print(f"  {mark(level)} {section}: {msg}")
        if level in ("warn", "err"):
            issues.append((level, section, msg))

    # ---- 引擎健康 ----
    console.print("\n引擎")
    try:
        from ..ext.registry import engine_healthcheck
        results = engine_healthcheck()
        ok_count = sum(1 for v in results.values() if v.get("ok"))
        for name, v in results.items():
            console.print(f"  {mark('ok' if v.get('ok') else 'err')} {name}")
        if ok_count < len(results):
            issues.append(("err", "engines", f"{ok_count}/{len(results)} 就绪"))
    except Exception:  # noqa: BLE001
        console.print("  ✗ 无法检测")
        issues.append(("err", "engines", "无法检测"))

    # ---- 网络连通 (urllib.request 替代 httpx, 零外部依赖) ----
    console.print("\n网络")
    base_url = config.get("model.base_url", "") or ""
    if not base_url:
        preset = get_provider(config.get("model.provider", ""))
        base_url = (preset.base_url if preset else "") or ""
    if base_url:
        host = base_url.split("//")[-1].split("/")[0]
        try:
            import urllib.request
            import ssl
            t0 = time.time()
            req = urllib.request.Request(base_url, method="HEAD")
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=3, context=ctx) as resp:
                resp.read()
            console.print(f"  {mark('ok')} {host} 可达 ({time.time() - t0:.0f}ms)")
        except Exception as exc:  # noqa: BLE001
            console.print(f"  {mark('warn')} {host} 不可达: {exc}")
            issues.append(("warn", "network", f"{host} 不可达"))
    else:
        console.print(f"  {mark('warn')} 未设置 base_url, 跳过网络检查")
        issues.append(("warn", "network", "未设置 base_url"))

    # ---- 模型连通 ----
    console.print("\n模型")
    if not config.api_key():
        console.print(f"  {mark('warn')} 未配置 API Key, 跳过连通性测试")
        issues.append(("warn", "model", "未配置 API Key"))
    else:
        provider = config.get("model.provider", "?")
        model = config.get("model.model", "?")
        try:
            from ..models import create_adapter
            adapter = create_adapter(config)
            t0 = time.time()
            adapter.chat([{"role": "user", "content": "ping"}], stream=False)
            console.print(f"  {mark('ok')} {provider}/{model} 连通 ({time.time() - t0:.1f}s)")
        except Exception as exc:  # noqa: BLE001
            console.print(f"  {mark('warn')} {provider}/{model} 连通失败: {exc}")
            issues.append(("warn", "model", f"{provider}/{model} 连通失败"))

    # ---- 工作区 git 状态 ----
    console.print("\n工作区")
    workspace = getattr(args, "workspace", None) or default_workspace()
    try:
        r = subprocess.run(
            ["git", "-C", workspace, "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            dirty = len([l for l in r.stdout.splitlines() if l.strip()])
            console.print(f"  {mark('ok')} git 仓库 ({'有未提交改动' if dirty else '干净'})")
        else:
            console.print(f"  {mark('warn')} 非 git 仓库")
            issues.append(("warn", "workspace", "非 git 仓库"))
    except Exception:  # noqa: BLE001
        console.print(f"  {mark('warn')} git 检测失败")
        issues.append(("warn", "workspace", "git 检测失败"))

    # ---- 磁盘空间 ----
    console.print("\n磁盘")
    try:
        import shutil
        usage = shutil.disk_usage(home_dir())
        free_gb = usage.free / (1024**3)
        total_gb = usage.total / (1024**3)
        pct = (usage.free / usage.total) * 100
        level = "ok" if pct > 10 else ("warn" if pct > 5 else "err")
        console.print(f"  {mark(level)} {free_gb:.1f}GB 可用 / {total_gb:.1f}GB 总计 ({pct:.0f}%)")
        if pct <= 5:
            issues.append((level, "disk", f"磁盘空间不足: {free_gb:.1f}GB"))
    except Exception:  # noqa: BLE001
        console.print(f"  {mark('warn')} 无法检测磁盘空间")

    # ---- 汇总 ----
    errs = [i for i in issues if i[0] == "err"]
    warns = [i for i in issues if i[0] == "warn"]
    if errs:
        console.print(f"\n发现 {len(errs)} 个错误, {len(warns)} 个警告")
        return 1
    if warns:
        console.print(f"\n发现 {len(warns)} 个警告")
        return 0
    console.print("\n全部正常 ✓")
    return 0


# ===================================================================== 模式覆盖辅助

# 推理投入档位顺序 (低→高), 用于 maxEffortLevel 截断比较
_EFFORT_ORDER = ["low", "medium", "high", "xhigh", "max"]


def clamp_effort(config: Any, desired: Optional[str]) -> Optional[str]:
    """按 agent.max_effort_level 截断 desired effort (对标 Claude Code maxEffortLevel)。

    - desired 为空/None: 返回 None (无需设置);
    - 档位高于 max_effort_level: 返回 max_effort_level (截断);
    - 合法且未超限: 返回原值。
    """
    if not desired:
        return None
    d = str(desired).strip().lower()
    if d not in _EFFORT_ORDER:
        return None  # 非法值交由校验层报错
    cap = str(config.get("agent.max_effort_level", "max")).strip().lower()
    if cap not in _EFFORT_ORDER:
        return d  # 配置非法时不做截断 (校验层负责报错)
    if _EFFORT_ORDER.index(d) > _EFFORT_ORDER.index(cap):
        return cap
    return d


def _apply_fallback_model(config: Any, raw: Optional[str]) -> None:
    """接线 --fallback-model 到 model.fallbacks (对标 Claude Code fallbackModel)。

    支持逗号分隔多值, 如 ``--fallback-model "openai/gpt-4o,anthropic/claude-3-5"``。
    单个值可写 "provider/model" 或 dict 风格 (不解析 JSON, 简单 provider/model)。
    空值/None 不修改; 追加到现有 model.fallbacks 之后 (显式 CLI 优先覆盖)。
    """
    if not raw:
        return
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    if not parts:
        return
    # CLI 显式指定: 整体替换 (而非追加), 保证确定性
    config.set_user("model.fallbacks", parts[:3])


def _apply_mode_override(kernel: Any, mode: Optional[str], yes: bool = False) -> str:
    """应用模式覆盖 (不写用户配置, 避免污染后续启动)。

    旧三档体系 (standard/yolo/plan) 向后兼容; 新五模式通过 switch_mode 走 TUI/Web。
    ``--permission-mode auto`` 是内部标记 (对标 Claude Code Auto Mode): 不写入
    ``mode.default`` (避免污染五模式体系校验), 由调用方读取返回的 ``"auto"`` 设置
    ``agent.ctx.auto_mode``。返回值为字符串, 供调用方分派。
    """
    if yes:
        effective = "yolo"
    elif mode:
        effective = mode
    else:
        # 读取原始配置值 (不经过五模式别名解析), 保持旧三档兼容
        config = kernel.require("config")
        mode_data = config.get("mode", {}) or {}
        effective = str(mode_data.get("default") or "standard")
    # auto 是内部标记, 不写入 mode.default (避免五模式校验拒绝), 原样返回。
    if effective == "auto":
        return "auto"
    if effective != str(kernel.require("config").get("mode", {}).get("default", "standard")):
        config = kernel.require("config")
        config.data.setdefault("mode", {})["default"] = effective
    return effective


_PERMISSION_MODE_MAP = {
    # Claude Code 权限模式 -> 青小团内部模式
    "default": "standard",
    "acceptEdits": "standard",
    "plan": "plan",
    "auto": "auto",              # Auto 模式 (对标 Claude Code): 分类器按风险分级, 安全操作自动批准
    "dontAsk": "yolo",
    "bypassPermissions": "yolo",
}


def resolve_mode_from_permission(args: Any) -> Optional[str]:
    """根据 --permission-mode 推导内部模式; 显式 --mode 优先。返回 None 表示无需覆盖。"""
    pm = getattr(args, "permission_mode", None)
    if pm:
        return _PERMISSION_MODE_MAP.get(pm, "standard")
    return None
