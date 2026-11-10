"""初始化向导 + 基准测试 CLI 命令。

拆分自 commands.py:
- cmd_setup: 交互式初始化向导
- cmd_bench: 基准测试 (cache/latency)
- cmd_open: 精确引用跳转
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from ..config import Config, home_dir, persist_api_key
from ..models import PROVIDER_PRESETS
from ..models.provider_catalog import (
    ALL_PROVIDERS, free_providers, get_provider,
)
from ..logging_conf import log
from ..i18n import ensure_language, t
from ._ui_singleton import console


# ---- app 链惰性加载: 仅真正执行 setup/bench 时才构建内核 ----
def build_kernel(*a: Any, **k: Any) -> Any:
    from ..app import build_kernel as _f
    return _f(*a, **k)


def create_agent(*a: Any, **k: Any) -> Any:
    from ..app import create_agent as _f
    return _f(*a, **k)


def seed_builtin_skills(*a: Any, **k: Any) -> Any:
    from ..app import seed_builtin_skills as _f
    return _f(*a, **k)





# ===================================================================== cmd_setup

def _ask_sandbox_setup(config: Any) -> None:
    """安全加固选项: 是否启用分层沙箱隔离 (高风险命令自动路由到隔离执行域)。

    三档:
      [1] 启用 (推荐) —— 高/中风险命令自动进 L1(bwrap)/L2(gVisor), 用户无感
      [2] 仅审批模式 —— 依赖命令审批 + 回滚 (旧行为)
      [3] 自定义 —— 资源配额 / 网络策略
    沙箱运行时缺失时自动降级为仅审批并明确告知 (绝不静默假装隔离了)。
    """
    from ..ext.sandbox import sandbox_status

    console.print("\n  🛡️ 安全加固选项 (分层沙箱隔离)")
    status = sandbox_status()
    avail = ", ".join(b["name"] for b in status["backends"] if b["available"]) or "未检测到"
    console.print(f"     检测到的隔离运行时: {avail}")
    console.print("     [1] ✅ 启用 (推荐)   高/中风险命令自动路由到隔离执行域, 用户无感")
    console.print("         · L1 进程级沙箱 (秒级) · L2 微 VM (内核级) · 网络默认隔离")
    console.print("     [2] ⚠️ 仅审批模式    不启用隔离, 依赖命令审批 + 事务回滚")
    console.print("     [3] 🔧 自定义        隔离级别 / 资源配额 / 网络策略 (写配置后手动调)")
    try:
        choice = input("     选择 [1/2/3] (默认 1): ").strip() or "1"
    except (EOFError, KeyboardInterrupt):
        choice = "1"

    if choice == "2":
        config.set_user("security.sandbox.enabled", False)
        console.print("     ✓ 已选择仅审批模式 (可随时在配置里开启 security.sandbox.enabled)")
        return
    if choice == "3":
        config.set_user("security.sandbox.enabled", True)
        console.print("     ✓ 已启用; 资源/网络策略见配置 security.sandbox.* (cpu/memory_mb/"
                      "pids/network/network_allow/forbidden_paths)")
    else:
        config.set_user("security.sandbox.enabled", True)
        console.print("     ✓ 已启用分层沙箱 (低风险宿主直跑 · 中风险 L1 · 高风险 L2)")

    if choice in ("1", "3"):
        if avail == "未检测到":
            console.print("     ⚠️ 当前机器未检测到 bwrap / runsc —— 已记录偏好, "
                          "运行时缺失会自动降级为「审批模式」, 绝不静默假装隔离。")
            console.print("        安装运行时: Linux `apt install bubblewrap` / "
                          "gVisor `apt install runsc`; 启用后用 `tuan safe vm-status` 查看。")
        else:
            console.print("     ✓ 沙箱运行时就绪; 随时可用 `tuan safe vm-status` 查看状态。")


def cmd_setup(args: Any) -> int:
    """初始化向导。"""
    # C-1.6 跳过机制: `tuan setup --skip` 或 TUAN_SKIP_SETUP=1 直接写完成标记退出。
    if getattr(args, "skip", False) or os.environ.get("TUAN_SKIP_SETUP") == "1":
        try:
            from .cmd_onboarding import mark_onboarding_done

            mark_onboarding_done()
        except Exception:  # noqa: BLE001 - 标记写失败不影响跳过语义
            pass
        console.print("  已跳过设置向导。可用 `tuan setup` 随时重跑。")
        return 0

    # B3 XIII A′: 一进入向导就派发（--skip 快速路径上面已 return，不派发）。
    # 初版放在 input() 之后，重依赖链阻塞时静默不触发 —— 端到端真跑
    # 抓回，源码扫描看不出来。
    try:
        from ..hooks.lifecycle import emit
        emit("Setup", {"quick": bool(getattr(args, "quick", False)),
                       "source": "cli/setup"})
    except Exception:  # noqa: BLE001
        pass

    kernel = build_kernel()
    config = kernel.require("config")
    ensure_language(config)

    # C-1 首次向导 (onboarding 以 --quick 进入): 直接走精简三步 (Provider -> Key -> 模式)
    if getattr(args, "quick", False):
        return _wizard_first_run(config)

    console.print(f"{t('setup.title')}")
    console.print(f"  1. {t('setup.opt_quick')}")
    console.print(f"  2. {t('setup.opt_full')}")
    console.print(f"  3. {t('setup.opt_blank')}")
    try:
        choice = input(t("setup.choose")).strip() or "1"
    except (EOFError, KeyboardInterrupt):
        choice = "1"

    if choice == "1":
        return _setup_quick(config)
    if choice == "2":
        return _setup_full(config)
    if choice == "3":
        return _setup_blank(config)
    console.print(f"{t('setup.wip')}")
    return 0


def _setup_quick(config: Any) -> int:
    """快速设置: 供应商 + 模型 + API Key。"""
    console.print(f"\n{t('setup.quick_title')}")
    picked = _pick_setup_provider()
    if picked is None:
        console.print("  已取消。")
        return 0
    provider, model_name, base_url, api_key_env = picked
    preset = get_provider(provider)
    console.print(f"\n  {t('setup.chosen', provider=provider)}")
    if preset:
        console.print(f"  {t('setup.gateway', url=preset.base_url)}")
    else:
        console.print(f"  {t('setup.gateway', url=base_url)}")
    if api_key_env:
        # C-1.3: API Key 安全输入不回显 (getpass)
        key = _ask_api_key(api_key_env)
        if key:
            _save_api_key(api_key_env, key)

    config.set_user("model.provider", provider)
    config.set_user("model.model", model_name)
    if base_url:
        config.set_user("model.base_url", base_url)
    if api_key_env:
        config.set_user("model.api_key_env", api_key_env)
    console.print(f"\n{t('setup.done', model=f'{provider}/{model_name}')}")
    return 0


def _ask_api_key(env_name: str) -> str:
    """C-1.3: 安全输入 API Key (getpass 不回显)。

    终端不支持 getpass 时回退普通 input (仍不回显由调用方约束; 测试环境兼容)。
    """
    import getpass

    try:
        key = getpass.getpass(f"  请输入 {env_name} (输入时不显示): ").strip()
    except (EOFError, KeyboardInterrupt):
        key = ""
    except Exception:  # noqa: BLE001 - 罕见无 tty 场景回退
        try:
            key = input(f"  请输入 {env_name}: ").strip()
        except (EOFError, KeyboardInterrupt):
            key = ""
    return key


# C-1.2: 首次向导展示的 6 家常用供应商 (名称 -> 展示文案)
_CURATED_PROVIDERS = [
    ("deepseek", "DeepSeek    (国内直连, 性价比高)"),
    ("groq", "Groq        (海外, 速度极快, 免费额度)"),
    ("sensenova", "SenseNova   (商汤日日新, 国内直连)"),
    ("ollama", "Ollama      (本地离线, 无需 Key)"),
    ("openrouter", "OpenRouter  (海外聚合, 一家 Key 用百家模型)"),
    ("zhipu", "Zhipu       (智谱 GLM, 国内直连, 有免费模型)"),
]


def _wizard_first_run(config: Any) -> int:
    """C-1 首次精简三步向导: Step1 选 Provider -> Step2 填 API Key -> Step3 选模式。

    默认推荐模式「协同」(collaboration)。完成后写配置 + onboarding 完成标记。
    """
    import getpass  # noqa: F401  (保留显式导入便于检索)

    console.print("\n  🎯 三步完成初始化 (随时 Ctrl+C 退出, 配置不会写坏)\n")

    # ---- Step1: 选 Provider (6 家常用) ----
    console.print("  第 1 步 / 3: 选择模型供应商")
    for i, (_name, desc) in enumerate(_CURATED_PROVIDERS, 1):
        console.print(f"    {i}. {desc}")
    try:
        raw = input("  选择编号 [1-6] (默认 1 DeepSeek): ").strip() or "1"
        idx = max(1, min(int(raw), 6)) - 1
    except (ValueError, EOFError, KeyboardInterrupt):
        idx = 0
    provider, _desc = _CURATED_PROVIDERS[idx]

    preset = get_provider(provider)
    base_url = preset.base_url if preset else ""
    api_key_env = preset.api_key_env if preset else ""

    # Ollama 本地不需要 Key
    is_local = provider == "ollama"
    model_name = ""
    if not is_local:
        if preset:
            # 从该供应商目录里挑第一个模型作默认 (避免再让用户选一次模型)
            model_name = (preset.default_model or "").strip() if hasattr(preset, "default_model") else ""
        if not model_name:
            model_name = {"deepseek": "deepseek-chat", "groq": "llama-3.3-70b-versatile",
                          "sensenova": "SenseChat-5", "openrouter": "deepseek/deepseek-chat",
                          "zhipu": "glm-4-flash"}.get(provider, "")
    else:
        model_name = "llama3.1"

    # ---- Step2: 填 API Key (不回显) ----
    if not is_local:
        console.print(f"\n  第 2 步 / 3: 填入 {provider} 的 API Key")
        console.print(f"     (将保存到 ~/.tuan/.env, 环境变量名: {api_key_env})")
        key = _ask_api_key(api_key_env)
        if key:
            _save_api_key(api_key_env, key)
        else:
            console.print("     (未输入 Key: 稍后可用 `tuan models set` 再配)")
    else:
        console.print("\n  第 2 步 / 3: 本地模型无需 API Key, 跳过 ✅")

    # ---- Step3: 选默认模式 (五模式, 默认推荐「协同」) ----
    console.print("\n  第 3 步 / 3: 选择默认工作模式")
    from ..modes.registry import MODE_REGISTRY

    mode_ids = ["collaboration", "gantong", "lingma", "chat", "boundless"]
    for i, mid in enumerate(mode_ids, 1):
        meta = MODE_REGISTRY.get(mid, {})
        tag = " (推荐)" if mid == "collaboration" else ""
        console.print(f"    {i}. {meta.get('name', mid):<6} [{meta.get('level', '?')}] "
                      f"{meta.get('description', '')[:34]}{tag}")
    try:
        raw = input("  选择编号 [1-5] (默认 1 协同): ").strip() or "1"
        mode_picked = mode_ids[max(1, min(int(raw), 5)) - 1]
    except (ValueError, EOFError, KeyboardInterrupt):
        mode_picked = "collaboration"

    # ---- 写配置 ----
    config.set_user("model.provider", provider)
    config.set_user("model.model", model_name)
    if base_url:
        config.set_user("model.base_url", base_url)
    if api_key_env:
        config.set_user("model.api_key_env", api_key_env)
    config.set_user("mode.default", mode_picked)

    # C-1.5: 写 onboarding 完成标记 (下次不再自动弹向导)
    try:
        from .cmd_onboarding import mark_onboarding_done

        mark_onboarding_done()
    except Exception:  # noqa: BLE001
        pass

    console.print(f"\n  ✅ 初始化完成! 供应商={provider}  模型={model_name}  模式={mode_picked}")
    console.print("  输入 `tuan` 开始对话, 或 `tuan run \"任务\"` 跑一次性任务。")
    return 0


def _pick_from_free_tier() -> Any:
    """免费层子菜单: 只列"不花钱、不绑卡就能跑通"的供应商 (见 provider_catalog.free_providers)。

    这是新用户最快的首次跑通路径 —— 不必先掏卡、先充值。
    """
    free = free_providers()
    if not free:
        console.print("  ! 未找到免费层供应商")
        return None
    console.print("\n  ★ 免费层 (无需绑卡即可跑通):")
    for i, p in enumerate(free, 1):
        tag = "本地" if p.category == "本地部署" else p.region
        console.print(f"    {i:2d}. {p.name:<16s} [{tag}] {p.desc[:46]}")
    try:
        sel = int(input("  选择编号: ").strip() or "1") - 1
    except (ValueError, EOFError, KeyboardInterrupt):
        return None
    if not (0 <= sel < len(free)):
        sel = 0
    preset = free[sel]
    from .cmd_chat import _pick_model_interactive
    provider, model_name = _pick_model_interactive(preset)
    preset = get_provider(provider) or preset
    return provider, model_name, preset.base_url, preset.api_key_env


def _pick_setup_provider() -> Any:
    """setup 向导的供应商选择: 前 12 个内置预设 + 免费层筛选 + 末尾"自定义 (OpenAI 兼容端点)"。

    在编号处输入 ``f`` / ``free`` / ``免费`` 可切到**只看免费层**
    (无需绑卡即可跑通的那几家)。返回 (provider, model_name, base_url, api_key_env);
    用户中途取消返回 None。
    """
    console.print(f"  {t('setup.providers')}")
    names = list(PROVIDER_PRESETS.keys())[:12]
    for i, name in enumerate(names, 1):
        p = PROVIDER_PRESETS[name]
        console.print(f"    {i:2d}. {name:<20s} {p.get('desc','')[:40]}")
    console.print(f"    {13:2d}. 自定义 (手动配置 OpenAI 兼容端点)")
    console.print(f"    输入 f 只看免费层 (无需绑卡即可跑通, {len(free_providers())} 家)")
    try:
        raw = input(t("setup.pick_number")).strip() or "1"
    except (EOFError, KeyboardInterrupt):
        raw = "1"
    if raw.lower() in ("f", "free", "免费"):
        return _pick_from_free_tier()
    try:
        idx = int(raw) - 1
    except ValueError:
        idx = 0
    names = list(PROVIDER_PRESETS.keys())
    if idx == 12:
        # 自定义 OpenAI 兼容端点: 手填 provider/base_url/模型/api_key_env。
        try:
            custom_provider = input(
                "  供应商名称 (回车用 custom, 仅作展示用): ").strip() or "custom"
            custom_base = input(
                "  base_url (OpenAI 兼容, 如 https://api.example.com/v1): ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("  已取消")
            return None
        if not custom_base:
            console.print("  ! base_url 不能为空, 已取消")
            return None
        try:
            custom_model = input("  模型名 (如 gpt-4o-mini): ").strip()
            custom_env = input(
                "  API Key 环境变量名 (回车用 CUSTOM_API_KEY): ").strip() or "CUSTOM_API_KEY"
        except (EOFError, KeyboardInterrupt):
            console.print("  已取消")
            return None
        if not custom_model:
            console.print("  ! 模型名不能为空, 已取消")
            return None
        return custom_provider, custom_model, custom_base, custom_env
    if idx >= len(names):
        idx = 0
    provider = names[idx]
    from .cmd_chat import _pick_model_interactive
    preset = get_provider(provider) or ALL_PROVIDERS[0]
    provider, model_name = _pick_model_interactive(preset)
    preset = get_provider(provider) or preset
    api_key_env = preset.api_key_env
    return provider, model_name, preset.base_url, api_key_env


def _save_api_key(env_name: str, key: str) -> None:
    """把密钥写入 ~/.tuan/.env (幂等覆盖同名行, 不累积重复)。"""
    env_path = persist_api_key(env_name, key)
    console.print(f"  {t('setup.key_saved', path=env_path)}")


def _ask_choice(prompt: str, options: List[str], default: str) -> str:
    """通用枚举选择。"""
    try:
        raw = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return default
    if not raw:
        return default
    return raw if raw in options else default


def _setup_full(config: Any) -> int:
    """完整设置: 供应商/模型/API Key + 运行模式/推理投入/温度/输出上限。"""
    console.print(f"\n{t('setup.full_title')}")
    picked = _pick_setup_provider()
    if picked is None:
        console.print("  已取消。")
        return 0
    provider, model_name, base_url, api_key_env = picked
    preset = get_provider(provider)
    console.print(f"\n  {t('setup.chosen', provider=provider)}")
    if preset:
        console.print(f"  {t('setup.gateway', url=preset.base_url)}")
    else:
        console.print(f"  {t('setup.gateway', url=base_url)}")
    if api_key_env:
        # C-1.3: API Key 安全输入不回显 (getpass)
        key = _ask_api_key(api_key_env)
        if key:
            _save_api_key(api_key_env, key)

    mode = _ask_choice(t("setup.mode_prompt"), ["standard", "yolo"], "standard")
    effort = _ask_choice(t("setup.effort_prompt"), ["low", "medium", "high"], "high")
    try:
        temp = float(input(t("setup.temp_prompt")).strip() or "0.7")
        temp = max(0.0, min(2.0, temp))
    except (ValueError, EOFError, KeyboardInterrupt):
        temp = 0.7
    try:
        mt = int(input(t("setup.max_tokens_prompt")).strip() or "8192")
        mt = max(1, mt)
    except (ValueError, EOFError, KeyboardInterrupt):
        mt = 8192

    config.set_user("model.provider", provider)
    config.set_user("model.model", model_name)
    if base_url:
        config.set_user("model.base_url", base_url)
    if api_key_env:
        config.set_user("model.api_key_env", api_key_env)
    config.set_user("model.temperature", temp)
    config.set_user("model.max_tokens", mt)
    config.set_user("mode.default", mode)
    config.set_user("agent.effort", effort)
    # 安全加固: 分层沙箱隔离 (高风险命令自动路由到隔离执行域)
    _ask_sandbox_setup(config)
    console.print(f"\n{t('setup.done', model=f'{provider}/{model_name}')}")
    console.print(f"  {t('setup.full_summary', mode=mode, effort=effort, temp=temp, mt=mt)}")
    return 0


def _setup_blank(config: Any) -> int:
    """空白设置: 仅创建目录骨架, 不配置模型。"""
    config.ensure_home()
    console.print(f"\n{t('setup.blank_title')}")
    console.print(f"  {t('setup.blank_created')}")
    console.print(f"  {t('setup.blank_hint')}")
    for line in t("setup.blank_commands").split("\n"):
        console.print(f"    {line}")
    return 0


# ===================================================================== cmd_bench

_BENCH_EXCLUDE_TOOLS = (
    "write_file", "edit_file", "delete_file", "delete_dir", "move_file",
    "skill_save", "memory_write", "memory_update_user", "run_shell",
)


def cmd_bench(args: Any) -> int:
    """基准测试。"""
    bench_cmd = getattr(args, "bench_cmd", None)
    if bench_cmd == "cache":
        return _bench_cache(args)
    if bench_cmd == "latency":
        return _bench_latency(args)
    console.print("bench 功能开发中…")
    return 0


def _bench_cache(args: Any) -> int:
    """实测 prompt cache 命中率。"""
    from ..ui.format import Table as FTable

    rounds = max(1, getattr(args, "rounds", 8))
    task = getattr(args, "task", "解释一下当前工作区的结构")
    try:
        kernel = build_kernel()
    except Exception as exc:  # noqa: BLE001
        console.print(f"启动失败: {exc}")
        return 1
    config = kernel.require("config")
    provider = config.get("model.provider", "?")
    model = config.get("model.model", "?")
    if not config.api_key():
        console.print("未配置 API Key, 无法调用模型。请先运行 tuan setup 或 tuan models 配置。")
        return 1

    agent = create_agent(kernel, os.getcwd(), confirm=lambda prompt: True, exclude_tools=_BENCH_EXCLUDE_TOOLS)
    console.print("缓存命中率基准测试")
    console.print(f"  模型: {provider}/{model}")
    console.print(f"  轮次: {rounds}")
    console.print(f"  首轮任务: {task}\n")

    rows: List[tuple] = []
    errors = 0
    prev: Dict[str, int] = {}
    for i in range(rounds):
        prompt = task if i == 0 else f"继续。请基于以上对话，深入展开第 {i + 1} 部分，补充新的细节和见解。"
        t0 = time.time()
        try:
            agent.run(prompt, stream=False)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            console.print(f"  第 {i + 1} 轮失败: {exc}")
            continue
        elapsed = time.time() - t0
        cur = dict(agent.total_usage)
        delta = {k: cur.get(k, 0) - prev.get(k, 0) for k in cur}
        prev = cur
        rows.append((i + 1, delta, elapsed))

    if not rows:
        console.print("所有轮次均失败, 无法统计。")
        return 1

    total_prompt = sum(r[1].get("prompt_tokens", 0) for r in rows)
    total_completion = sum(r[1].get("completion_tokens", 0) for r in rows)
    total_hit = sum(r[1].get("prompt_cache_hit_tokens", 0) for r in rows)
    total_miss = sum(r[1].get("prompt_cache_miss_tokens", 0) for r in rows)
    hit_rate = total_hit / (total_hit + total_miss) if (total_hit + total_miss) > 0 else 0.0

    table = FTable(title="逐轮明细")
    table.add_column("轮次", justify="right")
    table.add_column("耗时(s)", justify="right")
    table.add_column("prompt", justify="right")
    table.add_column("输出", justify="right")
    table.add_column("缓存命中", justify="right")
    table.add_column("缓存未命中", justify="right")
    table.add_column("命中率", justify="right")
    for idx, usage, elapsed in rows:
        hit = usage.get("prompt_cache_hit_tokens", 0)
        miss = usage.get("prompt_cache_miss_tokens", 0)
        rate = hit / (hit + miss) if (hit + miss) > 0 else 0.0
        table.add_row(
            str(idx), f"{elapsed:.1f}",
            f"{usage.get('prompt_tokens', 0):,}",
            f"{usage.get('completion_tokens', 0):,}",
            f"{hit:,}", f"{miss:,}", f"{rate:.1%}",
        )
    console.print(table)

    from ..models.router import estimate_cost
    est_cost = estimate_cost(provider, model, total_prompt, total_completion)
    console.print("\n汇总")
    console.print(f"  总 prompt: {total_prompt:,}")
    console.print(f"  总输出:   {total_completion:,}")
    console.print(f"  缓存命中: {total_hit:,} ({hit_rate:.1%})")
    console.print(f"  缓存未命中: {total_miss:,}")
    if errors:
        console.print(f"  失败轮次: {errors}")
    console.print(f"  估算成本: ${est_cost:.4f}")
    return 0


def _bench_latency(args: Any) -> int:
    """实测模型响应延迟与吞吐。"""
    rounds = max(1, getattr(args, "rounds", 5))
    task = getattr(args, "task", "ping")
    try:
        kernel = build_kernel()
    except Exception as exc:  # noqa: BLE001
        console.print(f"启动失败: {exc}")
        return 1
    config = kernel.require("config")
    provider = config.get("model.provider", "?")
    model = config.get("model.model", "?")
    if not config.api_key():
        console.print("未配置 API Key, 无法调用模型。请先运行 tuan setup 或 tuan models 配置。")
        return 1

    from ..models import create_adapter
    try:
        adapter = create_adapter(config)
    except Exception as exc:  # noqa: BLE001
        console.print(f"适配器创建失败: {exc}")
        return 1

    console.print("延迟基准测试")
    console.print(f"  模型: {provider}/{model}")
    console.print(f"  轮次: {rounds}")
    console.print(f"  请求: {task!r}\n")

    latencies: List[float] = []
    tokens = 0
    errors = 0
    for i in range(rounds):
        t0 = time.time()
        try:
            resp = adapter.chat([{"role": "user", "content": task}], stream=False)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            console.print(f"  第 {i + 1} 轮失败: {exc}")
            continue
        elapsed = time.time() - t0
        latencies.append(elapsed)
        usage = getattr(resp, "usage", None) or {}
        tokens += usage.get("completion_tokens", 0)
        console.print(f"  第 {i + 1} 轮: {elapsed:.2f}s")

    if not latencies:
        console.print("所有轮次均失败, 无法统计。")
        return 1

    latencies.sort()
    avg = sum(latencies) / len(latencies)
    p95 = latencies[int(len(latencies) * 0.95) - 1]
    total_time = sum(latencies)
    throughput = tokens / total_time if total_time > 0 else 0.0

    console.print("\n汇总")
    console.print(f"  成功轮次: {len(latencies)}/{rounds}" + (f" (失败 {errors})" if errors else ""))
    console.print(f"  平均延迟: {avg:.2f}s")
    console.print(f"  最小延迟: {latencies[0]:.2f}s")
    console.print(f"  最大延迟: {latencies[-1]:.2f}s")
    console.print(f"  P95 延迟: {p95:.2f}s")
    console.print(f"  总输出 token: {tokens:,}")
    console.print(f"  吞吐: {throughput:.1f} tokens/s")
    return 0


# ===================================================================== cmd_open

def cmd_open(args: Any) -> int:
    """打开文件并定位到行: tuan open <file>[:<line>]。"""
    target = getattr(args, "target", "")
    if not target:
        console.print("用法: tuan open <file>[:<line>], 例如 tuan open tuan_cli/core/agent.py:42")
        return 1
    line = 0
    path_str = target
    if ":" in target:
        path_str, _, line_str = target.rpartition(":")
        try:
            line = int(line_str)
        except ValueError:
            console.print(f"行号无效: {line_str}")
            return 1
    fpath = Path(path_str).expanduser()
    if not fpath.is_absolute():
        fpath = Path.cwd() / fpath
    if not fpath.exists():
        console.print(f"文件不存在: {fpath}")
        return 1
    from ..tools.code import _open_in_editor
    editor = ""
    try:
        kernel = build_kernel()
        editor = kernel.require("config").get("ui.editor", "")
    except Exception as exc:  # noqa: BLE001
        log.debug("读取编辑器配置失败: %s", exc)
    console.print(_open_in_editor(fpath.resolve(), line, editor))
    return 0
