"""tuan offline —— 离线/本地优先态势 CLI 入口。

差异化独特能力: **本地优先** 是 Tuan-CLI 相对纯云 Agent CLI 的核心卖点。
本命令把「网络探测 → 离线降级 → 本地模型路由」的完整链路状态暴露给用户,
让运维/使用者一眼看到:

- 当前网络是否可达 (探测结果 + 探测路径)
- 是否已触发离线降级 (路由自动切到本地模型)
- 本机本地模型库存 (Ollama / llama.cpp)
- 降级决策预览 (若现在断网, 会切到哪个模型)

用法::

    tuan offline status     离线/本地优先综合态势
    tuan offline route      降级决策预览 (不实际切换)
    tuan offline models     本机本地模型清单
    tuan offline doctor     链路自检 (探测/降级/路由逐项健康)
"""
from __future__ import annotations

import sys
from typing import Any, Dict

from rich.console import Console
from rich.table import Table

console = Console()


def cmd_offline(args: Any) -> int:
    """``tuan offline`` 顶层分发。"""
    sub = getattr(args, "offline_cmd", None) or "status"

    if sub == "status":
        return _offline_status()
    if sub == "route":
        tree = bool(getattr(args, "tree", False))
        json_mode = bool(getattr(args, "json", False))
        if tree or json_mode:
            return _offline_route_tree(json_mode)
        return _offline_route()
    if sub == "models":
        return _offline_models()
    if sub == "doctor":
        return _offline_doctor()
    if sub == "pull":
        return _offline_pull(args)
    if sub == "verify":
        return _offline_verify(args)
    if sub == "probe":
        return _offline_probe(args)
    console.print("[red]未知子命令:[/red] %s (可用: status / route / models / doctor / pull / verify / probe)" % sub)
    return 1


# ------------------------------------------------------------------ 模型完整性校验

def _offline_verify(args: Any) -> int:
    """校验已装模型完整性 (供应链防投毒)。

      tuan offline verify [--json]
        --json   结构化输出 (CI / 审计消费)
    """
    from ..models.offline import get_ollama_manager

    json_mode = bool(getattr(args, "json", False))
    try:
        # OllamaManager 未实现 verify_models (models/offline.py 不在本批修改范围);
        # getattr 动态取用: 缺失时抛同款 AttributeError, 由上方 except 走 fail-closed 报错。
        verify = getattr(get_ollama_manager(), "verify_models", None)
        if verify is None:
            raise AttributeError("'OllamaManager' object has no attribute 'verify_models'")
        result = verify()
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]模型完整性校验失败: {exc}[/red]")
        return 1

    if json_mode:
        import json as _json
        sys.stdout.write(_json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return 0 if result.get("ok") else 2

    console.print("\n[bold]=== 离线模型完整性校验 ===[/bold]\n")
    if not result.get("ok"):
        console.print(f"[red]✗ 存在损坏/缺失的模型 blob[/red] "
                      f"({len(result.get('problems', []))} 个问题)")
        for p in result.get("problems", []):
            console.print(f"  [red]•[/red] {p}")
        console.print(f"[dim]模型目录: {result.get('model_home', '?')}[/dim]")
        console.print("[dim]提示: 对损坏模型运行 `tuan offline pull <模型>` 重拉, "
                      "或 `ollama rm <模型> && ollama pull <模型>`[/dim]")
        return 2

    verified = result.get("verified", [])
    console.print(f"[green]✓ 完整性校验通过[/green] "
                  f"({len(verified)}/{result.get('checked', 0)} 模型正常)")
    for name in verified:
        console.print(f"  [dim]•[/dim] {name}")
    console.print(f"[dim]模型目录: {result.get('model_home', '?')}[/dim]")
    console.print("[dim]说明: digest 即 sha256 引用, blob 存在且非空即通过目录级校验[/dim]")
    return 0


# ------------------------------------------------------------------ 状态

def _offline_status() -> int:
    """网络探测 + 离线降级 + 本地模型库存综合态势。"""
    from ..core import network_check
    from ..models.offline import check_offline_status
    from ..models import router

    probe = network_check.offline_status()
    offline = bool(probe.get("offline"))
    degrade = router.offline_degrade_active()
    local = check_offline_status()

    console.print("\n[bold]=== 离线/本地优先 综合态势 ===[/bold]\n")

    # 网络
    net_tbl = Table(title="网络可达性", show_header=False, box=None)
    net_tbl.add_column("指标", style="bold")
    net_tbl.add_column("值")
    net_tbl.add_row("状态", "[red]离线[/red]" if offline else "[green]在线[/green]")
    via = probe.get("via")
    net_tbl.add_row("探测路径", str(via) if via else "—")
    checked_at = probe.get("checked_at")
    if isinstance(checked_at, (int, float)):
        from datetime import datetime as _dt
        net_tbl.add_row("探测时间", _dt.fromtimestamp(checked_at).strftime("%Y-%m-%d %H:%M:%S"))
    timed_out = bool(probe.get("timed_out"))
    if timed_out:
        net_tbl.add_row("备注", "[yellow]探测超时 (DNS/连接挂起), 按离线处理[/yellow]")
    console.print(net_tbl)

    # 路由降级
    console.print("")
    if degrade:
        console.print("[bold]路由降级[/bold]: [red]已激活[/red] — 当前请求已切到本地模型")
    else:
        console.print("[bold]路由降级[/bold]: [green]未激活[/green] — 远程模型可用, 未强制降级")

    # 本地模型
    console.print("")
    ollama = local.get("ollama_available")
    llama = local.get("llamacpp_available")
    models = local.get("installed_models") or []
    llama_models = local.get("llamacpp_models") or []
    total_models = len(models) + len(llama_models)
    console.print(f"[bold]本地模型库存[/bold]: {total_models} 个")
    console.print(f"  Ollama   : {'[green]可用[/green]' if ollama else '[red]不可用[/red]'}"
                  f" — {len(models)} 个已安装")
    for m in models:
        console.print(f"      • {m.get('name')} ({m.get('size', '?')})")
    console.print(f"  llama.cpp: {'[green]可用[/green]' if llama else '[dim]未检测到[/dim]'}"
                  f" — {len(llama_models)} 个已加载")
    for m in llama_models:
        console.print(f"      • {m}")

    # 决策建议
    console.print("")
    if offline and total_models:
        console.print("[bold]建议[/bold]: [green]离线 + 有本地模型[/green] → 可安全降级, 无需联网")
    elif offline and not total_models:
        console.print("[bold]建议[/bold]: [yellow]离线 + 无本地模型[/yellow] → 模型调用将失败, 请先拉取本地模型")
    elif not offline:
        console.print("[bold]建议[/bold]: [green]在线[/green] → 默认走远程模型, 断网自动降级")

    console.print("\n[dim]提示: tuan offline route 看降级决策预览; "
                  "tuan offline doctor 逐项链路自检[/dim]")
    return 0


def _offline_route() -> int:
    """降级决策预览: 若现在断网/离线, 路由会切到哪个模型。"""
    from ..core import network_check
    from ..models import router

    offline = network_check.is_offline()
    degrade = router.offline_degrade_active()
    local_avail = network_check.local_model_available()

    console.print("\n[bold]=== 离线降级决策预览 ===[/bold]\n")
    console.print(f"  网络探测   : {'[red]离线[/red]' if offline else '[green]在线[/green]'}")
    console.print(f"  本地模型   : {'[green]有[/green]' if local_avail else '[red]无[/red]'}")
    console.print(f"  降级已激活 : {'[red]是[/red]' if degrade else '[green]否[/green]'}")

    console.print("")
    if offline and local_avail:
        console.print("[bold]决策[/bold]: [green]降级到本地模型[/green] (当前请求走 Ollama/llama.cpp)")
    elif offline and not local_avail:
        console.print("[bold]决策[/bold]: [red]降级但无本地模型[/red] → 需先拉取本地模型, 否则请求失败")
    elif not offline:
        console.print("[bold]决策[/bold]: [green]保持远程模型[/green] (断网时会自动降级)")
    return 0


def _offline_route_tree(json_mode: bool) -> int:
    """离线降级决策树预览 (差异化: 完整分支/条件/结论, 不只当前快照)。

    把「网络 × 本地模型 × 降级状态」的完整决策矩阵渲染成树:
      - 根: 当前实际探测到的网络/本地/降级三要素;
      - 分支: 三要素各自的 true/false 组合 (8 种情形);
      - 每个叶子给结论 (降级到本地 / 保持远程 / 需拉取模型)。
    与 ``_offline_route`` (只看当前快照) 互补: 这里暴露**全部可能路径**,
    让运维一次性看到所有降级分支, 而不是只看到此刻走哪条。
    """
    from ..core import network_check
    from ..models import router

    offline = bool(network_check.is_offline())
    degrade = bool(router.offline_degrade_active())
    local_avail = bool(network_check.local_model_available())

    def _conclude(off: bool, loc: bool) -> tuple[str, str]:
        """返回 (标签, 结论)。"""
        if off and loc:
            return "green", "降级到本地模型 (Ollama/llama.cpp, 零成本本地推理)"
        if off and not loc:
            return "red", "降级但无本地模型 → 需先拉取, 否则请求失败"
        return "green", "保持远程模型 (断网时自动降级)"

    if json_mode:
        import json as _json

        branches = []
        for o in (True, False):
            for l in (True, False):
                tag, concl = _conclude(o, l)
                branches.append({
                    "network_offline": o,
                    "local_model_available": l,
                    "outcome": "degrade_to_local" if (o and l) else (
                        "degrade_fail_no_local" if (o and not l) else "keep_remote"),
                    "conclusion": concl,
                })
        sys.stdout.write(_json.dumps({
            "current": {"network_offline": offline, "local_model_available": local_avail,
                        "degrade_active": degrade},
            "branches": branches,
            "current_outcome": _conclude(offline, local_avail)[1],
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print("\n[bold]=== 离线降级决策树 (完整分支) ===[/bold]\n")

    # 根: 当前三要素
    console.print(f"  网络探测: {'[red]离线[/red]' if offline else '[green]在线[/green]'}")
    console.print(f"  本地模型: {'[green]有[/green]' if local_avail else '[red]无[/red]'}")
    console.print(f"  降级激活: {'[red]是[/red]' if degrade else '[green]否[/green]'}")
    console.print("")

    # 树: 分支1=网络, 分支2=本地模型
    console.print("  [bold]决策树[/bold]")
    console.print("  网络 ──┬─ 离线 ──┬─ 有本地模型 → 降级到本地 (零成本本地推理)")
    console.print("         │         └─ 无本地模型 → 降级但无模型 (需先拉取)")
    console.print("         └─ 在线 ──┬─ 有本地模型 → 保持远程 (可随时切本地)")
    console.print("                   └─ 无本地模型 → 保持远程 (无本地兜底)")

    console.print("")
    # 当前路径高亮
    cur_o = "离线" if offline else "在线"
    cur_l = "有本地模型" if local_avail else "无本地模型"
    tag, concl = _conclude(offline, local_avail)
    console.print(f"  [bold]当前路径[/bold]: [{tag}]网络{cur_o} + {cur_l}")
    console.print(f"  [bold]结论[/bold]: [{tag}]{concl}")

    console.print("\n[dim]提示: 这是静态决策矩阵 (8 分支); 实际运行按探测实时裁决。"
                  "tuan offline route 看当前快照 / status 看综合态势[/dim]")
    return 0


def _offline_models() -> int:
    """本机本地模型清单。"""
    from ..models.offline import check_offline_status

    local = check_offline_status()
    console.print("\n[bold]=== 本机本地模型 ===[/bold]\n")
    models = local.get("installed_models") or []
    llama_models = local.get("llamacpp_models") or []
    if not models and not llama_models:
        console.print("[dim]未安装/未加载任何本地模型[/dim]")
        console.print("[dim]提示: tuan offline models 需 Ollama 运行中; 或访问 https://ollama.com[/dim]")
        return 0
    if models:
        console.print("[bold]Ollama[/bold]:")
        for m in models:
            console.print(f"  • {m.get('name')} ({m.get('size', '?')})")
    if llama_models:
        console.print("[bold]llama.cpp[/bold]:")
        for m in llama_models:
            console.print(f"  • {m}")
    return 0


def _offline_pull(args: Any) -> int:
    """下载本地模型 (Ollama), 带实时进度回调。

    独特能力: Claude Code 无离线模型管理, 断网即不可用;
    Tuan-CLI 预先把模型拉到本地, 断网后零成本本地推理。
    """
    from ..models.offline import OllamaManager

    model = getattr(args, "model", None)
    if not model:
        console.print("[red]用法: tuan offline pull <模型名> (如 qwen2.5:7b)[/red]")
        console.print("[dim]提示: tuan offline models 看已装; 或 tuan offline doctor 看链路[/dim]")
        return 1

    console.print(f"\n[bold]正在下载本地模型[/bold] {model} ...\n")
    mgr = OllamaManager()
    ok = mgr.pull_model(model, callback=_on_pull_progress)
    console.print()
    if ok:
        console.print(f"[green]✓ 已下载 {model}[/green]")
        console.print("[dim]验证: tuan offline models 应列出该模型[/dim]")
        return 0
    console.print(f"[red]✗ 下载失败: {model}[/red]")
    console.print("[dim]排障: 1) ollama 已安装? 2) 网络可达? "
                  "3) 磁盘空间? 4) tuan offline doctor 自检[/dim]")
    return 1


def _on_pull_progress(line: str) -> None:
    """进度回调: 单行打印 ollama pull 输出 (含百分比/状态行)。"""
    line = line.strip()
    if not line:
        return
    # ollama pull 通常输出 "pulling manifest", "verifying sha256 digest",
    # "writing manifest", "success" 等; 带百分比行直接打印, 其他行也打印。
    console.print(f"[dim]{line}[/dim]")


def _offline_doctor() -> int:
    """链路自检: 探测 / 降级 / 路由逐项健康, 供排障。"""
    from ..core import network_check
    from ..models import router
    from ..models.offline import check_offline_status

    probe = network_check.offline_status()
    degrade = router.offline_degrade_active()
    local = check_offline_status()

    console.print("\n[bold]=== 离线链路自检 ===[/bold]\n")
    checks: list[tuple[str, bool, str]] = [
        ("网络探测", bool(probe.get("offline") is not None),
         f"offline={probe.get('offline')}, via={probe.get('via') or '—'}"),
        ("路由降级状态", True, f"degrade={degrade}"),
        ("Ollama 探测", bool(local.get("ollama_available")),
         local.get("ollama_error") or "可用"),
        ("llama.cpp 探测", bool(local.get("llamacpp_available")),
         local.get("llamacpp_error") or "可用"),
        ("本地模型库存", True, f"{len(local.get('installed_models') or [])} Ollama + "
                               f"{len(local.get('llamacpp_models') or [])} llama.cpp"),
    ]
    all_ok = True
    for name, ok, detail in checks:
        mark = "[green]✓[/green]" if ok else "[yellow]△[/yellow]"
        if not ok:
            all_ok = False
        console.print(f"  {mark} {name:<14} {detail}")
    console.print("")
    console.print("[green]链路健康[/green]" if all_ok else "[yellow]部分项异常, 见上 (不阻断, 降级会兜底)[/yellow]")
    return 0 if all_ok else 1


def _offline_probe(args: Any) -> int:
    """强制真实网络探测 (第 59 个独特功能: 绕过缓存重检)。

    与 ``status``/``doctor`` 用缓存版 ``offline_status()`` 不同, 这里调用
    ``network_check.probe_once()`` 强制绕开进程内 10s 缓存, 做一次真实网络
    IO 探测 (含 DNS), 并给出探测端点清单与超时标志。网络刚恢复/刚断时,
    这是最可靠的「现在就测, 别信缓存」入口。

      tuan offline probe              # 强制探测 (默认 3s 超时)
      tuan offline probe --timeout 5  # 自定义超时
      tuan offline probe --json       # 机器可读 (CI 判定)
    """
    from ..core import network_check

    timeout = float(getattr(args, "timeout", 3.0) or 3.0)
    json_mode = bool(getattr(args, "json", False))

    result = network_check.probe_once(timeout=timeout)

    if json_mode:
        import json as _json
        sys.stdout.write(_json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return 0 if not result.get("offline") else 1

    offline = bool(result.get("offline"))
    console.print("\n[bold]=== 强制网络探测 (绕过缓存) ===[/bold]\n")
    console.print(f"  状态    : {'[red]离线[/red]' if offline else '[green]在线[/green]'}")
    via = result.get("via")
    console.print(f"  可达端点: {via or '—'}")
    raw_checked = result.get("checked") or []
    checked = [str(u) for u in raw_checked] if hasattr(raw_checked, "__iter__") else []
    if checked:
        console.print(f"  探测清单: {len(checked)} 个端点")
        for u in checked:
            mark = "[green]✓[/green]" if u == via else "[dim]·[/dim]"
            console.print(f"    {mark} {u}")
    timed_out = bool(result.get("timed_out"))
    if timed_out:
        console.print(f"  [yellow]⚠ 探测超时 ({timeout:.1f}s 预算耗尽, DNS/连接挂起)[/yellow]")
        console.print("  [dim]处理: 按离线处理, 但可能是 DNS 卡顿而非真断网[/dim]")
    if not offline:
        console.print("\n[dim]结论: 网络可达, 路由保持远程模型; tuan offline route 看决策[/dim]")
    else:
        console.print("\n[dim]结论: 不可达 (或超时), 自动降级逻辑将切本地模型[/dim]")
    return 0
