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
"""
from __future__ import annotations

import json
import os
import random
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence, Tuple

__all__ = [
    "PHASES", "LANGUAGES", "SpinnerVerbsConfig", "SloganView",
    "RuntimeSloganEngine", "load_config", "slogan_bank", "sanitize_verb",
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

#: 忙碌但长时间无任何真实进展时的诊断文案。{sec} 会被静默秒数替换。
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

# ------------------------------------------------------------------ 净化

# ESC / CSI / OSC / C0 / C1 / DEL。标语会直接进终端，绝不能回显控制序列。
_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?")
_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_MAX_VERB_CHARS = 48          # 字符数上限
_MAX_VERB_COLS = 40           # 显示列上限（CJK 算 2）


def _char_cols(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def sanitize_verb(raw: object) -> str:
    """把任意用户输入净化成可安全渲染的标语；非法输入返回空串。

    去掉 ANSI/OSC/CSI 转义序列、C0/C1 控制字符、组合标记开头的异常串，
    按显示宽度截断（不切断代理对，Python str 本身已是码点序列）。
    """
    if not isinstance(raw, str):
        return ""
    s = _OSC_RE.sub("", raw)
    s = _CSI_RE.sub("", s)
    s = _CTRL_RE.sub("", s)
    s = s.strip()
    if not s:
        return ""
    s = s[:_MAX_VERB_CHARS]
    cols = 0
    out = []
    for ch in s:
        c = _char_cols(ch)
        if cols + c > _MAX_VERB_COLS:
            break
        cols += c
        out.append(ch)
    return "".join(out).strip()


def slogan_bank(lang: str) -> Dict[str, Tuple[str, ...]]:
    """返回该语言的完整词库；未知语言回退英文（调用方负责显式选择语言）。"""
    return _BANK.get(lang, _BANK["en"])


# ------------------------------------------------------------------ 配置

_VALID_MODES = ("default", "append", "replace", "off")
_DEFAULT_INTERVAL_MS = 1800
_DEFAULT_STALL_MS = 15000


@dataclass(frozen=True)
class SpinnerVerbsConfig:
    """与上游同款的 ``spinnerVerbs`` 配置，额外带两个本地化开关。"""
    mode: str = "default"                       # default | append | replace | off
    verbs: Tuple[str, ...] = ()                 # 自定义词（已净化）
    interval_ms: int = _DEFAULT_INTERVAL_MS     # 同阶段最短换词间隔
    stall_ms: int = _DEFAULT_STALL_MS           # 无进展判定阈值
    source: str = "builtin"                     # 配置来源，供诊断展示

    def __post_init__(self) -> None:
        if self.mode not in _VALID_MODES:
            raise ValueError(f"spinnerVerbs.mode 非法: {self.mode!r}")
        if not (200 <= self.interval_ms <= 60000):
            raise ValueError("interval_ms 超出 [200, 60000]")
        if not (1000 <= self.stall_ms <= 600000):
            raise ValueError("stall_ms 超出 [1000, 600000]")
        if any(v == "" for v in self.verbs):
            raise ValueError("净化后存在空标语")


def _settings_path(explicit: Optional[Path] = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    env_home = os.environ.get("TUAN_HOME") or os.environ.get("TUAN_HOME")
    base = Path(env_home) if env_home else (Path.home() / ".tuan")
    return base / "settings.json"


def load_config(path: Optional[Path] = None) -> SpinnerVerbsConfig:
    """读取 ``~/.tuan/settings.json`` 的 ``spinnerVerbs``（键名与上游同款）。

    任何异常都回落到出厂配置，**绝不因为配置写错就让 TUI 崩**；但非法值
    会被拒绝而不是静默生效（``source`` 会标注 ``invalid:*`` 便于排查）。
    """
    p = _settings_path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        section = raw.get("spinnerVerbs") if isinstance(raw, dict) else None
    except (OSError, ValueError, TypeError):
        return SpinnerVerbsConfig(source="builtin")
    if section is None:
        return SpinnerVerbsConfig(source="builtin")
    if not isinstance(section, dict):
        return SpinnerVerbsConfig(source="invalid:not-a-dict")

    mode = str(section.get("mode") or "append").strip().lower()
    if mode not in _VALID_MODES:
        return SpinnerVerbsConfig(source=f"invalid:mode={mode}")

    raw_verbs = section.get("verbs", [])
    if not isinstance(raw_verbs, (list, tuple)):
        return SpinnerVerbsConfig(source="invalid:verbs-not-a-list")
    verbs = tuple(v for v in (sanitize_verb(x) for x in raw_verbs[:200]) if v)
    if mode in ("append", "replace") and not verbs:
        return SpinnerVerbsConfig(source="invalid:empty-verbs")

    try:
        interval = int(section.get("interval_ms", _DEFAULT_INTERVAL_MS))
        stall = int(section.get("stall_ms", _DEFAULT_STALL_MS))
    except (TypeError, ValueError):
        return SpinnerVerbsConfig(source="invalid:numbers")

    try:
        return SpinnerVerbsConfig(mode=mode, verbs=verbs, interval_ms=interval,
                                  stall_ms=stall, source=str(p))
    except ValueError as exc:
        return SpinnerVerbsConfig(source=f"invalid:{exc}")


# ------------------------------------------------------------------ 视图

@dataclass(frozen=True)
class SloganView:
    """一次渲染的结果。"""
    text: str                 # 可直接进终端的文案（off/空闲时为空串）
    phase: str                # 真实阶段
    stalled: bool             # 是否触发「疑似摸鱼」诊断
    idle_ms: int              # 距最后一次真实事件的毫秒数
    seq: int                  # 换词序号，供测试/审计核对「没有空转」
    mode: str                 # 生效的配置模式


# ------------------------------------------------------------------ 引擎

class RuntimeSloganEngine:
    """事件驱动的运行时标语引擎。

    与「定时随机换词」的关键区别：只有 ``note_activity()`` 收到真实事件，
    或阶段切换、或超过 ``interval_ms``，才会换词。``render()`` 本身是纯读，
    每帧重绘不会让文案自己动起来 —— 这正是避免「看起来在忙」的设计。
    """

    def __init__(
        self,
        config: Optional[SpinnerVerbsConfig] = None,
        lang: Optional[str] = None,
        *,
        rng: Optional[random.Random] = None,
        clock=time.monotonic,
    ) -> None:
        self.config = config or load_config()
        self.lang = lang or _current_language()
        self._rng = rng or random.Random()
        self._clock = clock
        self._bank = slogan_bank(self.lang)
        self._stall_fmt = _STALL_TEXT.get(self.lang, _STALL_TEXT["en"])
        self._phase = "waiting_model"
        self._current = ""
        self._last_event_at: Optional[float] = None
        self._last_change_at: float = 0.0
        self._seq = 0
        self._pools: Dict[str, Tuple[str, ...]] = {}

    # ------------------------------------------------------------ 词池
    def _pool(self, phase: str) -> Tuple[str, ...]:
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
        # 去重保序（保序让 seed 可复现）
        seen = set()
        uniq = tuple(v for v in pool if v and not (v in seen or seen.add(v)))
        self._pools[phase] = uniq
        return uniq

    def _pick(self, phase: str) -> str:
        pool = self._pool(phase)
        if not pool:
            return ""
        if len(pool) == 1:
            return pool[0]
        choices = [v for v in pool if v != self._current] or list(pool)
        return self._rng.choice(choices)

    # ------------------------------------------------------------ 事件
    def note_activity(self, phase: str, detail: str = "", *, now: Optional[float] = None) -> None:
        """记录一次**真实**运行时事件。``detail`` 只用于审计，不进文案。"""
        if phase not in PHASES:
            phase = "waiting_model"
        at = self._clock() if now is None else now
        interval = self.config.interval_ms / 1000.0
        phase_changed = phase != self._phase
        due = (at - self._last_change_at) >= interval
        self._last_event_at = at
        self._phase = phase
        if self._current == "" or phase_changed or due:
            self._current = self._pick(phase)
            self._last_change_at = at
            self._seq += 1

    def reset(self) -> None:
        """回合结束：清空当前词，但保留配置与词池。"""
        self._current = ""
        self._last_event_at = None
        self._phase = "waiting_model"
        self._pools.clear()

    # ------------------------------------------------------------ 渲染
    def render(self, busy: bool, *, now: Optional[float] = None) -> SloganView:
        """纯读渲染。不会换词、不产生副作用，可安全地被每帧调用。"""
        at = self._clock() if now is None else now
        cfg = self.config
        if cfg.mode == "off" or not busy:
            return SloganView("", self._phase, False, 0, self._seq, cfg.mode)
        if self._last_event_at is None:
            # busy 但从未收到事件：本身就是异常，直接给诊断而不是编一句标语
            return SloganView(self._stall_fmt.format(sec=-1), self._phase,
                              True, -1, self._seq, cfg.mode)
        idle_ms = max(0, int((at - self._last_event_at) * 1000))
        if idle_ms >= cfg.stall_ms:
            return SloganView(self._stall_fmt.format(sec=idle_ms // 1000),
                              self._phase, True, idle_ms, self._seq, cfg.mode)
        if not self._current:
            # 首次 note_activity 尚未发生时的兜底：不换词，只给阶段默认锚点
            pool = self._pool(self._phase)
            text = pool[0] if pool else ""
        else:
            text = self._current
        return SloganView(text, self._phase, False, idle_ms, self._seq, cfg.mode)

    # ------------------------------------------------------------ 诊断
    def snapshot(self) -> Dict[str, object]:
        return {
            "lang": self.lang, "mode": self.config.mode,
            "source": self.config.source, "phase": self._phase,
            "current": self._current, "seq": self._seq,
            "interval_ms": self.config.interval_ms,
            "stall_ms": self.config.stall_ms,
            "pool_sizes": {p: len(self._pool(p)) for p in PHASES},
        }


def _current_language() -> str:
    """从 i18n 取当前语言；i18n 不可用时回退默认 zh-CN。"""
    try:
        from ..i18n import get_language
        return get_language()
    except Exception:  # noqa: BLE001 - i18n 不可用时不能让 TUI 崩
        return "zh-CN"
