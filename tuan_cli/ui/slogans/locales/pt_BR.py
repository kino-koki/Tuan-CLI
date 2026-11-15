"""Português (BR) 标语 — 50 条, 按 10 个上下文分组。

风格: ditados + gíria coloquial ("De boa" / "Tá sussa" / "Eita")。
协作 (together) 表达较少, 由通用池补齐。

分布: startup 3 · thinking 4 · explore 4 · error 6 · undo 5
      done 11 · signoff 3 · together 2 · guard 4 · idle 8
"""

from __future__ import annotations

GROUPS: dict[str, tuple[str, ...]] = {
    "startup": (
        "Devagar se vai ao longe.",
        "A pressa é inimiga da perfeição.",
        "Bora.",
    ),
    "thinking": (
        "Água mole em pedra dura, tanto bate até que fura.",
        "Quem não tem cão, caça com gato.",
        "Fazer das tripas coração.",
        "Procurar agulha em palheiro.",
    ),
    "explore": (
        "Achei.",
        "Olha só.",
        "Que isso.",
        "Sério?",
    ),
    "error": (
        "Enxugar gelo.",
        "Chover no molhado.",
        "Dar com os burros n'água.",
        "Errar é humano.",
        "Vixe.",
        "Eita.",
    ),
    "undo": (
        "Não adianta chorar pelo leite derramado.",
        "Água passada não move moinho.",
        "Começar de novo.",
        "Fazer tábula rasa.",
        "Voltar à estaca zero.",
    ),
    "done": (
        "É isso aí.",
        "Ficou bom.",
        "Ficou show.",
        "Mandou bem.",
        "Arrasou.",
        "Caprichou.",
        "Deu certo.",
        "Pronto.",
        "Feito.",
        "Tá pronto.",
        "Deu bom.",
    ),
    "signoff": (
        "Um café?",
        "Vai dormir.",
        "Até amanhã.",
    ),
    "together": (
        "Cada macaco no seu galho.",
        "Vamos nessa.",
    ),
    "guard": (
        "Mais vale um pássaro na mão.",
        "Macaco velho não mete a mão em cumbuca.",
        "Cuidado, isso machuca.",
        "Não mexe aí.",
    ),
    "idle": (
        "Devagar com o andor.",
        "Tudo bem.",
        "De boa.",
        "Suave.",
        "Na paz.",
        "Sem pressa.",
        "Tá tranquilo.",
        "Tá sussa.",
    ),
}
