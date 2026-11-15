"""扩展场景的本地化补池 — 8 语种 × 6 场景 × 5 条 = 240 条。

为什么单独成文件 (而不是改 ``extra.LOCALES``):

- ``extra.py`` 的 docstring 明确要求「**不改动主体编号与数量**」。原
  ``extra.LOCALES`` 只有 ``zh-CN`` 与 ``en`` 两个语种，其余 8 语种的
  6 个扩展场景全部回落英文通用池 —— 实测 ``pick("bg.progress", lang="ja")``
  返回 ``"Still at it."``，日语用户看到英文。
- 本模块只**追加**，不重排、不删改原有 60 条通用英文与 10 条中/英扩展，
  让 48 个 (语种, 上下文) 组合第一次拥有本语种词条。
- ``picker.pool()`` 合并 ``extra.LOCALES`` 与本模块，顺序保持
  「本语种在前、通用英文在后」，英文通用池仍是最后的兜底。

每条都对应 ``mapping.EVENT_BINDINGS`` 里唯一一个真实运行时事件，
``mapping.audit()`` 会逐条核验「无孤儿标语 / 无无标语事件」。
"""

from __future__ import annotations

from typing import Dict, Tuple

#: 补齐的语种 (其余 2 个已在 extra.LOCALES 中)
LANGUAGES: Tuple[str, ...] = (
    "zh-TW", "ja", "ko", "es", "pt-BR", "fr", "de", "ru",
)

LOCALES: Dict[str, Dict[str, Tuple[str, ...]]] = {
    # ---------------------------------------------------------------- zh-TW
    "zh-TW": {
        "model.switch": (
            "換了個人，還是這間屋。", "換手了。", "另一雙手。",
            "換了個腦子。", "接著說。",
        ),
        "budget.warn": (
            "錢包在變薄。", "看看表。", "這個貴一點。",
            "快到線了。", "花得有點快。",
        ),
        "bg.start": (
            "它自己跑了。", "你先忙去。", "交給背景。",
            "先讓它跑著。", "派出去了。",
        ),
        "bg.progress": (
            "還在跑。", "沒消息，就是還在忙。", "這個慢。",
            "慢慢來。", "還早。",
        ),
        "pairing": (
            "兩塊螢幕，一間屋。", "連上了。", "手機進來了。",
            "握過手了。", "一條線，兩頭。",
        ),
        "memory.write": (
            "記下了。", "收好了。", "寫著呢。",
            "存起來了。", "只記這一句。",
        ),
    },
    # ---------------------------------------------------------------- ja
    "ja": {
        "model.switch": (
            "声が変わった、部屋は同じ。", "交代しました。", "別の手に。",
            "レンズを替えた。", "続きをどうぞ。",
        ),
        "budget.warn": (
            "財布が軽くなった。", "メーターを見て。", "これは少し高い。",
            "もうすぐ上限。", "出費が速い。",
        ),
        "bg.start": (
            "あとは勝手に動きます。", "先にどうぞ。", "裏に回しました。",
            "走らせておきます。", "送り出しました。",
        ),
        "bg.progress": (
            "まだ動いてる。", "便りがない＝まだ作業中。", "これは長い。",
            "時間がかかる。", "まだ先です。",
        ),
        "pairing": (
            "二つの画面、一部屋。", "つながった。", "スマホが入った。",
            "握手済み。", "一本の糸、両端。",
        ),
        "memory.write": (
            "メモした。", "しまった。", "書き留めた。",
            "取っておいた。", "これだけ覚えた。",
        ),
    },
    # ---------------------------------------------------------------- ko
    "ko": {
        "model.switch": (
            "목소리가 바뀌었어, 방은 그대로.", "교대했어.", "다른 손이야.",
            "렌즈를 갈았어.", "이어서 말해 줘.",
        ),
        "budget.warn": (
            "지갑이 가벼워졌어.", "계량기를 봐.", "이건 좀 비싸.",
            "한도에 가까워.", "쓰는 속도가 빠르다.",
        ),
        "bg.start": (
            "이제 알아서 돌아가.", "먼저 하던 일 해.", "뒤로 보냈어.",
            "돌려놓을게.", "보냈어.",
        ),
        "bg.progress": (
            "아직 가는 중.", "소식 없으면 아직 하는 중.", "이건 오래 걸려.",
            "천천히 가자.", "아직 이르다.",
        ),
        "pairing": (
            "화면 둘, 방 하나.", "연결됐어.", "폰이 들어왔어.",
            "악수했어.", "한 줄, 양 끝.",
        ),
        "memory.write": (
            "적어 뒀어.", "잘 넣어 뒀어.", "기록 중.",
            "보관했어.", "이 한 줄만.",
        ),
    },
    # ---------------------------------------------------------------- es
    "es": {
        "model.switch": (
            "Otra voz, la misma habitación.", "Cambio de manos.", "Otras manos.",
            "Lente nueva.", "Sigue, por favor.",
        ),
        "budget.warn": (
            "La cartera pesa menos.", "Mira el contador.", "Este sale más caro.",
            "Casi en la raya.", "Se va rápido.",
        ),
        "bg.start": (
            "Ya corre solo.", "Tú sigue a lo tuyo.", "Lo dejé en segundo plano.",
            "Que siga corriendo.", "Enviado.",
        ),
        "bg.progress": (
            "Sigue en ello.", "Sin noticias, sigue trabajando.", "Este es largo.",
            "Se toma su tiempo.", "Aún queda.",
        ),
        "pairing": (
            "Dos pantallas, una habitación.", "Conectado.", "El móvil ya está.",
            "Nos dimos la mano.", "Un hilo, dos puntas.",
        ),
        "memory.write": (
            "Anotado.", "Guardado.", "Lo estoy escribiendo.",
            "Apartado con cuidado.", "Solo eso.",
        ),
    },
    # ---------------------------------------------------------------- pt-BR
    "pt-BR": {
        "model.switch": (
            "Outra voz, mesma sala.", "Trocou de mão.", "Outras mãos.",
            "Lente nova.", "Pode continuar.",
        ),
        "budget.warn": (
            "A carteira está mais leve.", "Olha o medidor.", "Esse sai mais caro.",
            "Perto da linha.", "Tá gastando rápido.",
        ),
        "bg.start": (
            "Já roda sozinho.", "Vai cuidar das suas coisas.", "Mandei pro fundo.",
            "Deixa rodando.", "Despachei.",
        ),
        "bg.progress": (
            "Ainda rodando.", "Sem notícia, ainda trabalhando.", "Esse é demorado.",
            "Leva o tempo dele.", "Ainda cedo.",
        ),
        "pairing": (
            "Duas telas, um quarto.", "Conectou.", "O celular entrou.",
            "Cumprimento feito.", "Um fio, duas pontas.",
        ),
        "memory.write": (
            "Anotado.", "Guardado.", "Escrevendo.",
            "Separei com cuidado.", "Só isso.",
        ),
    },
    # ---------------------------------------------------------------- fr
    "fr": {
        "model.switch": (
            "Une autre voix, même pièce.", "On a changé de main.", "D'autres mains.",
            "Nouvelle lentille.", "Continuez.",
        ),
        "budget.warn": (
            "Le portefeuille s'allège.", "Regarde le compteur.", "Celui-ci coûte plus.",
            "Presque à la limite.", "Ça dépense vite.",
        ),
        "bg.start": (
            "Ça tourne tout seul maintenant.", "Vaquez à vos affaires.", "Passé en arrière-plan.",
            "Laissez tourner.", "Envoyé.",
        ),
        "bg.progress": (
            "Toujours en cours.", "Pas de nouvelles, toujours au travail.", "Celui-là est long.",
            "Il prend son temps.", "Encore tôt.",
        ),
        "pairing": (
            "Deux écrans, une pièce.", "Connecté.", "Le téléphone est là.",
            "Poignée de main faite.", "Un fil, deux bouts.",
        ),
        "memory.write": (
            "Noté.", "Rangé.", "Je l'écris.",
            "Mis de côté.", "Rien que ça.",
        ),
    },
    # ---------------------------------------------------------------- de
    "de": {
        "model.switch": (
            "Neue Stimme, gleicher Raum.", "Handwechsel.", "Andere Hände.",
            "Neue Brille auf.", "Weiter im Text.",
        ),
        "budget.warn": (
            "Der Geldbeutel wird leichter.", "Auf die Uhr schauen.", "Das kostet mehr.",
            "Nah an der Linie.", "Geht schnell ins Geld.",
        ),
        "bg.start": (
            "Läuft jetzt allein.", "Mach du mal weiter.", "Nach hinten geschickt.",
            "Laufen lassen.", "Abgeschickt.",
        ),
        "bg.progress": (
            "Läuft noch.", "Keine Nachricht, noch bei der Arbeit.", "Das dauert.",
            "Braucht seine Zeit.", "Noch früh.",
        ),
        "pairing": (
            "Zwei Bildschirme, ein Raum.", "Verbunden.", "Das Handy ist da.",
            "Hände geschüttelt.", "Ein Faden, zwei Enden.",
        ),
        "memory.write": (
            "Notiert.", "Weggelegt.", "Schreibe es auf.",
            "Sicher verwahrt.", "Nur das eine.",
        ),
    },
    # ---------------------------------------------------------------- ru
    "ru": {
        "model.switch": (
            "Другой голос, та же комната.", "Сменились руки.", "Другие руки.",
            "Новая оптика.", "Продолжайте.",
        ),
        "budget.warn": (
            "Кошелёк легчает.", "Посмотри на счётчик.", "Этот подороже.",
            "Почти у черты.", "Быстро уходит.",
        ),
        "bg.start": (
            "Теперь само работает.", "Займись своим.", "Отправил в фон.",
            "Пусть идёт.", "Запущено.",
        ),
        "bg.progress": (
            "Ещё работает.", "Вестей нет — значит, ещё работает.", "Это надолго.",
            "Берёт своё время.", "Ещё рано.",
        ),
        "pairing": (
            "Два экрана, одна комната.", "Связались.", "Телефон подключён.",
            "Пожали руки.", "Одна нить, два конца.",
        ),
        "memory.write": (
            "Записал.", "Убрал на место.", "Записываю.",
            "Отложил аккуратно.", "Только это.",
        ),
    },
}


def count() -> int:
    """补池条目总数 (期望 240)。"""
    return sum(len(v) for lang in LOCALES.values() for v in lang.values())
