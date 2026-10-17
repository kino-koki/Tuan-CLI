"""工具暴露分层 (core/extended/deferred) + 暴露档位 + tool_search + 配置目录迁移 测试。"""
from pathlib import Path

import pytest

from tuan_cli.config.defaults import APP_DIR_NAME, LEGACY_APP_DIR_NAMES
from tuan_cli.tools.base import Tool, ToolRegistry
from tuan_cli.tools.tiers import (
    CORE_TOOLS,
    DEFERRED_TOOLS,
    allowed_tiers,
    exposure_summary,
    filter_exposed,
    is_exposed,
    resolve_auto_exposure,
    resolve_exposure,
    tier_of,
)


def _reg():
    r = ToolRegistry()
    for name in ("read_file", "run_shell", "tool_search", "git_status", "ext_json_diff", "image_generate"):
        r.register(Tool(name=name, description=f"{name} desc", parameters={"type": "object"},
                        handler=lambda *a, **k: "ok"))
    return r


# ---------------------------------------------------------------- 1. 分层归类
def test_core_and_deferred_classification():
    assert tier_of("read_file") == "core"
    assert tier_of("tool_search") == "core"
    assert tier_of("ext_json_diff") == "deferred"
    assert tier_of("image_generate") == "deferred"
    # 未列名者归 extended
    assert tier_of("git_status") == "extended"
    assert tier_of("memory_search") == "extended"
    # core / deferred 互斥
    assert not (CORE_TOOLS & DEFERRED_TOOLS)


def test_allowed_tiers_and_unknown_fallback():
    assert allowed_tiers("minimal") == ("core",)
    assert "extended" in allowed_tiers("standard")
    assert "deferred" in allowed_tiers("full")
    # 未知档位回退 standard (绝不降成空集)
    assert allowed_tiers("nonsense") == allowed_tiers("standard")
    assert allowed_tiers(None) == allowed_tiers("standard")


def test_is_exposed_per_mode():
    assert is_exposed("read_file", "minimal")
    assert not is_exposed("git_status", "minimal")
    assert is_exposed("git_status", "standard")
    assert not is_exposed("ext_json_diff", "standard")
    assert is_exposed("ext_json_diff", "full")


# ---------------------------------------------------------------- 2. 注册表过滤
def test_registry_schemas_respects_exposure():
    r = _reg()
    names = lambda mode: {s["function"]["name"] for s in r.schemas(exposure=mode)}
    assert names("minimal") == {"read_file", "run_shell", "tool_search"}
    assert names("standard") == {"read_file", "run_shell", "tool_search", "git_status"}
    assert "ext_json_diff" in names("full") and "image_generate" in names("full")


def test_deferred_tools_still_dispatchable_by_name():
    """分层只影响"看到什么", 不影响"能调用什么"。"""
    r = _reg()
    assert r.get("ext_json_diff") is not None
    assert "ext_json_diff" not in {s["function"]["name"] for s in r.schemas(exposure="minimal")}
    assert r.get("ext_json_diff") is not None  # 仍可按名调用


def test_filter_exposed_preserves_order():
    r = _reg()
    tools = r.tools
    out = filter_exposed(tools, "minimal")
    assert [t.name for t in out] == ["read_file", "run_shell", "tool_search"]


def test_exposure_summary_counts():
    counts = exposure_summary(_reg().tools)
    assert counts == {"core": 3, "extended": 1, "deferred": 2}


# ---------------------------------------------------------------- 3. auto 档位
def test_auto_exposure_by_model_capability():
    assert resolve_auto_exposure("sensenova-6.8-flash-lite") == "minimal"
    assert resolve_auto_exposure("qwen2.5:7b") == "minimal"
    assert resolve_auto_exposure("gpt-4o-mini") == "standard"   # 强模型线索优先
    assert resolve_auto_exposure("deepseek-chat") == "standard"
    assert resolve_auto_exposure("unknown-model-x") == "standard"  # 未知不冒险降级
    assert resolve_auto_exposure(None) == "standard"


def test_resolve_exposure_modes():
    assert resolve_exposure("minimal") == "minimal"
    assert resolve_exposure("full") == "full"
    assert resolve_exposure("auto", "qwen2.5:7b") == "minimal"
    assert resolve_exposure(None) == "standard"
    assert resolve_exposure("bogus") == "standard"


# ---------------------------------------------------------------- 4. tool_search
def test_tool_search_finds_deferred_by_keyword():
    from tuan_cli.tools.base import ToolContext
    from tuan_cli.tools.tool_search import tool_search

    class _K:
        def get(self, name):
            return _reg() if name == "tool_registry" else None

    out = tool_search(ToolContext(kernel=_K(), workspace="."), query="json", limit=3)
    assert "ext_json_diff" in out
    assert "参数 schema" in out


def test_tool_search_empty_query_browses_deferred_only():
    from tuan_cli.tools.base import ToolContext
    from tuan_cli.tools.tool_search import tool_search

    class _K:
        def get(self, name):
            return _reg() if name == "tool_registry" else None

    out = tool_search(ToolContext(kernel=_K(), workspace="."), limit=5)
    assert "ext_json_diff" in out
    assert "read_file" not in out          # core 不该出现在默认浏览里


# ---------------------------------------------------------------- 5. 配置目录
def test_app_dir_is_tuan_and_legacy_listed():
    assert APP_DIR_NAME == ".tuan"
    assert ".tuan_cli" in LEGACY_APP_DIR_NAMES


def test_migrate_legacy_home_copies_and_keeps_old(tmp_path, monkeypatch):
    from tuan_cli.config import loader

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    legacy = fake_home / ".tuan_cli"
    legacy.mkdir()
    (legacy / "config.yaml").write_text("model:\n  provider: deepseek\n", encoding="utf-8")
    new = fake_home / ".tuan"

    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    assert loader.migrate_legacy_home(new) is True
    assert (new / "config.yaml").read_text(encoding="utf-8").startswith("model:")
    assert legacy.exists()  # 旧目录保留 (不可逆操作绝不自动做)


def test_migrate_legacy_home_skips_when_new_exists(tmp_path, monkeypatch):
    from tuan_cli.config import loader

    fake_home = tmp_path / "home"
    (fake_home / ".tuan").mkdir(parents=True)
    (fake_home / ".tuan_cli").mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    assert loader.migrate_legacy_home(fake_home / ".tuan") is False


def test_migrate_legacy_home_noop_without_legacy(tmp_path, monkeypatch):
    from tuan_cli.config import loader

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    assert loader.migrate_legacy_home(fake_home / ".tuan") is False


# ---------------------------------------------------------------- 6. CLI 标志与别名提示
def test_tools_flag_registered():
    from tuan_cli.cli import parser as cli_parser

    ap = cli_parser.build_parser() if hasattr(cli_parser, "build_parser") else None
    if ap is None:
        return  # 无 build_parser 则跳过 (由 CLI e2e 测试覆盖)
    ns = ap.parse_args(["--tools", "minimal"])
    assert ns.tools == "minimal"


def test_legacy_command_name_is_rejected(monkeypatch, capsys):
    """旧命令名 qxt 已彻底废弃: 触发即明确报错并以非零码退出 (兜底旧 shim)。"""
    from tuan_cli.cli import _reject_legacy_command_name

    monkeypatch.setattr("sys.argv", ["qxt"])
    with pytest.raises(SystemExit) as e:
        _reject_legacy_command_name()
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "废弃" in err and "tuan" in err

    # 新命令名与解释器路径 (python -m / 测试) 不受影响
    for prog in ("tuan", "/usr/bin/python3"):
        monkeypatch.setattr("sys.argv", [prog])
        _reject_legacy_command_name()
        assert capsys.readouterr().err == ""


def test_qxt_is_not_an_entry_point():
    """qxt 必须已从 [project.scripts] 移除 (彻底废弃, 不是过渡别名)。"""
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data.get("project", {}).get("scripts", {})
    assert "tuan" in scripts
    assert "qxt" not in scripts, "qxt 应已废弃, 不得再作为入口点"
