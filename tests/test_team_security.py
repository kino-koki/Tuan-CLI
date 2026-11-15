"""团组安全强化层 (TeamGroupSecurity) 测试 —— 密钥轮换/防重放/challenge/用量策略。"""

from __future__ import annotations

import hashlib
import hmac
import time

import pytest

from tuan_cli.core.team_group import TeamGroupError, TeamGroupStore
from tuan_cli.core.team_security import (
    TeamGroupSecurity,
    TeamSecurityError,
    load_team_security,
)

OWNER = "owner_alice"


@pytest.fixture()
def sec(tmp_path):
    store = TeamGroupStore(tmp_path / ".tuan" / "team_group.json")
    store.create_group("研发团组", OWNER, owner_name="Alice")
    store.register_provider_key("openai", "fp_openai", owner=OWNER)
    store.add_member("bob", actor=OWNER)
    grant = store.issue_grant("openai", "bob", days=30, owner=OWNER)
    s = load_team_security(store)
    return s, store, grant["grant_id"]


# ---------------------------------------------------------------- 密钥轮换


def test_rotate_secret_owner_only(sec):
    s, store, _ = sec
    with pytest.raises(TeamSecurityError, match="团主"):
        s.rotate_secret(actor="bob")
    r = s.rotate_secret(actor=OWNER, grace_days=7)
    assert r["ok"] is True
    assert r["resigned_grants"] >= 1


def test_rotate_re_signs_active_grants(sec):
    s, store, gid = sec
    # 轮换前授权有效
    assert store.verify_grant(gid, "openai")["ok"]
    s.rotate_secret(actor=OWNER)
    # 轮换后 (已用新密钥重签) 仍然有效
    assert store.verify_grant(gid, "openai")["ok"]
    # 密钥确实变了
    assert store.group.secret != s._rotation.previous_secret


def test_rotate_invalidates_challenges(sec):
    s, store, _ = sec
    ch = s.issue_challenge()
    sig = hmac.new(store.group.secret.encode(), ch["challenge"].encode(),
                   hashlib.sha256).hexdigest()
    s.rotate_secret(actor=OWNER)
    # 轮换清空 challenge, 旧应答不可再用
    with pytest.raises(TeamSecurityError, match="不存在"):
        s.verify_challenge(ch["challenge_id"], sig, actor=OWNER)


def test_rotate_invalidates_nonces(sec):
    s, store, _ = sec
    s.consume_nonce("n1")
    s.rotate_secret(actor=OWNER)
    # 旧 nonce 被清空, 可重新使用 (与旧密钥绑定, 已失效)
    s.consume_nonce("n1")  # 不抛


# ---------------------------------------------------------------- 防重放


def test_nonce_single_use(sec):
    s, store, _ = sec
    s.consume_nonce("abc")
    with pytest.raises(TeamSecurityError, match="重放"):
        s.consume_nonce("abc")


def test_nonce_required_non_empty(sec):
    s, _, _ = sec
    with pytest.raises(TeamSecurityError, match="nonce"):
        s.consume_nonce("")


def test_nonce_expiry(sec):
    s, _, _ = sec
    s._nonce_ttl = -1  # 立即过期
    s.consume_nonce("old")
    time.sleep(0.01)
    s.consume_nonce("old")  # 过期后可复用


# ---------------------------------------------------------------- challenge-response


def test_challenge_roundtrip(sec):
    s, store, _ = sec
    ch = s.issue_challenge(ttl_seconds=60)
    good = hmac.new(store.group.secret.encode(), ch["challenge"].encode(),
                    hashlib.sha256).hexdigest()
    r = s.verify_challenge(ch["challenge_id"], good, actor=OWNER)
    assert r["ok"] is True


def test_challenge_bad_signature(sec):
    s, store, _ = sec
    ch = s.issue_challenge()
    with pytest.raises(TeamSecurityError, match="失败"):
        s.verify_challenge(ch["challenge_id"], "deadbeef", actor=OWNER)


def test_challenge_single_use(sec):
    s, store, _ = sec
    ch = s.issue_challenge()
    good = hmac.new(store.group.secret.encode(), ch["challenge"].encode(),
                    hashlib.sha256).hexdigest()
    s.verify_challenge(ch["challenge_id"], good, actor=OWNER)
    with pytest.raises(TeamSecurityError, match="不存在"):
        s.verify_challenge(ch["challenge_id"], good, actor=OWNER)


def test_challenge_expiry(sec):
    s, store, _ = sec
    ch = s.issue_challenge(ttl_seconds=10)
    s._challenges[ch["challenge_id"]]["expires_at"] = time.time() - 1
    with pytest.raises(TeamSecurityError, match="过期"):
        s.verify_challenge(ch["challenge_id"], "x", actor=OWNER)


def test_sensitive_op_requires_challenge(sec):
    s, store, _ = sec
    store.add_member("carol", actor=OWNER)
    # 无有效 challenge 直接调加固版 -> 拒绝
    with pytest.raises(TeamSecurityError):
        s.revoke_member_verified("carol", actor=OWNER, challenge_id="x", signature="y")
    # 正确 challenge -> 通过
    ch = s.issue_challenge()
    good = hmac.new(store.group.secret.encode(), ch["challenge"].encode(),
                    hashlib.sha256).hexdigest()
    assert s.revoke_member_verified(
        "carol", actor=OWNER, challenge_id=ch["challenge_id"], signature=good) is True


# ---------------------------------------------------------------- 用量策略


def test_policy_hours_block(sec):
    s, store, gid = sec
    cur = time.localtime().tm_hour
    bad_hour = (cur + 1) % 24
    s.set_grant_policy(gid, allowed_hours=[bad_hour], actor=OWNER)
    with pytest.raises(TeamSecurityError, match="时段"):
        s.verify_grant_hardened(gid, "openai")


def test_policy_max_uses(sec):
    s, store, gid = sec
    s.set_grant_policy(gid, max_uses=2, actor=OWNER)
    s.verify_grant_hardened(gid, "openai")
    s.verify_grant_hardened(gid, "openai")
    with pytest.raises(TeamSecurityError, match="次数"):
        s.verify_grant_hardened(gid, "openai")
    assert s.usage_of(gid)["count"] == 2


def test_policy_set_requires_admin(sec):
    s, store, gid = sec
    with pytest.raises(TeamSecurityError, match="权限"):
        s.set_grant_policy(gid, max_uses=5, actor="bob")


def test_hardened_no_policy_passthrough(sec):
    s, store, gid = sec
    # 未设策略 = 仅原始验证
    v = s.verify_grant_hardened(gid, "openai")
    assert v["ok"] is True


def test_hardened_nonce_flow(sec):
    s, store, gid = sec
    v = s.verify_grant_hardened(gid, "openai", nonce="nn-1")
    assert v["ok"]
    # 同一 nonce 二次用 -> 重放
    with pytest.raises(TeamSecurityError, match="重放"):
        s.verify_grant_hardened(gid, "openai", nonce="nn-1")
