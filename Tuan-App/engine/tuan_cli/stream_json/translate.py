"""内部流 → Anthropic 形状信封翻译层（headless 域）。

把青小团 ``agent.run(..., on_token=..., on_reason=..., on_tool=...,
on_tool_result=..., on_error=...)`` 的内部回调流，翻译为 Claude Code
stream-json 线协议的信封序列：

* on_token(delta)      → content_block_start(text) / content_block_delta
                         (text_delta) / content_block_stop（块边界时）
* on_reason(delta)     → thinking 块同构流（thinking_delta）
* on_tool(name,args)   → content_block_start(tool_use{id,name,input:dict})
                         + content_block_stop，并紧接着发射一条完整的
                         ``assistant``  transcript 信封（content=[text?, tool_use]）
* on_tool_result()     → 一条 ``user`` transcript 信封，content=[tool_result]
* usage                → 翻译层不直接写 usage；由 headless 在读 agent 累计
                         用量后拼装进 ``result``（见 headless.turn_worker）

设计要点（对齐 TS QueryEngine.ts:788-828 的事件门控语义）：
* ``stream_event`` 信封仅在 ``include_partial_messages=True`` 时发射；
  ``assistant`` / ``user`` transcript 信封始终发射（它们是对话记录，
  不是增量流）。
* 块索引 ``index`` 从 0 单调递增，与 Anthropic 流式协议一致。
* 所有回调均为异常吸收（翻译层 bug 绝不允许打穿 agent 后台线程）：
  翻译失败时降级为 stderr 诊断，turn 继续。

Python >= 3.10（禁 3.11+ 语法）；不引入第三方依赖。
"""

from __future__ import annotations

import json
import sys
import uuid as _uuid
from typing import Any, Callable, Dict, List, Optional

from .schema import (
    AssistantMessage,
    StreamEventMessage,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

# 信封发射器: (envelope: dataclass|dict) -> None。由 headless 注入，
# 内部已做线程锁 + encode_message + stdout flush。
Emitter = Callable[[Any], None]


class StreamTranslator:
    """单个 turn 的翻译器（一次性，每个 turn 新建一个实例）。

    Parameters
    ----------
    emit:
        线程安全信封发射器（headless 提供）。
    session_id:
        本会话 id（所有信封的 ``session_id``）。
    model:
        当前模型名（写入 message_start）。
    include_partial_messages:
        是否发射 ``stream_event`` 增量信封（TS 的 --include-partial-messages）。
    """

    def __init__(
        self,
        emit: Emitter,
        session_id: str,
        model: str,
        include_partial_messages: bool = True,
    ) -> None:
        self._emit = emit
        self.session_id = session_id
        self._model = model or "unknown"
        self._partial = include_partial_messages

        # --- 流式块状态机 ---
        self._block_index = -1
        self._open_kind: Optional[str] = None  # None | "text" | "thinking"
        # 当前 assistant 段尚未收尾的内容块（dict 列表，直接 to_dict 友好）
        self._pending: List[Dict[str, Any]] = []
        # 最近一次 on_tool 分配的 tool_use_id（on_tool_result 无 id，按序消费）
        self._last_tool_id: Optional[str] = None
        # 错误收集（on_error）
        self.errors: List[str] = []
        # 统计
        self.num_assistant_msgs = 0
        self.num_user_msgs = 0
        self.started = False

    # ------------------------------------------------------------------ 内部

    def _uid(self) -> str:
        return str(_uuid.uuid4())

    def _safe_emit(self, envelope: Any) -> None:
        """发射信封，但翻译层自身异常永远不外抛。"""
        try:
            self._emit(envelope)
        except Exception as exc:  # noqa: BLE001 - 翻译层故障不得打穿 turn
            try:
                sys.stderr.write(f"[stream_json.translate] emit 失败: {exc!r}\n")
                sys.stderr.flush()
            except Exception:  # noqa: BLE001
                pass

    def _stream_event(self, event: Dict[str, Any],
                      parent_tool_use_id: Optional[str] = None) -> None:
        if not self._partial:
            return
        self._safe_emit(StreamEventMessage(
            event=event,
            uuid=self._uid(),
            session_id=self.session_id,
            parent_tool_use_id=parent_tool_use_id,
        ))

    def _close_open_block(self) -> None:
        """若有开启的流式块，发射 content_block_stop 并复位。"""
        if self._open_kind is not None:
            self._stream_event({
                "type": "content_block_stop",
                "index": self._block_index,
            })
            self._open_kind = None

    def _start_block(self, kind: str) -> None:
        """开启一个新的 text/thinking 流式块（先关掉旧块）。"""
        self._close_open_block()
        self._block_index += 1
        if kind == "text":
            block: Dict[str, Any] = {"type": "text", "text": ""}
        else:
            block = {"type": "thinking", "thinking": ""}
        self._stream_event({
            "type": "content_block_start",
            "index": self._block_index,
            "content_block": block,
        })
        self._pending.append(block)
        self._open_kind = kind

    # ------------------------------------------------------------------ turn 生命周期

    def begin_turn(self) -> None:
        """turn 开始：发射 message_start（仅 partial 模式）。"""
        self.started = True
        self._stream_event({
            "type": "message_start",
            "message": {
                "id": "msg_" + self._uid().replace("-", "")[:24],
                "type": "message",
                "role": "assistant",
                "model": self._model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 0},
            },
        })

    # ------------------------------------------------------------------ 回调（挂 agent.run）

    def on_token(self, delta: str) -> None:
        """文本增量。"""
        if not delta:
            return
        try:
            if self._open_kind != "text":
                self._start_block("text")
            self._stream_event({
                "type": "content_block_delta",
                "index": self._block_index,
                "delta": {"type": "text_delta", "text": delta},
            })
            # 追加进当前 pending 文本块（末尾块必然是 text，因 _start_block 刚追过）
            if self._pending and self._pending[-1]["type"] == "text":
                self._pending[-1]["text"] += delta
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"[translate.on_token] {exc!r}\n")

    def on_reason(self, delta: str) -> None:
        """思维链增量（thinking_delta）。"""
        if not delta:
            return
        try:
            if self._open_kind != "thinking":
                self._start_block("thinking")
            self._stream_event({
                "type": "content_block_delta",
                "index": self._block_index,
                "delta": {"type": "thinking_delta", "thinking": delta},
            })
            if self._pending and self._pending[-1]["type"] == "thinking":
                self._pending[-1]["thinking"] += delta
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"[translate.on_reason] {exc!r}\n")

    def on_tool(self, name: str, args_str: str) -> None:
        """模型发起一次工具调用：tool_use 块 + 随后完整 assistant 信封。"""
        try:
            parsed: Dict[str, Any]
            try:
                parsed = json.loads(args_str) if args_str else {}
                if not isinstance(parsed, dict):
                    parsed = {"value": parsed}
            except (ValueError, TypeError):
                parsed = {"_raw": args_str}

            tid = "toolu_" + self._uid().replace("-", "")[:24]
            self._last_tool_id = tid

            # 结束正在流式的文本/思维块
            self._close_open_block()
            self._block_index += 1
            self._stream_event({
                "type": "content_block_start",
                "index": self._block_index,
                "content_block": {
                    "type": "tool_use",
                    "id": tid,
                    "name": name,
                    "input": parsed,
                },
            })
            self._stream_event({
                "type": "content_block_stop",
                "index": self._block_index,
            })

            # 组装完整 assistant 信封：此前累积的文本/思维块 + 本次 tool_use
            content: List[Any] = list(self._pending)
            content.append(ToolUseBlock(id=tid, name=name, input=parsed).to_dict())
            self._safe_emit(AssistantMessage(
                content=content,
                uuid=self._uid(),
                session_id=self.session_id,
            ))
            self.num_assistant_msgs += 1
            # 复位 pending：下一个 assistant 段重新累积
            self._pending = []
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"[translate.on_tool] {exc!r}\n")

    def on_tool_result(self, name: str, result: str) -> None:
        """工具执行结果：user{content:[tool_result]} 信封。"""
        try:
            tid = self._last_tool_id
            self._last_tool_id = None
            self._safe_emit(UserMessage(
                content=[ToolResultBlock(
                    tool_use_id=tid or "toolu_unknown",
                    content=result if result is not None else "",
                    is_error=False,
                ).to_dict()],
                uuid=self._uid(),
                session_id=self.session_id,
            ))
            self.num_user_msgs += 1
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"[translate.on_tool_result] {exc!r}\n")

    def on_error(self, message: str) -> None:
        """agent.run 报告的非致命错误。"""
        if message:
            self.errors.append(str(message))

    # ------------------------------------------------------------------ turn 收尾

    def finish_turn(self, answer: str,
                    stop_reason: str = "end_turn",
                    output_tokens: int = 0) -> None:
        """turn 收尾：把悬挂的 assistant 段发出，并打 message_delta/message_stop。

        Parameters
        ----------
        answer:
            agent.run 的最终回答（可能为空串 —— 纯工具轮没有文本）。
        stop_reason:
            Anthropic 风格 stop_reason。
        output_tokens:
            本 turn 估算 output_tokens（写进 message_delta.usage）。
        """
        try:
            self._close_open_block()
            # pending 里仍有文本/思维块（模型没调工具就收尾）：发完整 assistant 信封。
            if self._pending:
                content = list(self._pending)
                self._safe_emit(AssistantMessage(
                    content=content,
                    uuid=self._uid(),
                    session_id=self.session_id,
                ))
                self.num_assistant_msgs += 1
                self._pending = []
            elif answer:
                # agent.run 返回了文本但 on_token 流里没有（非 stream 路径兜底）：
                # 用 answer 补一条文本块，避免 transcript 空缺。
                self._safe_emit(AssistantMessage(
                    content=[{"type": "text", "text": answer}],
                    uuid=self._uid(),
                    session_id=self.session_id,
                ))
                self.num_assistant_msgs += 1

            self._stream_event({
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": int(output_tokens or 0)},
            })
            self._stream_event({"type": "message_stop"})
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"[translate.finish_turn] {exc!r}\n")


def make_callbacks(t: StreamTranslator) -> Dict[str, Any]:
    """把翻译器包装成 agent.run 的 kwargs（on_token/on_reason/on_tool/...）。"""
    return {
        "on_token": t.on_token,
        "on_reason": t.on_reason,
        "on_tool": t.on_tool,
        "on_tool_result": t.on_tool_result,
        "on_error": t.on_error,
    }
