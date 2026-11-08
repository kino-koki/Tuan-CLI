"""配置加载与组合视图。

Config 类负责把 内置默认 -> 用户配置 -> Profile -> 命令行 patch 四层叠加成统一视图;
并附带 home_dir / load_dotenv / deep_merge / patch_replace / dump_yaml 等辅助函数。
"""

from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

# YAML 后端门面: 有 PyYAML 就用 PyYAML (完整规范), 否则用内置 stdlib 实现。
# 两者对本仓库全部 YAML 文件解析结果一致, 因此 PyYAML 可真正作为可选依赖。
from .. import _yaml  # noqa: E402
from ..core.errors import ConfigError

from .defaults import (
    APP_DIR_NAME,
    DEFAULT_CONFIG,
    LEGACY_APP_DIR_NAMES,
    PRESET_PROFILES,
    load_builtin_soul,
    load_builtin_user_soul,
)


_HOME_MIGRATION_DONE = False


def migrate_legacy_home(new_home: Path) -> bool:
    """把更名前的旧配置目录一次性迁移到新目录 (~/.tuan)。

    触发条件 (保守): 新目录**不存在**, 且某个旧目录**存在**。
    行为: 整目录复制 (copytree) 后打一行 stderr 提示; **旧目录保留不删** ——
    由用户确认无误后自行清理, 避免任何不可逆的数据丢失。

    返回是否真的发生了迁移。
    """
    if new_home.exists():
        return False
    for legacy_name in LEGACY_APP_DIR_NAMES:
        legacy = Path.home() / legacy_name
        if not legacy.is_dir():
            continue
        try:
            shutil.copytree(legacy, new_home)
        except Exception as exc:  # noqa: BLE001 - 迁移失败不应阻断启动
            log.warning("配置目录迁移失败 (%s -> %s): %s", legacy, new_home, exc)
            return False
        sys.stderr.write(
            f"[tuan] 配置目录已迁移: {legacy} -> {new_home}\n"
            f"       (命令由 tuan 更名为 tuan)。旧目录已保留, 确认无误后可手动删除: {legacy}\n"
        )
        return True
    return False


def home_dir() -> Path:
    """用户配置主目录 (默认 ``~/.tuan``)。

    环境变量 ``TUAN_HOME`` (新) 或 ``TUAN_HOME`` (兼容旧名) 可覆盖。
    首次调用时, 若新目录不存在而旧目录 (``~/.tuan`` / ``~/.tuan``) 存在,
    自动迁移一次并提示 —— 不静默切换, 不丢用户配置。
    """
    override = os.environ.get("TUAN_HOME") or os.environ.get("TUAN_HOME")
    if override:
        return Path(override)
    target = Path.home() / APP_DIR_NAME
    global _HOME_MIGRATION_DONE
    if not _HOME_MIGRATION_DONE:
        _HOME_MIGRATION_DONE = True
        try:
            migrate_legacy_home(target)
        except Exception:  # noqa: BLE001 - 迁移属尽力而为, 绝不阻断启动
            pass
    return target


def load_dotenv(home: Optional[Path] = None) -> None:
    """把 ~/.tuan/.env 中的键值加载进进程环境变量 (不覆盖已有变量)。

    密钥集中管理, 不进版本库。.env 权限应为 600。
    """
    env_path = (home or home_dir()) / ".env"
    if not env_path.exists():
        return
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def normalize_api_key(raw: str) -> str:
    """把用户粘贴的 API Key 规范成可用形式。

    常见脏输入: 前后空白、误粘的 `Bearer ` 前缀 (平台文档示例常写成
    `Authorization: Bearer xxx`, 用户整行复制)、包裹引号、多行换行。
    统一在此收敛, 避免请求头变成 `Bearer Bearer xxx` 而 401。
    """
    if not raw:
        return ""
    s = raw.strip()
    # 剥包裹引号 ("..."/'...')
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        s = s[1:-1].strip()
    # 剥误粘的 Bearer 前缀 (大小写不敏感)
    low = s.lower()
    if low.startswith("bearer "):
        s = s[7:].strip()
    # 粘贴多行时取第一行 (其余为误粘的示例文本)
    if "\n" in s:
        s = s.splitlines()[0].strip()
    return s


def persist_api_key(env_name: str, key: str, home: Optional[Path] = None) -> Path:
    """把 API Key 幂等写入 ~/.tuan/.env (按 env 名覆盖该行, 不追加重复)。

    与 tuan setup / tuan models / TUI /provider 共用同一持久化入口, 保证任何入口
    配置的密钥都能在下次启动时被 load_dotenv() 读到 (不因环境变量生命周期丢失)。
    返回写入的 .env 路径。
    """
    if env_name and "=" not in env_name:  # 合法 env 名校验 (防注入性内容)
        env_path = (home or home_dir()) / ".env"
        env_path.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if env_path.exists():
            try:
                existing = env_path.read_text(encoding="utf-8").splitlines()
            except OSError:
                existing = []
        key = normalize_api_key(key)  # 统一规范化: 剥 Bearer 前缀/引号/空白
        replacement = f"{env_name}={key}"
        out, replaced = [], False
        for line in existing:
            stripped = line.strip()
            # 覆盖已有同名密钥 (兼容带引号/首尾空格的历史写法), 其余行原样保留
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k = stripped.partition("=")[0].strip().strip('"').strip("'")
                if k == env_name:
                    out.append(replacement)
                    replaced = True
                    continue
            out.append(line)
        if not replaced:
            out.append(replacement)
        try:
            from ..core.atomicio import atomic_write_text
            atomic_write_text(env_path, "\n".join(out) + "\n")
        except OSError as exc:
            # 写入失败（如 .env 被设为只读/被占用/权限受限）时降级：
            # 仅注入当前进程环境变量保证本次会话可用，不因持久化失败阻断配置流程。
            os.environ[env_name] = key
            log.warning("持久化 API Key 到 %s 失败 (%s)，已降级为仅本次会话生效", env_path, exc)
            return env_path
        # 收紧权限仅限 POSIX；Windows 下 chmod 0o600 会把文件误设为只读，
        # 反而导致后续持久化 write_text 触发 PermissionError。故 Windows 跳过。
        if os.name != "nt":
            try:
                os.chmod(env_path, 0o600)
            except OSError:
                pass
        return env_path
    raise ValueError(f"非法环境变量名: {env_name!r}")


def read_api_key(env_name: str, home: Optional[Path] = None) -> Optional[str]:
    """从 ~/.tuan/.env 读取指定 env 的密钥 (未写入则返回 None)。

    供换模型/换供应商时判断该 env 是否已配置过密钥, 避免误报"未配置"而要求重输。
    """
    env_path = (home or home_dir()) / ".env"
    if not env_path.exists():
        return None
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        k, _, v = stripped.partition("=")
        if k.strip().strip('"').strip("'") == env_name:
            val = v.strip().strip('"').strip("'")
            return val if val else None
    return None


def remove_api_key(env_name: str, home: Optional[Path] = None) -> Path:
    """幂等删除 ~/.tuan/.env 中指定 env 的密钥行。返回 .env 路径。"""
    env_path = (home or home_dir()) / ".env"
    if not env_path.exists():
        return env_path
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return env_path
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.partition("=")[0].strip().strip('"').strip("'")
            if k == env_name:
                continue
        out.append(line)
    if len(out) != len(lines):
        from ..core.atomicio import atomic_write_text
        atomic_write_text(env_path, "\n".join(out) + ("\n" if out else ""))
    return env_path


def deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """深合并: overlay 中的 dict 递归合并, 其他类型直接覆盖。"""
    out = copy.deepcopy(base)
    for key, value in overlay.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def patch_replace(base: Dict[str, Any], patch: Dict[str, Any], _prefix: str = "") -> Dict[str, Any]:
    """patch 语义: 以点分隔路径定位, 整值替换 (与 dsh --patch 一致)。

    patch 文件格式示例:
        model.model: deepseek-reasoner
        agent.max_iterations: 50
    """
    out = copy.deepcopy(base)
    for dotted_key, value in patch.items():
        keys = str(dotted_key).split(".")
        node = out
        for k in keys[:-1]:
            node = node.setdefault(k, {})
            if not isinstance(node, dict):
                raise ValueError(f"patch 路径冲突: {dotted_key}")
        node[keys[-1]] = value
    return out


def _chmod_600(path: Path) -> None:
    """把文件权限设为 600 (仅所有者可读写), 用于保存密钥相关文件。"""
    try:
        if os.name == "nt":
            # Windows 上 chmod 效果有限, 用 attrib 隐藏保护
            import subprocess
            subprocess.run(["attrib", "+H", str(path)], capture_output=True, timeout=5)
        else:
            os.chmod(path, 0o600)
    except Exception as exc:
        log.debug("设置配置文件权限失败 (%s): %s", path, exc)


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        data = _yaml.safe_load(text)
        return data or {}
    except Exception as exc:  # noqa: BLE001
        log.debug("YAML 配置加载失败 (%s): %s", path, exc)
        return {}


def _dump_yaml_impl(data: Dict[str, Any], path: Path) -> bool:
    """原子写入的**单一实现**，如实返回是否落盘成功。

    B3 续轮 V 实测缺陷：旧 ``dump_yaml`` 把 mkstemp / fsync / os.replace
    的全部异常吞成一行 warning 并返回 ``None``，调用方无法区分「写成功」
    和「磁盘没写成」。实测把 ``user_config_path`` 指向一个目录时，
    ``Config.set_user`` 仍会派发 ``ConfigChange`` —— 等于告诉外部 hook
    「配置已生效」，而磁盘上根本没有这个文件。这与上一轮在
    ``ManagedSettings.reload`` 里写下的「失败不派发」契约直接矛盾。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                _yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_name, path)
            return True
        finally:
            try:
                Path(temp_name).unlink()
            except FileNotFoundError:
                pass
    except Exception as exc:
        log.warning("配置写入失败 (%s): %s", path, exc)
        return False


def dump_yaml(data: Dict[str, Any], path: Path) -> None:
    """写入 YAML 配置 (临时文件 + 原子替换, 崩溃不留下半截配置)。

    **返回 None，行为与旧版逐值一致**：全仓既有调用方都忽略返回值。
    需要知道成败的调用方改用 ``dump_yaml_checked``（同一份实现）。
    """
    _dump_yaml_impl(data, path)


def dump_yaml_checked(data: Dict[str, Any], path: Path) -> bool:
    """与 ``dump_yaml`` 共用同一份实现，但如实返回是否落盘成功。

    刻意**不回读比对值**：safe_dump / safe_load 对 tuple、OrderedDict、
    非 ASCII 等存在序列化差异，回读会产生假阴性；``os.replace`` 的原子
    成功本身就是写入完成的判据。也因此不引入「判定依赖文件系统时间点」
    的缓存 —— 与前几轮拒绝给活性判定加文件系统缓存是同一个理由。
    """
    return _dump_yaml_impl(data, path)


def to_yaml_str(data: Dict[str, Any]) -> str:
    """把配置序列化为 YAML 字符串 (用于 tuan config dump 打印)。"""
    try:
        return str(_yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    except Exception:
        return json.dumps(data, ensure_ascii=False, indent=2)


class Config:
    """组合后的配置视图。"""

    def __init__(self, profile: str = "default", patch_file: Optional[str] = None,
                 bare: bool = False, hooks: Any = None):
        self.profile = profile
        self.bare = bare
        # B3 续轮: 配置写入要触发 ConfigChange。显式 hooks 优先，
        # 未传时由 HookTrigger 回落到 app.py 注入的 default provider。
        self._hooks = hooks
        # B3 续轮 V: 最近一次用户层写盘成败（None = 尚未写过），供诊断。
        self.last_write_persisted: Optional[bool] = None
        self.home = home_dir()
        self.user_config_path = self.home / "config.yaml"
        self.profile_dir = self.home / "profiles" / profile

        merged = copy.deepcopy(DEFAULT_CONFIG)
        # 预设 profile 作为基线 (用户可在 profiles/<name>/config.yaml 再覆盖)
        if profile in PRESET_PROFILES:
            merged = deep_merge(merged, PRESET_PROFILES[profile])
        # bare (CI/纯净模式): 仅用内置默认配置, 不叠加用户级 config.yaml 与 profile 覆盖,
        # 保证 CI/评测可复现, 不受本机用户配置污染。
        if not bare:
            merged = deep_merge(merged, _load_yaml(self.user_config_path))
            merged = deep_merge(merged, _load_yaml(self.profile_dir / "config.yaml"))
        if patch_file:
            merged = patch_replace(merged, _load_yaml(Path(patch_file)))
        self.data = merged

    # ------------------------------------------------------------ 访问

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for key in dotted.split("."):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
            # 路径中间节点为 None 时无法继续向下查找
            if node is None and key != dotted.split(".")[-1]:
                return default
        return node

    def set_user(self, dotted: str, value: Any) -> None:
        """写入用户层配置文件 (自动把字符串值按目标类型转换)。"""
        value = self._autofill_preset_fields(self._coerce(value))
        cfg = _load_yaml(self.user_config_path)
        keys = dotted.split(".")
        node = cfg
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value
        self.home.mkdir(parents=True, exist_ok=True)
        ok = dump_yaml_checked(cfg, self.user_config_path)
        self.last_write_persisted = bool(ok)
        # 同步内存视图: 用 patch_replace 整值替换目标键 (保留同级默认字段)。
        # 注意: 写盘失败时内存视图仍更新 —— 这是**既有行为**，本轮不扩大
        # 改动面去修「重启后丢失」；只保证不把失败伪装成 ConfigChange。
        self.data = patch_replace(self.data, {dotted: value})
        if ok:
            from ..hooks.triggers import HookTrigger
            HookTrigger(self._hooks).config_change(
                source="user_config", key=dotted, origin="set_user")
        else:
            log.debug("ConfigChange 未派发: 用户层配置未落盘 (%s)", dotted)

    def delete_user(self, dotted: str) -> bool:
        """从用户层配置删除某个点路径键 (复位到内置默认值)。返回是否真的删掉了。

        仅作用于用户层 (~/.tuan/config.yaml), 不影响 Profile/patch 层。
        """
        cfg = _load_yaml(self.user_config_path)
        keys = dotted.split(".")
        node = cfg
        for k in keys[:-1]:
            if not isinstance(node, dict) or k not in node:
                return False
            node = node[k]
        leaf = keys[-1]
        if not isinstance(node, dict) or leaf not in node:
            return False
        del node[leaf]
        self.home.mkdir(parents=True, exist_ok=True)
        ok = dump_yaml_checked(cfg, self.user_config_path)
        self.last_write_persisted = bool(ok)
        # 刷新内存视图: 重建 默认 -> 用户(已删) -> Profile。
        self.data = copy.deepcopy(DEFAULT_CONFIG)
        if self.profile in PRESET_PROFILES:
            self.data = deep_merge(self.data, PRESET_PROFILES[self.profile])
        self.data = deep_merge(self.data, cfg)
        self.data = deep_merge(self.data, _load_yaml(self.profile_dir / "config.yaml"))
        if ok:
            from ..hooks.triggers import HookTrigger
            HookTrigger(self._hooks).config_change(
                source="user_config", key=dotted, origin="delete_user")
        else:
            log.debug("ConfigChange 未派发: 用户层配置删除未落盘 (%s)", dotted)
        return True

    @staticmethod
    def _autofill_preset_fields(value: Any) -> Any:
        """dict 且带已知 provider 时, 从对应预设补全缺失字段。

        典型场景: `tuan config set model.worker '{"provider":"opencode-zen"}'` ——
        只写 provider 就能自动带好 base_url / api_key_env / model 等连接信息,
        与 provider_catalog / swarm worker 的补全语义保持一致。
        """
        if isinstance(value, dict) and isinstance(value.get("provider"), str):
            preset = PRESET_PROFILES.get(value["provider"])
            if preset and isinstance(preset.get("model"), dict):
                return deep_merge(preset["model"], value)
        return value

    @staticmethod
    def _coerce(value: Any) -> Any:
        """尽力把用户/CLI 传入的字符串值转为 int/float/bool/JSON/原值。"""
        if not isinstance(value, str):
            return value
        low = value.strip().lower()
        if low in ("true", "false"):
            return low == "true"
        if low in ("null", "none", "~"):
            return None
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        s = value.strip()
        if s and s[0] in ("{", "["):
            try:
                return json.loads(s)
            except (ValueError, json.JSONDecodeError):
                pass
        return value

    def api_key(self) -> Optional[str]:
        """按优先级解析密钥: 专用 env 名 -> 通用 TUAN_API_KEY -> 用户配置中的引用。"""
        env_name = self.get("model.api_key_env", "DEEPSEEK_API_KEY")
        key = os.environ.get(env_name)
        if key:
            return key
        key = os.environ.get("TUAN_API_KEY")
        if key:
            return key
        ref = self.get("model.api_key_ref")
        if ref:
            return os.environ.get(ref)
        return None

    def require_api_key(self) -> str:
        key = self.api_key()
        if not key:
            env_name = self.get("model.api_key_env", "DEEPSEEK_API_KEY")
            # ConfigError (kind="config"): 让重试策略立即失败, 并支持 C-2 友好模板渲染
            raise ConfigError(
                f"未配置 API Key。请设置环境变量 {env_name} (推荐写入 ~/.tuan/.env), "
                f"或运行 `tuan setup`。"
            )
        return key

    @property
    def mode(self) -> str:
        """当前运行模式 ID（五模式体系）。

        优先读取 mode.current（新字段），回退到 mode.default（历史兼容）。
        旧三档别名 standard/yolo/plan 自动映射为新模式 ID。
        """
        from .defaults import DEFAULT_CONFIG
        from ..modes.registry import resolve_mode_id
        mode_data = self.get("mode", {}) or {}
        raw = mode_data.get("current") or mode_data.get("default") or "chat"
        return resolve_mode_id(str(raw))

    @mode.setter
    def mode(self, value: str) -> None:
        """设置运行模式（写入 mode.current，旧三档别名自动解析）。"""
        from ..modes.registry import resolve_mode_id
        try:
            resolved = resolve_mode_id(value)
        except ValueError:
            raise ValueError(
                f"未知运行模式: {value!r} "
                f"(五模式: gantong/lingma/chat/boundless/collaboration; "
                f"别名: standard→collaboration / yolo→boundless / plan→chat)"
            )
        self.set_user("mode.current", resolved)

    def is_yolo(self) -> bool:
        """是否为 YOLO 模式（历史兼容：mode.default == "yolo" 或 mode.current == "boundless"）。"""
        mode_data = self.get("mode", {}) or {}
        raw_default = mode_data.get("default", "")
        current = mode_data.get("current", "")
        return bool(raw_default == "yolo" or current == "boundless")

    def tool_auto_approve(self, tool_name: str) -> bool:
        if not self.is_yolo():
            return False
        redlist = self.get("mode.yolo_require_confirm", []) or []
        return tool_name not in redlist

    def ensure_home(self) -> None:
        """创建 ~/.tuan 目录骨架 (Hermes 风格)。"""
        for sub in ["memories", "skills", "sessions", "logs", "cron", "profiles", "history"]:
            (self.home / sub).mkdir(parents=True, exist_ok=True)
        env_file = self.home / ".env"
        if not env_file.exists():
            env_file.write_text("# 密钥集中在此, 不要提交到版本库\n", encoding="utf-8")
        _chmod_600(env_file)
        soul = self.home / "SOUL.md"
        if not soul.exists():
            soul.write_text(load_builtin_soul(), encoding="utf-8")
        # 用户助手灵魂 (user_mode=True 时注入): 与 SOUL.md 并存, 不存在时补写,
        # 否则用户 Agent 会回退到开发向 SOUL, 透明/不拒绝条款失效。
        user_soul = self.home / "USER_SOUL.md"
        if not user_soul.exists():
            user_soul.write_text(load_builtin_user_soul(), encoding="utf-8")
        memory = self.home / "memories" / "MEMORY.md"
        if not memory.exists():
            memory.write_text("# MEMORY.md - 长期事实记忆\n\n(Agent 会把跨会话需要记住的事实写在这里)\n", encoding="utf-8")
        user = self.home / "memories" / "USER.md"
        if not user.exists():
            user.write_text("# USER.md - 关于用户\n\n- Name:\n- City:\n- Notes:\n", encoding="utf-8")

    def raw(self) -> dict:
        """返回配置数据的深拷贝, 避免外部修改影响内部状态。"""
        return copy.deepcopy(self.data)
