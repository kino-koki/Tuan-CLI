# -*- coding: utf-8 -*-
"""运行时标语（spinner verbs）—— Claude Code 同款，但中文不装忙。

背景
----
Claude Code 转圈时会在 spinner 旁随机显示一个英文动名词
（``Marinating…`` / ``Lollygagging…`` / ``Whatchamacalliting…``），
v2.1.42 内置约 185 个，``~/.claude/settings.json`` 的
``spinnerVerbs: {mode: replace|append, verbs: [...]}`` 可定制（官方文档不收录
这份词表，属 UI 彩蛋）。中文社区把整份词表翻成中文后，
「游手好闲 / 磨洋工 / 溜达 / 撒欢」集体露馅 —— 这就是
「给转圈的英文挂上中文后，我发现它在摸鱼」那个梗。

本模块做同款，**并修掉梗背后的真实缺陷**：上游那些词只是 spinner 动画的
随机装饰，**不代表任何阶段，也不代表任何进展**。所以「看起来在忙」和
「真的在动」是两件事。这里：

1. 每条标语**绑定到真实运行时事件**（提交 / 流式分片 / 工具开始 / 重试）；
   阶段不变且没超间隔时不换词 —— 不靠定时器空转制造「很忙」的假象。
2. 忙碌中若超过 ``stall_ms`` 收不到任何真实事件，中文会**如实**显示
   「疑似摸鱼」诊断并带上静默秒数，而不是继续换词装忙。这既是视频梗的
   本地化，也是一条能帮用户发现「卡在网络 / 死循环」的真实诊断。
3. 十种界面语言全覆盖，**不把 fallback 冒充本地化**；中文词池保留
   「腌制入味 / 磨洋工 / 看报纸中 / 那个啥来着」这批摸鱼梗。
4. 自定义词来自 ``~/.tuan/settings.json`` 的 ``spinnerVerbs``（键名与上游
   同款，方便迁移），并在写入终端前**严格净化 ESC / OSC / C0 / C1 控制
   字符** —— 标语是要渲染到终端的文本，不能变成转义序列注入口。

纯标准库、无 I/O 副作用（除首次加载配置）、可注入 clock / rng 做确定性测试。

**深度轮（不再扩广度）**：上版把「事件驱动」做成了「绑 3 个事件 + 一个固定
15 秒阈值」，其实还是很浅。本轮把同一条线往下挖四层，不新增任何模块或指标：

D1 **并发正确性**。`note_activity` 会从 UI 线程（submit）、模型线程（流式）、
   工具线程（begin_tool）并发进入，`render` 从动画 invalidate 线程进入。
   五个可变字段是无锁复合读写，GIL 只保证单条赋值原子 ——
   ``self._current = ...`` 与 ``self._seq += 1`` 之间会切线程，
   出现「新 seq + 旧文案」的撕裂，或间隔判断读到半更新的时间戳。
   现在全部公开方法在 ``RLock`` 内线性化，并把每次转移记成不可变证据。

D2 **分阶段活性预算**。单一 15s 阈值把「等模型首 token」和「流式分片断了」
   混为一谈：前者 30s 正常，后者 6s 就该提示。改成
   ``PHASE_BUDGET_MS`` 分阶段预算 + ``slow_ratio`` 三态
   （healthy / slow / stalled），诊断才不是定时乱报。

D3 **结构化判定 + 脱敏证据链**。``liveness()`` 返回可测、可回放、可接 UI 的
   快照（阶段 / 静默时长 / 预算 / 剩余 / 建议 / 最近事件），文案只是它的渲染。
   证据只记阶段、类型、时间、序号、当前文案与 detail 的**长度和字符类别**，
   绝不记 detail 原文 —— 它可能含工具参数或路径。

D4 **事件覆盖补全**。新增 ``note_progress()``：只刷新活性时间戳，不改阶段、
   不换词。给 ``end_tool`` / ``end_stream`` / 中断等生命周期点用，
   避免「工具结束到下一事件之间」被误判为无进展。
   刻意**不**从 ``_animate`` 调用它 —— 那会把诚实诊断退回定时空转。

另外补 ``reload()`` 显式热重载（失败保留旧配置、原子切换、不轮询文件），
以及 ``reset()`` 跨回合保留证据链，使「上一回合为什么卡住」可回放。

**深度轮 11（继续只挖深度）**：上一轮把引擎 public 入参面收口，本轮
把镜头对准**注入契约与配置切换的锚点**：A ``__init__`` 的 ``or`` 吞掉
falsy 但合法的 ``config`` / ``rng`` 注入；B ``load_config`` 把 205 条
自定义词静默截成 200；C ``mode=default`` 下自定义词全不可渲染时静默
忽略；D **最值钱** —— ``reload()`` 清 ``_current`` 却不推进 ``seq`` /
不记证据，让同一个 seq 对应两个文案，打断 D1 的 ``(seq, verb)``
撕裂检测锚点，且 ``unchanged`` 也静默换词。四个「不该修」候选
（``lang`` 的 ``or``、``phase_budgets_ms`` 的 ``[:10]``、
``snapshot()`` 写 ``_pools``、``evidence_seq`` 饱和语义）实测后锁成
回归。详见 ``SLOGAN_MAPPING.md`` §20。
"""
from __future__ import annotations

import json
import math
import os
import random
import re
import threading
import time
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "PHASES", "LANGUAGES", "PHASE_BUDGET_MS", "LivenessState",
    "SpinnerVerbsConfig", "EventRecord", "Liveness", "SloganView",
    "RuntimeSloganEngine", "load_config", "slogan_bank", "sanitize_verb",
    "display_cols", "MAX_SETTINGS_BYTES",
]

# ------------------------------------------------------------------ 阶段

#: 真实运行时阶段；不是「动画帧」，必须由事件驱动。
PHASES: Tuple[str, ...] = (
    "booting",        # 启动 / 加载内核
    "waiting_model",  # 已提交，等模型首个 token
    "streaming",      # 正在接收流式分片
    "running_tool",   # 工具/命令执行中
    "retrying",       # 失败重试 / 回炉
)

LANGUAGES: Tuple[str, ...] = (
    "zh-CN", "zh-TW", "en", "ja", "ko", "es", "pt-BR", "fr", "de", "ru",
)

# ------------------------------------------------------------------ 词库
#
# 每个语言、每个阶段一组。中文 waiting_model 故意混入「摸鱼梗」词条：
# 挂上中文后应当能复现视频里的笑点；但引擎的 stall 诊断会在真的没进展时
# 把「装忙」揭穿，幽默和诚实各归其位。

_BANK: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "zh-CN": {
        "booting": ("正在起身", "正在热锅", "正在铺开摊子", "正在点灯",
                    "正在把摊子支起来", "正在醒面"),
        "waiting_model": (
            "正在琢磨", "正在沉吟", "正在反刍", "正在盘算", "正在想词儿",
            "正在等模型回话", "正在假装思考", "正在发呆式推理",
            # ↓ 摸鱼梗：与中文社区 185 词翻译同款
            "正在腌制入味", "正在磨洋工", "正在溜溜达达", "正在看报纸中",
            "正在光合作用中", "正在闲庭信步", "正在那个啥来着", "正在撒欢",
        ),
        "streaming": ("正在往外吐字", "正在码字", "正写到兴头上", "正在倾泻",
                      "正在边想边说", "正在刷屏", "正在一字一顿", "正在续写"),
        "running_tool": ("正在搬砖", "正在跑命令", "正在翻文件", "正在动真格",
                         "正在敲键盘", "正在调工具", "正在实打实干", "正在落地"),
        "retrying": ("正在再试一次", "正在回炉", "正在换个姿势", "正在补救",
                     "正在把碎的拼回去", "正在绕路"),
    },
    "zh-TW": {
        "booting": ("正在起身", "正在熱鍋", "正在把攤子架起來", "正在點燈"),
        "waiting_model": ("正在琢磨", "正在沉吟", "正在反芻", "正在等模型回話",
                          "正在醃製入味", "正在摸魚", "正在溜達", "正在看報紙中",
                          "正在光合作用中", "正在那個啥來著"),
        "streaming": ("正在吐字", "正在碼字", "正寫到興頭上", "正在邊想邊說"),
        "running_tool": ("正在搬磚", "正在跑指令", "正在翻檔案", "正在動真格"),
        "retrying": ("正在再試一次", "正在回爐", "正在換個姿勢", "正在補救"),
    },
    "en": {
        "booting": ("Booting", "Warming up", "Setting up shop", "Lighting up"),
        "waiting_model": ("Pondering", "Cogitating", "Ruminating", "Marinating",
                          "Lollygagging", "Dilly-dallying", "Photosynthesizing",
                          "Whatchamacalliting", "Waiting on the model"),
        "streaming": ("Streaming", "Writing", "Spilling words", "Unfurling"),
        "running_tool": ("Running tool", "Crunching", "Digging through files",
                         "Getting hands dirty"),
        "retrying": ("Retrying", "Reworking", "Trying another angle", "Patching up"),
    },
    "ja": {
        "booting": ("起き上がり中", "準備中", "店開き中", "灯りを入れ中"),
        "waiting_model": ("思案中", "沈思中", "反芻中", "漬け込み中",
                          "サボり中", "ぶらぶら中", "新聞読み中", "光合成中",
                          "モデルの返事待ち中"),
        "streaming": ("書き出し中", "文字を吐き出し中", "筆が乗り中", "綴り中"),
        "running_tool": ("道具を実行中", "ファイルを漁り中", "本気出し中", "実装中"),
        "retrying": ("再試行中", "やり直し中", "別の角度から中", "立て直し中"),
    },
    "ko": {
        "booting": ("일어나는 중", "준비 중", "자리 펴는 중", "불 켜는 중"),
        "waiting_model": ("고민 중", "숙고 중", "되새기는 중", "재우는 중",
                          "땡땡이 중", "어슬렁거리는 중", "신문 보는 중",
                          "광합성 중", "모델 답 기다리는 중"),
        "streaming": ("글 쏟아내는 중", "작성 중", "한 자씩 쓰는 중", "이어 쓰는 중"),
        "running_tool": ("도구 실행 중", "파일 뒤지는 중", "진짜 일하는 중", "적용 중"),
        "retrying": ("다시 시도 중", "되돌아가기 중", "다른 각도로 중", "수습 중"),
    },
    "es": {
        "booting": ("Arrancando", "Calentando", "Montando el puesto", "Encendiendo"),
        "waiting_model": ("Meditando", "Rumiando", "Marinando", "Holgazaneando",
                          "Dando vueltas", "Fotosintetizando", "Esperando al modelo",
                          "Haciendo el vago"),
        "streaming": ("Escribiendo", "Soltando palabras", "Desplegando", "Continuando"),
        "running_tool": ("Ejecutando herramienta", "Revisando archivos", "Manos a la obra",
                         "Aterrizando"),
        "retrying": ("Reintentando", "Rehaciendo", "Probando otro ángulo", "Remendando"),
    },
    "pt-BR": {
        "booting": ("Levantando", "Aquecendo", "Abrindo a banca", "Acendendo"),
        "waiting_model": ("Pensando", "Ruminando", "Marinando", "Enrolando",
                          "Batendo perna", "Fotossintetizando", "Esperando o modelo",
                          "Fazendo hora"),
        "streaming": ("Escrevendo", "Despejando palavras", "Desdobrando", "Continuando"),
        "running_tool": ("Rodando ferramenta", "Vasculhando arquivos", "Mão na massa",
                         "Aterrissando"),
        "retrying": ("Tentando de novo", "Refazendo", "Por outro ângulo", "Remendando"),
    },
    "fr": {
        "booting": ("Au démarrage", "On chauffe", "On installe l'étal", "On allume"),
        "waiting_model": ("En pleine réflexion", "On rumine", "On marine", "On flâne",
                          "On traîne", "Photosynthèse en cours", "En attente du modèle",
                          "On tire au flanc"),
        "streaming": ("Ça couche du texte", "Rédaction", "Ça se déploie", "On continue"),
        "running_tool": ("Outil en cours", "On fouille les fichiers", "Mains à la pâte",
                         "On atterrit"),
        "retrying": ("On réessaie", "On remet sur le métier", "Autre angle", "On rafistole"),
    },
    "de": {
        "booting": ("Startet", "Wärmt auf", "Baut den Stand auf", "Macht Licht"),
        "waiting_model": ("Grübelt", "Kaut wieder", "Mariniert", "Bummelt",
                          "Trödelt", "Betreibt Photosynthese", "Wartet aufs Modell",
                          "Macht blau"),
        "streaming": ("Schreibt", "Lässt Worte fließen", "Rollt aus", "Führt fort"),
        "running_tool": ("Werkzeug läuft", "Wühlt in Dateien", "Packt richtig an",
                         "Setzt um"),
        "retrying": ("Versucht es erneut", "Nochmal von vorn", "Anderer Winkel",
                     "Flickt zusammen"),
    },
    "ru": {
        "booting": ("Поднимается", "Разогревается", "Раскладывается", "Зажигает свет"),
        "waiting_model": ("Размышляет", "Пережёвывает", "Маринуется", "Бездельничает",
                          "Прохаживается", "Фотосинтезирует", "Ждёт ответ модели",
                          "Газету читает"),
        "streaming": ("Пишет", "Выдаёт слова", "Разворачивает", "Продолжает"),
        "running_tool": ("Запускает инструмент", "Роется в файлах", "Берётся за дело",
                         "Приземляет"),
        "retrying": ("Пробует снова", "Переделывает", "С другого бока", "Латает"),
    },
}

# ------------------------------------------------------------------ 诊断文案

#: 忙碌但长时间无任何真实进展时的诊断文案。{sec} 会被静默秒数替换。
#: 刻意保持**单行短文案**：header 是 height=1 控件，_clip_parts 会硬裁，
#: 完整阶段信息与可操作建议放在 Liveness.diagnostic / .advice 里，不塞进这行。
_STALL_TEXT: Dict[str, str] = {
    "zh-CN": "疑似摸鱼 · 已 {sec}s 没收到模型/工具/流式的任何动静",
    "zh-TW": "疑似摸魚 · 已 {sec}s 沒收到模型/工具/串流的任何動靜",
    "en": "Possibly slacking · no model/tool/stream event for {sec}s",
    "ja": "サボり疑い · {sec} 秒間モデル/ツール/ストリームの進展なし",
    "ko": "땡땡이 의심 · {sec}초간 모델/도구/스트림 소식 없음",
    "es": "Posible holgazanería · sin eventos de modelo/herramienta/flujo por {sec}s",
    "pt-BR": "Possível enrolação · sem evento de modelo/ferramenta/fluxo por {sec}s",
    "fr": "Ça flâne peut-être · aucun événement modèle/outil/flux depuis {sec}s",
    "de": "Möglicherweise blau · seit {sec}s kein Modell-/Werkzeug-/Stream-Ereignis",
    "ru": "Похоже, бездельничает · {sec} с без событий модели/инструмента/потока",
}

#: header 用的**短版**诊断（完整版是 ``Liveness.diagnostic``）。
#: 上一轮文档写了「header 只显示短文案」，但 ``render()`` 实际把
#: ``_STALL_TEXT`` 整串塞了进去 —— 中文约 26 个 CJK ≈ 52 列，
#: 比 ``_MAX_VERB_COLS``(40) 还长，窄终端下关键秒数直接被 ``_clip_parts``
#: 裁没。更根本的是：**内置诊断文案绕过了 ``sanitize_verb`` 的宽度/不可见
#: 字符约束**，等于净化层留了一道侧门。现在短版与自定义词走同一条
#: ``_fit_headline()`` 通道。
_STALL_SHORT: Dict[str, str] = {
    "zh-CN": "疑似摸鱼 · {sec}s 无进展",
    "zh-TW": "疑似摸魚 · {sec}s 無進展",
    "en": "Possibly slacking · {sec}s idle",
    "ja": "サボり疑い · {sec}秒 無進展",
    "ko": "땡땡이 의심 · {sec}초 무진행",
    "es": "Posible holgazanería · {sec}s sin avance",
    "pt-BR": "Possível enrolação · {sec}s sem progresso",
    "fr": "Ça flâne peut-être · {sec}s sans progrès",
    "de": "Möglicherweise blau · {sec}s ohne Fortschritt",
    "ru": "Похоже, бездельничает · {sec} с без прогресса",
}

#: 阶段 -> 诊断类别。决定该给哪一类可操作建议，而不是所有阶段都劝人查网络。
_PHASE_KIND: Dict[str, str] = {
    "booting": "model", "waiting_model": "model", "retrying": "model",
    "streaming": "stream", "running_tool": "tool",
}

#: 可操作建议（10 语言 × 3 类）。只进结构化字段与诊断行，不进 header 短文案。
_ADVICE_TEXT: Dict[str, Dict[str, str]] = {
    "zh-CN": {"model": "等模型首个响应：检查网络/模型服务，或 Esc 中断",
              "stream": "流式输出中断：Esc 中断后重试，或检查连接",
              "tool": "工具执行中：长命令属正常，Esc 可中断；持续无输出再查进程"},
    "zh-TW": {"model": "等模型首個回應：檢查網路/模型服務，或 Esc 中斷",
              "stream": "串流輸出中斷：Esc 中斷後重試，或檢查連線",
              "tool": "工具執行中：長指令屬正常，Esc 可中斷；持續無輸出再查行程"},
    "en": {"model": "waiting for first token: check network/model, or press Esc",
           "stream": "stream stalled: press Esc and retry, or check the connection",
           "tool": "tool still running: long commands are normal; Esc interrupts"},
    "ja": {"model": "初回トークン待ち：ネットワーク/モデルを確認、または Esc で中断",
           "stream": "ストリーム停止：Esc で中断して再試行、または接続を確認",
           "tool": "ツール実行中：長時間は正常、Esc で中断可"},
    "ko": {"model": "첫 토큰 대기: 네트워크/모델 확인 또는 Esc 로 중단",
           "stream": "스트림 중단: Esc 로 중단 후 재시도 또는 연결 확인",
           "tool": "도구 실행 중: 긴 명령은 정상, Esc 로 중단 가능"},
    "es": {"model": "esperando el primer token: revisa red/modelo o pulsa Esc",
           "stream": "flujo interrumpido: pulsa Esc y reintenta, o revisa la conexión",
           "tool": "herramienta en curso: los comandos largos son normales; Esc interrumpe"},
    "pt-BR": {"model": "aguardando o primeiro token: verifique rede/modelo ou pressione Esc",
              "stream": "fluxo interrompido: pressione Esc e tente de novo, ou verifique a conexão",
              "tool": "ferramenta em execução: comandos longos são normais; Esc interrompe"},
    "fr": {"model": "en attente du premier jeton : vérifiez réseau/modèle ou Appuyez sur Échap",
           "stream": "flux interrompu : Échap puis réessayez, ou vérifiez la connexion",
           "tool": "outil en cours : les commandes longues sont normales ; Échap interrompt"},
    "de": {"model": "Warten auf erstes Token: Netzwerk/Modell prüfen oder Esc drücken",
           "stream": "Stream unterbrochen: Esc und erneut versuchen, oder Verbindung prüfen",
           "tool": "Werkzeug läuft: lange Befehle sind normal; Esc bricht ab"},
    "ru": {"model": "ожидание первого токена: проверьте сеть/модель или нажмите Esc",
           "stream": "поток прерван: Esc и повторите, или проверьте соединение",
           "tool": "инструмент работает: долгие команды нормальны; Esc прерывает"},
}

#: 阶段 -> 「慢」的措辞（进完整诊断行，不进 header）。
_SLOW_TEXT: Dict[str, str] = {
    "zh-CN": "比预期慢", "zh-TW": "比預期慢", "en": "slower than expected",
    "ja": "想定より遅い", "ko": "예상보다 느림", "es": "más lento de lo previsto",
    "pt-BR": "mais lento que o esperado", "fr": "plus lent que prévu",
    "de": "langsamer als erwartet", "ru": "медленнее ожидаемого",
}

# ------------------------------------------------------------------ 活性预算

#: 各阶段「多久没有真实事件才算异常」。这是 D2 的核心：单一 15s 太浅。
#: 等模型首 token 最慢，流式分片断了最快暴露，长命令工具本就该跑很久。
PHASE_BUDGET_MS: Dict[str, int] = {
    "booting": 30_000,
    "waiting_model": 45_000,
    "streaming": 6_000,
    "running_tool": 120_000,
    "retrying": 20_000,
}
_DEFAULT_SLOW_RATIO = 0.5
_EVIDENCE_CAPACITY = 16


class LivenessState:
    HEALTHY = "healthy"
    SLOW = "slow"
    STALLED = "stalled"
    UNKNOWN = "unknown"   # busy 但从未收到任何真实事件 —— 本身就是异常


@dataclass(frozen=True)
class EventRecord:
    """一条**脱敏**证据：只记形状，绝不记 detail 原文。

    ``detail`` 可能来自 ``begin_tool(name)`` 乃至未来的工具参数，
    直接落诊断日志会泄露路径/命令。这里只保留长度与字符类别。
    ``verb`` 是当前已净化的标语，用于核验「同一 seq 只对应一个文案」
    （D1 的撕裂检测就靠这个不变量）。
    """
    phase: str
    kind: str                 # activity | progress | reset
    at_ms: int                # time.monotonic() 毫秒，不含墙钟时间
    seq: int
    verb: str
    detail_len: int
    detail_class: str         # empty | ascii | cjk | mixed


def _detail_class(s: str) -> str:
    if not s:
        return "empty"
    has_cjk = any(unicodedata.east_asian_width(c) in ("W", "F") for c in s)
    has_ascii = any(ord(c) < 128 for c in s)
    if has_cjk and has_ascii:
        return "mixed"
    return "cjk" if has_cjk else "ascii"


# ------------------------------------------------------------------ 净化
#
# 净化层已抽到 ``tuan_cli/ui/slogans/_clean.py``: 新标语库的 1105 条词条
# 与活性引擎的诊断文案共用**同一个函数对象**, 不产生第三套宽度/净化真值。
# ``mapping.audit()`` 会断言 ``sanitize_verb is _clean.sanitize_verb``。
from ..ui.slogans._clean import (  # noqa: F401  (re-export, 保持旧 API)
    _CSI_RE, _CTRL_RE, _DROP_CATEGORIES, _ESC_SEQ_RE,
    _MAX_VERB_CHARS, _MAX_VERB_COLS, _OSC_RE,
    _clusters, _fit_headline, _is_variation_selector, _sanitize_once,
    display_cols, sanitize_log_field, sanitize_verb,
)

def slogan_bank(lang: str) -> Dict[str, Tuple[str, ...]]:
    """返回该语言的完整词库；未知语言回退英文（调用方负责显式选择语言）。"""
    return _BANK.get(lang, _BANK["en"])


# ------------------------------------------------------------------ 配置

_VALID_MODES = ("default", "append", "replace", "off")
_DEFAULT_INTERVAL_MS = 1800
_DEFAULT_STALL_MS = 15000


@dataclass(frozen=True)
class SpinnerVerbsConfig:
    """与上游同款的 ``spinnerVerbs`` 配置，额外带本地化与活性预算开关。

    向后兼容：只写 ``mode / verbs / interval_ms / stall_ms`` 的旧配置照常生效。
    **显式给出 ``stall_ms`` 会被当作全局预算覆盖**（尊重用户设置）；不给时
    才走 ``PHASE_BUDGET_MS`` 分阶段表。分阶段表可用 ``phase_budgets_ms``
    逐项覆盖，``slow_ratio`` 控制「慢」提示的触发比例。
    """
    mode: str = "default"
    verbs: Tuple[str, ...] = ()
    interval_ms: int = _DEFAULT_INTERVAL_MS
    stall_ms: int = _DEFAULT_STALL_MS
    phase_budgets_ms: Tuple[Tuple[str, int], ...] = ()   # frozen 友好，不用 dict
    slow_ratio: float = _DEFAULT_SLOW_RATIO
    stall_ms_override: Optional[int] = None
    source: str = "builtin"

    def __post_init__(self) -> None:
        if self.mode not in _VALID_MODES:
            raise ValueError(f"spinnerVerbs.mode 非法: {self.mode!r}")
        if not (200 <= self.interval_ms <= 60000):
            raise ValueError("interval_ms 超出 [200, 60000]")
        if not (1000 <= self.stall_ms <= 600000):
            raise ValueError("stall_ms 超出 [1000, 600000]")
        if not (0.1 <= self.slow_ratio <= 0.9):
            raise ValueError("slow_ratio 超出 [0.1, 0.9]")
        if any(v == "" for v in self.verbs):
            raise ValueError("净化后存在空标语")
        for key, val in self.phase_budgets_ms:
            if key not in PHASES:
                raise ValueError(f"phase_budgets_ms 未知阶段: {key!r}")
            if not (1000 <= val <= 600000):
                raise ValueError(f"phase_budgets_ms[{key}] 超出 [1000, 600000]")
        if self.stall_ms_override is not None and not (1000 <= self.stall_ms_override <= 600000):
            raise ValueError("stall_ms_override 超出 [1000, 600000]")
        # 兼容路径：直接用 dataclass 构造且显式改了 stall_ms（老测试/调用方），
        # 等价于显式全局覆盖，不能让分阶段表把它悄悄吃掉。
        if self.stall_ms_override is None and self.stall_ms != _DEFAULT_STALL_MS:
            object.__setattr__(self, "stall_ms_override", self.stall_ms)

    def budget_for(self, phase: str) -> int:
        """该阶段的活性预算（毫秒）。优先级：显式全局覆盖 > 逐项覆盖 > 分阶段表 > 兜底。"""
        if self.stall_ms_override is not None:
            return self.stall_ms_override
        for key, val in self.phase_budgets_ms:
            if key == phase:
                return val
        return PHASE_BUDGET_MS.get(phase, self.stall_ms)

    def slow_after_ms(self, phase: str) -> int:
        return int(self.budget_for(phase) * self.slow_ratio)


#: settings.json 的读取上限。TUI 启动时会读它；一个损坏/恶意的大文件不该
#: 被整份 read_text + json.loads 吃进内存。1 MiB 对一份用户配置绰绰有余。
MAX_SETTINGS_BYTES = 1 << 20


def _strict_int(value: object, default: int) -> int:
    """只接受真正的 int；拒绝 bool（``int(True)==1``）与字符串数字。

    旧实现用 ``int(section.get(...))``，``"3000"``、``True``、``3.9``
    都会被悄悄接受或截断。用户写 ``"3000"`` 时以为设了 3000ms，
    实际语义靠隐式转换兜着 —— 配置层不该有这种魔法。
    """
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("expected-int")
    return value


def _strict_ratio(value: object, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected-number")
    ratio = float(value)
    if not math.isfinite(ratio):
        raise ValueError("non-finite")
    return ratio


# ------------------------------------------------------------------ 深度轮 10 辅助
#
# 前九轮把 ``ui/slogans/mapping.py`` 的 public 入参面收得很紧，引擎这边
# 却一行没动。实测发现同一类病在这里更毒：``now=nan`` 会在**抛异常之前**
# 先把 ``_last_event_at`` 写成 nan，之后 ``liveness()`` / ``snapshot()``
# 永久抛 ValueError（UI 直接崩）。D1 的 RLock 只防并发撕裂，防不住
# **异常路径的半更新**。所以校验必须在任何字段写入之前完成。

#: ``now`` 是单调秒；夹到 [0, 1e9]（约 31 年）。理由不是业务上限，
#: 而是 ``_record_locked`` 里的 ``int(at * 1000)``：实测合法但极大的
#: 有限值 ``now=1e308`` 会让 ``at*1000`` 溢出成 inf，``int(inf)`` 抛
#: OverflowError。1e9 秒 → 1e12 毫秒，``int()`` 安全且数值仍可读。
_MAX_NOW_SECONDS = 1e9


def _coerce_now_value(value: object) -> Optional[float]:
    """把 public ``now`` / 注入 ``clock`` 的返回值收敛成有限实数秒。

    深度轮 10 (P1) 实测: 旧实现 ``at = clock() if now is None else now``
    让 ``now='1000'`` 抛底层 TypeError、``nan`` 抛 ValueError、
    ``inf`` 抛 OverflowError、``True`` 被悄悄当成 1 秒、``1e308``
    在 ``int()`` 处溢出。**脏值一律返回 None**，调用方回落真实时钟，
    绝不把可疑值写进状态（这是异常路径撕裂的根因）。
    ``0`` 是合法零值，必须显式判 ``is None`` —— 深度轮 7 踩过
    ``_coerce_ms(...) or fallback()`` 把 0 当 falsy 吞掉的坑。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    if not math.isfinite(v) or v < 0.0 or v > _MAX_NOW_SECONDS:
        return None
    return v


def _safe_source(raw: object) -> str:
    """诊断 ``source`` 的统一出口：净化 + 限长，绝不把配置原文带进日志。

    深度轮 10 (P3) 实测: ``mode = str(raw_mode)`` 后
    ``source=f"invalid:mode={mode}"`` 会把 settings.json 里 5000 码点
    含 OSC 8 / U+202E RLO 的串**原样**带进 ``Liveness.source`` /
    ``snapshot()["source"]`` / ``render``。与 D4/d9 的日志字段净化
    共用同一个 ``_clean`` 真值，不新造第二套。
    """
    text = raw if isinstance(raw, str) else str(raw)
    return sanitize_log_field(text, 120) or "invalid:unknown"


def _settings_path(explicit: Optional[Path] = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    env_home = os.environ.get("TUAN_HOME")
    base = Path(env_home) if env_home else (Path.home() / ".tuan")
    return base / "settings.json"


def load_config(path: Optional[Path] = None) -> SpinnerVerbsConfig:
    """读取 ``~/.tuan/settings.json`` 的 ``spinnerVerbs``（键名与上游同款）。

    任何异常都回落到出厂配置，**绝不因为配置写错就让 TUI 崩**；但非法值
    会被拒绝而不是静默生效（``source`` 会标注 ``invalid:*`` 便于排查）。
    注意「未知阶段键」也必须整段拒绝：静默忽略会让用户以为自己收紧了
    ``stremaing``（拼错）的预算，实际仍在用默认值 —— 那是危险的假安全感。

    深度轮 10: ``path`` 的构造挪进 try（脏类型不再掀掉调用方）、
    ``mode`` / 阶段键 / 路径 / 异常消息一律经 ``_safe_source()``
    或 ``sanitize_log_field()`` 净化限长，诊断 source 不再携带配置
    原文里的控制字符或超长串。
    """
    # 深度轮 10 (P8): 旧实现把 ``p = _settings_path(path)`` 放在 try
    # **之外**。实测 ``load_config(123)`` / ``(['a'])`` 直接抛底层
    # TypeError 掀掉调用方 —— 与 docstring「绝不因为配置写错就让 TUI
    # 崩」的契约矛盾（except 里明明有 TypeError，只是位置不对）。
    try:
        p = _settings_path(path)
        if p.stat().st_size > MAX_SETTINGS_BYTES:
            return SpinnerVerbsConfig(source=_safe_source("invalid:too-large"))
        raw = json.loads(p.read_text(encoding="utf-8"))
        section = raw.get("spinnerVerbs") if isinstance(raw, dict) else None
    except (OSError, ValueError, TypeError):
        return SpinnerVerbsConfig(source=_safe_source("builtin"))
    if section is None:
        return SpinnerVerbsConfig(source=_safe_source("builtin"))
    if not isinstance(section, dict):
        return SpinnerVerbsConfig(source=_safe_source("invalid:not-a-dict"))

    raw_verbs = section.get("verbs", [])
    # 真实缺陷修复：旧实现把「没写 mode」一律当成 append，而 append 又强制
    # 要求 verbs 非空 —— 于是用户只想收紧 `stall_ms`、或只写
    # `phase_budgets_ms`，整段配置就被判成 invalid:empty-verbs 静默回落出厂值。
    # 正确语义：给了 verbs 但没写 mode 才按 append（兼容上游习惯）；
    # 两者都没给就是 default（用内置词库）。
    raw_mode = section.get("mode")
    if raw_mode is None:
        inferred = "append" if raw_verbs else "default"
        mode = inferred
    else:
        # 深度轮 10 (P3): 旧实现 ``str(raw_mode)`` 对任意对象取字符串，
        # 再原样拼进 ``source`` —— 实测 5000 码点含 OSC 8 / RLO 的串
        # 全量进入 ``Liveness.source`` / ``snapshot()`` / 诊断日志。
        # 非字符串直接拒绝；字符串过同一个 ``_clean`` 真值并限长 40。
        if not isinstance(raw_mode, str):
            return SpinnerVerbsConfig(source=_safe_source("invalid:mode-type"))
        mode = sanitize_log_field(raw_mode, 40).strip().lower()
        if not mode:
            mode = "<empty>"
    if mode not in _VALID_MODES:
        return SpinnerVerbsConfig(source=_safe_source(f"invalid:mode={mode}"))

    if not isinstance(raw_verbs, (list, tuple)):
        return SpinnerVerbsConfig(source=_safe_source("invalid:verbs-not-a-list"))
    # 深度轮 11 (B): 旧实现 ``raw_verbs[:200]`` **静默截断**。实测写入
    # 205 条 verbs 只生效 200 条, 第 205 条凭空消失, 而 ``source`` 是
    # 正常路径、没有任何提示 —— 与深度轮 10 P8「静默忽略是危险的假
    # 安全感」同类。200 是防 DoS 的上限, 但不该悄悄生效: 超限**整段
    # 拒绝**, 让用户明确知道要减到 200 以内。
    #: ``spinnerVerbs.verbs`` 的硬上限（防超大配置吃内存）。
    MAX_CUSTOM_VERBS = 200
    if len(raw_verbs) > MAX_CUSTOM_VERBS:
        return SpinnerVerbsConfig(source=_safe_source("invalid:too-many-verbs"))
    verbs = tuple(v for v in (sanitize_verb(x) for x in raw_verbs) if v)
    # 深度轮 11 (C): 旧实现只在 append/replace 下检查空词池。实测
    # ``mode=default`` + ``verbs=[123, None, ['a'], {}, True]`` 时净化
    # 后一条不剩, 但 ``source`` 仍是**正常路径** —— 用户以为自定义了
    # 标语, 实际全用内置词库且毫不知情。现在「写了自定义词却一条都
    # 不可渲染」对**所有** mode 一律用既有的 ``invalid:empty-verbs``
    # 拒绝 (复用既有 source, 不改任何既有断言的口径)。
    if not verbs and (raw_verbs or mode in ("append", "replace")):
        return SpinnerVerbsConfig(source=_safe_source("invalid:empty-verbs"))

    try:
        interval = _strict_int(section.get("interval_ms"), _DEFAULT_INTERVAL_MS)
        stall = _strict_int(section.get("stall_ms"), _DEFAULT_STALL_MS)
    except ValueError:
        return SpinnerVerbsConfig(source=_safe_source("invalid:numbers"))

    # 只有显式出现 stall_ms 才算全局覆盖；缺省时走分阶段预算表。
    override: Optional[int] = stall if "stall_ms" in section else None

    budgets: Tuple[Tuple[str, int], ...] = ()
    raw_budgets = section.get("phase_budgets_ms")
    if raw_budgets is not None:
        if not isinstance(raw_budgets, dict):
            return SpinnerVerbsConfig(source=_safe_source("invalid:budgets-not-a-dict"))
        try:
            pairs = []
            for k, v in list(raw_budgets.items())[:10]:
                if isinstance(v, bool) or not isinstance(v, int):
                    raise ValueError("expected-int")
                key = k if isinstance(k, str) else str(k)
                # 深度轮 10 (P3): 未知阶段键会进 ``__post_init__`` 的
                # ValueError 消息，再经 ``invalid:{exc}`` 进 source。
                # 与 mode 同一净化真值、限长 40；合法短阶段名零变化。
                pairs.append((sanitize_log_field(key, 40), v))
            items = tuple(pairs)
        except (TypeError, ValueError):
            return SpinnerVerbsConfig(source=_safe_source("invalid:budget-values"))
        if any(k not in PHASES for k, _ in items):
            return SpinnerVerbsConfig(source=_safe_source("invalid:budget-phase"))
        budgets = items

    try:
        ratio = _strict_ratio(section.get("slow_ratio"), _DEFAULT_SLOW_RATIO)
    except ValueError:
        return SpinnerVerbsConfig(source=_safe_source("invalid:slow_ratio"))

    try:
        return SpinnerVerbsConfig(mode=mode, verbs=verbs, interval_ms=interval,
                                  stall_ms=stall, phase_budgets_ms=budgets,
                                  slow_ratio=ratio,
                                  stall_ms_override=override,
                                  source=_safe_source(str(p)))
    except ValueError as exc:
        return SpinnerVerbsConfig(source=_safe_source(f"invalid:{exc}"))


# ------------------------------------------------------------------ 视图

@dataclass(frozen=True)
class SloganView:
    """一次渲染的结果。

    兼容旧调用：前 6 个字段位置与语义不变，新增字段全部带默认值。
    ``state`` / ``budget_ms`` / ``advice`` / ``diagnostic`` 让 UI 能区分
    「健康」「比预期慢」「真的没进展」，而不只是拿到一个字符串。
    """
    text: str                 # 可直接进终端的文案（off/空闲时为空串）
    phase: str                # 真实阶段
    stalled: bool             # 是否触发诊断（stalled / unknown）
    idle_ms: int              # 距最后一次真实事件的毫秒数，-1 表示从未收到事件
    seq: int                  # 换词序号，供测试/审计核对「没有空转」
    mode: str                 # 生效的配置模式
    state: str = LivenessState.HEALTHY
    budget_ms: int = 0
    remaining_ms: int = 0
    advice: str = ""
    diagnostic: str = ""      # 完整诊断行（给日志/调试，不进 header）
    evidence_seq: int = 0     # 快照时的证据条数
    slow_after_ms: int = 0    # 「比预期慢」的触发点
    headline: str = ""        # header 专用短版；空串表示用 text


@dataclass(frozen=True)
class Liveness:
    """结构化活性快照 —— 判定本身，文案只是它的渲染。

    不依赖 ``busy``：即使当前不在渲染，也能查询「上一回合卡在哪」。
    """
    state: str
    phase: str
    idle_ms: int
    budget_ms: int
    slow_after_ms: int
    remaining_ms: int
    seq: int
    last_event: Optional[EventRecord]
    advice: str
    diagnostic: str
    evidence: Tuple[EventRecord, ...]
    source: str

    @property
    def is_degraded(self) -> bool:
        return self.state in (LivenessState.SLOW, LivenessState.STALLED,
                              LivenessState.UNKNOWN)

    @property
    def needs_diagnostic(self) -> bool:
        return self.state in (LivenessState.STALLED, LivenessState.UNKNOWN)


# ------------------------------------------------------------------ 引擎

class RuntimeSloganEngine:
    """事件驱动的运行时标语引擎 + 活性判定器。

    D1 并发：所有公开方法在 ``RLock`` 内线性化。``note_activity`` 由 UI /
    模型 / 工具三类线程并发进入，``render`` / ``liveness`` 由动画重绘线程进入；
    五个可变字段必须作为**一个状态**被读写，否则会出现「新 seq + 旧文案」
    或间隔判断读到半更新时间戳的撕裂。

    D4 事件：``note_activity`` 是完整阶段事件（可能换词），
    ``note_progress`` 只刷新活性时间戳（不改阶段、不换词）。
    **绝不从动画循环调用这两者** —— 那是把诚实诊断退回定时空转。
    """

    def __init__(
        self,
        config: Optional[SpinnerVerbsConfig] = None,
        lang: Optional[str] = None,
        *,
        rng: Optional[random.Random] = None,
        clock=time.monotonic,
    ) -> None:
        self._lock = threading.RLock()
        # 深度轮 11 (A): 旧实现 ``config or load_config()`` /
        # ``rng or random.Random()`` 会把 **falsy 但完全合法** 的注入对象
        # 静默换掉。实测注入一个 ``__len__=0`` 的 FalsyConfig /
        # FalsyRng 后: ``config.source`` 从 ``INJECTED`` 变成 ``builtin``、
        # 注入 rng 的 ``choice`` 调用 0 次 —— 深度轮 4 刚建好的「确定性
        # 回放」契约被一个 ``or`` 吃掉。这是深度轮 7 A′
        # (``_coerce_ms(...) or fallback()`` 吞掉合法 0) 的**第三次同源**。
        # 现在显式判 ``is None``，None 仍是「用出厂值」。
        self.config = config if config is not None else load_config()
        # ``lang`` 刻意**保持** ``lang or _current_language()``: 实测
        # ``slogan_bank("")`` 会回落到英文词库，改成 ``is None`` 反而让
        # ``lang=""`` 从「本机 zh-CN」变成英文 —— 空串表示「未指定」
        # 是既有兼容契约，本轮判定「不该修」，见 SLOGAN_MAPPING.md §20。
        self.lang = lang or _current_language()
        self._rng = rng if rng is not None else random.Random()
        self._clock = clock
        self._apply_language_locked()
        self._phase = "waiting_model"
        self._current = ""
        self._last_event_at: Optional[float] = None
        self._last_change_at: float = 0.0
        self._seq = 0
        self._pools: Dict[str, Tuple[str, ...]] = {}
        self._evidence: Deque[EventRecord] = deque(maxlen=_EVIDENCE_CAPACITY)

    # ------------------------------------------------------------ 统一时钟
    def _now(self, value: object) -> float:
        """所有 public 时钟的**唯一**入口，且在写任何状态之前完成校验。

        优先级：显式 ``now``（合法）> 注入 ``clock``（合法）>
        ``time.monotonic()``。注入 clock 本身抛异常也接住 —— 实测
        ``clock=lambda: 'x'`` 会让 ``note_activity()`` 抛 TypeError。
        深度轮 10 (P1): 校验前置是修复「异常路径半更新」的关键。
        """
        if value is not None:
            v = _coerce_now_value(value)
            if v is not None:
                return v
        try:
            v = _coerce_now_value(self._clock())
        except Exception:  # noqa: BLE001 - 注入 clock 故障绝不能掀掉 TUI
            v = None
        return time.monotonic() if v is None else v

    # ------------------------------------------------------------ 语言 / 配置
    def _apply_language_locked(self) -> None:
        self._bank = slogan_bank(self.lang)
        self._stall_fmt = _STALL_TEXT.get(self.lang, _STALL_TEXT["en"])
        self._stall_short_fmt = _STALL_SHORT.get(self.lang, _STALL_SHORT["en"])
        self._slow_word = _SLOW_TEXT.get(self.lang, _SLOW_TEXT["en"])
        self._advice = _ADVICE_TEXT.get(self.lang, _ADVICE_TEXT["en"])

    def _advice_for(self, phase: str) -> str:
        kind = _PHASE_KIND.get(phase, "model")
        return self._advice.get(kind, self._advice["model"])

    def reload(self, path: Optional[Path] = None) -> Tuple[bool, str]:
        """显式热重载：原子切换，失败保留旧配置。

        返回 ``(changed, reason)``。刻意**不做文件监听/轮询**：长驻 TUI 里
        后台轮询会引入 I/O 线程与竞态，收益却只是省一次显式调用。
        需要生效时由调用方（命令/信号/测试）显式触发。

        深度轮 11 (D): 旧实现 ``self._current = ""`` 后**不推进 seq、不记
        证据**。实测：事件后 ``seq=1 / current='正在刷屏' /
        evidence.verb='正在刷屏'``，reload 之后 ``seq`` 仍是 1、
        ``current=''``，而 ``render`` 走 ``not self._current`` 分支显示
        新词池首条 ``'重装后的词'`` —— **同一个 seq 对应两个文案**，
        D1 用来检测并发撕裂的 ``(seq, verb)`` 锚点被配置切换直接打断。
        更隐蔽的是：第二次 reload 返回 ``unchanged``，却照样清空
        ``_current`` 造成静默换词（实测 ``unchanged`` 时屏幕文案与
        evidence.verb 也不同）。

        现在：
        * ``unchanged`` 是**真正的 no-op**（不清 current、不动 seq、
          不记证据、不碰缓存）；
        * ``changed`` 时把配置切换视作一次**可审计的状态转移**：
          新文案取新词池首条（确定性、不用 rng，避免把配置重载伪装
          成随机 spinner 事件）、推进 ``seq``、记一条
          ``kind="reload"`` 证据，其 ``verb`` 与屏幕显示**严格相等**；
        * 证据时间戳沿用 ``_last_event_at``（与深度轮 10 P4 的
          ``reset()`` 同源），不把真实时钟与注入时钟混进同一条链。

        这不是「从动画循环记活性」—— reload 是显式配置事件，D4 禁止
        的是定时空转，两者不矛盾。
        """
        try:
            cfg = load_config(path)
            lang = _current_language()
        except Exception as exc:  # noqa: BLE001 - 重载失败绝不能掀掉 TUI
            return False, f"reload-failed:{type(exc).__name__}"
        if cfg.source.startswith("invalid:"):
            return False, cfg.source          # 保留旧配置，不静默吞掉错误配置
        with self._lock:
            old = (self.config, self.lang)
            changed = old != (cfg, lang)
            if not changed:
                return False, "unchanged"    # 真 no-op，不再静默换词
            self.config = cfg
            self.lang = lang
            self._apply_language_locked()
            self._pools.clear()
            self._last_change_at = 0.0
            # D1 锚点：配置切换也是一次状态转移，必须与证据对齐。
            pool = self._pool(self._phase)
            self._current = pool[0] if pool else ""
            self._seq += 1
            last = self._last_event_at
            at = (last if last is not None and math.isfinite(last)
                  else self._now(None))
            self._record_locked("reload", self._phase, at, "")
        return True, "ok"

    # ------------------------------------------------------------ 词池
    def _pool(self, phase: str) -> Tuple[str, ...]:
        with self._lock:
            cached = self._pools.get(phase)
            if cached is not None:
                return cached
            base = tuple(self._bank.get(phase) or self._bank["waiting_model"])
            cfg = self.config
            if cfg.mode == "replace":
                pool = cfg.verbs
            elif cfg.mode == "append":
                pool = base + cfg.verbs
            else:
                pool = base
            seen = set()
            uniq = tuple(v for v in pool if v and not (v in seen or seen.add(v)))
            self._pools[phase] = uniq
            return uniq

    def _pick(self, phase: str) -> str:
        """调用方必须持锁。"""
        pool = self._pool(phase)
        if not pool:
            return ""
        if len(pool) == 1:
            return pool[0]
        choices = [v for v in pool if v != self._current] or list(pool)
        return self._rng.choice(choices)

    # ------------------------------------------------------------ 事件
    def _record_locked(self, kind: str, phase: str, at: float,
                       detail: str) -> None:
        self._evidence.append(EventRecord(
            phase=phase, kind=kind, at_ms=int(at * 1000), seq=self._seq,
            verb=self._current, detail_len=len(detail),
            detail_class=_detail_class(detail),
        ))

    def note_activity(self, phase: str, detail: str = "",
                      *, now: Optional[float] = None) -> None:
        """记录一次**真实**运行时事件（阶段可能变化，可能换词）。"""
        if phase not in PHASES:
            phase = "waiting_model"
        # 深度轮 10 (P7): ``detail`` 是 public 入参，``_record_locked``
        # 直接 ``len(detail)``。实测 ``detail=None`` / ``123`` 抛
        # TypeError（掀掉 UI），``detail=['a']`` 则被 ``_detail_class``
        # 当字符串遍历、得出误导性的 ``class='ascii'``。非 str 一律
        # 收敛成空串 —— 与 D3「绝不记 detail 原文」的脱敏契约一致。
        if not isinstance(detail, str):
            detail = ""
        with self._lock:
            at = self._now(now)
            # 单调化：乱序事件 / 时钟回拨会让 idle_ms 变负、预算错乱。
            if self._last_event_at is not None and at < self._last_event_at:
                at = self._last_event_at
            interval = self.config.interval_ms / 1000.0
            phase_changed = phase != self._phase
            due = (at - self._last_change_at) >= interval
            self._last_event_at = at
            self._phase = phase
            if self._current == "" or phase_changed or due:
                # 先把 seq 与文案一起写好，再统一提交：证据里的
                # (seq, verb) 就是撕裂检测的锚点。
                self._current = self._pick(phase)
                self._last_change_at = at
                self._seq += 1
            self._record_locked("activity", phase, at, detail)

    def note_progress(self, kind: str = "progress", *,
                      now: Optional[float] = None) -> None:
        """D4：只刷新活性时间戳，**不改阶段、不换词、不推进 seq**。

        给 ``end_tool`` / ``end_stream`` / 中断等生命周期点用，避免
        「工具结束 → 下一事件」的间隙被误判为没进展。
        这不是心跳：必须由真实事件调用，不能放进动画循环。
        """
        # 深度轮 10 (P2): ``kind`` 是 public 入参，旧实现**原样**存进
        # EventRecord.kind，而它会经 ``Liveness.evidence`` 进诊断输出。
        # 实测注入 530 码点含 OSC 8 + RLO 的串后全部原样保留。
        # mapping.record_error 早已净化 kind，引擎这边漏了；用同一个
        # ``_clean`` 真值补齐，不新造第二套净化。
        safe_kind = sanitize_log_field(kind, 40) or "progress"
        with self._lock:
            at = self._now(now)
            if self._last_event_at is not None and at < self._last_event_at:
                at = self._last_event_at
            self._last_event_at = at
            self._record_locked(safe_kind, self._phase, at, "")

    def reset(self) -> None:
        """回合结束：清空当前词，**保留证据链**供跨回合回放。

        上一版把 evidence 一起清了，导致「上一回合为什么卡住」不可查。
        深度轮 10 (P4): 旧实现用 ``self._clock()`` 记 reset 时间戳，
        而 ``note_activity(now=...)`` 走注入时钟 —— 实测
        ``[1000000, 1001000, 1000000]``（证据链**时间倒退**），真实
        monotonic 下更是「1000 秒」与「1945 秒」两套时间源混用。
        这是深度轮 6 在 mapping 层修过的「淘汰痕与 decision 时钟
        不同源」的引擎版。现在优先沿用最后事件的时钟：证据链完全
        同源、单调，且 ``kind="reset"`` 本身已足够标记回合边界。
        全新引擎（无事件）才回落到 ``_now(None)``。
        """
        with self._lock:
            last = self._last_event_at
            if last is not None and not math.isfinite(last):
                last = None            # 防御：旧状态里万一残留 nan/inf
            at = last if last is not None else self._now(None)
            self._current = ""
            self._last_event_at = None
            self._phase = "waiting_model"
            self._pools.clear()
            # 记一条分隔证据，回放时能区分回合边界
            self._evidence.append(EventRecord(
                phase="waiting_model", kind="reset", at_ms=int(at * 1000),
                seq=self._seq, verb="", detail_len=0, detail_class="empty"))

    # ------------------------------------------------------------ 活性判定
    def liveness(self, *, now: Optional[float] = None) -> Liveness:
        """结构化活性快照（与 ``busy`` 无关，可在任意时刻查询）。"""
        with self._lock:
            return self._liveness_locked(self._now(now))

    def _liveness_locked(self, at: float) -> Liveness:
        cfg = self.config
        phase = self._phase
        budget = cfg.budget_for(phase)
        slow_after = cfg.slow_after_ms(phase)
        advice = self._advice_for(phase)
        evidence = tuple(self._evidence)
        last = evidence[-1] if evidence else None

        if self._last_event_at is None:
            state = LivenessState.UNKNOWN
            idle_ms = -1
            remaining = budget
        else:
            idle_ms = max(0, int((at - self._last_event_at) * 1000))
            remaining = max(0, budget - idle_ms)
            if idle_ms >= budget:
                state = LivenessState.STALLED
            elif idle_ms >= slow_after:
                state = LivenessState.SLOW
            else:
                state = LivenessState.HEALTHY

        diagnostic = self._format_diagnostic(state, phase, idle_ms,
                                             budget, advice)
        return Liveness(
            state=state, phase=phase, idle_ms=idle_ms, budget_ms=budget,
            slow_after_ms=slow_after, remaining_ms=remaining, seq=self._seq,
            last_event=last, advice=advice, diagnostic=diagnostic,
            evidence=evidence, source=cfg.source,
        )

    def _format_diagnostic(self, state: str, phase: str, idle_ms: int,
                           budget: int, advice: str) -> str:
        """完整诊断行（给日志/调试）。header 只显示短文案，不塞这一整行。"""
        if state == LivenessState.UNKNOWN:
            return self._stall_fmt.format(sec=-1) + f" · {phase} · {advice}"
        if state == LivenessState.STALLED:
            return (self._stall_fmt.format(sec=idle_ms // 1000)
                    + f" · {phase} · 预算 {budget // 1000}s · {advice}")
        if state == LivenessState.SLOW:
            return (f"{self._slow_word} · {phase} · 已 {idle_ms // 1000}s / "
                    f"预算 {budget // 1000}s · {advice}")
        return ""

    # ------------------------------------------------------------ 渲染
    def render(self, busy: bool, *, now: Optional[float] = None) -> SloganView:
        """纯读渲染：不换词、不推进 seq、不写证据，可安全地被每帧调用。

        变更点：现在基于 ``liveness()`` 的分阶段预算判定，不再用单一 15s。
        """
        with self._lock:
            at = self._now(now)
            cfg = self.config
            lv = self._liveness_locked(at)
            if cfg.mode == "off" or not busy:
                return SloganView("", lv.phase, False, 0, self._seq, cfg.mode,
                                  state=lv.state, budget_ms=lv.budget_ms,
                                  remaining_ms=lv.remaining_ms,
                                  advice=lv.advice, diagnostic=lv.diagnostic,
                                  evidence_seq=len(lv.evidence),
                                  slow_after_ms=lv.slow_after_ms)
            if lv.needs_diagnostic:
                sec = -1 if lv.idle_ms < 0 else lv.idle_ms // 1000
                # text 保持**完整**诊断（向后兼容；给日志/多行区域用）。
                # headline 是单行 header 专用短版，走统一净化/列宽出口 ——
                # 上一轮的缺陷正是「把完整诊断直接塞进 header」。
                text = self._stall_fmt.format(sec=sec)
                headline = _fit_headline(self._stall_short_fmt.format(sec=sec))
                return SloganView(text, lv.phase, True, lv.idle_ms, self._seq,
                                  cfg.mode, state=lv.state,
                                  budget_ms=lv.budget_ms,
                                  remaining_ms=lv.remaining_ms,
                                  advice=lv.advice, diagnostic=lv.diagnostic,
                                  evidence_seq=len(lv.evidence),
                                  slow_after_ms=lv.slow_after_ms,
                                  headline=headline)
            if not self._current:
                pool = self._pool(lv.phase)
                text = pool[0] if pool else ""
            else:
                text = self._current
            text = _fit_headline(text)
            return SloganView(text, lv.phase, False, lv.idle_ms, self._seq,
                              cfg.mode, state=lv.state,
                              budget_ms=lv.budget_ms,
                              remaining_ms=lv.remaining_ms,
                              advice=lv.advice, diagnostic=lv.diagnostic,
                              evidence_seq=len(lv.evidence),
                              slow_after_ms=lv.slow_after_ms)

    # ------------------------------------------------------------ 诊断
    def snapshot(self) -> Dict[str, object]:
        """向后兼容的诊断字典（旧字段全保留），并暴露新的活性维度。"""
        with self._lock:
            lv = self._liveness_locked(self._now(None))
            return {
                "lang": self.lang, "mode": self.config.mode,
                "source": self.config.source, "phase": self._phase,
                "current": self._current, "seq": self._seq,
                "interval_ms": self.config.interval_ms,
                "stall_ms": self.config.stall_ms,
                "state": lv.state,
                "budget_ms": lv.budget_ms,
                "slow_after_ms": lv.slow_after_ms,
                "idle_ms": lv.idle_ms,
                "remaining_ms": lv.remaining_ms,
                "evidence_count": len(lv.evidence),
                "pool_sizes": {p: len(self._pool(p)) for p in PHASES},
                "phase_budgets_ms": {p: self.config.budget_for(p) for p in PHASES},
            }


def _current_language() -> str:
    """从 i18n 取当前语言；i18n 不可用时回退默认 zh-CN。"""
    try:
        from ..i18n import get_language
        return get_language()
    except Exception:  # noqa: BLE001 - i18n 不可用时不能让 TUI 崩
        return "zh-CN"
