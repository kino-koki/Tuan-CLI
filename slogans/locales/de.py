"""Deutsch (de) 标语 — 50 条, 按 10 个上下文分组。

风格: Sprichwörter + Büroalltag ("Feierabend" / "Läuft" / "Passt schon")。
协作 (together) 在本列表中无对应表达 —— 该组完全由通用池 (30 条) 承担。
若日后要补德语协作语, 建议加 "Zusammen geht's leichter." / "Ich halt die Leiter."

分布: startup 7 · thinking 9 · explore 2 · error 3 · undo 6
      done 6 · signoff 5 · together 0 · guard 3 · idle 9
"""

from __future__ import annotations

GROUPS: dict[str, tuple[str, ...]] = {
    "startup": (
        "Eile mit Weile.",
        "Gut Ding will Weile haben.",
        "Übung macht den Meister.",
        "Aller Anfang ist schwer.",
        "Ohne Fleiß kein Preis.",
        "Morgenstund hat Gold im Mund.",
        "Rom wurde nicht an einem Tag erbaut.",
    ),
    "thinking": (
        "Probieren geht über Studieren.",
        "Steter Tropfen höhlt den Stein.",
        "Den Wald vor lauter Bäumen nicht sehen.",
        "Auf dem Schlauch stehen.",
        "Die Nadel im Heuhaufen suchen.",
        "Läuft.",
        "So weit, so gut.",
        "Fast fertig.",
        "Gleich geschafft.",
    ),
    "explore": (
        "Den Nagel auf den Kopf treffen.",
        "Aus dem Nähkästchen plaudern.",
    ),
    "error": (
        "Das ist nicht das Gelbe vom Ei.",
        "Irren ist menschlich.",
        "Aus Fehlern wird man klug.",
    ),
    "undo": (
        "Einmal ist keinmal.",
        "Alles wieder auf Anfang.",
        "Zurück auf Los.",
        "Den Reset-Knopf drücken.",
        "Schnee von gestern.",
        "Schwamm drüber.",
    ),
    "done": (
        "Wer zuletzt lacht, lacht am besten.",
        "Fertig.",
        "Geschafft.",
        "Saubere Arbeit.",
        "Gut gemacht.",
        "Läuft bei dir.",
    ),
    "signoff": (
        "Kaffee?",
        "Feierabend.",
        "Schluss für heute.",
        "Bis morgen.",
        "Gute Nacht.",
    ),
    "together": (),
    "guard": (
        "Vorsicht ist besser als Nachsicht.",
        "Die Katze im Sack kaufen.",
        "Vorsicht, das ist scharf.",
    ),
    "idle": (
        "In der Ruhe liegt die Kraft.",
        "Reden ist Silber, Schweigen ist Gold.",
        "Es ist, wie es ist.",
        "Ganz ruhig.",
        "Immer mit der Ruhe.",
        "Kein Stress.",
        "Kein Ding.",
        "Passt schon.",
        "Ich bin da.",
    ),
}
