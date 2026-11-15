"""团组密钥库 (TeamGroupStore) 测试 —— v0.4.2 安全咽喉。

覆盖 goal 硬性要求: key 所有者验证、TTL≤3月、最多100人、纯本地、fail-closed。
"""

from __future__ import annotations

import json
import time

import pytest

from tuan_cli.core.team_group import (
    MAX_GRANT_DAYS,
    MAX_MEMBERS,
    TeamGroupError,
    TeamGroupStore,
    load_team_group,
)

OWNER = "owner_alice"


@pytest.fixture()
def tmp_group(tmp_path):
    store = TeamGroupStore(tmp_path / ".tuan" / "team_group.json")
    store.create_group("研发团组", OWNER, owner_name="Alice")
    store.register_provider_key("openai", "fp_openai_abc", owner=OWNER)
    return store


# ---------------------------------------------------------------- 创建


def test_create_and_persist(tmp_path):
    store = TeamGroupStore(tmp_path / ".tuan" / "team_group.json")
    g = store.create_group("X", "m1", owner_name="M")
    assert g.group_id.startswith("tg_")
    assert g.owner == "m1"
    assert g.secret  # 本地密钥存在
    # 落盘且 owner 自动入组
    raw = json.loads((tmp_path / ".tuan" / "team_group.json").read_text(encoding="utf-8"))
    assert raw["owner"] == "m1"
    assert "m1" in raw["members"]


def test_create_idempotent_rejected(tmp_group):
    with pytest.raises(TeamGroupError, match="已存在"):
        tmp_group.create_group("另一个", "x")


def test_create_requires_name_and_owner(tmp_path):
    store = TeamGroupStore(tmp_path / ".tuan" / "team_group.json")
    with pytest.raises(TeamGroupError):
        store.create_group("", "m1")
    with pytest.raises(TeamGroupError):
        store.create_group("n", "")


def test_export_public_hides_secret(tmp_group):
    pub = tmp_group.export_public()
    assert pub["created"] is True
    assert "secret" not in pub
    assert pub["member_count"] == 1
    assert pub["max_members"] == MAX_MEMBERS


# ---------------------------------------------------------------- 成员


def test_add_member_and_cap(tmp_group):
    tmp_group.add_member("bob", "Bob", actor=OWNER)
    assert tmp_group.get_member("bob")["role"] == "member"
    # 重复加被拒
    with pytest.raises(TeamGroupError, match="已存在"):
        tmp_group.add_member("bob", "Bob2", actor=OWNER)


def test_member_cap_100(tmp_group):
    # 已有 owner 1 人, 再加到 100
    for i in range(MAX_MEMBERS - 1):
        tmp_group.add_member(f"m{i}", actor=OWNER)
    assert len(tmp_group.list_members()) == MAX_MEMBERS
    # 第 101 人被拒
    with pytest.raises(TeamGroupError, match="已满"):
        tmp_group.add_member("overflow", actor=OWNER)


def test_add_member_requires_admin(tmp_group):
    tmp_group.add_member("bob", actor=OWNER)
    with pytest.raises(TeamGroupError, match="权限不足"):
        tmp_group.add_member("carol", actor="bob")  # 普通 member 无权


def test_revoke_member_cascades_grants(tmp_group):
    tmp_group.add_member("bob", actor=OWNER)
    tmp_group.issue_grant("openai", "bob", days=30, owner=OWNER)
    assert tmp_group.verify_grant(
        tmp_group.list_grants("bob")[0]["grant_id"], "openai")["ok"]
    tmp_group.revoke_member("bob", actor=OWNER)
    assert tmp_group.get_member("bob") is None
    # 授权连带撤销
    with pytest.raises(TeamGroupError, match="撤销"):
        tmp_group.verify_grant(tmp_group.list_grants("bob")[0]["grant_id"], "openai")


def test_cannot_revoke_owner(tmp_group):
    with pytest.raises(TeamGroupError, match="团主"):
        tmp_group.revoke_member(OWNER, actor=OWNER)


# ---------------------------------------------------------------- 供应商/凭证


def test_register_provider_owner_only(tmp_group):
    with pytest.raises(TeamGroupError, match="团主"):
        tmp_group.register_provider_key("kimi", "fp", owner="someone_else")
    assert tmp_group.register_provider_key("kimi", "fp_kimi", owner=OWNER)["provider_id"] == "kimi"


def test_register_provider_no_secret(tmp_group):
    # 只存指纹, 不存原文
    tmp_group.register_provider_key("kimi", "fp", owner=OWNER)
    raw = tmp_group.group.provider_keys["kimi"]
    assert raw["key_fingerprint"] == "fp"
    assert "api_key" not in raw and "key" not in raw


# ---------------------------------------------------------------- 授权签发/验证


def test_issue_and_verify_grant(tmp_group):
    tmp_group.add_member("bob", actor=OWNER)
    grant = tmp_group.issue_grant("openai", "bob", days=30, owner=OWNER)
    assert grant["grant_id"].startswith("gr_")
    assert grant["signature"]
    r = tmp_group.verify_grant(grant["grant_id"], "openai")
    assert r["ok"] is True
    assert r["member"] == "bob"


def test_grant_ttl_cap_90_days(tmp_group):
    tmp_group.add_member("bob", actor=OWNER)
    with pytest.raises(TeamGroupError, match="上限"):
        tmp_group.issue_grant("openai", "bob", days=MAX_GRANT_DAYS + 1, owner=OWNER)
    with pytest.raises(TeamGroupError, match="正"):
        tmp_group.issue_grant("openai", "bob", days=0, owner=OWNER)
    with pytest.raises(TeamGroupError, match="正"):
        tmp_group.issue_grant("openai", "bob", days=-5, owner=OWNER)
    # 90 天恰好允许
    g = tmp_group.issue_grant("openai", "bob", days=MAX_GRANT_DAYS, owner=OWNER)
    assert tmp_group.verify_grant(g["grant_id"], "openai")["ok"]


def test_grant_expiry_fail_closed(tmp_group):
    tmp_group.add_member("bob", actor=OWNER)
    g = tmp_group.issue_grant("openai", "bob", days=1, owner=OWNER)
    gid = g["grant_id"]
    # 构造签名合法但已过期的授权 (重新签名以正确测过期路径)
    grant = tmp_group.group.grants[gid]
    grant["expires_at"] = time.time() - 10
    scope = grant["scope"]
    payload = tmp_group._grant_payload(gid, grant["provider"], grant["member"],
                                       float(grant["expires_at"]), scope)
    grant["signature"] = tmp_group.group._sign(payload)
    with pytest.raises(TeamGroupError, match="过期"):
        tmp_group.verify_grant(gid, "openai")


def test_grant_tamper_detected(tmp_group):
    tmp_group.add_member("bob", actor=OWNER)
    g = tmp_group.issue_grant("openai", "bob", days=30, owner=OWNER)
    gid = g["grant_id"]
    # 篡改成员/过期时间 → 验签失败
    tmp_group.group.grants[gid]["member"] = "mallory"
    with pytest.raises(TeamGroupError, match="签名"):
        tmp_group.verify_grant(gid, "openai")


def test_grant_wrong_provider(tmp_group):
    tmp_group.add_member("bob", actor=OWNER)
    tmp_group.register_provider_key("kimi", "fp_kimi", owner=OWNER)
    g = tmp_group.issue_grant("openai", "bob", days=30, owner=OWNER)
    with pytest.raises(TeamGroupError, match="不适用于"):
        tmp_group.verify_grant(g["grant_id"], "kimi")


def test_grant_model_scope(tmp_group):
    tmp_group.add_member("bob", actor=OWNER)
    g = tmp_group.issue_grant(
        "openai", "bob", days=30, model_scope=["gpt-4o", "gpt-4o-mini"], owner=OWNER)
    gid = g["grant_id"]
    assert tmp_group.verify_grant(gid, "openai", model="gpt-4o")["ok"]
    assert tmp_group.verify_grant(gid, "openai", model="gpt-4o-mini")["ok"]
    with pytest.raises(TeamGroupError, match="不覆盖"):
        tmp_group.verify_grant(gid, "openai", model="o1")


def test_revoke_grant(tmp_group):
    tmp_group.add_member("bob", actor=OWNER)
    g = tmp_group.issue_grant("openai", "bob", days=30, owner=OWNER)
    tmp_group.revoke_grant(g["grant_id"], actor=OWNER)
    with pytest.raises(TeamGroupError, match="撤销"):
        tmp_group.verify_grant(g["grant_id"], "openai")


def test_verify_requires_group(tmp_path):
    store = TeamGroupStore(tmp_path / ".tuan" / "team_group.json")
    with pytest.raises(TeamGroupError, match="未创建"):
        store.verify_grant("x", "openai")


def test_signature_is_deterministic(tmp_group):
    """同 payload 签名一致, 篡改 scope 变化 → 验签失败。"""
    tmp_group.add_member("bob", actor=OWNER)
    g = tmp_group.issue_grant("openai", "bob", days=30, owner=OWNER)
    gid = g["grant_id"]
    tmp_group.group.grants[gid]["scope"]["models"] = ["evil-model"]
    with pytest.raises(TeamGroupError, match="签名"):
        tmp_group.verify_grant(gid, "openai")


# ---------------------------------------------------------------- 工厂/加载


def test_load_factory_empty(tmp_path):
    store = load_team_group(str(tmp_path))
    assert store.group is None
    assert store.export_public() == {"created": False}


def test_load_factory_roundtrip(tmp_path):
    s1 = load_team_group(str(tmp_path))
    s1.create_group("G", "m1")
    s1.add_member("bob", actor="m1")
    # 重新加载 (模拟重启)
    s2 = load_team_group(str(tmp_path))
    assert s2.group.name == "G"
    assert s2.get_member("bob")["member_id"] == "bob"


# ---------------------------------------------------------------- 团组→供应商解析


def test_build_for_member_fail_closed_no_key(tmp_group, monkeypatch):
    """授权有效但所有者本机无 key 环境变量 → 拒绝 (凭证不外传)。"""
    from tuan_cli.runtime.provider_service import ProviderService
    monkeypatch.delenv("TUAN_GROUP_KEY_OPENAI", raising=False)
    tmp_group.add_member("bob", actor=OWNER)
    g = tmp_group.issue_grant("openai", "bob", days=30, owner=OWNER)
    svc = ProviderService()
    with pytest.raises(ValueError, match="TUAN_GROUP_KEY_OPENAI"):
        svc.build_for_member(tmp_group, g["grant_id"], "openai", member="bob")


def test_build_for_member_fail_closed_no_grant(tmp_group, monkeypatch):
    """无效/无授权 → 即使有 key 也拒绝 (先验授权, 后注入 key)。"""
    from tuan_cli.runtime.provider_service import ProviderService
    monkeypatch.setenv("TUAN_GROUP_KEY_OPENAI", "sk-test")
    svc = ProviderService()
    with pytest.raises(TeamGroupError):
        svc.build_for_member(tmp_group, "gr_nonexistent", "openai", member="bob")


def test_build_for_member_expired_grant(tmp_group, monkeypatch):
    """过期授权 → 拒绝 (时限硬约束)。"""
    import time as _time
    from tuan_cli.runtime.provider_service import ProviderService
    monkeypatch.setenv("TUAN_GROUP_KEY_OPENAI", "sk-test")
    tmp_group.add_member("bob", actor=OWNER)
    g = tmp_group.issue_grant("openai", "bob", days=1, owner=OWNER)
    gid = g["grant_id"]
    grant = tmp_group.group.grants[gid]
    grant["expires_at"] = _time.time() - 10
    payload = tmp_group._grant_payload(gid, grant["provider"], grant["member"],
                                       float(grant["expires_at"]), grant["scope"])
    grant["signature"] = tmp_group.group._sign(payload)
    svc = ProviderService()
    with pytest.raises(TeamGroupError, match="过期"):
        svc.build_for_member(tmp_group, gid, "openai", member="bob")


# ---------------------------------------------------------------- 团组 HTTP 端点


def test_teamgroup_http_create_and_snapshot(tmp_path):
    """/api/teamgroup/create + snapshot: 创建团组并总览 (纯本地, 无 kernel)。"""
    import json
    import threading
    import time
    import urllib.request
    from tuan_cli.web import server as ws_mod
    from tuan_cli.web.server import WebServer

    ws_mod._SESSIONS.clear()
    srv = WebServer(kernel=None, workspace=str(tmp_path), port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    for _ in range(50):
        if srv._httpd is not None:
            break
        time.sleep(0.05)
    try:
        base = f"http://127.0.0.1:{srv._httpd.server_port}"
        # 初始快照: 未创建
        with urllib.request.urlopen(base + "/api/teamgroup/snapshot", timeout=10) as r:
            snap = json.loads(r.read().decode("utf-8"))
        assert snap["ok"] is True
        assert snap["group"]["created"] is False
        assert isinstance(snap.get("capabilities"), list)
        # 创建团组
        req = urllib.request.Request(
            base + "/api/teamgroup/create",
            data=json.dumps({"name": "研发", "owner_member_id": "alice",
                             "owner_name": "Alice"}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            created = json.loads(r.read().decode("utf-8"))
        assert created["ok"] is True
        assert created["group"]["owner"] == "alice"
        assert created["group"]["member_count"] == 1
        # 快照反映成员
        with urllib.request.urlopen(base + "/api/teamgroup/snapshot", timeout=10) as r:
            snap2 = json.loads(r.read().decode("utf-8"))
        assert snap2["group"]["created"] is True
        assert any(m["member_id"] == "alice" for m in snap2["members"])
        assert len(snap2["capabilities"]) >= 10  # 能力矩阵
    finally:
        if srv._httpd is not None:
            srv._httpd.shutdown()
            srv._httpd.server_close()
        ws_mod._SESSIONS.clear()


def test_teamgroup_http_grant_flow(tmp_path):
    """/api/teamgroup 全授权流: 登记 provider → 签发 grant → verify → revoke。"""
    import json
    import threading
    import time
    import urllib.request
    from tuan_cli.web import server as ws_mod
    from tuan_cli.web.server import WebServer

    ws_mod._SESSIONS.clear()
    srv = WebServer(kernel=None, workspace=str(tmp_path), port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    for _ in range(50):
        if srv._httpd is not None:
            break
        time.sleep(0.05)
    try:
        base = f"http://127.0.0.1:{srv._httpd.server_port}"

        def post(path, payload):
            req = urllib.request.Request(
                base + path,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                return json.loads(e.read().decode("utf-8"))

        def get(path):
            with urllib.request.urlopen(base + path, timeout=10) as r:
                return json.loads(r.read().decode("utf-8"))

        post("/api/teamgroup/create", {"name": "G", "owner_member_id": "alice"})
        post("/api/teamgroup/member/add",
             {"member_id": "bob", "display_name": "Bob", "actor": "alice"})
        post("/api/teamgroup/provider/register",
             {"provider_id": "openai", "key_fingerprint": "fp_x", "owner": "alice"})
        g = post("/api/teamgroup/grant/issue",
                 {"provider_id": "openai", "member": "bob", "days": 30, "owner": "alice"})
        assert g["ok"] is True
        gid = g["grant"]["grant_id"]
        # verify (GET)
        v = get(f"/api/teamgroup/grant/verify?grant_id={gid}&provider_id=openai")
        assert v["ok"] is True and v["verdict"]["member"] == "bob"
        # 超时天数被拒 (400)
        over = post("/api/teamgroup/grant/issue",
                    {"provider_id": "openai", "member": "bob", "days": 999, "owner": "alice"})
        assert over["ok"] is False
        # revoke
        rv = post("/api/teamgroup/grant/revoke", {"grant_id": gid, "actor": "alice"})
        assert rv["ok"] is True
        # revoked grant → verify 返回 400 + ok:false
        req = urllib.request.Request(
            base + f"/api/teamgroup/grant/verify?grant_id={gid}&provider_id=openai")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                body = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = json.loads(e.read().decode("utf-8"))
        assert body["ok"] is False
        assert "撤销" in body["error"]
    finally:
        if srv._httpd is not None:
            srv._httpd.shutdown()
            srv._httpd.server_close()
        ws_mod._SESSIONS.clear()


# ============================================================ 审计日志 (v0.4.2)

def test_audit_written_on_mutations(tmp_group, tmp_path):
    """创建/加成员/登记/签发都应落审计链。"""
    tmp_group.add_member("bob", "Bob", "member", actor=OWNER)
    tmp_group.issue_grant("openai", "bob", 30, owner=OWNER)
    audit = tmp_group.read_audit()
    actions = {a["action"] for a in audit}
    assert "create_group" in actions
    assert "add_member" in actions
    assert "register_provider" in actions
    assert "issue_grant" in actions
    assert audit[0]["action"] == "issue_grant"  # 最新在前


def test_audit_verify_and_revoke(tmp_group):
    """verify_grant / revoke_grant 也进审计。"""
    g = tmp_group.issue_grant("openai", OWNER, 10, owner=OWNER)
    gid = g["grant_id"]
    tmp_group.verify_grant(gid, "openai")
    tmp_group.revoke_grant(gid, actor=OWNER)
    actions = [a["action"] for a in tmp_group.read_audit()]
    assert "verify_grant" in actions
    assert "revoke_grant" in actions


def test_audit_read_empty(tmp_path):
    """无审计文件时返回空列表。"""
    store = TeamGroupStore(tmp_path / ".tuan" / "team_group.json")
    assert store.read_audit() == []


# ============================================================ 跨机邀请 (远程/局域网)

def test_invite_roundtrip(tmp_group):
    """导出邀请 → 校验结构 (远程/局域网加入)。"""
    tok = tmp_group.export_invite(days_valid=7)
    assert tok["kind"] == "tuan-group-invite"
    assert tok["group_id"] == tmp_group.group.group_id
    assert tok["secret"] == tmp_group.group.secret
    meta = TeamGroupStore.import_invite(tok)
    assert meta["group_id"] == tmp_group.group.group_id
    assert meta["owner"] == OWNER


def test_invite_expired_rejected(tmp_group):
    """过期邀请令牌 fail-closed。"""
    tok = tmp_group.export_invite(days_valid=1)
    tok["expires_at"] = time.time() - 10
    with pytest.raises(TeamGroupError, match="过期"):
        TeamGroupStore.import_invite(tok)


def test_invite_bad_kind_rejected(tmp_group):
    """kind 不符的令牌拒绝。"""
    with pytest.raises(TeamGroupError, match="格式无效"):
        TeamGroupStore.import_invite({"kind": "other"})
