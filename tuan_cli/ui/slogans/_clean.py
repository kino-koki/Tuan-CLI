"""标语文案的**唯一净化出口** — 纯 stdlib, 两边共用同一份实现。

为什么单独成模块 (本轮「每个标语都要对应的」的前置条件):

- ``tuan_cli/tui/runtime_slogans.py`` 前两轮把净化层做成了
  bidi/零宽/ESC/变体选择符/grapheme/幂等 的完整边界, 并与
  ``tui._display_width`` 做了 500 串交叉一致回归。
- 新标语库 ``tuan_cli/ui/slogans/`` 有 1105 条词条, 也要进终端。
  若再写一套净化, 就是第三套真值来源 —— 前两轮刚刚消灭的东西。
- 因此抽到这里, 由 ``runtime_slogans`` **re-export** 同一批函数对象。
  ``mapping.audit()`` 断言 ``runtime_slogans.sanitize_verb is _clean.sanitize_verb``,
  把「统一出口」变成可验证的不变量, 而不是文档承诺。

本模块不依赖 prompt_toolkit / rich / wcwidth / i18n, 可被纯 stdlib
验证脚本直接 import。
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import List

# ------------------------------------------------------------------ 净化

# 标语会直接进终端，绝不能回显控制序列，也不能带不可见/双向字符。
#
# 深度轮 2 实测复现的洞（见 RUNTIME_SLOGANS.md §11.1）：旧版只剥了
# OSC(BEL/ST) 与 CSI，其余 ESC 序列只删掉了 ESC 本身，把参数字符留在文案里；
# 更严重的是 **bidi 覆写 (U+202E RLO / U+202D LRO)、isolate、零宽字符
# 全部原样输出** —— 终端会按它们重排显示方向，用户看到的和字符串内容
# 不一致（Trojan Source 的 UI 版）。旧 docstring 还声称「去掉组合标记开头
# 的异常串」，实测根本没做。
_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?")   # BEL 或 ST 终止
_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
# 其余 ESC 序列：ESC c (RIS)、ESC 7/8 (save/restore)、ESC ( B (charset) …
# ``[ -/]*`` 吃中间字节，``[0-~]`` 吃终止/单字符命令。必须排在 OSC/CSI 之后。
_ESC_SEQ_RE = re.compile(r"\x1b[ -/]*[0-~]")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

_MAX_VERB_CHARS = 48          # 码点上限（第二道保险）
_MAX_VERB_COLS = 40           # 显示列上限（CJK / emoji 算 2）

#: 绝不进终端的 Unicode 通用类别。
#: Cc 控制 / Cf 格式（bidi、ZWSP、ZWJ、BOM、WJ、软连字符全在这里）/
#: Cs 代理项 / Co 私用区 / Cn 未分配。
_DROP_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})


def _is_variation_selector(ch: str) -> bool:
    """VS1–VS16 (U+FE00–FE0F) 与补充变体选择符 (U+E0100–E01EF)。

    它们不可见，却会改变前一个字符的**终端宽度**：实测 wcwidth 把
    ``❤\ufe0f`` 算 2 列、``❤`` 算 1 列，而纯 ``east_asian_width`` 实现
    会算出 1 列 —— 于是「同一套宽度真值」在 emoji 呈现序列上又裂开。
    净化层直接删掉它们：短 UI 文案不需要文本/emoji 呈现切换，
    换来的是宽度可预测、且没有任何不可见字符进终端。
    """
    cp = ord(ch)
    return 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF


def display_cols(s: str) -> int:
    """一串文本的终端显示列数（**纯 stdlib**，无第三方依赖）。

    这是上一轮 B3「统一宽度真值来源」的收口：那时把 ``_disp_width`` 与
    ``_display_width`` 合并了，却漏了 ``sanitize_verb`` 里还藏着第三套
    ``_char_cols`` —— 实测 ``👩‍💻`` 它算 5 列、wcwidth 算 2 列，
    ``a\\u200db`` 算 3 列、wcwidth 算 1 列。净化后 Cf 已全部删除，
    变体选择符已由净化层删除，这里只需处理组合标记(0 列) 与 W/F(2 列)，
    并与 ``tui._display_width`` 在「已净化串」上逐值一致（有 500 串交叉回归守着）。

    刻意**不 import wcwidth、不引入运行时注入**：引擎必须能被
    ``verify_deep.py`` 这类纯 stdlib 脚本独立验证，也不该为了对齐宽度
    再引入一处全局可变状态（那会破坏 D1 的并发不变量）。
    """
    total = 0
    for ch in s:
        cat = unicodedata.category(ch)
        if cat[0] == "M" or cat in _DROP_CATEGORIES:
            continue                       # 组合标记 / 变体选择符 / 不可见
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def _clusters(s: str) -> List[str]:
    """按 grapheme 近似分簇：基字符 + 其后连续的组合标记/变体选择符。

    不做完整 UAX #29（零依赖约束），但足够保证**截断不落在组合序列中间** ——
    旧实现 ``s[:48]`` 会把 ``e\u0301`` 切成孤立的 ``\u0301`` 挂到前一个字上。
    净化后 ZWJ 已删除，emoji 序列天然拆成独立簇，无需处理 ZWJ 连接。
    """
    out: List[str] = []
    cur = ""
    for ch in s:
        if cur and unicodedata.category(ch)[0] != "M":
            out.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def _clean_once(raw: str) -> str:
    """**纯清理核心**：去 ANSI/OSC/CSI/ESC 序列、控制字符、bidi 覆写、
    isolate、零宽/格式字符、私用区与未分配码点、组合标记开头。

    刻意**不做任何截断** —— UI 标语与日志字段共用这一份清理真值,
    但两者的长度约束不同 (前者按显示列宽 40, 后者按码点 120)。
    """
    s = _OSC_RE.sub("", raw)
    s = _CSI_RE.sub("", s)
    s = _ESC_SEQ_RE.sub("", s)             # 吃完整序列，不只是 ESC 字节
    s = _CTRL_RE.sub("", s)
    # 删不可见/双向/私用/未分配；保留中间的组合标记（如 ❤️ 的 VS16）。
    s = "".join(ch for ch in s
                if unicodedata.category(ch) not in _DROP_CATEGORIES
                and not _is_variation_selector(ch))
    # docstring 承诺的「组合标记开头」：旧版声称做了、实测没做。
    i = 0
    while i < len(s) and unicodedata.category(s[i])[0] == "M":
        i += 1
    return s[i:].strip()


def _sanitize_once(raw: str) -> str:
    s = _clean_once(raw)
    if not s:
        return ""
    # 按 grapheme 簇累加，双上限都在**簇边界**上截断。
    cols = 0
    chars = 0
    kept: List[str] = []
    for cl in _clusters(s):
        cw = display_cols(cl)
        if cols + cw > _MAX_VERB_COLS or chars + len(cl) > _MAX_VERB_CHARS:
            break
        kept.append(cl)
        cols += cw
        chars += len(cl)
    return "".join(kept).strip()


def _fit_headline(s: str) -> str:
    """所有进 header 的文案统一走这里：净化 + 列宽约束，不留侧门。

    ``_STALL_TEXT`` / ``_STALL_SHORT`` 是内置硬编码，本来「看起来可信」，
    但正因可信才最容易漏掉校验。上一轮就是这么把 52 列的完整诊断直接
    塞进单行 header 的。现在自定义 verbs 与内置诊断共用同一个出口，
    且 ``display_cols`` 与 ``tui._display_width`` 有交叉回归保证一致。
    """
    clean = sanitize_verb(s)
    if not clean:
        return ""
    cols = 0
    kept: List[str] = []
    for cl in _clusters(clean):
        cw = display_cols(cl)
        if cols + cw > _MAX_VERB_COLS:
            break
        kept.append(cl)
        cols += cw
    return "".join(kept).strip()


def sanitize_verb(raw: object) -> str:
    """把任意用户输入净化成可安全渲染的标语；非法输入返回空串。

    去掉 ANSI/OSC/CSI/其它 ESC 序列、C0/C1 控制字符、**bidi 覆写与
    isolate、零宽/格式字符、私用区与未分配码点**，拒绝组合标记开头，
    按显示列宽在 grapheme 簇边界截断。

    **幂等是构造出来的，不是碰巧**：``_sanitize_once`` 迭代到不动点，
    最多 3 轮；不收敛就 fail-closed 返回空串，绝不输出可疑文案。
    净化函数若不满足 ``f(f(x)) == f(x)``，调用方（load_config 存词、
    reload 换词池）就会在不同路径上得到不同结果，这类隐性不一致最难查。
    """
    if not isinstance(raw, str):
        return ""
    s = raw
    for _ in range(3):
        nxt = _sanitize_once(s)
        if nxt == s:
            return s
        s = nxt
    return ""   # 不收敛：拒绝，而不是把半成品送进终端


#: 日志字段码点上限。刻意**不是**显示列宽 —— 日志不参与终端渲染,
#: 用码点限长才能保留 ``background.progress`` 这类长事件名的可读性。
LOG_FIELD_LIMIT = 120


def _coerce_log_limit(limit: object) -> int:
    """把 ``limit`` 收敛成合法正整数；脏值一律回落默认，绝不抛异常。

    深度轮 5 实测: ``sanitize_log_field`` 是 public API, 旧实现直接
    ``int(limit)`` —— ``None`` 抛 TypeError、``nan`` 抛 ValueError、
    ``inf`` 抛 OverflowError、``'5'`` 被悄悄接受、``True`` 被当成 1。
    与 ``runtime_slogans.load_config`` 对 ``stall_ms`` 的严格类型口径
    不一致。这里显式拒绝 bool / 非数值 / 非有限 / 非正, 并夹在
    ``[8, 4096]``。
    """
    if isinstance(limit, bool) or not isinstance(limit, (int, float)):
        return LOG_FIELD_LIMIT
    if isinstance(limit, float):
        if not math.isfinite(limit) or limit != int(limit):
            return LOG_FIELD_LIMIT
        limit = int(limit)
    if limit <= 0:
        return LOG_FIELD_LIMIT
    return max(8, min(4096, int(limit)))


def sanitize_log_field(raw: object, limit: int = LOG_FIELD_LIMIT) -> str:
    """把任意（可能外部可控的）字段净化成可安全写入日志的字符串。

    与 ``sanitize_verb`` 共用 ``_clean_once`` 这份**唯一** Unicode 清理
    核心，因此不产生第三套净化真值；差别只在长度约束：

    - ``sanitize_verb``: 按 ``_MAX_VERB_COLS`` 显示列宽、在 grapheme
      簇边界截断（进终端的 UI 文案）。
    - ``sanitize_log_field``: 按码点上限 ``limit`` 截断，不做列宽计算
      （进内存日志 / repr / 导出的字段名）。

    实测复现的必要性：``record_error(event, ...)`` 的 ``event`` 是
    public API 入参，``slogan_for(event)`` 拼错时会把整个字符串写进
    留痕。实测注入 5030 码点含 ``ESC ]8;;`` + ``U+202E`` RLO 的串，
    旧实现原样存下 —— 控制字符可被日志查看器/终端解释。

    同样迭代到不动点；不收敛或非字符串输入返回空串（fail-closed）。
    返回空串时调用方应记为 ``error:invalid-field``，不写原文。

    ``limit`` 走 ``_coerce_log_limit`` 严格校验（深度轮 5）：脏值回落
    默认 120 而不是抛异常，public API 不会因脏配置崩。
    """
    if not isinstance(raw, str):
        return ""
    lim = _coerce_log_limit(limit)
    s = raw[:lim * 4]          # 先粗切，避免超长输入在正则上放大
    for _ in range(3):
        nxt = _clean_once(s)
        if nxt == s:
            s = nxt
            break
        s = nxt
    else:
        return ""              # 不收敛：拒绝，不写半成品
    if not s:
        return ""
    if len(s) > lim:
        s = s[:lim].rstrip() + "…"
    return s
