"""stdlib YAML 子集解析器 —— 零依赖替代 PyYAML。

为什么存在
----------
``PyYAML`` 是安装量最大、却被文档描述成「可选」的核心依赖: ``tuan_cli`` 里有 12 处
``import yaml``, 其中 11 处早已写成 try/except 降级, 只有 ``cli/cmd_tutorial.py`` 一处
模块级裸导入。也就是说, 文档说「可不装」, 实际上一不装 ``tuan tutorial`` 直接崩 —— 这正是
本次依赖治理要消灭的「声明可选、实际必需」问题。

本模块提供 PyYAML 常用 API 的子集:

- ``safe_load`` / ``load`` / ``safe_load_all``: 解析 YAML 文本
- ``safe_dump`` / ``dump``: 序列化 Python 对象为 YAML
- ``YAMLError`` / ``ScannerError``: 带行号的错误消息

支持范围 (覆盖本仓库全部 YAML 资源文件与配置文件)
--------------------------------------------------
块映射 / 块序列 / 序列内联映射 (``- key: value``) / literal block scalar
(``|`` ``|-`` ``|+``) / folded block scalar (``>`` ``>-`` ``>+``) / **多行普通标量**
(缩进续行, 教程 note 字段大量使用) / 流式列表 ``[a, b]`` / 流式映射 ``{a: b}`` /
单双引号标量与转义 / 类型推断 (int float bool null) / 注释 (整行与行尾) /
``---`` 与 ``...`` 文档边界。

不支持 (抛出带行号的 ``YAMLError``, 而不是静默解析错)
------------------------------------------------------
锚点与别名 (``&x`` / ``*x``)、标签 (``!!str``)、复杂键、跨行引用的深层嵌套流式结构。
这些都不是本项目 YAML 的用法; 抛出明确错误好过悄悄给错数据。

已知有意分歧: YAML 1.1 的六十进制整数 (``12:30:45`` -> 45045) 不实现 —— 那是 PyYAML
的一个反直觉行为, 没有真实配置依赖它, 解析成字符串更安全。

正确性策略: 本实现与已安装的 PyYAML 做过差分测试 (见 ``.scratch/test_yaml_shim.py``),
在仓库全部 YAML 文件上解析结果一致。PyYAML 仍可作为可选增强安装
(``pip install tuan-cli[yaml]``) —— 装了就自动用 PyYAML 的完整实现, 没装则用本模块。
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "YAMLError",
    "ScannerError",
    "safe_load",
    "load",
    "safe_load_all",
    "safe_dump",
    "dump",
]


class YAMLError(ValueError):
    """YAML 解析或序列化错误。消息里带行号, 便于直接定位。"""


class ScannerError(YAMLError):
    """扫描阶段错误 (缩进、不认识的构造)。"""


# --------------------------------------------------------------------------- #
# 标量识别表
# --------------------------------------------------------------------------- #
_TRUE = frozenset({"true", "True", "TRUE", "yes", "Yes", "YES", "on", "On", "ON"})
_FALSE = frozenset({"false", "False", "FALSE", "no", "No", "NO", "off", "Off", "OFF"})
_NULL = frozenset({"null", "Null", "NULL", "none", "None", "NONE", "~", ""})

# 整数: 十进制 (不含前导零), 十六进制, 八进制
_INT_RE = re.compile(r"^-?(?:0|[1-9]\d*)$")
_HEX_RE = re.compile(r"^0x[0-9a-fA-F]+$")
_OCT_RE = re.compile(r"^0o[0-7]+$")
# 浮点: 必须含小数点 (对齐 PyYAML 的 resolver —— 因此 "1e5" 是字符串而非 100000.0)
_FLOAT_RE = re.compile(r"^-?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?$")

_BLOCK_SCALAR_RE = re.compile(r"^([|>])([0-9]*)([+-]?)\s*(?:#.*)?$")

_DOUBLE_ESCAPES = {
    "0": "\0", "a": "\a", "b": "\b", "t": "\t", "n": "\n", "v": "\v", "f": "\f",
    "r": "\r", "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\",
    "N": "\u0085", "_": "\u00a0", "L": "\u2028", "P": "\u2029",
}


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def _indent_of(line: str) -> int:
    n = 0
    for ch in line:
        if ch == " ":
            n += 1
        elif ch == "\t":
            # YAML 明确禁止 tab 缩进 (PyYAML 同样报错); 静默折算会让结构悄悄错位
            raise ScannerError("YAML 不允许使用 tab 作为缩进, 请改用空格")
        else:
            break
    return n


def _is_blank(line: str) -> bool:
    return not line.strip()


def _is_comment_line(line: str) -> bool:
    s = line.lstrip(" ")
    return s.startswith("#")


def _is_noise(line: str) -> bool:
    return _is_blank(line) or _is_comment_line(line)


def _is_doc_boundary(line: str) -> bool:
    return line.strip() in ("---", "...")


def _split_trailing_comment(s: str) -> str:
    """去掉行尾注释 (引号内的 # 不算, 且 # 前必须是空白)。"""
    in_s = in_d = False
    for j, ch in enumerate(s):
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif not in_s and not in_d and ch == "#" and (j == 0 or s[j - 1] in " \t"):
            return s[:j].rstrip()
    return s


def _decode_double(body: str) -> str:
    out: List[str] = []
    i, n = 0, len(body)
    while i < n:
        ch = body[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        i += 1
        if i >= n:
            out.append("\\")
            break
        e = body[i]
        if e in _DOUBLE_ESCAPES:
            out.append(_DOUBLE_ESCAPES[e])
            i += 1
        elif e == "x" and i + 2 <= n:
            out.append(chr(int(body[i + 1:i + 3], 16)))
            i += 3
        elif e == "u" and i + 4 <= n:
            out.append(chr(int(body[i + 1:i + 5], 16)))
            i += 5
        elif e == "U" and i + 8 <= n:
            out.append(chr(int(body[i + 1:i + 9], 16)))
            i += 9
        else:
            out.append(e)
            i += 1
    return "".join(out)


def _unquote(s: str) -> Any:
    """解析单个标量 (含引号与类型推断)。"""
    s = s.strip()
    if not s:
        return None
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return _decode_double(s[1:-1])
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1].replace("''", "'")
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    if s in _NULL:
        return None
    if _INT_RE.match(s):
        return int(s)
    if _HEX_RE.match(s):
        return int(s, 16)
    if _OCT_RE.match(s):
        return int(s, 8)
    if s in ("nan", ".nan", "NaN"):
        return float("nan")
    if s in (".inf", "+.inf", "Inf", "Infinity"):
        return float("inf")
    if s in ("-.inf", "-.Inf", "-Infinity"):
        return float("-inf")
    if _FLOAT_RE.match(s):
        return float(s)
    return s


def _looks_like_mapping(s: str) -> bool:
    """``key: value`` / ``key:`` —— 冒号后必须是空白或行尾, 且在引号与括号外。"""
    in_s = in_d = False
    depth = 0
    for j, ch in enumerate(s):
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif in_s or in_d:
            continue
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == ":" and depth == 0:
            if j + 1 >= len(s) or s[j + 1] in " \t":
                return True
    return False


def _split_key(s: str) -> Tuple[Optional[str], Optional[str]]:
    """拆出 ``key, rest``; 冒号必须在引号外、括号外, 且后接空白或行尾。"""
    in_s = in_d = False
    depth = 0
    for j, ch in enumerate(s):
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif in_s or in_d:
            continue
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == ":" and depth == 0:
            if j + 1 >= len(s) or s[j + 1] in " \t":
                return _unquote(s[:j].strip()) or "", s[j + 1:].strip()
    return None, None


def _split_top(body: str, sep: str) -> List[str]:
    """按顶层 sep 切分, 忽略引号与括号内的 sep。"""
    parts: List[str] = []
    depth = 0
    in_s = in_d = False
    cur: List[str] = []
    for ch in body:
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        if not in_s and not in_d:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
            elif ch == sep and depth == 0:
                parts.append("".join(cur))
                cur = []
                continue
        cur.append(ch)
    parts.append("".join(cur))
    return [p for p in (x.strip() for x in parts) if p != ""]


def _parse_flow(s: str, line_no: int) -> Any:
    """解析 ``[a, b]`` / ``{a: b}`` 流式结构 (可跨层嵌套)。"""
    s = s.strip()
    if s.startswith("["):
        if not s.endswith("]"):
            raise ScannerError(f"第 {line_no} 行: 流式列表未闭合")
        body = s[1:-1].strip()
        if not body:
            return []
        return [_parse_flow(p, line_no) for p in _split_top(body, ",")]
    if s.startswith("{"):
        if not s.endswith("}"):
            raise ScannerError(f"第 {line_no} 行: 流式映射未闭合")
        body = s[1:-1].strip()
        if not body:
            return {}
        out: Dict[Any, Any] = {}
        for part in _split_top(body, ","):
            part = part.strip()
            if _looks_like_mapping(part):
                k, v = _split_key(part)
                out[k] = _parse_flow(v, line_no) if v else None
            else:
                out[_unquote(part)] = None
        return out
    return _unquote(s)


# --------------------------------------------------------------------------- #
# 块标量 (| 和 >)
# --------------------------------------------------------------------------- #
def _parse_block_scalar(
    lines: List[str],
    i: int,
    parent_indent: int,
    indicator: str,
    ends_nl: bool,
    line_no: int,
) -> Tuple[str, int]:
    m = _BLOCK_SCALAR_RE.match(indicator)
    if not m:
        raise ScannerError(f"第 {line_no} 行: 非法块标量指示符 {indicator!r}")
    style, explicit, chomp = m.group(1), m.group(2), m.group(3)
    n = len(lines)

    # 探测内容缩进: 显式指定优先, 否则取首个非空行的缩进
    content_indent: Optional[int] = int(explicit) + parent_indent if explicit else None
    j = i
    while j < n:
        if _is_blank(lines[j]):
            j += 1
            continue
        jind = _indent_of(lines[j])
        if jind <= parent_indent:
            break
        if content_indent is None:
            content_indent = jind
        break
    if content_indent is None:
        return ("" if chomp != "+" else "\n"), i

    body: List[str] = []
    while j < n:
        raw = lines[j]
        if _is_blank(raw):
            body.append("")
            j += 1
            continue
        jind = _indent_of(raw)
        if jind < content_indent:
            break
        body.append(raw[content_indent:] if jind >= content_indent else raw.strip())
        j += 1

    joined = "\n".join(body)
    trimmed = joined.rstrip("\n")
    # 块之后是否还有内容 —— 决定 clip/keep 能否保留结尾换行
    has_following = j < n
    terminated_by_newline = ends_nl or has_following

    if style == ">":  # folded: 相邻非空行折叠为空格, 空行折叠为换行
        text = _fold_lines(body)
        if chomp == "-":
            return text.rstrip("\n"), j
        return (text.rstrip("\n") + "\n") if terminated_by_newline else text.rstrip("\n"), j

    # literal: 原样保留行结构
    if chomp == "-":  # strip
        return trimmed, j
    if chomp == "+":  # keep
        return (joined + "\n") if terminated_by_newline else joined, j
    # clip: 至多保留一个结尾换行
    return (trimmed + "\n") if terminated_by_newline else trimmed, j


def _fold_lines(body: List[str]) -> str:
    """折叠块: 相邻非空行用空格连接, 空行折叠为单个换行。"""
    out: List[str] = []
    pending_nl = False
    for line in body:
        if line.strip() == "":
            pending_nl = True
            continue
        if pending_nl:
            if out:
                out.append("\n")
            pending_nl = False
        elif out:
            out.append(" ")
        out.append(line.strip())
    return "".join(out)


# --------------------------------------------------------------------------- #
# 多行普通标量 (缩进续行, 教程 note/narrative 大量使用)
# --------------------------------------------------------------------------- #
def _parse_plain_value(
    lines: List[str],
    i: int,
    key_indent: int,
    first: str,
) -> Tuple[Any, int]:
    """解析普通标量, 并折叠缩进更深的续行。

    折叠规则 (对齐 YAML 块上下文的 plain 标量):
    - 相邻非空行用单个空格连接
    - 空行折叠为单个换行
    - 续行缩进必须严格大于所属 key 的缩进, 否则视为新节点
    - 结尾不追加换行 (PyYAML 行为: 普通标量不携带文档结尾换行)
    """
    n = len(lines)
    parts: List[str] = [first.strip()]
    while i < n:
        raw = lines[i]
        if _is_blank(raw):
            parts.append("")
            i += 1
            continue
        ind = _indent_of(raw)
        if ind <= key_indent:
            break
        cont = raw.strip()
        if cont.startswith("- "):
            # "key: value" 下面跟更深的序列项 —— 非法结构, 报错而不是猜
            raise ScannerError(f"第 {i + 1} 行: 普通标量后出现更深层的序列项, 缩进结构非法")
        parts.append(cont)
        i += 1

    # 折叠
    out: List[str] = []
    pending_newline = False
    for p in parts:
        if p == "":
            pending_newline = True
            continue
        if pending_newline:
            if out:
                out.append("\n")
            pending_newline = False
        elif out:
            out.append(" ")
        out.append(p)
    text = "".join(out).rstrip("\n")
    return (_unquote(text) if "\n" not in text else text), i


# --------------------------------------------------------------------------- #
# 块结构解析
# --------------------------------------------------------------------------- #
def _parse_node(
    lines: List[str],
    i: int,
    min_indent: int,
    ends_nl: bool,
) -> Tuple[Any, int]:
    n = len(lines)
    while i < n and _is_noise(lines[i]):
        i += 1
    if i >= n:
        return None, i
    ind = _indent_of(lines[i])
    if ind < min_indent or _is_doc_boundary(lines[i]):
        return None, i
    s = _split_trailing_comment(lines[i][ind:])
    if s.startswith("- ") or s == "-":
        return _parse_seq(lines, i, ind, ends_nl)
    if s[0] in "[{":
        return _parse_flow(s, i + 1), i + 1
    if _looks_like_mapping(s):
        return _parse_map(lines, i, ind, ends_nl, first=None)
    val, nxt = _parse_plain_value(lines, i + 1, ind, s)
    return val, nxt


def _parse_seq(
    lines: List[str], i: int, indent: int, ends_nl: bool
) -> Tuple[List[Any], int]:
    items: List[Any] = []
    n = len(lines)
    while i < n:
        if _is_noise(lines[i]):
            i += 1
            continue
        if _is_doc_boundary(lines[i]):
            break
        ind = _indent_of(lines[i])
        if ind < indent:
            break
        if ind > indent:
            raise ScannerError(f"第 {i + 1} 行: 序列缩进不一致")
        s = _split_trailing_comment(lines[i][ind:])
        if not (s.startswith("- ") or s == "-"):
            break
        if s == "-":
            val, i = _parse_node(lines, i + 1, indent + 1, ends_nl)
            items.append(val)
            continue
        content = _split_trailing_comment(s[2:])
        vindent = ind + 2
        if _looks_like_mapping(content):
            val, i = _parse_map(lines, i + 1, vindent, ends_nl, first=content)
            items.append(val)
        else:
            val, nxt = _parse_plain_value(lines, i + 1, ind, content)
            items.append(val)
            i = nxt
    return items, i


def _parse_map(
    lines: List[str],
    i: int,
    indent: int,
    ends_nl: bool,
    first: Optional[str],
) -> Tuple[Dict[Any, Any], int]:
    """解析映射。``first`` 非空时表示首行已由调用方抽出 (用于 ``- key: value``)。"""
    out: Dict[Any, Any] = {}
    n = len(lines)

    def _take(k: Any, val: Any, nxt: int) -> int:
        out[k] = val
        return nxt

    if first is not None:
        s = _split_trailing_comment(first)
        k, rest = _split_key(s)
        if k is None:
            raise ScannerError(f"第 {i} 行: 期望 'key: value', 实际 {first[:40]!r}")
        key = _unquote(k)
        if rest:
            i = _assign_value(out, key, rest, lines, i, indent, ends_nl)
        else:
            val, i = _parse_node(lines, i, indent + 1, ends_nl)
            out[key] = val
        return _continue_map(out, lines, i, indent, ends_nl)

    return _continue_map(out, lines, i, indent, ends_nl)


def _continue_map(
    out: Dict[Any, Any],
    lines: List[str],
    i: int,
    indent: int,
    ends_nl: bool,
) -> Tuple[Dict[Any, Any], int]:
    n = len(lines)
    while i < n:
        if _is_noise(lines[i]):
            i += 1
            continue
        if _is_doc_boundary(lines[i]):
            break
        ind = _indent_of(lines[i])
        if ind < indent:
            break
        if ind > indent:
            raise ScannerError(f"第 {i + 1} 行: 映射缩进不一致")
        s = _split_trailing_comment(lines[i][ind:])
        if s.startswith("- ") or s == "-":
            break
        k, rest = _split_key(s)
        if k is None:
            raise ScannerError(f"第 {i + 1} 行: 期望 'key: value', 实际 {s[:40]!r}")
        key = _unquote(k)
        if not rest:
            val, i = _parse_node(lines, i + 1, indent + 1, ends_nl)
            out[key] = val
            continue
        i = _assign_value(out, key, rest.strip(), lines, i + 1, ind, ends_nl)
    return out, i


def _assign_value(
    out: Dict[Any, Any],
    key: Any,
    rest: str,
    lines: List[str],
    i: int,
    key_indent: int,
    ends_nl: bool,
) -> int:
    """把一个已抽出的 value 表达式写入 out[key], 返回下一个行号。"""
    line_no = i
    m = _BLOCK_SCALAR_RE.match(rest)
    if m:
        val, i = _parse_block_scalar(lines, i, key_indent, rest, ends_nl, line_no)
        out[key] = val
        return i
    if rest[0] in "&*!":
        raise ScannerError(
            f"第 {line_no} 行: 本实现不支持该 YAML 构造 {rest[:20]!r} "
            f"(锚点/别名/标签请使用 PyYAML: pip install tuan-cli[yaml])"
        )
    if rest[0] in "[{":
        out[key] = _parse_flow(rest, line_no)
        return i
    if _looks_like_mapping(rest):
        # "a: b: c" 这类未缩进的嵌套映射是非法 YAML
        raise ScannerError(
            f"第 {line_no} 行: 普通标量中不允许出现 'key: value' 结构 ({rest[:30]!r}), "
            f"请缩进或加引号"
        )
    val, i = _parse_plain_value(lines, i, key_indent, rest)
    out[key] = val
    return i


# --------------------------------------------------------------------------- #
# 公共解析 API
# --------------------------------------------------------------------------- #
def _impl_safe_load(text: Any, *, Loader: Any = None) -> Any:
    """解析 YAML 文本, 返回 Python 对象。空文本返回 None。

    私有实现名, 不会被模块末尾的后端选择逻辑重绑定 —— ``load`` / ``safe_load_all``
    等调用它才能稳定走 stdlib 内核 (否则闭包会拿到被替换成 PyYAML 的版本)。
    """
    if text is None:
        return None
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    raw = text.replace("\r\n", "\n").replace("\r", "\n")
    if raw.startswith("\ufeff"):
        raw = raw[1:]
    if not raw.strip():
        return None
    ends_nl = raw.endswith("\n")
    lines = raw.split("\n")
    if ends_nl:
        lines = lines[:-1]  # 丢弃 split 产生的幻影空行
    i = 0
    n = len(lines)
    while i < n and lines[i].strip() in ("---",):
        i += 1
    value, _ = _parse_node(lines, i, 0, ends_nl)
    return value


def safe_load(text: Any, *, Loader: Any = None) -> Any:
    """解析 YAML 文本 (公共入口, 可能被后端选择逻辑替换为 PyYAML 实现)。"""
    return _impl_safe_load(text, Loader=Loader)


def load(text: Any, Loader: Any = None) -> Any:  # noqa: A002 - 对齐 PyYAML 签名
    return _impl_safe_load(text, Loader=Loader)


def safe_load_all(text: Any) -> List[Any]:
    """多文档解析。本实现只返回第一个文档, 多文档请使用 PyYAML。"""
    return [_impl_safe_load(text)]


# --------------------------------------------------------------------------- #
# 序列化
# --------------------------------------------------------------------------- #
def _quote_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float):
        if math.isnan(value):
            return ".nan"
        if math.isinf(value):
            return ".inf" if value > 0 else "-.inf"
        return repr(value)
    if isinstance(value, int):
        return str(value)
    s = str(value)
    if "\n" in s or "\t" in s:
        body = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
        return f'"{body}"'
    if s == "" or s != s.strip() or s in {"~", "null", "true", "false", "on", "off", "yes", "no"}:
        body = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{body}"'
    if _unquote(s) != s or _looks_like_mapping(s) or s[0] in "#[]{}&*!|>'\"":
        body = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{body}"'
    return s


def _dump_node(value: Any, indent: int, out: List[str]) -> None:
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            out.append(pad + "{}")
            return
        for k, v in value.items():
            key_s = _quote_scalar(k)
            if isinstance(v, dict) and v:
                out.append(f"{pad}{key_s}:")
                _dump_node(v, indent + 2, out)
            elif isinstance(v, (list, tuple)) and v:
                out.append(f"{pad}{key_s}:")
                _dump_node(list(v), indent + 2, out)
            elif isinstance(v, (dict, list, tuple)):
                out.append(f"{pad}{key_s}: " + ("{}" if isinstance(v, dict) else "[]"))
            else:
                out.append(f"{pad}{key_s}: {_quote_scalar(v)}")
    elif isinstance(value, (list, tuple)):
        if not value:
            out.append(pad + "[]")
            return
        for item in value:
            if isinstance(item, dict) and item:
                sub: List[str] = []
                _dump_node(item, indent + 2, sub)
                if sub:
                    out.append(f"{pad}- {sub[0][indent + 2:]}")
                    out.extend(sub[1:])
                else:
                    out.append(pad + "- {}")
            elif isinstance(item, (list, tuple)) and item:
                sub = []
                _dump_node(list(item), indent + 2, sub)
                out.append(f"{pad}- {sub[0][indent + 2:]}")
                out.extend(sub[1:])
            elif isinstance(item, (dict, list, tuple)):
                out.append(pad + "- " + ("{}" if isinstance(item, dict) else "[]"))
            else:
                out.append(f"{pad}- {_quote_scalar(item)}")
    else:
        out.append(pad + _quote_scalar(value))


def _impl_safe_dump(
    data: Any,
    stream: Any = None,
    *,
    indent: int = 2,
    allow_unicode: bool = True,
    sort_keys: bool = False,
    default_flow_style: bool = False,
    Dumper: Any = None,
    **_: Any,
) -> Optional[str]:
    """序列化 Python 对象为 YAML (私有实现名, 不被后端选择逻辑重绑定)。

    ``stream`` 为文件对象时写入并返回 None。
    """
    obj = data
    if sort_keys and isinstance(obj, dict):
        obj = {k: obj[k] for k in sorted(obj)}
    out: List[str] = []
    _dump_node(obj, 0, out)
    text = "\n".join(out) + "\n"
    if stream is not None:
        stream.write(text)
        return None
    return text


def safe_dump(data: Any, stream: Any = None, **kw: Any) -> Optional[str]:
    """序列化 Python 对象为 YAML (公共入口, 可能被后端选择逻辑替换)。"""
    return _impl_safe_dump(data, stream, **kw)


def dump(data: Any, stream: Any = None, Dumper: Any = None, **kw: Any) -> Optional[str]:  # noqa: A002
    return _impl_safe_dump(data, stream, Dumper=Dumper, **kw)


# --------------------------------------------------------------------------- #
# 后端选择: 有 PyYAML 就用 PyYAML (完整规范, 零回归), 否则用上面的 stdlib 实现。
# 这让 PyYAML 真正变成可选依赖 —— 装了是增强, 没装功能依然完整。
# `_stdlib_safe_load` / `_stdlib_safe_dump` 保留 stdlib 内核引用, 供差分测试使用。
# --------------------------------------------------------------------------- #
_stdlib_safe_load = _impl_safe_load
_stdlib_load = load
_stdlib_safe_dump = _impl_safe_dump
_stdlib_dump = dump
_stdlib_YAMLError = YAMLError
_stdlib_ScannerError = ScannerError

try:
    import yaml as _pyyaml  # type: ignore[import-not-found]

    _BACKEND = "pyyaml"
    safe_load = _pyyaml.safe_load  # type: ignore[assignment]
    load = _pyyaml.load  # type: ignore[assignment]
    safe_load_all = _pyyaml.safe_load_all  # type: ignore[assignment]
    safe_dump = _pyyaml.safe_dump  # type: ignore[assignment]
    dump = _pyyaml.dump  # type: ignore[assignment]
    YAMLError = _pyyaml.YAMLError  # type: ignore[misc,assignment]
    try:
        from yaml.scanner import ScannerError as _PYScannerError

        ScannerError = _PYScannerError  # type: ignore[misc,assignment]
    except ImportError:  # pragma: no cover - PyYAML 版本差异
        ScannerError = YAMLError  # type: ignore[misc,assignment]
except ImportError:  # pragma: no cover - 取决于运行环境
    _BACKEND = "stdlib"
