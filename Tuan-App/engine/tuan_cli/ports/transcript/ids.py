"""Agent/transcript id types and helpers (对齐上游 model/ids 的类型).

设计: 所有 id 在运行时就是普通 str, 类型上同样按 str 处理, 方便调用方
直接传字符串。旧写法先 NewType 再试图用 `= str` 覆盖 (Convenience
aliases) 在 mypy 下是非法的 (Cannot assign to a type), 覆盖实际不生效,
导致本模块与下游 (history/apply/model) 的 id 类型分裂, 连锁报 arg-type。
统一为 str 别名后, 运行时与静态类型都一致。
"""

from __future__ import annotations

import math

TurnId = str
StepId = str
FrameId = str
MarkerId = str
TaskRefId = str
TaskId = str
AgentId = str
InteractionId = str
AttachmentId = str
TodoId = str
PromptId = str
ItemId = str


def turn_id(ordinal: int) -> TurnId:
    return f"t{ordinal}"


def step_id(turn: TurnId, ordinal: int) -> StepId:
    return f"{turn}.{ordinal}"


def frame_id(step: StepId, ordinal: int) -> FrameId:
    return f"{step}.f{ordinal}"


def compare_turn_ids(a: TurnId, b: TurnId) -> int:
    return turn_ordinal(a) - turn_ordinal(b)


def turn_ordinal(id: TurnId) -> int:
    s = id[1:] if id else ""
    try:
        n = float(s)
    except (ValueError, TypeError):
        return 0
    if not math.isfinite(n):
        return 0
    return int(n)
