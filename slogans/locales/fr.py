"""Français (fr) 标语 — 50 条, 按 10 个上下文分组。

风格: proverbes + registre familier ("Ça marche" / "Tu gères")。
收工 (signoff) 与探索 (explore) 较少, 由通用池补齐。

分布: startup 5 · thinking 3 · explore 4 · error 2 · undo 6
      done 13 · signoff 2 · together 4 · guard 5 · idle 6
"""

from __future__ import annotations

GROUPS: dict[str, tuple[str, ...]] = {
    "startup": (
        "Petit à petit, l'oiseau fait son nid.",
        "Paris ne s'est pas fait en un jour.",
        "Qui va lentement va sûrement.",
        "Rien ne sert de courir.",
        "On y va.",
    ),
    "thinking": (
        "À bon chat, bon rat.",
        "Chercher une aiguille dans une botte de foin.",
        "Faire avec.",
    ),
    "explore": (
        "Tomber des nues.",
        "Mettre le doigt dessus.",
        "Voir clair.",
        "Tirer le fil.",
    ),
    "error": (
        "Mettre la charrue avant les bœufs.",
        "L'erreur est humaine.",
    ),
    "undo": (
        "Après la pluie, le beau temps.",
        "Repartir à zéro.",
        "Faire table rase.",
        "L'eau a coulé sous les ponts.",
        "Tourner la page.",
        "C'est du passé.",
    ),
    "done": (
        "Petite pluie abat grand vent.",
        "Ce n'est pas la mer à boire.",
        "C'est du gâteau.",
        "Simple comme bonjour.",
        "Ça marche.",
        "C'est bon.",
        "Voilà.",
        "Et voilà.",
        "Terminé.",
        "Fini.",
        "C'est fait.",
        "Beau travail.",
        "Bravo.",
    ),
    "signoff": (
        "Va te coucher.",
        "À demain.",
    ),
    "together": (
        "Allons-y.",
        "À deux, c'est mieux.",
        "Je m'en occupe.",
        "Tu gères.",
    ),
    "guard": (
        "Un tiens vaut mieux que deux tu l'auras.",
        "Prudence est mère de sûreté.",
        "Mieux vaut prévenir que guérir.",
        "Attention, ça pique.",
        "Ne touche pas à ça.",
    ),
    "idle": (
        "Mieux vaut tard que jamais.",
        "À l'impossible nul n'est tenu.",
        "Doucement.",
        "Tranquille.",
        "Pas de souci.",
        "Je suis là.",
    ),
}
