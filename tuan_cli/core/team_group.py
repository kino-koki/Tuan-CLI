"""团组 (TeamGroup) —— Tuan 的团队核心 (v0.4.2)。

「团组」是 Tuan 中「团队」的一等概念: 一群人 (最多 100 人) 在**纯本地**的
环境里共享算力供应商/模型, 而不经过任何云端中转。核心安全不变量:

1. **key 所有权**: 每个供应商凭证 (API key) 都属于某个成员 (owner)。
   其它成员要用, 必须由 owner **显式签发授权 (Grant)**。
2. **使用前验证**: 授权是 owner 用团组密钥 HMAC 签名的令牌, 使用前必须
   验签 + 校验 TTL + 校验 scope, 任一不满足即 fail-closed 拒绝。
3. **时限**: 单条授权最长 90 天 (≤3 月), 过期自动失效。
4. **纯本地**: 团组密钥、成员清单、授权全部落在
   ``<workspace>/.tuan/team_group.json``, 不上传任何第三方。
5. **远程 + 局域网**: 授权令牌可离线验证 (只要持有团组密钥), 因此既支持
   同机、也支持局域网/远程成员互认 —— 不需要中心服务器在线。

数据模型 (全部纯本地 JSON):
- 团组: id / name / secret (HMAC 密钥) / created_at / owner
- 成员: member_id / display_name / role / public_key_fingerprint / joined_at / revoked
- 授权: grant_id / owner / scope (provider/model) / member / expires_at / signature

设计对齐既有 fail-closed 风格 (见 web_sessions_auth.py): 原子写、
``hmac.compare_digest`` 常时比较、永不返回敏感原文、越权即拒绝。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# 团组容量上限 (goal: 最大一个团组支持 100 人)
MAX_MEMBERS = 100
# 单条授权最长时限: 90 天 (goal: 最高 3 月)
MAX_GRANT_DAYS = 90
_DAY = 86400


class TeamGroupError(Exception):
    """团组操作失败 (fail-closed 语义, 调用方据 message 拒绝)。"""


# ============================================================ 团组


@dataclass
class TeamGroup:
    """一个团组的本地持久化状态。"""

    group_id: str
    name: str
    secret: str  # HMAC-SHA256 密钥 (纯本地, 绝不外传)
    owner: str  # 团主 member_id
    created_at: float = field(default_factory=time.time)
    members: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    grants: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # 已签发但本机不持有原文的供应商凭证 (owner 录入时只留指纹, 原文进本机 keyring/环境)
    provider_keys: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # ---------------------------------------------------------- 持久化

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "name": self.name,
            "secret": self.secret,
            "owner": self.owner,
            "created_at": self.created_at,
            "members": self.members,
            "grants": self.grants,
            "provider_keys": self.provider_keys,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TeamGroup":
        return cls(
            group_id=str(data.get("group_id") or ""),
            name=str(data.get("name") or ""),
            secret=str(data.get("secret") or ""),
            owner=str(data.get("owner") or ""),
            created_at=float(data.get("created_at") or time.time()),
            members=dict(data.get("members") or {}),
            grants=dict(data.get("grants") or {}),
            provider_keys=dict(data.get("provider_keys") or {}),
        )

    # ---------------------------------------------------------- 签名

    def _sign(self, payload: str) -> str:
        """HMAC-SHA256 签名 (纯本地密钥)。"""
        return hmac.new(
            self.secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def _verify_sig(self, payload: str, signature: str) -> bool:
        if not signature:
            return False
        return hmac.compare_digest(self._sign(payload), str(signature))


# ============================================================ 密钥库


class TeamGroupStore:
    """团组密钥库: 创建/成员/供应商/授权 + 验证。

    全部操作纯本地, 原子落盘。验证路径 (verify_grant) 是安全关键:
    任何一项不满足即抛 :class:`TeamGroupError`, 绝不「宽松通过」。
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._group: Optional[TeamGroup] = None
        self._load()

    @property
    def _audit_path(self) -> Path:
        """审计日志: 与团组文件同目录的 JSONL 追加链 (纯本地)。"""
        return self._path.parent / "team_audit.jsonl"

    def _audit(self, action: str, actor: str = "", detail: Optional[Dict[str, Any]] = None) -> None:
        """追加一条审计记录 (JSONL, 时间降序追加)。写失败不阻断主流程。"""
        rec = {
            "ts": time.time(),
            "action": action,
            "actor": actor or (self._group.owner if self._group else ""),
        }
        if detail:
            rec["detail"] = detail
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError as exc:  # noqa: BLE001
            log.debug("团组审计写入失败 (不阻断): %s", exc)

    def read_audit(self, limit: int = 100) -> List[Dict[str, Any]]:
        """读取最近 ``limit`` 条审计 (时间降序)。"""
        p = self._audit_path
        if not p.exists():
            return []
        out: List[Dict[str, Any]] = []
        try:
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            return []
        return list(reversed(out))[: max(1, int(limit))]

    # ---------------------------------------------------------- 加载/落盘

    def _load(self) -> None:
        if not self._path.exists():
            self._group = None
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._group = TeamGroup.from_dict(data)
        except Exception as exc:  # noqa: BLE001
            log.warning("团组文件读取失败, 视为未创建: %s", exc)
            self._group = None

    def _save(self) -> None:
        if self._group is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self._path.parent), prefix=".team_group.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._group.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ---------------------------------------------------------- 创建/查询

    @property
    def group(self) -> Optional[TeamGroup]:
        return self._group

    def create_group(self, name: str, owner_member_id: str, owner_name: str = "") -> TeamGroup:
        """创建团组, owner 即首位成员 (角色 owner)。幂等于已存在时拒绝。"""
        if self._group is not None:
            raise TeamGroupError("团组已存在, 不可重复创建")
        name = (name or "").strip()
        if not name:
            raise TeamGroupError("团组名称不能为空")
        owner_member_id = (owner_member_id or "").strip()
        if not owner_member_id:
            raise TeamGroupError("团主 member_id 不能为空")
        self._group = TeamGroup(
            group_id="tg_" + secrets.token_hex(8),
            name=name,
            secret=secrets.token_urlsafe(32),
            owner=owner_member_id,
        )
        # owner 自动入组
        self._group.members[owner_member_id] = {
            "member_id": owner_member_id,
            "display_name": (owner_name or owner_member_id).strip() or owner_member_id,
            "role": "owner",
            "joined_at": time.time(),
            "revoked": False,
        }
        self._save()
        self._audit("create_group", actor=owner_member_id,
                    detail={"group_id": self._group.group_id, "name": name})
        return self._group

    def reset_group(self) -> None:
        """删除团组 (危险操作, 仅供测试/重建)。"""
        self._group = None
        if self._path.exists():
            self._path.unlink()

    def export_public(self) -> Dict[str, Any]:
        """对外快照 (不含 secret, 供 web/API 展示)。"""
        if self._group is None:
            return {"created": False}
        g = self._group
        return {
            "created": True,
            "group_id": g.group_id,
            "name": g.name,
            "owner": g.owner,
            "created_at": g.created_at,
            "member_count": sum(1 for m in g.members.values() if not m.get("revoked")),
            "max_members": MAX_MEMBERS,
        }

    # ---------------------------------------------------------- 成员

    def add_member(
        self, member_id: str, display_name: str = "", role: str = "member",
        actor: str = "",
    ) -> Dict[str, Any]:
        """加入成员 (仅 owner/admin 可操作)。上限 100 人, member_id 唯一。"""
        g = self._require_group()
        self._require_role(actor, {"owner", "admin"})
        member_id = (member_id or "").strip()
        if not member_id:
            raise TeamGroupError("member_id 不能为空")
        if member_id in g.members and not g.members[member_id].get("revoked"):
            raise TeamGroupError(f"成员已存在: {member_id}")
        role = role if role in {"owner", "admin", "member"} else "member"
        if role == "owner":
            raise TeamGroupError("owner 角色仅在创建时确定, 不可新增")
        active = sum(1 for m in g.members.values() if not m.get("revoked"))
        if active >= MAX_MEMBERS:
            raise TeamGroupError(f"团组成员已满 ({MAX_MEMBERS} 人上限)")
        info = {
            "member_id": member_id,
            "display_name": (display_name or member_id).strip() or member_id,
            "role": role,
            "joined_at": time.time(),
            "revoked": False,
        }
        g.members[member_id] = info
        self._save()
        self._audit("add_member", actor=actor, detail={"member": member_id, "role": role})
        return dict(info)

    def revoke_member(self, member_id: str, actor: str = "") -> bool:
        """移除成员 (软删除, 保留审计)。同时撤销其未过期授权。"""
        g = self._require_group()
        self._require_role(actor, {"owner", "admin"})
        info = g.members.get(member_id)
        if info is None:
            raise TeamGroupError(f"成员不存在: {member_id}")
        if member_id == g.owner:
            raise TeamGroupError("不可撤销团主")
        info["revoked"] = True
        info["revoked_at"] = time.time()
        # 连带撤销其授权
        for gid, grant in g.grants.items():
            if grant.get("member") == member_id and not self._grant_expired(grant):
                grant["revoked"] = True
                grant["revoked_at"] = time.time()
        self._save()
        self._audit("revoke_member", actor=actor, detail={"member": member_id})
        return True

    def list_members(self, include_revoked: bool = False) -> List[Dict[str, Any]]:
        g = self._require_group()
        out = []
        for m in g.members.values():
            if m.get("revoked") and not include_revoked:
                continue
            out.append({k: v for k, v in m.items() if k != "secret"})
        return out

    def get_member(self, member_id: str) -> Optional[Dict[str, Any]]:
        g = self._require_group()
        info = g.members.get(member_id)
        if info is None or info.get("revoked"):
            return None
        return dict(info)

    # ---------------------------------------------------------- 供应商凭证

    def register_provider_key(
        self, provider_id: str, key_fingerprint: str, owner: str, meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """owner 登记一个供应商凭证 (只存指纹, 不存原文)。

        原文 key 留在 owner 本机 (环境变量/keyring), 团组内只流转「可否使用」
        的签名授权 —— 这保证「无云端传 key」。
        """
        g = self._require_group()
        if (owner or "").strip() != g.owner:
            # 只有 owner 能录入凭证 (key 所有权)
            raise TeamGroupError("只有团主 (key 所有者) 可登记供应商凭证")
        provider_id = (provider_id or "").strip()
        if not provider_id:
            raise TeamGroupError("provider_id 不能为空")
        entry = {
            "provider_id": provider_id,
            "key_fingerprint": (key_fingerprint or "").strip(),
            "owner": g.owner,
            "registered_at": time.time(),
            "meta": dict(meta or {}),
        }
        g.provider_keys[provider_id] = entry
        self._save()
        self._audit("register_provider", actor=g.owner, detail={"provider": provider_id})
        return dict(entry)

    def list_providers(self) -> List[Dict[str, Any]]:
        g = self._require_group()
        return [dict(v) for v in g.provider_keys.values()]

    # ---------------------------------------------------------- 授权 (Grant)

    def issue_grant(
        self, provider_id: str, member: str, days: int,
        model_scope: Optional[List[str]] = None, owner: str = "",
    ) -> Dict[str, Any]:
        """owner 给成员签发供应商使用授权 (签名令牌, 时限 ≤90 天)。"""
        g = self._require_group()
        owner = (owner or "").strip() or g.owner
        if owner != g.owner:
            raise TeamGroupError("只有团主可签发授权")
        provider_id = (provider_id or "").strip()
        if provider_id not in g.provider_keys:
            raise TeamGroupError(f"供应商未登记: {provider_id}")
        target = g.members.get(member)
        if target is None or target.get("revoked"):
            raise TeamGroupError(f"目标成员无效或已移除: {member}")
        try:
            days = int(days)
        except (TypeError, ValueError):
            raise TeamGroupError("days 必须是整数天数")
        if days <= 0:
            raise TeamGroupError("授权时限必须为正")
        if days > MAX_GRANT_DAYS:
            raise TeamGroupError(f"授权时限超过上限 (最长 {MAX_GRANT_DAYS} 天 / 3 个月)")
        expires_at = time.time() + days * _DAY
        scope = {
            "provider": provider_id,
            "models": sorted({str(m) for m in (model_scope or []) if str(m).strip()}),
        }
        grant_id = "gr_" + secrets.token_hex(8)
        payload = self._grant_payload(grant_id, provider_id, member, expires_at, scope)
        grant = {
            "grant_id": grant_id,
            "owner": g.owner,
            "provider": provider_id,
            "member": member,
            "scope": scope,
            "issued_at": time.time(),
            "expires_at": expires_at,
            "days": days,
            "signature": g._sign(payload),
            "revoked": False,
        }
        g.grants[grant_id] = grant
        self._save()
        self._audit("issue_grant", actor=g.owner,
                    detail={"grant_id": grant_id, "provider": provider_id,
                            "member": member, "days": days})
        return dict(grant)

    def revoke_grant(self, grant_id: str, actor: str = "") -> bool:
        g = self._require_group()
        self._require_role(actor, {"owner", "admin"})
        grant = g.grants.get(grant_id)
        if grant is None:
            raise TeamGroupError(f"授权不存在: {grant_id}")
        grant["revoked"] = True
        grant["revoked_at"] = time.time()
        self._save()
        self._audit("revoke_grant", actor=actor, detail={"grant_id": grant_id})
        return True

    def list_grants(self, member: Optional[str] = None) -> List[Dict[str, Any]]:
        g = self._require_group()
        out = []
        for grant in g.grants.values():
            if member and grant.get("member") != member:
                continue
            out.append(dict(grant))
        return out

    def verify_grant(
        self, grant_id: str, provider_id: str, model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """**使用前验证**: 验签 + TTL + scope + 成员有效性, fail-closed。

        返回 ``{"ok": True, ...}`` 或抛 :class:`TeamGroupError`。
        这是「key 所有者验证 + 时限 + 纯本地」的安全咽喉。
        """
        g = self._require_group()
        grant = g.grants.get(grant_id)
        if grant is None:
            raise TeamGroupError("授权不存在")
        if grant.get("revoked"):
            raise TeamGroupError("授权已被撤销")
        # 验签 (防伪造/篡改)
        payload = self._grant_payload(
            grant["grant_id"], grant["provider"], grant["member"],
            float(grant["expires_at"]), grant["scope"],
        )
        if not g._verify_sig(payload, grant.get("signature", "")):
            raise TeamGroupError("授权签名校验失败 (可能被篡改)")
        # provider 匹配
        if str(grant.get("provider")) != str(provider_id):
            raise TeamGroupError("授权不适用于该供应商")
        # TTL
        if time.time() > float(grant["expires_at"]):
            raise TeamGroupError("授权已过期 (超过时限)")
        # 成员有效性
        member = g.members.get(grant["member"])
        if member is None or member.get("revoked"):
            raise TeamGroupError("授权对应成员已无效")
        # model scope (若授权限定了模型, 必须命中其一)
        models = list((grant.get("scope") or {}).get("models") or [])
        if models and model and str(model) not in models:
            raise TeamGroupError(f"授权不覆盖模型: {model}")
        self._audit("verify_grant", actor=grant["member"],
                    detail={"grant_id": grant_id, "provider": provider_id,
                            "model": model, "ok": True})
        return {
            "ok": True,
            "grant_id": grant_id,
            "provider": grant["provider"],
            "member": grant["member"],
            "owner": grant["owner"],
            "expires_at": grant["expires_at"],
            "models": models,
        }

    # ---------------------------------------------------------- 内部

    def _grant_expired(self, grant: Dict[str, Any]) -> bool:
        return time.time() > float(grant.get("expires_at") or 0)

    @staticmethod
    def _grant_payload(
        grant_id: str, provider: str, member: str, expires_at: float,
        scope: Dict[str, Any],
    ) -> str:
        """签名字符串: 字段规范化拼接 (scope 用 JSON 保证稳定)。"""
        scope_json = json.dumps(scope, sort_keys=True, ensure_ascii=False)
        return "|".join([grant_id, provider, member, f"{expires_at:.3f}", scope_json])

    def _require_group(self) -> TeamGroup:
        if self._group is None:
            raise TeamGroupError("团组未创建")
        return self._group

    def _require_role(self, actor: str, roles: set) -> None:
        g = self._require_group()
        if not actor:
            raise TeamGroupError("需要身份 (actor)")
        info = g.members.get(actor)
        if info is None or info.get("revoked"):
            raise TeamGroupError(f"操作者无效: {actor}")
        if info.get("role") not in roles and actor != g.owner:
            raise TeamGroupError(f"权限不足: 需要 {'/'.join(sorted(roles))}")

    # ---------------------------------------------------------- 跨机分享 (远程/局域网)

    def export_invite(self, days_valid: int = 7) -> Dict[str, Any]:
        """导出团组邀请令牌 (供远程/局域网成员跨机加入)。

        **安全**: 令牌含 group_id + name + secret (HMAC 密钥), 否则远端无法
        验签授权。secret 通过安全信道 (面对面/加密传输) 分享, 不经任何云端。
        days_valid 是令牌本身的有效期 (加入窗口), 与授权时限无关。
        """
        g = self._require_group()
        expires = time.time() + max(1, int(days_valid)) * _DAY
        return {
            "kind": "tuan-group-invite",
            "group_id": g.group_id,
            "name": g.name,
            "owner": g.owner,
            "secret": g.secret,
            "expires_at": expires,
        }

    @staticmethod
    def import_invite(token: Dict[str, Any]) -> Dict[str, Any]:
        """校验邀请令牌结构 + 有效期 (不落盘, 仅供加入流程读取元数据)。"""
        if token.get("kind") != "tuan-group-invite":
            raise TeamGroupError("邀请令牌格式无效")
        if time.time() > float(token.get("expires_at") or 0):
            raise TeamGroupError("邀请令牌已过期")
        return {k: token.get(k) for k in ("group_id", "name", "owner")}


# ============================================================ 工厂


def load_team_group(workspace: str) -> TeamGroupStore:
    """从 ``<workspace>/.tuan/team_group.json`` 加载团组密钥库。"""
    path = Path(workspace or ".").resolve() / ".tuan" / "team_group.json"
    return TeamGroupStore(path)
