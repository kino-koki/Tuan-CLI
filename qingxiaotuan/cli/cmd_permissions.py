"""qxt permissions —— 查看权限规则 / 测试某次工具调用会命中哪条规则。

用法:
    qxt permissions                 # 列出 permissions.rules 全部规则
    qxt permissions test run_shell '{"command":"rm -rf /"}'
                                    # 测试一次具体调用会被哪条规则命中 (只读, 不执行)
"""

from __future__ import annotations

import json

from ..ui.plain_console import console
from ..tools.permissions import PermissionPolicy


def _fmt_rule(rule: dict) -> str:
    """把一条规则格式化成单行可读文本。"""
    tool = rule.get("tool", "*")
    action = rule.get("action", "?")
    if rule.get("param"):
        detail = f"{tool}({rule.get('param')}={rule.get('value', '*')})"
    else:
        p = rule.get("pattern")
        detail = f"{tool}:{p}" if p else str(tool)
    return f"{action:6s}  {detail}"


def cmd_permissions(args) -> int:
    """权限规则查看与命中测试。"""
    from ..config import Config

    sub = getattr(args, "permissions_cmd", "list")
    config = Config(profile=getattr(args, "profile", "default"),
                    patch_file=getattr(args, "patch", None))
    rules = config.get("permissions.rules", []) or []

    if sub == "test":
        tool = getattr(args, "tool", "") or ""
        try:
            call_args = json.loads(getattr(args, "args_json", "") or "{}")
            if not isinstance(call_args, dict):
                raise ValueError("参数必须是 JSON 对象")
        except (json.JSONDecodeError, ValueError) as exc:
            console.print(f"  参数解析失败: {exc}")
            console.print("  示例: qxt permissions test run_shell '{\"command\":\"rm -rf /\"}'")
            return 2

        policy = PermissionPolicy(_Cfg(rules))
        result = policy.inspect(tool, call_args)
        console.print(f"  测试调用: {tool}({json.dumps(call_args, ensure_ascii=False)})")
        if not result["hits"]:
            console.print("  无规则命中 → 走默认决策 (危险工具需确认, 只读工具放行)")
            return 0
        console.print(f"  命中 {len(result['hits'])} 条规则, 最终动作: {result['action'] or '(无)'}")
        for hit in result["hits"]:
            console.print(f"    #{hit['index']}  {_fmt_rule(hit['rule'])}")
        return 0

    # list (默认)
    console.print(f"  权限规则 (permissions.rules): {len(rules)} 条")
    for i, rule in enumerate(rules):
        if isinstance(rule, dict):
            console.print(f"    #{i}  {_fmt_rule(rule)}")
    if not rules:
        console.print("    (空) 示例:")
        console.print('    qxt config set permissions.rules \'[{"tool":"run_shell","param":"command","value":"rm -rf*","action":"deny"}]\'')
    return 0


class _Cfg:
    """最小配置桩: 只回答 permissions.rules。"""

    def __init__(self, rules):
        self._rules = rules

    def get(self, key, default=None):
        if key == "permissions.rules":
            return self._rules
        return default
