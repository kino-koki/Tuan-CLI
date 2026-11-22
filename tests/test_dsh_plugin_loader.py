"""DSH 0.2 原生插件加载器与技能注入测试。

覆盖核心请求#4 的"为 Tuan-CLI 做真实接口以支持调用插件, 完全原生支持
Deepseek Harness 0.2+ 插件系统":
  - DshPluginLoader: 加载 DSH 原生 Cordis ESM 插件 (lib/index.js),
    读取导出契约, list/get 注册 provider 的技能。
  - PluginManager 识别 DSH 原生插件 (无 plugin.json/toml 时)。
  - inject_skills_to_skill_manager: 把插件声明技能注入 SkillManager,
    使 _discover 原生发现 (不被 builtin 抢占)。
"""

import shutil
from pathlib import Path

import pytest

from tuan_cli.skills.plugin_sdk import DshPluginLoader, PluginManager
from tuan_cli.skills.manager import SkillManager


NODE_AVAILABLE = shutil.which("node") is not None


def _official_root() -> Path:
    """定位 G:/Tuan-CLI-Official (工作区根)。"""
    cands = [
        Path("G:/Tuan-CLI-Official"),
        Path("G:/Tuan-CLI-Official/plugins/tuan-skills-bundle"),
    ]
    for c in cands:
        if (c / "plugins" / "tuan-skills-bundle" / "lib" / "index.js").exists():
            return c
    return None


BUNDLE_DIR = None
_r = _official_root()
if _r is not None:
    BUNDLE_DIR = _r / "plugins" / "tuan-skills-bundle"


@pytest.mark.skipif(not NODE_AVAILABLE, reason="需要 node 以加载 DSH 原生插件")
@pytest.mark.skipif(BUNDLE_DIR is None or not (BUNDLE_DIR / "lib" / "index.js").exists(),
                    reason="缺少 tuan-skills-bundle 原生插件")
class TestDshPluginLoader:
    def test_is_dsh_native(self):
        assert DshPluginLoader.is_dsh_native(BUNDLE_DIR)
        assert DshPluginLoader.plugin_entry(BUNDLE_DIR) == BUNDLE_DIR / "lib" / "index.js"

    def test_describe(self):
        loader = DshPluginLoader(timeout=30)
        meta = loader.describe(BUNDLE_DIR)
        assert meta.get("name") == "tuan-skills-bundle"
        assert meta.get("hasApply") is True
        assert meta.get("hasConfig") is True
        assert "skills" in (meta.get("inject") or [])

    def test_describe_full_contract(self):
        """describe 增强: injectResolved/configFields/entry 完整契约。"""
        loader = DshPluginLoader(timeout=30)
        meta = loader.describe(BUNDLE_DIR)
        # inject 依赖解析结果
        inject_res = meta.get("injectResolved") or []
        assert any(
            item.get("service") == "skills" and item.get("resolved") is True
            for item in inject_res
        )
        # Config schema 字段类型映射
        fields = meta.get("configFields") or {}
        assert fields.get("providerName") == "string"
        assert fields.get("rank") == "number"
        assert fields.get("skillDirs") == "array"
        assert fields.get("watch") == "boolean"
        # 入口路径
        assert meta.get("entry")
        assert str(BUNDLE_DIR / "lib" / "index.js") in meta.get("entry", "")

    def test_list_skills(self):
        loader = DshPluginLoader(timeout=30)
        skills = loader.list_skills(BUNDLE_DIR)
        assert isinstance(skills, list)
        assert len(skills) >= 90
        names = {s["name"] for s in skills}
        assert "accessibility-wcag" in names
        assert "hyperframes" in names
        assert "tuan-design" in names

    def test_get_skills_has_content(self):
        loader = DshPluginLoader(timeout=30)
        skills = loader.get_skills(BUNDLE_DIR)
        assert isinstance(skills, list)
        assert len(skills) >= 90
        # 每个技能应有非空 content
        for s in skills[:10]:
            assert s.get("name")
            assert s.get("content")

    def test_patch_file(self):
        p = DshPluginLoader.patch_file(BUNDLE_DIR)
        assert p is not None
        assert p.name == "cordis.patch.yml"

    def test_read_patch(self):
        loader = DshPluginLoader(timeout=30)
        patch = loader.read_patch(BUNDLE_DIR)
        assert patch.get("file")
        inserts = patch.get("insert", [])
        assert len(inserts) >= 1
        assert inserts[0].get("id") == "tuan-skills-bundle"
        assert inserts[0].get("name") == "tuan-skills-bundle"
        assert isinstance(inserts[0].get("config"), dict)

    def test_plugin_info(self):
        loader = DshPluginLoader(timeout=30)
        info = loader.plugin_info(BUNDLE_DIR)
        assert info["is_native"] is True
        assert info["meta"].get("name") == "tuan-skills-bundle"
        assert len(info["skills"]) >= 90
        assert len(info["patch"].get("insert", [])) >= 1

    def test_schema_info(self):
        loader = DshPluginLoader(timeout=30)
        sch = loader.schema_info(BUNDLE_DIR)
        assert sch["hasConfig"] is True
        fields = sch["fields"]
        assert "providerName" in fields
        assert "rank" in fields
        assert "skillDirs" in fields
        assert fields["rank"]["type"] == "number"

    def test_validate_config_ok(self):
        loader = DshPluginLoader(timeout=30)
        res = loader.validate_config(BUNDLE_DIR, {"providerName": "tuan-skills", "rank": 300})
        assert res["valid"] is True
        assert res["config"].get("rank") == 300

    def test_validate_config_fills_defaults(self):
        """空 config 经 Config 校验返回含全部 schema 默认值的规范化配置。"""
        loader = DshPluginLoader(timeout=30)
        res = loader.validate_config(BUNDLE_DIR, {})
        assert res["valid"] is True
        cfg = res.get("config") or {}
        assert cfg.get("providerName") == "tuan-skills"
        assert cfg.get("rank") == 300
        assert cfg.get("watch") is True
        assert cfg.get("watchPollIntervalMs") == 1000
        assert cfg.get("maxEntries") == 1024
        assert cfg.get("skillDirs") == []

    def test_validate_config_reject(self):
        loader = DshPluginLoader(timeout=30)
        res = loader.validate_config(BUNDLE_DIR, {"rank": "not-a-number"})
        assert res["valid"] is False
        assert "rank" in str(res.get("error", ""))

    def test_install_with_config_persists(self, tmp_path):
        """install_from_directory 带合法 config: 校验通过并持久化 cordis.config.json。"""
        pm = PluginManager(tmp_path / "plugins")
        info = pm.install_from_directory(BUNDLE_DIR, config={"rank": 42})
        assert info is not None
        cfg = tmp_path / "plugins" / "tuan-skills-bundle" / "cordis.config.json"
        assert cfg.exists()
        import json
        data = json.loads(cfg.read_text(encoding="utf-8"))
        assert data.get("rank") == 42

    def test_install_with_bad_config_rejected(self, tmp_path):
        """install_from_directory 带非法 config: 拒绝并清理目录。"""
        pm = PluginManager(tmp_path / "plugins")
        with pytest.raises(ValueError):
            pm.install_from_directory(BUNDLE_DIR, config={"rank": "bad"})
        assert not (tmp_path / "plugins" / "tuan-skills-bundle").exists()

    @pytest.mark.skipif(BUNDLE_DIR is None or not BUNDLE_DIR.exists(), reason="缺少 tuan-skills-bundle")
    def test_installed_state_full_contract(self, tmp_path):
        """安装态端到端: 安装到任意位置后 get/describe/apply 全链路仍识别。"""
        pm = PluginManager(tmp_path / "plugins")
        info = pm.install_from_directory(BUNDLE_DIR, name="tuan-skills-bundle")
        assert info is not None
        assert info.manifest.name == "tuan-skills-bundle"
        # 安装态 get_plugin 识别为原生
        found = pm.get_plugin("tuan-skills-bundle")
        assert found is not None
        loader = DshPluginLoader(timeout=30)
        assert loader.is_dsh_native(info.path)
        # 安装态 describe 契约完整
        meta = loader.describe(info.path)
        assert meta.get("name") == "tuan-skills-bundle"
        assert len(meta.get("configFields") or {}) == 6
        # 安装态 apply 运行时: TUAN_SKILLS_DIRS 注入使技能根定位成功
        r = loader.apply_plugin(info.path, {"providerName": "tuan-skills", "rank": 300})
        assert r.get("applied") is True
        assert len(r.get("skills", [])) >= 90

    def test_apply_plugin(self):
        """apply_plugin 完整运行时执行: apply() 执行, provider/event 注册, 技能全量。"""
        loader = DshPluginLoader(timeout=30)
        r = loader.apply_plugin(BUNDLE_DIR, {"providerName": "tuan-skills", "rank": 300})
        assert r.get("applied") is True
        assert r.get("providerCount", 0) >= 1
        assert r.get("eventCount", 0) >= 1
        assert len(r.get("skills", [])) >= 90
        # invalidate 通路可观测: 初始无触发 (watch 变更需真实事件循环)
        assert isinstance(r.get("invalidations"), int)
        assert r.get("invalidations", 0) >= 0
        # 注入依赖解析结果
        inject_res = r.get("injectResolved") or []
        assert any(
            item.get("service") == "skills" and item.get("resolved") is True
            for item in inject_res
        )

    def test_apply_logger_callable_and_effect(self):
        """ctx.logger 可调用契约 + effect 处置函数契约:
        插件 ctx.logger("x") 返回具名门面, ctx.effect 的 yield 处置函数被安全调用。"""
        loader = DshPluginLoader(timeout=30)
        r = loader.apply_plugin(BUNDLE_DIR, {"providerName": "tuan-skills", "rank": 300})
        assert r.get("applied") is True
        # effect 处置函数已收集并安全执行 (tuan-skills-bundle 有 1 个 watcher effect)
        assert r.get("effectCount", 0) >= 1
        # 处置函数执行无错误
        assert not r.get("effectErrors")
        # logger 门面被调用过 (ctx.logger?.info / ctx.logger("...") 均有产出)
        assert r.get("logs", 0) >= 1

    def test_emit_mutation_observed(self):
        """observeHostMutation 接线: fs/observed 事件派发命中 host 并转调 observeHostMutation。"""
        loader = DshPluginLoader(timeout=30)
        r = loader.emit_mutation(BUNDLE_DIR, actor="edit")
        assert r.get("listeners", 0) >= 1
        assert r.get("mutationCount", 0) >= 1
        assert not r.get("emitErrors")

    def test_emit_mutation_non_edit_ignored(self):
        """actor 非 edit/write 时 host 不转调 observeHostMutation (与真实 DSH 过滤一致)。"""
        loader = DshPluginLoader(timeout=30)
        r = loader.emit_mutation(BUNDLE_DIR, actor="delete")
        assert r.get("listeners", 0) >= 1
        assert r.get("mutationCount", 0) == 0


@pytest.mark.skipif(not NODE_AVAILABLE, reason="需要 node")
class TestNativePluginScan:
    def test_scan_detects_native(self, tmp_path):
        """无 plugin.json/toml, 仅有 lib/index.js 的目录应被识别为原生插件。"""
        plugins_dir = tmp_path / "plugins"
        pm = PluginManager(plugins_dir)  # 先构造 (首次 _scan 为空)
        plugin_dir = plugins_dir / "native-demo"
        lib = plugin_dir / "lib"
        lib.mkdir(parents=True)
        (lib / "index.js").write_text(
            "export const name = 'native-demo';\n"
            "export const inject = ['skills'];\n"
            "export function apply(ctx) {}\n",
            encoding="utf-8",
        )
        pm._scan()
        info = pm.get_plugin("native-demo")
        assert info is not None
        assert info.manifest.format == "dsh_native"
        assert info.manifest.metadata.get("dsh_native") is True

    def test_apply_with_full_host_services(self, tmp_path):
        """inject 声明全部已知宿主服务 (fs/config/command/http/timer/logger) 的插件
        apply 不因 ctx 缺服务抛错 (完全原生支持 DSH 0.2 几乎所有插件系统)。"""
        plugin_dir = tmp_path / "multi-service"
        lib = plugin_dir / "lib"
        lib.mkdir(parents=True)
        (lib / "index.js").write_text(
            "export const name = 'multi-service';\n"
            "export const inject = ['skills', 'logger', 'fs', 'config', 'command', 'http', 'timer'];\n"
            "export function apply(ctx) {\n"
            "  // 触碰所有声明服务, 若 ctx 缺任一则抛错\n"
            "  ctx.logger.info('x');\n"
            "  ctx.fs.watch('x', () => {});\n"
            "  ctx.config.get('x', 1);\n"
            "  ctx.command('x').action(() => {}).usage('u').option('-n, --name <n>');\n"
            "  ctx.http.get('http://x');\n"
            "  ctx.timer.setTimeout(() => {}, 1);\n"
            "  ctx.skills.registerProvider((ctrl) => ({\n"
            "    name: 'multi-service',\n"
            "    async list() { return []; },\n"
            "    dispose() { return Promise.resolve(); },\n"
            "  }));\n"
            "}\n",
            encoding="utf-8",
        )
        loader = DshPluginLoader(timeout=30)
        r = loader.apply_plugin(plugin_dir, {})
        assert r.get("applied") is True
        # 全部已知服务解析为 resolved
        inject_res = r.get("injectResolved") or []
        assert len(inject_res) == 7
        assert all(item.get("resolved") is True for item in inject_res)
        # command 桩函数式契约: ctx.command('x').action() 链式执行并记录注册命令
        assert "x" in (r.get("commands") or [])

    def test_apply_patch_insert_append(self, tmp_path):
        """apply_patch: insert 追加新服务到 services 段。"""
        loader = DshPluginLoader(timeout=30)
        target = tmp_path / "cordis.yml"
        patch = {"insert": [{"id": "tuan-skills-bundle", "name": "tuan-skills-bundle",
                             "config": {"rank": 300}}], "remove": []}
        r = loader.apply_patch(patch, target)
        assert r.get("ok") is True
        assert r.get("inserted") == ["tuan-skills-bundle"]
        import yaml
        doc = yaml.safe_load(target.read_text(encoding="utf-8"))
        assert doc["services"][0]["id"] == "tuan-skills-bundle"
        assert doc["services"][0]["config"]["rank"] == 300

    def test_apply_patch_insert_replace_and_remove(self, tmp_path):
        """apply_patch: insert 同 id 整行替换 + remove 删除。"""
        loader = DshPluginLoader(timeout=30)
        target = tmp_path / "cordis.yml"
        target.write_text(
            "services:\n"
            "  - id: tuan-skills-bundle\n"
            "    name: tuan-skills-bundle\n"
            "    config: {rank: 300}\n"
            "  - id: legacy\n"
            "    name: legacy\n",
            encoding="utf-8",
        )
        patch = {
            "insert": [{"id": "tuan-skills-bundle", "name": "tuan-skills-bundle",
                        "config": {"rank": 500}}],
            "remove": [{"id": "legacy"}],
        }
        r = loader.apply_patch(patch, target)
        assert r.get("ok") is True
        assert r.get("inserted") == ["tuan-skills-bundle"]
        assert r.get("removed") == ["legacy"]
        import yaml
        doc = yaml.safe_load(target.read_text(encoding="utf-8"))
        assert len(doc["services"]) == 1
        assert doc["services"][0]["id"] == "tuan-skills-bundle"
        assert doc["services"][0]["config"]["rank"] == 500

    def test_apply_patch_remove_missing_target(self, tmp_path):
        """apply_patch: remove 但目标不存在 → 报错。"""
        loader = DshPluginLoader(timeout=30)
        target = tmp_path / "cordis.yml"
        patch = {"insert": [], "remove": [{"id": "x"}]}
        r = loader.apply_patch(patch, target)
        assert r.get("ok") is False
        assert "remove" in r.get("error", "")

    @pytest.mark.skipif(BUNDLE_DIR is None or not BUNDLE_DIR.exists(), reason="缺少 tuan-skills-bundle")
    def test_get_skills_full_definition(self):
        """get_skills: DSH get 契约——返回全部技能完整定义, 含 content 正文。"""
        loader = DshPluginLoader(timeout=30)
        full = loader.get_skills(BUNDLE_DIR)
        assert len(full) >= 90
        assert all(s.get("name") for s in full)
        # 全部含非空 content (DSH validateDefinition 对空 content 是硬失败)
        assert all(s.get("content") for s in full)
        # 抽查: name 与 list_skills 一致, description 非空
        sample = full[0]
        assert sample.get("description")
        assert len(sample.get("content", "")) > 50
