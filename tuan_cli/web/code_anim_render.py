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

import logging
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量 / 配置
# ---------------------------------------------------------------------------

#: 已知的 node type 白名单 (未知类型跳过, 不执行)。
_KNOWN_NODE_TYPES = frozenset({
    "code", "title", "subtitle", "box", "dataflow", "bg",
    # 阶段 3 高级动效原语 (transition / particles / kinetic / beat)
    "transition", "particles", "kinetic", "beat",
    # 阶段 8 givemotion 式动效补全 (shape_morph / camera / path_motion / hand_drawn)
    "shape_morph", "camera", "path_motion", "hand_drawn",
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
    except Exception as exc:  # noqa: BLE001 - PIL 必须可用
        log.debug("_load_font(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        return None
    for path in cands:
        if os.path.isfile(path):
            key = (path, size)
            if key not in _FONT_CACHE:
                try:
                    _FONT_CACHE[key] = ImageFont.truetype(path, size)
                except Exception as exc:  # noqa: BLE001 - 单个字体失败继续找
                    log.debug("_load_font(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                    continue
            return _FONT_CACHE.get(key) or None
    try:
        return ImageFont.load_default()
    except Exception as exc:  # noqa: BLE001
        log.debug("_load_font(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
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
      3. imageio-ffmpeg 打包的二进制 (pip install imageio-ffmpeg 即得);
      4. 系统 PATH 上的 ``ffmpeg`` (``shutil.which``)。
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
    try:  # imageio-ffmpeg 自带一个静态编译的 ffmpeg 二进制
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).is_file():
            return str(exe)
    except Exception as exc:  # noqa: BLE001 - 未安装/损坏都降级到 PATH
        log.debug("find_ffmpeg(): imageio_ffmpeg 不可用: %s", exc)
    return shutil.which("ffmpeg")


def ffmpeg_available() -> bool:
    """ffmpeg 是否可用。"""
    return bool(find_ffmpeg())


def _pillow_available() -> bool:
    """Pillow 是否可导入。"""
    try:
        from PIL import Image  # noqa: F401
        return True
    except Exception as exc:  # noqa: BLE001
        log.debug("_pillow_available(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
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
    # 资源上限 (审计 P1-13 深度加固): 畸形项目 (超大分辨率/时长/帧率) 会让
    # 渲染循环耗尽内存/永久占用后台 job —— 在校验层直接拒绝。
    if project_json["width"] > 7680 or project_json["height"] > 7680:
        return "project_json.width/height 超过上限 (7680)"
    if project_json["fps"] > 240:
        return "project_json.fps 超过上限 (240)"
    if project_json["duration"] > 3600:
        return "project_json.duration 超过上限 (3600s)"
    est_frames = int(project_json["duration"] * project_json["fps"]) + 1
    if est_frames > 200_000:
        return "project_json 渲染帧数超过上限 (duration*fps ≤ 200000)"
    nodes = project_json.get("nodes")
    if nodes is not None and not isinstance(nodes, list):
        return "project_json.nodes 必须是数组"
    if isinstance(nodes, list):
        if len(nodes) > 500:
            return "project_json.nodes 超过上限 (500)"
        for idx, nd in enumerate(nodes):
            if not isinstance(nd, dict):
                return f"project_json.nodes[{idx}] 必须是对象"
            nt = nd.get("type")
            if not isinstance(nt, str) or not nt.strip():
                return f"project_json.nodes[{idx}].type 必须是非空字符串"
    # 阶段 9: 音频混音轨 (cinecode 式) —— 路径或对象列表, 逐项校验, fail-closed
    audio = project_json.get("audio")
    if audio is not None:
        if isinstance(audio, str):
            if not audio.strip():
                return "project_json.audio 路径不能为空"
        elif isinstance(audio, list):
            for idx, tr in enumerate(audio):
                if not isinstance(tr, dict):
                    return f"project_json.audio[{idx}] 必须是对象"
                ap = tr.get("path")
                if not isinstance(ap, str) or not ap.strip():
                    return f"project_json.audio[{idx}].path 必须是非空字符串"
                vol = tr.get("volume")
                if vol is not None and (not isinstance(vol, (int, float))
                                        or isinstance(vol, bool) or vol <= 0):
                    return f"project_json.audio[{idx}].volume 必须是 > 0 的数字"
                st = tr.get("start")
                if st is not None and (not isinstance(st, (int, float))
                                       or isinstance(st, bool) or st < 0):
                    return f"project_json.audio[{idx}].start 必须 >= 0 的数字"
        else:
            return "project_json.audio 必须是路径字符串或对象数组"
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
            except Exception as exc:  # noqa: BLE001
                log.warning("_render_code_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
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
        except Exception as exc:  # noqa: BLE001
            log.warning("_render_code_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
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
                except Exception as exc:  # noqa: BLE001
                    log.warning("_render_code_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                    pass


def _text_width(font: Any, text: str) -> float:
    """测量文本宽度 (兼容不同 PIL)。"""
    try:
        return float(font.getlength(text))
    except Exception:  # noqa: BLE001
        try:
            return float(font.getsize(text)[0])
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
        except Exception as exc:  # noqa: BLE001
            log.warning("_draw_colored_code(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
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
    except Exception as exc:  # noqa: BLE001
        log.warning("_render_title_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
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
    except Exception as exc:  # noqa: BLE001
        log.warning("_render_subtitle_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        pass
    if fade < 1.0:
        color = _blend((0, 0, 0), color, fade)
    try:
        draw.text((px, y), shown, font=font, fill=color)
    except Exception as exc:  # noqa: BLE001
        log.warning("_render_subtitle_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
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
        except Exception as exc:  # noqa: BLE001
            log.warning("_render_box_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
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
                except Exception as exc:  # noqa: BLE001
                    log.warning("_render_dataflow_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                    pass
    # 流动点
    if dot:
        px = x1 + (x2 - x1) * progress
        py = y1 + (y2 - y1) * progress
        rad = max(3, width + 2)
        try:
            draw.ellipse([px - rad, py - rad, px + rad, py + rad], fill=color)
        except Exception as exc:  # noqa: BLE001
            log.warning("_render_dataflow_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
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
            except Exception as exc:  # noqa: BLE001
                log.debug("_render_bg_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                break
        else:
            pass
    elif btype == "grid":
        try:
            draw.rectangle([0, 0, canvas_w, canvas_h], fill=c1)
        except Exception as exc:  # noqa: BLE001
            log.warning("_render_bg_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass
        # 滚动网格线 (随 t 缓慢滚动)
        offset = int((t * 24) % grid_size)
        for gx in range(-offset, canvas_w + grid_size, grid_size):
            try:
                draw.line([gx, 0, gx, canvas_h], fill=grid_color, width=1)
            except Exception as exc:  # noqa: BLE001
                log.warning("_render_bg_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                pass
        for gy in range(-offset, canvas_h + grid_size, grid_size):
            try:
                draw.line([0, gy, canvas_w, gy], fill=grid_color, width=1)
            except Exception as exc:  # noqa: BLE001
                log.warning("_render_bg_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                pass
    else:  # solid
        try:
            draw.rectangle([0, 0, canvas_w, canvas_h], fill=c1)
        except Exception as exc:  # noqa: BLE001
            log.warning("_render_bg_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass


# ---------------------------------------------------------------------------
# 高级动效原语 (阶段 3: 对齐 givemotion/Motion 卖点)
#   * transition  场景转场 (crossfade / slide / zoom / wipe)
#   * particles   粒子爆发 (发射/漂移/重力/消散)
#   * kinetic     动能排版 (逐字弹入/缩放/旋转, kinetic typography)
#   * beat        音乐卡点脉冲 (背景/边框随 BPM 脉冲)
# 全部为纯函数 (只读 project_json + t), 无全局可变状态, 保持 frame-stable。
# ---------------------------------------------------------------------------

def _render_transition_node(draw: Any, node: Dict[str, Any], t: float,
                            canvas_w: int, canvas_h: int) -> None:
    """渲染 ``transition`` 节点: 场景转场遮罩。

    props:
      type: crossfade | slide | zoom | wipe
      from_color / to_color: 转场主色 (默认黑/白)
      direction: for slide/wipe, "ltr"/"rtl"/"ttb"/"btt" (默认 ltr)
    """
    props = node.get("props") or {}
    if not isinstance(props, dict):
        props = {}
    ttype = str(props.get("type") or "crossfade")
    c1 = _hex_color(props.get("from_color"), (0, 0, 0))
    c2 = _hex_color(props.get("to_color"), (255, 255, 255))
    direction = str(props.get("direction") or "ltr")
    node_start = _num(node.get("start"), 0.0)
    node_end = _num(node.get("end"), 1.0)
    span = max(0.001, node_end - node_start)
    progress = _ease(_clamp((t - node_start) / span))
    if progress <= 0 or progress >= 1:
        return
    try:
        if ttype == "slide":
            # 用 to_color 滑入覆盖: 方向决定位移轴
            if direction in ("ttb", "btt"):
                shift = (progress * canvas_h) if direction == "ttb" else (-(1 - progress) * canvas_h)
                draw.rectangle([0, shift, canvas_w, shift + canvas_h], fill=c2)
            else:
                shift = (progress * canvas_w) if direction == "ltr" else (-(1 - progress) * canvas_w)
                draw.rectangle([shift, 0, shift + canvas_w, canvas_h], fill=c2)
        elif ttype == "zoom":
            # 以画面中心放大 to_color (矩形随 progress 收缩)
            half_w = canvas_w * (1 - progress) / 2
            half_h = canvas_h * (1 - progress) / 2
            draw.rectangle([half_w, half_h, canvas_w - half_w, canvas_h - half_h],
                           fill=c2)
        elif ttype == "wipe":
            if direction in ("ttb", "btt"):
                cut = progress * canvas_h
                if direction == "ttb":
                    draw.rectangle([0, 0, canvas_w, cut], fill=c2)
                else:
                    draw.rectangle([0, canvas_h - cut, canvas_w, canvas_h], fill=c2)
            else:
                cut = progress * canvas_w
                if direction == "ltr":
                    draw.rectangle([0, 0, cut, canvas_h], fill=c2)
                else:
                    draw.rectangle([canvas_w - cut, 0, canvas_w, canvas_h], fill=c2)
        else:  # crossfade: 混合黑/白遮罩, 透明度随 progress 变化
            blend = _blend(c1, c2, progress)
            # 半透明遮罩: 用 blend 色整屏覆盖 (Pillow 无 alpha 需手动混)
            overlay = _blend(c1, c2, progress)
            draw.rectangle([0, 0, canvas_w, canvas_h],
                           fill=(overlay[0], overlay[1], overlay[2]))
    except Exception as exc:  # noqa: BLE001 - 绘制失败静默 (frame 仍可渲染)
        log.warning("_render_transition_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        pass


def _render_particles_node(draw: Any, node: Dict[str, Any], t: float,
                           canvas_w: int, canvas_h: int) -> None:
    """渲染 ``particles`` 节点: 粒子爆发。

    props:
      color: 粒子颜色 (默认强调蓝)
      count: 粒子数 (默认 60)
      origin: "center" | "top" | "bottom" | (x,y)
      spread: 扩散半径 (默认 120)
      gravity: 重力 (默认 0, 正向下)
      life: 生命周期秒 (默认 1.2)
    """
    props = node.get("props") or {}
    if not isinstance(props, dict):
        props = {}
    color = _hex_color(props.get("color"), _DEFAULT_ACCENT)
    count = max(1, _int(props.get("count"), 60))
    spread = max(1.0, _num(props.get("spread"), 120.0))
    gravity = _num(props.get("gravity"), 0.0)
    life = max(0.1, _num(props.get("life"), 1.2))
    origin = props.get("origin", "center")
    node_start = _num(node.get("start"), 0.0)
    node_end = _num(node.get("end"), 1.0)
    # 粒子仅在节点激活期内发射; t 超出则整体淡出。
    if t < node_start or t > node_end:
        return
    if isinstance(origin, (list, tuple)) and len(origin) >= 2:
        ox, oy = _num(origin[0], canvas_w / 2), _num(origin[1], canvas_h / 2)
    elif origin == "top":
        ox, oy = canvas_w / 2, 0
    elif origin == "bottom":
        ox, oy = canvas_w / 2, canvas_h
    else:
        ox, oy = canvas_w / 2, canvas_h / 2
    age = t - node_start
    # 每颗粒子: 伪随机方向 (按 index 确定性), 位移 = 扩散 * 进度 + 重力
    rng = _clamp(age / life)
    # 整体透明度: 生命周期末端淡出
    global_alpha = _fade_out(t, node_end, 0.2)
    if global_alpha <= 0:
        return
    for i in range(count):
        # 确定性伪随机角度/速度 (基于 i 的 hash, 保证 frame-stable)
        seed = (i * 2654435761) & 0xFFFFFFFF
        ang = (seed % 360) * math.pi / 180.0
        speed = spread * (0.5 + ((seed >> 8) % 100) / 100.0)
        dx = math.cos(ang) * speed * rng
        dy = math.sin(ang) * speed * rng + gravity * rng * rng
        px = ox + dx
        py = oy + dy
        # 粒子尺寸随生命衰减
        size = max(1.0, 3.0 * (1.0 - rng))
        alpha = (1.0 - rng) * global_alpha
        c = _blend((0, 0, 0), color, alpha)
        try:
            draw.ellipse([px - size, py - size, px + size, py + size], fill=c)
        except Exception as exc:  # noqa: BLE001
            log.warning("_render_particles_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass


def _render_kinetic_node(draw: Any, node: Dict[str, Any], t: float,
                         canvas_w: int, canvas_h: int) -> None:
    """渲染 ``kinetic`` 节点: 动能排版 (逐字弹入 / 缩放 / 旋转)。

    props:
      text: 文本
      font_size: 字号 (默认 40)
      color: 颜色
      x / y: 中心位置
      mode: "char" (逐字弹入, 默认) | "scale" (整体缩放) | "rotate" (旋转)
      stagger: 逐字错峰 (默认 0.05s)
    """
    props = node.get("props") or {}
    if not isinstance(props, dict):
        props = {}
    text = str(props.get("text") or "")
    if not text:
        return
    font_size = max(12, _int(props.get("font_size"), 40))
    color = _hex_color(props.get("color"), _DEFAULT_FG)
    x = _num(props.get("x"), canvas_w * 0.5)
    y = _num(props.get("y"), canvas_h * 0.5)
    mode = str(props.get("mode") or "char")
    stagger = max(0.0, _num(props.get("stagger"), 0.05))
    font = _sans_font(font_size)
    node_start = _num(node.get("start"), 0.0)
    node_end = _num(node.get("end"), 1.0)
    fade = _fade_in(t, node_start, 0.3) * _fade_out(t, node_end, 0.3)
    if fade <= 0:
        return
    tw = _text_width(font, text)
    if mode == "scale":
        progress = _ease(_clamp((t - node_start) / 0.5))
        scale = 0.5 + 0.5 * progress
        _draw_scaled_text(draw, font, text, x, y, scale, color, fade, tw)
        return
    if mode == "rotate":
        progress = _ease(_clamp((t - node_start) / 0.6))
        angle = progress * 360.0
        _draw_rotated_text(draw, font, text, x, y, angle, color, fade, tw)
        return
    # char 逐字弹入
    char_w = _text_width(font, "M")
    if char_w <= 0:
        char_w = font_size * 0.6
    start_x = x - tw / 2
    for i, ch in enumerate(text):
        if ch == " ":
            continue
        char_start = node_start + i * stagger
        cf = _ease(_clamp((t - char_start) / 0.15))
        if cf <= 0:
            continue
        c = _blend((0, 0, 0), color, cf * fade)
        cx = start_x + i * char_w
        # 逐字小幅上跳 + 缩放
        jump = (1.0 - cf) * 12
        size_scale = 0.7 + 0.3 * cf
        try:
            _draw_scaled_text(draw, font, ch, cx + char_w / 2, y - jump,
                              size_scale, c, 1.0, char_w)
        except Exception as exc:  # noqa: BLE001
            log.warning("_render_kinetic_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass


def _draw_scaled_text(draw: Any, font: Any, text: str, cx: float, cy: float,
                      scale: float, color: Any, alpha: float, tw: float) -> None:
    """以 (cx,cy) 为中心绘制缩放文本 (用字号近似缩放, Pillow 无原生 scale)。"""
    try:
        # 通过字号近似实现缩放 (避免图像缩放的开销与锯齿)
        base = getattr(font, "size", 40)
        scaled_font = _sans_font(max(8, int(base * max(0.1, scale))))
        c = _blend((0, 0, 0), color, alpha)
        w = _text_width(scaled_font, text)
        draw.text((cx - w / 2, cy - base * scale / 2), text,
                  font=scaled_font, fill=c)
    except Exception as exc:  # noqa: BLE001
        log.warning("_draw_scaled_text(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        pass


def _draw_rotated_text(draw: Any, font: Any, text: str, cx: float, cy: float,
                       angle: float, color: Any, alpha: float, tw: float) -> None:
    """以中心绘制旋转文本 (用整帧旋转近似, 仅在角度显著时做)。"""
    try:
        if abs(angle) < 0.5:
            c = _blend((0, 0, 0), color, alpha)
            draw.text((cx - tw / 2, cy - 20), text, font=font, fill=c)
            return
        # 角度显著: 绘制到临时帧再旋转 (成本高, 但仅节点激活期内调用)
        from PIL import Image
        pad = 64
        w = int(tw + pad * 2)
        h = int(_text_width(font, "M") * 2 + pad * 2)
        tmp = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        from PIL import ImageDraw
        tdraw = ImageDraw.Draw(tmp)
        tdraw.text((pad, pad), text, font=font,
                   fill=(color[0], color[1], color[2], int(alpha * 255)))
        tmp = tmp.rotate(angle, expand=True)
        draw._image.paste(tmp, (int(cx - tmp.width / 2), int(cy - tmp.height / 2)), tmp)
    except Exception as exc:  # noqa: BLE001
        log.warning("_draw_rotated_text(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        pass


def _render_beat_node(draw: Any, node: Dict[str, Any], t: float,
                      canvas_w: int, canvas_h: int) -> None:
    """渲染 ``beat`` 节点: 音乐卡点脉冲。

    props:
      bpm: 每分钟节拍 (默认 120)
      color: 脉冲色 (默认强调蓝)
      kind: "bg" (全屏底色脉冲) | "border" (边框脉冲) | "ring" (中心圆环)
      strength: 脉冲强度 (默认 0.15)
    """
    props = node.get("props") or {}
    if not isinstance(props, dict):
        props = {}
    bpm = max(1.0, _num(props.get("bpm"), 120.0))
    color = _hex_color(props.get("color"), _DEFAULT_ACCENT)
    kind = str(props.get("kind") or "bg")
    strength = _clamp(_num(props.get("strength"), 0.15), 0.0, 1.0)
    node_start = _num(node.get("start"), 0.0)
    node_end = _num(node.get("end"), 1.0)
    fade = _fade_in(t, node_start, 0.2) * _fade_out(t, node_end, 0.2)
    if fade <= 0 or t < node_start or t > node_end:
        return
    # 心跳: 每个节拍一个尖峰 (用相位衰减模拟)
    beat_interval = 60.0 / bpm
    phase = (t - node_start) / beat_interval
    frac = phase - math.floor(phase)  # 0..1 当前拍内位置
    pulse = math.exp(-frac * 5.0) * strength * fade
    if pulse <= 0.001:
        return
    c = _blend((0, 0, 0), color, pulse)
    try:
        if kind == "border":
            bw = max(2, int(pulse * 24))
            draw.rectangle([0, 0, canvas_w, canvas_h], outline=c, width=bw)
        elif kind == "ring":
            cx, cy = canvas_w / 2, canvas_h / 2
            r = max(1.0, (canvas_w * 0.15) * (1.0 + pulse * 3))
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=c, width=4)
        else:  # bg
            # 全屏底色脉冲 (在节点激活时叠加)
            base = _blend((0, 0, 0), c, 0.35)
            draw.rectangle([0, 0, canvas_w, canvas_h], fill=base)
    except Exception as exc:  # noqa: BLE001
        log.warning("_render_beat_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        pass


def _render_shape_morph_node(draw: Any, node: Dict[str, Any], t: float,
                             canvas_w: int, canvas_h: int) -> None:
    """渲染 ``shape_morph`` 节点: 形状渐变 (circle→square→triangle→hex, 逐顶点插值)。

    对齐 givemotion "shape morphing" 卖点。通过把各形状参数化为单位圆上的
    顶点序列 (圆=密采样圆, 正方形=4 角, 三角=3 角, 六边形=6 角, 星=10 角),
    再按 ``progress`` 在两形状顶点序列间做线性插值, 得到连续形变。

    props:
      from / to: 形状名 (circle|square|triangle|hex|star) 默认 circle→square
      color: 填充色 (默认强调蓝)
      x / y: 中心 (默认画布中心)
      size: 半径 (默认 80)
      duration: 形变时长秒 (默认 1.0, 节点 start 起算)
      outline: 仅描边 (默认 False)
    """
    props = node.get("props") or {}
    if not isinstance(props, dict):
        props = {}
    from_shape = str(props.get("from") or "circle")
    to_shape = str(props.get("to") or "square")
    color = _hex_color(props.get("color"), _DEFAULT_ACCENT)
    cx = _num(props.get("x"), canvas_w * 0.5)
    cy = _num(props.get("y"), canvas_h * 0.5)
    size = max(1.0, _num(props.get("size"), 80.0))
    morph_dur = max(0.01, _num(props.get("duration"), 1.0))
    outline = bool(props.get("outline"))
    node_start = _num(node.get("start"), 0.0)
    node_end = _num(node.get("end"), 1.0)
    fade = _fade_in(t, node_start, 0.2) * _fade_out(t, node_end, 0.2)
    if fade <= 0 or t < node_start or t > node_end:
        return
    progress = _ease(_clamp((t - node_start) / morph_dur))
    pts_from = _shape_vertices(from_shape, size, 48)
    pts_to = _shape_vertices(to_shape, size, 48)
    # 线性插值对应顶点
    pts = []
    for i in range(48):
        ax, ay = pts_from[i]
        bx, by = pts_to[i]
        pts.append((cx + ax + (bx - ax) * progress,
                    cy + ay + (by - ay) * progress))
    if fade < 1.0:
        color = _blend((0, 0, 0), color, fade)
    try:
        if outline:
            draw.polygon(pts, outline=color, width=max(2, _int(props.get("stroke_w"), 3)))
        else:
            draw.polygon(pts, fill=color)
    except Exception as exc:  # noqa: BLE001
        log.warning("_render_shape_morph_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        pass


def _shape_vertices(name: str, size: float, n: int) -> List[Tuple[float, float]]:
    """把形状参数化为 n 个顶点 (单位圆上极坐标, 返回相对中心的偏移)。

    顶点数固定为 n 便于跨形状插值: 圆用 n 等分; 多边形按角数等分 + 顶点对齐;
    星形用内外交替半径。全部相对中心 (0,0), 无绝对坐标。
    """
    import math as _m

    name = (name or "circle").lower()
    verts: List[Tuple[float, float]] = []
    if name == "square":
        # 4 角: 对角对齐 → 按 n 个采样取多边形边界近似 (简单法: 用 4 个主方向角)
        corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
        for i in range(n):
            # 均匀采样边: 4 段, 每段 n/4 个点
            seg = int(n / 4)
            c = corners[i // seg] if seg else corners[i % 4]
            nxt = corners[(i // seg + 1) % 4] if seg else corners[(i + 1) % 4]
            frac = (i % seg) / max(1, seg) if seg else 0.0
            verts.append((size * (c[0] + (nxt[0] - c[0]) * frac),
                          size * (c[1] + (nxt[1] - c[1]) * frac)))
        return verts
    if name == "triangle":
        angs: List[float] = [90, 210, 330]
    elif name == "hex":
        angs = [0, 60, 120, 180, 240, 300]
    elif name == "star":
        # 10 顶点: 内外交替
        for i in range(n):
            ang = 360.0 * i / n
            rad = size if (i % 2 == 0) else size * 0.45
            verts.append((rad * _m.cos(_m.radians(ang)),
                          rad * _m.sin(_m.radians(ang))))
        return verts
    elif name == "circle":
        angs = [360.0 * i / n for i in range(n)]
    else:
        angs = [360.0 * i / n for i in range(n)]
    for i in range(n):
        if name in ("triangle", "hex"):
            # 多边形: 顶点落在对应角, 其余点在边间 (插值到最近角之间的边)
            k = len(angs)
            segf = n / k
            idx = min(k - 1, int(i / segf))
            nxt_i = (idx + 1) % k
            frac = (i % segf) / max(1, segf)
            a0 = _m.radians(angs[idx])
            a1 = _m.radians(angs[nxt_i])
            ang = a0 + (a1 - a0) * frac
            verts.append((size * _m.cos(ang), size * _m.sin(ang)))
        else:
            ang = _m.radians(360.0 * i / n)
            verts.append((size * _m.cos(ang), size * _m.sin(ang)))
    return verts


def _render_camera_node(draw: Any, node: Dict[str, Any], t: float,
                        canvas_w: int, canvas_h: int) -> None:
    """渲染 ``camera`` 节点: 相机跟随 (平移/缩放/旋转取景框, 叠加目标指示)。

    对齐 givemotion "camera movement / follow" 卖点。绘制取景框 (viewport) 并
    用十字/圆点标出相机中心, 随 t 沿 ``path`` (点列表) 运动, 支持缩放。
    由于是纯函数单帧绘制, 相机框本身是**可视化叠加层** (真实变换由调用方
    在合成阶段应用); 此处提供清晰的取景指示。

    props:
      x1,y1 / x2,y2: 起点/终点 (默认对角线)
      t0 / t1: 运动起止时间比例 (默认 0→1, 相对节点寿命)
      zoom_start / zoom_end: 取景缩放 (默认 1→1.2)
      color: 取景框色 (默认强调蓝)
      show_target: 显示目标十字 (默认 True)
      ease: 缓动 (linear|easein|easeout|easeinout, 默认 easeinout)
    """
    props = node.get("props") or {}
    if not isinstance(props, dict):
        props = {}
    x1 = _num(props.get("x1"), 0.0)
    y1 = _num(props.get("y1"), 0.0)
    x2 = _num(props.get("x2"), canvas_w)
    y2 = _num(props.get("y2"), canvas_h)
    color = _hex_color(props.get("color"), _DEFAULT_ACCENT)
    show_target = bool(props.get("show_target", True))
    ease_name = str(props.get("ease") or "easeinout")
    node_start = _num(node.get("start"), 0.0)
    node_end = _num(node.get("end"), 1.0)
    fade = _fade_in(t, node_start, 0.2) * _fade_out(t, node_end, 0.2)
    if fade <= 0 or t < node_start or t > node_end:
        return
    span = max(0.001, node_end - node_start)
    raw = _clamp((t - node_start) / span)
    eased = _ease_kind(raw, ease_name)
    # 相机中心沿线段插值
    cx = x1 + (x2 - x1) * eased
    cy = y1 + (y2 - y1) * eased
    if fade < 1.0:
        color = _blend((0, 0, 0), color, fade)
    # 取景框: 以相机为中心, 随 zoom 缩放
    zoom_start = max(0.1, _num(props.get("zoom_start"), 1.0))
    zoom_end = max(0.1, _num(props.get("zoom_end"), 1.2))
    zoom = zoom_start + (zoom_end - zoom_start) * eased
    vw = canvas_w * 0.4 / zoom
    vh = canvas_h * 0.4 / zoom
    try:
        draw.rectangle([cx - vw, cy - vh, cx + vw, cy + vh],
                       outline=color, width=max(2, _int(props.get("stroke_w"), 2)))
    except Exception as exc:  # noqa: BLE001
        log.warning("_render_camera_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        pass
    if show_target:
        cross = max(4, int(vw * 0.1))
        try:
            draw.line([cx - cross, cy, cx + cross, cy], fill=color, width=2)
            draw.line([cx, cy - cross, cx, cy + cross], fill=color, width=2)
        except Exception as exc:  # noqa: BLE001
            log.warning("_render_camera_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass


def _ease_kind(t: float, name: str) -> float:
    """多种缓动 (0→1)。"""
    t = _clamp(t)
    n = (name or "linear").lower()
    if n == "easein":
        return t * t
    if n == "easeout":
        return 1 - (1 - t) * (1 - t)
    if n == "easeinout":
        return t * t * (3 - 2 * t)  # smoothstep
    return t


def _render_path_motion_node(draw: Any, node: Dict[str, Any], t: float,
                             canvas_w: int, canvas_h: int) -> None:
    """渲染 ``path_motion`` 节点: 物体沿路径运动 (贝塞尔/折线/圆/螺旋)。

    对齐 givemotion "path-based motion" 卖点。支持路径类型:
      line    直线 (x1,y1)→(x2,y2)
      poly    折线 (points 列表)
      bezier  三次贝塞尔 (p0,p1,p2,p3)
      circle  圆 (cx,cy,r)
      spiral  螺旋 (cx,cy,r0,r1,turns)
    物体在路径上随 ``speed`` 前进; 绘制位置 + 尾迹。

    props:
      path: 路径类型 (默认 line)
      points: 折线/贝塞尔控制点 (list of [x,y])
      x1,y1,x2,y2: line 端点 (默认画布对角)
      cx,cy,r / r0,r1,turns: 圆/螺旋参数
      speed: 前进速度 (默认 1.0, 完整路径往返)
      direction: "forward"|"reverse"|"pingpong" (默认 forward)
      color: 物体色 (默认强调蓝)
      trail: 尾迹长度 (0-1, 默认 0.15; 0=无)
      size: 物体半径 (默认 10)
    """
    props = node.get("props") or {}
    if not isinstance(props, dict):
        props = {}
    ptype = str(props.get("path") or "line")
    color = _hex_color(props.get("color"), _DEFAULT_ACCENT)
    speed = max(0.01, _num(props.get("speed"), 1.0))
    direction = str(props.get("direction") or "forward")
    trail = _clamp(_num(props.get("trail"), 0.15), 0.0, 1.0)
    size = max(1.0, _num(props.get("size"), 10.0))
    node_start = _num(node.get("start"), 0.0)
    node_end = _num(node.get("end"), 1.0)
    fade = _fade_in(t, node_start, 0.2) * _fade_out(t, node_end, 0.2)
    if fade <= 0 or t < node_start or t > node_end:
        return
    span = max(0.001, node_end - node_start)
    raw = _clamp((t - node_start) / span * speed) % 1.0
    if direction == "reverse":
        raw = 1.0 - raw
    elif direction == "pingpong":
        ph = (t - node_start) / span * speed
        raw = 1.0 - abs(1.0 - (ph % 2.0))  # 0..1 往返
    pos = _path_point(ptype, props, raw, canvas_w, canvas_h)
    if pos is None:
        return
    px, py = pos
    if fade < 1.0:
        color = _blend((0, 0, 0), color, fade)
    # 尾迹
    if trail > 0:
        steps = max(2, int(trail * 40))
        for s in range(1, steps + 1):
            back = _clamp(raw - (s / steps) * trail)
            bp = _path_point(ptype, props, back, canvas_w, canvas_h)
            if bp is None:
                continue
            alpha = fade * (1.0 - s / (steps + 1))
            bc = _blend((0, 0, 0), color, alpha)
            r = max(0.5, size * (1.0 - s / (steps + 1)))
            try:
                draw.ellipse([bp[0] - r, bp[1] - r, bp[0] + r, bp[1] + r], fill=bc)
            except Exception as exc:  # noqa: BLE001
                log.warning("_render_path_motion_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                pass
    try:
        draw.ellipse([px - size, py - size, px + size, py + size], fill=color)
    except Exception as exc:  # noqa: BLE001
        log.warning("_render_path_motion_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        pass


def _path_point(ptype: str, props: Dict[str, Any], t: float,
                canvas_w: int, canvas_h: int) -> Optional[Tuple[float, float]]:
    """按路径类型计算 t∈[0,1] 处的点坐标; 非法参数返回 None。"""
    import math as _m

    ptype = (ptype or "line").lower()
    if ptype == "line":
        x1 = _num(props.get("x1"), 0.0)
        y1 = _num(props.get("y1"), 0.0)
        x2 = _num(props.get("x2"), canvas_w)
        y2 = _num(props.get("y2"), canvas_h)
        return (x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
    if ptype == "poly":
        pts = props.get("points")
        if not isinstance(pts, list) or len(pts) < 2:
            return None
        n_seg = len(pts) - 1
        seg = min(n_seg - 1, int(t * n_seg))
        frac = t * n_seg - seg
        a = pts[seg]
        b = pts[seg + 1]
        if not (isinstance(a, (list, tuple)) and len(a) >= 2 and
                isinstance(b, (list, tuple)) and len(b) >= 2):
            return None
        return (_num(a[0], 0) + (_num(b[0], 0) - _num(a[0], 0)) * frac,
                _num(a[1], 0) + (_num(b[1], 0) - _num(a[1], 0)) * frac)
    if ptype == "bezier":
        pts = props.get("points")
        if not isinstance(pts, list) or len(pts) < 4:
            return None
        p = [(_num(q[0], 0), _num(q[1], 0)) if isinstance(q, (list, tuple)) and len(q) >= 2 else (0, 0)
             for q in pts[:4]]
        u = 1 - t
        x = (u ** 3 * p[0][0] + 3 * u * u * t * p[1][0]
             + 3 * u * t * t * p[2][0] + t ** 3 * p[3][0])
        y = (u ** 3 * p[0][1] + 3 * u * u * t * p[1][1]
             + 3 * u * t * t * p[2][1] + t ** 3 * p[3][1])
        return (x, y)
    if ptype == "circle":
        cx = _num(props.get("cx"), canvas_w * 0.5)
        cy = _num(props.get("cy"), canvas_h * 0.5)
        r = max(0.0, _num(props.get("r"), 100.0))
        ang = 2 * _m.pi * t - _m.pi / 2
        return (cx + r * _m.cos(ang), cy + r * _m.sin(ang))
    if ptype == "spiral":
        cx = _num(props.get("cx"), canvas_w * 0.5)
        cy = _num(props.get("cy"), canvas_h * 0.5)
        r0 = max(0.0, _num(props.get("r0"), 20.0))
        r1 = max(0.0, _num(props.get("r1"), 180.0))
        turns = max(0.1, _num(props.get("turns"), 2.0))
        ang = 2 * _m.pi * turns * t - _m.pi / 2
        r = r0 + (r1 - r0) * t
        return (cx + r * _m.cos(ang), cy + r * _m.sin(ang))
    return None


def _render_hand_drawn_node(draw: Any, node: Dict[str, Any], t: float,
                            canvas_w: int, canvas_h: int) -> None:
    """渲染 ``hand_drawn`` 节点: 手绘自绘 (笔画渐进显现 + 轻微抖动)。

    对齐 givemotion "hand-drawn / sketch reveal" 卖点。把折线/曲线路径按
    ``progress`` 截断显示 (draw line segment), 并加确定性抖动模拟手绘质感。

    props:
      points: 折线顶点 list (必填, >=2)
      color: 笔触色 (默认近白)
      width: 笔触宽 (默认 3)
      jitter: 抖动幅度 px (默认 1.5)
      speed: 绘制速度 (默认 1.0, 相对节点寿命)
      close: 闭合路径 (默认 False)
    """
    props = node.get("props") or {}
    if not isinstance(props, dict):
        props = {}
    pts = props.get("points")
    if not isinstance(pts, list) or len(pts) < 2:
        return
    pts = [(x, y) for x, y in
           ((_num(q[0], 0), _num(q[1], 0)) if isinstance(q, (list, tuple)) and len(q) >= 2
            else (0, 0) for q in pts)]
    color = _hex_color(props.get("color"), (235, 240, 246))
    width = max(1, _int(props.get("width"), 3))
    jitter = max(0.0, _num(props.get("jitter"), 1.5))
    speed = max(0.01, _num(props.get("speed"), 1.0))
    close = bool(props.get("close"))
    node_start = _num(node.get("start"), 0.0)
    node_end = _num(node.get("end"), 1.0)
    fade = _fade_in(t, node_start, 0.2) * _fade_out(t, node_end, 0.2)
    if fade <= 0 or t < node_start or t > node_end:
        return
    if close and len(pts) > 2:
        pts = pts + [pts[0]]
    span = max(0.001, node_end - node_start)
    progress = _ease(_clamp((t - node_start) / span * speed))
    total_len = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
                    for i in range(len(pts) - 1))
    if total_len <= 0:
        return
    # 确定性抖动 (基于顶点 index + t 帧, 保证 frame-stable)
    def _jit(i: int) -> Tuple[float, float]:
        if jitter <= 0:
            return 0.0, 0.0
        seed = (i * 2654435761 + int(t * 60) * 40503) & 0xFFFFFFFF
        return (jitter * (((seed % 100) / 100.0) - 0.5),
                jitter * ((((seed >> 8) % 100) / 100.0) - 0.5))

    acc = 0.0
    drawn = total_len * progress
    if fade < 1.0:
        color = _blend((0, 0, 0), color, fade)
    for i in range(len(pts) - 1):
        seg_len = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        if acc >= drawn:
            break
        seg_finish = min(1.0, max(0.0, (drawn - acc) / max(0.001, seg_len)))
        ex = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * seg_finish
        ey = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * seg_finish
        jx, jy = _jit(i)
        try:
            draw.line([pts[i][0] + jx, pts[i][1] + jy, ex + jx, ey + jy],
                      fill=color, width=width)
        except Exception as exc:  # noqa: BLE001
            log.warning("_render_hand_drawn_node(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass
        acc += seg_len


# 节点分发: type -> 渲染函数
_NODE_RENDERERS: Dict[str, Callable[[Any, Dict[str, Any], float, int, int], None]] = {
    "code": _render_code_node,
    "title": _render_title_node,
    "subtitle": _render_subtitle_node,
    "box": _render_box_node,
    "dataflow": _render_dataflow_node,
    "bg": _render_bg_node,
    # 阶段 3 高级动效原语
    "transition": _render_transition_node,
    "particles": _render_particles_node,
    "kinetic": _render_kinetic_node,
    "beat": _render_beat_node,
    # 阶段 8 givemotion 式动效补全
    "shape_morph": _render_shape_morph_node,
    "camera": _render_camera_node,
    "path_motion": _render_path_motion_node,
    "hand_drawn": _render_hand_drawn_node,
}


# ---------------------------------------------------------------------------
# 帧绘制 (纯函数)
# ---------------------------------------------------------------------------

def draw_frame(project_json: Dict[str, Any], t: float,
               profiler: Optional[Dict[str, Any]] = None) -> Any:
    """绘制时间 t 的单帧。**纯函数**: 只读 project_json + t, 无全局可变状态。

    先画背景 (首个 bg 节点, 否则深色默认), 再按列表顺序渲染所有
    ``start <= t <= end`` 的节点; 范围外的节点跳过, 未知类型跳过 (记录日志)。

    若提供 ``profiler`` dict, 会就地写入逐节点/整帧耗时 (毫秒):
    ``{"frame_ms": float, "nodes": {ntype: {"count", "total_ms", "max_ms"}}}``。
    未提供时行为与旧版完全一致 (零开销)。
    """
    from PIL import Image, ImageDraw

    frame_start = time.perf_counter()
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
            _render_with_profiler(profiler, "bg", _render_bg_node,
                                  draw, n, t, width, height)
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
                _render_with_profiler(profiler, ntype, renderer,
                                      draw, n, t, width, height)
            except Exception as exc:  # noqa: BLE001 - 单节点失败不影响整帧
                log.debug("draw_frame(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                continue
    if profiler is not None:
        profiler["frame_ms"] = round((time.perf_counter() - frame_start) * 1000, 3)
    return img


def _render_with_profiler(profiler: Optional[Dict[str, Any]], ntype: str,
                          renderer: Callable[..., Any], *args: Any) -> None:
    """调用单个节点渲染器; 若传了 profiler, 记录该节点耗时。"""
    start = time.perf_counter()
    renderer(*args)
    if profiler is not None:
        ms = (time.perf_counter() - start) * 1000
        slot = profiler.setdefault("nodes", {}).setdefault(
            ntype, {"count": 0, "total_ms": 0.0, "max_ms": 0.0})
        slot["count"] += 1
        slot["total_ms"] += ms
        if ms > slot["max_ms"]:
            slot["max_ms"] = ms


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
        stdout = proc.stdout
        out = ((stdout.read() if stdout is not None else b"") or b"").decode("utf-8", "replace")
        proc.wait()
    except OSError:
        return None
    for enc in _VIDEO_ENCODERS:
        if f" {enc}" in out or enc in out:
            return enc
    return None


def render_video(project_json: Dict[str, Any], out_path: str, *,
                 fps: int = 30, on_progress: Optional[Callable[[int, int], None]] = None,
                 profile: bool = False,
                 workspace: Optional[str] = None) -> Dict[str, Any]:
    """同步渲染视频 (Pillow 逐帧 + ffmpeg rawvideo 管道编码)。

    返回 ``{"out_path","frames","fps","elapsed","size_bytes"}``。
    ``profile=True`` 时额外返回 ``perf`` (逐节点耗时 + 帧时间序列,
    见 :func:`_profile_summary`)。ffmpeg 缺失时抛出 RuntimeError。
    ``workspace`` 用于 audio 轨道路径的边界校验 (审计 P2-31)。
    """
    err = validate_project(project_json)
    if err:
        raise ValueError(err)
    width = max(1, _int(project_json.get("width"), 1280))
    height = max(1, _int(project_json.get("height"), 720))
    duration = max(0.0, _num(project_json.get("duration"), 1.0))
    # 优先用 project_json.fps (validate 已保证 >0), 否则退到函数参数 fps。
    fps = max(1, _int(project_json.get("fps"), fps) or fps)
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
    frame_profiles: List[Dict[str, Any]] = []
    try:
        for i in range(total_frames):
            t = i / fps
            prof: Optional[Dict[str, Any]] = {} if profile else None
            frame = draw_frame(project_json, t, profiler=prof)
            if prof is not None:
                frame_profiles.append(prof)
            if proc.stdin is not None:
                proc.stdin.write(frame.tobytes())
            if on_progress and (i % max(1, total_frames // 10) == 0 or i == total_frames - 1):
                try:
                    on_progress(i + 1, total_frames)
                except Exception as exc:  # noqa: BLE001 - 回调异常忽略
                    log.warning("render_video(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                    pass
    except Exception:
        try:
            proc.kill()
        except Exception as exc:  # noqa: BLE001
            log.warning("render_video(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass
        raise
    finally:
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except Exception as exc:  # noqa: BLE001
                log.warning("render_video(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                pass
    stderr_b = b""
    if proc.stderr is not None:
        stderr_b = proc.stderr.read() or b""
    proc.wait()
    elapsed = time.time() - started
    if proc.returncode != 0:
        tail = stderr_b.decode("utf-8", errors="replace")[-_TAIL_BYTES:]
        raise RuntimeError(f"ffmpeg 编码失败 (exit={proc.returncode}): {tail}")
    # 阶段 9: cinecode 式音频混音 —— 混入音轨 (若 project_json 含 audio)
    audio_result = _mix_audio_tracks(ffmpeg, project_json, str(out), duration,
                                     workspace=workspace)
    size_bytes = out.stat().st_size if out.is_file() else 0
    result: Dict[str, Any] = {
        "out_path": str(out),
        "frames": total_frames,
        "fps": fps,
        "elapsed": round(elapsed, 3),
        "size_bytes": size_bytes,
        "audio": audio_result,
    }
    if profile:
        result["perf"] = _profile_summary(frame_profiles, total_frames)
    return result


def _profile_summary(frame_profiles: List[Dict[str, Any]],
                     total_frames: int) -> Dict[str, Any]:
    """把逐帧 profiler 聚合为性能摘要 (逐节点耗时 + 帧时间序列热力图)。"""
    agg: Dict[str, Dict[str, float]] = {}
    frame_ms: List[float] = []
    for prof in frame_profiles:
        fms = float(prof.get("frame_ms") or 0.0)
        frame_ms.append(fms)
        for ntype, slot in (prof.get("nodes") or {}).items():
            a = agg.setdefault(ntype, {"count": 0, "total_ms": 0.0, "max_ms": 0.0})
            a["count"] += int(slot.get("count") or 0)
            a["total_ms"] += float(slot.get("total_ms") or 0.0)
            a["max_ms"] = max(a["max_ms"], float(slot.get("max_ms") or 0.0))
    nodes = {}
    for ntype, a in agg.items():
        nodes[ntype] = {
            "count": a["count"],
            "total_ms": round(a["total_ms"], 3),
            "avg_ms": round(a["total_ms"] / max(1, a["count"]), 3),
            "max_ms": round(a["max_ms"], 3),
        }
    if frame_ms:
        worst = max(frame_ms)
        avg = sum(frame_ms) / len(frame_ms)
        p95 = sorted(frame_ms)[min(len(frame_ms) - 1, int(len(frame_ms) * 0.95))]
    else:
        worst = avg = p95 = 0.0
    return {
        "nodes": nodes,
        "frame_ms": {
            "avg": round(avg, 3),
            "p95": round(p95, 3),
            "max": round(worst, 3),
            "total": round(sum(frame_ms), 3),
        },
        "frame_series": [round(x, 3) for x in frame_ms],
        "frames": len(frame_ms),
        "total_frames": total_frames,
    }


def _mix_audio_tracks(ffmpeg: str, project_json: Dict[str, Any],
                      video_path: str, duration: float,
                      workspace: Optional[str] = None) -> Dict[str, Any]:
    """把 project_json 的 ``audio`` 音轨混入已编码视频 (cinecode 式)。

    audio 支持两种形态:
      * str:  单个音频文件路径 (起点 0, 音量 1.0)
      * list: [{"path", "start"?, "volume"?, "loop"?}, ...]

    用 ffmpeg 二次转码: 读视频 + N 条音频输入, amix 合并 (每条延迟 start,
    缩放 volume), 输出临时 mp4 后原子替换。任何一步失败都 fail-closed
    (抛 RuntimeError, 不产出无声假成功)。

    审计 P2-31: 音频路径必须 ``resolve`` 后落在 **workspace 内** —— 否则
    任意本地音频/媒体文件可被混进导出视频并经 /api/media 取回 (信息外带)。
    ``workspace`` 缺失时一律拒绝 (fail-closed)。

    返回 ``{"mixed": bool, "tracks": n, "audio_codec": ...}``; 无 audio 时返回
    ``{"mixed": False, "tracks": 0}``。
    """
    audio = project_json.get("audio")
    if audio is None:
        return {"mixed": False, "tracks": 0}
    if isinstance(audio, str):
        tracks = [{"path": audio, "start": 0.0, "volume": 1.0}]
    elif isinstance(audio, list):
        tracks = list(audio)
    else:
        raise RuntimeError("audio 字段类型非法 (fail-closed)")
    if not tracks:
        return {"mixed": False, "tracks": 0}
    root = Path(workspace).resolve() if workspace else None
    # 逐条解析
    resolved: List[Dict[str, Any]] = []
    for tr in tracks:
        if not isinstance(tr, dict):
            raise RuntimeError("audio 轨道必须是对象 (fail-closed)")
        ap = tr.get("path")
        if not isinstance(ap, str) or not ap.strip():
            raise RuntimeError("audio 轨道缺 path (fail-closed)")
        if root is None:
            raise RuntimeError("audio 轨道需要 workspace 边界 (fail-closed)")
        try:
            rp = Path(ap).resolve()
            rp.relative_to(root)
        except (ValueError, OSError):
            raise RuntimeError(f"audio 路径越界 (必须位于工作区内): {ap} (fail-closed)")
        if not rp.is_file():
            raise RuntimeError(f"audio 文件不存在: {ap} (fail-closed)")
        resolved.append({
            "path": str(rp),
            "start": max(0.0, _num(tr.get("start"), 0.0)),
            "volume": max(0.01, _num(tr.get("volume"), 1.0)),
            "loop": bool(tr.get("loop")),
        })
    tmp = video_path + ".audiotmp.mp4"
    argv = [ffmpeg, "-y", "-i", video_path]
    for rtr in resolved:
        argv += ["-i", rtr["path"]]
    n = len(resolved)
    # 每个音频输入: 循环→延迟→音量
    filters = []
    for i in range(n):
        rtr = resolved[i]
        pre = "aloop=loop=-1:size=2e9,atrim=duration=%.3f," % max(0.1, duration) if rtr["loop"] else ""
        filters.append(f"[{i+1}:a]{pre}adelay={int(rtr['start']*1000)}|{int(rtr['start']*1000)},"
                       f"volume={rtr['volume']:.4f}[a{i}]")
    # 合并
    amix_inputs = "".join(f"[a{i}]" for i in range(n))
    filters.append(f"{amix_inputs}amix=inputs={n}:duration=longest:dropout_transition=0"
                   f",aformat=sample_rates=44100:channel_layouts=stereo[aout]")
    argv += [
        "-filter_complex", ";".join(filters),
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        tmp,
    ]
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                shell=False)
        _, errb = proc.communicate(timeout=_RENDER_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError("音频混音超时 (fail-closed)")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"音频混音启动失败: {exc} (fail-closed)")
    if proc.returncode != 0:
        tail = errb.decode("utf-8", errors="replace")[-_TAIL_BYTES:]
        raise RuntimeError(f"音频混音失败 (exit={proc.returncode}): {tail}")
    try:
        Path(tmp).replace(video_path)
    except OSError as exc:
        raise RuntimeError(f"音频混音输出替换失败: {exc} (fail-closed)")
    return {"mixed": True, "tracks": n, "audio_codec": "aac"}


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
                     fps: int = 30, profile: bool = False,
                     workspace: Optional[str] = None) -> str:
    """后台渲染视频; 返回 job_id。``profile=True`` 时结果含 ``perf``。"""
    return _start_render_job(
        "render",
        lambda: render_video(project_json, out_path, fps=fps, profile=profile,
                             workspace=workspace))


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
