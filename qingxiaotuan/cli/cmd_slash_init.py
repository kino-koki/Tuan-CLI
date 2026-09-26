"""/init 项目引导 —— 对标 Claude Code 的 /init。

扫描当前工作区, 检测项目类型 (语言 / 框架 / 测试框架 / 包管理器), 生成
``QXT.md`` 项目规则文件 (项目概述 / 技术栈 / 常用命令 / 测试命令 / 构建命令 /
目录结构), 供后续会话中的 Agent 快速上手。

已存在 QXT.md 时默认不覆盖 (显式 force 或交互确认后才覆盖)。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

QXT_MD_NAME = "QXT.md"

# 检测时跳过的目录 (依赖/产物/隐藏目录)
_SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest-tmp",
    ".mypy_cache", ".ruff_cache", ".qxt", ".idea", ".vscode", "dist", "build",
    ".egg-info", "node_modules", ".next", ".cache",
}


def _read_text_safe(path: Path, limit: int = 200_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]
    except Exception:  # noqa: BLE001
        return ""


def detect_project(workspace: Path) -> Dict[str, Any]:
    """扫描工作区, 返回项目元信息 (纯只读, 不写盘)。"""
    ws = Path(workspace)
    info: Dict[str, Any] = {
        "name": ws.name or "project",
        "languages": [],
        "package_manager": "",
        "test_framework": "",
        "frameworks": [],
        "run_cmd": "",
        "test_cmd": "",
        "build_cmd": "",
        "top_entries": [],
        "top_dirs": set(),
    }

    # ---- 顶层结构 ----
    try:
        entries = sorted(p.name for p in ws.iterdir() if p.name not in _SKIP_DIRS)
        info["top_dirs"] = {p.name for p in ws.iterdir()
                            if p.name not in _SKIP_DIRS and p.is_dir()}
    except Exception:  # noqa: BLE001
        entries = []
    info["top_entries"] = entries

    has = lambda name: (ws / name).exists()  # noqa: E731

    # ---- Python ----
    py_markers = ["pyproject.toml", "setup.py", "setup.cfg"]
    has_py = any(has(m) for m in py_markers)
    if not has_py:
        # 工作区根或下一层有 .py 即视为 Python 项目
        try:
            has_py = any(p.suffix == ".py" for p in ws.iterdir())
        except Exception:  # noqa: BLE001
            has_py = False
    if not has_py:
        for sub in entries:
            subdir = ws / sub
            if subdir.is_dir():
                try:
                    if any(p.suffix == ".py" for p in subdir.iterdir()):
                        has_py = True
                        break
                except Exception:  # noqa: BLE001
                    pass
    if has_py:
        info["languages"].append("python")

    # ---- 包管理器 (Python) ----
    if has("poetry.lock"):
        info["package_manager"] = "poetry"
    elif has("uv.lock"):
        info["package_manager"] = "uv"
    elif any(has(m) for m in ("requirements.txt", "requirements-dev.txt",
                              "pyproject.toml", "setup.py")):
        info["package_manager"] = "pip"

    # ---- Node ----
    pkg_json: Dict[str, Any] = {}
    if has("package.json"):
        info["languages"].append("javascript")
        info["package_manager"] = "npm"
        try:
            pkg_json = json.loads(_read_text_safe(ws / "package.json"))
            info["name"] = str(pkg_json.get("name") or info["name"])
        except Exception:  # noqa: BLE001
            pkg_json = {}

    # ---- Go / Rust ----
    if has("go.mod"):
        info["languages"].append("go")
    if has("Cargo.toml"):
        info["languages"].append("rust")

    # ---- 测试框架 ----
    pyproject_txt = _read_text_safe(ws / "pyproject.toml") if has("pyproject.toml") else ""
    req_txt = ""
    for req_name in ("requirements.txt", "requirements-dev.txt", "requirements-test.txt"):
        if has(req_name):
            req_txt += _read_text_safe(ws / req_name)
    tests_dir = has("tests") or has("test")
    if "python" in info["languages"]:
        if has("pytest.ini") or tests_dir or "[tool.pytest" in pyproject_txt or "pytest" in req_txt:
            info["test_framework"] = "pytest"
        elif has("unittest"):
            info["test_framework"] = "unittest"
    if pkg_json:
        scripts = pkg_json.get("scripts") or {}
        if "test" in scripts:
            info["test_framework"] = info["test_framework"] or "jest"
            info["test_cmd"] = "npm test"
    if has("go.mod"):
        info["test_framework"] = "go test"

    # ---- 应用框架 ----
    if "python" in info["languages"]:
        blob = pyproject_txt + "\n" + req_txt
        for fw, mark in (("Flask", "flask"), ("Django", "django"),
                         ("FastAPI", "fastapi"), ("Streamlit", "streamlit")):
            if mark in blob.lower():
                info["frameworks"].append(fw)
    if pkg_json:
        deps = {**(pkg_json.get("dependencies") or {}),
                **(pkg_json.get("devDependencies") or {})}
        for fw in ("react", "vue", "express", "next"):
            if fw in deps:
                info["frameworks"].append(fw.capitalize() if fw != "next" else "Next.js")

    # ---- 常用/测试/构建命令 ----
    if "python" in info["languages"]:
        if info["package_manager"] == "poetry":
            info["run_cmd"] = "poetry run python -m <package>"
        elif info["package_manager"] == "uv":
            info["run_cmd"] = "uv run python -m <package>"
        else:
            info["run_cmd"] = "python -m <package>"
        if not info["test_cmd"]:
            info["test_cmd"] = ("python -m pytest tests/ -q" if tests_dir
                                else "python -m pytest -q")
        info["build_cmd"] = "python -m build"
    elif pkg_json:
        scripts = pkg_json.get("scripts") or {}
        if not info["run_cmd"] and "start" in scripts:
            info["run_cmd"] = "npm start"
        if "build" in scripts:
            info["build_cmd"] = "npm run build"
    elif has("Cargo.toml"):
        info["run_cmd"] = "cargo run"
        info["test_cmd"] = info["test_cmd"] or "cargo test"
        info["build_cmd"] = "cargo build --release"
    elif has("go.mod"):
        info["run_cmd"] = "go run ."
        info["build_cmd"] = "go build -o ./bin/app ."

    return info


def render_qxt_md(info: Dict[str, Any]) -> str:
    """把检测结果渲染成 QXT.md 正文。"""
    langs = "、".join(info["languages"]) or "未识别"
    pkm = info["package_manager"] or "未检测到"
    tfw = info["test_framework"] or "未检测到"
    fws = "、".join(info["frameworks"]) or "未检测到"

    lines: List[str] = []
    lines.append(f"# QXT.md — 青小团项目规则: {info['name']}")
    lines.append("")
    lines.append("> 本文件由 `/init` 自动生成, 描述项目概况与常用命令, 供 Agent 快速上手。")
    lines.append("> 可随时手动编辑; 再次运行 `/init` 会在确认后整体覆盖。")
    lines.append("")
    lines.append("## 项目概述")
    lines.append(f"- 项目名: {info['name']}")
    lines.append(f"- 主语言: {langs}")
    lines.append(f"- 包管理器: {pkm}")
    lines.append(f"- 应用框架: {fws}")
    lines.append("")
    lines.append("## 技术栈")
    for lang in info["languages"]:
        lines.append(f"- {lang}")
    for fw in info["frameworks"]:
        lines.append(f"- {fw}")
    lines.append("")
    lines.append("## 常用命令")
    if info["package_manager"] == "poetry":
        lines.append("- 安装依赖: `poetry install`")
    elif info["package_manager"] == "uv":
        lines.append("- 安装依赖: `uv sync`")
    elif info["package_manager"] == "pip":
        lines.append("- 安装依赖: `pip install -e .`")
    if info["run_cmd"]:
        lines.append(f"- 运行: `{info['run_cmd']}`")
    lines.append("")
    lines.append("## 测试命令")
    if info["test_cmd"]:
        lines.append(f"- `{info['test_cmd']}`")
    else:
        lines.append("- (未检测到测试框架, 请补充)")
    lines.append("")
    lines.append("## 构建命令")
    if info["build_cmd"]:
        lines.append(f"- `{info['build_cmd']}`")
    else:
        lines.append("- (未检测到构建命令, 请补充)")
    lines.append("")
    lines.append("## 目录结构")
    top_dirs = set(info.get("top_dirs") or [])
    for name in info["top_entries"][:20]:
        kind = "目录" if name in top_dirs else "文件"
        suffix = "/" if name in top_dirs else ""
        lines.append(f"- `{name}{suffix}` — {kind}")
    lines.append("")
    lines.append(f"- 测试框架: {tfw}")
    lines.append("")
    return "\n".join(lines)


def write_qxt_md(workspace: Path, *, force: bool = False,
                 confirm=None) -> str:
    """生成并写入 QXT.md。返回状态说明文案。

    - 已存在且 force=False: 若传入 confirm 回调则交互确认; 否则不覆盖。
    """
    ws = Path(workspace)
    target = ws / QXT_MD_NAME
    if target.exists() and not force:
        if confirm is not None:
            try:
                if not bool(confirm(f"{QXT_MD_NAME} 已存在, 是否覆盖?")):
                    return f"已取消: {QXT_MD_NAME} 已存在, 未覆盖。"
            except Exception:  # noqa: BLE001
                return f"{QXT_MD_NAME} 已存在, 未覆盖 (确认交互不可用)。"
        else:
            return f"{QXT_MD_NAME} 已存在, 未覆盖 (交互式确认不可用, 请加 --force 重跑 /init)。"
    info = detect_project(ws)
    md = render_qxt_md(info)
    target.write_text(md, encoding="utf-8")
    langs = "、".join(info["languages"]) or "未识别"
    return f"已生成 {QXT_MD_NAME} (项目: {info['name']}, 语言: {langs}, 测试: {info['test_framework'] or '未检测'})。"


def _cmd_init(agent, arg: str, config, workspace: str) -> None:
    """/init 斜杠命令入口: 扫描工作区并生成 QXT.md。"""
    from ._ui_singleton import ui
    force = bool(arg) and ("force" in arg.lower() or "y" == arg.strip().lower())
    confirm = None
    if agent is not None and getattr(agent, "ctx", None) is not None:
        confirm = getattr(agent.ctx, "confirm", None)
    msg = write_qxt_md(Path(workspace), force=force, confirm=confirm)
    ui.info(msg)
