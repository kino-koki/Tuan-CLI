"""PreToolUse ``updatedInput`` / ``args`` 改参校验（B3）。

**为什么需要它（实测，不是推测）**

旧 ``HookManager._parse_decision`` 直接把 hook stdout 里的 ``args``
dict 原样交给 ``run_pre``，``tools/base.py`` 再执行
``tool.handler(ctx, **args)``。构造一个返回
``{"args": {"path": "ok.txt", "TOTALLY_UNKNOWN": "pwn"}}`` 的 hook，
实测结果是：

1. 未知键 **原样进入** ``decision.args``；
2. 原始必需参数 ``content`` 被**整个替换掉**；
3. ``handler(ctx, **args)`` 直接抛 ``TypeError``（未知关键字参数 +
   缺必需参数），而 ``tools/base.py::_apply_pre_hooks`` 的
   ``except Exception: _hd = None`` 只吞掉 HookManager 自身的异常，
   工具层的崩溃会变成一条工具错误。

Claude Code v2.1.300 起的行为是：``updatedInput`` **替换**整个
``tool_input``（不是 merge）、未知键被丢弃、缺必需参数或类型不符的
改参**拒绝该次调用**（"The required parameter content is missing"）。
本模块把这套语义做成单一裁决出口。

**分层策略（如实，不夸大）**

- 有工具 JSON Schema（``Tool.parameters``）：严格对齐 CC ——
  按 ``properties`` 白名单丢未知键、校验 ``required``、``type``、
  ``enum``；任一不符 → ``deny=True``，由 ``run_pre`` 转成
  ``HookDecision.block=True``。``enforced=True``。
- 无 Schema（例如 ``arch/execution.py`` 那条调用链拿不到 ``Tool``
  对象）：**不能假装校验过**。退化为保守子集约束 —— 改参不得引入
  原 ``args`` 里不存在的新键（挡住上面那个 TypeError 注入面），
  但不做 required / type 判定。``enforced=False``，审计里明示。

刻意不做：不校验值的业务语义（路径是否越界、命令是否危险）——
那是写边界 / 四层滤网的职责；不做 ``$ref`` / ``oneOf`` 等复杂
JSON Schema 组合，本仓库工具 schema 都是扁平 object。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ValidationResult:
    """一次改参裁决。

    ``deny`` 为真时 ``sanitized`` 不可用于执行；``run_pre`` 应转成
    ``HookDecision(block=True, reason=...)``。``enforced`` 标明是否
    真的按 schema 严格校验过 —— 调用方不得把 ``False`` 包装成
    「已通过 schema 校验」。
    """

    sanitized: Dict[str, Any]
    dropped: List[str] = field(default_factory=list)
    deny: bool = False
    reason: str = ""
    enforced: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dropped": list(self.dropped), "deny": self.deny,
            "reason": self.reason, "enforced": self.enforced,
            "keys": sorted(self.sanitized),
        }


_JSON_TYPES: Dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def _type_ok(value: Any, expected: str) -> bool:
    if expected not in _JSON_TYPES:
        return True  # 未知类型声明不做断言，避免误拒
    py = _JSON_TYPES[expected]
    if expected == "integer" and isinstance(value, bool):
        return False  # bool 是 int 子类，但 JSON 里不是 integer
    if expected == "number" and isinstance(value, bool):
        return False
    if expected in ("string", "boolean") and isinstance(value, bool) \
            and expected == "string":
        return False
    return isinstance(value, py)


def validate_updated_input(
    new_input: Any,
    original: Dict[str, Any],
    schema: Optional[Dict[str, Any]],
    tool_name: str = "",
) -> ValidationResult:
    """校验 hook 返回的改参 dict；返回可执行的 sanitized 或 deny。

    ``new_input`` 是**替换**语义（CC ``updatedInput``）：调用方不应先
    merge 再传进来。``original`` 只用于无 schema 时的保守子集判定与诊断。
    """
    if not isinstance(new_input, dict):
        return ValidationResult(
            sanitized={}, deny=True, enforced=schema is not None,
            reason=f"改参不是 dict (实际 {type(new_input).__name__})，拒绝调用")

    if not isinstance(original, dict):
        original = {}

    # ---------------------------------------------------------- 无 schema
    if not isinstance(schema, dict) or not schema:
        allowed_keys = set(original)
        dropped = [k for k in new_input if k not in allowed_keys]
        clean = {k: v for k, v in new_input.items() if k in allowed_keys}
        return ValidationResult(
            sanitized=clean, dropped=dropped, deny=False, enforced=False,
            reason=("无工具 schema: 仅按原参数键集做保守子集过滤，"
                    "未做 required/type 校验" if dropped else ""))

    # ---------------------------------------------------------- 有 schema
    props = schema.get("properties")
    if not isinstance(props, dict):
        # schema 存在但没有 properties：无法白名单，按 fail-closed 拒绝改参
        return ValidationResult(
            sanitized={}, deny=True, enforced=True,
            reason=f"工具 {tool_name or '?'} 的 schema 缺少 properties，"
                   "无法校验改参（fail-closed 拒绝）")

    known = set(props)
    dropped = [k for k in new_input if k not in known]
    clean = {k: v for k, v in new_input.items() if k in known}

    # 类型 + enum 校验（不通过即 deny，不静默丢弃值）
    for key, value in clean.items():
        spec = props.get(key)
        if not isinstance(spec, dict):
            continue
        expected = spec.get("type")
        if isinstance(expected, str) and not _type_ok(value, expected):
            return ValidationResult(
                sanitized=clean, dropped=dropped, deny=True, enforced=True,
                reason=f"改参 {key!r} 类型不符 (期望 {expected}, "
                       f"实际 {type(value).__name__})，拒绝调用")
        enum = spec.get("enum")
        if isinstance(enum, (list, tuple)) and value not in list(enum):
            return ValidationResult(
                sanitized=clean, dropped=dropped, deny=True, enforced=True,
                reason=f"改参 {key!r} 不在允许枚举 {list(enum)!r} 中，拒绝调用")

    required = schema.get("required")
    if isinstance(required, (list, tuple)):
        missing = [k for k in required if k not in clean]
        if missing:
            return ValidationResult(
                sanitized=clean, dropped=dropped, deny=True, enforced=True,
                reason=f"改参缺少必需参数 {missing}；"
                       "updatedInput 是替换语义（不是 merge），拒绝调用")

    return ValidationResult(
        sanitized=clean, dropped=dropped, deny=False, enforced=True,
        reason=("已丢弃未知键 " + ", ".join(sorted(dropped))) if dropped else "")
