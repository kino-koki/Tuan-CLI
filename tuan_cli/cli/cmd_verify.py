"""`tuan verify` —— 验证工具发现与反思诊断 (第 48 个独特功能)。

Claude Code 的验证 (/test, /checkpoint) 是黑盒: 你不知道它跑了什么工具、每个
工具的结果、失败原因。Tuan-CLI 的 Verifier/Reflector (core/reflector.py) 把
验证做成结构化: 检测可用工具 → 运行 → 提取关键错误 → 自动诊断 → 决策
(继续/修正/降级/请求帮助)。本命令把这套验证体系暴露为可观测视图:

    tuan verify detect                # 检测工作区可用的验证工具 (只读)
    tuan verify run <tool>            # 运行单个验证工具 (pytest/ruff/mypy/...)
    tuan verify all                   # 运行全部可用验证工具
    tuan verify all --tools a,b       # 运行指定工具 (逗号分隔)
    tuan verify reflect <task>        # 反思诊断: 运行验证并给出决策建议
    tuan verify detect --json         # 机器可读 (CI 门禁)

差异化价值:
- 工具发现透明化: detect 列出工作区能跑哪些验证 (Claude Code 隐藏此信息)。
- 结构化结果: 每个验证返回 passed/exit_code/duration/error_summary。
- 失败诊断: reflect 用验证输出提取关键错误, 给出修正/降级建议。
- 安全: 验证命令经 command_guard 硬红线拦截 (core/reflector.py 已接入)。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import home_dir
from ..ui.plain_console import console


def _workspace(args: Any) -> str:
    w = getattr(args, "workspace", None) or getattr(args, "cwd", None) or ""
    if w:
        return str(Path(w).resolve())
    return str(Path.cwd().resolve())


def _verification_dict(v: Any) -> Dict[str, Any]:
    return {
        "name": v.name,
        "passed": v.passed,
        "exit_code": v.exit_code,
        "duration_sec": v.duration,
        "error_summary": v.error_summary,
        "output": v.output,
    }


def _cmd_verify_detect(args: Any, json_mode: bool) -> int:
    """verify detect: 检测工作区可用的验证工具 (只读)。"""
    from ..core.reflector import Verifier

    ws = _workspace(args)
    verifier = Verifier(ws)
    tools = verifier.detect_available()
    if json_mode:
        sys.stdout.write(json.dumps({
            "workspace": ws,
            "available": tools,
            "count": len(tools),
        }, ensure_ascii=False, indent=2) + "\n")
        return 0
    if not tools:
        console.print(f"[dim]工作区 {ws} 未检测到可用验证工具 (需 pyproject.toml/tests/package.json 等)[/dim]")
        return 0
    console.print(f"[bold]可用验证工具[/bold] ({ws}):")
    for t in tools:
        console.print(f"  [green]{t}[/green]")
    console.print("\n提示: tuan verify run <tool> 运行单个; tuan verify all 运行全部")
    return 0


def _cmd_verify_run(args: Any, json_mode: bool) -> int:
    """verify run: 运行单个验证工具 (实际执行)。"""
    from ..core.reflector import Verifier

    tool = getattr(args, "tool", "") or ""
    if not tool:
        console.print("[dim]请指定验证工具: tuan verify run <tool>[/dim]")
        return 1
    ws = _workspace(args)
    verifier = Verifier(ws)
    result = verifier.run_verification(tool)
    if json_mode:
        sys.stdout.write(json.dumps(_verification_dict(result), ensure_ascii=False, indent=2) + "\n")
        return 0 if result.passed else 1
    color = "green" if result.passed else "red"
    icon = "✓" if result.passed else "✗"
    console.print(f"[{color}]{icon} {result.name}[/{color}]  "
                  f"exit={result.exit_code}  {result.duration:.1f}s")
    if result.error_summary:
        console.print(f"[red]{result.error_summary}[/red]")
    if result.output and not result.passed:
        console.print(f"[dim]{result.output[:600]}{'…' if len(result.output) > 600 else ''}[/dim]")
    return 0 if result.passed else 1


def _cmd_verify_all(args: Any, json_mode: bool) -> int:
    """verify all: 运行全部/指定验证工具。"""
    from ..core.reflector import Verifier

    ws = _workspace(args)
    verifier = Verifier(ws)
    tools_arg = getattr(args, "tools", None)
    tools: Optional[List[str]] = None
    if tools_arg:
        tools = [t.strip() for t in tools_arg.split(",") if t.strip()]
    results = verifier.run_all(tools)
    passed = sum(1 for r in results if r.passed)
    if json_mode:
        sys.stdout.write(json.dumps({
            "workspace": ws,
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "results": [_verification_dict(r) for r in results],
        }, ensure_ascii=False, indent=2) + "\n")
        return 0 if passed == len(results) else 1
    console.print(f"[bold]验证结果[/bold] ({ws}): {passed}/{len(results)} 通过")
    for r in results:
        color = "green" if r.passed else "red"
        icon = "✓" if r.passed else "✗"
        console.print(f"  [{color}]{icon} {r.name:<12}[/{color}] exit={r.exit_code} {r.duration:.1f}s")
        if r.error_summary and not r.passed:
            console.print(f"    [red]{r.error_summary[:160]}[/red]")
    if passed != len(results):
        console.print("\n[red]存在失败的验证, 反思: tuan verify reflect <task>[/red]")
        return 1
    return 0


def _cmd_verify_reflect(args: Any, json_mode: bool) -> int:
    """verify reflect: 反思诊断 (运行验证 → 自动诊断 → 决策建议)。"""
    from ..core.reflector import Reflector

    task = getattr(args, "task", "") or ""
    if not task.strip():
        console.print("[dim]请提供任务描述: tuan verify reflect <task>[/dim]")
        return 1
    ws = _workspace(args)
    last_output = getattr(args, "last_output", "") or ""
    reflector = Reflector(ws)
    result = reflector.reflect(task, last_output=last_output)

    # --prompt: 生成可注入反思提示词 (第 66 个独特功能) --
    # 暴露 build_reflection_prompt(): reflect() 只给「诊断+建议」, 本命令把
    # 诊断结果拼成下一轮可注入 Agent 的反思提示词文本 —— 用户可把这段文本
    # 作为后续 /chat 的注入上下文, 实现「验证失败 → 反思 → 修正」闭环。
    # Claude Code 无此能力 (失败只报错, 不给下一轮自我修正提示)。
    if getattr(args, "prompt", False):
        prompt_text = reflector.build_reflection_prompt(task, result, last_output)
        if json_mode:
            sys.stdout.write(json.dumps({
                "reflection_prompt": prompt_text,
                "task": task,
                "decision": result.decision.value if hasattr(result.decision, "value") else str(result.decision),
            }, ensure_ascii=False, indent=2) + "\n")
            return 0
        console.print("[bold]可注入反思提示词[/bold] (供下一轮 Agent 思考)")
        console.print("  [dim]--- 复制以下文本作为 /chat 上下文注入 ---[/dim]")
        console.print(prompt_text)
        return 0

    if json_mode:
        sys.stdout.write(json.dumps({
            "workspace": ws,
            "decision": result.decision.value if hasattr(result.decision, "value") else str(result.decision),
            "diagnosis": result.diagnosis,
            "suggested_fix": result.suggested_fix,
            "failure_count": result.failure_count,
            "degraded_task": result.degraded_task,
            "summary": result.summary,
            "verifications": [_verification_dict(v) for v in result.verifications],
        }, ensure_ascii=False, indent=2) + "\n")
        return 0
    console.print(f"[bold]反思诊断[/bold] (任务: {task[:60]})")
    console.print(f"  决策: [cyan]{result.decision.value if hasattr(result.decision, 'value') else result.decision}[/cyan]"
                  f"  连续失败: {result.failure_count}")
    if result.diagnosis:
        console.print(f"  诊断: {result.diagnosis}")
    if result.suggested_fix:
        console.print(f"  建议修正: {result.suggested_fix}")
    if result.degraded_task:
        console.print(f"  降级任务: {result.degraded_task}")
    if result.verifications:
        console.print(f"\n  验证 ({len(result.verifications)}):")
        for v in result.verifications:
            color = "green" if v.passed else "red"
            console.print(f"    [{color}]{'✓' if v.passed else '✗'} {v.name}[/{color}] "
                          f"exit={v.exit_code} {v.duration:.1f}s")
            if v.error_summary and not v.passed:
                console.print(f"      [red]{v.error_summary[:120]}[/red]")
    if result.summary:
        console.print(f"\n  总结: {result.summary}")
    return 0


def cmd_verify(args: Any) -> int:
    """`tuan verify` 入口: 验证工具发现与反思诊断。"""
    sub = getattr(args, "verify_cmd", None) or "detect"
    json_mode = bool(getattr(args, "json", False))

    if sub == "run":
        return _cmd_verify_run(args, json_mode)
    if sub == "all":
        return _cmd_verify_all(args, json_mode)
    if sub == "reflect":
        return _cmd_verify_reflect(args, json_mode)
    # 默认 detect
    return _cmd_verify_detect(args, json_mode)


# 注册本模块的命令函数到全局注册表
from .parser import _register_command  # noqa: E402

_register_command("cmd_verify", ".cmd_verify")
