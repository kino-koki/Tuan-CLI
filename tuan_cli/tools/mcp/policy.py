"""E1: MCP server 信任分级 —— 持久化权限域 + 调用前工具级授权 + 会话内可回撤。

为什么需要这一层:
`tools/mcp/security.py` 只扫描**工具描述/参数**里的注入文本, 属于"内容层"检测;
但它不回答一个更基础的问题 —— **这台 server 到底被允许做什么**。此前所有 MCP
调用只过外层 `mcp_call` 的一刀切权限: 要么全放行, 要么全拒绝, 无法表达
"filesystem server 只读、允许 read_file 不允许 write_file、只允许访问内网域名"。

设计约束 (与本项目既有 fail-closed 口径一致):
- **默认 untrusted**: 未登记的 server 一律拒绝, 必须由用户显式确认信任等级后才可用。
  绝不因为"第一次见到"就临时放行 —— 那正是 TrustFall 类攻击的入口。
- **deny 优先**: tool_denylist > tool_allowlist > tier 默认; 与 permissions.rules
  的 deny > ask > allow 保持一致。
- **会话内可回撤**: `revoke_session()` 后立刻重新要求确认, 不需要重启进程。
  上一轮的路标里特别标了"会话内可回撤", 就是针对"确认过一次就永远信任"的提权风险。
- **损坏即拒绝**: 策略文件损坏 / 版本不认识时**不重建为默认值**, 而是进入
  locked 状态拒绝所有调用。旧实现里 `except: pass -> {}` 的"静默重置"在这里不能重演。
- 与 E6 的 `mcp__<server>__<tool>` 规范化名共用同一套 server/tool 提取逻辑。
"""
from __future__ import annotations

import fnmatch
import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

log = logging.getLogger(__name__)

_POLICY_VERSION = 1


# ============================================================ 信任等级

class ServerTier:
    UNTRUSTED = "untrusted"   # 未登记 / 默认: 拒绝一切
    LIMITED = "limited"       # 需逐工具确认
    READONLY = "readonly"     # 只读工具自动放行, 写工具拒绝
    TRUSTED = "trusted"       # 按 allowlist 自动放行

    ALL = (UNTRUSTED, LIMITED, READONLY, TRUSTED)


# 只读工具名启发式: 用于 READONLY 档的自动放行判定。
# 只认"名字明确表示只读"的; 名字含糊的一律不放行 (fail-closed)。
_READONLY_PREFIXES = (
    "read_", "get_", "list_", "fetch_", "search_", "query_", "show_",
    "describe_", "stat_", "inspect_", "view_", "count_", "exists_",
    "check_", "find_", "lookup_", "peek_", "head_", "tail_",
)
# 名字里出现这些词, 即便带只读前缀也不自动放行
_WRITE_HINTS = (
    "write", "delete", "remove", "create", "update", "set_", "put_",
    "patch", "exec", "run", "shell", "send", "post", "upload", "install",
    "apply", "commit", "push", "kill", "drop", "truncate", "grant",
)


def is_readonly_tool(tool: str) -> bool:
    name = str(tool or "").lower()
    if not name:
        return False
    if any(h in name for h in _WRITE_HINTS):
        return False
    return name.startswith(_READONLY_PREFIXES) or name in (
        "read", "list", "get", "search", "fetch", "stat", "help", "ping",
    )


# ============================================================ 策略记录

@dataclass
class ServerPolicy:
    """一台 MCP server 的权限域。"""

    server: str
    tier: str = ServerTier.UNTRUSTED
    read_only: bool = True
    tool_allowlist: List[str] = field(default_factory=list)
    tool_denylist: List[str] = field(default_factory=list)
    allowed_domains: List[str] = field(default_factory=list)
    max_calls_per_session: int = 0        # 0 = 不限
    require_confirm: bool = False
    granted_at: float = 0.0
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ServerPolicy":
        tier = str(d.get("tier", ServerTier.UNTRUSTED)).lower()
        if tier not in ServerTier.ALL:
            # 不认识的等级不能当成 trusted, 降级为最严格档
            tier = ServerTier.UNTRUSTED
        return cls(
            server=str(d.get("server", "")),
            tier=tier,
            read_only=bool(d.get("read_only", True)),
            tool_allowlist=[str(x) for x in (d.get("tool_allowlist") or [])],
            tool_denylist=[str(x) for x in (d.get("tool_denylist") or [])],
            allowed_domains=[str(x) for x in (d.get("allowed_domains") or [])],
            max_calls_per_session=int(d.get("max_calls_per_session", 0) or 0),
            require_confirm=bool(d.get("require_confirm", False)),
            granted_at=float(d.get("granted_at", 0) or 0),
            note=str(d.get("note", "")),
        )


@dataclass(frozen=True)
class AuthorizationDecision:
    """一次调用前授权的结果。action: allow | confirm | deny。"""
    action: str
    reason: str
    tier: str = ServerTier.UNTRUSTED
    server: str = ""
    tool: str = ""

    @property
    def allowed(self) -> bool:
        return self.action == "allow"

    def to_dict(self) -> Dict[str, Any]:
        return {"action": self.action, "reason": self.reason,
                "tier": self.tier, "server": self.server, "tool": self.tool}


# ============================================================ 策略存储

class MCPPolicyStore:
    """MCP server 信任策略的持久化存储 + 会话授权状态。

    用法::

        store = MCPPolicyStore(home=Path("~/.tuan"), session_id="s1")
        store.grant("filesystem", ServerTier.READONLY,
                    tool_allowlist=["read_file", "list_dir"])
        d = store.authorize("filesystem", "write_file", {})
        assert d.action == "deny"
        store.revoke_session("filesystem")   # 会话内回撤
    """

    def __init__(self, home: Optional[Path] = None, session_id: str = "",
                 now_fn: Optional[Any] = None) -> None:
        self._home = Path(home) if home else Path.home() / ".tuan"
        self._path = self._home / "mcp_server_policy.json"
        self._session_id = str(session_id or "default")
        self._now = now_fn or time.time
        self._lock = threading.Lock()
        self._policies: Dict[str, ServerPolicy] = {}
        # 会话内授权: session -> {(server, tool)} ; 空 tool 表示整台 server
        self._grants: Dict[str, Set[Tuple[str, str]]] = {}
        # 会话内拒绝/回撤: 优先级高于 anything, 用于"立刻反悔"
        self._revoked: Dict[str, Set[Tuple[str, str]]] = {}
        self._call_counts: Dict[str, int] = {}
        self._locked = False
        self._locked_reason = ""
        self._load()

    # ------------------------------------------------------------ 持久化
    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("策略文件顶层不是对象")
            version = int(data.get("version", 0))
            if version != _POLICY_VERSION:
                raise ValueError(f"策略文件版本 {version} 不受支持 (期望 {_POLICY_VERSION})")
            raw = data.get("servers", {})
            if not isinstance(raw, dict):
                raise ValueError("servers 段不是对象")
            for name, d in raw.items():
                if not isinstance(d, dict):
                    raise ValueError(f"server {name!r} 的策略不是对象")
                p = ServerPolicy.from_dict(d)
                p.server = str(name)
                self._policies[str(name)] = p
        except Exception as exc:  # noqa: BLE001
            # 关键: 损坏/版本不符时**不重建为空策略**。空策略看起来像"没有限制",
            # 而实际语义应是"无法验证 -> 拒绝一切"。进入 locked 直到人工修复。
            self._locked = True
            self._locked_reason = (
                f"MCP 策略文件不可信 ({type(exc).__name__}: {exc}); "
                f"fail-closed 锁定所有 MCP 调用, 请检查 {self._path}"
            )
            log.warning("%s", self._locked_reason)

    def _save(self) -> None:
        from ...core.atomicio import atomic_write_text
        payload = {
            "version": _POLICY_VERSION,
            "servers": {name: p.to_dict() for name, p in self._policies.items()},
        }
        atomic_write_text(self._path,
                          json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        try:
            self._home.mkdir(parents=True, exist_ok=True)
            import os
            os.chmod(self._path, 0o600)
        except OSError:
            pass

    @property
    def locked(self) -> bool:
        return self._locked

    @property
    def locked_reason(self) -> str:
        return self._locked_reason

    def unlock(self) -> bool:
        """人工确认修复后解除锁定 (会重新尝试加载)。"""
        with self._lock:
            self._locked = False
            self._locked_reason = ""
            self._policies.clear()
            self._load()
            return not self._locked

    # ------------------------------------------------------------ 策略管理
    def get(self, server: str) -> ServerPolicy:
        with self._lock:
            return self._policies.get(server) or ServerPolicy(server=server)

    def list_policies(self) -> List[ServerPolicy]:
        with self._lock:
            return [ServerPolicy.from_dict(p.to_dict()) for p in self._policies.values()]

    def grant(self, server: str, tier: str, *, read_only: bool = True,
              tool_allowlist: Optional[List[str]] = None,
              tool_denylist: Optional[List[str]] = None,
              allowed_domains: Optional[List[str]] = None,
              max_calls_per_session: int = 0,
              require_confirm: bool = False, note: str = "") -> ServerPolicy:
        """显式授予一台 server 的信任等级与权限域 (由用户确认后调用)。"""
        tier = str(tier).lower()
        if tier not in ServerTier.ALL:
            raise ValueError(f"未知信任等级: {tier}")
        if tier == ServerTier.TRUSTED and not (tool_allowlist or []):
            # trusted 却没有白名单 = 全放行, 这是最典型的过宽授权。
            # 不静默改成 limited, 直接要求调用方写明白名单。
            raise ValueError("trusted 档必须显式提供 tool_allowlist (禁止全放行)")
        p = ServerPolicy(
            server=server, tier=tier, read_only=bool(read_only),
            tool_allowlist=list(tool_allowlist or []),
            tool_denylist=list(tool_denylist or []),
            allowed_domains=list(allowed_domains or []),
            max_calls_per_session=max(0, int(max_calls_per_session)),
            require_confirm=bool(require_confirm),
            granted_at=float(self._now()), note=str(note or ""),
        )
        with self._lock:
            if self._locked:
                raise RuntimeError(self._locked_reason)
            self._policies[server] = p
            self._save()
        return p

    def revoke_server(self, server: str) -> bool:
        """撤销一台 server 的持久化信任 (回到默认 untrusted)。"""
        with self._lock:
            if self._locked:
                return False
            if server not in self._policies:
                return False
            del self._policies[server]
            self._save()
        self.revoke_session(server)
        return True

    # ------------------------------------------------------------ 会话授权
    def grant_session(self, server: str, tool: str = "", *,
                      session_id: Optional[str] = None) -> None:
        """会话内临时授权 (不写盘, 进程结束即失效)。"""
        sid = str(session_id or self._session_id)
        key = (server, str(tool or ""))
        with self._lock:
            self._grants.setdefault(sid, set()).add(key)
            self._revoked.get(sid, set()).discard(key)

    def revoke_session(self, server: Optional[str] = None, tool: Optional[str] = None,
                       *, session_id: Optional[str] = None) -> int:
        """会话内回撤。`server=None` 表示回撤本会话全部授权。

        回撤即刻生效: 后续 authorize 会重新走确认, 不需要重启进程。
        """
        sid = str(session_id or self._session_id)
        n = 0
        with self._lock:
            grants = self._grants.setdefault(sid, set())
            if server is None:
                n = len(grants)
                for s, t in list(grants):
                    self._revoked.setdefault(sid, set()).add((s, t))
                grants.clear()
            else:
                for s, t in list(grants):
                    if s == server and (tool is None or t == tool):
                        grants.discard((s, t))
                        self._revoked.setdefault(sid, set()).add((s, t))
                        n += 1
                # 即便没有现存 grant, 也记一条显式回撤, 防止之后被 grant_session 覆盖
                self._revoked.setdefault(sid, set()).add(
                    (server, str(tool or "")))
            self._call_counts.pop(sid, None)
        return n

    def session_state(self, *, session_id: Optional[str] = None) -> Dict[str, Any]:
        sid = str(session_id or self._session_id)
        with self._lock:
            return {
                "session_id": sid,
                "grants": sorted([list(x) for x in self._grants.get(sid, set())]),
                "revoked": sorted([list(x) for x in self._revoked.get(sid, set())]),
                "call_count": self._call_counts.get(sid, 0),
            }

    # ------------------------------------------------------------ 授权判定
    @staticmethod
    def _matches(tool: str, patterns: List[str]) -> bool:
        return any(fnmatch.fnmatch(tool.lower(), str(p).lower()) for p in patterns)

    @staticmethod
    def _extract_domains(args: Dict[str, Any]) -> List[str]:
        """从参数里抽出 URL 的 host (用于 allowed_domains 校验)。"""
        from urllib.parse import urlparse
        out: List[str] = []
        for v in args.values():
            if isinstance(v, str) and ("://" in v or v.startswith("www.")):
                try:
                    host = urlparse(v if "://" in v else "https://" + v).hostname
                    if host:
                        out.append(host.lower())
                except Exception:  # noqa: BLE001
                    continue
            elif isinstance(v, dict):
                out.extend(MCPPolicyStore._extract_domains(v))
        return out

    def authorize(self, server: str, tool: str,
                  args: Optional[Dict[str, Any]] = None, *,
                  session_id: Optional[str] = None) -> AuthorizationDecision:
        """调用前工具级授权。异常/不可验证一律 deny (fail-closed)。"""
        sid = str(session_id or self._session_id)
        args = args or {}
        try:
            if self._locked:
                return AuthorizationDecision("deny", self._locked_reason,
                                             ServerTier.UNTRUSTED, server, tool)
            policy = self.get(server)

            # 1) 未登记 server: 默认 untrusted -> 拒绝, 必须先显式 grant
            if policy.tier == ServerTier.UNTRUSTED:
                return AuthorizationDecision(
                    "deny",
                    f"MCP server {server!r} 未登记信任等级 (默认 untrusted); "
                    f"请先确认并授予权限域后再调用",
                    ServerTier.UNTRUSTED, server, tool)

            # 2) 会话内回撤优先: 一旦回撤, 立刻重新要求确认
            with self._lock:
                revoked = (server, "") in self._revoked.get(sid, set()) or \
                          (server, tool) in self._revoked.get(sid, set())
            if revoked:
                return AuthorizationDecision(
                    "confirm",
                    f"会话内已回撤 {server}::{tool or '*'} 的授权, 需重新确认",
                    policy.tier, server, tool)

            # 3) deny 优先于 allow (与 permissions.rules 一致)
            if self._matches(tool, policy.tool_denylist):
                return AuthorizationDecision(
                    "deny", f"工具 {tool!r} 在 {server} 的 tool_denylist 中",
                    policy.tier, server, tool)

            # 4) read_only 档: 写工具直接拒绝 (不弹确认, 权限域之外)
            if policy.tier == ServerTier.READONLY and not is_readonly_tool(tool):
                return AuthorizationDecision(
                    "deny",
                    f"server {server} 为 readonly 档, 工具 {tool!r} 非只读, 拒绝",
                    policy.tier, server, tool)

            # 5) 域名校验
            if policy.allowed_domains:
                hosts = self._extract_domains(args)
                bad = [h for h in hosts
                       if not any(fnmatch.fnmatch(h, d.lower())
                                  for d in policy.allowed_domains)]
                if bad:
                    return AuthorizationDecision(
                        "deny", f"参数含非白名单域名: {', '.join(bad[:3])}",
                        policy.tier, server, tool)

            # 6) 会话调用配额
            if policy.max_calls_per_session > 0:
                with self._lock:
                    used = self._call_counts.get(sid, 0)
                    if used >= policy.max_calls_per_session:
                        return AuthorizationDecision(
                            "deny",
                            f"server {server} 本会话调用已达上限 "
                            f"{policy.max_calls_per_session}",
                            policy.tier, server, tool)

            # 7) 会话内临时授权
            with self._lock:
                granted = ((server, "") in self._grants.get(sid, set())
                           or (server, tool) in self._grants.get(sid, set()))
            if granted:
                self._bump(sid, policy)
                return AuthorizationDecision(
                    "allow", "会话内临时授权", policy.tier, server, tool)

            # 8) 按档位裁决
            if policy.require_confirm or policy.tier == ServerTier.LIMITED:
                return AuthorizationDecision(
                    "confirm", f"server {server} 为 {policy.tier} 档, 工具调用需逐次确认",
                    policy.tier, server, tool)
            if policy.tool_allowlist:
                if self._matches(tool, policy.tool_allowlist):
                    self._bump(sid, policy)
                    return AuthorizationDecision(
                        "allow", f"命中 {server} 的 tool_allowlist", policy.tier, server, tool)
                return AuthorizationDecision(
                    "deny", f"工具 {tool!r} 不在 {server} 的 tool_allowlist 中",
                    policy.tier, server, tool)
            if policy.tier == ServerTier.READONLY and is_readonly_tool(tool):
                self._bump(sid, policy)
                return AuthorizationDecision(
                    "allow", "readonly 档只读工具", policy.tier, server, tool)
            # 兜底: 任何没明说放行的组合都要求确认, 绝不隐式 allow
            return AuthorizationDecision(
                "confirm", f"server {server} 的 {policy.tier} 档未覆盖该调用, 需确认",
                policy.tier, server, tool)
        except Exception as exc:  # noqa: BLE001
            return AuthorizationDecision(
                "deny", f"MCP 授权判定异常 (fail-closed): {type(exc).__name__}: {exc}",
                ServerTier.UNTRUSTED, server, tool)

    def _bump(self, sid: str, policy: ServerPolicy) -> None:
        if policy.max_calls_per_session > 0:
            with self._lock:
                self._call_counts[sid] = self._call_counts.get(sid, 0) + 1

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            tiers: Dict[str, int] = {}
            for p in self._policies.values():
                tiers[p.tier] = tiers.get(p.tier, 0) + 1
            return {
                "servers": len(self._policies),
                "by_tier": tiers,
                "locked": self._locked,
                "locked_reason": self._locked_reason,
                "policy_file": str(self._path),
                "active_sessions": len(self._grants),
            }


# ============================================================ 全局单例

_global_store: Optional[MCPPolicyStore] = None
_global_lock = threading.Lock()


def get_mcp_policy_store(home: Optional[Path] = None,
                         session_id: str = "") -> MCPPolicyStore:
    """进程级单例 (避免每个工具调用都重读磁盘)。"""
    global _global_store
    with _global_lock:
        if _global_store is None:
            _global_store = MCPPolicyStore(home=home, session_id=session_id)
        return _global_store


def reset_global_store() -> None:
    """测试 / 切换 session 时用。"""
    global _global_store
    with _global_lock:
        _global_store = None
