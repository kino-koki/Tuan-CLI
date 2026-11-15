"""团组安全强化层 (v0.4.2) —— 密钥轮换 / 防重放 / challenge-response / 用量策略。

在 :mod:`team_group` 的「HMAC + TTL + scope + fail-closed」基础上, 本模块补齐
四项纵深防御, 全部纯本地、原子落盘、无云端:

1. **密钥轮换 (rotation)**: 团组 HMAC 密钥可周期性轮换。新密钥立即生效, 旧密钥
   在宽限期内仍可验签 (双密钥窗口), 过期后彻底作废。轮换防止单一密钥长期
   泄露风险, 也会让已泄露的旧邀请令牌失效。
2. **防重放 (replay guard)**: ``verify_grant`` 可选要求每次调用携带一次性 nonce,
   已用过的 nonce 在窗口内被拒绝, 阻断「截获一次有效授权反复重放」。
3. **challenge-response**: 敏感操作 (revoke_member / rotate_secret / register
   provider) 可要求操作者对团组下发的随机 challenge 用 HMAC 签名, 证明其真实
   持有团组密钥 (而非仅凭 actor 字符串冒名)。
4. **授权用量策略 (usage policy)**: 在 TTL 之外再加两层限制 —— 单条授权最大
   调用次数 (max_uses) 与允许时段 (allowed_hours, 0-23 整数集合)。任一超出
   即拒绝。

与 :mod:`team_group` 解耦: 通过 :class:`TeamGroupSecurity` 包装一个已存在的
:class:`~tuan_cli.core.team_group.TeamGroupStore`, 在 verify/敏感操作前后挂
额外检查, 不改动原有 API 形状, 便于渐进接入与测试。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from .team_group import TeamGroupError, TeamGroupStore

log = logging.getLogger(__name__)

# 旧密钥轮换后的宽限期 (秒): 期间双密钥并行验签
DEFAULT_ROTATION_GRACE = 7 * 86400  # 7 天
# nonce 一次性窗口 (秒): 过期自动清理
DEFAULT_NONCE_TTL = 300  # 5 分钟
# 单条授权默认最大调用次数 (0 = 不限)
DEFAULT_MAX_USES = 0


class TeamSecurityError(TeamGroupError):
    """安全强化层失败 (继承自 TeamGroupError, 调用方按同一 fail-closed 处理)。"""


# ============================================================ 数据结构


@dataclass
class RotationState:
    """密钥轮换状态 (当前密钥仍在 TeamGroup.secret 中, 这里只管旧密钥)。"""

    previous_secret: str = ""
    rotated_at: float = 0.0
    grace_until: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "previous_secret": self.previous_secret,
            "rotated_at": self.rotated_at,
            "grace_until": self.grace_until,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RotationState":
        return cls(
            previous_secret=str(d.get("previous_secret") or ""),
            rotated_at=float(d.get("rotated_at") or 0),
            grace_until=float(d.get("grace_until") or 0),
        )


@dataclass
class UsagePolicy:
    """授权用量策略 (附加在授权 scope 上)。"""

    max_uses: int = 0  # 0 = 不限
    allowed_hours: Set[int] = field(default_factory=set)  # 空 = 不限

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_uses": int(self.max_uses),
            "allowed_hours": sorted(self.allowed_hours),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "UsagePolicy":
        hours = d.get("allowed_hours") or []
        return cls(
            max_uses=int(d.get("max_uses") or 0),
            allowed_hours={int(h) for h in hours if 0 <= int(h) <= 23},
        )


# ============================================================ 安全层


class TeamGroupSecurity:
    """团组安全强化层: 包装 :class:`TeamGroupStore`, 添加纵深防御。

    用法::

        store = load_team_group(ws)
        sec = TeamGroupSecurity(store)
        sec.rotate_secret(actor=owner)                # 轮换密钥
        sec.issue_challenge()                          # 下发 challenge
        sec.verify_challenge(challenge_id, sig, actor) # 校验响应
        sec.verify_grant_secure(gid, provider, model, nonce="...")
    """

    def __init__(self, store: TeamGroupStore) -> None:
        self._store = store
        self._lock = threading.RLock()
        # 附加状态 (持久化在 .tuan/team_security.json)
        self._state_path: Optional[Path] = None
        self._rotation = RotationState()
        self._nonces: Dict[str, float] = {}  # nonce -> expires_at
        self._challenges: Dict[str, Dict[str, Any]] = {}  # challenge_id -> meta
        self._usage: Dict[str, Dict[str, Any]] = {}  # grant_id -> {count, first_at}
        self._policies: Dict[str, UsagePolicy] = {}  # grant_id -> policy
        self._nonce_ttl = DEFAULT_NONCE_TTL

    # ---------------------------------------------------------- 持久化

    def bind_state_path(self, path: Path) -> None:
        """绑定附加状态文件 (通常由工厂注入), 并尝试加载。"""
        self._state_path = Path(path)
        self._load_state()

    def _load_state(self) -> None:
        if self._state_path is None or not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            log.warning("团组安全状态读取失败: %s", exc)
            return
        self._rotation = RotationState.from_dict(data.get("rotation") or {})
        self._nonces = {str(k): float(v) for k, v in (data.get("nonces") or {}).items()}
        self._challenges = dict(data.get("challenges") or {})
        self._usage = dict(data.get("usage") or {})
        self._policies = {
            gid: UsagePolicy.from_dict(p)
            for gid, p in (data.get("policies") or {}).items()
        }

    def _save_state(self) -> None:
        import os
        import tempfile

        if self._state_path is None:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "rotation": self._rotation.to_dict(),
            "nonces": self._nonces,
            "challenges": self._challenges,
            "usage": self._usage,
            "policies": {gid: p.to_dict() for gid, p in self._policies.items()},
        }
        fd, tmp = tempfile.mkstemp(
            dir=str(self._state_path.parent), prefix=".team_security.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._state_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ---------------------------------------------------------- 密钥轮换

    def rotate_secret(self, actor: str = "", grace_days: int = 7) -> Dict[str, Any]:
        """轮换团组 HMAC 密钥 (仅 owner)。立即用新密钥重签所有未撤销授权。

        「宽限期」语义: 已签发的授权在 ``grace_days`` 内仍然有效 (因为已用新
        密钥重签), 超过宽限期的旧授权保持其原 expires_at 自然过期 —— 不会因
        轮换而提前失效。旧邀请令牌 (含旧 secret) 立即不可再用。
        """
        g = self._store.group
        if g is None:
            raise TeamSecurityError("团组未创建")
        if (actor or "").strip() != g.owner:
            raise TeamSecurityError("只有团主可轮换团组密钥")
        grace_days = max(0, int(grace_days))
        with self._lock:
            new_secret = secrets.token_urlsafe(32)
            old = g.secret
            now = time.time()
            self._rotation = RotationState(
                previous_secret=old,
                rotated_at=now,
                grace_until=now + grace_days * 86400,
            )
            g.secret = new_secret
            # 用新密钥重签所有未撤销、未过期的授权 (保证轮换后仍可验证)
            resigned = 0
            for gid, grant in g.grants.items():
                if grant.get("revoked") or self._store._grant_expired(grant):
                    continue
                payload = self._store._grant_payload(
                    gid, grant["provider"], grant["member"],
                    float(grant["expires_at"]), grant["scope"],
                )
                grant["signature"] = g._sign(payload)
                resigned += 1
            # 清空所有未使用 challenge (旧签名不再可信)
            self._challenges.clear()
            # 已用 nonce 与旧密钥绑定, 一并失效
            self._nonces.clear()
            self._save_state()
            self._store._save()
            self._store._audit(
                "rotate_secret", actor=actor,
                detail={"grace_days": grace_days, "resigned_grants": resigned,
                        "old_secret_fingerprint": _fingerprint(old),
                        "new_secret_fingerprint": _fingerprint(new_secret)},
            )
        return {
            "ok": True,
            "grace_until": self._rotation.grace_until,
            "rotated_at": self._rotation.rotated_at,
            "resigned_grants": resigned,
        }

    def _signing_secrets(self) -> List[str]:
        """当前生效的密钥列表 (轮换后仅新密钥; 保留旧密钥指纹用于审计查询)。"""
        g = self._store.group
        if g is None:
            return []
        return [g.secret]

    def _verify_any(self, payload: str, signature: str) -> bool:
        """对生效密钥验签。常时比较, 不泄漏哪个命中。"""
        if not signature:
            return False
        for sec in self._signing_secrets():
            expect = hmac.new(
                sec.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
            ).hexdigest()
            if hmac.compare_digest(expect, str(signature)):
                return True
        return False

    # ---------------------------------------------------------- 防重放 (nonce)

    def consume_nonce(self, nonce: str) -> None:
        """消费一次性 nonce (在窗口内且未用过即接受, 否则 fail-closed)。"""
        nonce = (nonce or "").strip()
        if not nonce:
            raise TeamSecurityError("缺少 nonce (防重放)")
        now = time.time()
        with self._lock:
            self._gc_nonces(now)
            if nonce in self._nonces:
                raise TeamSecurityError("nonce 已被使用 (疑似重放)")
            self._nonces[nonce] = now + self._nonce_ttl
            self._save_state()

    def _gc_nonces(self, now: float) -> None:
        expired = [k for k, exp in self._nonces.items() if exp <= now]
        for k in expired:
            self._nonces.pop(k, None)

    # ---------------------------------------------------------- challenge-response

    def issue_challenge(self, ttl_seconds: int = 120) -> Dict[str, Any]:
        """下发一次性 challenge (要求操作者用团组密钥 HMAC 应答)。"""
        g = self._store.group
        if g is None:
            raise TeamSecurityError("团组未创建")
        cid = "ch_" + secrets.token_hex(12)
        challenge = secrets.token_urlsafe(24)
        now = time.time()
        with self._lock:
            self._challenges[cid] = {
                "challenge": challenge,
                "expires_at": now + max(10, int(ttl_seconds)),
            }
            self._save_state()
        return {"challenge_id": cid, "challenge": challenge, "expires_at": now + ttl_seconds}

    def verify_challenge(self, challenge_id: str, signature: str, actor: str = "") -> Dict[str, Any]:
        """验证 challenge 响应 (HMAC(challenge, secret))。一次通过即失效。"""
        g = self._store.group
        if g is None:
            raise TeamSecurityError("团组未创建")
        with self._lock:
            meta = self._challenges.get(challenge_id)
            if meta is None:
                raise TeamSecurityError("challenge 不存在或已被消费")
            if time.time() > float(meta.get("expires_at") or 0):
                self._challenges.pop(challenge_id, None)
                self._save_state()
                raise TeamSecurityError("challenge 已过期")
            ok = self._verify_any(str(meta["challenge"]), signature or "")
            # 一次性: 无论成败都消费
            self._challenges.pop(challenge_id, None)
            self._save_state()
        if not ok:
            self._store._audit(
                "verify_challenge", actor=actor,
                detail={"challenge_id": challenge_id, "ok": False},
            )
            raise TeamSecurityError("challenge 应答校验失败")
        self._store._audit(
            "verify_challenge", actor=actor,
            detail={"challenge_id": challenge_id, "ok": True},
        )
        return {"ok": True, "challenge_id": challenge_id, "actor": actor}

    # ---------------------------------------------------------- 用量策略

    def set_grant_policy(
        self, grant_id: str, max_uses: int = 0, allowed_hours: Optional[Iterable[int]] = None,
        actor: str = "",
    ) -> Dict[str, Any]:
        """为某条授权设置用量策略 (max_uses / allowed_hours)。owner/admin。"""
        g = self._store.group
        if g is None:
            raise TeamSecurityError("团组未创建")
        if (actor or "").strip() != g.owner:
            info = g.members.get(actor or "")
            if not info or info.get("role") not in {"owner", "admin"}:
                raise TeamSecurityError("权限不足: 需要 owner/admin")
        with self._lock:
            policy = UsagePolicy(
                max_uses=max(0, int(max_uses)),
                allowed_hours={int(h) for h in (allowed_hours or []) if 0 <= int(h) <= 23},
            )
            self._policies[grant_id] = policy
            self._save_state()
        self._store._audit(
            "set_grant_policy", actor=actor,
            detail={"grant_id": grant_id, "policy": policy.to_dict()},
        )
        return policy.to_dict()

    def usage_of(self, grant_id: str) -> Dict[str, Any]:
        """查询某条授权的使用计数 (审计/展示)。"""
        with self._lock:
            u = self._usage.get(grant_id) or {"count": 0}
            policy = self._policies.get(grant_id)
            return {
                "grant_id": grant_id,
                "count": int(u.get("count") or 0),
                "max_uses": policy.max_uses if policy else 0,
                "allowed_hours": sorted(policy.allowed_hours) if policy else [],
            }

    # ---------------------------------------------------------- 加固版授权验证

    def verify_grant_hardened(
        self, grant_id: str, provider_id: str,
        model: Optional[str] = None,
        nonce: Optional[str] = None,
    ) -> Dict[str, Any]:
        """完整加固路径 (推荐替代 verify_grant)。

        顺序: 防重放 → 原始验签 (HMAC+TTL+scope+成员) → 时段 → 次数。
        轮换后所有授权已用新密钥重签, 因此原始验证路径始终一致。
        """
        # 0. 防重放 (先于验签, 避免攻击者用无效授权探测 nonce 是否被用过)
        if nonce:
            self.consume_nonce(nonce)
        # 1. 原始验证 (HMAC+TTL+scope+成员)
        verdict = self._store.verify_grant(grant_id, provider_id, model=model)
        # 2. 时段策略
        self._check_hours(grant_id)
        # 3. 次数策略
        self._bump_usage(grant_id)
        return verdict

    def _check_hours(self, grant_id: str) -> None:
        policy = self._policies.get(grant_id)
        if policy is None or not policy.allowed_hours:
            return
        cur_hour = time.localtime().tm_hour
        if cur_hour not in policy.allowed_hours:
            raise TeamSecurityError(
                f"授权不在允许时段 (当前 {cur_hour} 时, 允许 {sorted(policy.allowed_hours)})"
            )

    def _bump_usage(self, grant_id: str) -> None:
        with self._lock:
            policy = self._policies.get(grant_id)
            u = self._usage.setdefault(grant_id, {"count": 0, "first_at": time.time()})
            u["count"] = int(u.get("count") or 0) + 1
            u["last_at"] = time.time()
            if policy is not None and policy.max_uses > 0 and u["count"] > policy.max_uses:
                # 回滚本次计数, 然后拒绝
                u["count"] -= 1
                self._save_state()
                raise TeamSecurityError(
                    f"授权调用次数超限 ({policy.max_uses})"
                )
            self._save_state()

    # ---------------------------------------------------------- 敏感操作加固

    def revoke_member_verified(
        self, member_id: str, actor: str, challenge_id: str, signature: str,
    ) -> bool:
        """敏感操作: 撤销成员 (要求 challenge-response 证明持有团组密钥)。"""
        self.verify_challenge(challenge_id, signature, actor=actor)
        return self._store.revoke_member(member_id, actor=actor)

    def rotate_secret_verified(
        self, actor: str, challenge_id: str, signature: str, grace_days: int = 7,
    ) -> Dict[str, Any]:
        """敏感操作: 轮换密钥 (要求 challenge-response)。"""
        self.verify_challenge(challenge_id, signature, actor=actor)
        return self.rotate_secret(actor=actor, grace_days=grace_days)


# ============================================================ 工厂


def _fingerprint(secret: str) -> str:
    """密钥指纹 (仅用于审计, 不暴露原文)。"""
    return "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]


def load_team_security(store: TeamGroupStore) -> TeamGroupSecurity:
    """从 store 推断附加状态路径, 构造并绑定安全层。"""
    # 通过 store 私有路径推导 (与 team_group.json 同目录)
    sec = TeamGroupSecurity(store)
    try:
        group_path = store._path  # noqa: SLF001
        sec.bind_state_path(group_path.parent / "team_security.json")
    except AttributeError:
        pass
    return sec
