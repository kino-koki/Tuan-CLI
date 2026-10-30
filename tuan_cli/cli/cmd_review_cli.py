"""Claude Code 对齐 CLI 命令面 —— review / security-review / simplify / debug / batch。

对应 docs/GAP-ANALYSIS-vs-ClaudeCode.md A2 节：补齐 CLI 层命令面对齐。

设计要点（保持轻量）:
- 本模块**不构建完整 kernel**（避免拖慢启动），review/simplify 直接复用底层纯逻辑
  （tools.code_review / skills.governance.consolidate），只需构造最小 ToolContext。
- debug 只做环境信息收集，不启动 app 链。
- batch 批量执行一组 slash 命令，依赖 SessionStore 与轻量 agent 句柄。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, List, Optional

from ..config import home_dir
from ..ui.plain_console import console


def _workspace(args: Any) -> str:
    """解析工作区目录。"""
    ws = getattr(args, "workspace", None) or os.getcwd()
    return str(Path(ws).resolve())


def _make_tool_context(workspace: str, kernel: Any = None) -> Any:
    """构造最小 ToolContext（复用 tools.base.ToolContext）。"""
    from ..tools.base import ToolContext
    return ToolContext(kernel=kernel, workspace=workspace)


# ---------------------------------------------------------------- review
def cmd_review(args: Any) -> int:
    """`tuan review [path|files...] [--security] [--json]` —— 自动代码评审。"""
    security = bool(getattr(args, "security", False))
    as_json = bool(getattr(args, "json", False))
    path = getattr(args, "path", "")
    files = getattr(args, "files", "")
    workspace = _workspace(args)

    if security:
        # 安全评审: 只跑 security 类别
        categories = "security"
    else:
        categories = getattr(args, "categories", None) or "security,logic,style,complexity"

    from ..tools.code_review import code_review

    ctx = _make_tool_context(workspace)
    # 当 path 指向单个存在的文件时, 走 files= 路径 (os.walk 不遍历文件)
    if path and Path(workspace, path).is_file():
        files = f"{files},{path}" if files else path
        path = ""
    try:
        result = code_review(ctx, path=path, files=files, categories=categories)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[错误] 评审失败: {exc}")
        return 2

    if as_json:
        # 结构化输出: 重新扫描并收集 issue 对象
        from ..tools.code_review import _get_review_files, _scan_security, _scan_logic, _scan_style, _scan_complexity
        cats = [c.strip() for c in categories.split(",") if c.strip()]
        if files:
            file_list = [Path(workspace, f.strip()) for f in files.split(",") if f.strip()]
            file_list = [f for f in file_list if f.exists() and f.is_file()]
        else:
            file_list = _get_review_files(ctx, path)
        issues = []
        for fpath in file_list:
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = str(fpath.relative_to(Path(workspace)))
            if "security" in cats:
                issues += [{"severity": i.severity, "category": i.category,
                            "file": i.file, "line": i.line, "message": i.message,
                            "suggestion": i.suggestion} for i in _scan_security(content, rel)]
            if "logic" in cats:
                issues += [{"severity": i.severity, "category": i.category,
                            "file": i.file, "line": i.line, "message": i.message,
                            "suggestion": i.suggestion} for i in _scan_logic(content, rel)]
            if "style" in cats:
                issues += [{"severity": i.severity, "category": i.category,
                            "file": i.file, "line": i.line, "message": i.message,
                            "suggestion": i.suggestion} for i in _scan_style(content, rel)]
            if "complexity" in cats:
                issues += [{"severity": i.severity, "category": i.category,
                            "file": i.file, "line": i.line, "message": i.message,
                            "suggestion": i.suggestion} for i in _scan_complexity(content, rel)]
        sys.stdout.write(json.dumps({
            "scope": workspace, "security": security,
            "files": len(file_list), "issues": issues,
            "critical": sum(1 for i in issues if i["severity"] == "critical"),
            "warning": sum(1 for i in issues if i["severity"] == "warning"),
            "info": sum(1 for i in issues if i["severity"] == "info"),
        }, ensure_ascii=False, indent=2) + "\n")
        return 1 if any(i["severity"] == "critical" for i in issues) else 0

    console.print(result)
    return 0


def cmd_security_review(args: Any) -> int:
    """`tuan security-review [path]` —— 仅安全扫描的评审。"""
    return cmd_review(args)


# ---------------------------------------------------------------- simplify
def cmd_simplify(args: Any) -> int:
    """`tuan simplify [--dry-run|--apply] [--threshold 0.7]` —— 简化冗余技能。"""
    workspace = _workspace(args)
    apply_merge = bool(getattr(args, "apply", False))
    threshold = float(getattr(args, "threshold", 0.7))
    dry_run = not apply_merge

    try:
        from ..skills.manager import SkillManager
        from ..skills.governance import consolidate

        home = home_dir()
        manager = SkillManager(home, workspace=Path(workspace))
        proposals = consolidate(manager, dry_run=dry_run, threshold=threshold)
        if not proposals:
            console.print("[简化] 未发现可合并的冗余技能 (dry-run)。" if dry_run
                          else "[简化] 未发现可合并的冗余技能。")
            return 0
        for pr in proposals:
            console.print(
                f"  相似度 {pr.score}: 保留 {pr.keeper.slug} "
                f"{'<- 并入 ' + pr.loser.slug if pr.writable else '(只读, 仅报告)'}"
            )
        if dry_run:
            console.print(f"\n[简化] dry-run 共 {len(proposals)} 组。加 --apply 实际合并。")
        else:
            console.print(f"\n[简化] 已合并 {len(proposals)} 组。")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[错误] 简化失败: {exc}")
        return 2
    return 0


# ---------------------------------------------------------------- debug
def cmd_debug(args: Any) -> int:
    """`tuan debug` —— 环境/配置/运行时诊断摘要。"""
    from .. import __version__
    console.print(f"tuan {__version__} 调试诊断")
    console.print("=" * 40)
    console.print(f"  python: {sys.version.split()[0]} ({sys.executable})")
    console.print(f"  cwd:    {os.getcwd()}")
    console.print(f"  home:   {home_dir()}")
    try:
        from ..config import Config
        cfg = Config()
        console.print(f"  provider: {cfg.get('model.provider', '?')}")
        console.print(f"  model:    {cfg.get('model.model', '?')}")
        console.print(f"  mode:     {cfg.get('mode.default', '?')}")
        console.print(f"  effort:   {cfg.get('agent.effort', '?')}")
    except Exception as exc:  # noqa: BLE001
        console.print(f"  config:   (不可用: {exc})")
    # 关键环境变量
    for env in ("TUAN_PROVIDER", "TUAN_MODEL", "TUAN_WORKSPACE",
                "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY"):
        if os.environ.get(env):
            val = os.environ[env]
            if "KEY" in env:
                val = f"<已设置, {len(val)} 字符>"
            console.print(f"  env {env}: {val}")
    return 0


# ---------------------------------------------------------------- auto-mode
def cmd_auto_mode(args: Any) -> int:
    """`tuan auto-mode [list|test <tool> <json>]` —— Auto 模式分类器。

    - list (默认): 展示工具风险基线与三级权限 (auto/normal/yolo);
    - test <tool> <json>: 评估单次调用的自动批准决策 (纯规则, 不调 LLM)。
    """
    from ..core.auto_mode import AutoModeClassifier, TOOL_BASELINE_RISK, RiskLevel

    action = getattr(args, "action", "list") or "list"
    classifier = AutoModeClassifier(None)

    if action == "test":
        tool = getattr(args, "tool", "") or ""
        args_raw = getattr(args, "args", "{}") or "{}"
        if not tool:
            console.print("[错误] 用法: tuan auto-mode test <tool> '<json>'" )
            return 2
        try:
            call_args = json.loads(args_raw) if args_raw.strip().startswith("{") else {"query": args_raw}
            if not isinstance(call_args, dict):
                raise ValueError("参数必须是 JSON 对象")
        except Exception as exc:  # noqa: BLE001
            example = 'tuan auto-mode test Bash \'{"command":"git status"}\''
            console.print(f"[错误] 参数解析失败: {exc} (示例: {example})")
            return 2
        a = classifier.assess(tool, call_args)
        level_name = RiskLevel(a.level).name if isinstance(a.level, int) else str(a.level)
        console.print(f"  test 调用: {tool}({json.dumps(call_args, ensure_ascii=False)})")
        console.print(f"  风险等级: {level_name}")
        console.print(f"  决策: {'自动批准' if a.auto_approve else ('需要确认' if a.needs_confirm else '未命中')}")
        console.print(f"  理由: {a.reason}")
        console.print(f"  规则来源: {a.rule_source}")
        return 0

    # list 默认
    console.print("Auto 模式分类器 (对标 Claude Code auto-mode): 纯规则 + 风险评分, 不依赖 LLM。")
    console.print("  三级权限: auto (自动批准低风险) / normal (需确认) / yolo (跳过确认)")
    console.print("  工具风险基线:")
    for tool, risk in sorted(TOOL_BASELINE_RISK.items(), key=lambda x: x[1]):
        console.print(f"    {RiskLevel(risk).name:<9} {tool}")
    console.print("")
    console.print("  示例: tuan auto-mode test Bash '{\"command\":\"git status\"}'  → 评估单次调用")
    return 0


# ---------------------------------------------------------------- batch
def cmd_batch(args: Any) -> int:
    """`tuan batch <file|commands...>` —— 批量执行一组 slash 命令。

    读取命令文件（每行一条）或从 argv 取逗号分隔列表，逐条执行。
    仅执行**本地安全**的 slash 命令（read-only / 配置 / 会话管理），
    不执行可能修改工作区文件的危险命令，防止误用。
    """
    items: List[str] = []
    raw = getattr(args, "commands", None)
    if raw:
        items = [x.strip() for x in raw if x.strip()]
    else:
        batch_file = getattr(args, "file", None)
        if batch_file and Path(batch_file).exists():
            items = [ln.strip() for ln in Path(batch_file).read_text(encoding="utf-8").splitlines()
                     if ln.strip() and not ln.strip().startswith("#")]
        else:
            console.print("[错误] 用法: tuan batch <命令1> [命令2 ...] | tuan batch --file commands.txt")
            return 2

    # 只允许批量执行只读/配置类命令
    _ALLOWED_PREFIXES = (
        "/help", "/commands", "/status", "/stats", "/memory", "/model",
        "/provider", "/permissions", "/config", "/theme", "/color", "/version",
        "/session", "/doctor", "/review", "/code-review", "/security-review",
        "/debug", "/simplify", "/branch", "/tasks", "/bg", "/background",
    )
    skipped = []
    for cmd in items:
        head = cmd.split()[0].lower() if cmd.split() else ""
        if not head.startswith("/") or not any(head == a or head.startswith(a + " ") or head == a
                                                for a in _ALLOWED_PREFIXES):
            # 前缀匹配: 允许带参数的只读命令
            if not any(head.split("/")[0] == a.split("/")[0] for a in _ALLOWED_PREFIXES if a.startswith(head[:4])):
                skipped.append(cmd)
                continue
        console.print(f"$ {cmd}")
        # 逐条注入到会话执行（这里仅打印，实际由 REPL 层批处理）
        console.print(f"  (交由 REPL 批处理: {cmd})")
    if skipped:
        console.print(f"\n[批量] 跳过 {len(skipped)} 条非安全命令: {skipped}")
    console.print(f"\n[批量] 共 {len(items)} 条，跳过 {len(skipped)} 条。")
    return 0
