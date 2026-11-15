"""cmd_roles tests -- specialized roles query CLI (list/get/suggest)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_roles as P


# ---------------------------------------------------------------- _role_brief

class TestRoleBrief:
    def test_brief_structure(self):
        from tuan_cli.core.specialized_roles import get_role
        r = get_role("reviewer")
        if r is None:
            pytest.skip("reviewer role not available")
        b = P._role_brief(r)
        assert b["role_id"] == "reviewer"
        assert "name" in b and "description" in b
        assert isinstance(b["recommended_tools"], list)
        assert isinstance(b["quality_criteria"], list)
        assert "max_iterations" in b


# ---------------------------------------------------------------- list

class TestList:
    def test_list_text(self, capsys):
        from types import SimpleNamespace as NS
        rc = P.cmd_roles(NS(roles_cmd="list", json=False))
        assert rc == 0
        out = capsys.readouterr().out
        assert "专业化角色" in out

    def test_list_json(self, capsys):
        from types import SimpleNamespace as NS
        rc = P.cmd_roles(NS(roles_cmd="list", json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert "count" in d and "roles" in d
        assert d["count"] > 0

    def test_default_list(self, capsys):
        from types import SimpleNamespace as NS
        rc = P.cmd_roles(NS(roles_cmd=None, json=False))
        assert rc == 0
        assert "专业化角色" in capsys.readouterr().out


# ---------------------------------------------------------------- get

class TestGet:
    def test_get_known(self, capsys):
        from tuan_cli.core.specialized_roles import list_roles
        roles = list_roles()
        if not roles:
            pytest.skip("no roles")
        rid = roles[0].role_id
        rc = P.cmd_roles(SimpleNamespace(roles_cmd="get", json=False, role_id=rid))
        assert rc == 0
        out = capsys.readouterr().out
        assert rid in out

    def test_get_unknown(self, capsys):
        rc = P.cmd_roles(SimpleNamespace(roles_cmd="get", json=False, role_id="nope"))
        assert rc == 1
        assert "未找到角色" in capsys.readouterr().out

    def test_get_json(self, capsys):
        from tuan_cli.core.specialized_roles import list_roles
        roles = list_roles()
        if not roles:
            pytest.skip("no roles")
        rid = roles[0].role_id
        rc = P.cmd_roles(SimpleNamespace(roles_cmd="get", json=True, role_id=rid))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["role_id"] == rid


# ---------------------------------------------------------------- suggest

class TestSuggest:
    def test_suggest_empty_task(self, capsys):
        rc = P.cmd_roles(SimpleNamespace(roles_cmd="suggest", json=False, task="  "))
        assert rc == 1
        assert "请提供" in capsys.readouterr().out

    def test_suggest_text(self, capsys):
        rc = P.cmd_roles(SimpleNamespace(
            roles_cmd="suggest", json=False, task="审查代码质量"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "推荐角色" in out

    def test_suggest_json(self, capsys):
        rc = P.cmd_roles(SimpleNamespace(
            roles_cmd="suggest", json=True, task="写测试"))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert "suggested_role" in d
        assert "task" in d
