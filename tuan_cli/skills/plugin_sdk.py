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

    def _scan(self) -> None:
        """扫描已安装插件 (兼容旧 tuan 格式与 DSH 0.2 格式)。"""
        self._cache.clear()
        if not self.plugins_dir.is_dir():
            return
        for entry in sorted(self.plugins_dir.iterdir()):
            if not entry.is_dir():
                continue
            resolved = self.resolve_dsh_plugin_format(entry)
            if resolved is None:
                continue
            data, fmt = resolved
            try:
                manifest = PluginManifest.from_dict(data, fmt=fmt)
                if not manifest.name:
                    continue
                enabled_path = entry / ".enabled"
                enabled = (
                    not enabled_path.exists()
                    or enabled_path.read_text(encoding="utf-8").strip() != "false"
                )
                manifest_mtime = (
                    entry / "plugin.toml"
                ).stat().st_mtime if (entry / "plugin.toml").is_file() else (
                    entry / "plugin.json"
                ).stat().st_mtime
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

    def install_from_directory(self, source: Path, name: Optional[str] = None) -> PluginInfo:
        """从本地目录安装插件 (兼容旧 tuan plugin.json 与 DSH 0.2 plugin.toml)。"""
        source = Path(source).resolve()
        resolved = self.resolve_dsh_plugin_format(source)
        if resolved is None:
            raise ValueError(f"目录 {source} 中没有 plugin.toml / plugin.json")
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

        # 写入启用标记
        (target / ".enabled").write_text("true", encoding="utf-8")

        # 执行 install hook
        self._run_hook(target, manifest, "install")

        # 刷新缓存
        self._scan()
        info = self._cache.get(plugin_name)
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

    def inject_skills_to_skill_manager(self, skill_manager: Any) -> int:
        """把所有已启用插件的技能目录注入到 SkillManager._search_dirs。

        对每个已启用插件, 把 `<plugin>/skills` (若存在) 加入 _search_dirs,
        origin 标记为 "plugin"; SkillManager._discover 会按
        `<search_dir>/<slug>/SKILL.md` 自然发现每个 DSH 0.2 技能包。

        插件根目录直接放 SKILL.md 的形态 (无 skills/ 子目录) 不通过
        _search_dirs 注入 (会误发现同目录其他插件); 这种情况请使用
        `PluginManager.get_all_skills()` / `resolve_skill()` 读取。

        返回注入的目录数量。
        """
        if skill_manager is None:
            return 0
        search_dirs = getattr(skill_manager, "_search_dirs", None)
        if search_dirs is None:
            log.debug(
                "inject_skills_to_skill_manager(): 目标 SkillManager 无 "
                "_search_dirs, 跳过",
            )
            return 0

        existing = {(str(p.resolve()), o) for p, o in search_dirs}
        injected = 0
        for info in self._cache.values():
            if not info.enabled:
                continue
            skills_dir = info.path / "skills"
            if not skills_dir.is_dir():
                continue
            key = (str(skills_dir.resolve()), "plugin")
            if key not in existing:
                search_dirs.append((skills_dir, "plugin"))
                existing.add(key)
                injected += 1
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
