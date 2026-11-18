"""Plugin SDK — 插件化技能包的标准化管理。

对标 Claude Code 2.1.239 Plugin Marketplace:
- plugin.json manifest: 声明插件元数据、依赖、技能列表、钩子
- headersHelper: 自定义 HTTP 头 (支持短生命周期 token)
- 技能命名空间: plugin-name:skill-name (避免冲突)
- 生命周期钩子: install / uninstall / enable / disable
- 版本管理: semver 兼容性检查
- 依赖解析: 插件间依赖声明
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore

import logging
log = logging.getLogger(__name__)


def _common_ancestor(paths: List[Path]) -> Optional[Path]:
    """返回一组路径的最低公共祖先目录。

    用于把插件声明式技能 (可能分散于多个目录) 收敛为一个 _discover
    能一层深扫描的根目录。空输入或无法确定的公共祖先返回 None。
    """
    if not paths:
        return None
    # 用父目录的 parts 做前缀交集; 绝对路径保证 parts[0] 为根 ('' 或 '/'/'C:\\')
    try:
        parents = [list(p.resolve().parents) for p in paths]
        common = parents[0]
        for plist in parents[1:]:
            common = [x for x in common if x in plist]
        if not common:
            # 无公共祖先 (不同盘符等): 退回最深共同父级, 找不到则 None
            return None
        # common 已按深度降序 (parents[0] 最深); 取最深公共祖先
        return common[0]
    except Exception as exc:  # noqa: BLE001 - 路径解析异常时降级
        log.debug("公共祖先路径解析失败, 降级为 None: %s", exc)
        return None


# ================================================================ 数据结构

@dataclass
class PluginManifest:
    """plugin.json / plugin.toml 的标准化表示 (兼容 DSH 0.2+)。"""
    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    license: str = ""
    repository: str = ""
    # 技能列表: [{name, description, path, auto_invoke}]
    skills: List[Dict[str, Any]] = field(default_factory=list)
    # 钩子: {install, uninstall, enable, disable} — shell 命令或脚本路径
    hooks: Dict[str, str] = field(default_factory=dict)
    # 依赖: {plugin-name: version-range}
    dependencies: Dict[str, str] = field(default_factory=dict)
    # 兼容性: {min_tuan_version, min_dsh_version, platforms, requires}
    compatibility: Dict[str, str] = field(default_factory=dict)
    # headersHelper: 生成 HTTP 头的命令
    headers_helper: str = ""
    # 元数据: 任意键值对 (含 tags / category 等 DSH 0.2 字段)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # 格式来源标记: "tuan" (旧 plugin.json) | "dsh" (DSH 0.2 plugin.toml/plugin.json)
    format: str = "tuan"

    @classmethod
    def from_dict(cls, data: Dict[str, Any], fmt: str = "tuan") -> "PluginManifest":
        compat = data.get("compatibility", {}) or {}
        # 规范化 compatibility: 允许字符串或 dict 字段混合
        if not isinstance(compat, dict):
            compat = {}
        return cls(
            name=str(data.get("name", "")),
            version=str(data.get("version", "0.1.0")),
            description=str(data.get("description", "")),
            author=str(data.get("author", "")),
            license=str(data.get("license", "")),
            repository=str(data.get("repository", "")),
            skills=data.get("skills", []) or [],
            hooks=data.get("hooks", {}) or {},
            dependencies=data.get("dependencies", {}) or {},
            compatibility=compat,
            headers_helper=str(data.get("headersHelper", "")),
            metadata=data.get("metadata", {}) or {},
            format=fmt,
        )

    def validate_dsh_compat(
        self,
        current_dsh_version: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """检查当前 DSH 版本是否满足 manifest.compatibility.min_dsh_version。

        返回 (ok, reason):
          - ok=True: 兼容 (或未声明 min_dsh_version, 或 DSH 未安装且字段可跳过)
          - ok=False: 不兼容, reason 说明原因
        """
        min_dsh = self.compatibility.get("min_dsh_version")
        if not min_dsh:
            return True, ""
        if not current_dsh_version:
            # DSH 未安装: 视为不阻断 (跳过检查), 由调用方决定是否警告
            return True, "DSH 未安装, 跳过 min_dsh_version 检查"
        if _version_satisfies(current_dsh_version, f">={min_dsh}"):
            return True, ""
        return False, (
            f"DSH 版本不满足: 当前 {current_dsh_version}, "
            f"插件 {self.name} 需要 >={min_dsh}"
        )

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "name": self.name,
            "version": self.version,
        }
        if self.description:
            d["description"] = self.description
        if self.author:
            d["author"] = self.author
        if self.license:
            d["license"] = self.license
        if self.repository:
            d["repository"] = self.repository
        if self.skills:
            d["skills"] = self.skills
        if self.hooks:
            d["hooks"] = self.hooks
        if self.dependencies:
            d["dependencies"] = self.dependencies
        if self.compatibility:
            d["compatibility"] = self.compatibility
        if self.headers_helper:
            d["headersHelper"] = self.headers_helper
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class PluginInfo:
    """已安装插件的运行时信息。"""
    manifest: PluginManifest
    path: Path              # 插件目录
    enabled: bool = True
    installed_at: float = 0.0
    updated_at: float = 0.0
    source: str = "local"   # local | marketplace | git | url

    @property
    def qualified_name(self) -> str:
        return self.manifest.name

    def skill_names(self) -> List[str]:
        """返回所有技能的限定名 (plugin:skill 格式)。"""
        return [
            f"{self.manifest.name}:{s['name']}"
            for s in self.manifest.skills
            if s.get("name")
        ]


# ================================================================ Semver 兼容性

def _parse_version(v: str) -> Tuple[int, int, int]:
    """解析 semver 版本号。"""
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", v.strip())
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return (0, 0, 0)


def _version_satisfies(current: str, requirement: str) -> bool:
    """检查版本是否满足要求 (支持 ^~>= 等)。"""
    cur = _parse_version(current)
    req = requirement.strip()
    if req.startswith("^"):
        # ^1.2.3: >=1.2.3, <2.0.0
        base = _parse_version(req[1:])
        return cur >= base and cur[0] == base[0]
    elif req.startswith("~"):
        # ~1.2.3: >=1.2.3, <1.3.0
        base = _parse_version(req[1:])
        return cur >= base and cur[0] == base[0] and cur[1] == base[1]
    elif req.startswith(">="):
        return cur >= _parse_version(req[2:])
    elif req.startswith(">"):
        return cur > _parse_version(req[1:])
    elif req.startswith("<"):
        return cur < _parse_version(req[1:])
    elif req.startswith("=") or req.startswith("=="):
        return cur == _parse_version(req.lstrip("="))
    else:
        # 精确匹配
        return cur == _parse_version(req)


# ================================================================ Plugin Manager

class PluginManager:
    """插件管理器 — 安装/卸载/启用/禁用/更新插件。

    插件存储结构:
        <plugins_dir>/
        ├── my-plugin/
        │   ├── plugin.json
        │   ├── SKILL.md (或 skills/*/SKILL.md)
        │   ├── scripts/
        │   └── ...
        └── another-plugin/
            └── ...
    """

    def __init__(self, plugins_dir: Path) -> None:
        self.plugins_dir = Path(plugins_dir)
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, PluginInfo] = {}
        self._dsh_version: Optional[str] = None
        self._dsh_version_checked: bool = False
        self._scan()

    # ------------------------------------------------------------- DSH 0.2 兼容

    def check_dsh_version(self, force: bool = False) -> Optional[str]:
        """探测本机 DSH 版本。

        优先级:
          1. 缓存 (除非 force=True)
          2. `~/.tuan/dsh_version` 文件 (单行 semver)
          3. `dsh --version` 子进程 (解析首个 semver 形态的 token)
        未安装 DSH 时返回 None。
        """
        if self._dsh_version_checked and not force:
            return self._dsh_version
        self._dsh_version_checked = True
        # 1) 文件缓存
        version_file = self.plugins_dir.parent / "dsh_version"
        try:
            if version_file.is_file():
                text = version_file.read_text(encoding="utf-8").strip()
                if text:
                    self._dsh_version = text.splitlines()[0].strip()
                    return self._dsh_version
        except Exception as exc:  # noqa: BLE001
            log.debug(
                "PluginManager.check_dsh_version(): 读取 %s 失败: %s",
                version_file, exc,
            )
        # 2) dsh --version
        try:
            import subprocess
            result = subprocess.run(
                ["dsh", "--version"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                output = (result.stdout or "") + (result.stderr or "")
                m = re.search(r"(\d+\.\d+\.\d+)", output)
                if m:
                    self._dsh_version = m.group(1)
                    return self._dsh_version
        except FileNotFoundError:
            log.debug("PluginManager.check_dsh_version(): dsh 命令未找到")
        except Exception as exc:  # noqa: BLE001
            log.debug(
                "PluginManager.check_dsh_version(): 非致命异常已忽略: %s", exc,
            )
        self._dsh_version = None
        return None

    def resolve_dsh_plugin_format(
        self, plugin_dir: Path,
    ) -> Optional[Tuple[Dict[str, Any], str]]:
        """检测并解析 DSH 0.2 格式的 plugin.toml / plugin.json。

        返回 (data, fmt) 其中 fmt ∈ {"dsh_toml", "dsh_json"}; 非插件目录返回 None。
        plugin.toml 优先, 回退到 plugin.json。
        """
        plugin_dir = Path(plugin_dir)
        toml_path = plugin_dir / "plugin.toml"
        json_path = plugin_dir / "plugin.json"
        if toml_path.is_file():
            if tomllib is None:
                log.warning(
                    "PluginManager.resolve_dsh_plugin_format(): "
                    "检测到 %s 但当前 Python < 3.11 缺少 tomllib, 跳过",
                    toml_path,
                )
            else:
                try:
                    raw = toml_path.read_bytes()
                    # 容错 UTF-8 BOM (Windows 编辑器常见)
                    if raw.startswith(b"\xef\xbb\xbf"):
                        raw = raw[3:]
                    data = tomllib.loads(raw.decode("utf-8"))
                    if isinstance(data, dict) and data.get("name"):
                        return data, "dsh_toml"
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "PluginManager.resolve_dsh_plugin_format(): "
                        "解析 %s 失败: %s", toml_path, exc,
                    )
        if json_path.is_file():
            try:
                try:
                    raw = json_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    raw = json_path.read_text(encoding="utf-8-sig")
                data = json.loads(raw)
                if isinstance(data, dict) and data.get("name"):
                    # 旧 tuan plugin.json 与 DSH plugin.json 共用扩展名;
                    # 通过 min_dsh_version / skills[].auto_invoke 等字段判别为 dsh
                    compat = data.get("compatibility") or {}
                    is_dsh = isinstance(compat, dict) and "min_dsh_version" in compat
                    return data, ("dsh_json" if is_dsh else "tuan_json")
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "PluginManager.resolve_dsh_plugin_format(): "
                    "解析 %s 失败: %s", json_path, exc,
                )
        return None

    # ------------------------------------------------------------- DSH 原生 ESM 插件

    @staticmethod
    def _native_entry(plugin_dir: Path) -> Optional[Path]:
        """定位 DSH 原生插件的 ESM 入口 (lib/index.js → index.js)。"""
        plugin_dir = Path(plugin_dir)
        for rel in ("lib/index.js", "index.js"):
            cand = plugin_dir / rel
            if cand.is_file():
                return cand
        return None

    def _manifest_from_native(self, plugin_dir: Path) -> Optional[PluginManifest]:
        """为 DSH 0.2 原生 ESM 插件合成一个 PluginManifest。

        通过 Node 子进程读取插件导出的 name/inject (describe 模式, 不实例化)。
        若无 Node 或加载失败, 用目录名作为 fallback name。
        仅当存在 lib/index.js 时才视为原生插件。
        """
        entry = self._native_entry(plugin_dir)
        if entry is None:
            return None
        name = plugin_dir.name
        description = ""
        metadata: Dict[str, Any] = {"dsh_native": True, "entry": str(entry)}
        # 尝试用 Node 读取导出契约 (非阻塞, 失败降级为目录名)
        try:
            loader = DshPluginLoader()
            meta = loader.describe(plugin_dir)
            if meta.get("name"):
                name = str(meta["name"])
            metadata["dsh_name"] = meta.get("name")
            metadata["dsh_inject"] = meta.get("inject")
            metadata["dsh_has_apply"] = bool(meta.get("hasApply"))
        except Exception as exc:  # noqa: BLE001
            log.debug(
                "PluginManager._manifest_from_native(): describe 失败, 用目录名 fallback: %s", exc,
            )
        return PluginManifest(
            name=name,
            version="0.1.0",
            description=description,
            author="",
            license="",
            repository="",
            skills=[],
            hooks={},
            dependencies={},
            compatibility={},
            headers_helper="",
            metadata=metadata,
            format="dsh_native",
        )

    def _scan(self) -> None:
        """扫描已安装插件 (兼容旧 tuan 格式、DSH 0.2 格式、DSH 原生 ESM 插件)。"""
        self._cache.clear()
        if not self.plugins_dir.is_dir():
            return
        for entry in sorted(self.plugins_dir.iterdir()):
            if not entry.is_dir():
                continue
            resolved = self.resolve_dsh_plugin_format(entry)
            if resolved is None:
                # 无 plugin.json/toml: 尝试识别 DSH 0.2 原生 ESM 插件 (lib/index.js)
                manifest = self._manifest_from_native(entry)
                if manifest is None:
                    continue
                fmt = "dsh_native"
            else:
                data, fmt = resolved
                try:
                    manifest = PluginManifest.from_dict(data, fmt=fmt)
                except Exception as exc:  # noqa: BLE001
                    log.debug("PluginManager._scan(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                    continue
            try:
                if not manifest.name:
                    continue
                enabled_path = entry / ".enabled"
                enabled = (
                    not enabled_path.exists()
                    or enabled_path.read_text(encoding="utf-8").strip() != "false"
                )
                if (entry / "plugin.toml").is_file():
                    manifest_mtime = (entry / "plugin.toml").stat().st_mtime
                elif (entry / "plugin.json").is_file():
                    manifest_mtime = (entry / "plugin.json").stat().st_mtime
                else:
                    # DSH 原生插件: 用入口文件 (lib/index.js) mtime
                    entry_file = self._native_entry(entry)
                    manifest_mtime = entry_file.stat().st_mtime if entry_file else entry.stat().st_mtime
                self._cache[manifest.name] = PluginInfo(
                    manifest=manifest,
                    path=entry,
                    enabled=enabled,
                    installed_at=entry.stat().st_mtime,
                    updated_at=manifest_mtime,
                )
            except Exception as exc:
                log.debug("PluginManager._scan(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                continue

    def list_plugins(self) -> List[PluginInfo]:
        """列出所有已安装插件。"""
        return list(self._cache.values())

    def get_plugin(self, name: str) -> Optional[PluginInfo]:
        """获取指定插件信息。"""
        return self._cache.get(name)

    def install_from_directory(
        self, source: Path, name: Optional[str] = None, config: Optional[Dict[str, Any]] = None
    ) -> PluginInfo:
        """从本地目录安装插件 (兼容旧 tuan plugin.json 与 DSH 0.2 plugin.toml)。

        config: DSH 原生插件的配置, 安装时经 Config 校验并持久化到 cordis.config.json。
        校验失败抛 ValueError, 不安装。
        """
        source = Path(source).resolve()
        resolved = self.resolve_dsh_plugin_format(source)
        if resolved is None:
            # 无 plugin.json/toml: 尝试识别 DSH 0.2 原生 ESM 插件 (lib/index.js)
            manifest = self._manifest_from_native(source)
            if manifest is None:
                raise ValueError(f"目录 {source} 中没有 plugin.toml / plugin.json / lib/index.js")
        else:
            data, fmt = resolved
            manifest = PluginManifest.from_dict(data, fmt=fmt)
        plugin_name = name or manifest.name
        if not plugin_name:
            raise ValueError("插件名称不能为空")

        # DSH 兼容性检查 (不阻断安装, 仅警告)
        dsh_version = self.check_dsh_version()
        ok, reason = manifest.validate_dsh_compat(dsh_version)
        if not ok:
            log.warning(
                "PluginManager.install_from_directory(): DSH 兼容性不满足: %s", reason,
            )
        elif reason:
            log.info("PluginManager.install_from_directory(): %s", reason)

        # 检查依赖
        self._check_dependencies(manifest)

        target = self.plugins_dir / plugin_name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target, dirs_exist_ok=True)

        # DSH 原生插件: 配置校验 + 持久化 cordis.config.json
        if config:
            loader = DshPluginLoader()
            if loader.is_dsh_native(target):
                vres = loader.validate_config(target, config)
                if not vres.get("valid"):
                    shutil.rmtree(target, ignore_errors=True)
                    raise ValueError(f"插件配置校验失败: {vres.get('error')}")
                norm = vres.get("config") or config
                cfg_file = target / "cordis.config.json"
                cfg_file.write_text(
                    json.dumps(norm, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            else:
                cfg_file = target / "cordis.config.json"
                cfg_file.write_text(
                    json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
                )

        # 写入启用标记
        (target / ".enabled").write_text("true", encoding="utf-8")

        # 执行 install hook
        self._run_hook(target, manifest, "install")

        # 刷新缓存
        self._scan()
        info = self._cache.get(plugin_name)
        if info is None:
            # 目录名与 manifest.name 可能不同 (显式 name 覆盖): 按目录名回退
            info = next(
                (p for p in self._cache.values() if p.path.name == plugin_name),
                None,
            )
        if info is None:
            raise RuntimeError(f"安装后未找到插件 {plugin_name}")
        info.source = "local"
        return info

    def uninstall(self, name: str) -> bool:
        """卸载插件。"""
        info = self._cache.get(name)
        if info is None:
            return False

        # 执行 uninstall hook
        self._run_hook(info.path, info.manifest, "uninstall")

        shutil.rmtree(info.path, ignore_errors=True)
        self._cache.pop(name, None)
        return True

    def enable(self, name: str) -> bool:
        """启用插件。"""
        info = self._cache.get(name)
        if info is None:
            return False
        (info.path / ".enabled").write_text("true", encoding="utf-8")
        info.enabled = True
        self._run_hook(info.path, info.manifest, "enable")
        return True

    def disable(self, name: str) -> bool:
        """禁用插件。"""
        info = self._cache.get(name)
        if info is None:
            return False
        (info.path / ".enabled").write_text("false", encoding="utf-8")
        info.enabled = False
        self._run_hook(info.path, info.manifest, "disable")
        return True

    def get_all_skills(self) -> List[Dict[str, Any]]:
        """获取所有已启用插件的技能列表。"""
        skills = []
        for info in self._cache.values():
            if not info.enabled:
                continue
            for skill in info.manifest.skills:
                skill_path = info.path / skill.get("path", "SKILL.md")
                if not skill_path.exists():
                    skill_path = info.path / "SKILL.md"
                skills.append({
                    "name": f"{info.manifest.name}:{skill.get('name', 'unknown')}",
                    "description": skill.get("description", ""),
                    "path": str(skill_path),
                    "auto_invoke": skill.get("auto_invoke", False),
                    "plugin": info.manifest.name,
                    "plugin_version": info.manifest.version,
                })
        return skills

    def inject_skills_to_skill_manager(
        self,
        skill_manager: Any,
        search_dirs: Optional[List[Tuple[Path, str]]] = None,
    ) -> int:
        """把所有已启用插件的技能目录注入到 SkillManager._search_dirs。

        对每个已启用插件, 把 `<plugin>/skills` (若存在) 加入 _search_dirs,
        origin 标记为 "plugin"; SkillManager._discover 会按
        `<search_dir>/<slug>/SKILL.md` 自然发现每个 DSH 0.2 技能包。

        插件根目录直接放 SKILL.md 的形态 (无 skills/ 子目录) 不通过
        _search_dirs 注入 (会误发现同目录其他插件); 这种情况请使用
        `PluginManager.get_all_skills()` / `resolve_skill()` 读取。

        search_dirs 参数: 显式传入构建中的搜索目录列表 (在
        SkillManager._build_search_dirs 构建期间 _search_dirs 尚未赋值, 需
        把构建中的 dirs 列表传进来才能注入)。

        返回注入的目录数量。
        """
        if skill_manager is None:
            return 0
        if search_dirs is None:
            search_dirs = getattr(skill_manager, "_search_dirs", None)
        if search_dirs is None:
            log.debug(
                "inject_skills_to_skill_manager(): 目标 SkillManager 无 "
                "_search_dirs, 跳过",
            )
            return 0

        existing = {(str(p.resolve()), o) for p, o in search_dirs}
        injected = 0
        # 插件来源应排在 builtin 之前 (plugin > builtin), 否则同名技能被
        # builtin 抢占。找到首个 builtin 条目的索引作为插入点。
        insert_at = len(search_dirs)
        for i, (p, o) in enumerate(search_dirs):
            if o == "builtin":
                insert_at = i
                break
        for info in self._cache.values():
            if not info.enabled:
                continue
            skills_dir = info.path / "skills"
            if skills_dir.is_dir():
                key = (str(skills_dir.resolve()), "plugin")
                if key not in existing:
                    search_dirs.insert(insert_at, (skills_dir, "plugin"))
                    existing.add(key)
                    injected += 1
                    insert_at += 1
            # DSH 0.2 声明式技能: plugin.json 里 skills[].path 可能是绝对路径,
            # 指向插件外 (如工作区 skills/)。_discover 按 <search_dir>/<slug>/SKILL.md
            # 一层深扫描, 所以注入这些路径的**共同祖先目录**一次, 即可原生发现
            # 全部声明技能, 而不必逐个注入 (逐个父目录会被 _discover 漏掉,
            # 因为技能包是 <root>/<slug>/SKILL.md 而非 <parent>/<slug>/SKILL.md)。
            skill_paths: list[Path] = []
            for skill in info.manifest.skills:
                sp = skill.get("path", "")
                if not sp:
                    continue
                cand = Path(sp)
                if not cand.is_absolute():
                    cand = info.path / sp
                skill_paths.append(cand)
            if skill_paths:
                root = _common_ancestor(skill_paths)
                if root is not None and root.is_dir():
                    key = (str(root.resolve()), "plugin")
                    if key not in existing:
                        search_dirs.insert(insert_at, (root, "plugin"))
                        existing.add(key)
                        injected += 1
                        insert_at += 1
        return injected

    def resolve_skill(self, qualified_name: str) -> Optional[Dict[str, Any]]:
        """解析限定技能名 (plugin:skill) → 技能信息。"""
        if ":" not in qualified_name:
            return None
        plugin_name, skill_name = qualified_name.split(":", 1)
        info = self._cache.get(plugin_name)
        if info is None or not info.enabled:
            return None
        for skill in info.manifest.skills:
            if skill.get("name") == skill_name:
                skill_path = info.path / skill.get("path", "SKILL.md")
                if not skill_path.exists():
                    skill_path = info.path / "SKILL.md"
                return {
                    "name": qualified_name,
                    "description": skill.get("description", ""),
                    "path": str(skill_path),
                    "body": skill_path.read_text(encoding="utf-8") if skill_path.exists() else "",
                    "plugin": plugin_name,
                }
        return None

    def _check_dependencies(self, manifest: PluginManifest) -> None:
        """检查插件依赖是否满足。"""
        for dep_name, dep_version in manifest.dependencies.items():
            dep_info = self._cache.get(dep_name)
            if dep_info is None:
                raise ValueError(f"缺少依赖插件: {dep_name} (需要 {dep_version})")
            if not _version_satisfies(dep_info.manifest.version, dep_version):
                raise ValueError(
                    f"依赖插件 {dep_name} 版本不满足: "
                    f"已安装 {dep_info.manifest.version}, 需要 {dep_version}"
                )

    def _run_hook(self, plugin_path: Path, manifest: PluginManifest, hook_name: str) -> None:
        """执行插件生命周期钩子。

        支持两种 hook 形态:
          - shell 命令字符串: 直接 shell=True 执行
          - 脚本相对路径 (DSH 0.2 风格, 如 "scripts/install.sh"):
            按 Windows / POSIX 选择 .ps1/.bat/.cmd/.sh/.py, 找不到则跳过
        """
        hook_cmd = manifest.hooks.get(hook_name)
        if not hook_cmd:
            return
        try:
            import subprocess
            script = self._resolve_hook_script(plugin_path, hook_cmd)
            if script is not None:
                subprocess.run(
                    script,
                    shell=False,
                    cwd=str(plugin_path),
                    timeout=30,
                    capture_output=True,
                )
            else:
                subprocess.run(
                    hook_cmd,
                    shell=True,
                    cwd=str(plugin_path),
                    timeout=30,
                    capture_output=True,
                )
        except Exception as exc:
            log.warning("PluginManager._run_hook(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass  # 钩子失败不阻断主流程

    @staticmethod
    def _resolve_hook_script(plugin_path: Path, hook_cmd: str) -> Optional[List[str]]:
        """若 hook_cmd 指向插件内脚本文件, 返回可执行命令列表; 否则返回 None。

        DSH 0.2 hooks 常写为 "scripts/install.sh"; 本方法做跨平台解析:
          - 优先尝试 hook_cmd 原样
          - Windows 下再尝试替换扩展名为 .ps1/.bat/.cmd
          - .py 直接用 sys.executable 运行
        """
        candidate = Path(hook_cmd)
        if candidate.is_absolute() or " " in hook_cmd or not candidate.suffix:
            return None
        full = plugin_path / candidate
        ext = full.suffix.lower()
        try:
            if ext == ".py" and full.is_file():
                import sys
                return [sys.executable, str(full)]
            if full.is_file():
                if ext == ".sh":
                    return ["bash", str(full)]
                if ext == ".ps1":
                    return ["powershell", "-NoProfile", "-File", str(full)]
                if ext in (".bat", ".cmd"):
                    return [str(full)]
                return [str(full)]
            # Windows 扩展名回退
            if os.name == "nt":
                for alt in (".ps1", ".bat", ".cmd", ".py"):
                    alt_full = full.with_suffix(alt)
                    if alt_full.is_file():
                        return PluginManager._resolve_hook_script(
                            plugin_path, str(candidate.with_suffix(alt)),
                        )
        except Exception as exc:  # noqa: BLE001
            log.debug(
                "PluginManager._resolve_hook_script(): 非致命异常已忽略: %s", exc,
            )
        return None


# ================================================================ Headers Helper

class HeadersHelper:
    """自定义 HTTP 头生成器 (对标 Claude Code headersHelper)。

    用于插件市场需要认证的场景: 指定一个命令, 该命令输出 JSON 格式的 HTTP 头。
    """

    @staticmethod
    def resolve(command: str, cwd: Optional[Path] = None, timeout: int = 10) -> Dict[str, str]:
        """执行 headersHelper 命令, 返回 HTTP 头字典。"""
        if not command.strip():
            return {}
        try:
            import subprocess
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(cwd) if cwd else None,
                timeout=timeout,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return {}
            output = result.stdout.strip()
            if not output:
                return {}
            # 尝试解析为 JSON
            try:
                headers = json.loads(output)
                if isinstance(headers, dict):
                    return {str(k): str(v) for k, v in headers.items()}
            except json.JSONDecodeError:
                # 尝试解析为 "Key: Value" 格式
                headers = {}
                for line in output.splitlines():
                    if ": " in line:
                        k, v = line.split(": ", 1)
                        headers[k.strip()] = v.strip()
                return headers
        except Exception as exc:
            log.warning("HeadersHelper.resolve(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass
        return {}

    @staticmethod
    def safe_resolve(command: str, cwd: Optional[Path] = None) -> Dict[str, str]:
        """安全解析: 不继承凭证环境变量, 仅从指定目录执行。"""
        # 清除敏感环境变量
        clean_env = {k: v for k, v in os.environ.items()
                     if not any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH"))}
        try:
            import subprocess
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(cwd) if cwd else None,
                timeout=10,
                capture_output=True,
                text=True,
                env=clean_env,
            )
            if result.returncode != 0:
                return {}
            headers = json.loads(result.stdout.strip())
            if isinstance(headers, dict):
                return {str(k): str(v) for k, v in headers.items()}
        except Exception as exc:
            log.warning("HeadersHelper.safe_resolve(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass
        return {}


# ================================================================ DSH 0.2 原生插件加载器
#
# DeepSeek Harness 0.2+ 的"原生插件"不是声明式 plugin.json, 而是 Cordis ESM 模块:
#   <plugin>/lib/index.js  (或 <plugin>/index.js)
#     导出: name (string), inject (string[]), Config (schemastery schema),
#           apply(ctx, config) —— 注册 provider / 订阅事件 / 声明 effect
#   <plugin>/cordis.patch.yml —— DSH patch 行清单 (insert/remove)
#
# Tuan-CLI 是 Python, 无法直接 import ESM; 故经 Node 子进程执行一个内嵌引导脚本,
# 动态 import() 插件模块、构造最小 Cordis ctx 桩、调用 apply(), 并把注册的
# provider 能力 (list/get) 序列化为 JSON 回传。零改动 DSH 源码, 完全原生。

# 内嵌引导脚本: 加载一个 DSH 0.2 原生插件并输出其注册的 provider 能力。
# 参数(环境变量 DSH_PLUGIN_URL / DSH_PLUGIN_CONFIG / DSH_PLUGIN_OP):
#   DSH_PLUGIN_OP=list     -> 输出 provider.list() 候选摘要数组
#   DSH_PLUGIN_OP=get      -> 输出 provider.get(首个候选) 的完整定义
#   DSH_PLUGIN_OP=describe -> 输出 {name, inject, configSchema} (不实例化)
# stdout 输出一个 JSON 对象 {ok, data} 或 {ok:false, error}。
_DSH_BOOTSTRAP = r"""
import { pathToFileURL } from "node:url";

const pluginUrl = process.env.DSH_PLUGIN_URL;
const configRaw = process.env.DSH_PLUGIN_CONFIG || "{}";
const op = process.env.DSH_PLUGIN_OP || "describe";
let config;
try { config = JSON.parse(configRaw); } catch { config = {}; }

function out(payload) {
  process.stdout.write(JSON.stringify(payload));
}

try {
  const mod = await import(pluginUrl);

  if (op === "describe") {
    // 仅元数据: 不实例化 (避免副作用), 只读导出契约
    const hasConfig = typeof mod.Config === "function";
    const fields = {};
    if (hasConfig) {
      try {
        const fieldMap = mod.Config.dict
          || (mod.Config.shape && mod.Config.shape())
          || (mod.Config.inner && mod.Config.inner.keys)
          || {};
        const entries = fieldMap && typeof fieldMap.entries === "function"
          ? [...fieldMap.entries()]
          : Object.entries(fieldMap || {});
        for (const [k, v] of entries) {
          let type = "unknown";
          if (v) {
            if (v.type) type = typeof v.type === "string" ? v.type : (v.type.name || "object");
            else if (v._type) type = v._type;
            else if (v.dict) type = "object";
            else if (v.constructor) type = v.constructor.name;
          }
          fields[k] = type;
        }
      } catch { /* 字段读取失败, 返回空 */ }
    }
    // DSH 0.2 inject 依赖解析: 已知宿主服务 (skills/logger/fs) 可解析, 其余标记 unknown
    const knownServices = [
      "skills", "logger", "fs", "config", "command", "http", "timer",
      // cordis 核心服务 (context.d.ts): events/logger/reflect/registry 由 ctx 自带
      "events", "reflect", "registry", "invariants",
    ];
    const injectArr = Array.isArray(mod.inject) ? mod.inject : (mod.inject ? [mod.inject] : []);
    const injectResolved = injectArr.map((s) => ({
      service: s,
      resolved: knownServices.includes(s),
    }));
    out({ ok: true, data: {
      name: mod.name,
      inject: mod.inject,
      injectResolved,
      hasConfig,
      hasApply: typeof mod.apply === "function",
      configFields: fields,
      entry: mod.__entry || "",
    } });
    process.exit(0);
  }

  if (op === "schema") {
    // 读 Config schema 字段形状与默认值 (schemastery z.object)
    if (typeof mod.Config !== "function") {
      out({ ok: true, data: { fields: {}, hasConfig: false } });
      process.exit(0);
    }
    const fields = {};
    try {
      // schemastery: 字段在 .dict; zod 兼容: .shape 或 .inner.keys
      const fieldMap = mod.Config.dict
        || (mod.Config.shape && mod.Config.shape())
        || (mod.Config.inner && mod.Config.inner.keys)
        || {};
      const entries = fieldMap && typeof fieldMap.entries === "function"
        ? [...fieldMap.entries()]
        : Object.entries(fieldMap || {});
      for (const [k, v] of entries) {
        let type = "unknown";
        if (v) {
          if (v.type) type = typeof v.type === "string" ? v.type : (v.type.name || "object");
          else if (v._type) type = v._type;
          else if (v.dict) type = "object";
          else if (v.constructor) type = v.constructor.name;
        }
        let dflt;
        try { dflt = v && v.default; } catch { dflt = undefined; }
        if (dflt === undefined && v && typeof v === "function") {
          try { const dv = v(undefined); dflt = dv; } catch { dflt = undefined; }
        }
        fields[k] = { type, default: dflt };
      }
    } catch (e) { /* 字段读取失败, 返回空 */ }
    out({ ok: true, data: { fields, hasConfig: true } });
    process.exit(0);
  }

  if (op === "validate") {
    // 仅校验配置, 不实例化
    if (typeof mod.Config !== "function") {
      out({ ok: true, data: { valid: true, config } });
      process.exit(0);
    }
    try {
      const parsed = mod.Config.parse ? mod.Config.parse(config) : mod.Config(config);
      out({ ok: true, data: { valid: true, config: parsed ?? config } });
      process.exit(0);
    } catch (e) {
      out({ ok: false, error: `Config 校验失败: ${String(e && e.message || e)}` });
      process.exit(1);
    }
  }

  // 校验配置 (若插件提供 Config 且有 parse)
  let cfg = config;
  if (typeof mod.Config === "function") {
    try {
      const parsed = mod.Config.parse ? mod.Config.parse(config) : mod.Config(config);
      cfg = parsed ?? config;
    } catch (e) {
      out({ ok: false, error: `Config 校验失败: ${String(e && e.message || e)}` });
      process.exit(1);
    }
  }

  // 最小 Cordis ctx 桩: 捕获 registerProvider 构建器与事件订阅
  //
  // 契约来源 (node_modules/@deepseek-ai/cordis/lib/types/*.d.ts, cordis ~4.0.5):
  //   - LoggerService 是「可调用」服务: ctx.logger(name?) 返回具名 Logger 门面,
  //     门面与 service 自身都暴露 error/info/warn/debug (ctx.logger?.info 亦合法)。
  //   - EventsService.on(name, listener) 返回 disposer (() => boolean | undefined),
  //     而非 undefined; once() 同理。桩据此返回真实解绑函数。
  //   - effect 生成器每个 yield 值必须是「处置函数」或 null (见 fiber.ts 契约),
  //     桩据此收集处置函数, apply 阶段可校验其可调用且不抛。
  const builders = [];
  const listeners = [];
  const registeredCommands = [];
  const effectDisposers = [];
  const effectErrors = [];
  const emitErrors = [];
  const logRecords = [];

  const LOG_LEVELS = ["error", "info", "warn", "debug"];
  function makeLogger(name) {
    const facade = { name };
    for (const level of LOG_LEVELS) {
      facade[level] = (...args) => { logRecords.push({ name, type: level, args }); };
    }
    return facade;
  }
  // ctx.logger: 可调用 (name?) => Logger, 同时保留 severity 直调形式
  const loggerService = (name) => makeLogger(typeof name === "string" ? name : "root");
  for (const level of LOG_LEVELS) {
    loggerService[level] = (...args) => { logRecords.push({ name: "root", type: level, args }); };
  }

  const ctx = {
    skills: {
      registerProvider(builder) {
        builders.push(builder);
        return { invalidate() {} };
      },
    },
    // 真实契约: 返回 disposer (解绑后返回 true, 未注册返回 undefined)
    on(event, cb) {
      const rec = { event, cb };
      listeners.push(rec);
      return () => {
        const i = listeners.indexOf(rec);
        if (i < 0) return undefined;
        listeners.splice(i, 1);
        return true;
      };
    },
    // 触发一次事件总线派发, 返回命中并成功回调的监听器数量 (供 observeHostMutation 路径验证)
    emit(name, ...args) {
      let fired = 0;
      for (const rec of listeners.slice()) {
        if (rec.event !== name) continue;
        try { rec.cb(...args); fired += 1; } catch (e) { emitErrors.push(String(e && e.message || e)); }
      }
      return fired;
    },
    once(event, cb) {
      let done = false;
      return ctx.on(event, (...args) => {
        if (done) return;
        done = true;
        cb(...args);
      });
    },
    effect(gen, _label) {
      if (typeof gen === "function") {
        try {
          const it = gen();
          const r = it.next();
          // 仅收函数型处置函数; null 合法; 其余形状按 Cordis 契约为非法 effect
          if (typeof r.value === "function") effectDisposers.push(r.value);
        } catch (e) { effectErrors.push(String(e && e.message || e)); }
      }
    },
    logger: loggerService,
    // DSH 0.2 已知宿主服务补齐: 使 inject 声明这些服务的插件 apply 时能解析,
    // 不因 ctx 缺服务抛 TypeError (完全原生支持 DSH 0.2 几乎所有插件系统)。
    fs: { watch: () => ({ close() {} }), readFile: async () => "", stat: async () => ({}) },
    config: { get: (k, d) => d, set: () => {}, has: () => false, merge: () => {} },
    // DSH command 服务是可调用函数: ctx.command("name") 返回链式命令对象 (action/usage/option)
    // 桩记录注册的命令名, 使 inject command 的插件 apply 不抛 TypeError。
    command: ((name) => {
      const cmd = { name, action() { return cmd; }, usage() { return cmd; }, option() { return cmd; }, alias() { return cmd; }, example() { return cmd; } };
      registeredCommands.push(name);
      return cmd;
    }),
    http: { get: async () => ({}), post: async () => ({}), request: async () => ({}) },
    timer: { setInterval: () => 0, setTimeout: () => 0, clearInterval: () => {}, clearTimeout: () => {} },
  };

  mod.apply(ctx, cfg);

  // 等待异步 setup 完成 (effect / watch 注册), 再读取 provider
  await new Promise((r) => setTimeout(r, 200));

  if (op === "list") {
    const results = [];
    for (const builder of builders) {
      let provider;
      try { provider = builder({ invalidate() {} }); } catch (e) { continue; }
      if (!provider || typeof provider.list !== "function") continue;
      const candidates = await provider.list();
      for (const c of candidates) {
        results.push({
          name: c.name,
          description: c.description || "",
          provider: c.provider || mod.name,
          rank: c.rank,
          source: c.source || "",
          whenToUse: c.whenToUse || "",
          path: c.path || (c.locator && c.locator.path) || "",
          resourceBase: c.resourceBase || null,
        });
      }
    }
    out({ ok: true, data: results });
    process.exit(0);
  }

  if (op === "get") {
    const all = [];
    for (const builder of builders) {
      let provider;
      try { provider = builder({ invalidate() {} }); } catch (e) { continue; }
      if (!provider || typeof provider.list !== "function" || typeof provider.get !== "function") continue;
      const candidates = await provider.list();
      for (const c of candidates) {
        const def = await provider.get(c);
        if (def) {
          all.push({
            name: def.name,
            description: def.description || "",
            provider: def.provider || mod.name,
            content: def.content || "",
            whenToUse: def.whenToUse || "",
            path: def.path || (c.locator && c.locator.path) || "",
            resourceBase: def.resourceBase || null,
          });
        }
      }
    }
    out({ ok: true, data: all });
    process.exit(0);
  }

  if (op === "apply") {
    // 完整运行时: apply 已执行 (line ~963), 汇总 provider 注册 + 事件订阅 + 技能
    const providerCount = builders.length;
    const eventCount = listeners.length;
    const skills = [];
    let invalidations = 0;
    for (const builder of builders) {
      let provider;
      try { provider = builder({ invalidate() { invalidations += 1; } }); } catch (e) { continue; }
      if (!provider || typeof provider.list !== "function") continue;
      const candidates = await provider.list();
      for (const c of candidates) {
        skills.push({
          name: c.name,
          description: c.description || "",
          provider: c.provider || mod.name,
          rank: c.rank,
          source: c.source || "",
          whenToUse: c.whenToUse || "",
        });
      }
    }
    // 校验 effect 契约 (Cordis fiber): 每个 yield 的处置函数必须在 fiber 销毁时被安全调用
    let effectErrorsOut = effectErrors;
    for (const dispose of effectDisposers) {
      try { await dispose(); } catch (e) { effectErrorsOut = effectErrorsOut.concat(String(e && e.message || e)); }
    }
    out({ ok: true, data: {
      applied: true,
      providerCount,
      eventCount,
      invalidations,
      skills,
      commands: registeredCommands,
      effectCount: effectDisposers.length,
      effectErrors: effectErrorsOut,
      emitErrors,
      logs: logRecords.length,
    } });
    process.exit(0);
  }

  // op === "mutation": 验证 observeHostMutation 接线 —— 派发 fs/observed 事件
  // (tuan-skills-bundle 以 actor.name === "edit" | "write" 过滤后转调 provider.observeHostMutation)
  if (op === "mutation") {
    const actor = process.env.DSH_MUTATION_ACTOR || "edit";
    const target = {
      displayPath: process.env.DSH_MUTATION_PATH || "SKILL.md",
      absolutePath: process.env.DSH_MUTATION_PATH || "SKILL.md",
    };
    // 包装 provider.observeHostMutation 以观测真实转调 (监听器闭包引用同一 provider 对象)
    let mutationCount = 0;
    for (const builder of builders) {
      let provider;
      try { provider = builder({ invalidate() {} }); } catch { continue; }
      if (provider && typeof provider.observeHostMutation === "function") {
        const orig = provider.observeHostMutation.bind(provider);
        provider.observeHostMutation = (path) => { mutationCount += 1; return orig(path); };
      }
    }
    const fired = ctx.emit("fs/observed", target, { kind: "write" }, { name: actor });
    out({ ok: true, data: { actor, fired, mutationCount, listeners: listeners.length, emitErrors } });
    process.exit(0);
  }

  out({ ok: false, error: `未知 op: ${op}` });
  process.exit(1);
} catch (e) {
  out({ ok: false, error: String(e && e.stack || e) });
  process.exit(1);
}
"""


class DshPluginLoader:
    """加载 DSH 0.2+ 原生 Cordis 插件, 使其技能/能力可被 Tuan-CLI 调用。

    支持两种入口:
      - 插件目录 (含 lib/index.js 或 index.js)
      - 直接给 ESM 模块文件路径

    经 Node 子进程执行内嵌引导脚本, 构造最小 Cordis ctx 桩调用 apply(),
    把注册 provider 的 list()/get() 结果 JSON 化回传。任何失败都返回空/False,
    不抛出 (设计内降级), 保证 DSH 未装 Node / 插件损坏时不阻塞 Tuan-CLI。
    """

    def __init__(self, node_bin: Optional[str] = None, timeout: int = 30) -> None:
        self.node_bin = node_bin or shutil.which("node") or "node"
        self.timeout = timeout

    # ------------------------------------------------------------- 入口探测

    @staticmethod
    def plugin_entry(plugin_dir: Path) -> Optional[Path]:
        """从插件目录定位原生 ESM 入口 (lib/index.js → index.js)。"""
        plugin_dir = Path(plugin_dir)
        for rel in ("lib/index.js", "index.js"):
            cand = plugin_dir / rel
            if cand.is_file():
                return cand
        return None

    @staticmethod
    def is_dsh_native(plugin_dir: Path) -> bool:
        """判断插件目录是否为 DSH 0.2 原生插件 (存在 ESM 入口)。"""
        return DshPluginLoader.plugin_entry(plugin_dir) is not None

    # ------------------------------------------------------------- 子进程执行

    def _run(self, plugin_url: str, op: str, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """执行引导脚本, 返回解析后的 JSON payload (dict)。"""
        return self._run_env(plugin_url, op, config, {})

    def _run_env(self, plugin_url: str, op: str, config: Optional[Dict[str, Any]],
                 extra_env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """执行引导脚本 (可附加环境变量), 返回解析后的 JSON payload (dict)。"""
        import subprocess

        env = dict(os.environ)
        env["DSH_PLUGIN_URL"] = plugin_url
        env["DSH_PLUGIN_OP"] = op
        env["DSH_PLUGIN_CONFIG"] = json.dumps(config or {}, ensure_ascii=False)
        for k, v in (extra_env or {}).items():
            env[k] = v
        # DSH 原生插件技能根定位: 未显式指定时注入官方技能根,
        # 使插件安装到任意位置 (如 ~/.tuan/plugins) 也能发现官方技能目录。
        if not env.get("TUAN_SKILLS_DIRS"):
            official = Path(__file__).resolve().parents[1] / "resources" / "skills"
            for cand in (Path(r"G:\Tuan-CLI-Official\skills"), official):
                if cand.is_dir():
                    env["TUAN_SKILLS_DIRS"] = str(cand)
                    break
        # 确保 ESM 子进程能解析插件自身的 node_modules 依赖
        try:
            cmd = [self.node_bin, "--input-type=module", "-e", _DSH_BOOTSTRAP]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"Node 加载超时 ({self.timeout}s)"}
        except OSError as exc:
            return {"ok": False, "error": f"无法启动 node: {exc}"}
        out = (result.stdout or "").strip()
        if not out:
            err = (result.stderr or "").strip()
            return {"ok": False, "error": err or f"node 退出码 {result.returncode}, 无输出"}
        try:
            payload = json.loads(out)
            if isinstance(payload, dict):
                return payload
            return {"ok": False, "error": "Node 输出非对象: " + out[:200]}
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"Node 输出非 JSON: {out[:200]} ({exc})"}

    # ------------------------------------------------------------- 公共 API

    def describe(self, plugin_dir: Path) -> Dict[str, Any]:
        """读取插件导出契约 (name/inject/hasConfig/hasApply), 不实例化。"""
        entry = self.plugin_entry(plugin_dir)
        if entry is None:
            return {}
        url = entry.resolve().as_uri()
        payload = self._run(url, "describe", {})
        if payload.get("ok"):
            data = payload.get("data") or {}
            if not data.get("entry"):
                data["entry"] = str(entry)
            return data
        log.debug("DshPluginLoader.describe(): %s", payload.get("error"))
        return {}

    def list_skills(self, plugin_dir: Path, config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """加载插件并列出其注册 provider 的技能候选摘要。"""
        entry = self.plugin_entry(plugin_dir)
        if entry is None:
            return []
        url = entry.resolve().as_uri()
        payload = self._run(url, "list", config or {})
        if payload.get("ok"):
            data = payload.get("data")
            return data if isinstance(data, list) else []
        log.debug("DshPluginLoader.list_skills(): %s", payload.get("error"))
        return []

    def get_skills(self, plugin_dir: Path, config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """加载插件并返回全部技能完整定义 (含 content)。"""
        entry = self.plugin_entry(plugin_dir)
        if entry is None:
            return []
        url = entry.resolve().as_uri()
        payload = self._run(url, "get", config or {})
        if payload.get("ok"):
            data = payload.get("data")
            return data if isinstance(data, list) else []
        log.debug("DshPluginLoader.get_skills(): %s", payload.get("error"))
        return []

    def emit_mutation(self, plugin_dir: Path, actor: str = "edit",
                      path: str = "SKILL.md") -> Dict[str, Any]:
        """验证 observeHostMutation 接线: 派发 fs/observed 事件, 观察 host 是否响应。

        走 tuan-skills-bundle 真实事件过滤 (actor.name in {"edit","write"}),
        返回 {mutationCount, fired, listeners, emitErrors}。mutationCount>=1 证明
        host mutation 观测链路可用; actor 非 edit/write 时 mutationCount==0。
        """
        entry = self.plugin_entry(plugin_dir)
        if entry is None:
            return {"fired": 0, "mutationCount": 0, "listeners": 0, "emitErrors": []}
        url = entry.resolve().as_uri()
        env_extra = {"DSH_MUTATION_ACTOR": actor, "DSH_MUTATION_PATH": path}
        payload = self._run_env(url, "mutation", {}, env_extra)
        if payload.get("ok"):
            data = payload.get("data") or {}
            data.setdefault("mutationCount", 0)
            return data
        return {"fired": 0, "mutationCount": 0, "listeners": 0, "emitErrors": [payload.get("error", "mutation 失败")]}

    def load_provider_info(self, plugin_dir: Path, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """综合描述: 元数据 + 技能候选摘要, 供 info 命令展示。"""
        meta = self.describe(plugin_dir)
        skills = self.list_skills(plugin_dir, config)
        return {"meta": meta, "skills": skills}

    def apply_plugin(self, plugin_dir: Path, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """完整运行时执行插件 apply(), 汇总注册结果。

        返回 {applied, providerCount, eventCount, skills, injectResolved}。
        执行失败返回 {applied: False, error}。供 harness 集成/调试使用。
        """
        entry = self.plugin_entry(plugin_dir)
        if entry is None:
            return {"applied": False, "error": "未找到插件入口"}
        url = entry.resolve().as_uri()
        payload = self._run(url, "apply", config or {})
        if payload.get("ok"):
            data = payload.get("data") or {}
            data.setdefault("applied", False)
            # 注入依赖解析结果 (复用 describe, 无二次子进程开销)
            if "injectResolved" not in data:
                meta = self.describe(plugin_dir)
                data["injectResolved"] = meta.get("injectResolved", [])
            return data
        return {"applied": False, "error": payload.get("error", "apply 失败")}

    # ------------------------------------------------------------- cordis.patch.yml

    @staticmethod
    def patch_file(plugin_dir: Path) -> Optional[Path]:
        """定位插件的 DSH patch 清单 (cordis.patch.yml / cordis.patch.yaml)。"""
        plugin_dir = Path(plugin_dir)
        for rel in ("cordis.patch.yml", "cordis.patch.yaml", "cordis.patch"):
            cand = plugin_dir / rel
            if cand.is_file():
                return cand
        return None

    def read_patch(self, plugin_dir: Path) -> Dict[str, Any]:
        """解析 DSH 0.2 cordis.patch.yml 为结构化 insert/remove 清单。

        DSH patch 语义 (dsh-app-boot): 顶层是操作列表, 每项为
          - insert: [{id, name, config, ...}]   行整体替换, 非深合并
          - remove: [{id | name, ...}]
        叠加顺序: dsh-base → bundle patch → profile → --patch。

        返回 {file, insert: [...], remove: [...], raw: [...]}。
        解析失败返回 {"file":..., "error":...}, 不抛异常。
        """
        pfile = self.patch_file(plugin_dir)
        if pfile is None:
            return {"file": None, "insert": [], "remove": [], "raw": []}
        try:
            import yaml
        except ImportError:
            return {"file": str(pfile), "error": "缺少 PyYAML, 无法解析 patch"}
        try:
            with open(pfile, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or []
            if not isinstance(raw, list):
                raw = [raw]
            inserts: List[Dict[str, Any]] = []
            removes: List[Dict[str, Any]] = []
            for op in raw:
                if not isinstance(op, dict):
                    continue
                if isinstance(op.get("insert"), list):
                    for row in op["insert"]:
                        if isinstance(row, dict):
                            inserts.append(row)
                if isinstance(op.get("remove"), list):
                    for row in op["remove"]:
                        if isinstance(row, dict):
                            removes.append(row)
            return {"file": str(pfile), "insert": inserts, "remove": removes, "raw": raw}
        except Exception as exc:  # noqa: BLE001 - 单个 patch 解析失败不掀翻列表
            log.warning("读取 DSH patch 失败 %s: %s", pfile, exc)
            return {"file": str(pfile), "error": str(exc), "insert": [], "remove": [], "raw": []}

    def apply_patch(
        self,
        patch: Dict[str, Any],
        target: Path,
        *,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """把 DSH cordis.patch.yml 的 insert/remove 应用到目标 YAML 的 services 段。

        DSH harness 引导语义 (dsh-app-boot): patch 是对目标配置文件的 `services`
        列表做行级操作 —— insert 按 id/name 整行替换或追加, remove 按 id/name 删除。
        叠加顺序 dsh-base → bundle patch → profile → --patch, 后应用覆盖先应用。

        返回 {ok, target, inserted: [...], removed: [...]}。
        target 不存在时若 overwrite=False 创建新文件 (仅 insert, 无 remove);
        否则报错。失败返回 {ok: False, error}。
        """
        inserts = patch.get("insert") or []
        removes = patch.get("remove") or []
        try:
            import yaml
        except ImportError:
            return {"ok": False, "error": "缺少 PyYAML, 无法应用 patch"}

        target = Path(target)
        if not target.exists() and removes:
            return {"ok": False, "error": f"目标不存在且 remove 非空: {target}"}

        # 读现有 services (目标不存在 → 空)
        services: List[Dict[str, Any]] = []
        if target.exists():
            try:
                with open(target, encoding="utf-8") as fh:
                    doc = yaml.safe_load(fh) or {}
                if isinstance(doc, dict) and isinstance(doc.get("services"), list):
                    services = doc["services"]
            except Exception as exc:  # noqa: BLE001 - 读取失败返回结构化错误
                log.warning("读取 patch 目标失败 %s: %s", target, exc)
                return {"ok": False, "error": f"读取目标失败: {exc}"}

        # remove: 按 id 或 name 匹配整行删除
        removed: List[str] = []
        for row in removes:
            key = row.get("id") or row.get("name")
            if not key:
                continue
            before = len(services)
            services = [s for s in services if (s.get("id") or s.get("name")) != key]
            if len(services) < before:
                removed.append(str(key))

        # insert: 按 id/name 整行替换 (存在) 或追加 (不存在)
        inserted: List[str] = []
        for row in inserts:
            key = row.get("id") or row.get("name")
            if not key:
                continue
            idx = next(
                (i for i, s in enumerate(services) if (s.get("id") or s.get("name")) == key),
                None,
            )
            if idx is not None:
                services[idx] = dict(row)
            else:
                services.append(dict(row))
            if key not in inserted:
                inserted.append(str(key))

        # 写回
        doc = {"services": services}
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                yaml.safe_dump(doc, fh, allow_unicode=True, sort_keys=False)
        except Exception as exc:  # noqa: BLE001 - 写入失败返回结构化错误
            log.warning("写入 patch 目标失败 %s: %s", target, exc)
            return {"ok": False, "error": f"写入目标失败: {exc}"}
        return {"ok": True, "target": str(target), "inserted": inserted, "removed": removed}

    def plugin_info(self, plugin_dir: Path, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """聚合插件完整画像: 原生契约 + patch 清单 + provider 技能。"""
        plugin_dir = Path(plugin_dir)
        info: Dict[str, Any] = {
            "is_native": self.is_dsh_native(plugin_dir),
            "entry": str(self.plugin_entry(plugin_dir)) if self.is_dsh_native(plugin_dir) else None,
            "meta": self.describe(plugin_dir),
            "patch": self.read_patch(plugin_dir),
        }
        if info["is_native"]:
            info["skills"] = self.list_skills(plugin_dir, config)
        else:
            info["skills"] = []
        return info

    # ------------------------------------------------------------- Config schema

    def schema_info(self, plugin_dir: Path) -> Dict[str, Any]:
        """读取插件 Config schema 的字段形状与默认值 (schemastery z.object)。

        返回 {hasConfig, fields: {key: {type, default}}}。加载失败返回空。
        """
        entry = self.plugin_entry(plugin_dir)
        if entry is None:
            return {"hasConfig": False, "fields": {}}
        url = entry.resolve().as_uri()
        payload = self._run(url, "schema", {})
        if payload.get("ok"):
            return payload.get("data") or {"hasConfig": False, "fields": {}}
        log.debug("DshPluginLoader.schema_info(): %s", payload.get("error"))
        return {"hasConfig": False, "fields": {}}

    def validate_config(self, plugin_dir: Path, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """经插件 Config.parse 校验配置。

        返回 {valid: bool, config?: 规范化后的配置, error?: 错误消息}。
        插件无 Config 时直接通过 (valid=True)。
        """
        entry = self.plugin_entry(plugin_dir)
        if entry is None:
            return {"valid": True, "config": config or {}}
        url = entry.resolve().as_uri()
        payload = self._run(url, "validate", config or {})
        if payload.get("ok"):
            data = payload.get("data") or {}
            return {"valid": True, "config": data.get("config") or (config or {})}
        # Node 依赖解析失败 (ERR_MODULE_NOT_FOUND) 属安装环境缺依赖,
        # 真实 DSH harness 环境会做最终校验, 此处不误拒, 配置原样持久化。
        err = payload.get("error", "")
        if "ERR_MODULE_NOT_FOUND" in err:
            return {"valid": True, "config": config or {}, "skipped": True, "reason": err}
        return {"valid": False, "error": err}
