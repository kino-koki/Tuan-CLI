"""Python port of the Claude Code TS ``stream-json`` wire protocol: message
schemas + NDJSON serialization layer.

This module is the frozen public API for the "stream-json adaptation layer"
first milestone. The electron/bridge-server shell pulls stdout apart on ``\\n``,
treats a ``system/init`` line as "engine ready" and a ``result`` line as
"turn over". Every wire key below is copied *byte-for-byte* from the TypeScript
source of truth::

    claude-desktop-app/engine/src/entrypoints/sdk/coreSchemas.ts
    claude-desktop-app/engine/src/cli/ndjsonSafeStringify.ts
    claude-desktop-app/engine/src/utils/messages/systemInit.ts

Conventions
-----------
* Dataclasses take **snake_case** Python parameters (per the frozen contract).
  Where the wire uses camelCase (``permissionMode``, ``apiKeySource``,
  ``modelUsage``), :meth:`to_dict` rewrites the key — see each class docstring.
* Optional fields default to ``None`` and are **omitted** from ``to_dict()``.
* Nullable wire fields (e.g. ``stop_reason``, ``status``, ``error_status``) are
  emitted as JSON ``null`` when the caller passes ``None`` — matching
  ``z.string().nullable()``.
* ``encode_message`` mirrors ``ndjsonSafeStringify``: ``json.dumps`` with
  ``ensure_ascii=False``, then a literal replace of U+2028 / U+2029 so a
  line-splitting receiver can never cut a line mid-string.

Python >= 3.10 (no 3.11+ syntax). No third-party dependencies.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any, Dict, List, Optional

__all__ = [
    # content blocks
    "TextBlock",
    "ThinkingBlock",
    "ToolUseBlock",
    "ToolResultBlock",
    # envelope messages
    "SystemInitMessage",
    "SystemCompactBoundaryMessage",
    "SystemTaskMessage",
    "SystemStatusMessage",
    "SystemApiRetryMessage",
    "StreamEventMessage",
    "AssistantMessage",
    "UserMessage",
    "ResultMessage",
    # serialization / parsing
    "encode_message",
    "parse_input_line",
]


# ---------------------------------------------------------------------------
# Content blocks (Anthropic message shape; raw dicts pass through untouched)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class TextBlock:
    """``{"type":"text","text":...}`` content block."""

    text: str

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "text", "text": self.text}


@dataclasses.dataclass
class ThinkingBlock:
    """``{"type":"thinking","thinking":...}`` extended-thinking block."""

    thinking: str

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "thinking", "thinking": self.thinking}


@dataclasses.dataclass
class ToolUseBlock:
    """``{"type":"tool_use","id","name","input"}`` assistant tool-use block."""

    id: str
    name: str
    input: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "tool_use",
            "id": self.id,
            "name": self.name,
            "input": self.input,
        }


@dataclasses.dataclass
class ToolResultBlock:
    """``{"type":"tool_result",...}`` block living *inside* a user message."""

    tool_use_id: str
    content: Any
    is_error: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": self.tool_use_id,
            "content": self.content,
        }
        if self.is_error is not None:
            d["is_error"] = self.is_error
        return d


# ---------------------------------------------------------------------------
# system/* messages
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class SystemInitMessage:
    """``{type:"system", subtype:"init", ...}`` — first message, marks ready.

    Wire keys (coreSchemas SDKSystemMessageSchema): ``permissionMode`` and
    ``apiKeySource`` are camelCase on the wire. ``agents``/``skills``/``plugins``
    may be empty lists but are omitted when left ``None``.
    """

    cwd: str
    session_id: str
    tools: List[str]
    mcp_servers: List[Dict[str, Any]]
    model: str
    permission_mode: str
    slash_commands: List[str]
    api_key_source: str
    claude_code_version: str
    output_style: str
    uuid: str
    agents: Optional[List[str]] = None
    skills: Optional[List[str]] = None
    plugins: Optional[List[Dict[str, Any]]] = None
    betas: Optional[List[str]] = None
    fast_mode_state: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "type": "system",
            "subtype": "init",
            "cwd": self.cwd,
            "session_id": self.session_id,
            "tools": list(self.tools),
            "mcp_servers": list(self.mcp_servers),
            "model": self.model,
            "permissionMode": self.permission_mode,
            "slash_commands": list(self.slash_commands),
            "apiKeySource": self.api_key_source,
            "claude_code_version": self.claude_code_version,
            "output_style": self.output_style,
            "uuid": self.uuid,
        }
        if self.agents is not None:
            d["agents"] = list(self.agents)
        if self.skills is not None:
            d["skills"] = list(self.skills)
        if self.plugins is not None:
            d["plugins"] = list(self.plugins)
        if self.betas is not None:
            d["betas"] = list(self.betas)
        if self.fast_mode_state is not None:
            d["fast_mode_state"] = self.fast_mode_state
        return d


@dataclasses.dataclass
class SystemCompactBoundaryMessage:
    """``{type:"system", subtype:"compact_boundary", compact_metadata, ...}``.

    ``compact_metadata`` is passed through as a dict, expected shape::

        {"trigger": "manual"|"auto", "pre_tokens": <int>,
         "preserved_segment"?: {"head_uuid", "anchor_uuid", "tail_uuid"}}
    """

    compact_metadata: Dict[str, Any]
    uuid: str
    session_id: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "system",
            "subtype": "compact_boundary",
            "compact_metadata": self.compact_metadata,
            "uuid": self.uuid,
            "session_id": self.session_id,
        }


@dataclasses.dataclass
class SystemTaskMessage:
    """Union of ``system/task_started``, ``system/task_progress`` and
    ``system/task_notification`` (discriminated by ``subtype``).

    Per-variant required fields (coreSchemas):
      * ``task_started``: ``task_id``, ``description``
      * ``task_progress``: ``task_id``, ``description``, ``usage``
      * ``task_notification``: ``task_id``, ``status``, ``output_file``,
        ``summary``
    Other fields are emitted only when not ``None``.
    """

    subtype: str  # task_started | task_progress | task_notification
    task_id: str
    uuid: str
    session_id: str
    description: Optional[str] = None
    tool_use_id: Optional[str] = None
    task_type: Optional[str] = None
    workflow_name: Optional[str] = None
    prompt: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    output_file: Optional[str] = None
    summary: Optional[str] = None
    last_tool_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "type": "system",
            "subtype": self.subtype,
            "task_id": self.task_id,
            "uuid": self.uuid,
            "session_id": self.session_id,
        }
        for key, value in (
            ("description", self.description),
            ("tool_use_id", self.tool_use_id),
            ("task_type", self.task_type),
            ("workflow_name", self.workflow_name),
            ("prompt", self.prompt),
            ("usage", self.usage),
            ("status", self.status),
            ("output_file", self.output_file),
            ("summary", self.summary),
            ("last_tool_name", self.last_tool_name),
        ):
            if value is not None:
                d[key] = value
        return d


@dataclasses.dataclass
class SystemStatusMessage:
    """``{type:"system", subtype:"status", status, ...}``.

    ``status`` is nullable per the schema: pass ``None`` to emit JSON ``null``
    (meaning idle). ``permission_mode`` is optional and omitted when unset.
    """

    status: Optional[str]
    uuid: str
    session_id: str
    permission_mode: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "type": "system",
            "subtype": "status",
            "status": self.status,
            "uuid": self.uuid,
            "session_id": self.session_id,
        }
        if self.permission_mode is not None:
            d["permissionMode"] = self.permission_mode
        return d


@dataclasses.dataclass
class SystemApiRetryMessage:
    """``{type:"system", subtype:"api_retry", ...}``.

    ``error_status`` is nullable: pass ``None`` for connection errors that had
    no HTTP response (emitted as JSON ``null``).
    """

    attempt: int
    max_retries: int
    retry_delay_ms: int
    error: str
    uuid: str
    session_id: str
    error_status: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "system",
            "subtype": "api_retry",
            "attempt": self.attempt,
            "max_retries": self.max_retries,
            "retry_delay_ms": self.retry_delay_ms,
            "error_status": self.error_status,
            "error": self.error,
            "uuid": self.uuid,
            "session_id": self.session_id,
        }


# ---------------------------------------------------------------------------
# Stream / transcript messages
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class StreamEventMessage:
    """``{type:"stream_event", event, ...}``.

    ``event`` is the raw Anthropic RawMessageStreamEvent dict — passed through
    verbatim, never reshaped. ``parent_tool_use_id`` is omitted when ``None``.
    """

    event: Dict[str, Any]
    uuid: str
    session_id: str
    parent_tool_use_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "type": "stream_event",
            "event": self.event,
            "uuid": self.uuid,
            "session_id": self.session_id,
        }
        if self.parent_tool_use_id is not None:
            d["parent_tool_use_id"] = self.parent_tool_use_id
        return d


@dataclasses.dataclass
class AssistantMessage:
    """``{type:"assistant", message:{role:"assistant", content:[...]}, ...}``."""

    content: List[Any]
    uuid: str
    session_id: str
    parent_tool_use_id: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "type": "assistant",
            "message": {"role": "assistant", "content": self.content},
            "uuid": self.uuid,
            "session_id": self.session_id,
        }
        if self.parent_tool_use_id is not None:
            d["parent_tool_use_id"] = self.parent_tool_use_id
        if self.error is not None:
            d["error"] = self.error
        return d


@dataclasses.dataclass
class UserMessage:
    """``{type:"user", message:{role:"user", content:[...]}, ...}``.

    ``content`` is passed through as-is: either a list of content blocks
    (TextBlock / ToolResultBlock dicts) or a raw string.
    """

    content: Any
    uuid: str
    session_id: str
    parent_tool_use_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "type": "user",
            "message": {"role": "user", "content": self.content},
            "uuid": self.uuid,
            "session_id": self.session_id,
        }
        if self.parent_tool_use_id is not None:
            d["parent_tool_use_id"] = self.parent_tool_use_id
        return d


@dataclasses.dataclass
class ResultMessage:
    """``{type:"result", subtype, ...}`` — turn-over signal for the shell.

    Two wire variants (coreSchemas SDKResultSuccessSchema / SDKResultErrorSchema):
      * ``subtype == "success"`` emits ``result`` (string) and optional
        ``structured_output``.
      * ``subtype`` in
        {``error_during_execution``, ``error_max_turns``,
         ``error_max_budget_usd``, ``error_max_structured_output_retries``}
        emits ``errors`` (list of strings) instead of ``result``.

    ``model_usage`` maps to the camelCase wire key ``modelUsage``.
    ``stop_reason`` is nullable (emitted as JSON ``null`` when ``None``).
    """

    subtype: str
    duration_ms: float
    duration_api_ms: float
    is_error: bool
    num_turns: int
    total_cost_usd: float
    usage: Dict[str, Any]
    model_usage: Dict[str, Any]
    uuid: str
    session_id: str
    result: Optional[str] = None
    stop_reason: Optional[str] = None
    permission_denials: Optional[List[Dict[str, Any]]] = None
    structured_output: Optional[Any] = None
    errors: Optional[List[str]] = None
    fast_mode_state: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "type": "result",
            "subtype": self.subtype,
            "duration_ms": self.duration_ms,
            "duration_api_ms": self.duration_api_ms,
            "is_error": self.is_error,
            "num_turns": self.num_turns,
            "stop_reason": self.stop_reason,
            "total_cost_usd": self.total_cost_usd,
            "usage": self.usage,
            "modelUsage": self.model_usage,
            "uuid": self.uuid,
            "session_id": self.session_id,
        }
        if self.subtype == "success":
            d["result"] = self.result
            if self.structured_output is not None:
                d["structured_output"] = self.structured_output
        else:
            d["errors"] = self.errors if self.errors is not None else []
        if self.permission_denials is not None:
            d["permission_denials"] = list(self.permission_denials)
        if self.fast_mode_state is not None:
            d["fast_mode_state"] = self.fast_mode_state
        return d


# ---------------------------------------------------------------------------
# NDJSON serialization / stdin parsing
# ---------------------------------------------------------------------------


def encode_message(msg: Any) -> str:
    """Serialize a message to a single NDJSON line (no trailing newline).

    Equivalent to ``ndjsonSafeStringify`` in the TS source:
    ``JSON.stringify``-style dump (``ensure_ascii=False``), then literal
    U+2028 / U+2029 characters are replaced with the ``\\u2028`` / ``\\u2029``
    escape sequences so no line-splitting receiver can break the line.

    Accepts any of the dataclasses above (uses ``to_dict``) or an already-built
    dict. The caller is expected to append ``\\n`` when writing to stdout.
    """
    obj = msg.to_dict() if hasattr(msg, "to_dict") else msg
    line = json.dumps(obj, ensure_ascii=False)
    # Replace the literal line-separator characters that json.dumps emits raw
    # (they are not JSON-escapable special chars, unlike \\n).
    line = line.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return line


def parse_input_line(line: Any) -> Optional[Dict[str, Any]]:
    """Parse one stdin NDJSON line into its raw dict.

    Returns ``None`` (never raises) for empty / whitespace-only lines and for
    lines that are not valid JSON or that do not decode to a JSON object —
    mirroring the structuredIO fault tolerance. Valid envelopes include
    ``{"type":"user","message":{...},"uuid":...}`` and the low-priority
    ``control_request`` / ``control_response`` envelopes.
    """
    if line is None:
        return None
    s = line.strip() if isinstance(line, str) else ""
    if not s:
        return None
    try:
        obj = json.loads(s)
    except ValueError:
        return None
    if isinstance(obj, dict):
        return obj
    return None
