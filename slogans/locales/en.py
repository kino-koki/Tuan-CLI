"""English 标语 — 50 条, 口语 / 文化梗向。

说明: 本语种与 ``universal.py`` 同为英文, ``picker`` 取词时**两者合并**后
随机, 因此英语用户实际可用池为 300 + 50。

原列表偏谚语与客套, 探索类 (explore) 表达稀缺, 该组由通用池补齐;
收工/告别 (signoff) 特别丰富 (9 条), 这是英语本身的特点, 未强行削平。

分布: startup 6 · thinking 5 · explore 0 · error 1 · undo 4
      done 6 · signoff 9 · together 5 · guard 9 · idle 5
"""

from __future__ import annotations

GROUPS: dict[str, tuple[str, ...]] = {
    "startup": (
        "Slow is smooth, smooth is fast.",
        "Measure twice.",
        "Rome wasn't built in a day.",
        "Slow and steady.",
        "A stitch in time.",
        "Break a leg.",
    ),
    "thinking": (
        "Steady as she goes.",
        "The devil's in the details.",
        "Fingers crossed.",
        "Knock on wood.",
        "Cracking on.",
    ),
    "explore": (),
    "error": (
        "Close, but no cigar.",
    ),
    "undo": (
        "Back to the drawing board.",
        "Don't cry over spilt milk.",
        "Back to square one.",
        "Third time lucky.",
    ),
    "done": (
        "Bob's your uncle.",
        "Piece of cake.",
        "Sorted.",
        "Job done.",
        "That's the ticket.",
        "Chuffed to bits.",
    ),
    "signoff": (
        "Tea?",
        "Fancy a brew?",
        "Time to clock off.",
        "Call it a day.",
        "Home time.",
        "Cheerio.",
        "Ta for now.",
        "Mind how you go.",
        "Same time tomorrow?",
    ),
    "together": (
        "All hands on deck.",
        "Many hands make light work.",
        "Two heads are better.",
        "The more, the merrier.",
        "I'm here.",
    ),
    "guard": (
        "Trust, but verify.",
        "Keep your powder dry.",
        "Mind the gap.",
        "Mind the step.",
        "Batten down the hatches.",
        "Hold the line.",
        "Better safe than sorry.",
        "Look before you leap.",
        "Don't count your chickens.",
    ),
    "idle": (
        "Easy does it.",
        "Hold your horses.",
        "Keep calm and carry on.",
        "Stiff upper lip.",
        "Steady on.",
    ),
}
