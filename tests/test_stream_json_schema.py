"""Unit tests for tuan_cli.stream_json.schema.

Runnable standalone (no pytest needed):

    python tests/test_stream_json_schema.py

Exits non-zero and prints the first failure on any assertion error; prints a
final ALL TESTS PASSED line when everything holds.

NOTE: this file used to live inside the package at
``tuan_cli/stream_json/test_schema.py``, where it was shipped to end users by
``pip install`` / wheel builds while being run by nothing (pytest is configured
with ``testpaths = ["tests"]``). It was the only test coverage for
``stream_json/schema.py`` (the Claude Code stream-JSON serializer), so it was
moved here rather than deleted. ``tests/test_json_schema.py`` covers a
different module (``tuan_cli/json_schema.py``) and has no overlap.
"""

from __future__ import annotations

import json
import sys

from tuan_cli.stream_json import schema as S


def check(name: str, cond: bool, detail: str = "") -> None:
    if not cond:
        raise AssertionError(f"FAIL: {name} {detail}")
    print(f"  ok - {name}")


# ---------------------------------------------------------------------------
# 1. Per-message serialization, field-by-field
# ---------------------------------------------------------------------------


def test_system_init() -> None:
    print("[system/init]")
    msg = S.SystemInitMessage(
        cwd="/proj",
        session_id="sess-1",
        tools=["Read", "Write", "Task"],
        mcp_servers=[{"name": "fs", "status": "connected"}],
        model="claude-sonnet-4-5",
        permission_mode="acceptEdits",
        slash_commands=["init", "review"],
        api_key_source="oauth",
        claude_code_version="1.0.47",
        output_style="default",
        uuid="uuid-init",
        agents=["Explore"],
        skills=["grep"],
        plugins=[{"name": "p", "path": "/p", "source": "x@inline"}],
    )
    d = msg.to_dict()
    check("type/subtype", d["type"] == "system" and d["subtype"] == "init")
    check("cwd", d["cwd"] == "/proj")
    check("session_id", d["session_id"] == "sess-1")
    check("tools passthrough", d["tools"] == ["Read", "Write", "Task"])
    check("mcp_servers shape", d["mcp_servers"] == [{"name": "fs", "status": "connected"}])
    check("model", d["model"] == "claude-sonnet-4-5")
    check("wire key permissionMode (camelCase)", d["permissionMode"] == "acceptEdits")
    check("no snake permission_mode key", "permission_mode" not in d)
    check("slash_commands", d["slash_commands"] == ["init", "review"])
    check("wire key apiKeySource (camelCase)", d["apiKeySource"] == "oauth")
    check("claude_code_version", d["claude_code_version"] == "1.0.47")
    check("output_style", d["output_style"] == "default")
    check("agents", d["agents"] == ["Explore"])
    check("skills", d["skills"] == ["grep"])
    check("plugins", d["plugins"] == [{"name": "p", "path": "/p", "source": "x@inline"}])
    check("uuid", d["uuid"] == "uuid-init")
    check("betas omitted", "betas" not in d)
    check("fast_mode_state omitted", "fast_mode_state" not in d)


def test_system_compact_boundary() -> None:
    print("[system/compact_boundary]")
    msg = S.SystemCompactBoundaryMessage(
        compact_metadata={
            "trigger": "auto",
            "pre_tokens": 200000,
            "preserved_segment": {
                "head_uuid": "h1",
                "anchor_uuid": "a1",
                "tail_uuid": "t1",
            },
        },
        uuid="uuid-cb",
        session_id="sess-1",
    )
    d = msg.to_dict()
    check("type/subtype", d["type"] == "system" and d["subtype"] == "compact_boundary")
    check("compact_metadata trigger", d["compact_metadata"]["trigger"] == "auto")
    check("preserved_segment passthrough", d["compact_metadata"]["preserved_segment"]["tail_uuid"] == "t1")
    check("uuid/session_id", d["uuid"] == "uuid-cb" and d["session_id"] == "sess-1")


def test_system_task_messages() -> None:
    print("[system/task_*]")
    started = S.SystemTaskMessage(
        subtype="task_started",
        task_id="task-1",
        uuid="uuid-t1",
        session_id="sess-1",
        description="read the repo",
        tool_use_id="tu-1",
    ).to_dict()
    check("task_started subtype", started["subtype"] == "task_started")
    check("task_started fields", started["task_id"] == "task-1" and started["description"] == "read the repo")
    check("task_started tool_use_id", started["tool_use_id"] == "tu-1")
    check("task_started no status", "status" not in started)

    progress = S.SystemTaskMessage(
        subtype="task_progress",
        task_id="task-1",
        uuid="uuid-t2",
        session_id="sess-1",
        description="still reading",
        usage={"total_tokens": 1200, "tool_uses": 3, "duration_ms": 900},
        last_tool_name="Read",
    ).to_dict()
    check("task_progress usage", progress["usage"]["total_tokens"] == 1200)
    check("task_progress last_tool_name", progress["last_tool_name"] == "Read")

    notif = S.SystemTaskMessage(
        subtype="task_notification",
        task_id="task-1",
        uuid="uuid-t3",
        session_id="sess-1",
        status="completed",
        output_file="/out.txt",
        summary="done",
    ).to_dict()
    check("task_notification status", notif["status"] == "completed")
    check("task_notification output_file", notif["output_file"] == "/out.txt")
    check("task_notification no description", "description" not in notif)


def test_system_status_and_api_retry() -> None:
    print("[system/status + system/api_retry]")
    st = S.SystemStatusMessage(status=None, uuid="uuid-s", session_id="sess-1").to_dict()
    check("status null emitted", st["status"] is None and json.dumps(st["status"]) == "null")
    check("permissionMode omitted", "permissionMode" not in st)
    st2 = S.SystemStatusMessage(status="compacting", uuid="uuid-s2", session_id="sess-1",
                                permission_mode="plan").to_dict()
    check("status compacting", st2["status"] == "compacting")
    check("permissionMode present", st2["permissionMode"] == "plan")

    retry = S.SystemApiRetryMessage(
        attempt=2, max_retries=5, retry_delay_ms=1500, error="rate_limit",
        uuid="uuid-r", session_id="sess-1", error_status=429,
    ).to_dict()
    check("api_retry subtype", retry["subtype"] == "api_retry")
    check("api_retry fields", retry["attempt"] == 2 and retry["error_status"] == 429 and retry["error"] == "rate_limit")
    retry2 = S.SystemApiRetryMessage(
        attempt=1, max_retries=5, retry_delay_ms=500, error="server_error",
        uuid="uuid-r2", session_id="sess-1",
    ).to_dict()
    check("api_retry error_status null", retry2["error_status"] is None)


def test_stream_event_passthrough() -> None:
    print("[stream_event]")
    event = {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "hello"},
    }
    msg = S.StreamEventMessage(event=event, uuid="uuid-se", session_id="sess-1").to_dict()
    check("type", msg["type"] == "stream_event")
    check("event passthrough shape", msg["event"] == event)
    check("event passthrough identical", msg["event"]["delta"]["text"] == "hello")
    check("parent_tool_use_id omitted", "parent_tool_use_id" not in msg)

    msg2 = S.StreamEventMessage(event=event, uuid="uuid-se2", session_id="sess-1",
                                parent_tool_use_id="tu-9").to_dict()
    check("parent_tool_use_id present", msg2["parent_tool_use_id"] == "tu-9")


def test_assistant_and_user_messages() -> None:
    print("[assistant / user]")
    asst = S.AssistantMessage(
        content=[S.TextBlock("hi").to_dict(), S.ToolUseBlock("tu-1", "Read", {"path": "a.py"}).to_dict()],
        uuid="uuid-a", session_id="sess-1",
    ).to_dict()
    check("type", asst["type"] == "assistant")
    check("message.role", asst["message"]["role"] == "assistant")
    check("content blocks", asst["message"]["content"][0]["type"] == "text"
          and asst["message"]["content"][1]["type"] == "tool_use"
          and asst["message"]["content"][1]["name"] == "Read")

    u = S.UserMessage(
        content=[S.ToolResultBlock("tu-1", "file body", is_error=False).to_dict()],
        uuid="uuid-u", session_id="sess-1",
    ).to_dict()
    check("type", u["type"] == "user")
    check("message.role", u["message"]["role"] == "user")
    check("tool_result block", u["message"]["content"][0] == {
        "type": "tool_result", "tool_use_id": "tu-1", "content": "file body", "is_error": False})

    tr = S.ToolResultBlock("tu-2", "plain").to_dict()
    check("tool_result is_error omitted when None", "is_error" not in tr)


def test_result_success() -> None:
    print("[result/success]")
    usage = {"input_tokens": 100, "output_tokens": 50}
    model_usage = {"claude-sonnet-4-5": {
        "inputTokens": 100, "outputTokens": 50, "cacheReadInputTokens": 0,
        "cacheCreationInputTokens": 0, "webSearchRequests": 0, "costUSD": 0.001,
        "contextWindow": 200000, "maxOutputTokens": 8192}}
    msg = S.ResultMessage(
        subtype="success", duration_ms=1234.5, duration_api_ms=600.0,
        is_error=False, num_turns=3, total_cost_usd=0.012,
        usage=usage, model_usage=model_usage,
        result="all done", stop_reason="end_turn",
        permission_denials=[], uuid="uuid-res", session_id="sess-1",
    ).to_dict()
    check("type/subtype", msg["type"] == "result" and msg["subtype"] == "success")
    check("result string", msg["result"] == "all done")
    check("usage passthrough", msg["usage"] == usage)
    check("wire key modelUsage (camelCase)", msg["modelUsage"] == model_usage)
    check("no model_usage snake key", "model_usage" not in msg)
    check("stop_reason", msg["stop_reason"] == "end_turn")
    check("duration fields", msg["duration_ms"] == 1234.5 and msg["num_turns"] == 3)
    check("no errors key on success", "errors" not in msg)
    check("structured_output omitted", "structured_output" not in msg)


def test_result_error() -> None:
    print("[result/error_*]")
    for sub in ("error_during_execution", "error_max_turns",
                "error_max_budget_usd", "error_max_structured_output_retries"):
        msg = S.ResultMessage(
            subtype=sub, duration_ms=500.0, duration_api_ms=100.0,
            is_error=True, num_turns=4, total_cost_usd=0.002,
            usage={"input_tokens": 1}, model_usage={},
            stop_reason="max_tokens", errors=["boom"],
            uuid="uuid-re", session_id="sess-1",
        ).to_dict()
        check(f"{sub} subtype", msg["subtype"] == sub)
        check(f"{sub} errors", msg["errors"] == ["boom"])
        check(f"{sub} no result key", "result" not in msg)
        check(f"{sub} stop_reason", msg["stop_reason"] == "max_tokens")


# ---------------------------------------------------------------------------
# 2. encode_message: U+2028 / U+2029 escaping + single line
# ---------------------------------------------------------------------------


def test_encode_line_separator_escaping() -> None:
    print("[encode: U+2028/U+2029]")
    text = "line one\u2028line two\u2029para two"
    out = S.encode_message(S.TextBlock(text))
    check("literal \\u2028 present", "\\u2028" in out)
    check("literal \\u2029 present", "\\u2029" in out)
    check("raw U+2028 absent", "\u2028" not in out)
    check("raw U+2029 absent", "\u2029" not in out)
    check("single line (no raw LF inside)", "\n" not in out)
    # the escaped form must round-trip back to the same string
    parsed = json.loads(out)
    check("round-trip text", parsed["text"] == text)


def test_encode_general() -> None:
    print("[encode: general NDJSON]")
    line = S.encode_message(S.SystemStatusMessage(status=None, uuid="u", session_id="s"))
    check("ends without trailing newline", not line.endswith("\n"))
    check("is valid single JSON line", json.loads(line)["subtype"] == "status")

    line2 = S.encode_message({"type": "user", "message": {"role": "user", "content": "café"}})
    check("ensure_ascii=False keeps café", "café" in line2)


# ---------------------------------------------------------------------------
# 3. Optional None fields omitted
# ---------------------------------------------------------------------------


def test_none_omitted() -> None:
    print("[optional None omitted]")
    se = S.StreamEventMessage(event={"type": "x"}, uuid="u", session_id="s").to_dict()
    check("stream_event parent_tool_use_id omitted", "parent_tool_use_id" not in se)
    r = S.ResultMessage(
        subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
        num_turns=1, total_cost_usd=0.0, usage={}, model_usage={},
        result="ok", uuid="u", session_id="s",
    ).to_dict()
    check("permission_denials omitted", "permission_denials" not in r)
    check("structured_output omitted", "structured_output" not in r)
    check("fast_mode_state omitted", "fast_mode_state" not in r)
    i = S.SystemInitMessage(
        cwd="/", session_id="s", tools=[], mcp_servers=[], model="m",
        permission_mode="default", slash_commands=[], api_key_source="oauth",
        claude_code_version="v", output_style="default", uuid="u",
    ).to_dict()
    check("init agents/skills/plugins omitted",
          "agents" not in i and "skills" not in i and "plugins" not in i)


# ---------------------------------------------------------------------------
# 4. parse_input_line
# ---------------------------------------------------------------------------


def test_parse_input_line() -> None:
    print("[parse_input_line]")
    good = S.parse_input_line('{"type":"user","message":{"role":"user","content":"hi"},"uuid":"u-1"}\n')
    check("user line parsed", good is not None and good["type"] == "user"
          and good["uuid"] == "u-1" and good["message"]["content"] == "hi")
    ctrl = S.parse_input_line('{"type":"control_request","request":"ping","uuid":"c-1"}')
    check("control_request envelope parsed", ctrl is not None and ctrl["type"] == "control_request")
    check("empty line -> None", S.parse_input_line("") is None)
    check("whitespace line -> None", S.parse_input_line("   \t  ") is None)
    check("None input -> None", S.parse_input_line(None) is None)
    check("broken JSON -> None", S.parse_input_line("{not json") is None)
    check("truncated -> None", S.parse_input_line('{"type":"user"') is None)
    check("json array -> None (not envelope)", S.parse_input_line("[1,2]") is None)


def main() -> int:
    tests = [
        test_system_init,
        test_system_compact_boundary,
        test_system_task_messages,
        test_system_status_and_api_retry,
        test_stream_event_passthrough,
        test_assistant_and_user_messages,
        test_result_success,
        test_result_error,
        test_encode_line_separator_escaping,
        test_encode_general,
        test_none_omitted,
        test_parse_input_line,
    ]
    for t in tests:
        t()
    print()
    print(f"ALL {len(tests)} TEST GROUPS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
