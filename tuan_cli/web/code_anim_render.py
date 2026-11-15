# -*- coding: utf-8 -*-
"""Code-animation 渲染后端 —— 纯 Python + Pillow + ffmpeg, 零外部依赖。

设计要点 (fail-closed):
  * 不依赖外部 ``mh`` CLI / Node / 浏览器。帧由 Pillow 逐帧绘制, 经 ffmpeg
    ``rawvideo`` 管道编码为 mp4。
  * 子进程一律 argv 列表 (``shell=False``), 永不 ``shell=True``。
  * ``project_json`` 只做**类型/结构校验**, 未知 node type 一律跳过 (记录日志),
    永不 ``eval`` / ``exec``。
  * ``draw_frame`` 是 ``(project_json, t)`` 的**纯函数** —— 无全局可变状态,
    同一 t 可重复绘制, 保证帧稳定 (frame-stable)。
  * 后台线程渲染 job (与 ``mh_runner`` 同款 job 表), HTTP 请求立即返回 job_id。

环境变量:
  * ``TUAN_FFMPEG``  显式指定 ffmpeg 路径 (优先);
  * 否则遍历 ``%LOCALAPPDATA%/mh/cache-v2/runtime/*/media/ffmpeg.exe``;
  * 否则退化到 ``shutil.which("ffmpeg")``。
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 常量 / 配置
# ---------------------------------------------------------------------------

#: 已知的 node type 白名单 (未知类型跳过, 不执行)。
_KNOWN_NODE_TYPES = frozenset({
    "code", "title", "subtitle", "box", "dataflow", "bg",
})

#: 后台渲染硬超时 (秒)。
_RENDER_TIMEOUT_SEC = 900
#: 每个 job 保留的错误尾部字节数。
_TAIL_BYTES = 2048
#: job 表容量上限。
_JOB_CAP = 50

#: 默认调色板 (深色代码主题)。
_DEFAULT_BG = (18, 20, 26)
_DEFAULT_FG = (226, 232, 240)
_DEFAULT_ACCENT = (79, 195, 247)
_DEFAULT_GUTTER = (100, 116, 139)

# 进程内 job 注册表: {job_id: job_dict}; 多个 HTTP 工作线程会读, 后台线程会写。
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()

#: 字体缓存: {(path, size): ImageFont}。
_FONT_CACHE: Dict[Tuple[str, int], Any] = {}

#: 候选等宽字体 (Windows / 通用)。
_MONO_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\cour.ttf",
    "DejaVuSansMono.ttf",
    r"C:\Windows\Fonts\consolab.ttf",
)
#: 候选无衬线字体 (标题 / 字幕)。
_SANS_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "DejaVuSans.ttf",
)


# ---------------------------------------------------------------------------
# 工具函数: 数值 / 时间 / 颜色
# ---------------------------------------------------------------------------

def _num(v: Any, default: float = 0.0) -> float:
    """安全转 float; 非数字 / bool 返回 default。"""
    if isinstance(v, bool):
        return default
    if isinstance(v, (int, float)):
        return float(v)
    return default


def _int(v: Any, default: int = 0) -> int:
    """安全转 int; 非数字 / bool 返回 default。"""
    if isinstance(v, bool):
        return default
    if isinstance(v, (int, float)):
        return int(v)
    return default


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """夹取到 [lo, hi]。"""
    return max(lo, min(hi, v))


def _ease(t: float) -> float:
    """夹取 0-1 的缓动 (线性; 供淡入淡出)。"""
    return _clamp(t)


def _fade_in(t: float, start: float, dur: float) -> float:
    """节点进入后的透明度 (0-1): start 开始, dur 秒内线性淡入。"""
    if dur <= 0:
        return 1.0 if t >= start else 0.0
    return _clamp((t - start) / dur)


def _fade_out(t: float, end: float, dur: float) -> float:
    """节点退出前的透明度 (0-1): end 前 dur 秒开始淡出。"""
    if dur <= 0:
        return 1.0 if t <= end else 0.0
    return _clamp((end - t) / dur)


def _hex_color(v: Any, default: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """解析 '#rrggbb' / '#rgb' / (r,g,b) 为 0-255 元组; 失败返回 default。"""
    if isinstance(v, str):
        s = v.strip().lstrip("#")
        if len(s) == 6:
            try:
                return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
            except ValueError:
                return default
        if len(s) == 3:
            try:
                return (int(s[0] * 2, 16), int(s[1] * 2, 16), int(s[2] * 2, 16))
            except ValueError:
                return default
        return default
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        try:
            return (int(v[0]) % 256, int(v[1]) % 256, int(v[2]) % 256)
        except (ValueError, TypeError):
            return default
    return default


def _blend(c1: Tuple[int, int, int], c2: Tuple[int, int, int], a: float) -> Tuple[int, int, int]:
    """线性混合 c1→c2 (a=0 → c1, a=1 → c2)。"""
    a = _clamp(a)
    return (int(c1[0] + (c2[0] - c1[0]) * a),
            int(c1[1] + (c2[1] - c1[1]) * a),
            int(c1[2] + (c2[2] - c1[2]) * a))


# ---------------------------------------------------------------------------
# 字体
# ---------------------------------------------------------------------------

def _load_font(size: int, mono: bool = True) -> Any:
    """加载字体 (带缓存); 找不到退化到 ``load_default``。"""
    size = max(8, int(size))
    cands = _MONO_FONT_CANDIDATES if mono else _SANS_FONT_CANDIDATES
    key_candidates = [(c, size) for c in cands]
    # 先查缓存
    for key in key_candidates:
        if key in _FONT_CACHE:
            return _FONT_CACHE[key]
    try:
        from PIL import ImageFont
    except Exception:  # noqa: BLE001 - PIL 必须可用
        return None
    for path in cands:
        if os.path.isfile(path):
            key = (path, size)
            if key not in _FONT_CACHE:
                try:
                    _FONT_CACHE[key] = ImageFont.truetype(path, size)
                except Exception:  # noqa: BLE001 - 单个字体失败继续找
                    continue
            return _FONT_CACHE.get(key) or None
    try:
        return ImageFont.load_default()
    except Exception:  # noqa: BLE001
        return None


def _mono_font(size: int) -> Any:
    """等宽字体。"""
    return _load_font(size, mono=True)


def _sans_font(size: int) -> Any:
    """无衬线字体 (标题)。"""
    return _load_font(size, mono=False)


# ---------------------------------------------------------------------------
# ffmpeg 定位
# ---------------------------------------------------------------------------

def _mh_cache_ffmpeg() -> Optional[str]:
    """在 ``%LOCALAPPDATA%/mh/cache-v2/runtime/*/media/ffmpeg.exe`` 下找 ffmpeg。

    这是 mh 安装时自带的 media 工具 (mh_runner 定位方式之一); 找不到返回 None。
    只遍历一层 runtime 目录, 不深挖, 防止失控。
    """
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    runtime_dir = Path(local) / "mh" / "cache-v2" / "runtime"
    if not runtime_dir.is_dir():
        return None
    try:
        for child in runtime_dir.iterdir():
            if not child.is_dir():
                continue
            cand = child / "media" / "ffmpeg.exe"
            if cand.is_file():
                return str(cand)
    except OSError:
        return None
    return None


def find_ffmpeg() -> Optional[str]:
    """定位 ffmpeg 可执行文件。

    优先级:
      1. ``TUAN_FFMPEG`` 环境变量 (显式覆盖);
      2. mh cache 内的 ``ffmpeg.exe``;
      3. 系统 PATH 上的 ``ffmpeg`` (``shutil.which``)。
    找不到返回 None。
    """
    env = os.environ.get("TUAN_FFMPEG", "").strip()
    if env:
        cand = Path(env)
        if cand.is_file():
            return str(cand)
    cached = _mh_cache_ffmpeg()
    if cached:
        return cached
    which = shutil.which("ffmpeg")
    return which


def ffmpeg_available() -> bool:
    """ffmpeg 是否可用。"""
    return bool(find_ffmpeg())


def _pillow_available() -> bool:
    """Pillow 是否可导入。"""
    try:
        from PIL import Image  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# project_json 校验
# ---------------------------------------------------------------------------

def validate_project(project_json: Any) -> Optional[str]:
    """校验 project_json 基本结构; 返回错误消息 (None = 通过)。

    要求: dict, width/height/fps/duration 均为 > 0 的数字, nodes 是 list。
    未知 node type 不在此处拒绝 (渲染时跳过), 只做类型校验。
    """
    if not isinstance(project_json, dict):
        return "project_json 必须是 JSON 对象"
    for key in ("width", "height", "fps", "duration"):
        val = project_json.get(key)
        if not isinstance(val, (int, float)) or isinstance(val, bool) or val <= 0:
            return f"project_json.{key} 必须是 > 0 的数字"
    nodes = project_json.get("nodes")
    if nodes is not None and not isinstance(nodes, list):
        return "project_json.nodes 必须是数组"
    return None


def _node_active(node: Dict[str, Any], t: float) -> bool:
    """节点是否在时间 t 处于 [start, end] 范围内。"""
    start = _num(node.get("start"), 0.0)
    end = _num(node.get("end"), 0.0)
    if end <= 0:
        end = start  # 未显式给 end 视为瞬时
    return start <= t <= end


# ---------------------------------------------------------------------------
# 语法高亮 (轻量) —— 按语言分类, 简单正则分词
# ---------------------------------------------------------------------------

#: 各语言关键字表 (用于高亮)。
_KEYWORDS: Dict[str, List[str]] = {
    "python": ["def", "class", "return", "import", "from", "if", "elif", "else",
               "for", "while", "try", "except", "finally", "with", "as", "in",
               "not", "and", "or", "lambda", "yield", "pass", "break", "continue",
               "raise", "global", "nonlocal", "assert", "del", "is", "None",
               "True", "False", "async", "await", "match", "case"],
    "javascript": ["const", "let", "var", "function", "return", "if", "else",
                   "for", "while", "do", "switch", "case", "break", "continue",
                   "new", "class", "extends", "super", "this", "typeof", "instanceof",
                   "try", "catch", "finally", "throw", "async", "await", "yield",
                   "import", "export", "from", "default", "delete", "void", "in",
                   "of", "null", "undefined", "true", "false"],
    "json": ["true", "false", "null"],
    "shell": ["echo", "if", "then", "else", "elif", "fi", "for", "in", "do",
              "done", "while", "case", "esac", "function", "return", "exit",
              "export", "local", "readonly", "source", "alias", "cd", "set"],
}


def _tokenize_code(lang: str, line: str) -> List[Tuple[str, str]]:
    """把一行代码切成 [(kind, text)]; kind ∈ {plain, keyword, string, comment, number, fn, punct}。

    仅用于**着色**, 不解析语义; 失败时整行按 plain 返回。
    """
    tokens: List[Tuple[str, str]] = []
    i = 0
    n = len(line)
    lang = (lang or "").lower()
    kw = set(_KEYWORDS.get(lang, []))
    while i < n:
        ch = line[i]
        # 注释: '#' (python/shell) 或 '//'
        if ch == "#" or (ch == "/" and i + 1 < n and line[i + 1] == "/"):
            tokens.append(("comment", line[i:]))
            break
        # 字符串: 单/双引号
        if ch in "\"'":
            quote = ch
            j = i + 1
            while j < n:
                if line[j] == "\\":
                    j += 2
                    continue
                if line[j] == quote:
                    j += 1
                    break
                j += 1
            tokens.append(("string", line[i:j]))
            i = j
            continue
        # 数字
        if ch.isdigit():
            j = i
            while j < n and (line[j].isalnum() or line[j] in "._"):
                j += 1
            tokens.append(("number", line[i:j]))
            i = j
            continue
        # 标识符 / 关键字
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (line[j].isalnum() or line[j] == "_"):
                j += 1
            word = line[i:j]
            if word in kw:
                tokens.append(("keyword", word))
            elif j < n and line[j] == "(":
                tokens.append(("fn", word))
            else:
                tokens.append(("plain", word))
            i = j
            continue
        tokens.append(("punct", ch))
        i += 1
    return tokens


# 高亮配色 (深色主题): kind -> (r,g,b)
_SYNTAX_COLORS: Dict[str, Tuple[int, int, int]] = {
    "keyword": (197, 134, 192),   # 紫
    "string": (152, 195, 121),    # 绿
    "comment": (92, 99, 112),     # 灰
    "number": (209, 154, 102),    # 橙
    "fn": (97, 175, 239),         # 蓝
    "plain": (206, 212, 220),     # 近白
    "punct": (171, 178, 191),     # 浅灰
}


def _render_code_node(draw: Any, node: Dict[str, Any], t: float,
                      canvas_w: int, canvas_h: int) -> None:
    """渲染 ``code`` 节点: 带行号的动画代码块。"""
    props = node.get("props") or {}
    if not isinstance(props, dict):
        props = {}
    code = str(props.get("code") or "")
    lines = code.split("\n")
    title = props.get("title")
    lang = str(props.get("language") or "")
    bg = _hex_color(props.get("bg"), (30, 34, 42))
    fg = _hex_color(props.get("fg"), _DEFAULT_FG)
    accent = _hex_color(props.get("accent"), _DEFAULT_ACCENT)
    line_h = max(12, _int(props.get("line_height"), 22))
    font_size = max(8, _int(props.get("font_size"), 16))
    x = _int(props.get("x"), 60)
    y = _int(props.get("y"), 60)
    w = _int(props.get("w"), min(canvas_w - x - 60, 720))
    h = _int(props.get("h"), min(canvas_h - y - 60, 60 + len(lines) * line_h))
    font = _mono_font(font_size)

    # 行高亮: highlight 可为 [[startLine,endLine],...] 或 {line:[start,end]}
    highlights = props.get("highlight")
    highlight_ranges: List[Tuple[int, int, float, float]] = []  # (start_line, end_line, t0, t1)
    if isinstance(highlights, list):
        for item in highlights:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                sl = _int(item[0], 0)
                el = _int(item[1], sl)
                highlight_ranges.append((sl, el, node.get("start", 0.0), node.get("end", 1e9)))
    elif isinstance(highlights, dict):
        for key, val in highlights.items():
            try:
                line_no = int(str(key))
            except (ValueError, TypeError):
                continue
            if isinstance(val, (list, tuple)) and len(val) >= 2:
                highlight_ranges.append((line_no, line_no, _num(val[0], 0.0), _num(val[1], 1e9)))
            elif isinstance(val, (int, float)) and not isinstance(val, bool):
                highlight_ranges.append((line_no, line_no, 0.0, float(val)))
            else:
                highlight_ranges.append((line_no, line_no, 0.0, 1e9))

    # 当前行高亮 (reveal/typing 位置): 计算可见行数
    reveal = str(props.get("reveal") or "lines")
    typing = bool(props.get("typing"))
    caret = bool(props.get("caret"))
    # 可见行数: 根据 t 进度 (节点寿命内线性)
    node_start = _num(node.get("start"), 0.0)
    node_end = _num(node.get("end"), 1.0)
    span = max(0.001, node_end - node_start)
    progress = _clamp((t - node_start) / span)
    total_lines = len(lines)
    if reveal == "characters":
        visible_lines = total_lines
    elif reveal == "fade":
        visible_lines = total_lines
    else:  # lines (默认)
        visible_lines = max(0, min(total_lines, int(math.ceil(progress * total_lines))))

    # 代码块背景
    pad = 14
    block_w = max(120, min(w, canvas_w - x - 8))
    block_h = max(40, min(h, canvas_h - y - 8))
    try:
        draw.rounded_rectangle([x, y, x + block_w, y + block_h], radius=10, fill=bg)
    except Exception:  # noqa: BLE001 - 旧 PIL 无 rounded_rectangle
        draw.rectangle([x, y, x + block_w, y + block_h], fill=bg)

    # 标题栏
    top = y + 6
    if title:
        tfont = _sans_font(max(12, font_size - 2))
        tcolor = _hex_color(props.get("fg"), (230, 235, 240))
        draw.text((x + pad, top), str(title), font=tfont, fill=tcolor)
        top += font_size + 4
    # 语言徽章 (右上角)
    if lang:
        lfont = _sans_font(max(10, font_size - 5))
        ltext = str(lang)
        try:
            tw = draw.textlength(ltext, font=lfont)
        except Exception:  # noqa: BLE001
            tw = len(ltext) * (font_size - 5) * 0.6
        draw.text((x + block_w - pad - tw, top), ltext, font=lfont, fill=accent)

    # 行号 + 代码
    gutter_w = 36
    code_x = x + pad + gutter_w
    code_y = top + 10
    # 高亮当前范围 (accent bar)
    for (sl, el, t0, t1) in highlight_ranges:
        if t0 <= t <= t1 and sl < total_lines:
            el = min(el, total_lines - 1)
            y0 = code_y + sl * line_h - 2
            y1 = code_y + (el + 1) * line_h - 2
            try:
                draw.rectangle([x + 2, y0, x + 6, y1], fill=accent)
            except Exception:  # noqa: BLE001
                pass

    for idx in range(total_lines):
        if idx >= visible_lines and reveal in ("lines", "characters"):
            break
        line = lines[idx]
        alpha = 1.0
        if reveal == "fade":
            alpha = _clamp(progress * total_lines - idx)
            if alpha <= 0:
                continue
        line_txt = line
        caret_x = None
        if typing and idx == visible_lines - 1 and idx < total_lines:
            # 打字机: 当前行按字符渐进
            chars_visible = int(math.ceil((t - node_start) * font_size * 6))
            chars_visible = max(0, min(len(line), chars_visible))
            line_txt = line[:chars_visible]
            caret_x = code_x + _text_width(font, line_txt)
        # 行号
        gutter_color = _hex_color(props.get("gutter_color"), _DEFAULT_GUTTER)
        try:
            draw.text((x + pad + 6, code_y + idx * line_h), str(idx + 1),
                      font=font, fill=gutter_color)
        except Exception:  # noqa: BLE001
            pass
        # 代码 (按 token 着色)
        _draw_colored_code(draw, font, code_x, code_y + idx * line_h, line_txt,
                           lang, fg, alpha)
        # 闪烁光标
        if caret and caret_x is not None:
            if int(t * 2) % 2 == 0:  # 2Hz 闪烁
                try:
                    draw.rectangle([caret_x, code_y + idx * line_h,
                                    caret_x + font_size * 0.55,
                                    code_y + idx * line_h + font_size], fill=fg)
                except Exception:  # noqa: BLE001
                    pass


def _text_width(font: Any, text: str) -> float:
    """测量文本宽度 (兼容不同 PIL)。"""
    try:
        return font.getlength(text)
    except Exception:  # noqa: BLE001
        try:
            return font.getsize(text)[0]
        except Exception:  # noqa: BLE001
            return len(text) * 8.0


def _draw_colored_code(draw: Any, font: Any, x: float, y: float, line: str,
                       lang: str, fg: Tuple[int, int, int], alpha: float) -> None:
    """按 token 着色绘制一行代码 (逐 token 累积 x 偏移)。"""
    tokens = _tokenize_code(lang, line)
    cx = x
    for kind, text in tokens:
        color = _SYNTAX_COLORS.get(kind, fg)
        if alpha < 1.0:
            color = _blend((0, 0, 0), color, alpha)
        try:
            draw.text((cx, y), text, font=font, fill=color)
        except Exception:  # noqa: BLE001
            pass
        cx += _text_width(font, text)


# ---------------------------------------------------------------------------
# 其它节点渲染: title / subtitle / box / dataflow / bg
# ---------------------------------------------------------------------------

def _render_title_node(draw: Any, node: Dict[str, Any], t: float,
                       canvas_w: int, canvas_h: int) -> None:
    """渲染 ``title`` 节点: 大标题。"""
    props = node.get("props") or {}
    if not isinstance(props, dict):
        props = {}
    text = str(props.get("text") or "")
    if not text:
        return
    font_size = max(12, _int(props.get("font_size"), 48))
    color = _hex_color(props.get("color"), _DEFAULT_FG)
    x = _num(props.get("x"), canvas_w * 0.5)
    y = _num(props.get("y"), canvas_h * 0.4)
    align = str(props.get("align") or "center")
    font = _sans_font(font_size)
    node_start = _num(node.get("start"), 0.0)
    node_end = _num(node.get("end"), 1.0)
    fade = _fade_in(t, node_start, 0.4) * _fade_out(t, node_end, 0.4)
    if fade <= 0:
        return
    if fade < 1.0:
        color = _blend((0, 0, 0), color, fade)
    tw = _text_width(font, text)
    if align == "left":
        px = x
    elif align == "right":
        px = x - tw
    else:
        px = x - tw / 2
    # slide 入场: 横向位移
    slide = bool(props.get("slide"))
    if slide:
        px -= (1.0 - _ease(fade)) * 60
    try:
        draw.text((px, y), text, font=font, fill=color)
    except Exception:  # noqa: BLE001
        pass


def _render_subtitle_node(draw: Any, node: Dict[str, Any], t: float,
                          canvas_w: int, canvas_h: int) -> None:
    """渲染 ``subtitle`` 节点: 底部说明条 (可打字机)。"""
    props = node.get("props") or {}
    if not isinstance(props, dict):
        props = {}
    text = str(props.get("text") or "")
    if not text:
        return
    font_size = max(10, _int(props.get("font_size"), 24))
    color = _hex_color(props.get("color"), (255, 255, 255))
    bg = _hex_color(props.get("bg"), (30, 34, 42))
    y = _num(props.get("y"), canvas_h - 90)
    font = _sans_font(font_size)
    node_start = _num(node.get("start"), 0.0)
    node_end = _num(node.get("end"), 1.0)
    fade = _fade_in(t, node_start, 0.3) * _fade_out(t, node_end, 0.3)
    if fade <= 0:
        return
    typewriter = bool(props.get("typewriter"))
    shown = text
    if typewriter:
        span = max(0.001, node_end - node_start)
        progress = _clamp((t - node_start) / span)
        n_chars = int(round(progress * len(text)))
        shown = text[:n_chars]
    if not shown:
        return
    tw = _text_width(font, shown)
    px = (canvas_w - tw) / 2
    # 半透明底条
    try:
        draw.rounded_rectangle([px - 20, y - font_size * 0.4,
                                px + tw + 20, y + font_size * 1.4],
                               radius=8, fill=(bg[0], bg[1], bg[2]))
    except Exception:  # noqa: BLE001
        pass
    if fade < 1.0:
        color = _blend((0, 0, 0), color, fade)
    try:
        draw.text((px, y), shown, font=font, fill=color)
    except Exception:  # noqa: BLE001
        pass


def _render_box_node(draw: Any, node: Dict[str, Any], t: float,
                     canvas_w: int, canvas_h: int) -> None:
    """渲染 ``box`` 节点: 圆角矩形 / 标注框。"""
    props = node.get("props") or {}
    if not isinstance(props, dict):
        props = {}
    x = _num(props.get("x"), 100)
    y = _num(props.get("y"), 100)
    w = max(10, _num(props.get("w"), 300))
    h = max(10, _num(props.get("h"), 160))
    r = _num(props.get("r"), 12)
    fill = _hex_color(props.get("fill"), (40, 44, 54))
    stroke = _hex_color(props.get("stroke"), (79, 195, 247))
    stroke_w = max(1, _int(props.get("stroke_w"), 2))
    node_start = _num(node.get("start"), 0.0)
    node_end = _num(node.get("end"), 1.0)
    fade = _fade_in(t, node_start, 0.3) * _fade_out(t, node_end, 0.3)
    if fade <= 0:
        return
    grow = bool(props.get("grow"))
    if grow:
        progress = _ease(fade)
        w *= progress
        h *= progress
    if fade < 1.0:
        fill = _blend((0, 0, 0), fill, fade)
        stroke = _blend((0, 0, 0), stroke, fade)
    try:
        draw.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=fill,
                               outline=stroke, width=stroke_w)
    except Exception:  # noqa: BLE001 - 旧 PIL 退化
        draw.rectangle([x, y, x + w, y + h], fill=fill, outline=stroke,
                       width=stroke_w)
    label = props.get("label")
    if label:
        lfont = _sans_font(max(10, _int(props.get("font_size"), 18)))
        lcolor = _hex_color(props.get("label_color"), (255, 255, 255))
        try:
            draw.text((x + 10, y + 8), str(label), font=lfont, fill=lcolor)
        except Exception:  # noqa: BLE001
            pass


def _render_dataflow_node(draw: Any, node: Dict[str, Any], t: float,
                          canvas_w: int, canvas_h: int) -> None:
    """渲染 ``dataflow`` 节点: 两点间的流动点 / 虚线。"""
    props = node.get("props") or {}
    if not isinstance(props, dict):
        props = {}
    x1 = _num(props.get("x1"), 0.0)
    y1 = _num(props.get("y1"), 0.0)
    x2 = _num(props.get("x2"), canvas_w)
    y2 = _num(props.get("y2"), canvas_h)
    color = _hex_color(props.get("color"), _DEFAULT_ACCENT)
    width = max(1, _int(props.get("width"), 3))
    node_start = _num(node.get("start"), 0.0)
    node_end = _num(node.get("end"), 1.0)
    fade = _fade_in(t, node_start, 0.2) * _fade_out(t, node_end, 0.2)
    if fade <= 0:
        return
    if fade < 1.0:
        color = _blend((0, 0, 0), color, fade)
    dash = bool(props.get("dash"))
    dot = bool(props.get("dot"))
    speed = max(0.1, _num(props.get("speed"), 1.0))
    span = max(0.001, node_end - node_start)
    progress = _clamp((t - node_start) / span * speed)
    # 虚线 (静态基线)
    if dash:
        total = math.hypot(x2 - x1, y2 - y1)
        if total > 0:
            seg = 12.0
            n = max(1, int(total / seg))
            for i in range(n):
                a = i * seg / total
                b = (i + 0.6) * seg / total
                if b > 1:
                    b = 1.0
                ax = x1 + (x2 - x1) * a
                ay = y1 + (y2 - y1) * a
                bx = x1 + (x2 - x1) * b
                by = y1 + (y2 - y1) * b
                try:
                    draw.line([ax, ay, bx, by], fill=color, width=width)
                except Exception:  # noqa: BLE001
                    pass
    # 流动点
    if dot:
        px = x1 + (x2 - x1) * progress
        py = y1 + (y2 - y1) * progress
        rad = max(3, width + 2)
        try:
            draw.ellipse([px - rad, py - rad, px + rad, py + rad], fill=color)
        except Exception:  # noqa: BLE001
            pass


def _render_bg_node(draw: Any, node: Dict[str, Any], t: float,
                    canvas_w: int, canvas_h: int) -> None:
    """渲染 ``bg`` 节点: 背景 (solid / gradient / grid)。"""
    props = node.get("props") or {}
    if not isinstance(props, dict):
        props = {}
    btype = str(props.get("type") or "solid")
    c1 = _hex_color(props.get("color1"), _DEFAULT_BG)
    c2 = _hex_color(props.get("color2"), (40, 60, 90))
    grid_color = _hex_color(props.get("grid_color"), (60, 70, 90))
    grid_size = max(8, _int(props.get("grid_size"), 48))
    if btype == "gradient":
        # 逐行绘制水平渐变线 (每行一种混合色, 简单可靠)
        for yy in range(canvas_h):
            frac = yy / max(1, canvas_h - 1)
            row = _blend(c1, c2, frac)
            try:
                draw.line([0, yy, canvas_w, yy], fill=row, width=1)
            except Exception:  # noqa: BLE001
                break
        else:
            pass
    elif btype == "grid":
        try:
            draw.rectangle([0, 0, canvas_w, canvas_h], fill=c1)
        except Exception:  # noqa: BLE001
            pass
        # 滚动网格线 (随 t 缓慢滚动)
        offset = int((t * 24) % grid_size)
        for gx in range(-offset, canvas_w + grid_size, grid_size):
            try:
                draw.line([gx, 0, gx, canvas_h], fill=grid_color, width=1)
            except Exception:  # noqa: BLE001
                pass
        for gy in range(-offset, canvas_h + grid_size, grid_size):
            try:
                draw.line([0, gy, canvas_w, gy], fill=grid_color, width=1)
            except Exception:  # noqa: BLE001
                pass
    else:  # solid
        try:
            draw.rectangle([0, 0, canvas_w, canvas_h], fill=c1)
        except Exception:  # noqa: BLE001
            pass


# 节点分发: type -> 渲染函数
_NODE_RENDERERS: Dict[str, Callable[[Any, Dict[str, Any], float, int, int], None]] = {
    "code": _render_code_node,
    "title": _render_title_node,
    "subtitle": _render_subtitle_node,
    "box": _render_box_node,
    "dataflow": _render_dataflow_node,
    "bg": _render_bg_node,
}


# ---------------------------------------------------------------------------
# 帧绘制 (纯函数)
# ---------------------------------------------------------------------------

def draw_frame(project_json: Dict[str, Any], t: float) -> Any:
    """绘制时间 t 的单帧。**纯函数**: 只读 project_json + t, 无全局可变状态。

    先画背景 (首个 bg 节点, 否则深色默认), 再按列表顺序渲染所有
    ``start <= t <= end`` 的节点; 范围外的节点跳过, 未知类型跳过 (记录日志)。
    """
    from PIL import Image, ImageDraw

    width = max(1, _int(project_json.get("width"), 1280))
    height = max(1, _int(project_json.get("height"), 720))
    img = Image.new("RGB", (width, height), _DEFAULT_BG)
    draw = ImageDraw.Draw(img)

    nodes = project_json.get("nodes")
    if not isinstance(nodes, list):
        nodes = []
    # 背景节点 (type == "bg") 优先绘制
    bg_nodes = [n for n in nodes
                if isinstance(n, dict) and str(n.get("type")) == "bg"]
    for n in bg_nodes:
        if _node_active(n, t):
            _render_bg_node(draw, n, t, width, height)
    # 其余节点按顺序
    for n in nodes:
        if not isinstance(n, dict):
            continue
        ntype = str(n.get("type"))
        if ntype == "bg":
            continue
        if ntype not in _KNOWN_NODE_TYPES:
            # 未知类型: 跳过, 不执行 (fail-closed)
            continue
        if not _node_active(n, t):
            continue
        renderer = _NODE_RENDERERS.get(ntype)
        if renderer is not None:
            try:
                renderer(draw, n, t, width, height)
            except Exception:  # noqa: BLE001 - 单节点失败不影响整帧
                continue
    return img


# ---------------------------------------------------------------------------
# 渲染 job (render_video / render_contact_sheet)
# ---------------------------------------------------------------------------

def _start_render_job(kind: str, worker: Callable[[], Dict[str, Any]]) -> str:
    """启动后台渲染 job; 立即返回 job_id, 完成状态由 ``GET /api/codeanim/job`` 轮询。"""
    job_id = uuid.uuid4().hex[:12]
    job: Dict[str, Any] = {
        "id": job_id,
        "kind": kind,
        "status": "running",
        "out_path": "",
        "returncode": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "error": "",
        "started_at": time.time(),
        "finished_at": None,
        "result": None,
    }
    with _JOBS_LOCK:
        _JOBS[job_id] = job
        _prune_jobs_locked()

    def _run() -> None:
        error_msg = ""
        result: Optional[Dict[str, Any]] = None
        try:
            result = worker()
        except Exception as exc:  # noqa: BLE001
            error_msg = str(exc)
        with _JOBS_LOCK:
            cur = _JOBS.get(job_id)
            if cur is None:
                return
            cur["finished_at"] = time.time()
            cur["result"] = result
            if error_msg:
                cur["status"] = "error"
                cur["error"] = error_msg
            else:
                cur["status"] = "done"
                if isinstance(result, dict):
                    cur["out_path"] = result.get("out_path") or ""

    thread = threading.Thread(target=_run, daemon=True,
                              name=f"codeanim-{kind}-{job_id}")
    thread.start()
    return job_id


def _prune_jobs_locked() -> None:
    """调用方需持有 _JOBS_LOCK; 按 started_at 淘汰最老的 job 直到容量合规。"""
    if len(_JOBS) <= _JOB_CAP:
        return
    ordered = sorted(_JOBS.items(), key=lambda kv: kv[1].get("started_at", 0))
    for key, _job in ordered[: len(_JOBS) - _JOB_CAP]:
        _JOBS.pop(key, None)


#: 候选视频编码器 (按优先级): 多数 ffmpeg 有 libx264; mh 自带的 MediaFoundation
#: 构建没有 libx264, 退化到 h264_mf / mpeg4。均输出 mp4 容器。
_VIDEO_ENCODERS = ("libx264", "h264_mf", "mpeg4")


def _probe_encoder(ffmpeg: str) -> Optional[str]:
    """探测 ffmpeg 可用的第一个视频编码器 (mp4 兼容)。

    通过 ``ffmpeg -encoders`` 输出匹配; 不实际编码, 快。
    """
    try:
        proc = subprocess.Popen([ffmpeg, "-hide_banner", "-encoders"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                shell=False)
        out = (proc.stdout.read() or b"").decode("utf-8", "replace")
        proc.wait()
    except OSError:
        return None
    for enc in _VIDEO_ENCODERS:
        if f" {enc}" in out or enc in out:
            return enc
    return None


def render_video(project_json: Dict[str, Any], out_path: str, *,
                 fps: int = 30, on_progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """同步渲染视频 (Pillow 逐帧 + ffmpeg rawvideo 管道编码)。

    返回 ``{"out_path","frames","fps","elapsed","size_bytes"}``。
    ffmpeg 缺失时抛出 RuntimeError。
    """
    err = validate_project(project_json)
    if err:
        raise ValueError(err)
    width = max(1, _int(project_json.get("width"), 1280))
    height = max(1, _int(project_json.get("height"), 720))
    duration = max(0.0, _num(project_json.get("duration"), 1.0))
    fps = max(1, int(fps))
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg 不可用: 未找到可执行文件 (设置 TUAN_FFMPEG 或安装 ffmpeg)")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    encoder = _probe_encoder(ffmpeg)
    if encoder is None:
        raise RuntimeError("ffmpeg 无可用视频编码器 (libx264/h264_mf/mpeg4 均缺)")
    argv = [
        ffmpeg, "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "-i", "-",
        "-c:v", encoder,
    ]
    if encoder == "libx264":
        argv += ["-preset", "veryfast"]
    argv += [
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out),
    ]
    total_frames = max(1, int(math.ceil(duration * fps)))
    started = time.time()
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, shell=False)
    except FileNotFoundError as exc:
        raise RuntimeError(f"ffmpeg 启动失败: {exc}") from exc
    try:
        for i in range(total_frames):
            t = i / fps
            frame = draw_frame(project_json, t)
            if proc.stdin is not None:
                proc.stdin.write(frame.tobytes())
            if on_progress and (i % max(1, total_frames // 10) == 0 or i == total_frames - 1):
                try:
                    on_progress(i + 1, total_frames)
                except Exception:  # noqa: BLE001 - 回调异常忽略
                    pass
    except Exception:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass
    stderr_b = b""
    if proc.stderr is not None:
        stderr_b = proc.stderr.read() or b""
    proc.wait()
    elapsed = time.time() - started
    if proc.returncode != 0:
        tail = stderr_b.decode("utf-8", errors="replace")[-_TAIL_BYTES:]
        raise RuntimeError(f"ffmpeg 编码失败 (exit={proc.returncode}): {tail}")
    size_bytes = out.stat().st_size if out.is_file() else 0
    return {
        "out_path": str(out),
        "frames": total_frames,
        "fps": fps,
        "elapsed": round(elapsed, 3),
        "size_bytes": size_bytes,
    }


def render_contact_sheet(project_json: Dict[str, Any], times: List[float],
                         out_path: str) -> Dict[str, Any]:
    """绘制接触表 (多时间点缩略图网格) 为单张 PNG。

    返回 ``{"out_path","times","size_bytes"}``。
    """
    err = validate_project(project_json)
    if err:
        raise ValueError(err)
    width = max(1, _int(project_json.get("width"), 1280))
    height = max(1, _int(project_json.get("height"), 720))
    cols = 3
    thumb_w = max(64, width // cols)
    thumb_h = max(48, int(height * (thumb_w / max(1, width))))
    rows = max(1, (len(times) + cols - 1) // cols)
    from PIL import Image
    sheet = Image.new("RGB", (thumb_w * cols, thumb_h * rows), (18, 20, 26))
    for idx, tt in enumerate(times):
        try:
            frame = draw_frame(project_json, float(tt))
            frame = frame.resize((thumb_w, thumb_h))
        except Exception:  # noqa: BLE001 - 单点失败用占位
            frame = Image.new("RGB", (thumb_w, thumb_h), (40, 44, 54))
        cx = (idx % cols) * thumb_w
        cy = (idx // cols) * thumb_h
        sheet.paste(frame, (cx, cy))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "PNG")
    return {
        "out_path": str(out),
        "times": [float(tt) for tt in times],
        "size_bytes": out.stat().st_size if out.is_file() else 0,
    }


def start_render_job(project_json: Dict[str, Any], out_path: str,
                     fps: int = 30) -> str:
    """后台渲染视频; 返回 job_id。"""
    return _start_render_job(
        "render",
        lambda: render_video(project_json, out_path, fps=fps))


def start_contact_job(project_json: Dict[str, Any], times: List[float],
                      out_path: str) -> str:
    """后台接触表; 返回 job_id。"""
    return _start_render_job(
        "contact",
        lambda: render_contact_sheet(project_json, times, out_path))


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """查询单个 job 状态 (深拷贝, 防调用方改内部表)。"""
    with _JOBS_LOCK:
        job = _JOBS.get((job_id or "").strip())
        return dict(job) if job else None


def list_jobs(limit: int = 20) -> List[Dict[str, Any]]:
    """最近的 jobs (按 started_at 倒序, 截断到 limit)。"""
    with _JOBS_LOCK:
        ordered = sorted(_JOBS.values(), key=lambda j: j.get("started_at", 0),
                         reverse=True)
        return [dict(j) for j in ordered[: max(1, min(limit, 100))]]


def _reset_jobs() -> None:
    """清空 job 表 (测试隔离用)。"""
    with _JOBS_LOCK:
        _JOBS.clear()


def status() -> Dict[str, Any]:
    """整体可用性状态: ``{available, ffmpeg, reason}``。"""
    if not _pillow_available():
        return {"available": False, "ffmpeg": "", "reason": "Pillow 不可用 (需 PIL)"}
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return {"available": False, "ffmpeg": "",
                "reason": "未找到 ffmpeg (设置 TUAN_FFMPEG 或安装 ffmpeg)"}
    return {"available": True, "ffmpeg": ffmpeg, "reason": ""}


# ---------------------------------------------------------------------------
# 路径护栏 (媒体输出根: <workspace>/.tuan/codeanim/)
# ---------------------------------------------------------------------------

def codeanim_root(workspace: str) -> Path:
    """返回 ``<workspace>/.tuan/codeanim`` 根目录 (resolve)。"""
    return (Path(workspace or ".").resolve() / ".tuan" / "codeanim")


def resolve_media_path(workspace: str, rel: str) -> Optional[Path]:
    """把 media 相对路径解析到 codeanim 根之下; 越界返回 None。"""
    raw = (rel or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or ".." in raw.split("/"):
        return None
    root = codeanim_root(workspace)
    target = (root / raw).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    return target


__all__ = [
    "ffmpeg_available",
    "find_ffmpeg",
    "validate_project",
    "draw_frame",
    "render_video",
    "render_contact_sheet",
    "start_render_job",
    "start_contact_job",
    "get_job",
    "list_jobs",
    "resolve_media_path",
    "codeanim_root",
    "status",
    "_reset_jobs",
    "_KNOWN_NODE_TYPES",
]
