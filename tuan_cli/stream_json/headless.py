"""持久 stdin 循环驱动器（headless 域）—— TS runHeadlessStreaming 的 Python 转写。

职责
----
1. 启动即发射 ``system/init``（壳收到后才标记引擎就绪）。
2. 持久 stdin 循环：按 ``\\n`` 切 NDJSON 行，``parse_input_line`` 容错；
   每收到一条 ``user`` 消息在**后台线程**跑 ``agent.run``（同步阻塞放后台，
   主线程守 stdin）。
3. turn 状态机：等待输入 → 运行中 → result 扣住（heldBack）等流式事件全部
   flush 完 → 发射 ``result``（壳收到后才结束 turn）。
4. ``install_stdout_guard``：协议模式下把所有非协议 stdout 写导流到 stderr，
   保证壳按行切 stdout 时永远只看到合法 NDJSON（在第一条协议写之前安装）。
5. SIGINT / stdin EOF 优雅退出（在途 turn 的 result 等 flush 完再退）。

Python >= 3.10（禁 3.11+ 语法）；不引入第三方依赖。
"""

from __future__ import annotations
from ..paths import default_workspace

import os
import sys
import threading
import time
import uuid as _uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .. import __version__
from .schema import ResultMessage, SystemInitMessage, encode_message, parse_input_line
from .translate import StreamTranslator, make_callbacks


# ---------------------------------------------------------------------------
# stdout 护栏
# ---------------------------------------------------------------------------


class _StdoutGuard:
    """非协议 stdout 写导流到 stderr；协议写经 ``protocol_write`` 直写真 stdout。

    对齐 TS ``installStreamJsonStdoutGuard``：任何 stray print / 库 banner /
    debug 输出若落到 ``sys.stdout``，都会被改道 stderr，绝不污染 NDJSON 流。
    """

    def __init__(self, real: Any, err: Any) -> None:
        self.real = real
        self.err = err
        self.lock = threading.Lock()
        self._depth = 0

    # -- 被替换到 sys.stdout 上的常规写入口（全部导流） --

    def write(self, s: str) -> int:
        with self.lock:
            if self._depth > 0:
                return int(self.real.write(s))
            try:
                return int(self.err.write(s))
            except Exception:  # noqa: BLE001
                return 0

    def writelines(self, lines: Any) -> None:
        with self.lock:
            target = self.real if self._depth > 0 else self.err
            try:
                target.writelines(lines)
            except Exception:  # noqa: BLE001
                pass

    def flush(self) -> None:
        with self.lock:
            target = self.real if self._depth > 0 else self.err
            try:
                target.flush()
            except Exception:  # noqa: BLE001
                pass

    # -- 协议写唯一通道：持锁、置位、直写真 stdout、flush、复位 --

    def protocol_write(self, line: str) -> None:
        with self.lock:
            self._depth += 1
            try:
                self.real.write(line + "\n")
                self.real.flush()
            finally:
                self._depth -= 1

    # -- 兼容属性转发（print() 等会探测 encoding/isatty） --

    def __getattr__(self, name: str) -> Any:
        return getattr(self.real, name)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass
class HeadlessConfig:
    """run_headless 的入参（字段对齐壳的 argv）。"""

    input_format: str = "stream-json"
    output_format: str = "stream-json"
    verbose: bool = False
    include_partial_messages: bool = True
    permission_mode: str = "bypassPermissions"
    permission_prompt_tool: Optional[str] = None
    add_dir: Optional[str] = None
    model: Optional[str] = None
    bare: bool = False  # CI/纯净模式（不读用户 config.yaml / 不挂 MCP）
    # 非 bypassPermissions 模式下的权限闸门策略。
    # True (默认, fail-closed): 拒绝 —— headless 没有交互终端, 也没有 control_request
    #   RPC 可回问壳, 默认放行等于"看起来在检查、其实什么都没拦"。
    # False (legacy): 放行并写一行 stderr —— 仅当壳侧已自行把关时用它恢复旧行为。
    fail_closed_on_permission: bool = True
    # ---- 壳固定追加的 argv（不报错、尽量生效）----
    thinking_enabled: bool = False
    resume_session_id: Optional[str] = None  # 壳 --resume <session_id>
    resume_session_at: Optional[str] = None  # 壳 --resume-session-at <uuid>
    append_system_prompt: Optional[str] = None  # 壳 --append-system-prompt <text>


# ---------------------------------------------------------------------------
# 驱动器
# ---------------------------------------------------------------------------


class HeadlessDriver:
    """单进程 = 单会话；一个 session_id 贯穿所有 turn。"""

    def __init__(self, config: HeadlessConfig) -> None:
        self.config = config
        # 壳续作（--resume <session_id>）时沿用同一 session_id，落同一会话流；
        # 新会话才生成全新 id。
        self.session_id = config.resume_session_id or _uuid.uuid4().hex
        self._guard: Optional[_StdoutGuard] = None
        self._kernel: Any = None
        self._agent: Any = None
        self._workspace: str = os.getcwd()
        self._model_name: str = config.model or "unknown"
        self._running = False
        self._worker: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ 信封发射

    def _emit(self, envelope: Any) -> None:
        """线程安全地写一条 NDJSON 信封（dataclass 或 dict）。"""
        assert self._guard is not None, "stdout 护栏尚未安装"
        line = encode_message(envelope)
        self._guard.protocol_write(line)

    # ------------------------------------------------------------------ 启动

    def _install_guard(self) -> None:
        """在第一条协议写之前安装：此后 bootstrap 期间的所有 stray 输出都进 stderr。"""
        real = sys.stdout
        try:
            real.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
        self._guard = _StdoutGuard(real, sys.stderr)
        sys.stdout = self._guard

    def _make_confirm(self) -> Any:
        """权限闸门回调。bypassPermissions 直接放行；其余模式默认拒绝 (fail-closed)。

        headless 进程没有交互终端, 也没有 control_request RPC 回问壳, 所以
        default/plan/acceptEdits 模式下「打一行 stderr 然后继续放行」等于把护栏
        做成了摆设 —— 用户以为在检查权限, 实际什么都没拦。这里改为默认拒绝,
        并给出可行动的说明; 只有壳侧已自行把关时才用
        ``fail_closed_on_permission=False`` 恢复旧的放行行为。

        TODO(EC-6): default/plan 模式应经 control_request RPC 向壳请求权限,
        届时 fail-closed 可降级为「等待壳回包」。
        """
        if self.config.permission_mode == "bypassPermissions":
            return lambda question: True

        fail_closed = getattr(self.config, "fail_closed_on_permission", True)

        def _ask(question: str) -> bool:
            if fail_closed:
                sys.stderr.write(
                    f"[headless] 权限请求被拒绝 (permission_mode={self.config.permission_mode!r}, "
                    "fail-closed): "
                    f"{question!r} — 需要交互式批准; 用 --permission-mode bypassPermissions "
                    "或在 HeadlessConfig 设 fail_closed_on_permission=False 放行\n"
                )
                return False
            sys.stderr.write(
                f"[headless] 权限请求 {question!r} — 非 bypassPermissions 模式"
                "按 fail_closed_on_permission=False 放行（TODO EC-6: control_request RPC）\n"
            )
            return True

        return _ask

    def _bootstrap(self) -> None:
        from ..app import build_kernel, create_agent

        kernel = build_kernel(bare=self.config.bare)
        config = kernel.require("config")

        # --model 覆盖：内存层补丁 + 重建模型适配器（不落盘）。
        if self.config.model:
            from ..models.plugin import ModelPlugin

            ModelPlugin.switch_model(kernel, {"model": self.config.model})
            self._model_name = self.config.model
        else:
            self._model_name = config.get("model.model", "unknown")

        workspace = self.config.add_dir or default_workspace()
        os.makedirs(workspace, exist_ok=True)

        agent = create_agent(
            kernel,
            workspace,
            confirm=self._make_confirm(),
            system_extra=self.config.append_system_prompt or "",
        )
        self._kernel = kernel
        self._agent = agent
        self._workspace = workspace
        # 运行时 adapter 可能带更准确的模型名
        adapter = getattr(agent, "model", None)
        self._model_name = getattr(adapter, "model_name", "") or self._model_name

    def _send_init(self) -> None:
        """发射 system/init —— 壳收到才标记引擎就绪。"""
        tools: List[str] = []
        try:
            tools = sorted(t.name for t in self._agent.registry.tools_for())
        except Exception:  # noqa: BLE001
            pass

        slash_commands: List[str] = []
        try:
            from ..cli.cmd_help import all_commands_metadata

            meta = all_commands_metadata()
            slash_commands = [str(c.get("name")) for c in meta
                              if isinstance(c, dict) and c.get("name")]
        except Exception:  # noqa: BLE001
            pass

        self._emit(SystemInitMessage(
            cwd=os.path.abspath(self._workspace),
            session_id=self.session_id,
            tools=tools,
            mcp_servers=[],
            model=self._model_name,
            permission_mode=self.config.permission_mode,
            slash_commands=slash_commands,
            api_key_source="stored-credential",
            claude_code_version=__version__,
            output_style="default",
            uuid=str(_uuid.uuid4()),
            agents=[],
            skills=[],
            plugins=[],
        ))

    # ------------------------------------------------------------------ usage 归集

    def _collect_usage(self) -> Dict[str, int]:
        """从 agent 累计用量拼 Anthropic 形状 usage。"""
        raw: Dict[str, int] = getattr(self._agent, "total_usage", {}) or {}
        return {
            "input_tokens": int(raw.get("prompt_tokens", 0) or 0),
            "output_tokens": int(raw.get("completion_tokens", 0) or 0),
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }

    def _model_usage(self, usage: Dict[str, int], cost: float) -> Dict[str, Dict[str, Any]]:
        """result.modelUsage：per-model 明细（coreSchemas ModelUsageSchema）。"""
        return {
            self._model_name: {
                "inputTokens": usage["input_tokens"],
                "outputTokens": usage["output_tokens"],
                "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 0,
                "webSearchRequests": 0,
                "costUSD": cost,
                "contextWindow": 0,
                "maxOutputTokens": 0,
            }
        }

    # ------------------------------------------------------------------ turn

    @staticmethod
    def _extract_text(message: Any) -> str:
        """从输入信封的 message 里抽出纯文本（兼容 str / 内容块列表）。"""
        if message is None:
            return ""
        if isinstance(message, str):
            return message
        content = message.get("content") if isinstance(message, dict) else message
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
            return "".join(parts)
        return str(content) if content is not None else ""

    def _turn(self, prompt_text: str) -> None:
        """后台线程：跑一个 turn，结束后发射 heldBack result。"""
        translator = StreamTranslator(
            emit=self._emit,
            session_id=self.session_id,
            model=self._model_name,
            include_partial_messages=self.config.include_partial_messages,
        )
        started = time.perf_counter()
        answer = ""
        is_error = False
        try:
            translator.begin_turn()
            answer = self._agent.run(
                prompt_text,
                stream=True,
                session_id=self.session_id,
                **make_callbacks(translator),
            ) or ""
        except Exception as exc:  # noqa: BLE001
            is_error = True
            translator.on_error(f"{type(exc).__name__}: {exc}")

        usage = self._collect_usage()
        cost = 0.0
        try:
            cost = float(self._agent._estimate_total_cost() or 0.0)
        except Exception:  # noqa: BLE001
            cost = 0.0
        num_turns = int(getattr(self._agent, "turn_count", 1) or 1)
        duration_ms = (time.perf_counter() - started) * 1000.0

        # heldBack: 先把流式/transcript 事件 flush 完，再发 result。
        translator.finish_turn(
            answer,
            stop_reason="error" if is_error else "end_turn",
            output_tokens=usage["output_tokens"],
        )

        if is_error:
            self._emit(ResultMessage(
                subtype="error_during_execution",
                duration_ms=duration_ms,
                duration_api_ms=duration_ms,
                is_error=True,
                num_turns=num_turns,
                total_cost_usd=cost,
                usage=usage,
                model_usage=self._model_usage(usage, cost),
                uuid=str(_uuid.uuid4()),
                session_id=self.session_id,
                stop_reason=None,
                errors=translator.errors or ["未知错误"],
            ))
        else:
            self._emit(ResultMessage(
                subtype="success",
                duration_ms=duration_ms,
                duration_api_ms=duration_ms,
                is_error=False,
                num_turns=num_turns,
                result=answer,
                stop_reason="end_turn",
                total_cost_usd=cost,
                usage=usage,
                model_usage=self._model_usage(usage, cost),
                permission_denials=[],
                uuid=str(_uuid.uuid4()),
                session_id=self.session_id,
            ))

    def _turn_wrapper(self, prompt_text: str) -> None:
        try:
            self._turn(prompt_text)
        finally:
            self._running = False

    # ------------------------------------------------------------------ 主循环

    def serve(self) -> int:
        # 1. 护栏必须在第一条协议写之前安装（TS: installStreamJsonStdoutGuard）。
        self._install_guard()

        # 2. 装配内核/Agent（期间所有 stray stdout 自动导流 stderr）。
        try:
            self._bootstrap()
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"[headless] 启动失败: {type(exc).__name__}: {exc}\n")
            self._emit(ResultMessage(
                subtype="error_during_execution",
                duration_ms=0.0, duration_api_ms=0.0, is_error=True,
                num_turns=0, total_cost_usd=0.0,
                usage={"input_tokens": 0, "output_tokens": 0,
                       "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
                model_usage={},
                uuid=str(_uuid.uuid4()), session_id=self.session_id,
                stop_reason=None, errors=[f"{type(exc).__name__}: {exc}"],
            ))
            return 1

        # 3. system/init —— 壳就绪信号。
        self._send_init()

        # 4. 持久 stdin 循环：行缓冲（sys.stdin 文本迭代自动按 \n 切行，
        #    EOF 残行也会被吐出），parse_input_line 容错。
        try:
            for raw in sys.stdin:
                msg = parse_input_line(raw)
                if msg is None:
                    continue
                if msg.get("type") != "user":
                    continue
                prompt_text = self._extract_text(msg.get("message"))
                if not prompt_text.strip():
                    continue
                if self._running:
                    # 壳是 result-gated 的（收到 result 才发下一条 user）。
                    # 防御式告警，不丢线程状态。
                    sys.stderr.write("[headless] 上一 turn 尚未结束，丢弃多余 user 消息\n")
                    continue
                self._running = True
                self._worker = threading.Thread(
                    target=self._turn_wrapper, args=(prompt_text,), daemon=True
                )
                self._worker.start()
        except KeyboardInterrupt:
            # SIGINT: 尝试取消在途 turn，等其 flush 完再退出。
            sys.stderr.write("[headless] 收到中断信号，退出中...\n")
            agent = self._agent
            if agent is not None and hasattr(agent, "cancel"):
                try:
                    agent.cancel()
                except Exception:  # noqa: BLE001
                    pass
        finally:
            # EOF / 中断：在途 turn 的 result 必须 flush 完再退。
            if self._worker is not None:
                self._worker.join(timeout=60.0)
            # B3 续轮 X（R3）：headless 驱动器的明确退出出口注销会话槽。
            try:
                from ..hooks.triggers import close_agent_session
                close_agent_session(getattr(self, "_agent", None))
            except Exception:  # noqa: BLE001 - 退出路径不得被关闭动作掀翻
                pass
        return 0


def run_headless(config: HeadlessConfig) -> int:
    """headless 驱动器入口。"""
    return HeadlessDriver(config).serve()
