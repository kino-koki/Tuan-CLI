"""Claude Code 风格 settings.json 与 CLI 标志对齐测试。"""

import json

import pytest

from tuan_cli.cli.parser import build_parser
from tuan_cli.config.settings_file import (
    apply_env,
    load_settings,
    merge_rules,
    normalize_tool_name,
)


def _write(tmp_path, data):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def test_model_and_env(tmp_path, monkeypatch):
    path = _write(tmp_path, {"model": "claude-sonnet-4-5",
                             "env": {"TUAN_TEST_ENV": "1"}})
    res = load_settings(path)
    assert res.config_patch["model.model"] == "claude-sonnet-4-5"
    monkeypatch.delenv("TUAN_TEST_ENV", raising=False)
    apply_env(res.env)
    import os
    assert os.environ["TUAN_TEST_ENV"] == "1"


def test_bash_prefix_and_exact_rule(tmp_path):
    path = _write(tmp_path, {"permissions": {"allow": [
        "Bash(git status:*)", "Bash(git push)",
    ]}})
    res = load_settings(path)
    rules = res.config_patch["permissions.rules"]
    assert rules[0] == {"tool": "run_shell", "pattern": "git status*",
                        "action": "allow"}
    assert rules[1] == {"tool": "run_shell", "pattern": "git push",
                        "action": "allow"}


def test_path_rule_variants(tmp_path):
    path = _write(tmp_path, {"permissions": {"deny": ["Read(./secrets/**)"]}})
    res = load_settings(path)
    rules = res.config_patch["permissions.rules"]
    assert all(r["action"] == "deny" for r in rules)
    assert any(r["pattern"] == "secrets/*" for r in rules)
    assert any(r["pattern"] == "*secrets/*" for r in rules)


def test_mcp_rule(tmp_path):
    path = _write(tmp_path, {"permissions": {"deny": ["mcp__fs__write_file"]}})
    res = load_settings(path)
    rule = res.config_patch["permissions.rules"][0]
    assert rule["tool"] == "mcp_call"
    assert rule["pattern"] == "mcp__fs__write_file"
    assert rule["action"] == "deny"


def test_web_fetch_domain(tmp_path):
    path = _write(tmp_path, {"permissions": {"allow": ["WebFetch(domain:example.com)"]}})
    res = load_settings(path)
    rule = res.config_patch["permissions.rules"][0]
    assert rule["param"] == "url"
    assert rule["value"] == "*example.com*"


def test_default_mode_and_dirs(tmp_path):
    path = _write(tmp_path, {"permissions": {
        "defaultMode": "plan",
        "additionalDirectories": ["../shared"],
    }})
    res = load_settings(path)
    assert res.mode == "plan"
    assert res.additional_directories == ["../shared"]


def test_unknown_fields_warn_not_fail(tmp_path):
    path = _write(tmp_path, {"model": "m", "weirdKey": 1,
                             "permissions": {"allow": ["WeirdTool(x)"]}})
    res = load_settings(path)
    assert any("weirdKey" in w for w in res.warnings)
    assert any("WeirdTool" in w for w in res.warnings)


def test_untranslatable_deny_fails_closed(tmp_path):
    path = _write(tmp_path, {"permissions": {"deny": ["WeirdTool(x)"]}})
    with pytest.raises(ValueError) as ei:
        load_settings(path)
    assert "WeirdTool" in str(ei.value)


def test_invalid_shapes(tmp_path):
    for bad in ({"permissions": {"allow": "Bash"}},
                {"permissions": {"defaultMode": "nope"}},
                {"env": []}):
        path = _write(tmp_path, bad)
        with pytest.raises(ValueError):
            load_settings(path)


def test_allowed_disallowed_tools(tmp_path):
    path = _write(tmp_path, {"allowedTools": ["Read", "Grep"],
                             "disallowedTools": ["WebFetch"]})
    res = load_settings(path)
    assert res.allowed_tools == ["Read", "Grep"]
    assert normalize_tool_name("Bash") == "run_shell"


def test_merge_rules():
    existing = [{"tool": "run_shell", "action": "allow"}]
    merged = merge_rules(existing, [{"tool": "read_file", "action": "deny"}])
    assert len(merged) == 2
    assert merged[0]["tool"] == "run_shell"


def test_cli_flags_parse():
    parser = build_parser()
    args = parser.parse_args([
        "--add-dir", "a", "--add-dir", "b",
        "--disallowed-tools", "web_fetch,run_shell",
        "--settings", "s.json",
    ])
    assert args.add_dir == ["a", "b"]
    assert args.disallowed_tools == "web_fetch,run_shell"
    assert args.settings == "s.json"


def test_cli_run_flags_parse():
    parser = build_parser()
    args = parser.parse_args(["run", "--add-dir", "x", "--settings", "s.json", "task"])
    assert args.add_dir == ["x"]
    assert args.settings == "s.json"
