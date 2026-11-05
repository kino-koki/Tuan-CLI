"""青小团 CLI (Tuan-CLI)

融合两大开源 Agent 项目的理念:
- DeepSeek Harness: Cordis 插件容器, 一切皆插件, Profile 组合式配置, 模型中立
- Hermes Agent: 三层记忆, 技能自进化闭环, SOUL 身份, 自注册工具
"""

# 单一版本号源: 升级 tuan 时只改 tuan_cli/version.py。
# 此处 re-export 保持 `from tuan_cli import __version__` 的既有 API。
from .version import __version__  # noqa: F401 (re-export 供外部/CLI 命令消费)

APP_NAME = "tuan_cli"
CLI_NAME = "tuan"

__all__ = ["__version__", "APP_NAME", "CLI_NAME"]
