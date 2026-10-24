"""五模式提示词装配器 —— 按当前模式拼接 system/memory/guard 三件套。

资源目录布局（§4.1–§4.5 逐字落盘）:
    tuan_cli/resources/modes/<id>/prompts/{system.md, memory.md, guard.md}

装配器职责:
    - 解析模式 ID（含历史三档别名 standard/yolo/plan，经 resolve_mode_id 统一解析）
    - 从资源目录读取三件套 .md
    - 组装为 ModePrompts 数据类返回，交 core/prompts.py 统一注入

资源目录解析参考 config/defaults.py::_resolve_resources_dir() 的模式:
    优先 importlib.resources（pip install 后走 wheel 包内），
    回退到相对源码路径。MultiplexedPath 不能直接 Path() 转换,
    必须迭代后取各项（见 config/defaults.py 的鸭子类型判断）。
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Tuple

# 三件套文件名（缺一不可；任一缺失即视为装配失败）
_PROMPT_FILES: Tuple[str, ...] = ("system.md", "memory.md", "guard.md")


@dataclass
class ModePrompts:
    """模式提示词三件套。"""
    system: str
    memory: str
    guard: str


def _resolve_mode_prompts_dir(mode_id: str) -> Path:
    """定位模式提示词目录: resources/modes/<id>/prompts/。

    参考 config/defaults.py::_resolve_resources_dir() 的候选枚举策略:
        1. importlib.resources.files("tuan_cli.resources.modes")
           —— MultiplexedPath 可迭代出各子包 Traversable, 单一 Traversable
              (Path) 不可迭代; 鸭子类型判断, 避免引入 abc 依赖。
        2. 相对源码路径: <this-file>.parent.parent / resources / modes / <id> / prompts
    首个满足 is_dir() 且含 system.md 的候选即胜出。

    参数:
        mode_id: 标准模式 ID（不含别名；别名解析由 build_mode_prompts 前置完成）。

    返回:
        提示词目录 Path。

    异常:
        FileNotFoundError: 所有候选目录均不存在或缺少 system.md。
    """
    candidates: list[Path] = []
    try:
        res = resources.files("tuan_cli.resources.modes")
        if hasattr(res, "__iter__"):
            for item in res:
                candidates.append(Path(str(item)) / mode_id / "prompts")
        else:
            candidates.append(Path(str(res)) / mode_id / "prompts")
    except Exception:
        pass
    candidates.append(
        Path(__file__).resolve().parent.parent / "resources" / "modes" / mode_id / "prompts"
    )
    for cand in candidates:
        if cand.is_dir() and (cand / "system.md").exists():
            return cand
    raise FileNotFoundError(
        f"未找到模式 {mode_id!r} 的提示词目录; 尝试过: {candidates}"
    )


def _read_prompt_file(path: Path) -> str:
    """读取提示词文件为字符串（UTF-8）。"""
    return path.read_text(encoding="utf-8")


def build_mode_prompts(mode_id: str) -> ModePrompts:
    """按模式 ID 加载三件套提示词。

    参数:
        mode_id: 模式 ID 或别名（含历史 standard/yolo/plan）。

    返回:
        ModePrompts 三件套（system / memory / guard），均为 UTF-8 原文。

    异常:
        ValueError: 未知模式 ID（由 resolve_mode_id 抛出）。
        FileNotFoundError: 提示词目录或三件套文件缺失。
    """
    from .registry import resolve_mode_id

    resolved = resolve_mode_id(mode_id)
    prompts_dir = _resolve_mode_prompts_dir(resolved)

    missing = [name for name in _PROMPT_FILES if not (prompts_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"模式 {resolved!r} 提示词缺失: {missing}; 目录: {prompts_dir}"
        )

    return ModePrompts(
        system=_read_prompt_file(prompts_dir / "system.md"),
        memory=_read_prompt_file(prompts_dir / "memory.md"),
        guard=_read_prompt_file(prompts_dir / "guard.md"),
    )
