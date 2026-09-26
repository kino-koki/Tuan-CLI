"""Behavioral tests for the transcript port (stdlib only)."""

from __future__ import annotations

import json

import pytest

from qingxiaotuan.ports.transcript import (
    AgentTranscript,
    AgentTranscriptSnapshot,
    AppendOp,
    AppendTargetFrame,
    FrameUpsertOp,
    TranscriptDecodeError,
    TranscriptStep,
    TranscriptStore,
    TranscriptTurn,
    TurnUpsertOp,
    dump_snapshot,
    fold_wire_record_facts,
    frame_id,
    group_messages_into_snapshot,
    is_plain_agent_id,
    load_snapshot,
    load_operation,
    paginate_turns,
    step_id,
    grade_for,
)
from qingxiaotuan.ports.transcript.model import TextFrame, TranscriptMarker


def _build_turn_ops() -> list:
    turn = TranscriptTurn(turn_id="t0", ordinal=0, state="running", origin={"kind": "user"}, prompt="hi", steps=[])
    step = TranscriptStep(step_id=step_id("t0", 1), turn_id="t0", ordinal=1, state="running", frames=[])
    frame = TextFrame(frame_id=frame_id(step_id("t0", 1), 1), role="assistant", text="")
    return [
        TurnUpsertOp(turn=turn),
        FrameUpsertOp(turn_id="t0", step_id=step.step_id, frame=frame),
    ]


def test_append_turn_serialize_deserialize_equals():
    tr = AgentTranscript("agent1")
    result = tr.apply(_build_turn_ops())
    assert len(result["accepted"]) == 2

    snap1 = tr.snapshot()
    assert isinstance(snap1, AgentTranscriptSnapshot)
    assert len(snap1.items) == 1

    payload = dump_snapshot(snap1)
    assert isinstance(payload, str)

    snap2 = load_snapshot(payload)
    # Feed the deserialized snapshot into a fresh transcript via reset.
    fresh = AgentTranscript("agent1")
    fresh.apply([_reset_op(snap2)])
    snap3 = fresh.snapshot()

    assert snap1 == snap3
    # Round-trip through dict form too.
    assert snap1 == load_snapshot(json.dumps(_snap_to_dict(snap1)))


def _reset_op(snapshot):
    from qingxiaotuan.ports.transcript import ResetOp

    return ResetOp(agent_id="agent1", snapshot=snapshot)


def _snap_to_dict(snapshot):
    from qingxiaotuan.ports.transcript.operation import snapshot_to_dict

    return snapshot_to_dict(snapshot)


def test_append_text_merges_and_detects_gap():
    tr = AgentTranscript("agent1")
    tr.apply(_build_turn_ops())

    step_id_ = step_id("t0", 1)
    frame_id_ = frame_id(step_id_, 1)
    target = AppendTargetFrame(turn_id="t0", step_id=step_id_, frame_id=frame_id_)

    # First chunk at offset 0.
    r1 = tr.apply([AppendOp(target=target, offset=0, text="Hello ")])
    assert r1["accepted"] and r1["gap"] is None
    # Contiguous chunk.
    r2 = tr.apply([AppendOp(target=target, offset=6, text="world")])
    assert r2["accepted"]
    assert tr.get_turn("t0").steps[0].frames[0].text == "Hello world"
    # Gap: offset beyond current length.
    r3 = tr.apply([AppendOp(target=target, offset=100, text="!")])
    assert r3["gap"] is not None
    assert r3["gap"]["expected"] == 11


def test_store_roster_and_agents():
    store = TranscriptStore("session-1")
    a = store.ensure_agent("main", None)
    assert isinstance(a, AgentTranscript)
    assert store.get_agent("main") is a
    store.describe_agent(__import__("qingxiaotuan.ports.transcript", fromlist=["AgentDescriptor"]).AgentDescriptor(agent_id="main", label="Main"))
    assert store.agents()[0].label == "Main"
    assert store.remove_agent("main") is True
    assert store.get_agent("main") is None


def test_malformed_input_raises():
    with pytest.raises(TranscriptDecodeError):
        load_snapshot("{not valid json")
    with pytest.raises(TranscriptDecodeError):
        load_snapshot(json.dumps({"items": "nope"}))
    with pytest.raises(TranscriptDecodeError):
        load_operation(json.dumps({"op": "bogus.op"}))


def test_grade_and_pagination_helpers():
    assert grade_for(None, "x") == "off"
    assert grade_for({"x": "block"}, "x") == "block"
    assert grade_for({"*": "turn"}, "y") == "turn"

    turns = [
        TranscriptTurn(turn_id="t0", ordinal=0, state="completed", origin={"kind": "user"}, steps=[]),
        TranscriptTurn(turn_id="t1", ordinal=1, state="completed", origin={"kind": "user"}, steps=[]),
        TranscriptTurn(turn_id="t2", ordinal=2, state="completed", origin={"kind": "user"}, steps=[]),
    ]
    page = paginate_turns(turns, {"pageSize": 2})
    assert len(page["items"]) == 2
    assert page["hasMore"] is True


def test_group_messages_into_snapshot_basic():
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "plan a trip"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Sure, "}, {"type": "think", "think": "thinking..."}]},
        {"role": "assistant", "toolCalls": [{"id": "c1", "name": "shell", "arguments": '{"cmd": "ls"}'}]},
        {"role": "tool", "toolCallId": "c1", "isError": False, "content": [{"type": "text", "text": "ok"}]},
    ]
    snap = group_messages_into_snapshot(messages)
    assert len(snap.items) >= 1
    turn = next(i for i in snap.items if i.kind == "turn")
    assert turn.prompt == "plan a trip"
    # assistant step should have text + thinking + tool frames
    kinds = [f.kind for s in turn.steps for f in s.frames]
    assert "text" in kinds and "thinking" in kinds and "tool" in kinds


def test_fold_wire_record_facts_basic():
    base = AgentTranscriptSnapshot(items=[], tasks=[], interactions=[], attachments=[], todos=[], prompts=[], meta=__import__("qingxiaotuan.ports.transcript.model", fromlist=["TranscriptMeta"]).TranscriptMeta())
    records = [
        {"type": "goal.create", "objective": "ship it", "time": 1000},
        {"type": "task.started", "info": {"taskId": "tk1", "kind": "process", "status": "running"}, "outputTail": "log"},
    ]
    out = fold_wire_record_facts(records, base)
    assert len(out.tasks) == 1
    assert out.tasks[0].task_id == "tk1"
    assert out.meta.goal is not None and out.meta.goal.objective == "ship it"


def test_is_plain_agent_id():
    assert is_plain_agent_id("agent-1.X")
    assert not is_plain_agent_id("..")
    assert not is_plain_agent_id("../evil")


def test_filesystem_round_trip_via_tmp_path(tmp_path):
    tr = AgentTranscript("agent1")
    tr.apply(_build_turn_ops())
    snap = tr.snapshot()
    path = tmp_path / "snap.json"
    path.write_text(dump_snapshot(snap), encoding="utf-8")
    loaded = load_snapshot(path.read_text(encoding="utf-8"))
    assert loaded == snap


# --------------------------------------------------------------------------- #
# Regression tests for the mypy-cleanup round (attachment extraction, tool
# message boundaries, meta.merge semantics, helpers).  These pin the behaviors
# that the type fixes must not change.
# --------------------------------------------------------------------------- #


def _group(parts, role="user", **extra):
    return group_messages_into_snapshot([{"role": role, "content": parts, **extra}])


def test_group_attachments_image_url():
    snap = _group([{"type": "image", "source": {"kind": "url", "url": "https://x/a.png"}}])
    assert len(snap.attachments) == 1
    assert snap.attachments[0].media_type == "image/*"
    assert snap.attachments[0].source == {"kind": "url", "url": "https://x/a.png"}


def test_group_attachments_image_base64_uses_media_type():
    snap = _group([{"type": "image", "source": {"kind": "base64", "media_type": "image/png", "data": "..."}}])
    assert snap.attachments[0].media_type == "image/png"


def test_group_attachments_file():
    snap = _group([{"type": "file", "file_id": "f1", "name": "a.txt"}])
    assert snap.attachments[0].source == {"kind": "file", "fileId": "f1"}


def test_group_attachments_daemon_image_ref():
    snap = _group([{"type": "image_url", "imageUrl": {"url": "kimi-file://f_abc"}}])
    assert len(snap.attachments) == 1
    assert snap.attachments[0].media_type == "image/*"
    assert snap.attachments[0].source == {"kind": "session_media", "fileId": "f_abc"}


def test_group_attachments_daemon_video_ref():
    snap = _group([{"type": "video_url", "videoUrl": {"url": "kimi-file://f_vid"}}])
    assert snap.attachments[0].media_type == "video/*"
    assert snap.attachments[0].source["fileId"] == "f_vid"


def test_group_attachments_daemon_missing_url_no_crash():
    # pairing part without imageUrl must not raise (media_ref 兜底分支)
    snap = _group([{"type": "image_url"}])
    assert snap.attachments == []


def test_group_first_message_is_tool_no_crash():
    snap = group_messages_into_snapshot([{"role": "tool", "toolCallId": "c1", "content": [{"type": "text", "text": "ok"}]}])
    assert snap is not None
    assert len(snap.items) == 0


def test_group_tool_error_frame_state():
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "run it"}]},
        {"role": "assistant", "toolCalls": [{"id": "c1", "name": "shell", "arguments": "{}"}]},
        {"role": "tool", "toolCallId": "c1", "isError": True, "content": [{"type": "text", "text": "boom"}]},
    ]
    snap = group_messages_into_snapshot(messages)
    turn = next(i for i in snap.items if i.kind == "turn")
    tool = next(f for s in turn.steps for f in s.frames if f.kind == "tool")
    assert tool.state == "error"
    assert tool.output == "boom"


def test_apply_meta_merge_goal_set_and_clear():
    from qingxiaotuan.ports.transcript import MetaMergeOp
    from qingxiaotuan.ports.transcript.apply import AgentState, apply_operation

    state = AgentState()
    r = apply_operation(state, MetaMergeOp(meta={"goal": {"objective": "ship", "status": "active"}}))
    assert r.changed and r.state.meta.goal is not None
    assert r.state.meta.goal.objective == "ship"
    r2 = apply_operation(r.state, MetaMergeOp(meta={"goal": None}))
    assert r2.changed and r2.state.meta.goal is None
    # 无变化合并 -> changed=False
    r3 = apply_operation(r2.state, MetaMergeOp(meta={"goal": None}))
    assert not r3.changed


def test_apply_meta_merge_modes_set_and_clear():
    from qingxiaotuan.ports.transcript import MetaMergeOp
    from qingxiaotuan.ports.transcript.apply import AgentState, apply_operation

    state = AgentState()
    r = apply_operation(state, MetaMergeOp(meta={"modes": {"plan": "block"}}))
    assert r.state.meta.modes is not None and r.state.meta.modes.plan == "block"
    # 空 dict 语义: 无变化 -> 保留 base
    r1 = apply_operation(r.state, MetaMergeOp(meta={"modes": {}}))
    assert r1.state.meta.modes is not None and r1.state.meta.modes.plan == "block"
    # 显式 None 值: 清空 -> modes 归 None
    r2 = apply_operation(r.state, MetaMergeOp(meta={"modes": {"plan": None, "swarm": None, "tower": None}}))
    assert r2.state.meta.modes is None


def test_apply_meta_merge_agent_merge_and_keep():
    from qingxiaotuan.ports.transcript import MetaMergeOp
    from qingxiaotuan.ports.transcript.apply import AgentState, apply_operation

    state = AgentState()
    r = apply_operation(state, MetaMergeOp(meta={"agent": {"model": "gpt-x"}}))
    assert r.state.meta.agent is not None and r.state.meta.agent.model == "gpt-x"
    # agent: None 保留 base（不清除）
    r2 = apply_operation(r.state, MetaMergeOp(meta={"agent": None}))
    assert r2.state.meta.agent is not None and r2.state.meta.agent.model == "gpt-x"


def test_item_id_and_frame_equals_helpers():
    from qingxiaotuan.ports.transcript import TranscriptTaskRef
    from qingxiaotuan.ports.transcript.apply import _frame_equals, _item_id_of
    from qingxiaotuan.ports.transcript.model import ThinkingFrame

    t = TranscriptTurn(turn_id="t0", ordinal=0, state="running", origin={"kind": "user"}, steps=[])
    m = TranscriptMarker(marker_id="m1", marker="skill", payload={})
    ref = TranscriptTaskRef(ref_id="r1", task_id="tk1")
    assert _item_id_of(t) == "t0"
    assert _item_id_of(m) == "m1"
    assert _item_id_of(ref) == "r1"
    a = TextFrame(frame_id="f1", role="assistant", text="hi")
    b = TextFrame(frame_id="f1", role="assistant", text="hi")
    c = TextFrame(frame_id="f1", role="assistant", text="bye")
    assert _frame_equals(a, b)
    assert not _frame_equals(a, c)
    assert not _frame_equals(a, ThinkingFrame(frame_id="f1", text="hi"))


def test_media_ref_parse_and_pairing():
    from qingxiaotuan.ports.transcript.media_ref import (
        MediaRefPart,
        daemon_file_ref_from_pairing_part,
        parse_daemon_file_ref,
    )

    assert parse_daemon_file_ref("kimi-file://f1?x=1").file_id == "f1"
    assert parse_daemon_file_ref("https://x") is None
    r = daemon_file_ref_from_pairing_part(MediaRefPart("image_url", image_url={"url": "kimi-file://f2"}))
    assert r["kind"] == "image" and r["ref"].file_id == "f2"
    assert daemon_file_ref_from_pairing_part(MediaRefPart("image_url")) is None  # 兜底
    assert daemon_file_ref_from_pairing_part(MediaRefPart("text")) is None
    assert daemon_file_ref_from_pairing_part(MediaRefPart("video_url", video_url=None)) is None
