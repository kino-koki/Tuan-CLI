"""极简配置模型 —— 用 stdlib 实现判别联合校验 + 属性访问, 替代 pydantic。

``pydantic`` 及其传递依赖 (``pydantic-core`` 是编译产物、``annotated-types``、
``typing-inspection``) 共占 4 个安装包, 而这里只需要四件事:

1. 按 ``transport`` 字段做判别联合 (stdio / http / sse)
2. 必填字段校验 (stdio 需要 command, http/sse 需要 url)
3. 标量类型归一 (str / int / bool / list[str] / dict[str,str])
4. 结果对象**同时**支持属性访问与 dict 访问

结果类型 :class:`ConfigModel` 对齐 pydantic BaseModel 的常用接口
(``model_dump`` / ``dict`` / ``get`` / ``__getitem__`` / ``__contains__`` / ``items``),
因此调用方无需区分「有 pydantic」还是「无 pydantic」—— 旧实现里这两条分支
返回 dict 与 pydantic 模型两种形状, 下游 ``getattr(config, "headers")`` 在 dict
形状下取不到值, 是一个真实存在的静默丢字段缺陷。本模块让形状只有一种。

扩展约定: 以后若需要更复杂的 schema (嵌套模型、跨字段约束、自定义序列化),
先评估能否在本模块内用同样的方式补; 只有确有必要时才把 pydantic 加回核心依赖。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

_TRUE = frozenset({"1", "1.0", "true", "t", "yes", "y", "on", "是", "对", "启用"})
_FALSE = frozenset({"0", "0.0", "false", "f", "no", "n", "off", "否", "不", "停用", ""})

# transport -> 必填字段
_TRANSPORTS = ("stdio", "http", "sse")
_REQUIRED = {
    "stdio": ("command",),
    "http": ("url",),
    "sse": ("url",),
}

# 字段名 -> 类型标记 (仅作文档与报错用, 实际转换看下面的函数)
_FIELD_KIND: Dict[str, str] = {
    "enabled": "bool",
    "startupTimeoutMs": "int",
    "toolTimeoutMs": "int",
    "enabledTools": "array[string]",
    "disabledTools": "array[string]",
    "command": "string",
    "args": "array[string]",
    "env": "object[string, string]",
    "cwd": "string",
    "executor": "string",
    "runtime_id": "string",
    "url": "string",
    "headers": "object[string, string]",
    "auth": "string",
    "bearerTokenEnvVar": "string",
}


class ValidationError(ValueError):
    """配置校验失败。消息采用 ``字段: 原因`` 形式, 便于直接透出给用户。"""


# --------------------------------------------------------------------------- #
# 类型归一 —— 对齐 pydantic v2 在 lax 模式下的常见转换行为
# --------------------------------------------------------------------------- #
def _to_str(v: Any, field: str) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else str(v)
    raise ValidationError(f"{field}: 期望 {_FIELD_KIND.get(field, 'string')}, 收到 {type(v).__name__}")


def _to_int(v: Any, field: str) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v) if v.is_integer() else int(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return int(s)
        except ValueError as exc:
            raise ValidationError(f"{field}: 期望 integer, 收到 {v!r}") from exc
    raise ValidationError(f"{field}: 期望 {_FIELD_KIND.get(field, 'integer')}, 收到 {type(v).__name__}")


def _to_bool(v: Any, field: str) -> Optional[bool]:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        s = v.strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
    raise ValidationError(f"{field}: 期望 boolean, 收到 {v!r}")


def _to_str_list(v: Any, field: str) -> Optional[List[str]]:
    if v is None:
        return None
    if isinstance(v, str):
        return [v]
    if isinstance(v, (list, tuple)):
        return [_to_str(x, f"{field}[{i}]") for i, x in enumerate(v)]
    raise ValidationError(f"{field}: 期望 array, 收到 {type(v).__name__}")


def _to_str_dict(v: Any, field: str) -> Optional[Dict[str, str]]:
    if v is None:
        return None
    if isinstance(v, dict):
        return {str(k): _to_str(val, f"{field}[{k!r}]") for k, val in v.items()}
    raise ValidationError(f"{field}: 期望 object, 收到 {type(v).__name__}")


_COERCERS: Dict[str, Callable[[Any, str], Any]] = {
    "enabled": _to_bool,
    "startupTimeoutMs": _to_int,
    "toolTimeoutMs": _to_int,
    "enabledTools": _to_str_list,
    "disabledTools": _to_str_list,
    "command": _to_str,
    "args": _to_str_list,
    "env": _to_str_dict,
    "cwd": _to_str,
    "executor": _to_str,
    "runtime_id": _to_str,
    "url": _to_str,
    "headers": _to_str_dict,
    "auth": _to_str,
    "bearerTokenEnvVar": _to_str,
}


# --------------------------------------------------------------------------- #
# 结果对象 —— 属性访问 + dict 访问双形态
# --------------------------------------------------------------------------- #
class ConfigModel:
    """校验结果。同时支持 ``cfg.transport`` 与 ``cfg["transport"]`` 两种读法。

    对齐 pydantic BaseModel 的常用接口, 使调用方在有无 pydantic 时行为一致:
    ``model_dump`` / ``dict`` / ``get`` / ``__getitem__`` / ``__contains__`` /
    ``__iter__`` / ``keys`` / ``values`` / ``items`` / ``__eq__``。
    """

    def __init__(self, data: Dict[str, Any]) -> None:
        object.__setattr__(self, "_data", dict(data))

    def __getattr__(self, key: str) -> Any:
        if key.startswith("_"):
            raise AttributeError(key)
        try:
            data = object.__getattribute__(self, "_data")
        except AttributeError:
            raise AttributeError(key)
        if key in data:
            return data[key]
        raise AttributeError(key)

    def __setattr__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __iter__(self):
        return iter(self._data)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def __len__(self) -> int:
        return len(self._data)

    def model_dump(self, **_: Any) -> Dict[str, Any]:
        return dict(self._data)

    def dict(self, **_: Any) -> Dict[str, Any]:
        return dict(self._data)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ConfigModel):
            return self._data == other._data
        if isinstance(other, dict):
            return self._data == other
        return NotImplemented

    def __hash__(self) -> int:  # 与可变 dict 语义一致: 不可哈希
        raise TypeError(f"unhashable type: {type(self).__name__}")

    def __repr__(self) -> str:  # noqa: D401
        return f"ConfigModel({self._data!r})"


# --------------------------------------------------------------------------- #
# 校验入口
# --------------------------------------------------------------------------- #
def validate_server_config(
    raw: Any,
    *,
    infer_transport: bool = True,
    required: bool = True,
) -> ConfigModel:
    """校验单个 MCP server 配置, 返回 :class:`ConfigModel`。

    Args:
        raw: 原始配置 (应为对象)。
        infer_transport: 缺少 ``transport`` 时按 ``command`` -> stdio /
            ``url`` -> http 推断。关闭后必须显式给出 transport。
        required: 为 False 时跳过必填字段校验 (仅做类型归一), 供部分场景复用。

    Raises:
        ValidationError: 类型不符、transport 非法或缺必填字段。
    """
    if not isinstance(raw, dict):
        raise ValidationError(f"配置必须是对象, 收到 {type(raw).__name__}")
    data: Dict[str, Any] = dict(raw)

    transport = data.get("transport")
    if transport is None or (isinstance(transport, str) and not transport.strip()):
        if infer_transport and isinstance(data.get("command"), str) and data.get("command").strip():
            transport = "stdio"
        elif infer_transport and isinstance(data.get("url"), str) and data.get("url").strip():
            transport = "http"
        else:
            raise ValidationError(
                "transport: 必须为 stdio / http / sse, 且需提供 command 或 url 用于推断"
            )
    transport = _to_str(transport, "transport")
    if transport not in _TRANSPORTS:
        raise ValidationError(
            f"transport: 必须为 {' / '.join(_TRANSPORTS)} 之一, 收到 {transport!r}"
        )
    data["transport"] = transport

    for name, coerter in _COERCERS.items():
        if name in data and name != "transport":
            data[name] = coerter(data[name], name)

    # auth 目前只支持 oauth 一种取值 (对齐原 Literal["oauth"] 约束)
    auth = data.get("auth")
    if auth is not None and auth != "oauth":
        raise ValidationError(f"auth: 仅支持 'oauth', 收到 {auth!r}")

    if required:
        for name in _REQUIRED[transport]:
            if data.get(name) in (None, ""):
                raise ValidationError(f"{name}: {transport} 传输方式必填")
    return ConfigModel(data)


# 便捷别名: 让 ``from tuan_cli._config_model import McpServerConfig`` 成立
McpServerConfig = validate_server_config
