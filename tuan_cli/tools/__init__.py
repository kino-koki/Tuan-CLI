"""工具系统入口: 注册表服务插件 + 全部内置工具插件。"""

from ..core.kernel import Kernel, Plugin
from typing import Any
from .base import Tool, ToolContext, ToolRegistry
from .cache import ToolResultCache
from .checkpoint import CheckpointPlugin
from .filesystem import FilesystemPlugin
from .memory_tool import MemoryToolPlugin
from .shell import ShellPlugin
from .skill_tool import SkillToolPlugin
from .web import WebPlugin
from .code import CodeToolPlugin
from .dispatch import DispatchPlugin
from .task_tool import TaskToolPlugin
from .monitor_tool import MonitorToolPlugin
from .session_tools import SessionToolsPlugin
from .todo_tool import TodoToolPlugin
from .team_tool import TeamToolPlugin
from .mcp.plugin import MCPPlugin
from .pipeline import PipelinePlugin
from .code_review import CodeReviewPlugin
from .external import ExternalToolsPlugin
from .languages import LanguagePlugin
from .permissions import PermissionPolicy
from .permission_fusion import FusionPermissionPolicy, build_permission_policy
from .code_graph import CodeGraphPlugin
from .backend_dev import BackendDevPlugin
from .sandbox import SandboxPlugin
from .dynamic_workflow_tool import DynamicWorkflowPlugin
from .image_gen import ImageGenPlugin
from .picker import PickerPlugin
from .tool_search import ToolSearchPlugin
from .consolidate import ConsolidatePlugin
from .browser import BrowserPlugin
from .notebook import NotebookPlugin
from .artifact_tool import ArtifactPlugin
from .messaging_tool import MessagingPlugin
from .subagent_tool import SubagentPlugin
from .workflow_tool import WorkflowPlugin
from .cron_tool import CronToolPlugin
from .gh_tool import GhToolPlugin
from .ecosystem_tool import EcosystemToolPlugin
from .audit_tool import AuditToolPlugin
from .dispatch_tool import DispatchToolPlugin

__all__ = [
    "Tool", "ToolContext", "ToolRegistry",
    "PermissionPolicy", "FusionPermissionPolicy", "build_permission_policy",
    "ToolRegistryPlugin", "builtin_tool_plugins",
]


class ToolRegistryPlugin(Plugin):
    """最底层的工具注册表服务, 其他工具插件都依赖它。"""

    name = "tools.registry"
    provides = ["tool_registry"]

    def activate(self, kernel: Kernel) -> None:
        # 只读工具结果缓存 (TTL 60s, 上限 200 条), 减少多轮循环里的重复 IO/摘要
        cfg = kernel.get("config")
        ttl = cfg.get("tools.cache_ttl", 60.0) if cfg is not None else 60.0
        cache = ToolResultCache(ttl=ttl)
        kernel.provide("tool_cache", cache, owner=self.name)
        kernel.provide("tool_registry", ToolRegistry(cache=cache), owner=self.name)


def builtin_tool_plugins() -> list[Any]:
    return [
        FilesystemPlugin(), ShellPlugin(), WebPlugin(),
        MemoryToolPlugin(), SkillToolPlugin(), CodeToolPlugin(),
        DispatchPlugin(), PipelinePlugin(), CodeReviewPlugin(),
        ExternalToolsPlugin(), LanguagePlugin(), CheckpointPlugin(),
        TaskToolPlugin(), SessionToolsPlugin(), TodoToolPlugin(), CodeGraphPlugin(), BackendDevPlugin(), SandboxPlugin(), DynamicWorkflowPlugin(),
        TeamToolPlugin(),
        ImageGenPlugin(),
        PickerPlugin(),
        ToolSearchPlugin(),
        BrowserPlugin(),
        MonitorToolPlugin(),
        NotebookPlugin(),
        # 审计「真实接入」轮: 以下 4 个插件早已实现 (各自有对应 CLI 命令)，
        # 但从未接入 builtin_tool_plugins() —— Agent 侧工具面缺失。现补齐接线。
        ArtifactPlugin(),
        MessagingPlugin(),
        SubagentPlugin(),
        WorkflowPlugin(),
        # cron 子系统此前仅 CLI 可用 (cmd_cron.py); 现接入 Agent 工具面。
        CronToolPlugin(),
        # gh 子系统 (gh_borrow + REST 回退) 接入 Agent 工具面。
        GhToolPlugin(),
        # ecosystem 互操作 (Claude Code / Hermes 资产盘点与导入导出) 接入 Agent 工具面。
        EcosystemToolPlugin(),
        # 内核审计归档只读查询接入 Agent 工具面。
        AuditToolPlugin(),
        # external_dispatch: tuan dispatch (Agent-of-Agents) 调度层接入 Agent 工具面。
        # 注意插件名是 tools.external_dispatch —— tools.dispatch 已被 DispatchPlugin 占用。
        DispatchToolPlugin(),
        # 必须最后: 在全部工具注册完之后做合并 (成员降级为隐藏别名)
        ConsolidatePlugin(),
    ]

