"""模型配置与热切换 CLI 命令 (拆分自 cmd_chat.py)。

承载 ``tuan models`` 子命令及其辅助函数:
- cmd_model: 列出/查看/设置/热切换模型供应商
- _model_test / _model_local / _model_update: 连通性测试 / 本地模型探测 / 目录更新
- 交互式选型辅助 (_pick_model_interactive / _pick_api_key_interactive 等)

路由: ``tuan_cli/cli/commands.py::_CMD_SOURCES`` 将 cmd_model 等符号指向本模块。
拆分前这些函数与 cmd_chat (交互对话) 混在同一 1300 行文件里, 职责不同却共享命名空间。
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, cast

from ..config import (
    Config,
    normalize_api_key,
    persist_api_key,
    read_api_key,
    remove_api_key,
)
from ..models.provider_catalog import get_provider
from ..i18n import t
from ..ui.plain_console import console


# ---- app 链惰性加载: 构建内核 (~1s) 只在真正需要热切换时付出 ----
# 与 cmd_chat.build_kernel 同款惰性包装 (拆分前 cmd_model 依赖 cmd_chat 的同名函数)。
def build_kernel(*a: Any, **k: Any) -> Any:
    from ..app import build_kernel as _f
    return _f(*a, **k)


# ===================================================================== cmd_model

def _show_provider_models(name: str, by_name: Optional[Dict[str, Any]] = None) -> None:
    """打印某供应商的可选模型清单。
    by_name: 本地目录视图 (呼叫方传入); 缺省内置 get_provider。
    """
    info = by_name.get(name) if by_name is not None else get_provider(name)
    if info is None:
        console.print(f"未知供应商: {name}")
        return
    models = info.recommended_models
    console.print(f"\n{info.name} 可选模型 ({len(models)}):")
    if not models:
        console.print("  (未收录, 可手动输入模型名)")
        return
    for i, m in enumerate(models, 1):
        console.print(f"  {i:3d}. {m}")


def _strip_model_label(m: str) -> str:
    """剥离模型清单项的 |free/|paid 标注。"""
    return m.split("|")[0] if "|" in m else m


def _ellipsize(text: str, max_chars: int = 40) -> str:
    """按字符数安全截断: 截断点回退到最近的词组边界 (空格/标点),
    避免把中文词语 (如"视频") 切成半个字。"""
    if len(text) <= max_chars:
        return text
    head = text[:max_chars]
    cut = -1
    for sep in (" ", ",", ";", "(", ")", "/", ":", "：", "，", "、"):
        pos = head.rfind(sep)
        if pos > cut:
            cut = pos
    if cut > max_chars // 2:
        return head[: cut + 1] + "…"
    return head + "…"


def _offer_keep_original_config(config: Any, chosen: Any) -> None:
    """换供应商时: Y/n 保留原 API 配置(可随时切回) / 删除原配置。不覆写已持久化的旧密钥。

    chosen 需具备 .name / .api_key_env。tuan models 交互式切换与 tuan setup 向导共用。
    """
    old_provider = config.get("model.provider", "")
    old_env = config.get("model.api_key_env", "")
    new_name = getattr(chosen, "name", old_provider)
    new_env = getattr(chosen, "api_key_env", None)
    if old_provider and old_provider != new_name and old_env and old_env != new_env:
        try:
            keep = input(t("model.switch_keep_orig", provider=old_provider)).strip().lower()
        except (EOFError, KeyboardInterrupt):
            keep = ""
        if keep == "n":
            try:
                remove_api_key(old_env)
                os.environ.pop(old_env, None)
                console.print(f"  已删除原配置 {old_env}")
            except Exception:  # noqa: BLE001
                console.print(f"  删除原配置 {old_env} 失败 (保留原文件)")
        else:
            console.print(f"  已保留原配置 {old_env} (可随时切回 {old_provider})")


def _no_key_env(config: Any) -> str:
    """缺失密钥的环境变量名 (状态栏提示用, 让"未配置"可操作)。"""
    env = config.get("model.api_key_env", "DEEPSEEK_API_KEY") or "API Key"
    return env


def _pick_api_key_interactive(preset: Any) -> str:
    """提示用户输入 API Key。已配置过 (环境变量或 .env 文件) 则优先复用, 避免换模型重输。"""
    env_name = preset.api_key_env
    if not env_name:
        return ""
    existing = os.environ.get(env_name, "") or ""
    if not existing:
        # 换模型/换供应商时, .env 里已持久化的密钥也要能复用,
        # 否则当前环境没载入就误判"未配置"而要求重新粘贴。
        existing = read_api_key(env_name) or ""
    if existing:
        console.print(f"  已检测到 {env_name} (长度 {len(existing)})")
        try:
            use = input("  使用此 Key? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            use = ""
        if use != "n":
            return existing
    if getattr(preset, "key_hint", ""):
        console.print(f"  {preset.key_hint}")
    try:
        raw = input(f"  输入 {preset.name} API Key (回车跳过): ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""
    key = normalize_api_key(raw)
    # OpenCode Zen 密钥前缀校验 (仅提示, 不阻断): zen 平台 key 形如 zen_xxxx
    if preset.api_key_env == "OPENCODE_ZEN_API_KEY" and key and not key.startswith("zen_"):
        console.print(f"  ! 提示: {preset.name} 的 API Key 通常以 zen_ 开头, 请确认粘贴正确")
    return key


def _pick_model_interactive(preset: Any) -> tuple:
    """展示供应商模型清单并让用户选择。"""
    models = preset.recommended_models
    if not models:
        try:
            raw = input(f"  输入模型名 (回车用默认 {preset.model}): ").strip()
        except (EOFError, KeyboardInterrupt):
            raw = ""
        return preset.name, (raw or preset.model)
    console.print(f"\n  选择模型 ({preset.name}, 共 {len(models)} 个):")
    for i, m in enumerate(models, 1):
        console.print(f"    {i:3d}. {m}")
    try:
        raw = input("    选择编号 [1] (或输入自定义模型名): ").strip()
    except (EOFError, KeyboardInterrupt):
        raw = ""
    if not raw:
        return preset.name, _strip_model_label(models[0])
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(models):
            return preset.name, _strip_model_label(models[idx])
        console.print(f"  编号超出范围, 已选默认 {models[0]}")
        return preset.name, _strip_model_label(models[0])
    return preset.name, raw


class _ConfigOverride:
    """只读配置视图: 在基础 config 上覆盖若干键 (不写盘)。"""

    def __init__(self, base: Any, overrides: Dict[str, Any]) -> None:
        self._base = base
        self._overrides = overrides

    def get(self, dotted: str, default: Any = None) -> Any:
        if dotted in self._overrides:
            return self._overrides[dotted]
        return self._base.get(dotted, default)

    def api_key(self) -> Optional[str]:
        env_name = self.get("model.api_key_env", "DEEPSEEK_API_KEY")
        key = os.environ.get(env_name)
        if key:
            return key
        return cast(Optional[str], self._base.api_key())


def _model_test(config: Any, args: Any = None) -> int:
    """连通性测试。"""
    overrides: Dict[str, Any] = {}
    for attr, dotted in (("provider", "model.provider"), ("model", "model.model"),
                         ("base_url", "model.base_url"), ("api_key_env", "model.api_key_env")):
        val = getattr(args, attr, None) if args is not None else None
        if val:
            overrides[dotted] = val
    if overrides:
        config = _ConfigOverride(config, overrides)

    provider = config.get("model.provider", "?")
    model = config.get("model.model", "?")
    base_url = config.get("model.base_url", "")
    if not config.api_key():
        console.print("未配置 API Key — 无法测试。请先运行 tuan models 或 tuan setup。")
        return 1
    console.print(f"  端点: {base_url or '(未设置)'}")
    console.print(f"  模型: {provider}/{model}")
    try:
        from ..models import create_adapter
        adapter = create_adapter(config)
        t0 = time.time()
        resp = adapter.chat([{"role": "user", "content": "ping"}], stream=False)
        elapsed = time.time() - t0
    except Exception as exc:  # noqa: BLE001
        console.print(f"  连接失败: {exc}")
        return 1
    usage = getattr(resp, "usage", None) or {}
    console.print(f"  连接成功 ({elapsed:.1f}s)")
    content = (resp.content or "")[:120]
    if content:
        console.print(f"  回复: {content}")
    if usage:
        console.print(f"  token: 入 {usage.get('prompt_tokens', 0)} / 出 {usage.get('completion_tokens', 0)}")
    return 0


def _model_local() -> int:
    """列出本机已安装的本地模型 (Ollama + llama.cpp)。"""
    try:
        from ..models.offline import detect_local_models
        status = detect_local_models()
    except Exception as exc:  # noqa: BLE001
        console.print(f"[错误] 本地模型探测失败: {exc}")
        return 1

    ollama = status.get("ollama", {})
    llama = status.get("llamacpp", {})

    console.print("\n[bold]本机本地模型[/bold]\n")

    if ollama.get("available"):
        models = ollama.get("models") or []
        console.print(f"[green]✓ Ollama 可用[/green] (已安装 {len(models)} 个)")
        for m in models:
            console.print(f"    • {m}")
        if not models:
            console.print("    运行 `ollama pull <model>` 下载, 例如 qwen2.5:7b")
    else:
        console.print("[dim]• Ollama 未检测到[/dim]")
        if ollama.get("error"):
            console.print(f"    {ollama['error']}")

    console.print("")
    if llama.get("available"):
        models = llama.get("models") or []
        console.print(f"[green]✓ llama.cpp 可用[/green] (:8080/v1, 已加载 {len(models)} 个)")
        for m in models:
            console.print(f"    • {m}")
        if not models:
            console.print("    用 llama.cpp 服务器加载模型后此处会列出")
    else:
        console.print("[dim]• llama.cpp 未检测到 (:8080/v1)[/dim]")
        if llama.get("error"):
            console.print(f"    {llama['error']}")

    console.print("\n[bold]快速接入[/bold]")
    console.print("    tuan models set ollama <模型名>      # 例如 tuan models set ollama qwen2.5:7b")
    console.print("    tuan models set llamacpp <模型名>    # 例如 tuan models set llamacpp local-model")
    console.print("    tuan models test --provider ollama    # 验证连通性")
    return 0


def _model_update(args: Any, config: Any) -> int:
    """tuan models update: 本地更新模型/供应商目录。
    全程离线: 把内置最新清单合并写入本地 JSON,
    保留用户自建条目; --check 只报告不写盘; --background 后台执行。
    """
    from ..models import local_catalog
    home = getattr(config, "home", None)
    if getattr(args, "check", False):
        d = local_catalog.diff_catalog(home)
        if not d["local_exists"]:
            console.print(f"本地目录不存在 — 内置 {d['missing_providers']} 供应商 / {d['missing_models']} 模型待写入 (tuan models update)")
        else:
            console.print(f"本地目录: {d['total_providers']} 供应商 / {d['total_models']} 模型")
            if d["missing_providers"] or d["missing_models"]:
                console.print(f"  内置新增未合并: {d['missing_providers']} 供应商 / {d['missing_models']} 模型 (tuan models update 合并)")
            else:
                console.print("  已是最新。")
        return 0
    if getattr(args, "background", False):
        local_catalog.refresh_in_background(home, on_done=_print_update_done)
        console.print("后台更新已启动 (模型/供应商目录, 本地离线写入)。")
        return 0
    n_p, n_m = local_catalog.refresh_catalog(home)
    console.print(f"模型/供应商目录已更新: {n_p} 供应商 / {n_m} 模型 -> {local_catalog.catalog_file(home)}")
    return 0


def _print_update_done(n_p: int, n_m: int, error: Optional[str] = None) -> None:
    """后台更新完成回调。"""
    if error:
        console.print(f"[后台更新失败] {error}")
    else:
        console.print(f"[后台更新完成] 模型/供应商目录: {n_p} 供应商 / {n_m} 模型")


def cmd_model(args: Any) -> int:
    """配置/热切换模型供应商。"""
    model_cmd = getattr(args, "model_cmd", None)
    config = Config(profile=getattr(args, "profile", "default"),
                    patch_file=getattr(args, "patch", None))

    # 本地目录视图: 存在时优先用本地 (用户可本地更新供应商/模型),
    # 仅影响展示类命令 (list/info/list-providers/交互); set/switch 仍用内置预设。
    from ..models import provider_catalog as _pc
    from ..models.local_catalog import load_catalog
    _local = load_catalog(config.home)
    if _local is not None:
        _view = _pc.presets_from_catalog(_local)
        if not _view:  # 本地文件存在但无合法条目 -> 回退内置
            _view = _pc.ALL_PROVIDERS
        _by_name = {_p.name: _p for _p in _view}
        _categories: Dict[str, List[Any]] = {}
        for _p in _view:
            _categories.setdefault(_p.category or "其他", []).append(_p)
    else:
        _by_name = _pc.PROVIDER_BY_NAME
        _categories = _pc.PROVIDER_CATEGORIES

    if model_cmd == "current":
        provider = config.get("model.provider", "?")
        model = config.get("model.model", "?")
        base_url = config.get("model.base_url", "")
        env_name = config.get("model.api_key_env", "")
        key = config.api_key()
        console.print(f"  provider:    {provider}")
        console.print(f"  model:       {model}")
        console.print(f"  base_url:    {base_url or '(未设置)'}")
        console.print(f"  api_key_env: {env_name or '(未设置)'}")
        if key:
            console.print(f"  API Key: 已配置 (长度 {len(key)})")
        else:
            console.print(f"  API Key: 未配置 — 调用模型会失败")
            console.print(f"  设置: tuan models (交互式) 或 tuan /provider set {env_name or 'DEEPSEEK_API_KEY'} <KEY>")
        console.print(f"  temperature: {config.get('model.temperature', 0.7)}")
        console.print(f"  max_tokens:  {config.get('model.max_tokens', 8192)}")
        console.print("  切换: tuan models 或 tuan models set <provider> <model>")
    elif model_cmd == "local":
        return _model_local()
    elif model_cmd == "test":
        return _model_test(config, args)
    elif model_cmd == "set":
        provider = getattr(args, "provider", None)
        model_name = getattr(args, "model", None)
        base_url = getattr(args, "base_url", None)
        api_key_env = getattr(args, "api_key_env", None)
        if provider:
            config.set_user("model.provider", provider)
        if model_name:
            config.set_user("model.model", model_name)
        preset = get_provider(provider) if provider else None
        if base_url:
            config.set_user("model.base_url", base_url)
        elif preset and preset.base_url:
            config.set_user("model.base_url", preset.base_url)
        if api_key_env:
            config.set_user("model.api_key_env", api_key_env)
        elif preset and preset.api_key_env:
            config.set_user("model.api_key_env", preset.api_key_env)
        console.print(f"模型已切换为: {provider or '?'}/{model_name or '?'}")
        # 未配置密钥时给出可操作指引 (避免"以为配好了, 请求却失败")
        if preset and preset.api_key_env:
            if not config.api_key():
                console.print(f"  ! 尚未配置 {preset.api_key_env} — 调用模型会失败。")
                console.print(f"    设置方式: tuan models (交互式) 或 tuan /provider set {preset.api_key_env} <KEY>")
    elif model_cmd == "switch":
        from ..models.plugin import ModelPlugin
        overrides = {}
        for key in ("provider", "model", "base_url", "api_key_env"):
            val = getattr(args, key, None)
            if val:
                overrides[key] = val
        kernel = build_kernel()
        ModelPlugin.switch_model(kernel, overrides)
        config.set_user("router.auto_switch", False)
        console.print("模型已热切换 (当前会话生效, 自动路由已暂停)。")
    elif model_cmd == "list":
        _show_provider_models(getattr(args, "provider_name", ""), _by_name)
    elif model_cmd == "info":
        name = getattr(args, "provider_name", "")
        info = _by_name.get(name)
        if info:
            console.print(f"  {info.name}: {info.desc}")
            console.print(f"  默认模型: {info.model}")
            console.print(f"  base_url: {info.base_url}")
            models = info.recommended_models
            if models:
                console.print(f"  可选模型 ({len(models)}):")
                for i, m in enumerate(models, 1):
                    console.print(f"    {i:3d}. {m}")
            else:
                console.print("  可选模型: (未收录, 可手动输入)")
        else:
            console.print(f"未知供应商: {name}")
    elif model_cmd == "update":
        return _model_update(args, config)
    elif model_cmd == "list-providers":
        for cat_name, providers in _categories.items():
            console.print(f"\n{cat_name}")
            for p in providers:
                console.print(f"  {p.name:<20s} {_ellipsize(p.desc, 60)}")
    else:
        # 无子命令: 交互式选择
        console.print("选择模型供应商")
        categories = list(_categories.keys())
        for i, cat in enumerate(categories, 1):
            console.print(f"  {i}. {cat}")
        custom_idx = len(categories) + 1
        console.print(f"  {custom_idx}. 自定义 (手动配置 OpenAI 兼容端点)")
        try:
            cat_idx = int(input("  分类编号 (回车跳过): ").strip() or "0") - 1
        except (ValueError, EOFError, KeyboardInterrupt):
            cat_idx = -1
        if cat_idx == len(categories):
            # 自定义 OpenAI 兼容端点: 手动填写 provider/base_url/模型/api_key_env。
            try:
                custom_provider = input(
                    "  供应商名称 (回车用 custom, 仅作展示用): ").strip() or "custom"
                custom_base = input(
                    "  base_url (OpenAI 兼容, 如 https://api.example.com/v1): ").strip()
                custom_model = input("  模型名 (如 gpt-4o-mini): ").strip()
                custom_env = input(
                    "  API Key 环境变量名 (回车用 CUSTOM_API_KEY): ").strip() or "CUSTOM_API_KEY"
            except (EOFError, KeyboardInterrupt):
                console.print("  已取消")
                return 0
            if not custom_base or not custom_model:
                console.print("  ! base_url 与模型名不能为空, 已取消")
                return 0
            config.set_user("model.provider", custom_provider)
            config.set_user("model.model", custom_model)
            config.set_user("model.base_url", custom_base)
            config.set_user("model.api_key_env", custom_env)
            try:
                api_key = input(f"  输入 {custom_env} API Key (回车跳过): ").strip()
            except (EOFError, KeyboardInterrupt):
                api_key = ""
            if api_key:
                os.environ[custom_env] = api_key
                try:
                    persist_api_key(custom_env, api_key)
                except ValueError:
                    pass
                console.print(f"  已设置 {custom_env} (本次会话生效)")
            console.print(f"已选择: {custom_provider}/{custom_model} (自定义端点)")
            return 0
        if 0 <= cat_idx < len(categories):
            cat = categories[cat_idx]
            providers = _categories[cat]
            for i, p in enumerate(providers, 1):
                console.print(f"    {i}. {p.name:<20s} {_ellipsize(p.desc, 55)}")
            try:
                p_idx = int(input("    选择编号 [1]: ").strip() or "1") - 1
            except (ValueError, EOFError, KeyboardInterrupt):
                p_idx = 0
            chosen = providers[min(p_idx, len(providers) - 1)]
            chosen_provider, model_name = _pick_model_interactive(chosen)
            if chosen_provider != chosen.name:
                chosen = get_provider(chosen_provider) or chosen
            # 换供应商时: Y/n 保留原 API 配置(可随时切回) / 删除原配置。不覆写已持久化的旧密钥。
            _offer_keep_original_config(config, chosen)
            api_key = _pick_api_key_interactive(chosen)
            config.set_user("model.provider", chosen.name)
            config.set_user("model.model", model_name)
            if chosen.base_url:
                config.set_user("model.base_url", chosen.base_url)
            if chosen.api_key_env:
                config.set_user("model.api_key_env", chosen.api_key_env)
            if api_key:
                os.environ[chosen.api_key_env] = api_key
                if chosen.api_key_env:
                    # 持久化到 ~/.tuan/.env, 避免密钥仅存活于当前进程,
                    # 下次启动 (load_dotenv) 读不到而误报"未配置 API"。
                    try:
                        persist_api_key(chosen.api_key_env, api_key)
                    except ValueError:
                        pass
                console.print(f"  已设置 {chosen.api_key_env} (本次会话生效)")
            console.print(f"已选择: {chosen.name}/{model_name}")
    return 0
