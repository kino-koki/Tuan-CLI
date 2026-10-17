"""工具合并 (consolidation) —— 把功能重叠的多个工具并成"一个更强的入口"。

设计要点:
  - **轻量**: N 个工具 → 1 个 schema (op 枚举 + 参数并集), 显著缩小每次请求的 tools 列表;
  - **能力零折扣**: 每个被合并的操作原样保留, 经 ``op`` 分发到**原来的 handler**,
    底层实现一行未改 (合并不重写逻辑, 只加路由);
  - **更强**: 单一入口收敛了同类操作, 弱模型不必在 N 个近义工具间纠结;
    权限旗标取"最严"口径 (任一成员危险 → 复合危险), 合并不放松任何判定;
  - **向后兼容**: 被合并的旧名降级为**隐藏别名** —— 不再暴露/不被检索, 但**仍可按名调用**,
    旧脚本、旧会话与既有测试不受影响。

本模块只声明"家族"数据, 实际合并由 ``ConsolidatePlugin`` 在**所有工具插件注册完之后**
执行 (builtin_tool_plugins 的最后一个)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..core.kernel import Kernel, Plugin


@dataclass
class Family:
    """一个待合并的工具家族。"""
    name: str                              # 复合工具名
    description: str                       # 面向模型的一段话
    ops: Dict[str, str]                    # op 名 -> 被合并工具的注册名
    op_docs: Dict[str, str] = field(default_factory=dict)  # op 名 -> 一句话说明
    group: str = "merged"


# 直接隐藏的纯重复工具 (与保留者功能重合, 无独特能力可吸收)
REDUNDANT_ALIASES: Dict[str, str] = {
    # 重复名 -> 保留者 (仅隐藏, 不新建复合)
    "list_agents": "agents_list",
}

FAMILIES: List[Family] = [
    Family(
        name="git",
        description="Git 操作入口 (status/diff/log)。查看工作区状态、查看改动 diff、查看提交历史。",
        ops={"status": "git_status", "diff": "git_diff", "log": "git_log"},
        op_docs={"status": "查看工作区状态", "diff": "查看改动 diff", "log": "查看提交历史"},
        group="git",
    ),
    Family(
        name="todo",
        description="会话任务清单入口 (write/read/list): 写入/更新待办、读取当前清单、列出全部条目。",
        ops={"write": "todo_write", "read": "todo_read", "list": "todo_list"},
        op_docs={"write": "写入/更新待办清单", "read": "读取当前待办", "list": "列出全部待办"},
        group="todo",
    ),
    Family(
        name="skill",
        description="技能入口 (list/read/save): 列出可用技能、读取某技能完整步骤、把可复用流程蒸馏成技能。",
        ops={"list": "skill_list", "read": "skill_read", "save": "skill_save"},
        op_docs={"list": "列出可用技能", "read": "读取技能完整 SKILL.md", "save": "保存/改进技能"},
        group="skill",
    ),
    Family(
        name="ext_json",
        description="JSON 结构化操作 (diff/merge/pointer): 逐路径 diff、深合并、JSON Pointer 取值。",
        ops={"diff": "ext_json_diff", "merge": "ext_json_merge", "pointer": "ext_json_pointer"},
        op_docs={"diff": "逐路径 JSON diff", "merge": "深合并两个 JSON", "pointer": "按 JSON Pointer 取值"},
        group="ext",
    ),
    Family(
        name="ext_crypto",
        description="文件加解密 (seal/unseal): AES-GCM 认证加密与解密 (未装 cryptography 时回退 CTR+HMAC)。",
        ops={"seal": "ext_crypto_seal", "unseal": "ext_crypto_unseal"},
        op_docs={"seal": "加密文件", "unseal": "解密文件"},
        group="ext",
    ),
    Family(
        name="ext_index",
        description="代码索引 (build/query): 构建索引、按语义/关键词查询索引。",
        ops={"build": "ext_index_build", "query": "ext_index_query"},
        op_docs={"build": "构建索引", "query": "查询索引"},
        group="ext",
    ),
    Family(
        name="ext_rules",
        description="规则引擎 (check/load): 加载规则集、按规则检查目标。",
        ops={"check": "ext_rules_check", "load": "ext_rules_load"},
        op_docs={"check": "按规则检查", "load": "加载规则集"},
        group="ext",
    ),
    Family(
        name="sandbox",
        description="沙箱 (run/snapshot/diff/cleanup): 隔离执行、快照、比对副本改动、清理沙箱。",
        ops={"run": "sandbox_run", "snapshot": "sandbox_snapshot",
             "diff": "sandbox_diff", "cleanup": "sandbox_cleanup"},
        op_docs={"run": "沙箱内隔离执行", "snapshot": "创建沙箱快照",
                 "diff": "比对沙箱副本改动", "cleanup": "清理沙箱"},
        group="sandbox",
    ),
    Family(
        name="codedev",
        description="代码开发闭环 (retrieve/spec/develop/verify): 检索定位、生成规格、实现、验证。",
        ops={"retrieve": "codedev_retrieve", "spec": "codedev_spec",
             "develop": "codedev_develop", "verify": "codedev_verify"},
        op_docs={"retrieve": "检索相关代码", "spec": "生成实现规格",
                 "develop": "实现改动", "verify": "验证结果"},
        group="codedev",
    ),
    Family(
        name="image",
        description="图像 (generate/list): 按文字描述生成图片、列出已生成的图片。",
        ops={"generate": "image_generate", "list": "image_list_generated"},
        op_docs={"generate": "文字生成图片", "list": "列出已生成图片"},
        group="image",
    ),
    Family(
        name="memory",
        description="记忆入口 (search/write/note/user): 检索记忆、写入长期记忆、追加笔记、更新用户画像。",
        ops={"search": "memory_search", "write": "memory_write",
             "note": "memory_note_append", "user": "memory_update_user"},
        op_docs={"search": "检索记忆", "write": "写长期记忆",
                 "note": "追加记忆笔记", "user": "更新用户画像"},
        group="memory",
    ),
    Family(
        name="templates",
        description="模板 (list/generate): 列出可用模板、按模板生成文件。",
        ops={"list": "list_templates", "generate": "generate_from_template"},
        op_docs={"list": "列出模板", "generate": "按模板生成"},
        group="template",
    ),
    Family(
        name="find",
        description="代码符号查找 (references/symbol): 查某符号的全部引用位置、按名查符号定义。",
        ops={"references": "find_references", "symbol": "find_symbol"},
        op_docs={"references": "查找符号引用", "symbol": "按名查找符号定义"},
        group="code",
    ),
    Family(
        name="code_review",
        description="代码评审 (full/quick): 完整评审 (多维度、含建议) 或快速扫描 (只看关键问题)。",
        ops={"full": "code_review", "quick": "code_review_quick"},
        op_docs={"full": "完整多维度评审", "quick": "快速关键问题扫描"},
        group="code",
    ),
    Family(
        name="delete",
        description="删除文件或目录 (file/dir)。",
        ops={"file": "delete_file", "dir": "delete_dir"},
        op_docs={"file": "删除文件", "dir": "删除目录"},
        group="filesystem",
    ),
    Family(
        name="background",
        description="后台任务 (shell/status): 提交后台命令、查询后台任务状态。",
        ops={"shell": "bg_shell", "status": "background_status"},
        op_docs={"shell": "提交后台命令", "status": "查询后台任务状态"},
        group="background",
    ),
]


def apply_consolidation(kernel: Kernel) -> Dict[str, object]:
    """执行全部合并 (幂等)。

    必须在 ``kernel.activate_all()`` **之后**调用 —— 插件激活顺序由 requires 拓扑决定,
    不保证"工具插件先于本合并执行", 故不能依赖 ConsolidatePlugin 的 activate 时机。
    返回 {复合工具名 -> 合并到的成员数} 供自检/测试。
    """
    registry = kernel.get("tool_registry")
    if registry is None:
        return {}

    # 1) 纯重复工具: 仅降级为隐藏别名
    for alias, keeper in REDUNDANT_ALIASES.items():
        if registry.get(alias) is not None and registry.get(keeper) is not None:
            registry.hide(alias)

    # 2) 家族合并: 生成复合工具, 成员降级为隐藏别名
    applied: Dict[str, object] = {}
    for fam in FAMILIES:
        try:
            tool = registry.merge(
                fam.name, fam.description, fam.ops,
                group=fam.group, op_docs=fam.op_docs, hide_members=True,
            )
        except Exception:  # noqa: BLE001 - 单个家族失败不应阻断启动
            continue
        if tool is not None:
            applied[fam.name] = len(fam.ops)
    return applied


class ConsolidatePlugin(Plugin):
    """占位插件 (合并的实际执行在 ``apply_consolidation``, 由 build_kernel 在
    activate_all 之后调用, 以保证成员工具已全部注册)。"""

    name = "tools.consolidate"
    provides = []
    requires = ["tool_registry"]

    def activate(self, kernel: Kernel) -> None:
        # 不在此处合并 (激活顺序不保证成员已注册); 由 app.build_kernel 显式调用。
        return None
