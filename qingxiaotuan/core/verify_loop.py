"""编码验证闭环 (Verify Loop) —— 对标 Claude Code 的编码验证能力。

设计:
- Agent 每次修改文件后 (write_file / str_replace / run_terminal_command 等写工具),
  可选触发 verify_loop: 自动跑 pytest / mypy / ruff, 失败则把错误信息喂回 Agent 让它自修复;
- 最多循环 MAX_HEAL_ROUNDS 轮, 超过则放弃并报告;
- 所有检查命令可按语言/框架自动推断, 也可由配置覆盖;
- 纯同步实现, 不引入重型依赖 (只用 subprocess).

配置 (config.yaml):
    verify:
      enabled: true           # 开关
      auto: true              # 写工具后自动触发 (需要 agent 主循环配合)
      max_heal_rounds: 3      # 最大自修复轮数
      checks:                 # 可覆盖检查命令 (留空=自动推断)
        test: ""
        typecheck: ""
        lint: ""
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, cast

log = logging.getLogger(__name__)

# 默认最大自修复轮数
MAX_HEAL_ROUNDS = 3

# 写类工具名集合: 这些工具执行后可触发验证闭环 (与 tools/ 实际注册名一致)
WRITE_TOOLS = {
    "write_file", "edit_file", "delete_file", "delete_dir", "move_file",
}

# 工具可用性探测缓存: 项目不变则结果稳定, 避免每轮重复 which/读文件
_tool_cache: Dict[str, bool] = {}


def clear_tool_cache() -> None:
    """清空工具探测缓存 (测试/环境变化时调用)。"""
    _tool_cache.clear()


@dataclass
class VerifyConfig:
    """验证闭环配置。"""
    enabled: bool = True
    auto: bool = True
    max_heal_rounds: int = MAX_HEAL_ROUNDS
    test_cmd: str = ""
    typecheck_cmd: str = ""
    lint_cmd: str = ""

    @classmethod
    def from_dict(cls, cfg: Dict[str, Any]) -> "VerifyConfig":
        v = cfg.get("verify", {})
        checks = v.get("checks", {})
        return cls(
            enabled=v.get("enabled", True),
            auto=v.get("auto", True),
            max_heal_rounds=v.get("max_heal_rounds", MAX_HEAL_ROUNDS),
            test_cmd=checks.get("test", ""),
            typecheck_cmd=checks.get("typecheck", ""),
            lint_cmd=checks.get("lint", ""),
        )


@dataclass
class CheckResult:
    """单个检查的结果。"""
    name: str          # test / typecheck / lint
    cmd: str           # 实际执行的命令
    passed: bool
    output: str        # 标准输出 + 标准错误
    returncode: int = 0
    elapsed: float = 0.0


@dataclass
class VerifyRound:
    """一轮验证 (含多个检查) 的结果。"""
    round_num: int
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> List[CheckResult]:
        return [c for c in self.checks if not c.passed]

    def summary(self) -> str:
        parts = []
        for c in self.checks:
            status = "PASS" if c.passed else "FAIL"
            parts.append(f"  [{status}] {c.name}: {c.cmd}")
            if not c.passed:
                # 截取最后 N 行错误
                tail = c.output.strip().splitlines()[-20:]
                parts.append("    " + "\n    ".join(tail))
        return "\n".join(parts)


@dataclass
class VerifyReport:
    """验证闭环的完整报告。"""
    rounds: List[VerifyRound] = field(default_factory=list)
    healed: bool = False          # 是否通过自修复全部通过
    gave_up: bool = False        # 是否达到轮数上限放弃

    @property
    def total_rounds(self) -> int:
        return len(self.rounds)

    def summary(self) -> str:
        lines = [f"验证闭环: {self.total_rounds} 轮"]
        if self.healed:
            lines.append("  结果: 全部通过 (自修复成功)")
        elif self.gave_up:
            lines.append("  结果: 仍有失败 (已达修复上限)")
        else:
            lines.append("  结果: 首轮即全部通过")
        for rnd in self.rounds:
            lines.append(f"\n--- 第 {rnd.round_num} 轮 ---")
            lines.append(rnd.summary())
        return "\n".join(lines)


def detect_project_type(workspace: str) -> str:
    """检测项目类型: python / node / rust / go / mixed。"""
    ws = Path(workspace)
    indicators = {
        "python": ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt"],
        "node": ["package.json"],
        "rust": ["Cargo.toml"],
        "go": ["go.mod"],
    }
    found = []
    for lang, files in indicators.items():
        for f in files:
            if (ws / f).exists():
                found.append(lang)
                break
    if len(found) == 0:
        return "unknown"
    if len(found) == 1:
        return found[0]
    return "mixed"


def _tool_available(tool: str) -> bool:
    """探测可执行工具 (带缓存)。"""
    if tool not in _tool_cache:
        _tool_cache[tool] = shutil.which(tool) is not None
    return _tool_cache[tool]


def _venv_python(ws: Path) -> Optional[str]:
    """项目 venv 里的 python (Windows Scripts/ 或 POSIX bin/), 优先于裸 python。

    裸 `python` 常是系统解释器, `python -m pytest` 会找不到项目依赖;
    用 venv 解释器才能命中项目内安装的 pytest/mypy/ruff。
    """
    for cand in (
        ws / ".venv" / "Scripts" / "python.exe",
        ws / "venv" / "Scripts" / "python.exe",
        ws / ".venv" / "bin" / "python",
        ws / "venv" / "bin" / "python",
    ):
        if cand.exists():
            return str(cand)
    return None


def _py_available(ws: Path, module: str) -> bool:
    """探测 (venv|系统) python 能否 import 指定模块。"""
    py = _venv_python(ws) or "python"
    key = f"{py}|{module}"
    if key not in _tool_cache:
        try:
            import subprocess
            r = subprocess.run(
                [py, "-c", f"import {module}"],
                capture_output=True, text=True, timeout=15,
            )
            _tool_cache[key] = r.returncode == 0
        except Exception:  # noqa: BLE001
            _tool_cache[key] = False
    return _tool_cache[key]


def _declares_pytest(ws: Path) -> bool:
    """项目是否声明使用 pytest (配置文件或 tests/ 目录)。

    仅有 pyproject.toml 不足以推断: 现代项目几乎都有它, 但可能用 unittest;
    需显式出现 [tool.pytest.ini_options] 或存在 pytest.ini/tox.ini/setup.cfg。
    """
    for f in ("pytest.ini", "tox.ini", "setup.cfg"):
        if (ws / f).exists():
            return True
    if (ws / "tests").is_dir():
        return True
    pyproject = ws / "pyproject.toml"
    if pyproject.exists():
        try:
            if "[tool.pytest.ini_options]" in pyproject.read_text(
                encoding="utf-8", errors="ignore"
            ):
                return True
        except OSError:
            pass
    return False


def infer_check_commands(workspace: str, cfg: VerifyConfig) -> Dict[str, str]:
    """根据项目类型推断检查命令。配置优先, 留空则自动推断。

    推断原则:
    - venv 感知: 项目有 .venv/venv 时用 venv 解释器, 命中项目内工具;
    - 工具可用才推断: mypy/ruff/pytest/cargo/go/npx 不可用绝不硬上,
      避免无工具环境每轮白耗自修复预算;
    - 声明才推断: pytest 需项目声明 (配置文件或 tests/), 防止把
      unittest 项目当 pytest 项目打;
    - mixed 项目取并集, 同类检查不重复。
    """
    lang = detect_project_type(workspace)
    ws = Path(workspace)
    # 仅有 pytest.ini / tests/ 目录的 python 项目检测不到常规指标:
    # 有 pytest 声明时按 python 处理, 否则 pytest-only 项目永远推断不出命令。
    # (仅凭声明判断, 不因"恰好能 import pytest"把未知项目升级为 python)
    if lang == "unknown" and _declares_pytest(ws):
        lang = "python"
    py = _venv_python(ws) or "python"
    checks: Dict[str, str] = {}

    # --- test ---
    if cfg.test_cmd:
        checks["test"] = cfg.test_cmd
    else:
        if lang in ("python", "mixed") and _declares_pytest(ws):
            if _py_available(ws, "pytest"):
                checks["test"] = f"{py} -m pytest -x -q --tb=short"
        if lang in ("node", "mixed") and "test" not in checks:
            pkg = _read_package_json(ws)
            if pkg and "test" in pkg.get("scripts", {}):
                checks["test"] = "npm test --silent"
        if lang in ("rust", "mixed") and "test" not in checks and _tool_available("cargo"):
            checks["test"] = "cargo test --quiet"
        if lang in ("go", "mixed") and "test" not in checks and _tool_available("go"):
            checks["test"] = "go test ./... -count=1"

    # --- typecheck ---
    if cfg.typecheck_cmd:
        checks["typecheck"] = cfg.typecheck_cmd
    else:
        if lang in ("python", "mixed") and _py_available(ws, "mypy"):
            checks["typecheck"] = f"{py} -m mypy --ignore-missing-imports --no-error-summary ."
        if lang in ("node", "mixed") and "typecheck" not in checks:
            if (ws / "tsconfig.json").exists() and _tool_available("npx"):
                checks["typecheck"] = "npx tsc --noEmit"
        if lang in ("rust", "mixed") and "typecheck" not in checks and _tool_available("cargo"):
            checks["typecheck"] = "cargo check --quiet"
        if lang in ("go", "mixed") and "typecheck" not in checks and _tool_available("go"):
            checks["typecheck"] = "go vet ./..."

    # --- lint ---
    if cfg.lint_cmd:
        checks["lint"] = cfg.lint_cmd
    else:
        if lang in ("python", "mixed") and _py_available(ws, "ruff"):
            checks["lint"] = f"{py} -m ruff check --select=E,F,W --quiet ."
        if lang in ("node", "mixed") and "lint" not in checks:
            pkg = _read_package_json(ws)
            if pkg and "lint" in pkg.get("scripts", {}):
                checks["lint"] = "npm run lint --silent"

    return checks


def _read_package_json(ws: Path) -> Optional[Dict[str, Any]]:
    """安全读取 package.json。"""
    pkg_path = ws / "package.json"
    if not pkg_path.exists():
        return None
    try:
        return cast(Dict[str, Any], json.loads(pkg_path.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return None


def run_check(name: str, cmd: str, workspace: str, timeout: float = 120.0,
              kernel=None, confirm=None) -> CheckResult:
    """执行单个检查命令, 返回 CheckResult。

    统一安全层接入: 执行前经 command_guard 裁决 (硬红线 / 网络出口 / 审计),
    拦截时以失败结果返回, 不触碰 subprocess (fail-closed)。
    """
    try:
        from ..core.command_guard import guard_command
        blocked = guard_command(cmd, kernel=kernel, confirm=confirm)
    except Exception as exc:  # noqa: BLE001 - 守卫自身异常按拦截处理
        blocked = f"[已拦截] 命令守卫不可用, 安全降级拒绝: {cmd} ({type(exc).__name__})"
    if blocked:
        return CheckResult(name=name, cmd=cmd, passed=False,
                           output=blocked, returncode=-1)
    import time
    t0 = time.monotonic()
    try:
        from ..core.proc import run_with_tree_kill
        proc = run_with_tree_kill(
            cmd, shell=True, cwd=workspace,
            capture_output=True, text=True, timeout=timeout,
        )
        elapsed = time.monotonic() - t0
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        return CheckResult(
            name=name, cmd=cmd, passed=(proc.returncode == 0),
            output=output.strip(), returncode=proc.returncode, elapsed=elapsed,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - t0
        return CheckResult(
            name=name, cmd=cmd, passed=False,
            output=f"[超时] 命令在 {timeout:.0f}s 内未完成",
            returncode=-1, elapsed=elapsed,
        )
    except Exception as exc:  # noqa: BLE001
        elapsed = time.monotonic() - t0
        return CheckResult(
            name=name, cmd=cmd, passed=False,
            output=f"[错误] {type(exc).__name__}: {exc}",
            returncode=-1, elapsed=elapsed,
        )


def verify_once(workspace: str, cfg: VerifyConfig, kernel=None, confirm=None) -> VerifyRound:
    """执行一轮验证 (test + typecheck + lint), 返回 VerifyRound。"""
    commands = infer_check_commands(workspace, cfg)
    rnd = VerifyRound(round_num=1)
    for name, cmd in commands.items():
        result = run_check(name, cmd, workspace, kernel=kernel, confirm=confirm)
        rnd.checks.append(result)
        log.info("verify %s: %s (%.2fs)", name, "PASS" if result.passed else "FAIL", result.elapsed)
    return rnd


def verify_with_heal(
    workspace: str,
    cfg: VerifyConfig,
    heal_fn: Optional[Callable[[str], str]] = None,
    max_rounds: Optional[int] = None,
    kernel=None,
    confirm=None,
) -> VerifyReport:
    """带自修复的验证闭环。

    Args:
        workspace: 项目根目录
        cfg: 验证配置
        heal_fn: 自修复函数, 接收错误信息文本, 返回修复指令 (返回空串表示放弃)。
                 通常由 Agent 的一次 run() 调用来实现。
        max_rounds: 最大轮数 (覆盖配置)

    Returns:
        VerifyReport: 完整验证报告
    """
    max_r = max_rounds if max_rounds is not None else cfg.max_heal_rounds
    report = VerifyReport()

    for i in range(1, max_r + 1):
        rnd = verify_once(workspace, cfg, kernel=kernel, confirm=confirm)
        rnd.round_num = i
        report.rounds.append(rnd)

        if rnd.all_passed:
            if i == 1:
                pass  # 首轮即通过
            else:
                report.healed = True
            return report

        # 有失败 → 尝试自修复
        if heal_fn is None:
            report.gave_up = True
            return report

        failure_text = "\n\n".join(
            f"=== {c.name} 失败 (exit={c.returncode}) ===\n{c.output}"
            for c in rnd.failures
        )
        try:
            instruction = heal_fn(failure_text)
        except Exception as exc:  # noqa: BLE001
            log.debug("heal_fn 异常: %s", exc)
            report.gave_up = True
            return report

        if not instruction or not instruction.strip():
            report.gave_up = True
            return report

    report.gave_up = True
    return report
