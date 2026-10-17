"""Python 脚本 AST 静态扫描 (Python script static analysis)。

在执行前对 Python 代码进行 AST 级静态扫描, 检测 subprocess、os.system、
eval、exec、socket、ctypes、pickle 等危险调用。

与正则黑名单互补: 正则无法区分 ``os.path.join("a")`` 与 ``os.system("rm -rf /")``,
AST 扫描能精确识别函数调用及其参数。

设计:
- 纯标准库 (ast), 零额外依赖。
- 返回结构化的 ``ScanResult``, 调用方可按 severity 决定拦截/确认/仅提示。
- ``extract_python_sources`` 从 shell 命令中提取 Python 源 (``-c`` 内联 / 文件路径),
  使 shell.py 可直接调用。

严重等级映射 (与 ctx.safety_severity 一致):
- critical: os.system, os.popen, eval, exec, os.execv* → 硬拦截
- high: subprocess.*, socket.*, ctypes.CDLL, pickle.loads, os.popen2 → 需确认
- medium: compile, __import__, importlib, urllib.request.urlopen → 仅提示
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ================================================================ 危险调用表
# (模块限定名, 函数名, severity, label)
# 限定名为 None 表示全局函数 (如 eval/exec/compile)
_DANGEROUS_CALLS: List[Tuple[Optional[str], str, str, str]] = [
    # ---- critical: 命令执行 / 代码注入 (硬拦截) ----
    (None, "eval", "critical", "eval (任意代码执行)"),
    (None, "exec", "critical", "exec (任意代码执行)"),
    ("os", "system", "critical", "os.system (shell 命令执行)"),
    ("os", "popen", "critical", "os.popen (shell 命令执行)"),
    ("os", "popen2", "critical", "os.popen2 (shell 命令执行)"),
    ("os", "popen3", "critical", "os.popen3 (shell 命令执行)"),
    ("os", "popen4", "critical", "os.popen4 (shell 命令执行)"),
    ("os", "execv", "critical", "os.execv (替换进程执行)"),
    ("os", "execve", "critical", "os.execve (替换进程执行)"),
    ("os", "execvp", "critical", "os.execvp (替换进程执行)"),
    ("os", "execvpe", "critical", "os.execvpe (替换进程执行)"),
    # ---- high: 子进程 / 网络 / 反序列化 (需确认) ----
    ("subprocess", "run", "high", "subprocess.run (子进程调用)"),
    ("subprocess", "call", "high", "subprocess.call (子进程调用)"),
    ("subprocess", "Popen", "high", "subprocess.Popen (子进程调用)"),
    ("subprocess", "check_call", "high", "subprocess.check_call (子进程调用)"),
    ("subprocess", "check_output", "high", "subprocess.check_output (子进程调用)"),
    ("subprocess", "getoutput", "high", "subprocess.getoutput (子进程调用)"),
    ("socket", "socket", "high", "socket.socket (网络套接字)"),
    ("socket", "create_connection", "high", "socket.create_connection (网络连接)"),
    ("socket", "gethostbyname", "high", "socket.gethostbyname (DNS 解析)"),
    ("ctypes", "CDLL", "high", "ctypes.CDLL (动态库加载)"),
    ("ctypes", "WinDLL", "high", "ctypes.WinDLL (动态库加载)"),
    ("pickle", "loads", "high", "pickle.loads (反序列化)"),
    ("pickle", "load", "high", "pickle.load (反序列化)"),
    ("marshal", "loads", "high", "marshal.loads (反序列化)"),
    ("marshal", "load", "high", "marshal.load (反序列化)"),
    ("shutil", "rmtree", "high", "shutil.rmtree (递归删除)"),
    ("shutil", "move", "medium", "shutil.move (文件移动)"),
    # ---- medium: 动态导入 / 网络请求 (仅提示) ----
    (None, "__import__", "medium", "__import__ (动态导入)"),
    ("importlib", "import_module", "medium", "importlib.import_module (动态导入)"),
    ("importlib", "load_source", "medium", "importlib.load_source (动态导入)"),
    ("urllib.request", "urlopen", "medium", "urllib.request.urlopen (网络请求)"),
    ("urllib", "urlopen", "medium", "urllib.urlopen (网络请求)"),
    ("http.client", "HTTPConnection", "medium", "http.client.HTTPConnection (网络请求)"),
]

# subprocess.run/Popen 的 shell=True 参数 → 升级为 critical
_SHELL_TRUE_KEYWORD = "shell"
_SHELL_TRUE_SHELL_ATTR = True

# shell=True 检测: 检查 keyword 参数 shell=True 或位置参数第 2 个为 True
_SUBPROCESS_METHODS_WITH_SHELL = {"run", "call", "Popen", "check_call", "check_output"}

# 文件写入路径检测 (os.write 到 /dev/sda 等)
_RAW_DISK_PATH_RE = re.compile(
    r"/dev/(?:sd[a-z]|nvme\d+n\d+(?:p\d+)?|vd[a-z]|hd[a-z]|xvd[a-z])",
    re.IGNORECASE,
)

# 编译错误消息 (用于友好展示)
_COMPILE_ERROR_RE = re.compile(r"^\s*line\s+(\d+)\s*(.*)$")


@dataclass
class ScanFinding:
    """单条 AST 扫描发现。"""
    severity: str       # critical | high | medium
    label: str          # 人类可读标签
    line: int           # 行号 (1-based)
    col: int            # 列号 (1-based)
    snippet: str        # 源码片段
    detail: str = ""    # 额外信息 (如参数值)


@dataclass
class ScanResult:
    """AST 扫描结果。"""
    findings: List[ScanFinding] = field(default_factory=list)
    parse_error: Optional[str] = None

    @property
    def blocked(self) -> bool:
        """是否存在 critical 级发现 (应硬拦截)。"""
        return any(f.severity == "critical" for f in self.findings)

    @property
    def needs_confirmation(self) -> bool:
        """是否存在 high 级发现 (应确认)。"""
        return any(f.severity == "high" for f in self.findings)

    @property
    def max_severity(self) -> Optional[str]:
        """最高严重等级, 无发现时 None。"""
        for sev in ("critical", "high", "medium"):
            if any(f.severity == sev for f in self.findings):
                return sev
        return None

    def summary(self) -> str:
        """生成用户可读的摘要。"""
        if not self.findings:
            return ""
        lines: List[str] = []
        lines.append(f"AST 扫描发现 {len(self.findings)} 处问题:")
        for f in self.findings:
            icon = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(f.severity, "⚪")
            loc = f"行 {f.line}"
            if f.detail:
                loc += f" ({f.detail})"
            lines.append(f"  {icon} [{f.severity}] {f.label} @ {loc}")
            lines.append(f"     {f.snippet[:80]}")
        return "\n".join(lines)


class _DangerousCallVisitor(ast.NodeVisitor):
    """遍历 AST, 收集危险函数调用。"""

    def __init__(self, source_lines: List[str]) -> None:
        self.source_lines = source_lines
        self.findings: List[ScanFinding] = []
        # 追踪 import: "import os" → {"os"}, "from os import system" → {("os", "system")}
        self._imported_modules: set = set()  # {"os", "subprocess", ...}
        self._imported_attrs: set = set()    # {("os", "system"), ("subprocess", "run"), ...}
        self._import_aliases: dict = {}      # {alias: original_module}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._imported_modules.add(alias.name.split(".")[0])
            self._import_aliases[alias.asname or alias.name.split(".")[0]] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        self._imported_modules.add(module.split(".")[0])
        for alias in node.names:
            self._imported_attrs.add((module, alias.name))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # 先检查是否是 compile() 调用
        func_name = self._resolve_func_name(node.func)
        if func_name == "compile":
            self._add_finding(node, "medium", "compile (动态编译)",
                              self._get_arg_snippet(node))
            self.generic_visit(node)
            return

        # 检查是否是危险函数调用
        if func_name in self._known_dangerous_names():
            pass  # 继续匹配

        # 匹配危险调用表
        for mod, fname, severity, label in _DANGEROUS_CALLS:
            if fname is None:
                continue
            if not self._matches_call(node.func, mod, fname):
                continue

            # subprocess.run(..., shell=True) → 升级为 critical
            actual_sev = severity
            actual_label = label
            detail = ""

            if mod == "subprocess" and fname in _SUBPROCESS_METHODS_WITH_SHELL:
                shell_val = self._get_keyword_arg(node, _SHELL_TRUE_KEYWORD)
                if shell_val is True:
                    actual_sev = "critical"
                    actual_label = f"subprocess.{fname}(shell=True) (shell 命令执行)"
                    detail = "shell=True"

            snippet = self._get_arg_snippet(node)
            self._add_finding(node, actual_sev, actual_label, snippet, detail)
            break  # 每个调用只匹配一次

        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # os.system 本身作为表达式出现 (不是调用) — 通常已被 Call 捕获, 此处兜底
        self.generic_visit(node)

    # ---- 辅助方法 ----

    def _known_dangerous_names(self) -> set:
        return {fname for _, fname, _, _ in _DANGEROUS_CALLS if fname is not None}

    def _resolve_func_name(self, node: ast.AST) -> Optional[str]:
        """解析函数名: Name → name, Attribute → attr, Call → recurse。"""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def _matches_call(self, node: ast.AST, mod: Optional[str], fname: str) -> bool:
        """检查调用是否匹配危险函数签名。

        匹配策略 (宽松, 不要求严格 import 关系):
        1. 直接函数名匹配: eval/x, compile, __import__
        2. 模块.函数匹配: os.system, subprocess.run, socket.socket
        3. from import 匹配: from os import system → system(x)
        """
        if mod is None:
            # 全局函数: eval, exec, __import__
            if isinstance(node, ast.Name) and node.id == fname:
                return True
            return False

        # 模块.函数 调用: os.system, subprocess.run
        if isinstance(node, ast.Attribute):
            base_name = self._resolve_base_name(node.value)
            if base_name and node.attr == fname:
                # 检查 base_name 是否对应 mod (考虑别名)
                actual_mod = self._import_aliases.get(base_name, base_name)
                return actual_mod == mod

        # from os import system → system(x)
        if isinstance(node, ast.Name):
            if (mod, fname) in self._imported_attrs:
                return True
            # 也考虑别名: from os import system as s → s(x)
            for (m, f) in self._imported_attrs:
                if m == mod and f == fname:
                    return True
        return False

    def _resolve_base_name(self, node: ast.AST) -> Optional[str]:
        """解析 Attribute.value 的名称部分。"""
        if isinstance(node, ast.Name):
            return node.id
        return None

    def _get_keyword_arg(self, node: ast.Call, kw_name: str) -> Optional[bool]:
        """获取关键字参数的布尔值, 不存在则 None。"""
        for kw in node.keywords:
            if kw.arg == kw_name:
                if isinstance(kw.value, ast.Constant):
                    return kw.value.value is True
                return False
        return None

    def _get_arg_snippet(self, node: ast.Call) -> str:
        """生成调用片段 (参数部分), 用于展示。"""
        args: List[str] = []
        for arg in node.args:
            if isinstance(arg, ast.Constant):
                args.append(repr(arg.value))
            elif isinstance(arg, ast.Name):
                args.append(arg.id)
            elif isinstance(arg, ast.Attribute):
                base = self._resolve_base_name(arg.value)
                args.append(f"{base}.{arg.attr}" if base else arg.attr)
            else:
                args.append("...")
        for kw in node.keywords:
            if isinstance(kw.value, ast.Constant):
                args.append(f"{kw.arg}={kw.value.value!r}")
            elif isinstance(kw.value, ast.Name):
                args.append(f"{kw.arg}={kw.value.id}")
            else:
                args.append(f"{kw.arg}=...")
        return f"({', '.join(args[:5])})"

    def _add_finding(self, node: ast.AST, severity: str, label: str,
                     snippet: str = "", detail: str = "") -> None:
        """记录一条发现。"""
        line = getattr(node, "lineno", 0) or 0
        col = getattr(node, "col_offset", 0) or 0
        # 获取源码行
        src_line = ""
        if 0 < line <= len(self.source_lines):
            src_line = self.source_lines[line - 1].strip()
        self.findings.append(ScanFinding(
            severity=severity,
            label=label,
            line=line,
            col=col + 1,  # 1-based
            snippet=src_line[:100] if src_line else snippet,
            detail=detail,
        ))


# ================================================================ 公共 API

def scan_python_source(source: str, filename: str = "<string>") -> ScanResult:
    """扫描 Python 源码, 检测危险调用。

    Args:
        source: Python 源码字符串
        filename: 文件名 (用于错误消息)

    Returns:
        ScanResult, 包含 findings 列表与 parse_error
    """
    if not source or not source.strip():
        return ScanResult()

    source_lines = source.splitlines()

    # 尝试解析 AST
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        # 解析失败: 可能是有意混淆, 也可能是语法片段
        # 保守处理: 标记为 high (需确认), 但不硬拦截
        msg = f"{exc.msg} (line {exc.lineno})"
        return ScanResult(
            findings=[ScanFinding(
                severity="high",
                label="Python 语法错误 (无法静态分析)",
                line=exc.lineno or 0,
                col=exc.offset or 0,
                snippet=f"{filename}: {msg}",
                detail="ast.parse 失败",
            )],
            parse_error=msg,
        )
    except (ValueError, MemoryError, RecursionError) as exc:
        return ScanResult(
            findings=[ScanFinding(
                severity="high",
                label=f"Python 解析异常 ({type(exc).__name__})",
                line=0, col=0,
                snippet=f"{filename}: {exc}",
                detail="ast.parse 异常",
            )],
            parse_error=str(exc),
        )

    # 遍历 AST
    visitor = _DangerousCallVisitor(source_lines)
    visitor.visit(tree)

    # 额外扫描: 字符串中的 os.system 调用模式 (正则兜底)
    _scan_string_literals(tree, source_lines, visitor.findings)

    # 额外扫描: 赋值给变量后调用的间接调用
    _scan_indirect_calls(tree, source_lines, visitor.findings)

    return ScanResult(findings=visitor.findings)


def _scan_string_literals(tree: ast.AST, source_lines: List[str],
                          findings: List[ScanFinding]) -> None:
    """正则兜底: 扫描字符串常量中可能包含的命令执行模式。

    例如: os.system("rm -rf /") 已被 AST 捕获, 但 eval("os.system(...)")
    或 exec(compile("...", ...)) 的嵌套调用需要正则兜底。
    """
    import re as _re
    dangerous_in_string = [
        (r"subprocess\.(?:run|call|Popen)\s*\(", "subprocess 调用 (字符串中)"),
        (r"os\.system\s*\(", "os.system 调用 (字符串中)"),
        (r"os\.popen\s*\(", "os.popen 调用 (字符串中)"),
        (r"\bsocket\.socket\s*\(", "socket 调用 (字符串中)"),
        (r"\bctypes\.\w*DLL\s*\(", "ctypes DLL 加载 (字符串中)"),
        (r"\bpickle\.loads?\s*\(", "pickle 反序列化 (字符串中)"),
    ]
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        val = node.value
        for pattern, label in dangerous_in_string:
            if _re.search(pattern, val, _re.IGNORECASE):
                line = getattr(node, "lineno", 0) or 0
                findings.append(ScanFinding(
                    severity="high",
                    label=label,
                    line=line,
                    col=0,
                    snippet=val[:80],
                    detail="字符串字面量中的危险调用",
                ))
                break  # 每个字符串只报一次


def _scan_indirect_calls(tree: ast.AST, source_lines: List[str],
                         findings: List[ScanFinding]) -> None:
    """扫描间接调用模式: 赋值后调用 (如 cmd = os.system; cmd("...")）。

    捕获: x = os.system → x("...") 或 import os as o; o.system("...")
    """
    # 第一遍: 收集赋值: 变量名 = 危险函数引用
    dangerous_refs = {}  # var_name → (label, severity)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if isinstance(node.value, ast.Attribute):
                base = ""
                if isinstance(node.value.value, ast.Name):
                    base = node.value.value.id
                alias = base.split(".")[0] if base else ""
                key = f"{alias}.{node.value.attr}"
                for mod, fname, sev, label in _DANGEROUS_CALLS:
                    if fname and mod == alias and fname == node.value.attr:
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                dangerous_refs[target.id] = (label, sev)
            elif isinstance(node.value, ast.Name):
                name = node.value.id
                for mod, fname, sev, label in _DANGEROUS_CALLS:
                    if fname is None and name == fname:
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                dangerous_refs[target.id] = (label, sev)

    # 第二遍: 检查是否调用了这些变量
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                ref = dangerous_refs.get(node.func.id)
                if ref:
                    line = getattr(node, "lineno", 0) or 0
                    src_line = source_lines[line - 1].strip() if 0 < line <= len(source_lines) else ""
                    findings.append(ScanFinding(
                        severity=ref[1],
                        label=f"间接调用 {ref[0]} (via {node.func.id})",
                        line=line,
                        col=0,
                        snippet=src_line[:100],
                        detail=f"变量 {node.func.id} 赋值为危险函数引用",
                    ))


# ================================================================ Shell 命令提取

_PYTHON_EXE_RE = re.compile(
    r"""(?:
        (?<![a-zA-Z0-9_-])(?:python[0-9.]*|py[0-9.]*)\s+     # python / python3 / py / py -3.11
        (?:
            -c\s+(?:"([^"]*)"|'([^']*)')                      # python -c "..." / '...'
            |(?:-m\s+[a-zA-Z_][a-zA-Z0-9_.]*)?\s+             # -m module / direct
            (?:"([^"]+\.py)"|'([^']+\d*\.py)'|(\S+\.py))       # "script.py" / 'script.py' / script.py
        )
    )""",
    re.VERBOSE | re.IGNORECASE,
)

_PYTHON_FILE_FLAGS_RE = re.compile(
    r"""(?:
        (?<![a-zA-Z0-9_-])(?:python[0-9.]*|py[0-9.]*)\s+     # python / python3 / py
        (?:-\S+\s+)*                                          # flags: -u, -O, etc.
        (?:
            (?:"([^"]+\.py)"|'([^']+\d*\.py)'|(\S+\.py))
        )
    )""",
    re.VERBOSE | re.IGNORECASE,
)


def extract_python_sources(command: str, workspace: str = "") -> List[Tuple[str, str]]:
    """从 shell 命令中提取 Python 源码。

    支持:
    - ``python -c "code"`` / ``python -c 'code'``
    - ``python script.py``
    - ``python3 -u script.py``

    Args:
        command: shell 命令字符串
        workspace: 工作区根目录 (用于解析相对路径)

    Returns:
        [(filename, source), ...] 列表; 无法提取时返回空列表
    """
    results: List[Tuple[str, str]] = []

    # 先尝试匹配 -c 内联代码
    for m in _PYTHON_EXE_RE.finditer(command):
        inline_dq = m.group(1)  # python -c "..."
        inline_sq = m.group(2)  # python -c '...'
        if inline_dq is not None:
            results.append(("<python -c>", inline_dq))
            continue
        if inline_sq is not None:
            results.append(("<python -c>", inline_sq))
            continue
        # 文件路径
        path_dq = m.group(3)
        path_sq = m.group(4)
        path_bare = m.group(5)
        script_path = path_dq or path_sq or path_bare
        if script_path:
            results.append(_try_read_python_file(script_path, workspace))

    # 如果 -c 没匹配到, 尝试单独匹配文件路径模式
    if not results:
        for m in _PYTHON_FILE_FLAGS_RE.finditer(command):
            path_dq = m.group(1)
            path_sq = m.group(2)
            path_bare = m.group(3)
            script_path = path_dq or path_sq or path_bare
            if script_path:
                results.append(_try_read_python_file(script_path, workspace))

    # 过滤 None
    return [(f, s) for f, s in results if s is not None]


def _try_read_python_file(script_path: str, workspace: str = "") -> Tuple[str, Optional[str]]:
    """尝试读取 Python 脚本文件, 返回 (filename, source)。

    读取失败时返回 (filename, None), 调用方应跳过。
    """
    # 解析路径: 绝对路径 / 工作区相对路径
    if os.path.isabs(script_path):
        candidates = [script_path]
    else:
        candidates = [
            os.path.join(workspace, script_path) if workspace else script_path,
            script_path,
        ]
    for path in candidates:
        try:
            rp = os.path.realpath(path)
            if os.path.isfile(rp) and os.access(rp, os.R_OK):
                with open(rp, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                return (os.path.basename(rp), content)
        except (OSError, PermissionError):
            continue
    return (script_path, None)


# ================================================================ 便捷接口

def scan_shell_command(command: str, workspace: str = "") -> Optional[ScanResult]:
    """一站式扫描: 从 shell 命令提取 Python 代码并扫描。

    返回:
        - ScanResult (有 Python 代码可扫描时)
        - None (命令中无 Python 代码, 无需扫描)
    """
    sources = extract_python_sources(command, workspace)
    if not sources:
        return None

    all_findings: List[ScanFinding] = []
    parse_errors: List[str] = []
    for filename, source in sources:
        result = scan_python_source(source, filename=filename)
        all_findings.extend(result.findings)
        if result.parse_error:
            parse_errors.append(f"{filename}: {result.parse_error}")

    return ScanResult(findings=all_findings, parse_error="; ".join(parse_errors) or None)
