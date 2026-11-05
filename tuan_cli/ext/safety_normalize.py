"""命令文本归一化与混淆还原 (safety_engine 拆分模块)。

负责把命令文本剥壳/解码/展开为「可静态分析」的形式: sh -c / eval / sudo / xargs / find -exec
等执行间接层、PowerShell -EncodedCommand、ANSI-C 转义、嵌套命令替换、全角/组合 Unicode、
变量拼接、glob 与 symlink 展开。本模块只依赖标准库, 不做任何危险判定。
"""
import base64
import os
import re
import shlex
import unicodedata
from typing import Any, Iterator, List

# ------------------------------------------------------------ 致命红线判定 (token 化)
# 正则容易被旗标顺序/写法变体绕过 (rm -r -f / git push -f / del /s /q),
# 这里用分词 + 旗标归一的方式判定, 供引擎与各工具共用。

def _segments(text: str) -> list[str]:
    """按命令分隔符切段 (; && || | 及换行), 每段独立分析。"""
    return [s for s in re.split(r"&&|\|\||[;|&\n]", text) if s.strip()]


def _strip_sudo(parts: list[str]) -> list[str]:
    while parts and _cmd_name(parts[0]) in ("sudo", "doas", "pkexec", "su"):
        # su 带 -c/-l/- 等旗标时, 后面的用户/旗标一并吞掉
        if _cmd_name(parts[0]) == "su" and len(parts) > 1 and not parts[1].startswith("-"):
            parts = parts[2:] if len(parts) > 2 else parts[1:]
        else:
            parts = parts[1:]
        while parts and parts[0].startswith("-"):
            parts = parts[1:]
    return parts


# 危险命令名集合: 用于检测 echo/cat/sed 等 "透传" 命令后面的危险参数
_DANGEROUS_CMDS_IN_ARGS = frozenset({
    'rm', 'del', 'rmdir', 'erase', 'format', 'mkfs', 'dd',
    'wipefs', 'shred', 'shutdown', 'reboot', 'halt', 'poweroff',
    'drop', 'delete', 'truncate', 'alter',
})


def _cmd_name(tok: str) -> str:
    """把命令 token 规范化为命令名, 对抗路径 / 引号 / 转义 / 大小写混淆。

    覆盖: ``/bin/rm`` · ``/usr/bin/rm`` · ``./rm`` · ``../bin/rm`` · ``\\rm``
    (绕过 alias) · ``'rm'`` · ``"rm"`` · ``rm''`` · ``r''m`` · ``rm.exe`` · ``RM``。

    旧实现直接做 ``parts[0] != "rm"`` 严格等值比较, 上述所有变体一律漏判 ——
    这是本项目最严重的一类绕过 (绝对路径写法即可击穿硬红线)。
    """
    s = tok
    prev = None
    while s != prev:                       # 逐层剥掉包裹引号 ('rm' / "rm")
        prev = s
        s = s.strip("'\"")
    # 平台转义字符剥离: cmd.exe 用 ^ 转义 (r^m → rm), PowerShell 用 ` 转义
    # (r`m → rm)。两者都让命令名 token 在文本层面与真实命令名不同, 但实际执行的是
    # 被转义还原后的命令。必须在取 basename / 小写化之前剥掉, 否则 is_hard_redline
    # 看到的是 r^m / r`m, 漏判 Windows 上的毁灭命令。
    s = s.replace("^", "").replace("`", "")
    s = _unicode_clean(s)                  # echo\u200b → echo (零宽/变体/控制符, 防提及豁免失效)
    # 西里尔之外的同形字: 希腊 (ρ→r / ο→o / е→e / с→c / х→x / у→y / α→a / κ→k 等),
    # 亚美尼亚 (հ→h 等) 及零散全/半角混淆。攻击者可用同形字母造一个可执行文件名
    # (如 ρm, 内含 shebang) 绕过 ASCII 精确比较。先做同形字归一, 再继续常规剥离。
    s = _HOMOGLYPH_MAP_TRANSLATE(s)
    # 剥掉 token 内部的引号: 对抗 `r'm'` / `r"m"` / `r''m''` 等把命令名
    # 拆成「字母 + 引号拼接」的写法 (旧实现只剥外层, 残留内部引号导致 r'm ≠ rm)。
    s = s.replace("'", "").replace('"', "")
    s = s.replace("\\", "")                # \rm: 反斜杠绕过 alias
    s = s.replace("''", "").replace('""', "")   # r''m / rm'': 空引号拼接
    s = s.replace("\\", "/")
    s = s.rsplit("/", 1)[-1]               # 取 basename
    low = s.lower()
    for suf in (".exe", ".bat", ".cmd", ".com", ".ps1"):
        if low.endswith(suf):
            s = s[: -len(suf)]
            break
    return s.lower()


# 报告 P1-1: 命令名含 glob 通配符 (/bin/r? / /bin/{r,c}m) 时, 命令名不出现在 token 里,
# 引擎无法静态识别。这里用 fnmatch 把通配命令名与已知危险命令名集合做匹配,
# 命中则返回该危险命令名 (供 token 化判定把 `/bin/r?` 当 `rm` 处理)。
# 平台无关: 不依赖真实文件系统 (Windows 无 /bin/rm, 但安全引擎必须保守)。
_GLOB_CMD_MATCH_RE = re.compile(r'[*?[{]')
_DANGEROUS_GLOB_CMDS = frozenset({
    'rm', 'chmod', 'chown', 'userdel', 'wipefs', 'shred', 'blkdiscard',
    'lvremove', 'vgremove', 'pvremove', 'sgdisk', 'parted', 'dd', 'mkfs',
    'format', 'shutdown', 'reboot', 'halt', 'poweroff',
    'su', 'passwd', 'umount', 'mount', 'mv', 'setuid', 'setcap',
    'chage', 'usermod', 'groupmod', 'groupadd', 'useradd', 'pkill',
    'kill', 'killall', 'systemctl', 'iptables', 'swapoff', 'ln', 'truncate',
})


def _glob_command_name(tok: str) -> str | None:
    """若命令名 token 含 glob 通配符且能匹配已知危险命令, 返回规范化命令名。

    例: ``/bin/r?`` → ``rm``; ``/bin/{r,c}m`` 已由 brace 展开预处理, 若残留
    ``{r,c}m`` 形态则在此展开; ``/bin/p?*`` → ``pkill``。
    无法匹配任何危险命令 (如 ``/bin/ls?`` → 无) 返回 None, 保留原文走常规判定。
    """
    bare = tok.strip("'\"")
    base = bare.rsplit("/", 1)[-1]
    if not _GLOB_CMD_MATCH_RE.search(base):
        return None
    import fnmatch
    # brace 残留: {r,c}m → r m (逗号平面列表), 再逐项匹配
    candidates = [base]
    if '{' in base:
        def _flat(s: str) -> list[str]:
            m = re.fullmatch(r'([^{}]*)\{([^{}]+)\}([^{}]*)', s)
            if not m:
                return [s]
            out = []
            for part in m.group(2).split(','):
                out.extend(_flat(m.group(1) + part + m.group(3)))
            return out
        candidates = _flat(base)
    for cand in candidates:
        low = cand.lower()
        # 模式必须含至少一个「具体锚定字符」(非通配/非空), 否则 `*`/`?` 这类纯泛化
        # 模式会匹配一切危险命令名 (如路径参数 `node_modules/*` 的 basename 是 `*`,
        # fnmatch 恒真, 会把任意参数误映射成危险命令 → 硬红线误判)。无锚定的纯通配
        # 模式无法确定映射到「一个」危险命令, 应返回 None 保留原文走常规判定。
        if not re.search(r"[A-Za-z0-9_]", low):
            continue
        # low 作为 glob 模式去匹配危险命令名: r? 匹配 rm / p?* 匹配 pkill。
        # 反方向 (dname 匹配 low) 只用于 low 本身是字面名 (无通配) 的精确相等,
        # 且要求模式不含通配才成立 —— 否则 `*` 会匹配一切造成全面误杀。
        for dname in _DANGEROUS_GLOB_CMDS:
            if fnmatch.fnmatchcase(dname, low):
                return dname
    return None


def _cmd_name_glob(tok: str) -> str:
    """命令名规范化 + glob 通配命令名识别 (报告 P1-1)。

    ``/bin/r?`` / ``/bin/p?*`` / ``/bin/{r,c}m`` 等命令名被通配符/花括号隐藏时,
    静态识别出真实危险命令名, 供 token 化判定把通配命令当具名命令处理。
    非通配命令名退化为 _cmd_name 原逻辑, 零性能损失。
    """
    g = _glob_command_name(tok)
    if g is not None:
        return g
    return _cmd_name(tok)


def _detect_passthrough_danger(args: list[str]) -> bool:
    """检测 echo/cat/sed 等 "透传" 命令后面的参数是否含危险命令。

    对抗: $(echo rm) -rf / → 内联后为 echo rm -rf /
    此时 _cmd_name 看到 echo, 但 rm 在参数中。
    """
    if not args:
        return False
    for arg in args:
        cleaned = _cmd_name(arg)
        if cleaned in _DANGEROUS_CMDS_IN_ARGS:
            return True
    return False


def _unescape_win(text: str) -> str:
    """剥掉 Windows 平台转义字符 (cmd.exe 的 ``^``、PowerShell 的 `````), 供判定使用。

    ``cmd /c d^d ...`` / ``powershell -c d`d ...`` 里的 ``^`` / ```` ``` `` 是平台转义符,
    实际执行的是被还原后的命令 (``dd`` / ``format``)。shell 侧 ``^`` / ```` ``` `` 是字面量 /
    命令替换, 不受影响 —— 因此本函数**只产出额外扫描段**, 不替换原始文本, 保证不误伤
    ``grep '^foo'`` / ``echo `n`` 这类良性写法。

    引号区间 (单/双引号) 内的 ``^`` / ```` ``` `` 在两个平台里都失去转义语义, 一并跳过。
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            while i < n:
                if text[i] == "\\" and quote == '"':
                    out.append(text[i:i + 2])
                    i += 2
                    continue
                out.append(text[i])
                if text[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if ch in ("^", "`"):
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _scan_variants(text: str) -> Iterator[str]:
    """产出待扫描的命令段: **原始文本 + 归一化文本** 的并集。

    fail-closed 原则: 归一化链路 (符号链接解析 / glob 展开 / 变量内联 /
    解释器剥壳) 依赖真实文件系统与当前工作目录, 存在把危险结构抹掉的可能
    —— 例如 ``os.path.realpath('/')`` 在 Windows 上返回 ``E:\\``, 且换行
    分隔符曾在 join 过程中丢失。若只扫描归一化结果, 这类变形就会变成漏判。

    因此原始与归一化两者都扫: **归一化只能增加命中, 绝不能减少命中。**
    """
    seen = set()
    for src in (text, _unescape_win(text), _normalize(text)):
        # 报告 P2: 原始文本也可能带整行注释 (`# 谨慎: rm -rf /`), 先剥注释再分段。
        src = _strip_shell_comments(src)
        try:
            segs = _segments(src)
        except Exception:  # noqa: BLE001 - 归一化异常时至少保住原始文本
            segs = _segments(text)
        for seg in segs:
            if seg not in seen:
                seen.add(seg)
                yield seg


# 前缀变量赋值 (NAME=value, 值可为带引号串), 仅在文本开头或分隔符后识别,
# 避免误收 `echo foo=bar` / `--opt=val` 这类普通参数。
_VAR_DEF_RE = re.compile(
    r"(?:^|[;|&\n])\s*([A-Za-z_]\w*)=(\"[^\"]*\"|'[^']*'|[^\s;&|]*)")

# 数组赋值收集: a=(rm) / cmd=(r m) 等。必须在普通 _VAR_DEF_RE 之前处理, 否则
# `cmd=(r` 会被值捕获截断 (值部分遇空格即停), 残留 ` m)` 破坏后续 token。
_ARRAY_ASSIGN_RE = re.compile(
    r"(?:^|[;|&\n])\s*([A-Za-z_]\w*)=\(\s*([^)]*?)\s*\)")


def _expand_param_ops(text: str, env: dict[str, str],
                      arrays: dict[str, list[str]]) -> str:
    """静态求值 Bash 参数展开 (报告 P0-1 系统性盲区)。

    覆盖:
      ${var:off:len}     切片      x=_rm_; ${x:1:2}  → rm
      ${var#pat}         前缀剥离  x=xxrm; ${x#xx}   → rm
      ${var%pat}         后缀剥离  x=rmxx; ${x%xx}   → rm
      ${var/pat/repl}    替换      x=zm; ${x/z/r}    → rm
      ${var:-default}    默认值    ${CMD:-rm}        → rm
      ${!var}            间接展开  v=C; C=rm; ${!v}  → rm
      ${arr[i]}          数组索引  a=(rm); ${a[0]}   → rm
      ${arr[*]}          数组+IFS cmd=(r m); IFS=; ${cmd[*]} → rm

    无法静态求值 (变量未定义 / 模式含未定义变量 / 含通配符模式) 时保留原文,
    由 _has_unresolved_dangerous_substitution 做 fail-closed 兜底判定。
    """
    _PARAM_OP_RE = re.compile(r"\$\{([^{}]*)\}")

    def _eval_one(expr: str) -> Any:
        expr = expr.strip()
        if not expr:
            return None
        # 1) 间接展开 ${!var}: 取 var 的值作为变量名, 再取值
        if expr.startswith("!"):
            name = expr[1:].strip()
            inner = env.get(name)
            if inner is None:
                return None
            return env.get(inner)
        # 2) 默认值 ${var:-def} / ${var-def} / ${var:=def} / ${var:+alt}
        m = re.fullmatch(r"([A-Za-z_]\w*):?(-|:=|\+)(.*)", expr, re.S)
        if m:
            name, op, val = m.group(1), m.group(2), m.group(3)
            has = name in env and env.get(name) != ""
            if op == "+":          # ${var:+alt}: 已设置非空 → alt, 否则空
                return val if has else ""
            if has:                # ${var:-def}: 已设置非空 → 原值
                return env[name]
            if op == ":=":         # ${var:=def}: 未设置则赋值并返回 def
                env[name] = val
                return val
            return val if op in ("-", ":-") else ""
        # 3) 切片 ${var:off:len} / ${var:off}
        m = re.fullmatch(r"([A-Za-z_]\w*):(-?\d+)(?::(-?\d+))?", expr)
        if m:
            name, off = m.group(1), int(m.group(2))
            s = env.get(name)
            if s is None:
                return None
            if m.group(3) is None:
                return s[off:]
            return s[off:off + int(m.group(3))]
        # 4) 替换 ${var/pat/repl} / ${var//pat/repl} / ${var/#pat/repl} / ${var/%pat/repl}
        m = re.fullmatch(r"([A-Za-z_]\w*)(//|/#|/%|/)(.+)", expr, re.S)
        if m:
            name, op, rest = m.group(1), m.group(2), m.group(3)
            s = env.get(name)
            if s is None:
                return None
            pat, _, repl = rest.partition("/")
            if op == "/":
                return s.replace(pat, repl, 1)
            if op == "//":
                return s.replace(pat, repl)
            if op == "/#":
                return repl + s[len(pat):] if s.startswith(pat) else s
            if op == "/%":
                return s[: -len(pat)] + repl if s.endswith(pat) else s
        # 5) 前缀/后缀剥离 ${var#pat} / ${var##pat} / ${var%pat} / ${var%%pat}
        m = re.fullmatch(r"([A-Za-z_]\w*)(##|%%|#|%)(.+)", expr, re.S)
        if m:
            name, op, pat = m.group(1), m.group(2), m.group(3)
            s = env.get(name)
            if s is None:
                return None
            if op in ("#", "##"):   # 前缀剥离 (字面模式; 通配模式无法静态求值 → 保留)
                return s[len(pat):] if s.startswith(pat) else s
            return s[: -len(pat)] if s.endswith(pat) else s
        # 6) 数组 ${arr[i]} / ${arr[*]} / ${arr[@]}
        m = re.fullmatch(r"([A-Za-z_]\w*)\[([^]]*)\]", expr)
        if m:
            name, idx = m.group(1), m.group(2).strip()
            els = arrays.get(name)
            if els is None:
                return None
            if idx in ("*", "@"):
                sep = env.get("IFS", " ")
                if sep == "":       # IFS 清空 → 无分隔连接 (cmd=(r m); IFS= → rm)
                    return "".join(els)
                return sep[0].join(els) if sep else "".join(els)
            try:
                i = int(idx)
            except ValueError:
                return None
            if i < 0:
                i += len(els)
            if 0 <= i < len(els):
                return els[i]
            return ""
        return None

    def _sub(m: Any) -> Any:
        val = _eval_one(m.group(1))
        if val is None:
            return m.group(0)       # 无法求值 → 保留原文, fail-closed 兜底
        return val

    return _PARAM_OP_RE.sub(_sub, text)


# ------------------------------------------------------------ 间接写法展开 (绕过修复)
# 这些 wrapper 会把真实命令藏在其参数里, 必须剥开才能让段首的 token 判定命中。
_INNER = r'("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|\S+)'

# 解释器 -c / -e (至少带一个旗标, 避免误剥 `bash script.sh` 这类无旗标调用):
#   sh -c "rm -rf /" / bash -c '...' / python -c "..." / perl -e '...' 等
# 旗标与内联命令之间允许无空格 (`sh -c"rm -rf /"` / `python3 -c"..."`),
# 这类无空格写法同样会被真实 shell 执行, 此前因 `\s+` 要求而漏判。
_INTERP_RE = re.compile(
    r'\b(?:bash|sh|zsh|ksh|python\d*|perl|ruby|node|php|lua|tclsh|'
    r'erl|Rscript|osascript|groovy|julia|scala|swift|kotlin|elixir|'
    r'irb|racket|guile|sbcl)\b'
    r'(?:\s+-{1,2}[A-Za-z]+)+'   # ≥1 旗标 (-c / -e / --eval / --norc 等, 支持双连字符)
    r'\s*(' + _INNER + r')',
    re.IGNORECASE,                # 大小写混淆 (PYTHON3 / PERL / Bash) 同样剥壳
)
# PowerShell 特殊处理: -EncodedCommand (Base64 编码的命令)
_PS_ENCODED_RE = re.compile(
    r'\b(?:powershell|pwsh)\b.*?-\s*(?:e|ec|enc|EncodedCommand)\s+(\S+)', re.IGNORECASE
)
# PowerShell -Command / -c 内联命令 (旗标与命令间允许无空格)
_PS_COMMAND_RE = re.compile(
    r'\bpowershell\b.*?-\s*(?:Command|c)\s*(' + _INNER + r')', re.IGNORECASE
)
# cmd /c 内联命令 (旗标与命令间允许无空格)
_CMD_C_RE = re.compile(
    r'\bcmd\b.*?/\s*c\s*(' + _INNER + r')', re.IGNORECASE
)
# sudo 及其带参变体: sudo -u user / sudo -g group / sudo -i / sudo -s ...
# 仅 -u / -g 等真正带参数的旗标消费其后参数, 其余单字母旗标 (-i/-s/-E...) 不带参,
# 否则会把紧跟的命令 (rm) 误当成旗标参数而漏剥。
_SUDO_RE = re.compile(r'\bsudo\b(?:\s+-(?:u|g)\s+\S+|\s+-[A-Za-z]+)*\s+')
# eval "cmd" (source 内容不可静态分析, 不在此展开)
_EVAL_RE = re.compile(r'\beval\b\s*')
# 检测 eval 是否存在 (剥离时用 _EVAL_RE, 检测用本正则, 避免 \s* 影响判断)
_EVAL_DETECT = re.compile(r'\beval\b')
# 透传包装: xargs / env / timeout / nice / nohup / command / builtin / watch / 等
_PASS_RE = re.compile(
    r'\b(?:xargs|env|nice|setsid|stdbuf|flock|command|builtin|watch|ionice|nohup|timeout|parallel)\b'
    r'(?:\s+(?:-[A-Za-z]+(?:\s+\S+)?|[A-Za-z_]\w*=\S+|\d+))*'
    r'\s+'
)
# find ... -exec CMD [{}] \; (shell 常把 ; 转义为 \;) / -exec CMD [{}] +
# 命令体可能含 sh -c '...' 等嵌套, 用非贪婪捕获到终结符为止 (不必含 {})
_FIND_EXEC_RE = re.compile(r'-exec\s+(.+?)\s*\\?[\+;]')


def _try_decode_ps_encoded(text: str) -> str:
    """尝试解码 PowerShell -EncodedCommand 的 Base64 内容。

    如果找到 -EncodedCommand <base64>, 尝试用 utf-16-le (PowerShell 默认编码) 解码,
    解码成功则把原始命令替换为解码后的文本供后续红线检测。
    解码失败则原样返回 (不做处理)。
    """
    m = _PS_ENCODED_RE.search(text)
    if not m:
        return text
    # \\S+ 会连同收尾引号/分号/括号一起吞进来 (如 powershell -enc "b64"; cmd),
    # 这里只取开头连续的 base64 字符, 解码失败概率大降; 引号包裹的编码串 (cmd /c
    # "powershell -enc ...") 此前因尾引号导致 decode 失败而原样漏放。
    b64_str = m.group(1)
    # 先剥前导/收尾引号 (powershell -enc "b64" 或 'b64'), 再取连续 base64 字符
    # (吞掉分号/括号等尾随分隔符)。此前引号包裹的编码串因 decode 失败而原样漏放。
    b64_str = b64_str.strip().strip("'").strip('"')
    b64_match = re.match(r"[A-Za-z0-9+/=]+", b64_str)
    if not b64_match:
        return text
    b64_str = b64_match.group(0)
    try:
        decoded_bytes = base64.b64decode(b64_str, validate=True)
        # 优先尝试 UTF-8 (纯 ASCII 命令更常见), 失败则回退 UTF-16LE
        try:
            decoded = decoded_bytes.decode('utf-8')
            # 确认是可打印文本 (排除二进制误匹配)
            if not all(c.isprintable() or c in '\n\r\t' for c in decoded):
                raise UnicodeDecodeError('utf-8', b'', 0, 1, 'not printable')
        except (UnicodeDecodeError, ValueError):
            try:
                decoded = decoded_bytes.decode('utf-16-le')
            except UnicodeDecodeError:
                decoded = decoded_bytes.decode('utf-8', errors='replace')
        # 用解码后的命令替换整个 powershell -EncodedCommand ... 部分
        return text[:m.start()] + decoded + text[m.end():]
    except Exception:  # noqa: BLE001 - Base64 解码失败则原样
        return text


# ANSI-C quoting ($'...' / $"...") 中支持的转义映射 (bash/dash 常见子集)。
# 关键点: \xHH / \0OOO 十六/八进制转义可把空格/斜杠编码成 `rm\x20-rf\x20/` 这类
# 无空字符串, 若不解码, token 化判定 (依赖空白分词) 会整体漏判 —— 必须先还原为
# 真实字符再进入间接层展开。
_ANSI_C_ESC = {
    "n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "e": "\x1b",
    "f": "\f", "v": "\v", "\\": "\\", "'": "'", '"': '"', "$": "$",
}


def _decode_ansi_c_escapes(s: str) -> str:
    """解码 ANSI-C quoted 字符串中的转义: \\xHH, \\0OOO(八进制), \\n/\\t/\\r 等。

    未知转义保留反斜杠原样 (避免误伤普通路径, 如 $'a\\b' 的 Windows 路径)。
    """
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch != "\\" or i + 1 >= n:
            out.append(ch)
            i += 1
            continue
        nxt = s[i + 1]
        # \xHH (1-2 位十六进制)
        if nxt == "x" and i + 2 < n:
            h = s[i + 2:i + 4]
            if len(h) == 2 and all(c in "0123456789abcdefABCDEF" for c in h):
                out.append(chr(int(h, 16)))
                i += 4
                continue
            out.append("\\")
            i += 1
            continue
        # \uHHHH (4 位十六进制 Unicode) — 对抗 `$'\uff52\uff4d'` 这类把全角
        # 字符经 Unicode 转义编码进 ANSI-C quoting 的混淆 (全角 r 需再经 NFKC 折叠)。
        if nxt == "u" and i + 5 < n:
            h = s[i + 2:i + 6]
            if len(h) == 4 and all(c in "0123456789abcdefABCDEF" for c in h):
                out.append(chr(int(h, 16)))
                i += 6
                continue
            out.append("\\")
            i += 1
            continue
        # \0OOO (最多 3 位八进制)
        if nxt == "0" and i + 2 < n and s[i + 2] in "01234567":
            j = i + 1
            digits = ""
            while j < n and len(digits) < 3 and s[j] in "01234567":
                digits += s[j]
                j += 1
            out.append(chr(int(digits, 8)))
            i = j
            continue
        # 常见转义映射 (\n / \t / \r / \\ / \' ...)
        if nxt in _ANSI_C_ESC:
            out.append(_ANSI_C_ESC[nxt])
            i += 2
            continue
        # \NNN 裸八进制 (1-3 位, 首位 0-7): bash 的 $'\162\155' 等价于 "rm"。
        # 必须放在已知转义映射之后, 否则 \r(回车) 会被误当八进制解析成 \162。
        if nxt in "01234567":
            j = i + 1
            digits = ""
            while j < n and len(digits) < 3 and s[j] in "01234567":
                digits += s[j]
                j += 1
            out.append(chr(int(digits, 8)))
            i = j
            continue
        # 未知转义: 保留原样
        out.append("\\")
        i += 1
    return "".join(out)


def _eval_is_unverifiable(text: str) -> bool:
    """eval 包裹命令替换 ($(...) / `...`) 时, 替换结果会被 eval 当作代码执行,
    其内容无法静态确定 —— 按 fail-closed 原则视为不可验证操作 (红线)。

    例: ``eval "$(echo 'rm -rf /')"`` / ``eval `echo 'rm -rf /'``` ——
    eval 会先求值 $() 再执行其结果字符串, 静态分析无法得知最终命令,
    只能拒绝。单纯的 ``eval "rm -rf /"`` 不在此列 (内容静态可见, 走常规检测)。
    """
    if not _EVAL_DETECT.search(text):
        return False
    inner = _EVAL_RE.sub("", text)
    return "$(" in inner or "`" in inner


def _inline_command_subs(text: str, max_iter: int = 8) -> str:
    """把命令替换 $() / 反引号的内容就地内联, 供红线判定。

    与旧实现的「抽取到独立段」不同: 就地内联保留上下文 (如 ``rm $(echo -rf) /``
    中 -rf 旗标浮回命令行), 且对嵌套 ``$(echo $(rm -rf /))`` 通过迭代收敛到内层。
    迭代上限防止病态输入 (如无限嵌套) 拖垮检测。
    """
    _CMD_SUB_RE = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")

    def _sub(m: Any) -> str:
        body = m.group(1) if m.group(1) is not None else m.group(2)

        def _unresolved() -> str:
            # Preserve the executed substitution body as a separate scan segment. Its
            # output is unknown, but dropping the body can hide nested destructive calls.
            return "__tuan_unresolved_command_substitution__ ; " + str(body)

        try:
            parts = shlex.split(body, posix=True)
        except ValueError:
            return _unresolved()
        if parts and _cmd_name(parts[0]) == "echo":
            values = parts[1:]
            echo_flags: set[str] = set()
            while values and values[0] in ("-n", "-e", "-E", "-ne", "-en", "-nE", "-En"):
                echo_flags.update(values.pop(0)[1:])
            if "e" in echo_flags and "E" not in echo_flags:
                values = [_decode_ansi_c_escapes(value) for value in values]
            return " ".join(values).rstrip("\n")
        if parts and _cmd_name(parts[0]) == "printf" and len(parts) >= 2:
            fmt, *args = parts[1:]
            output: list[str] = []
            arg_index = 0
            i = 0
            while i < len(fmt):
                if fmt[i] != "%":
                    output.append(fmt[i])
                    i += 1
                    continue
                if i + 1 < len(fmt) and fmt[i + 1] == "%":
                    output.append("%")
                    i += 2
                    continue
                conversion = re.match(r"%[-+ #0-9.]*([a-zA-Z])", fmt[i:])
                if not conversion or conversion.group(1) not in ("s", "b"):
                    return _unresolved()
                value = args[arg_index] if arg_index < len(args) else ""
                arg_index += 1
                if conversion.group(1) == "b":
                    value = _decode_ansi_c_escapes(value)
                output.append(value)
                i += conversion.end()
            if arg_index < len(args):
                return _unresolved()
            return "".join(output)
        return _unresolved()

    cur = text
    for _ in range(max_iter):
        nxt = _CMD_SUB_RE.sub(_sub, cur)
        if nxt == cur:
            break
        cur = nxt
    return cur


def _unwrap_indirection(text: str) -> str:
    """循环剥开执行间接层, 让真实命令浮到段首供红线判定。

    覆盖: 解释器 -c/-e (sh/bash/zsh/ksh/python/perl/ruby/node/php/lua/tclsh);
    带参 sudo (-u 用户 / -g 组 / -i / -s 等); eval; xargs/env/timeout/nice 等
    透传包装; find ... -exec CMD {} \\;; PowerShell -EncodedCommand (Base64);
    PowerShell -Command/-c; cmd /c。

    安全修复: 循环直到文本不再变化 (不再限制 6 层), 防止深层嵌套绕过。

    加固 (递归编码解壳): PowerShell -EncodedCommand 解码从「循环外只做一次」
    改为「每层循环都尝试解码」。对抗嵌套编码 `powershell -enc <b64-of-(powershell
    -enc <b64-of-payload>)>`: 旧实现只剥最外层, 内层 `powershell -enc <b64>`
    的密文永远不再解码, `Remove-Item -Recurse -Force C:\\` 等致命载荷浮出不来
    (实测漏放)。现在每层剥壳后若新文本仍含 `powershell -enc`, 继续剥开直到收敛;
    base64/hex 管道链另有保守拦截兜底 (见 _is_base64_pipeline_dangerous)。
    """
    cur = text
    for _ in range(32):  # 安全上限 32 层, 实际通常 2-3 层就稳定
        nxt = cur
        # 递归解码 PowerShell -EncodedCommand (可能嵌套多层编码); 放在各间接层
        # 剥离之前: 解码出的明文可能含 cmd /c、sh -c 等, 供后续步骤继续剥开。
        nxt = _try_decode_ps_encoded(nxt)
        # 先处理 find -exec: 提取命令体并用 " ; " 隔离成独立段。
        # 必须在解释器展开之前, 否则 sh -c 会被先剥掉导致 -exec 失去锚点。
        nxt = _FIND_EXEC_RE.sub(lambda m: " ; " + m.group(1) + " ; ", nxt)
        nxt = _INTERP_RE.sub(lambda m: m.group(1), nxt)   # 剥解释器, 保留 -c 参数
        nxt = _PS_COMMAND_RE.sub(lambda m: m.group(1), nxt)  # 剥 PowerShell -Command/-c
        nxt = _CMD_C_RE.sub(lambda m: m.group(1), nxt)      # 剥 cmd /c
        nxt = _SUDO_RE.sub("", nxt)                        # 剥 sudo 及其旗标/参数
        nxt = _EVAL_RE.sub("", nxt)                        # 剥 eval
        nxt = _PASS_RE.sub("", nxt)                        # 剥透传包装
        if nxt == cur:
            break
        cur = nxt
    return cur


def _resolve_symlinks(text: str) -> str:
    """尝试解析命令中可能的符号链接路径。

    对每个看起来是路径的 token, 尝试 os.path.realpath() 解析。
    如果解析后路径与原始不同 (是符号链接), 替换为真实路径供红线检测。
    仅处理实际存在的路径, 不存在的路径原样保留。
    """
    def _try_resolve(token: str) -> str:
        if not token or token.startswith('-') or token in (';', '&&', '||', '|'):
            return token
        # 绝对路径不做 realpath: Windows 上 realpath('/') 会解析为盘符根 (如 E:\),
        # 改写后破坏红线正则的 '/' 锚点, 反而造成漏判。仅对相对路径做符号链接解析。
        if token.startswith('/') or re.match(r'^[A-Za-z]:', token) or token.startswith('\\\\'):
            return token
        # 跳过明显的命令名/旗标
        if '/' not in token and '\\' not in token:
            return token
        try:
            real = os.path.realpath(token)
            if real != token and os.path.exists(real):
                return real
        except Exception:  # noqa: BLE001
            pass
        return token

    # 安全修复: 逐行处理后再用换行拼回。
    # 旧实现用 ' '.join() 会把 "\n" 命令分隔符压成空格, 导致
    # "ls\nrm -rf /" 被合并成单段 "ls rm -rf /", 段首不是 rm 从而绕过红线。
    return '\n'.join(' '.join(_try_resolve(p) for p in line.split())
                     for line in text.split('\n'))


def _tokenize_shell(text: str) -> list[str]:
    """按空白分词, 尊重单/双引号 (引号内空白不拆分); 反斜杠按字面处理 (兼容 Windows 路径)。

    朴素 ``text.split()`` 会把含空格的路径 (如 ``rm /path with space/*.txt``) 拆碎,
    导致 glob 无法展开 —— 这是旧实现在路径含空格时失效的根因。这里只在引号外拆分,
    既保留 ``"a b/*.txt"`` 这类带空格 glob 的完整性, 也不破坏普通多参数命令。
    """
    tokens: list[str] = []
    cur: list[str] = []
    quote: str | None = None
    for ch in text:
        if quote:
            if ch == quote:
                quote = None
            cur.append(ch)
        elif ch in ("'", '"'):
            quote = ch
            cur.append(ch)
        elif ch.isspace():
            if cur:
                tokens.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        tokens.append("".join(cur))
    return tokens


def _expand_globs(text: str) -> str:
    """尝试展开命令中的 glob 通配符为实际路径列表。

    对含 *, ?, [, { 的路径 token, 用受限 glob 展开, 展开后对每个路径做红线检测更精确。
    仅展开工作目录下实际存在的匹配, 不存在则原样保留。
    使用引号感知分词 (见 _tokenize_shell), 修复含空格路径被拆碎的问题。

    安全约束 (防 `**` 遍历全盘):
      - ** 递归深度上限 _GLOB_MAX_DEPTH;
      - 单 token 匹配数上限 _GLOB_MAX_MATCHES (防输出膨胀/路径轰炸);
      - 目录遍历迭代预算 _GLOB_MAX_ITERATIONS (防恶意深度结构造成 CPU 抖动)。
    """

    def _try_expand(token: str) -> str:
        bare = token.strip("'\"")
        if not bare or bare.startswith('-'):
            return token
        if not any(c in bare for c in '*?[{'):
            return token
        matches = _bounded_glob(bare)
        if matches:
            # 安全修复: 只限条数不够 —— 单 token 命中 1000 条路径时, 展开文本可达
            # 3 万字符, 后续每条正则都要在这段长串上扫描, 而模式库里有多条
            # 含 [\s\S]* 嵌套前瞻的正则 (tar-over-ssh / reverse-shell), 复杂度
            # 随长度平方甚至更高地放大。实测 `python3 -m pytest tests/test_*.py`
            # (命中 290 个真实测试文件) 让单条命令的完整评估耗时 22.2 秒 —— 一条
            # 日常测试命令就能卡死 Agent。因此同时限制**展开后总字符数**: 超出后
            # 截断匹配, 保留代表性样本供红线检测, 并把原文本一并保留以免漏判。
            out = ' '.join(matches[:_GLOB_MAX_MATCHES])
            if len(out) > _GLOB_MAX_TOTAL_CHARS:
                kept: list[str] = []
                acc = 0
                for m in matches:
                    add = len(m) + 1
                    if acc + add > _GLOB_MAX_TOTAL_CHARS:
                        break
                    kept.append(m)
                    acc += add
                out = ' '.join(kept)
                out += f" …({len(matches) - len(kept)} 个匹配已省略)"
            return out
        return token

    # 安全修复: 逐行处理后再用换行拼回 (同 _resolve_symlinks, 防止 "\n" 分隔符丢失)。
    return '\n'.join(' '.join(_try_expand(p) for p in _tokenize_shell(line))
                     for line in text.split('\n'))


def _expand_glob_cmd_names(text: str) -> str:
    """把含 glob 通配符的**命令名**展开为真实危险命令名 (报告 P1-1)。

    与 _expand_globs (路径 token) 不同, 本函数针对**命令名位置**的 token:
    ``/bin/r?`` → ``/bin/rm``、``/bin/c?mod`` → ``/bin/chmod``、
    ``/bin/umou?t`` → ``/bin/umount``。展开后让正则模式库 (\\bchmod\\b 等) 也能命中。

    平台无关: 不依赖真实文件系统; 无法匹配任何危险命令名的通配 token 原样保留。
    """
    out_tokens: list[str] = []
    for line in text.split('\n'):
        toks = _tokenize_shell(line)
        new_toks: list[str] = []
        # 只把「命令名位置」的 token 当命令名 glob 处理。命令名位置 = 每条子命令的
        # 首 token; 子命令由 `;`/`&&`/`||`/`|`/`&`/`(` 分隔。否则路径参数里的通配
        # (如 `rm -rf node_modules/*` 的 `node_modules/*`) 会被误当成命令名 glob,
        # 其 basename `*` 匹配一切危险命令名, 造成硬红线误判。
        at_cmd_start = True
        for tok in toks:
            stripped = tok.strip("'\"")
            if stripped in (";", "&&", "||", "|", "&", "(", ")"):
                at_cmd_start = True
                new_toks.append(tok)
                continue
            if at_cmd_start:
                g = _glob_command_name(tok)
                if g is not None:
                    # 保留路径前缀, 替换 basename 为真实命令名 (/bin/r? → /bin/rm)
                    prefix = tok.strip("'\"")
                    base = prefix.rsplit("/", 1)
                    if len(base) == 2:
                        new_toks.append(base[0] + "/" + g)
                    else:
                        new_toks.append(g)
                    at_cmd_start = False
                    continue
            at_cmd_start = False
            new_toks.append(tok)
        out_tokens.append(' '.join(new_toks))
    return '\n'.join(out_tokens)


# ---------- 受限 glob: 防止 `**` 递归遍历全盘 / 输出膨胀 / CPU 抖动 ----------
_GLOB_MAX_DEPTH = 6          # ** 允许穿越的最大目录层数
_GLOB_MAX_MATCHES = 1000     # 单 token 展开结果条数上限
_GLOB_MAX_ITERATIONS = 5000  # 单次展开最多执行的目录迭代次数 (超时保护)
# 单 token 展开后的**总字符数**上限。条数上限挡不住「1000 个长路径」造成的文本膨胀,
# 而膨胀后的长串会让下游含 [\s\S]* 嵌套前瞻的正则产生平方级以上的耗时 (实测单条
# 命令 22 秒)。这是真正的 DoS 面: 攻击者只要让 Agent 分析一条带 glob 的命令即可卡死。
_GLOB_MAX_TOTAL_CHARS = 1500


def _bounded_glob(pattern: str) -> List[str]:
    """带深度/次数/条数约束的 glob 展开。无 `**` 时走原生非递归 glob (天然受限)。"""
    if '**' not in pattern:
        try:
            import glob as _glob_mod
            return list(_glob_mod.glob(pattern))
        except Exception:  # noqa: BLE001
            return []
    out: List[str] = []
    budget = {"left": _GLOB_MAX_ITERATIONS}

    def walk(base: Any, parts: Any, depth: Any) -> None:  # noqa: ANN001
        if not parts or budget["left"] <= 0:
            if not parts:
                out.append(str(base))
            return
        head, rest = parts[0], parts[1:]
        if head == '**':
            # ** 匹配零层或多层目录 (深度受限)
            walk(base, rest, depth)
            if depth < _GLOB_MAX_DEPTH and budget["left"] > 0:
                try:
                    for child in base.iterdir():
                        budget["left"] -= 1
                        if budget["left"] < 0:
                            return
                        if child.is_dir():
                            walk(child, rest, depth + 1)
                except OSError:
                    pass
        elif any(c in head for c in '*?['):
            try:
                for child in base.glob(head):
                    budget["left"] -= 1
                    if budget["left"] < 0:
                        return
                    walk(child, rest, depth)
            except OSError:
                pass
        else:
            cand = base / head
            if cand.exists():
                walk(cand, rest, depth)

    # 基准目录 = 第一个通配符前的字面前缀; 支持相对/绝对/家目录路径
    m = None
    for anchor in ('*', '?', '[', '{'):
        i = pattern.find(anchor)
        if i != -1 and (m is None or i < m):
            m = i
    base_str = pattern[:m] if m is not None else pattern
    try:
        from pathlib import Path
        base = Path(base_str).expanduser() if base_str else Path('.')
        if not base.is_dir():
            base = base.parent
        rel = pattern[(m if m is not None else len(pattern)):]
        rel_parts = [p for p in rel.replace('\\', '/').split('/')
                     if p and p != '.']
        walk(base, rel_parts, 0)
    except Exception:  # noqa: BLE001
        return [] if not out else out
    _dedup: dict[str, None] = {}
    for p in out:
        _dedup.setdefault(p, None)
    return list(_dedup.keys())


# 破折号/连字符同形字 → ASCII 连字符 (对抗 rm‑rf 的 U+2011 / 减号 U+2212 混淆)
_DASH_MAP = dict.fromkeys(
    (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212, 0xFE63, 0xFF0D), "-")

# 西里尔同形字 → ASCII 映射 (对抗 Cyrillic р U+0440 → r 等混淆)
_CYRILLIC_MAP = {
    0x0440: ord('r'),  # Cyrillic р → Latin r
    0x0430: ord('a'),  # Cyrillic а → Latin a  
    0x0435: ord('e'),  # Cyrillic е → Latin e
    0x043E: ord('o'),  # Cyrillic о → Latin o
    0x0441: ord('c'),  # Cyrillic с → Latin c
    0x0443: ord('y'),  # Cyrillic у → Latin y (visually similar to y)
    0x0445: ord('x'),  # Cyrillic х → Latin x
}

# 同形字归一表 (西里尔之外的 confusables): 希腊 / 亚美尼亚等脚本中视觉上与 ASCII
# 字母相同、但码点不同的字符。攻击者可用同形字母命名可执行文件 (如 ρm, 内含 shebang)
# 或在命令名里混入同形字, 使 ASCII 精确比较 (parts[0]=="rm") 落空。此处把它们归一到
# ASCII, 供 _cmd_name 在小写化前调用, 令 ρm → rm 等被识别。
# 仅收录与危险命令字母重叠的 ASCII 对应项, 控制表规模。
_HOMOGLYPH_MAP: dict[int, int] = {
    # --- Greek ---
    0x0391: ord('A'), 0x03B1: ord('a'),  # Alpha
    0x0392: ord('B'), 0x03B2: ord('b'),  # Beta
    0x0395: ord('E'), 0x03B5: ord('e'),  # Epsilon
    0x0397: ord('H'), 0x03B7: ord('h'),  # Eta (visual h)
    0x0399: ord('I'), 0x03B9: ord('i'),  # Iota
    0x039A: ord('K'), 0x03BA: ord('k'),  # Kappa
    0x039C: ord('M'), 0x03BC: ord('m'),  # Mu
    0x039D: ord('N'), 0x03BD: ord('n'),  # Nu
    0x039F: ord('O'), 0x03BF: ord('o'),  # Omicron
    0x03A1: ord('P'), 0x03C1: ord('r'),  # Rho  (ρ → r, 关键)
    0x03A4: ord('T'), 0x03C4: ord('t'),  # Tau
    0x03A5: ord('Y'), 0x03C5: ord('u'),  # Upsilon
    0x03A7: ord('X'), 0x03C7: ord('x'),  # Chi
    # Greek with tonos (ά έ ή ί ό ύ ώ) — 归一到无调 ASCII
    0x03AC: ord('a'), 0x03AD: ord('e'), 0x03AE: ord('h'),
    0x03AF: ord('i'), 0x03CC: ord('o'), 0x03CD: ord('u'), 0x03CE: ord('w'),
    # --- Armenian ---
    0x0561: ord('a'), 0x0562: ord('b'), 0x0563: ord('g'), 0x0564: ord('d'),
    0x0565: ord('e'), 0x0567: ord('i'), 0x056B: ord('h'), 0x056D: ord('x'),
    0x056E: ord('c'), 0x0570: ord('h'), 0x0571: ord('r'),  # հ / ր 视觉接近
    0x0578: ord('n'), 0x0579: ord('o'), 0x0580: ord('p'),
}

_HOMOGLYPH_TRANSLATION = str.maketrans(_HOMOGLYPH_MAP)


def _HOMOGLYPH_MAP_TRANSLATE(text: str) -> str:
    """把同形字 (希腊/亚美尼亚 confusables) 归一到 ASCII, 供命令名比较使用。

    与 `_CYRILLIC_MAP` 分开维护: 二者覆盖不同 Unicode 区块, 合并会扩大每次翻译
    的查找表。本函数在 `_unicode_clean` 之后调用 —— 控制符/变体选择符已先被剥离,
    不会干扰同形字判定。
    """
    if not text.isascii():
        return text.translate(_HOMOGLYPH_TRANSLATION)
    return text


# 组合变音符号范围: U+0300-U+036F (Combining Diacritical Marks)
_COMBINING_MARKS_RE = re.compile(r'[\u0300-\u036f\u0483-\u0489]')

# 控制字符 (除常见空白外): null byte, backspace, bell, escape, etc.
_CONTROL_CHARS_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

# Variation Selectors: U+FE00-FE0F (16 个变体选择符, 含 VS15/VS16) +
# U+E0100-U+E01EF (Supplementary Ideographic Variation Selectors, 240 个)
# 这些字符不影响语义, 仅改变显示方式 (如 emoji/text presentation), 但会割裂 token:
#   r\uFE0Fm → 视觉上看起来是 rm, 但实际 token 是 r + FE0F + m
# U+FE0F (VS16) 最常被滥用为 emoji presentation selector 混淆。
_VARIATION_SELECTORS_RE = re.compile(r'[\ufe00-\ufe0f\U000e0100-\U000e01ef]')

# 命令替换 `$(` / 反引号出现在命令要求原处尽管引号包裹也会被真实执行 → 取消「文本提及」豁免。
_CMD_SUB_ANY_RE = re.compile(r"\$\(|`")


def _unicode_clean(text: str) -> str:
    """剥掉不可见/合成类 Unicode 字符 (零宽、变体选择符、组合变音、控制符)。

    放在 NFD 解构**之后**执行, 使组合变音符号 (U+0300-U+036F) 先被拆成独立码点
    再删除 —— 否则 NFKC 会把 `r + U+0301` 组合成预组合 ŕ (U+0155) 而逃出删除范围。
    """
    text = _VARIATION_SELECTORS_RE.sub('', text)
    text = _COMBINING_MARKS_RE.sub('', text)
    text = re.sub(r'[\u00ad\u180e\u200b-\u200f\u2028-\u202f\u2060-\u206f\ufeff]', '', text)
    text = _CONTROL_CHARS_RE.sub('', text)
    return text


# 整行 / 行尾 shell 注释剥离 (报告 P2 误杀修复)。
# `# 谨慎: rm -rf /`(整行注释) 与 `rm -rf / # 说明`(行尾注释) 在 shell 里都是注释,
# 不是要执行的命令。旧实现未剥离, `# 谨慎: rm -rf /` 被 is_redline 误判为执行。
# 剥离必须在 token 化/变量展开之前, 且不能破坏引号内的 `#` (如 echo '# rm -rf /')。
def _strip_shell_comments(text: str) -> str:
    out_lines: list[str] = []
    for line in text.split('\n'):
        # 逐字符扫描: 引号内 / 转义字符的 # 不算注释开始
        in_s = in_d = False
        esc = False
        cut = len(line)
        for i, ch in enumerate(line):
            if esc:
                esc = False
                continue
            if ch == '\\' and not in_s and not in_d:
                esc = True
                continue
            if ch == "'" and not in_d:
                in_s = not in_s
                continue
            if ch == '"' and not in_s:
                in_d = not in_d
                continue
            if ch == '#' and not in_s and not in_d:
                # # 前是空白或行首 → 注释开始; 否则是参数 (如 ${x#pat} 的 # 是操作符)
                if i == 0 or line[i - 1] in ' \t':
                    cut = i
                    break
        out_lines.append(line[:cut])
    return '\n'.join(out_lines)


def _normalize(text: str) -> str:
    """归一化间接写法, 让红线判定穿透子壳 / 变量 / 引号 / 解释器包装。

    安全修复 (v1.3):
    - Unicode NFKC 归一化: 防止全角字符/零宽空格/ANSI-C quoting 混淆;
    - ANSI-C quoting ($'...' / $"...") 剥壳并解码转义: \\xHH / \\0OOO / \\n / \\t 等,
      对抗 `bash -c $'rm\\x20-rf\\x20/'` 把空格编码成十六进制转义的混淆写法;
    - IFS 变量替换: $IFS / ${IFS} 等价于字段分隔符 (空格), 对抗 `rm${IFS}-rf${IFS}/`
      这类无空字符串 (token 化判定依赖空白分词, 不解码则整体漏判);
    - 执行间接层 (sh -c / sudo -u / eval / xargs / find -exec / PowerShell -Command 等)
      先被 _unwrap_indirection 剥开, 真实命令浮到段首; 旗标与命令间无空格
      (`sh -c"rm -rf /"`) 也在此展开;
    - 命令替换 $(...) 与 `...`: 内层命令会被真实执行, 就地内联供判定 (支持嵌套);
    - NAME=value 前缀赋值: 收集后把后续文本里的 $NAME/${NAME} 替换为字面值
      (如 R="rm"; F="-rf"; $R $F /data → rm -rf /data);
    - 符号链接解析: 路径 token 尝试 realpath() 解析, 穿透 symlink;
    - Glob 展开: 含通配符的路径尝试展开为实际路径列表;
    - token 首尾的包裹符 () ' " ` 剥掉 ((rm -rf /)、"rm -rf x" 同样命中)。
    注意: 变量替换须在 lower() 之前做 —— 变量名大小写敏感。
    """
    # 安全修复: 先合并行续接符 (backslash-newline)。shell 中 `\<换行>` 是续行符,
    # `dd if=/dev/zero \<换行>of=/dev/sda` 会被真实 shell 合成**单条**命令执行。
    # 不合并则跨行模式 (dd ... of=/dev/...) 的 [^\n]* 前瞻会断在换行处 → 漏判;
    # 这是「多行 dd 写裸设备」这类真实绕过手法的根因。必须在各分词/逐行步骤之前做。
    text = re.sub(r"\\\r?\n", " ", text)
    # 安全修复 (报告 P2): 剥离整行/行尾 shell 注释。`# 谨慎: rm -rf /` 是注释不是执行,
    # 旧实现未剥离导致误判。须在 Unicode/变量/token 化之前做, 且不破坏引号内 `#`。
    text = _strip_shell_comments(text)
    # 安全修复: 先 NFD 解构 (把预组合 ŕ 拆回 r + 组合重音), 剥掉组合变音/变体选择符/
    # 零宽/控制字符, 再 NFKC 折叠全角→ASCII —— 顺序颠倒会让 NFKC 先把 r+U+0301 拼成
    # 预组合 ŕ (U+0155), 组合重音就此逃出删除范围, 形成 `r\u0301m` 混淆绕过。
    text = unicodedata.normalize('NFD', text)
    text = _unicode_clean(text)
    text = unicodedata.normalize('NFKC', text)

    # 安全修复: 西里尔同形字映射 — 对抗 Cyrillic р → r 混淆
    if _CYRILLIC_MAP:
        text = text.translate(_CYRILLIC_MAP)
    # 破折号同形字统一为 ASCII 连字符
    if _DASH_MAP:
        text = text.translate(_DASH_MAP)
    # rm 与旗标被连字符粘连 (rm-rf / rm‒rf) 时补一个空格, 让 token 化判定命中
    text = re.sub(r'\brm(?=\s*-+\s*[rRfF]{1,2}\b)', 'rm ', text)
    # rm 与引号粘连 (rm'-rf' / rm"-rf") 时先剥掉紧贴 rm 的内部引号, 再补空格
    text = re.sub(r"\brm['\"]+(?=\-)", 'rm', text)
    # rm-rf / rm-fr 直接粘连 (无空格) 时拆开, 让 _check_rm_flags 命中
    text = re.sub(r'\brm-(rf|fr)\b', r'rm -\1', text)

    # 安全修复 (V-07): 在 ANSI-C 解码前预捕获 `VAR=$'...'` / `VAR=$"..."` 定义 ——
    # 解码后的值可能含空格 (`X=$'rm\\x20-rf'` → `X=rm -rf`), 而 `_VAR_DEF_RE` 的
    # 值捕获 `[^\s;&|]+` 遇空格即截断, 只抓到 `X=rm` 导致 `-rf` 残留, 后续 `$X /`
    # 替换成 `rm /` 而漏判递归删除。这里先把含 ANSI-C 值的赋值完整收集进 env,
    # 从文本中移除定义后再让后续 ANSI-C 解码与普通变量赋值继续处理剩余部分。
    env: dict[str, str] = {}
    _ANSI_C_ASSIGN_RE = re.compile(
        r"(?:^|[;|&\n])\s*([A-Za-z_]\w*)=\$'([^']*)'"
        r"|(?:^|[;|&\n])\s*([A-Za-z_]\w*)=\$\"([^\"]*)\""
    )

    def _capture_ansi_assign(m: Any) -> str:
        name1, val1, name2, val2 = m.group(1), m.group(2), m.group(3), m.group(4)
        name = name1 if name1 else name2
        raw_val = val1 if name1 else val2
        env[name] = _decode_ansi_c_escapes(raw_val)
        # 保留前导分隔符 (如果有), 把整个赋值替换为空格
        leading = m.group(0)[0] if m.group(0)[0] in ";|&\n" else " "
        return leading + " "

    text = _ANSI_C_ASSIGN_RE.sub(_capture_ansi_assign, text)

    # 安全修复: ANSI-C / locale 引号 ($'...' / $"...") 剥壳并解码转义 ——
    # 对抗 `bash -c $'rm -rf /'` / `eval $"rm -rf /"` 类混淆;
    # 解码 \\xHH / \\0OOO 等转义后, `rm\\x20-rf\\x20/` 还原为 `rm -rf /` 供后续分词。
    text = re.sub(r"\$\'([^\']*)\'", lambda m: _decode_ansi_c_escapes(m.group(1)), text)
    text = re.sub(r'\$\"([^\"]*)\"', lambda m: _decode_ansi_c_escapes(m.group(1)), text)
    # ANSI-C 解码可能新引入全角字符 ($'\uff52\uff4d') 或 rm-rf 粘连 (rm\x2drf /),
    # 需在解码后再次净化 Unicode 并合并 rm 旗标, 否则上述混淆会逃逸后续 token 判定。
    text = re.sub(r'\brm-(rf|fr)\b', r'rm -\1', text)
    text = _unicode_clean(text)
    text = unicodedata.normalize('NFKC', text)

    # 安全修复: 裸转义序列解码 (\xNN 十六进制 / \NNN 八进制) ——
    # 对抗 `printf '\162\155\040-\162\146\040/'` / `printf '\x72\x6d\x2d\x72\x66\x20/'`
    # 这类不经 $'...' 包裹、直接用转义序列拼出命令名的混淆。
    # 仅解码定长转义 (hex 恰好 2 位 / 八进制恰好 3 位), 避免误伤 \t \n 等常见转义。
    if "\\" in text:
        def _unescape_seq(m: Any) -> Any:
            seq = m.group(0)
            try:
                if seq[:2].lower() == "\\x":
                    return chr(int(seq[2:], 16))
                return chr(int(seq[1:], 8))
            except Exception:  # noqa: BLE001
                return seq
        text = re.sub(r"\\x[0-9a-fA-F]{2}|\\[0-7]{3}", _unescape_seq, text)
        # 解码后可能重新形成 rm-rf 粘连 / 全角字符, 需再净化一次
        text = re.sub(r'\brm-(rf|fr)\b', r'rm -\1', text)
        text = _unicode_clean(text)
        text = unicodedata.normalize('NFKC', text)

    # 安全修复: IFS 变量用于字段分隔, $IFS / ${IFS} 等价于空格。
    # 放在展开之前, 使 `rm${IFS}-rf${IFS}/` 还原为 `rm -rf /` 再进入后续判定。
    # 同时吞掉紧跟的位置参 ($IFS$9 / ${IFS}$9), 避免残留 $9 割裂 token。
    # 只吞一位位置参 ($9/$8...): 位置参最多一位数, `$9000` 是 $9 + 字面 000,
    # 贪婪匹配会把 `chmod -R $9000 /` 的 000 一并吃掉, 归一化成 chmod -R / 而漏判。
    text = re.sub(r'\$\{?IFS\}?(?:\$\d)?', ' ', text)

    # 安全修复: Bash brace expansion 模拟 — {a,b,c} 展开为各分量的并集。
    # 对抗 `{rm,-rf,/}` / `{rm,-r,f,/,}` 等用逗号分隔绕过 token 化判定的写法。
    # 非贪婪匹配: 优先展开最内层花括号。仅当内容含逗号且外层无引号时展开。
    def _expand_brace(m: Any) -> Any:
        inner = m.group(1)
        # 简单情况: 逗号分隔的平面列表 {a,b,c} → a b c
        if ',' in inner and '{' not in inner:
            return ' '.join(inner.split(','))
        return m.group(0)  # 含嵌套花括号的复杂情况, 保留原样
    for _ in range(8):  # 迭代展开多层嵌套
        new_text = re.sub(r'\{([^{}]+)\}', _expand_brace, text)
        if new_text == text:
            break
        text = new_text

    # 安全修复: 进程替换模拟 — <(cmd) 和 >(cmd)。
    # `<()` 内的命令会在子 shell 执行, 结果作为文件路径传递。
    # 对抗 `diff <(rm -rf /) /dev/null` 类混淆: 将 <(cmd) 替换为 (cmd) 让后续
    # 命令替换/子 shell 判定捕获。
    text = re.sub(r'<\(([^()]+)\)', r'(\1)', text)
    text = re.sub(r'>\(([^()]+)\)', r'(\1)', text)

    text = _unwrap_indirection(text)

    # 安全修复: 命令替换就地内联 (支持嵌套), 替代旧「抽取到独立段」——
    # `rm $(echo -rf) /` 中旗标浮回命令行, 且 eval 包裹的动态内容由 _eval_is_unverifiable 兜底。
    text = _inline_command_subs(text)

    # env 已在上方预创建 (含 ANSI-C 变量定义预填充), 此处不重建。
    # 但普通 NAME=value 赋值 (非 ANSI-C 值) 仍由 _VAR_DEF_RE 收集, 会覆写同名 key
    # (如果预填充的同名变量又被普通 NAME=value 定义覆盖, 以普通赋值为准 ——
    # 真实 shell 里后定义的会覆盖先定义的)。

    def _collect(m: Any) -> str:
        name, raw = m.group(1), m.group(2)
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
            raw = raw[1:-1]
        env[name] = raw
        return " "

    arrays: dict[str, list[str]] = {}
    if "=" in text:
        # 先收集数组赋值 (a=(rm)), 防止普通 _VAR_DEF_RE 把 `cmd=(r` 截断。
        def _collect_array(m: Any) -> str:
            name, body = m.group(1), m.group(2)
            # 按空白分词, 剥离包裹引号
            raw = [t.strip("'\"") for t in re.split(r"\s+", body.strip()) if t.strip()]
            arrays[name] = raw
            env[name] = raw[0] if raw else ""   # ${arr} 取首元素 (Bash 语义)
            return " "
        text = _ARRAY_ASSIGN_RE.sub(_collect_array, text)
        text = _VAR_DEF_RE.sub(_collect, text)

    if env or arrays or "${" in text:
        def _expand(m: Any) -> Any:
            return env.get(m.group(1) or m.group(2), m.group(0))
        text = re.sub(r"\$\{(\w+)\}|\$(\w+)", _expand, text)
        # 报告 P0-1: 静态求值参数展开 (切片/前缀/后缀/替换/间接/数组/默认值)。
        # 无法静态求值的 ${...} 保留原文, 由 _has_unresolved_dangerous_substitution fail-closed。
        text = _expand_param_ops(text, env, arrays)
        # 参数展开可能新引入普通 ${VAR} 直引 (如 ${x:-${CMD}}), 再替换一轮。
        text = re.sub(r"\$\{(\w+)\}|\$(\w+)", _expand, text)

    # 安全修复: 未定义变量 / 位置参拼接混淆 — 清空残余 ${VAR} / $VAR / $9,
    # 对抗 `r${X}m -rf /` 这类把命令名拆成变量拼接的写法 (已定义的变量已由上方展开)。
    # 注意跳过命令替换 $(...), 避免破坏已内联的子命令。
    # 位置参只删一位 ($9): `$9000` 在 shell 中解析为 $9 + 字面 000 (见 IFS 步骤说明)。
    text = re.sub(r'\$\{[A-Za-z_]\w*\}', '', text)
    text = re.sub(r'\$(?!\()[A-Za-z_]\w*', '', text)
    text = re.sub(r'\$\d', '', text)

    cleaned = " ".join(tok.strip("()'\"`") for tok in text.split())
    # 安全修复: 符号链接解析 — 穿透 symlink 检测真实路径
    cleaned = _resolve_symlinks(cleaned)
    # 安全修复: Glob 展开 — 展开通配符为实际路径
    cleaned = _expand_globs(cleaned)
    # 安全修复 (报告 P1-1): 命令名位置的 glob/花括号通配 token → 真实危险命令名,
    # 让正则模式库 (\bchmod\b / \bumount\b / \bpkill\b) 也能命中被通配隐藏的命令名。
    cleaned = _expand_glob_cmd_names(cleaned)
    return cleaned
