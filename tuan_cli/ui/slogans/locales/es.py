"""Español (es) 标语 — 50 条, 按 10 个上下文分组。

风格: refranes + habla cotidiana。
分布: startup 3 · thinking 5 · explore 7 · error 3 · undo 4
      done 7 · signoff 4 · together 4 · guard 6 · idle 7
"""

from __future__ import annotations

GROUPS: dict[str, tuple[str, ...]] = {
    "startup": (
        "Despacio, que tengo prisa.",
        "Vísteme despacio, que tengo prisa.",
        "A buen hambre no hay pan duro.",
    ),
    "thinking": (
        "Del dicho al hecho hay gran trecho.",
        "Buscar una aguja en un pajar.",
        "Estar en ascuas.",
        "Poco a poco.",
        "Ahora mismo.",
    ),
    "explore": (
        "En casa de herrero, cuchillo de palo.",
        "Aunque la mona se vista de seda.",
        "A río revuelto, ganancia de pescadores.",
        "Tirar del hilo.",
        "Ver la luz.",
        "Caer del guindo.",
        "Dar en el clavo.",
    ),
    "error": (
        "Nadie es perfecto.",
        "Errar es humano.",
        "El que tropieza dos veces…",
    ),
    "undo": (
        "Agua que no has de beber, déjala correr.",
        "Borrón y cuenta nueva.",
        "Agua pasada no mueve molino.",
        "A lo hecho, pecho.",
    ),
    "done": (
        "Coser y cantar.",
        "Pan comido.",
        "Está chupado.",
        "Estar en la gloria.",
        "Ya está.",
        "Listo.",
        "Hecho.",
    ),
    "signoff": (
        "A otra cosa, mariposa.",
        "Vete a dormir.",
        "Mañana será otro día.",
        "Hasta mañana.",
    ),
    "together": (
        "Venga, vamos.",
        "Echar una mano.",
        "Tú mandas.",
        "Yo sujeto la escalera.",
    ),
    "guard": (
        "Más vale prevenir que curar.",
        "Más vale pájaro en mano.",
        "Perro ladrador, poco mordedor.",
        "Con la mosca detrás de la oreja.",
        "Cuidado, que pincha.",
        "No toques eso.",
    ),
    "idle": (
        "Más vale tarde que nunca.",
        "No por mucho madrugar amanece más temprano.",
        "Ojos que no ven, corazón que no siente.",
        "Ni fu ni fa.",
        "Sin prisa.",
        "¿Un café?",
        "Aquí estoy.",
    ),
}
