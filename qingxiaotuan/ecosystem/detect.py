"""生态探测层 —— 发现本机已安装的 Claude Code / Hermes Agent 及其资产。

青小团把自己定位为「生态互操作枢纽」: 在原生能力之外, 直接发现、读取并复用
Claude Code (Anthropic) 与 Hermes Agent (Nous Research) 在本机积累的资产:

- Claude Code:  ``claude`` CLI、``~/.claude`` (用户级 agents/skills/settings)、
  项目 ``.claude`` (agents/skills/commands)、``.mcp.json`` (MCP server 配置)、
  ``CLAUDE.md`` (项目指令, qxt 已在运行期读取)。
- Hermes Agent: ``hermes`` CLI、``~/.hermes`` (skills/memories/SOUL.md/config.yaml)、
  ``$HERMES_HOME`` 覆盖、profiles (每 profile 独立 skills/memories)。

本模块是纯函数、无副作用、可测: 只做「定位 + 盘点」, 不写任何文件;
导入/导出动作由 bridges 负责。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------- 路径常量

CLAUDE_HOME_NAME = ".claude"
CLAUDE_AGENTS = "agents"
CLAUDE_SKILLS = "skills"
CLAUDE_COMMANDS = "commands"
CLAUDE_PLUGIN = ".claude-plugin"
HERMES_HOME_DEFAULT = ".hermes"
HERMES_SKILLS = "skills"
HERMES_MEMORIES = "memories"
HERMES_PROFILES = "profiles"
HERMES_SOUL = "SOUL.md"
HERMES_CONFIG = "config.yaml"


@dataclass
class AssetSummary:
    """某个生态目录里的资产盘点 (计数, 不读文件内容)。"""

    skills: int = 0
    agents: int = 0
    commands: int = 0
    memories: int = 0          # MEMORY.md / USER.md 存在数
    soul: bool = False
    mcp_servers: int = 0       # .mcp.json / config.yaml 里声明的 server 数
    plugins: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "skills": self.skills,
            "agents": self.agents,
            "commands": self.commands,
            "memories": self.memories,
            "soul": int(self.soul),
            "mcp_servers": self.mcp_servers,
            "plugins": self.plugins,
        }


@dataclass
class EcosystemProbe:
    """一次生态探测的结果: 双方 CLI / 主目录 / 资产摘要。"""

    claude_cli: Optional[str] = None
    claude_home: Optional[Path] = None          # ~/.claude
    claude_project: Optional[Path] = None       # <workspace>/.claude
    claude_version: str = ""
    hermes_cli: Optional[str] = None
    hermes_home: Optional[Path] = None          # ~/.hermes 或 $HERMES_HOME
    hermes_profiles: List[Path] = field(default_factory=list)
    hermes_version: str = ""
    workspace: Optional[Path] = None

    # ------------------------------------------------------------ 定位

    @staticmethod
    def _which(cmd: str) -> Optional[str]:
        """查找可执行文件路径; 找不到返回 None (不抛异常)。"""
        try:
            return shutil.which(cmd)
        except Exception:  # noqa: BLE001 - PATH 异常时静默降级
            return None

    @staticmethod
    def _run_version(cmd: str) -> str:
        """取 CLI 版本号 (尽力而为, 失败返回空串)。"""
        import subprocess
        try:
            out = subprocess.run(
                [cmd, "--version"], capture_output=True, text=True, timeout=8,
            )
            return (out.stdout or out.stderr).strip().splitlines()[0][:80] if out.stdout or out.stderr else ""
        except Exception:  # noqa: BLE001 - 版本探测失败不影响主流程
            return ""

    @classmethod
    def probe(
        cls,
        workspace: Optional[str] = None,
        *,
        claude_home: Optional[str] = None,
        hermes_home: Optional[str] = None,
    ) -> "EcosystemProbe":
        """探测本机 Claude Code 与 Hermes Agent 的安装情况。

        路径可显式注入 (测试/CI 用); 缺省时按标准位置探测:
        Claude Code:  ``~/.claude``; Hermes: ``$HERMES_HOME`` 或 ``~/.hermes``。
        """
        p = cls(workspace=Path(workspace) if workspace else None)

        # ---- Claude Code ----
        p.claude_cli = cls._which("claude")
        if p.claude_cli:
            p.claude_version = cls._run_version(p.claude_cli)
        home = Path(claude_home) if claude_home else Path.home() / CLAUDE_HOME_NAME
        if home.is_dir():
            p.claude_home = home
        if p.workspace is not None:
            proj = p.workspace / CLAUDE_HOME_NAME
            if proj.is_dir():
                p.claude_project = proj

        # ---- Hermes Agent ----
        p.hermes_cli = cls._which("hermes")
        if p.hermes_cli:
            p.hermes_version = cls._run_version(p.hermes_cli)
        hh = Path(hermes_home) if hermes_home else (
            Path(os.environ.get("HERMES_HOME", "")) if os.environ.get("HERMES_HOME") else Path.home() / HERMES_HOME_DEFAULT
        )
        if hh.is_dir():
            p.hermes_home = hh
            prof = hh / HERMES_PROFILES
            if prof.is_dir():
                p.hermes_profiles = sorted(
                    d for d in prof.iterdir() if d.is_dir()
                )
        return p

    # ------------------------------------------------------------ 盘点

    @property
    def claude_agents_dirs(self) -> List[Path]:
        """Claude Code agents 目录 (项目优先, 用户级其次)。"""
        out: List[Path] = []
        if self.claude_project is not None:
            out.append(self.claude_project / CLAUDE_AGENTS)
        if self.claude_home is not None:
            out.append(self.claude_home / CLAUDE_AGENTS)
        return out

    @property
    def claude_skills_dirs(self) -> List[Path]:
        """Claude Code skills 目录 (项目优先, 用户级其次)。"""
        out: List[Path] = []
        if self.claude_project is not None:
            out.append(self.claude_project / CLAUDE_SKILLS)
        if self.claude_home is not None:
            out.append(self.claude_home / CLAUDE_SKILLS)
        return out

    @property
    def hermes_skills_dirs(self) -> List[Path]:
        """Hermes skills 目录: 主 home + 各 profile。"""
        out: List[Path] = []
        if self.hermes_home is not None:
            out.append(self.hermes_home / HERMES_SKILLS)
        for prof in self.hermes_profiles:
            out.append(prof / HERMES_SKILLS)
        return out

    @property
    def hermes_memories_dirs(self) -> List[Path]:
        out: List[Path] = []
        if self.hermes_home is not None:
            out.append(self.hermes_home / HERMES_MEMORIES)
        for prof in self.hermes_profiles:
            out.append(prof / HERMES_MEMORIES)
        return out

    # ------------------------------------------------------------ 计数

    @staticmethod
    def _count_skills(dirs: List[Path]) -> int:
        """统计目录里的技能数: 单文件 <slug>.md 与目录包 <slug>/SKILL.md。

        隐藏目录 (如 Claude 官方安装的 ``.tabbit-stage-*`` 暂存目录) 不计入,
        避免把安装中间产物误认为用户技能。
        """
        n = 0
        seen: set = set()
        for d in dirs:
            if not d.is_dir():
                continue
            for md in sorted(d.glob("*.md")):
                if md.name == "SKILL.md":
                    continue
                if md.stem not in seen:
                    seen.add(md.stem)
                    n += 1
            for child in sorted(d.iterdir()):
                if child.name.startswith("."):
                    continue
                if child.is_dir() and (child / "SKILL.md").exists() and child.name not in seen:
                    seen.add(child.name)
                    n += 1
        return n

    @staticmethod
    def _count_md_files(dirs: List[Path]) -> int:
        seen: set = set()
        for d in dirs:
            if not d.is_dir():
                continue
            for md in sorted(d.glob("*.md")):
                if md.stem not in seen:
                    seen.add(md.stem)
        return len(seen)

    def _count_claude_mcp(self) -> int:
        """统计 Claude 项目 .mcp.json 的 server 数 (claude_code 生态口径)。"""
        n = 0
        if self.workspace is not None:
            mcp_json = self.workspace / ".mcp.json"
            if mcp_json.exists():
                try:
                    import json
                    data = json.loads(mcp_json.read_text(encoding="utf-8"))
                    servers = data.get("mcpServers", {}) if isinstance(data, dict) else {}
                    n += len(servers) if isinstance(servers, dict) else 0
                except Exception:  # noqa: BLE001 - 畸形 JSON 只计 0
                    pass
        return n

    def _count_hermes_mcp(self) -> int:
        """统计 Hermes config.yaml 的 mcp.servers 数 (hermes 生态口径)。"""
        n = 0
        if self.hermes_home is not None:
            cfg = self.hermes_home / HERMES_CONFIG
            if cfg.exists():
                try:
                    import yaml  # pyyaml 是核心依赖
                    data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
                    servers = (data.get("mcp") or {}).get("servers", {}) if isinstance(data, dict) else {}
                    n += len(servers) if isinstance(servers, dict) else 0
                except Exception:  # noqa: BLE001
                    pass
        return n

    def summarize(self) -> Dict[str, AssetSummary]:
        """返回 {ecosystem: AssetSummary}, 不读取文件正文。"""
        claude = AssetSummary()
        claude.agents = self._count_md_files(self.claude_agents_dirs)
        claude.skills = self._count_skills(self.claude_skills_dirs)
        claude.commands = self._count_md_files(
            [d / CLAUDE_COMMANDS for d in [self.claude_project, self.claude_home] if d]
        )
        if self.claude_home is not None and (self.claude_home / CLAUDE_PLUGIN).exists():
            claude.plugins = 1
        claude.mcp_servers = self._count_claude_mcp()

        hermes = AssetSummary()
        hermes.skills = self._count_skills(self.hermes_skills_dirs)
        for d in self.hermes_memories_dirs:
            if (d / "MEMORY.md").exists():
                hermes.memories += 1
            if (d / "USER.md").exists():
                hermes.memories += 1
        if self.hermes_home is not None and (self.hermes_home / HERMES_SOUL).exists():
            hermes.soul = True
        hermes.mcp_servers = self._count_hermes_mcp()
        return {"claude_code": claude, "hermes": hermes}


def render_probe(p: EcosystemProbe) -> str:
    """把探测结果渲染为可打印文本 (qxt ecosystem scan/status)。"""
    lines: List[str] = []
    lines.append("Claude Code (Anthropic):")
    if p.claude_cli:
        lines.append(f"  CLI      : {p.claude_cli}" + (f"  ({p.claude_version})" if p.claude_version else ""))
    else:
        lines.append("  CLI      : 未安装 (claude 不在 PATH)")
    if p.claude_home:
        lines.append(f"  用户目录 : {p.claude_home}")
    if p.claude_project:
        lines.append(f"  项目目录 : {p.claude_project}")
    lines.append("")
    lines.append("Hermes Agent (Nous Research):")
    if p.hermes_cli:
        lines.append(f"  CLI      : {p.hermes_cli}" + (f"  ({p.hermes_version})" if p.hermes_version else ""))
    else:
        lines.append("  CLI      : 未安装 (hermes 不在 PATH)")
    if p.hermes_home:
        lines.append(f"  HERMES_HOME: {p.hermes_home}")
        if p.hermes_profiles:
            lines.append("  profiles : " + ", ".join(x.name for x in p.hermes_profiles[:8]))
    return "\n".join(lines)


__all__ = [
    "AssetSummary", "EcosystemProbe", "render_probe",
    "CLAUDE_HOME_NAME", "HERMES_HOME_DEFAULT",
]
