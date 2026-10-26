"""扩展场景标语 — 主体 10 场景之外的产品特有场景。

6 个新场景 (来自 slogans_extra.md 附录):

- ``model.switch``  切换模型 / 供应商后  (原映射到 startup, 不贴切)
- ``budget.warn``   接近预算上限        (原映射到 guard, 缺"钱"的语义)
- ``bg.start``      派发后台 / 长任务    (原映射到 startup)
- ``bg.progress``   长任务进行中 (>30s)  (原映射到 thinking)
- ``pairing``       手机扫码配对        (原映射到 together)
- ``memory.write``  自动写入记忆        (原无对应)

接入方式: **不改动主体编号与数量**, 单独成池, 由 ``picker`` 优先查找,
未命中再回落主体同义组。英文通用池同时充当所有语种的兜底。
"""

from __future__ import annotations

from typing import Dict, Tuple

# 扩展场景清单
CONTEXTS: Tuple[str, ...] = (
    "model.switch", "budget.warn", "bg.start",
    "bg.progress", "pairing", "memory.write",
)

# 触发事件 -> 扩展场景 (远端配对沿用 pairing 池)
EVENT_MAP: Dict[str, str] = {
    "model.switch": "model.switch",
    "model.change": "model.switch",
    "provider.switch": "model.switch",
    "budget.warn": "budget.warn",
    "budget.limit": "budget.warn",
    "bg.start": "bg.start",
    "background.start": "bg.start",
    "bg.progress": "bg.progress",
    "background.progress": "bg.progress",
    "remote.pair": "pairing",
    "pairing": "pairing",
    "memory.write": "memory.write",
    "memory.auto": "memory.write",
}

# ---------------------------------------------------------------- 通用英文池 (6 × 10)
GROUPS: Dict[str, Tuple[str, ...]] = {
    "model.switch": (
        "New voice, same room.",
        "Switched. Listening.",
        "Different hands, same work.",
        "Another pair of eyes.",
        "Tuned differently now.",
        "Changed lanes.",
        "New lens on.",
        "Same road, new shoes.",
        "Handed over.",
        "Different mind, same desk.",
    ),
    "budget.warn": (
        "Wallet's getting lighter.",
        "Watch the meter.",
        "This one costs more.",
        "Meter's running.",
        "Getting pricey.",
        "Count before you spend.",
        "Worth it? Your call.",
        "The till is humming.",
        "Close to the line.",
        "Spending quietly.",
    ),
    "bg.start": (
        "It runs without you now.",
        "Walk away. I'll watch.",
        "Started. Go do something else.",
        "Left it running.",
        "It'll keep going.",
        "Working in the background.",
        "Sent it off.",
        "Running while you rest.",
        "Dispatched.",
        "Let it cook.",
    ),
    "bg.progress": (
        "Still going.",
        "Working. No news yet.",
        "Turning over.",
        "Long one, this.",
        "Still at it.",
        "Halfway, maybe.",
        "Grinding.",
        "It takes the time it takes.",
        "Still working.",
        "No rush on my end.",
    ),
    "pairing": (
        "Two screens, one room.",
        "Connected.",
        "Your phone's in.",
        "Shook hands.",
        "Paired.",
        "One of us now.",
        "Linked up.",
        "You're holding the other end.",
        "Connected — carefully.",
        "Two ends of one thread.",
    ),
    "memory.write": (
        "Noted.",
        "Filed away.",
        "Remembered.",
        "Written down.",
        "Kept.",
        "Saved for later.",
        "Jotted.",
        "Put aside, safely.",
        "Noted — and only that.",
        "Remembered quietly.",
    ),
}

# ---------------------------------------------------------------- 本地化扩展池
LOCALES: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "zh-CN": {
        "model.switch": (
            "换了个人，还是这间屋。",
            "换手了。",
            "另一双手。",
            "换了个脑子。",
            "接着说。",
        ),
        "budget.warn": (
            "钱包在变薄。",
            "看看表。",
            "这个贵一点。",
            "快到线了。",
            "花得有点快。",
        ),
        "bg.start": (
            "它自己跑了。",
            "你先忙去。",
            "交给后台。",
            "先让它跑着。",
            "派出去啦。",
        ),
        "bg.progress": (
            "还在跑。",
            "没消息，就是还在干。",
            "这个慢。",
            "慢慢来。",
            "还早。",
        ),
        "pairing": (
            "两块屏，一间屋。",
            "连上了。",
            "手机进来了。",
            "握过手了。",
            "一根线，两头。",
        ),
        "memory.write": (
            "记下了。",
            "收好了。",
            "写着呢。",
            "存起来了。",
            "只记这一句。",
        ),
    },
    "en": {
        "model.switch": (
            "New voice in the room.",
            "Switched over.",
            "Different hands now.",
            "Fresh eyes on it.",
            "Same desk, new mind.",
        ),
        "budget.warn": (
            "Wallet's lighter.",
            "Meter's running.",
            "This one's pricier.",
            "Close to the line.",
            "Spending fast.",
        ),
        "bg.start": (
            "It runs alone now.",
            "Off you go.",
            "Left it running.",
            "Dispatched.",
            "Let it cook.",
        ),
        "bg.progress": (
            "Still at it.",
            "No news — still working.",
            "This one's slow.",
            "Takes its time.",
            "Early days.",
        ),
        "pairing": (
            "Two screens, one room.",
            "Connected.",
            "Phone's in.",
            "Shook hands.",
            "One thread, two ends.",
        ),
        "memory.write": (
            "Noted.",
            "Filed.",
            "Writing it down.",
            "Kept safe.",
            "Just that one thing.",
        ),
    },
}


def count() -> int:
    """通用池条目总数 (期望 60)。"""
    return sum(len(v) for v in GROUPS.values())
