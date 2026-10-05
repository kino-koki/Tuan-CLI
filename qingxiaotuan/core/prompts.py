"""系统提示词组装 —— SOUL 身份 + 稳定前缀 + 动态后缀 (对标 Claude Code prompt cache 分段)。

缓存边界 (对标 Claude Code 静态缓存前缀 / 动态非缓存后缀):
- **build_system_prompt_stable()**: 绝对稳定前缀。只含 SOUL 身份、行为准则、Windows 外骨骼、
  上网指引、代码开发流程、安全提醒、技能使用规范。同一会话内逐字节不变,
  **可安全做 prompt cache** (DeepSeek/OpenAI 兼容端点命中关键)。
- **build_system_prompt_dynamic()**: 动态后缀。含每轮/每会话可能变化的段: 运行环境、
  Git 上下文、分层项目指令、用户画像、长期记忆、代码库地图、技能注册表快照、
  MEMORY.md 笔记、输出风格。**不应做跨轮缓存** (Git dirty/记忆/技能热度会变)。
- **build_system_prompt()**: 兼容入口 = stable + 动态, 内部拼接, 不破坏现有调用方。
  配置 `prompt.cache_stable_prefix=false` 时回退到「单段不区分」的旧行为
  (拼接结果逐字节相同, 仅不再对外声明 cache 边界)。

compact 后存活契约: 见 docs/compact_survival_guide.md。压缩不会删除磁盘上的状态,
下列内容在新会话/压缩后必须从磁盘重建 (本模块是重建入口之一):
SOUL.md → 项目指令(QXT.md/AGENTS.md/CLAUDE.md) → MEMORY.md 笔记 → FTS5 长期记忆 →
Git 上下文 → 技能注册表快照。

工具说明不进 system (function schema 自带), 避免重复。文案极简, 每条都有信息量。
"""

from __future__ import annotations

import hashlib
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from ..i18n import LANGUAGES, normalize_language


# 项目级指令文件名 (对标 Claude Code 的 CLAUDE.md; AGENTS.md 为社区通用约定,
# 优先级: 自家格式 > 社区标准 > 遗留兼容)
_INSTRUCTION_FILES = ["QXT.md", "AGENTS.md", "CLAUDE.md", ".qxt.md"]

# 用户级全局指令 (社区标准位置)。模块级变量便于测试 monkeypatch 隔离,
# 生产环境始终指向真实用户目录。
_USER_GLOBAL_AGENTS = Path.home() / ".agents" / "AGENTS.md"

# 单项目指令文件大小上限 (对标 Codex project_doc_max_bytes), 默认 32KiB。
# 超过则截断并附加提示, 避免一个巨型指令文件吃掉整个上下文窗口。
DEFAULT_PROJECT_DOC_MAX_BYTES = 32768

# MEMORY.md 文件型笔记默认注入行数上限 (对标 Claude Code 200 行注入上限)。
DEFAULT_MEMORY_NOTES_MAX_LINES = 200


# SOUL.md 缺失时的内置回退文案。保持与 resources/SOUL.md 关键要点同步:
# 身份信条 + 思考预算协议 + 错误处理协议 + 模型自我认知 + 工作协议。
_FALLBACK_SOUL = (
    "你是「青小团」, 用户终端里的 Agent。少客套多做事, 先查再问, "
    "可复用方法蒸馏成 Skill, 不确定就明说, 做错就承认。\n"
    "需求先行: 用户表述可能模糊、不准确甚至带专业错误, 先弄清真实意图再按判断推进, 不盲从字面。\n"
    "技能按需加载: 涉及技能时先 skill_read 读取完整步骤再执行, 无关技能不读。\n"
    "做前端/UI 时先定设计语言 (调色板/字体/布局/原则), 再写代码; 追求克制的高级感, "
    "避免千篇一律的 AI 模板味。\n"
    "思考预算: 复杂任务先估算步数, 超过 20 步主动拆分或向用户确认, 每 5 步做一次进度自检。\n"
    "错误处理: 工具失败三级恢复——先重试一次, 再换方案, 仍不行就如实向用户报告; "
    "不静默吞错, 不无限重试。\n"
    "自我认知: 你是通过 API 调用的 LLM, 有 token 上限, 长任务会触发上下文压缩; 不确定就明说。\n"
    "工作协议: 先理解再动手, 验证驱动; 不把「应该可以」当成「已完成」。"
)


def _read_instruction(path: Path) -> str:
    """读取单个指令文件内容; 不存在/为空/IO 失败一律返回空串。"""
    try:
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        pass
    return ""


def _read_instruction_capped(path: Path, max_bytes: int) -> str:
    """读取指令文件并按字节上限截断 (功能5: 对标 Codex project_doc_max_bytes)。

    超限返回截断后的文本 + 溢出提示; 未超限与 _read_instruction 行为一致。
    """
    try:
        if not (path.exists() and path.is_file()):
            return ""
        raw = path.read_bytes()
    except OSError:
        return ""
    if max_bytes > 0 and len(raw) > max_bytes:
        truncated = raw[:max_bytes].decode("utf-8", errors="replace").strip()
        return truncated + "\n…(文件过大已截断，完整内容请用 read_file 读取)"
    return raw.decode("utf-8", errors="replace").strip()


def _is_repo_root(path: Path) -> bool:
    """判断某目录是否为 git 仓库根 (存在 .git)。独立小函数便于测试 monkeypatch。"""
    return (path / ".git").exists()


def _project_chain(workspace: Path) -> List[Path]:
    """工作区 → 最近 git 仓库根的目录链 (含两端, 由远及近排列)。

    向上遇到 git 仓库根即止 —— 项目层指令绝不飘出仓库边界;
    工作区自身不在任何 git 仓库内时只返回 [workspace]。
    """
    cur = workspace
    chain: List[Path] = [cur]
    found_git = _is_repo_root(cur)
    # 盘符根的 parent 是它自身, 用 cur != cur.parent 防死循环
    while not found_git and cur != cur.parent:
        cur = cur.parent
        chain.append(cur)
        found_git = _is_repo_root(cur)
    if not found_git:
        return [workspace]
    chain.reverse()
    return chain


def _discover_project_instructions(
    workspace: str,
    home: Optional[Path] = None,
    max_bytes: int = DEFAULT_PROJECT_DOC_MAX_BYTES,
) -> str:
    """发现并合并分层项目级指令 (对标 Claude Code 的 CLAUDE.md 分层记忆)。

    三层, 从全局到局部依次注入 (越靠近工作区越后出现, 语义上越具体):
    1. 用户全局层: <qxt_home>/AGENTS.md 与 ~/.agents/AGENTS.md;
    2. 项目祖先层: 从工作区沿父目录向上到最近的 git 仓库根 (不含仓库外),
       逐级收录候选指令文件;
    3. 工作区根: 按候选名优先级收录 (QXT.md > AGENTS.md > CLAUDE.md > .qxt.md)。

    同一环境下多次调用产出逐字节一致 (prompt cache 友好)。
    max_bytes: 单文件大小上限 (功能5), 超过截断并附加提示。
    """
    parts: List[str] = []

    # 1. 用户全局层 (两个位置都收, 均带绝对路径标注以便区分来源)
    global_paths = []
    if home is not None:
        global_paths.append(home / "AGENTS.md")
    global_paths.append(_USER_GLOBAL_AGENTS)
    for gpath in global_paths:
        content = _read_instruction_capped(gpath, max_bytes)
        if content:
            parts.append(f"# 全局指令 ({gpath})\n{content}")

    # 2+3. 项目层: 由远及近逐级收录
    ws = Path(workspace)
    if not ws.is_dir():
        return "\n\n".join(parts)
    for directory in _project_chain(ws):
        depth = len(ws.relative_to(directory).parts)  # 根=0, 直接父=1, ...
        prefix = "../" * depth
        for name in _INSTRUCTION_FILES:
            content = _read_instruction_capped(directory / name, max_bytes)
            if content:
                parts.append(f"# 项目指令 ({prefix}{name})\n{content}")
    return "\n\n".join(parts)


def _get_system_context() -> str:
    """获取系统上下文信息 (对标 Claude Code 的 OS/Shell/Git 动态注入)。

    包含: OS、Shell 类型、Python 版本、Git 信息、平台架构。
    这些信息随环境变化, 但在同一会话内保持稳定。
    """
    parts: List[str] = []

    # OS 和平台
    parts.append(f"OS={platform.system()} {platform.release()}")
    parts.append(f"Platform={platform.machine()}")

    # Shell
    shell = "bash"
    if sys.platform == "win32":
        shell = "PowerShell/bash"
    parts.append(f"Shell={shell}")

    # Python 版本
    py_ver = platform.python_version()
    parts.append(f"Python={py_ver}")

    return ", ".join(parts)


def _get_git_context(workspace: str) -> str:
    """获取 Git 上下文 (分支、最近 commit、状态)。"""
    ws = Path(workspace)
    if not (ws / ".git").exists():
        return ""
    parts: List[str] = []
    # 当前分支
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(ws), capture_output=True, text=True, timeout=5,
            errors="replace",
        ).stdout.strip()
        if branch:
            parts.append(f"Branch={branch}")
    except Exception:
        pass
    # 最近一次 commit
    try:
        log_out = subprocess.run(
            ["git", "log", "-1", "--pretty=%h %s"],
            cwd=str(ws), capture_output=True, text=True, timeout=5,
            errors="replace",
        ).stdout.strip()
        if log_out:
            parts.append(f"LastCommit={log_out}")
    except Exception:
        pass
    # 是否有未提交改动
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(ws), capture_output=True, text=True, timeout=5,
            errors="replace",
        ).stdout.strip()
        dirty_count = len(status.splitlines()) if status else 0
        if dirty_count > 0:
            parts.append(f"DirtyFiles={dirty_count}")
        else:
            parts.append("Clean=true")
    except Exception:
        pass
    return ", ".join(parts) if parts else ""


# ============================================================ 稳定前缀 (可缓存)

def _build_soul_block(home: Path) -> str:
    """读取 SOUL.md; 不存在时返回内置回退文案 (与 resources/SOUL.md 要点同步)。"""
    soul_path = home / "SOUL.md"
    try:
        if soul_path.exists():
            return soul_path.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return _FALLBACK_SOUL


def build_system_prompt_stable(
    home: Path,
    workspace: str = "",
    reply_language: str = "zh-CN",
) -> str:
    """组装「绝对稳定」前缀 —— 可安全做 prompt cache。

    Cache 边界声明: 本函数的输出在同一 home + 同一 reply_language 下逐字节不变,
    不依赖 Git 状态、记忆内容、技能热度、工作区文件变化。**可作为缓存前缀**。
    包含段: SOUL 身份、行为准则、Windows 外骨骼、上网指引、代码开发流程、
    安全提醒、技能使用规范。

    参数 workspace 仅为对齐签名保留; 稳定段内容不读取工作区 (项目指令/环境走动态段)。
    """
    parts: List[str] = []

    # 1. SOUL (最稳定, 放最前, 便于缓存命中)
    parts.append(_build_soul_block(home))

    # 2. 行为准则 (核心操作规则, 与 SOUL.md 互补而非重复)
    rules = [
        _reply_rule(reply_language),
        "2. mcp__ 前缀工具来自外部 MCP Server, 调用前先检查 schema (参数名和类型是工具特定的)。",
        "3. plan 模式下只分析不修改文件, 等用户确认后再执行。",
        "4. 复杂任务 (3+ 步骤) 用 TodoWrite 追踪, 同一时间只允许 1 个任务处于 in_progress。",
        "5. 回答中引用代码时用 file:line 格式 (如 src/app.py:42), 让开发者能直接跳转。",
        "6. 更新长期记忆时, 只提取 2 个以上会话中出现的模式; 单次出现不算模式。",
        "7. 多个 MCP 工具调用时并行获取所有 schema, 再执行调用。",
        "8. 最终报告以普通文本提供, 不主动写入文件 (除非用户要求); 始终包含相关文件名和绝对路径。",
    ]
    parts.append("准则:\n" + "\n".join(rules))

    # 3. Windows 命令外骨骼 (当 Shell 包含 PowerShell/cmd 时注入)
    if "win" in platform.system().lower() or "Windows" in platform.system():
        win_guidance = (
            "\n## Windows 命令外骨骼\n"
            "你正在 Windows 用户电脑上运行。大部分模型的训练数据以 Linux/macOS 为主, "
            "对 Windows 命令 (CMD/PowerShell) 支持有限。请遵循以下规则:\n"
            "- 当你在 Windows 上执行 PowerShell 或 CMD 命令时, 如果遇到报错、不确定语法、"
            "或需要将 Linux 命令转换为 Windows 等价命令, 请先查阅你的 Windows 命令参考技能 "
            "(windows-cmd-powershell skill), 或使用 web_search 上网查找正确的 Windows 命令。\n"
            "- 优先使用 PowerShell (功能更全, 语法更一致), 而非 CMD。\n"
            "- Python 脚本比 shell 命令更跨平台可靠: 优先 `python -m pip` 而非 `pip`, "
            "优先 `python script.py` 而非直接调 shell。\n"
            "- 路径用正斜杠 `/` 或 pathlib.Path, 不要用反斜杠 `\\` (会被 Python 当转义符)。\n"
            "- 读写文件时显式指定 `encoding='utf-8'`, 因为 Windows 默认编码不是 UTF-8。\n"
            "- 虚拟环境激活: `.venv\\Scripts\\activate` (CMD) 或 `.venv\\Scripts\\Activate.ps1` (PowerShell)。\n"
            "- 如果你不确定某个 Windows 命令的语法, 可以用 web_search 搜索 "
            "`[你的意图] powershell windows command` 或 `[你的意图] cmd windows`。"
        )
        parts.append(win_guidance)

    # 4. 上网查证能力指引
    web_guidance = (
        "\n## 上网查证\n"
        "你拥有 web_search (搜索引擎) 和 web_fetch (抓取网页) 工具。当遇到以下情况时, "
        "请主动使用这些工具:\n"
        "- 不确定某个 API/库的最新用法或版本变化\n"
        "- 需要查找某个错误的解决方案\n"
        "- 需要确认某个技术概念的细节\n"
        "- 需要查找某个工具/服务的文档\n"
        "在回答中, 如果你参考了网上查到的信息, 请明确注明:\n"
        "- 引用的网站/网页 URL\n"
        "- 从该来源提取的关键信息\n"
        "- 这样用户可以自行验证信息的准确性\n"
        "注意: 不要编造 URL。如果 web_search 没有找到相关信息, 如实说明。"
    )
    parts.append(web_guidance)

    # 5. 代码开发能力 (精简版: SOUL.md 已覆盖详细规范, 此处只放流程提醒)
    code_dev_guidance = (
        "\n## 代码开发流程\n"
        "改代码时: 先读目标文件 (read_file) → grep 找引用 (search_files) → 理解上下文 → "
        "精确编辑 (edit_file) → 跑测试验证 (run_shell)。 "
        "如果用户要求 git commit, 用 Conventional Commits 格式 (feat:/fix:/refactor:/docs: 等前缀)。"
    )
    parts.append(code_dev_guidance)

    # 6. 安全操作提醒 (精简版: SOUL.md 已覆盖完整安全准则)
    sandbox_guidance = (
        "\n## 安全提醒\n"
        "- 危险操作 (删除文件、系统命令、网络写入) 必须先向用户确认, 说明后果。\n"
        "- Shell 命令优先用参数列表而非字符串拼接 (防注入)。\n"
        "- 如果被沙箱拦截, 向用户解释原因并建议替代方案。"
    )
    parts.append(sandbox_guidance)

    # 7. 技能使用规范 (提到才读: 注册表进动态段, 全文按需 skill_read)
    skill_guidance = (
        "\n## 技能使用 (提到才读)\n"
        "- 动态后缀会注入技能注册表快照 (名称 + 一句话描述 + 触发词), 不含正文。\n"
        "- 当任务与某技能相关时, 先用 skill_read <技能名> 读取完整 SKILL.md, 再按其步骤执行。\n"
        "- 无关技能不读取; 完成可复用任务后用 skill_save 蒸馏, 同名保存即改进。"
    )
    parts.append(skill_guidance)

    # 8. 文件型记忆笔记使用指引 (对标 Claude Code: Agent 直接写 MEMORY.md)
    notes_guidance = (
        "\n## 记忆笔记 (MEMORY.md)\n"
        "- 当用户表达跨会话有效的偏好/纠正/项目决策时 (如「以后都用 pytest」「别这么命名」"
        "「本项目统一用 ruff」), 直接用 memory_note_append 写入 MEMORY.md, 不要只记在当前会话。\n"
        "- 下次会话会自动把 MEMORY.md 注入系统提示; 笔记超过 200 行时先精简旧笔记再写新的。\n"
        "- 结构化条目 (事实/链接) 仍用 memory_write; MEMORY.md 写自然语言笔记, 两者互补。"
    )
    parts.append(notes_guidance)

    return "\n\n".join(parts)


# ============================================================ 动态后缀 (不跨轮缓存)

def _build_memory_notes_block(
    home: Path,
    workspace: str,
    enabled: bool,
    max_lines: int,
) -> str:
    """注入文件型记忆笔记 MEMORY.md (功能2, 对标 Claude Code 200 行注入上限)。

    惰性导入 MemoryNotesStore 避免 prompts <-> memory 循环依赖。
    超限截断并提示整理; 关闭/无笔记返回空串。
    """
    if not enabled:
        return ""
    try:
        from ..memory.memory_notes import MemoryNotesStore
        store = MemoryNotesStore(home=home, workspace=workspace)
        content = store.read().strip()
        if not content:
            return ""
        lines = content.splitlines()
        truncated = False
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            truncated = True
        body = "\n".join(lines)
        note = "## 记忆笔记 (MEMORY.md)\n" + body
        if truncated:
            note += (f"\n…(笔记已达 {max_lines} 行上限并截断，"
                     "请用 memory_note_append 整理后再写新内容)")
        return note
    except Exception:
        return ""


def build_system_prompt_dynamic(
    home: Path,
    workspace: str,
    memory_store=None,
    skill_manager=None,
    skill_limit: int = 3,
    codebase_map: str = "",
    output_style: str = "default",
    memory_notes_enabled: bool = True,
    memory_notes_max_lines: int = DEFAULT_MEMORY_NOTES_MAX_LINES,
    project_doc_max_bytes: int = DEFAULT_PROJECT_DOC_MAX_BYTES,
) -> str:
    """组装「动态」后缀 —— 不应做跨轮缓存。

    Cache 边界声明: 本函数输出依赖 Git dirty、长期记忆内容、技能热度、项目指令文件
    等会变化的状态, **不要缓存为固定前缀**; 每次会话/压缩后重新生成。
    包含段: 运行环境、Git 上下文、分层项目指令、用户画像、长期记忆、代码库地图、
    技能注册表快照、MEMORY.md 笔记、输出风格。
    """
    parts: List[str] = []

    # 1. 运行环境 (系统上下文注入, 对标 Claude Code)
    sys_ctx = _get_system_context()
    parts.append(
        f"环境: {sys_ctx} | 工作区={workspace}\n"
        "能力: 读写文件/执行命令/抓网页/读写记忆/蒸馏技能/理解代码库。"
    )

    # 2. Git 上下文 (动态注入: 分支/commit/dirty 每轮可能变)
    git_ctx = _get_git_context(workspace)
    if git_ctx:
        parts.append(f"Git: {git_ctx}")

    # 3. 分层项目级指令 (对标 Claude Code 的 CLAUDE.md 分层记忆)
    project_instructions = _discover_project_instructions(
        workspace, home=home, max_bytes=project_doc_max_bytes)
    if project_instructions:
        parts.append(project_instructions)

    # 4. 用户画像 (仅在有效内容时注入: 跳过空模板)
    if memory_store:
        user = memory_store.read_user().strip()
        if user and not _is_empty_user_template(user):
            parts.append(f"用户: {user}")

    # 5. 长期记忆: 读全量但限长 (FTS5 结构化记忆)
    if memory_store and hasattr(memory_store, "read_memory"):
        raw = memory_store.read_memory().strip()
        if raw:
            if len(raw) > 1500:
                raw = raw[:1500] + "\n…(详见 memory_read)"
            parts.append(f"长期记忆:\n{raw}")

    # 6. 文件型记忆笔记 MEMORY.md (功能2: Agent 直接写的偏好/纠正/项目决策)
    notes_block = _build_memory_notes_block(
        home, workspace, memory_notes_enabled, memory_notes_max_lines)
    if notes_block:
        parts.append(notes_block)

    # 7. 代码库地图 (大上下文: 钉死的全貌, 由 indexer 保证同内容同字符串)
    if codebase_map:
        parts.append(codebase_map)

    # 8. 技能注册表快照 (优先级排序, 会随热度变化 → 放动态段)
    if skill_manager:
        all_skills = skill_manager.list_all()
        import heapq  # noqa: F401  (保留历史导入位置语义)
        sorted_skills = sorted(all_skills, key=lambda s: (-s.priority, -s.use_count))
        top_skills = sorted_skills[:skill_limit]
        rendered = skill_manager.render_for_prompt(top_skills)
        if rendered:
            parts.append(rendered)

    # 9. 输出风格 (对标 Claude Code 的 Output Styles): default 不注入。
    if output_style:
        style_text = resolve_output_style(output_style, workspace)
        if style_text:
            parts.append("## 输出风格\n" + style_text)

    return "\n\n".join(parts)


# ============================================================ 兼容入口

def build_system_prompt(
    home: Path,
    workspace: str,
    memory_store=None,
    skill_manager=None,
    skill_limit: int = 3,
    codebase_map: str = "",
    reply_language: str = "zh-CN",
    output_style: str = "default",
    cache_stable_prefix: bool = True,
    memory_notes_enabled: Optional[bool] = None,
    memory_notes_max_lines: int = DEFAULT_MEMORY_NOTES_MAX_LINES,
    project_doc_max_bytes: int = DEFAULT_PROJECT_DOC_MAX_BYTES,
) -> str:
    """组装完整系统提示 = 稳定前缀 + 动态后缀 (兼容入口, 不破坏现有调用方)。

    - cache_stable_prefix=True (默认): 对外声明 cache 边界 (stable 可缓存 / dynamic 不缓存)。
    - cache_stable_prefix=False: 回退旧的「单段不区分」行为; 拼接结果与默认一致,
      仅不再利用分段做缓存 (供需要把 system 当整体看待的调用方)。

    无论开关如何, 返回字符串都等于 stable + 动态, 保证调用方拿到一致结果。
    """
    # memory_notes_enabled 未显式传入时默认开启; 供 agent/测试关闭。
    if memory_notes_enabled is None:
        memory_notes_enabled = True

    stable = build_system_prompt_stable(home, workspace, reply_language=reply_language)
    dynamic = build_system_prompt_dynamic(
        home, workspace,
        memory_store=memory_store,
        skill_manager=skill_manager,
        skill_limit=skill_limit,
        codebase_map=codebase_map,
        output_style=output_style,
        memory_notes_enabled=memory_notes_enabled,
        memory_notes_max_lines=memory_notes_max_lines,
        project_doc_max_bytes=project_doc_max_bytes,
    )
    # cache_stable_prefix 仅为边界声明; 拼接结果逐字节一致 (微内核行为不变)。
    del cache_stable_prefix
    return "\n\n".join([stable, dynamic])


# 内置输出风格文案 (对标 Claude Code 2.1.237 新增的内置 Output Styles)
_BUILTIN_OUTPUT_STYLES = {
    "concise": (
        "用尽可能少的文字回答: 直接给结论与关键代码/命令, 不铺垫不复述问题, "
        "不写总结性客套。解释仅在被追问时展开。"
    ),
    "explanatory": (
        "回答时穿插教学式说明: 在给出结论之外, 解释关键设计取舍与原理, "
        "帮助用户理解代码为什么这样写, 而不只是改好了。"
    ),
    "learning": (
        "协作学习模式: 先给出小而清晰的步骤, 留一部分实现 (标注 TODO(human)) "
        "让用户亲手补全, 再对其实现给出反馈; 避免一次性给全部代码。"
    ),
}


def resolve_output_style(output_style: str, workspace: str) -> str:
    """解析输出风格为提示词文本段。

    - "" / "default": 返回空 (不注入, 保持 system 前缀稳定);
    - concise / explanatory / learning: 返回内置中文文案;
    - 其他值视为自定义风格名或路径: 优先读 <workspace>/<值>, 否则读
      <workspace>/.qxt/output-style.md; 都不存在返回空。
    """
    style = (output_style or "").strip()
    if not style or style == "default":
        return ""
    builtin = _BUILTIN_OUTPUT_STYLES.get(style.lower())
    if builtin:
        return builtin
    ws = Path(workspace)
    candidates = [ws / style, ws / ".qxt" / "output-style.md"]
    for path in candidates:
        try:
            if path.is_file():
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    return text
        except OSError:
            continue
    return ""


def _reply_rule(reply_language: str = "zh-CN") -> str:
    """行为准则第 1 条 —— 要求模型按用户选择的界面语言回复。

    zh-CN 保持历史原文逐字节不变 (保护既有 prompt cache 与测试断言);
    其他语言注入对应语言名, 让 Agent 对话跟随 UI 语言。
    """
    code = normalize_language(reply_language or "")
    if code and code != "zh-CN":
        info = LANGUAGES[code]
        return (f"7. Always reply in {info['english']} ({info['native']}); "
                "be concise and direct; admit uncertainty honestly.")
    return "7. 中文回答, 简洁直接; 不确定如实说。"


def build_task_context(
    task_hint: str,
    memory_store=None,
    skill_manager=None,
    skill_limit: int = 3,
) -> str:
    """生成「随任务变化的上下文」, 贴在首条 user 消息前 (不进 system, 不破坏缓存)。

    包含: 与当前任务相关的记忆召回 (关键词命中 + 近 24h, 走 recall_context 合并去重)
    + 相关技能召回。无相关内容时返回空串, 调用方据此决定是否追加。
    """
    blocks: List[str] = []
    if memory_store and task_hint:
        try:
            if hasattr(memory_store, "recall_context"):
                # 增强召回 (MemoryStore): 关键词全文命中 + 近 24h 记忆, 已合并去重
                recalled = memory_store.recall_context(task_hint, limit=5)
                if recalled:
                    blocks.append(recalled)
            elif hasattr(memory_store, "search"):
                # 兜底: 仅实现基础全文检索的存储后端
                hits = memory_store.search(task_hint, limit=5)
                if hits:
                    mem = "\n".join(f"- {h['content']}" for h in hits)
                    blocks.append(f"[与任务相关的记忆]\n{mem}")
        except Exception:
            pass
    if skill_manager and task_hint:
        try:
            # 语义匹配激活: 任务描述 → 标签映射 → 最相关技能
            if hasattr(skill_manager, "activate_for_task"):
                skills = skill_manager.activate_for_task(task_hint, limit=skill_limit)
            else:
                skills = skill_manager.search(task_hint, limit=skill_limit)
        except Exception:
            skills = []
        rendered = skill_manager.render_for_prompt(skills) if skills else ""
        if rendered:
            blocks.append(rendered)
    return "\n\n".join(blocks)


def is_short_task(task_hint: str, max_chars: int = 160) -> bool:
    """判断任务是否适合跳过额外语义上下文。"""
    text = "".join(task_hint.split())
    return 0 < len(text) <= max_chars and not any(
        marker in text.lower()
        for marker in ("实现", "修复", "重构", "测试", "implement", "refactor", "fix")
    )


def system_prompt_hash(system_prompt: str) -> str:
    """返回 system 提示的短哈希, 用于断言「同会话前缀稳定」(缓存命中自检)。"""
    return hashlib.sha1(system_prompt.encode("utf-8")).hexdigest()[:16]


def system_prompt_stable_hash(stable_prompt: str) -> str:
    """稳定前缀哈希: 用于自检「stable 段跨 Git/记忆变化逐字节一致」(缓存前缀边界)。"""
    return hashlib.sha1(("stable|" + stable_prompt).encode("utf-8")).hexdigest()[:16]


def system_prompt_dynamic_hash(dynamic_prompt: str) -> str:
    """动态后缀哈希: 用于自检「dynamic 段随 Git/记忆变化而变化」。"""
    return hashlib.sha1(("dynamic|" + dynamic_prompt).encode("utf-8")).hexdigest()[:16]


def _is_empty_user_template(user_text: str) -> bool:
    """判断 USER.md 是否仍是未填写的空模板 (避免把空模板当有效画像注入)。

    用「去空行/去标记后无实质内容」判定, 不依赖硬编码的魔法字符串,
    即使模板文案微调也不会失效。
    """
    import re

    stripped = re.sub(r"[#\-\*\s:]", "", user_text)
    # 去掉模板里常见的示例字段名
    stripped = re.sub(r"(Name|City|Notes|关于用户)", "", stripped, flags=re.IGNORECASE)
    return stripped.strip() == ""
