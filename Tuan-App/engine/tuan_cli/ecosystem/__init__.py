"""生态互操作层 —— 青小团 ⇄ Claude Code ⇄ Hermes Agent 的三向桥。

「Model + Harness = Agent」之外的第三条腿: **生态互操作**。
青小团把自己定位为 Agent 生态的**互操作枢纽**: 在一个 harness 里直接发现、
导入、导出并复用 Claude Code (Anthropic) 与 Hermes Agent (Nous Research)
在本机积累的全部可移植资产 —— 技能 (SKILL.md 开放标准)、命名 Agent、长期记忆、
人格 (SOUL.md)、上下文文件 (AGENTS.md/CLAUDE.md)、MCP server 配置;
同时以 MCP Server / 委派工具两种方式**反向被它们调用**。

布局:
- ``detect.py``        生态探测 (定位 CLI / 主目录 / 资产盘点)
- ``skills_bridge.py`` 技能双向搬运 (tuan ⇄ Claude Code ⇄ Hermes, SKILL.md 标准)
- ``agents_bridge.py`` 命名 Agent 双向同步 (tuan ⇄ Claude Code .claude/agents)
- ``memory_bridge.py`` 记忆/人格互通 (tuan ⇄ Hermes MEMORY.md/USER.md/SOUL.md)
- ``mcp_import.py``    MCP server 配置互导 (.mcp.json / config.yaml ⇄ tuan)
- ``mcp_server.py``    tuan 能力以 MCP Server 暴露 (被 Claude Code/Hermes 挂载)
- ``invoke.py``        委派工具 (tuan 调 claude -p / hermes chat -q)
"""

# 不再硬编码 ecosystem 独立版本号 (历史遗留 0.1.0, 语义混淆)。
# ecosystem 是 CLI 的一个功能域, 版本随主包走。re-export 主包单一版本源,
# 既保留 `from tuan_cli.ecosystem import __version__` 的既有 API,
# 又消除"两版本并存"的漂移。升级 tuan 时只需改 tuan_cli/version.py。
from ..version import __version__  # noqa: F401 (re-export)

__all__ = ["__version__"]
