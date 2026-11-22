"""skill 工具进阶操作测试 (install / remove / update —— registry 链路)。

镜像 test_session_tools.py 的 build_kernel + Agent + tuan_home 夹具。
全程离线: 网络/registry 层全部 monkeypatch —— _fetch_json 不出网,
registry.install 不走 git/zip (直接落盘 SKILL.md), 用户级技能目录指向 tmp。
"""

from pathlib import Path

from tuan_cli.app import build_kernel
from tuan_cli.core.agent import Agent


def _make_ctx(tmp_path):
    kernel = build_kernel()
    config = kernel.require("config")
    agent = Agent(kernel=kernel, config=config, workspace=str(tmp_path),
                  confirm=lambda _p: True)
    return kernel, agent


def _patch_registry(monkeypatch, tmp_path):
    """把 registry 客户端换成离线假件 (与 test_cmd_skills.py 同一打法):
    - _user_skills_dir → tmp 目录;
    - _fetch_json → 固定清单 (不出网);
    - registry.install → 直接落盘 SKILL.md (不走 git/zip);
    - console.print 静音。
    返回 (skills_dir, installed_names)。
    """
    import tuan_cli.cli.cmd_skills as cmd_skills
    import tuan_cli.ecosystem.registry as registry

    skills_dir = tmp_path / "user_skills"
    installed: list = []
    monkeypatch.setattr(cmd_skills, "_user_skills_dir", lambda: skills_dir)
    monkeypatch.setattr(cmd_skills.console, "print", lambda *a, **k: None)
    monkeypatch.setattr(registry, "_fetch_json", lambda url, **kw: {
        "skills": [{"name": "demo-skill", "version": "1.2.0",
                    "description": "演示技能", "path": "skills/demo-skill"}],
    })

    def fake_install(entry, dest_root, *, prefer="auto"):
        dest = Path(dest_root) / entry.name
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "SKILL.md").write_text(
            f"---\nname: {entry.name}\nversion: {entry.version}\n---\n"
            f"# {entry.name}\n离线安装的测试技能\n", encoding="utf-8")
        installed.append(entry.name)
        return True

    monkeypatch.setattr(registry, "install", fake_install)
    return skills_dir, installed


# ------------------------------------------------------------------ 注册

def test_skill_advanced_tools_registered(tuan_home):
    kernel = build_kernel()
    reg = kernel.require("tool_registry")
    names = {t.name for t in reg.tools}
    for n in ("skill_install", "skill_remove", "skill_update"):
        assert n in names, f"缺少工具 {n}"
        t = reg.get(n)
        assert t.group == "skills"
        assert t.dangerous is True  # 触网/改用户目录, 需确认


# ------------------------------------------------------------------ install

def test_skill_install_writes_skill_dir(tmp_path, tuan_home, monkeypatch):
    kernel, agent = _make_ctx(tmp_path)
    skills_dir, installed = _patch_registry(monkeypatch, tmp_path)
    reg = kernel.require("tool_registry")
    out = reg.get("skill_install").handler(agent.ctx, name="demo-skill")
    assert "demo-skill" in out and "安装完成" in out
    assert installed == ["demo-skill"]
    skill_md = skills_dir / "demo-skill" / "SKILL.md"
    assert skill_md.exists()
    assert "demo-skill" in skill_md.read_text(encoding="utf-8")


def test_skill_install_with_explicit_source(tmp_path, tuan_home, monkeypatch):
    """带 source: 跳过清单查询, 按给定仓库内路径走同一 install 后端。"""
    kernel, agent = _make_ctx(tmp_path)
    skills_dir, installed = _patch_registry(monkeypatch, tmp_path)
    reg = kernel.require("tool_registry")
    out = reg.get("skill_install").handler(
        agent.ctx, name="edge-skill", source="skills/edge-skill")
    assert "edge-skill" in out and "安装" in out
    assert installed == ["edge-skill"]
    assert (skills_dir / "edge-skill" / "SKILL.md").exists()


def test_skill_install_missing_name_friendly_error(tmp_path, tuan_home, monkeypatch):
    kernel, agent = _make_ctx(tmp_path)
    _patch_registry(monkeypatch, tmp_path)
    reg = kernel.require("tool_registry")
    out = reg.get("skill_install").handler(agent.ctx, name="   ")
    assert out.startswith("[skill]") and "技能名" in out


def test_skill_install_failure_friendly_error(tmp_path, tuan_home, monkeypatch):
    """registry 不可达 + install 失败 → 友好报错而非异常。"""
    kernel, agent = _make_ctx(tmp_path)
    import tuan_cli.cli.cmd_skills as cmd_skills
    import tuan_cli.ecosystem.registry as registry

    monkeypatch.setattr(cmd_skills, "_user_skills_dir",
                        lambda: tmp_path / "user_skills")
    monkeypatch.setattr(cmd_skills.console, "print", lambda *a, **k: None)
    monkeypatch.setattr(registry, "_fetch_json", lambda url, **kw: None)  # 网络失败
    monkeypatch.setattr(registry, "install", lambda entry, dest, **kw: False)
    reg = kernel.require("tool_registry")
    out = reg.get("skill_install").handler(agent.ctx, name="nope")
    assert out.startswith("[skill]") and "失败" in out


# ------------------------------------------------------------------ remove

def test_skill_remove_deletes_seeded_skill_dir(tmp_path, tuan_home, monkeypatch):
    kernel, agent = _make_ctx(tmp_path)
    skills_dir, _ = _patch_registry(monkeypatch, tmp_path)
    seeded = skills_dir / "demo-skill"
    seeded.mkdir(parents=True)
    (seeded / "SKILL.md").write_text("# demo\n", encoding="utf-8")
    reg = kernel.require("tool_registry")
    out = reg.get("skill_remove").handler(agent.ctx, name="demo-skill")
    assert "demo-skill" in out and "删除" in out
    assert not seeded.exists()
    # 再删一次 → 友好报错
    out2 = reg.get("skill_remove").handler(agent.ctx, name="demo-skill")
    assert out2.startswith("[skill]") and "失败" in out2


def test_skill_remove_missing_name_friendly_error(tmp_path, tuan_home, monkeypatch):
    kernel, agent = _make_ctx(tmp_path)
    _patch_registry(monkeypatch, tmp_path)
    reg = kernel.require("tool_registry")
    out = reg.get("skill_remove").handler(agent.ctx, name="")
    assert out.startswith("[skill]") and "技能名" in out


# ------------------------------------------------------------------ update

def test_skill_update_refreshes_one(tmp_path, tuan_home, monkeypatch):
    kernel, agent = _make_ctx(tmp_path)
    skills_dir, installed = _patch_registry(monkeypatch, tmp_path)
    old = skills_dir / "demo-skill"
    old.mkdir(parents=True)
    (old / "SKILL.md").write_text("version: 0.0.1\n", encoding="utf-8")
    reg = kernel.require("tool_registry")
    out = reg.get("skill_update").handler(agent.ctx, name="demo-skill")
    assert "demo-skill" in out and "已更新" in out
    # _update_one: 删旧目录 → 重新 install (同一 registry 链路)
    assert installed == ["demo-skill"]
    assert "1.2.0" in (skills_dir / "demo-skill" / "SKILL.md").read_text(encoding="utf-8")


def test_skill_update_all(tmp_path, tuan_home, monkeypatch):
    kernel, agent = _make_ctx(tmp_path)
    skills_dir, installed = _patch_registry(monkeypatch, tmp_path)
    for n in ("alpha", "beta"):
        d = skills_dir / n
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"# {n}\n", encoding="utf-8")
    reg = kernel.require("tool_registry")
    out = reg.get("skill_update").handler(agent.ctx, name="all")
    assert "alpha" in out and "beta" in out and "已更新" in out
    assert sorted(installed) == ["alpha", "beta"]


def test_skill_update_no_targets_friendly_error(tmp_path, tuan_home, monkeypatch):
    kernel, agent = _make_ctx(tmp_path)
    _patch_registry(monkeypatch, tmp_path)
    reg = kernel.require("tool_registry")
    out = reg.get("skill_update").handler(agent.ctx)
    assert out.startswith("[skill]") and "没有可更新" in out
