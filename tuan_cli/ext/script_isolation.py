"""脚本执行隔离 (script isolation) —— 模型写入的可执行文件默认进沙箱隔离运行。

设计原则:
- 复用现有 sandbox 基础设施 (SandboxManager.execute_isolated)
- 在 shell.py 执行路径中插入隔离选路
- 脚本类型检测: .py / .sh / .ps1 / .bat / .cmd
- 隔离策略: AST 扫描发现 high 级调用 → 强制隔离执行; critical → 拦截

配置:
- sandbox.auto_isolate_scripts: bool (默认 true)
  启用后，模型写入的脚本文件执行时自动进沙箱隔离
- sandbox.isolation_timeout: float (默认 60.0)
  隔离执行的超时时间 (秒)

与现有安全架构的关系:
- AST 扫描 (ext/ast_scan.py): 检测脚本内容中的危险调用
- 沙箱隔离 (sandbox/manager.py): 提供隔离执行后端
- 本模块: 连接两者，实现"模型脚本默认隔离"策略
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, Optional, Tuple

from ..ext.ast_scan import ScanResult, scan_python_source

log = logging.getLogger(__name__)

# 可执行脚本扩展名
_SCRIPT_EXTENSIONS = frozenset({".py", ".pyw", ".sh", ".bash", ".ps1", ".bat", ".cmd", ".psm1", ".psd1"})

# Shell 命令中提取脚本文件的正则
_SCRIPT_COMMAND_RE = re.compile(
    r"""(?:
        # Python
        (?:python[0-9.]*|py[0-9.]*)\s+
        (?:
            -c\s+(?:"[^"]*"|'[^']*')
            |(?:-\S+\s+)*
            (?:"([^"]+\.(?:py|pyw))" | '([^']+\.(?:py|pyw))' | (\S+\.(?:py|pyw)))
        )
        # Shell
        |(?:(?:bash|zsh|sh)\s+(?:-\S+\s+)*\s*(?:"([^"]+\.(?:sh|bash))" | '([^']+\.(?:sh|bash))' | (\S+\.(?:sh|bash))))
        # PowerShell
        |(?:powershell|pwsh|powershell\.exe)\s+(?:-\S+\s+)*\s*(?:(?:-File|-f)\s+)?(?:"([^"]+\.(?:ps1|psm1|psd1))" | '([^']+\.(?:ps1|psm1|psd1))' | (\S+\.(?:ps1|psm1|psd1)))
        # Batch
        |(?:cmd\.exe\s+/[Cc]\s+|cmd\s+/[Cc]\s+)?(?:\s+)*(?:"([^"]+\.(?:bat|cmd))" | '([^']+\.(?:bat|cmd))' | (\S+\.(?:bat|cmd)))
    )""",
    re.VERBOSE | re.IGNORECASE,
)


def is_script_file(path: str) -> bool:
    """判断路径是否为可执行脚本文件。"""
    if not path:
        return False
    ext = os.path.splitext(path)[1].lower()
    return ext in _SCRIPT_EXTENSIONS


def extract_script_path(command: str, workspace: str = "") -> Optional[str]:
    """从 shell 命令中提取脚本文件路径。

    支持:
    - python script.py / python3 script.py
    - bash script.sh / sh script.sh
    - powershell -File script.ps1 / pwsh script.ps1
    - script.bat / script.cmd

    Returns:
        脚本文件路径 (已解析为绝对路径或工作区相对路径), 未检测到返回 None
    """
    if not command:
        return None

    m = _SCRIPT_COMMAND_RE.search(command)
    if not m:
        return None

    # 收集所有可能的路径组
    groups = m.groups()
    script_path = None
    for g in groups:
        if g:
            script_path = g.strip()
            break

    if not script_path:
        return None

    # 解析路径
    if os.path.isabs(script_path):
        return script_path

    # 工作区相对路径
    if workspace:
        return os.path.join(workspace, script_path)

    return script_path


def resolve_script_path(path: str, workspace: str = "") -> Optional[str]:
    """将脚本路径解析为实际文件路径。

    尝试多个候选路径:
    1. 绝对路径
    2. 工作区相对路径
    3. 当前工作目录相对路径

    Returns:
        解析后的文件路径, 不存在返回 None
    """
    if not path:
        return None

    candidates = []

    if os.path.isabs(path):
        candidates.append(path)
    else:
        if workspace:
            candidates.append(os.path.join(workspace, path))
        candidates.append(path)

    for candidate in candidates:
        try:
            rp = os.path.realpath(candidate)
            if os.path.isfile(rp) and os.access(rp, os.R_OK):
                return rp
        except (OSError, PermissionError):
            continue

    return None


def scan_script_for_isolation(script_path: str) -> Tuple[bool, Optional[ScanResult], str]:
    """扫描脚本文件，判断是否需要隔离执行。

    Args:
        script_path: 脚本文件绝对路径

    Returns:
        (should_isolate, scan_result, error_msg):
        - should_isolate: True 表示需要隔离执行
        - scan_result: AST 扫描结果 (Python 脚本), 非 Python 返回 None
        - error_msg: 错误消息 (无错误时为空字符串)
    """
    if not script_path:
        return False, None, ""

    ext = os.path.splitext(script_path)[1].lower()

    # 仅对 Python 脚本做 AST 扫描
    if ext not in (".py", ".pyw"):
        # 非 Python 脚本: 基于扩展名和路径启发式判断
        return _heuristic_isolation(script_path, ext), None, ""

    # Python 脚本: AST 扫描
    try:
        with open(script_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except (OSError, PermissionError) as exc:
        return False, None, f"读取失败: {exc}"

    if not content or not content.strip():
        return False, None, ""

    result = scan_python_source(content, filename=os.path.basename(script_path))

    # 判断是否需要隔离:
    # - critical: 需要隔离执行 (即使 shell.py 已拦截, 此处也标记以备直接调用)
    # - high: 需要隔离执行 (而非仅确认)
    # - medium/none: 不需要隔离
    should_isolate = result.blocked or result.needs_confirmation

    return should_isolate, result, ""


def _heuristic_isolation(script_path: str, ext: str) -> bool:
    """基于启发式规则判断非 Python 脚本是否需要隔离。

    规则:
    - .ps1/.psm1: PowerShell 脚本默认隔离 (功能强大, 风险高)
    - .sh/.bash: 仅当包含 rm/mkfs/dd 等危险命令时隔离
    - .bat/.cmd: 仅当包含 del/rmdir 等危险命令时隔离
    """
    try:
        with open(script_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(8192)  # 只读前 8KB
    except (OSError, PermissionError):
        return False

    # PowerShell: 默认隔离
    if ext in (".ps1", ".psm1", ".psd1"):
        return True

    # Shell/Batch: 检查危险命令
    dangerous_patterns = [
        r"\brm\s+-rf?\s+/",
        r"\brm\s+-rf?\s+~",
        r"\bmkfs\b",
        r"\bdd\b.*\bof=/dev/",
        r"\bshutdown\b",
        r"\bformat\s+[a-zA-Z]:",
        r"\bdiskpart\b",
        r"\bdel\s+/[Ss][Qq]",
        r"\brmdir\s+/[Ss]",
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return True

    return False


def format_isolation_summary(script_path: str, scan_result: ScanResult,
                             should_isolate: bool) -> str:
    """生成隔离执行的用户可读摘要。"""
    basename = os.path.basename(script_path) if script_path else "<unknown>"
    lines = []

    if should_isolate:
        lines.append(f"⚠️ 脚本 {basename} 将被隔离执行")
        if scan_result and scan_result.findings:
            lines.append(f"   AST 扫描发现 {len(scan_result.findings)} 处问题:")
            for f in scan_result.findings[:5]:
                icon = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(f.severity, "⚪")
                lines.append(f"   {icon} [{f.severity}] {f.label} @ 行 {f.line}")
            if len(scan_result.findings) > 5:
                lines.append(f"   ... 还有 {len(scan_result.findings) - 5} 处")
    else:
        lines.append(f"脚本 {basename} 无危险调用, 直接执行")

    return "\n".join(lines)


# ------------------------------------------------------------------ 沙箱集成

def get_sandbox_manager(ctx: Any) -> Optional[Any]:
    """从上下文获取 SandboxManager 实例。"""
    try:
        if ctx is None:
            return None
        kernel = getattr(ctx, "kernel", None)
        if kernel is None:
            return None
        return kernel.get("sandbox_manager")
    except Exception:
        return None


def should_auto_isolate(ctx: Any) -> bool:
    """检查是否启用脚本自动隔离。"""
    try:
        if ctx is None:
            return False
        kernel = getattr(ctx, "kernel", None)
        if kernel is None:
            return False
        config = getattr(kernel, "config", None)
        if config is None:
            return False
        # 默认启用
        return bool(config.get("sandbox.auto_isolate_scripts", True))
    except Exception:
        return True  # 默认启用


def get_isolation_timeout(ctx: Any) -> float:
    """获取隔离执行超时时间 (秒)。"""
    try:
        if ctx is None:
            return 60.0
        kernel = getattr(ctx, "kernel", None)
        if kernel is None:
            return 60.0
        config = getattr(kernel, "config", None)
        if config is None:
            return 60.0
        return float(config.get("sandbox.isolation_timeout", 60.0))
    except Exception:
        return 60.0


def check_script_isolation(command: str, ctx: Any) -> Optional[Dict[str, Any]]:
    """检查命令是否需要脚本隔离执行。

    在 shell.py 的安全检查链中调用 (AST 扫描之后、执行之前)。

    Args:
        command: shell 命令
        ctx: 工具执行上下文

    Returns:
        需要隔离时返回决策字典:
        {
            "isolate": True,
            "script_path": "...",
            "summary": "...",
            "timeout": 60.0,
        }
        不需要隔离或无法判断时返回 None
    """
    if not command:
        return None

    # 检查是否启用自动隔离
    if not should_auto_isolate(ctx):
        return None

    workspace = getattr(ctx, "workspace", "") or ""

    # 提取脚本路径
    script_path = extract_script_path(command, workspace)
    if not script_path:
        return None

    # 解析为实际文件路径
    resolved = resolve_script_path(script_path, workspace)
    if not resolved:
        return None

    # 扫描脚本
    should_isolate, scan_result, error = scan_script_for_isolation(resolved)

    if error:
        log.debug("脚本扫描错误: %s", error)
        return None

    if not should_isolate:
        return None

    assert scan_result is not None  # should_isolate=True 时必有扫描结果
    # 生成摘要
    summary = format_isolation_summary(resolved, scan_result, True)
    timeout = get_isolation_timeout(ctx)

    return {
        "isolate": True,
        "script_path": resolved,
        "summary": summary,
        "timeout": timeout,
    }
