"""生态互操作层 —— 青小团 ⇄ Claude Code ⇄ Hermes Agent 的三向桥。

「Model + Harness = Agent」之外的第三条腿: **生态互操作**。
青小团把自己定位为 Agent 生态的**互操作枢纽**: 在一个 harness 里直接发现、
导入、导出并复用 Claude Code (Anthropic) 与 Hermes Agent (Nous Research)
在本机积累的全部可移植资产 —— 技能 (SKILL.md 开放标准)、命名 Agent、长期记忆、
人格 (SOUL.md)、上下文文件 (AGENTS.md/CLAUDE.md)、MCP server 配置;
同时以 MCP Server / 委派工具两种方式**反向被它们调用**。

布局:
- ``detect.py``        生态探测 (定位 CLI / 主目录 / 资产盘点)
- ``skills_bridge.py`` 技能双向搬运 (qxt ⇄ Claude Code ⇄ Hermes, SKILL.md 标准)
- ``agents_bridge.py`` 命名 Agent 双向同步 (qxt ⇄ Claude Code .claude/agents)
- ``memory_bridge.py`` 记忆/人格互通 (qxt ⇄ Hermes MEMORY.md/USER.md/SOUL.md)
- ``mcp_import.py``    MCP server 配置互导 (.mcp.json / config.yaml ⇄ qxt)
- ``mcp_server.py``    qxt 能力以 MCP Server 暴露 (被 Claude Code/Hermes 挂载)
- ``invoke.py``        委派工具 (qxt 调 claude -p / hermes chat -q)
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
