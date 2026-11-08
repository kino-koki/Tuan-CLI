"""B2: 子进程出网边界与凭据代理（sentinel）。

**为什么要单独一个模块（先实测再修）**

``SandboxManager._execute_backend`` 算出 ``block_net = not verdict.network``，
但 ``local`` 分支调用 ``run_with_tree_kill`` 时 **既不传 block_net 也不传
env**：

1. 当 ``verdict.network=False`` 且后端落到 ``local``，命令仍以父进程完整
   ``os.environ`` 裸跑 —— 「默认禁网」在唯一**没有 OS 级网络隔离能力**
   的后端上静默失效。L2 的 ``_has_network_request`` 只是命令文本识别，
   深度轮 fuzz 已证明零宽字符 / ANSI-C / 注释换行都能绕过文本层。
2. 父进程里的 ``GITHUB_TOKEN`` / ``AWS_SECRET_ACCESS_KEY`` 等真实凭据
   原样进入子进程，与目录里「子进程不持密钥」的宣称相反。

本模块提供**执行前**的统一边界，不依赖模型、不依赖命令文本：

- :class:`CredentialBroker`：真实值只在当前进程内存；子进程拿 sentinel。
- :func:`build_child_env`：保留非敏感变量，敏感键替换为 sentinel；
  脏输入（非 mapping / 非 str 键或值）fail-closed 不继承。
- :func:`enforce_local_egress`：**local 后端 + 禁网 → 明确拒绝**，
  绝不假装禁网成功。强后端有自己的网络隔离，不在此重复判定。

**刻意不做的（决定 catalog 状态仍为 partial）**

- 不实现真实 HTTP 转发代理进程，所以「出网代理注入真实密钥」未接线；
  :meth:`CredentialBroker.inject_headers` 是预留接口，默认 ``enabled=False``。
- **不翻** ``deny_network_by_default`` 出厂默认（仍是 false）—— 那是
  破坏性行为变更，前 13 轮明确承诺给迁移开关、不擅自翻。
- 不把真实值写进日志 / repr / 异常 / 审计；只记键名与计数。

许可与合规：纯本地实现，未复制任何 Anthropic 源码或资产。
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

SENTINEL_PREFIX = "tuan-egress-sentinel-v1:"

# 环境变量**名字**匹配，不扫描值内容（值可能是任意二进制形态）。
# 用白名单排除常见非敏感但含关键字的变量，避免误伤 PATH/HOME 等。
_SENSITIVE_NAME_RE = re.compile(
    r"(?i)(?:SECRET|TOKEN|PASSW(?:OR)?D|CREDENTIAL|PRIVATE|APIKEY|API_KEY|"
    r"ACCESS_KEY|AUTH|COOKIE|SESSION|BEARER|SIGNATURE|CLIENT_ID|_KEY$)")
_SAFE_NAME_EXACT = frozenset({
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "SHELL", "TERM",
    "TMPDIR", "TEMP", "TMP", "USER", "LOGNAME", "PWD", "OLDPWD",
    "TZ", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX", "SYSTEMROOT",
    "COMSPEC", "WINDIR", "PATHEXT", "HOSTNAME", "DISPLAY", "SSH_AUTH_SOCK",
})


def is_sensitive_env_name(name: str) -> bool:
    """确定性的名字判定；非字符串一律 False（由调用方丢弃脏键）。"""
    if not isinstance(name, str):
        return False
    if name in _SAFE_NAME_EXACT or name.startswith(SENTINEL_PREFIX.upper()):
        return False
    return bool(_SENSITIVE_NAME_RE.search(name))


@dataclass
class EgressDecision:
    """执行前的边界结论。真实值绝不出现在任何可序列化字段里。"""

    allowed: bool
    reason: str = ""
    env: Dict[str, str] = field(default_factory=dict)
    masked_names: Tuple[str, ...] = ()
    dropped_names: Tuple[str, ...] = ()
    invalid_base: bool = False
    block_local_applied: bool = False
    broker: Optional["CredentialBroker"] = None

    def to_audit_dict(self) -> Dict[str, Any]:
        """只记名字与计数，绝不记值。供 ``last_egress`` 可查询。"""
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "masked_count": len(self.masked_names),
            "masked_names": list(self.masked_names),
            "dropped_count": len(self.dropped_names),
            "invalid_base": self.invalid_base,
            "block_local_applied": self.block_local_applied,
        }


class CredentialBroker:
    """真实凭据的进程内保管者。

    - ``mask()`` 把敏感值换成 sentinel 并在此登记；
    - ``resolve()`` / ``inject_headers()`` 只在**同一进程**内可用；
    - 不实现 ``__reduce__`` / ``to_dict``，不落盘、不进审计、不进异常。

    ``inject_headers`` 是给未来出网代理转发用的预留接口，默认关闭；
    当前没有任何出网代理进程调用它，所以 ``credential_masking`` 仍标
    ``partial``，不谎称已接线。
    """

    def __init__(self) -> None:
        self._secrets: Dict[str, str] = {}
        self._inject_enabled: bool = False

    @property
    def inject_enabled(self) -> bool:
        return self._inject_enabled

    def enable_injection(self) -> None:
        """显式开启注入能力（目前无调用方；保留给真实出网代理）。"""
        self._inject_enabled = True

    def _sentinel(self, name: str, value: str) -> str:
        fp = hashlib.sha256((name + "\x00" + value).encode("utf-8", "replace")).hexdigest()[:16]
        return SENTINEL_PREFIX + fp

    def mask(self, name: str, value: str) -> str:
        s = self._sentinel(name, value)
        self._secrets[s] = value
        return s

    def resolve(self, sentinel: str) -> Optional[str]:
        if not isinstance(sentinel, str):
            return None
        return self._secrets.get(sentinel)

    def inject_headers(self, headers: Mapping[str, str]) -> Dict[str, str]:
        """把 header 值里的 sentinel 还原（仅在显式开启后生效）。"""
        out = dict(headers) if isinstance(headers, Mapping) else {}
        if not self._inject_enabled:
            return out
        for k, v in list(out.items()):
            if isinstance(v, str) and SENTINEL_PREFIX in v:
                for s, real in self._secrets.items():
                    v = v.replace(s, real)
                out[k] = v
        return out

    def __len__(self) -> int:
        return len(self._secrets)

    def __repr__(self) -> str:  # 绝不打印真实值
        return f"<CredentialBroker secrets={len(self._secrets)} inject_enabled={self._inject_enabled}>"


def build_child_env(base: Any, *, broker: Optional[CredentialBroker] = None,
                    mask_credentials: bool = True
                    ) -> Tuple[Dict[str, str], Tuple[str, ...], Tuple[str, ...], bool]:
    """构造子进程环境。返回 ``(env, masked_names, dropped_names, invalid_base)``。

    脏输入语义（深度轮反复强调的「静默折叠」）：
      - ``base`` 不是 Mapping → **空环境**，``invalid_base=True``；
      - 键不是 str 或值不是 str → 丢弃，记进 ``dropped_names``；
    绝不是「回退到继承父进程完整 os.environ」—— 那样等于静默放行凭据。
    """
    broker = broker if broker is not None else CredentialBroker()
    if not isinstance(base, Mapping):
        return {}, (), (), True
    env: Dict[str, str] = {}
    masked: list[str] = []
    dropped: list[str] = []
    for k, v in base.items():
        if not isinstance(k, str) or not isinstance(v, str):
            dropped.append(repr(k)[:64] if not isinstance(k, str) else k)
            continue
        if mask_credentials and is_sensitive_env_name(k):
            env[k] = broker.mask(k, v)
            masked.append(k)
        else:
            env[k] = v
    return env, tuple(masked), tuple(dropped), False


def enforce_local_egress(verdict: Any, backend: str, *,
                         block_local_when_denied: bool = True) -> Tuple[bool, str, bool]:
    """local 后端没有 OS 级网络隔离能力：禁网请求必须明确拒绝，不假装生效。

    返回 ``(allowed, reason, applied)``。强后端（docker/landlock/seatbelt/
    jobobject/token-acl）自带网络边界，这里不重复判定。
    """
    if not isinstance(backend, str) or backend != "local":
        return True, "", False
    try:
        network_allowed = bool(getattr(verdict, "network", True))
    except Exception:  # noqa: BLE001 - 裁决对象异常时按最严处理
        network_allowed = False
    if network_allowed:
        return True, "", False
    if not isinstance(block_local_when_denied, bool) or not block_local_when_denied:
        # 显式逃生口：不拒绝，但必须让配置校验把它报成安全降级。
        return True, "egress: local 后端禁网请求被显式放行（安全降级）", True
    return False, (
        "egress fail-closed: 裁决要求禁网 (verdict.network=False)，但当前"
        "后端 local 没有 OS 级出网隔离能力；拒绝执行而不是裸跑。"
        "请改用强后端 (docker/bwrap/seatbelt/jobobject) 或显式开启网络。"
    ), True


class EgressGuard:
    """把上面三件事合成一次执行前检查。"""

    def __init__(self, *, mask_credentials: bool = True,
                 block_local_when_denied: bool = True) -> None:
        # 严格类型：bool 之外的脏值一律回落到最严档，避免 ``bool("false")==True``
        self.mask_credentials = mask_credentials if isinstance(mask_credentials, bool) else True
        self.block_local_when_denied = (
            block_local_when_denied if isinstance(block_local_when_denied, bool) else True)

    @classmethod
    def from_policy(cls, policy: Any) -> "EgressGuard":
        res: Mapping[str, Any] = {}
        if isinstance(policy, Mapping):
            raw = policy.get("resource")
            if isinstance(raw, Mapping):
                res = raw
        return cls(
            mask_credentials=res.get("egress_credential_masking", True),
            block_local_when_denied=res.get("egress_block_local_when_denied", True),
        )

    def prepare(self, verdict: Any, backend: str,
                base_env: Any = None) -> EgressDecision:
        broker = CredentialBroker()
        allowed, reason, applied = enforce_local_egress(
            verdict, backend,
            block_local_when_denied=self.block_local_when_denied)
        if not allowed:
            return EgressDecision(allowed=False, reason=reason,
                                  block_local_applied=applied, broker=broker)
        base = os.environ if base_env is None else base_env
        env, masked, dropped, invalid = build_child_env(
            base, broker=broker, mask_credentials=self.mask_credentials)
        if invalid:
            # 脏 base：空环境执行仍可能被命令依赖 PATH，但绝不继承父进程凭据。
            # 保持 allowed=True 由上层决定，理由写进审计。
            reason = (reason + " | egress: base env 非法, 使用空环境"
                      " (fail-closed, 不继承父进程变量)").strip(" |")
        return EgressDecision(allowed=True, reason=reason, env=env,
                              masked_names=masked, dropped_names=dropped,
                              invalid_base=invalid,
                              block_local_applied=applied, broker=broker)
