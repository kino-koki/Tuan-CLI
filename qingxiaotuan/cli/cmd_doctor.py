"""`qxt doctor` —— 环境健康诊断 (对标 Claude Code /doctor 与 Kimi kimi doctor)。

设计要点:

- **微内核 / 零重依赖**: 本模块不构建完整 kernel, 只做"文件系统 + 环境 + 配置文件"
  的轻量自检, 启动快、可在 CI / 容器里跑; 重依赖 (模型连通/引擎健康) 仍由
  ``cmd_chat.cmd_doctor`` 的完整链路承担 (旧测试与旧行为不受影响)。
- **结构化 findings**: ``run_checks()`` 返回纯数据 (list[dict]), 不直接 print,
  便于 ``--json`` 脚本消费与单测断言。
- **分级退出码**: 0 = 全部通过; 1 = 仅有警告; 2 = 有错误。
- **--fix**: 只修"安全且可逆"的问题 (建目录、补 frontmatter 占位字段), 不碰密钥。

诊断项 (category):
    config    配置文件 config.yaml 语法 / 必填字段 / 未知字段 / 版本兼容
    skills    技能 frontmatter 合法性 (name/description 必填, 正文非空, 无重复 slug)
    project   QXT.md / AGENTS.md / CLAUDE.md 可读性 / 体积 / 编码
    env       Python 版本 / git / 工作区可写 / venv 检测
    cache     system prompt 稳定段哈希 / 记忆存储可读写
    network   (--network) API endpoint 可达性
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .. import __version__
from ..config import home_dir

# frontmatter 正则: 与 skills/manager.py 保持一致 (^---\n ... \n---\n)
_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# 项目指令文件体积上限 (对标 Codex project_doc_max_bytes ≈ 32KiB)
_PROJECT_DOC_MAX = 32 * 1024

# 项目指令候选文件名 (三读: qxt 优先, 回退 AGENTS / CLAUDE)
_PROJECT_DOC_NAMES = ("QXT.md", "AGENTS.md", "CLAUDE.md")

# 配置文件里允许出现的顶层键 (未知键 -> 警告而非错误)
_KNOWN_TOP_KEYS = {
    "model", "mode", "skills", "memory", "hooks", "permissions", "language",
    "ui", "network", "mcp", "engine", "fusion", "acp", "onboarding", "version",
}


# ------------------------------------------------------------------ finding 构造

def _f(category: str, status: str, message: str, *,
      detail: str = "", fixable: bool = False, fixed: bool = False,
      path: str = "") -> Dict[str, Any]:
    """构造一条结构化 finding。status ∈ {"ok","warn","error"}。"""
    return {
        "category": category,
        "status": status,
        "message": message,
        "detail": detail,
        "fixable": fixable,
        "fixed": fixed,
        "path": path,
    }


# ------------------------------------------------------------------ 配置检查

def _check_config(home: Path, fix: bool) -> List[Dict[str, Any]]:
    """检查 ~/.qingxiaotuan/config.yaml 语法 / 必填字段 / 未知字段 / 版本。"""
    findings: List[Dict[str, Any]] = []
    cfg_path = home / "config.yaml"
    if not cfg_path.exists():
        findings.append(_f(
            "config", "warn", "未找到用户配置文件 config.yaml",
            detail="首次运行属正常; 运行 `qxt setup` 或 `qxt onboarding` 初始化。",
            path=str(cfg_path),
        ))
        return findings

    raw = cfg_path.read_text(encoding="utf-8", errors="replace")
    try:
        import yaml
    except ImportError:  # pragma: no cover - pyyaml 是核心依赖
        findings.append(_f("config", "error", "pyyaml 未安装, 无法解析 config.yaml"))
        return findings

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        # 提取行号, 给用户可定位的错误信息
        line = getattr(exc, "problem_mark", None)
        line_no = line.line + 1 if line is not None else None
        loc = f"第 {line_no} 行" if line_no else "未知位置"
        findings.append(_f(
            "config", "error", f"config.yaml 语法错误 ({loc})",
            detail=str(exc).splitlines()[0] if str(exc) else "",
            path=str(cfg_path),
        ))
        return findings

    if data is None:
        data = {}
    if not isinstance(data, dict):
        findings.append(_f(
            "config", "error", "config.yaml 顶层必须是键值映射 (mapping)",
            path=str(cfg_path),
        ))
        return findings

    findings.append(_f("config", "ok", "config.yaml 语法合法", path=str(cfg_path)))

    # ---- 必填字段 (仅当文件存在且非空时才要求, 避免对全新安装误报) ----
    model = data.get("model") or {}
    if not isinstance(model, dict):
        findings.append(_f("config", "error", "config.model 必须是映射", path=str(cfg_path)))
    else:
        if not model.get("provider"):
            findings.append(_f(
                "config", "warn", "config.model.provider 未设置",
                detail="运行 `qxt models set <provider> <model>` 选择供应商。",
                path=str(cfg_path),
            ))
        if not model.get("model"):
            findings.append(_f(
                "config", "warn", "config.model.model 未设置",
                detail="运行 `qxt models set <provider> <model>` 选择模型。",
                path=str(cfg_path),
            ))

    # ---- 未知顶层字段 (警告, 不阻塞) ----
    unknown = sorted(k for k in data.keys() if k not in _KNOWN_TOP_KEYS)
    if unknown:
        findings.append(_f(
            "config", "warn", f"config.yaml 含未知顶层字段: {', '.join(unknown)}",
            detail="拼写错误或废弃配置; qxt 会忽略它们。",
            path=str(cfg_path),
        ))

    # ---- 版本兼容性: config 里若带 version 字段, 不应高于当前运行版本 ----
    cfg_ver = data.get("version")
    if isinstance(cfg_ver, str) and cfg_ver:
        try:
            from packaging.version import Version  # type: ignore
            if Version(cfg_ver) > Version(__version__):
                findings.append(_f(
                    "config", "warn", f"配置版本 {cfg_ver} 高于当前 qxt {__version__}",
                    detail="可能来自更新版本; 建议 `qxt upgrade` 或降级配置。",
                    path=str(cfg_path),
                ))
        except Exception:  # noqa: BLE001 - packaging 可选 / 版本号解析失败
            pass

    return findings


# ------------------------------------------------------------------ 技能检查

def _parse_frontmatter(path: Path) -> Tuple[Dict[str, Any], str, Optional[str]]:
    """读取技能文件, 返回 (meta_dict, body, error)。error 非 None 表示解析失败。"""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {}, "", f"读取失败: {exc}"
    m = _FRONT_RE.match(text)
    if not m:
        return {}, text, "缺少 YAML frontmatter (开头应为 --- )"
    fm_text = m.group(1)
    body = text[m.end():]
    try:
        import yaml
        meta = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        return {}, body, f"frontmatter YAML 语法错误: {str(exc).splitlines()[0]}"
    if not isinstance(meta, dict):
        return {}, body, "frontmatter 顶层必须是映射"
    return meta, body, None


def _check_skills(home: Path, workspace: Path, fix: bool) -> List[Dict[str, Any]]:
    """扫描用户级 + 项目级技能目录, 校验每个 SKILL.md / *.md 技能的 frontmatter。"""
    findings: List[Dict[str, Any]] = []
    skill_dirs: List[Path] = [
        home / "skills",
        home / ".agents" / "skills",
        workspace / ".qxt" / "skills",
        workspace / ".agents" / "skills",
    ]
    seen_slugs: Dict[str, Path] = {}
    scanned = 0
    for d in skill_dirs:
        if not d.is_dir():
            continue
        # 单文件技能: <dir>/<slug>.md
        for md in sorted(d.glob("*.md")):
            scanned += 1
            findings.extend(_check_one_skill(md, seen_slugs, fix))
        # 目录型技能包: <dir>/<slug>/SKILL.md
        for child in sorted(p for p in d.iterdir() if p.is_dir()):
            sk = child / "SKILL.md"
            if sk.exists():
                scanned += 1
                findings.extend(_check_one_skill(sk, seen_slugs, fix))

    if scanned == 0:
        findings.append(_f("skills", "ok", "未发现用户/项目技能 (正常, 可后续用 / 蒸馏沉淀)"))
    else:
        findings.append(_f("skills", "ok", f"共扫描 {scanned} 个技能文件"))
    return findings


def _check_one_skill(path: Path, seen_slugs: Dict[str, Path], fix: bool) -> List[Dict[str, Any]]:
    """校验单个技能文件: name/description 必填, 正文非空, slug 不重复。"""
    out: List[Dict[str, Any]] = []
    slug = path.parent.name if path.name == "SKILL.md" else path.stem
    meta, body, err = _parse_frontmatter(path)
    rel = str(path)

    if err:
        out.append(_f("skills", "error", f"技能 {slug}: {err}", path=rel))
        return out

    # 重复 slug
    if slug in seen_slugs:
        out.append(_f(
            "skills", "warn", f"技能 slug 重复: {slug}",
            detail=f"{seen_slugs[slug]} 与 {rel} 同名, 后者被忽略。",
            path=rel,
        ))
    else:
        seen_slugs[slug] = path

    missing = [k for k in ("name", "description") if not str(meta.get(k, "")).strip()]
    if missing:
        out.append(_f(
            "skills", "error", f"技能 {slug}: frontmatter 缺少必填字段 {', '.join(missing)}",
            detail="必填: name, description。",
            path=rel, fixable=True,
        ))
        if fix:
            fixed = _fix_skill_frontmatter(path, meta, missing)
            if fixed:
                out[-1] = {**out[-1], "status": "warn", "fixed": True,
                           "message": f"技能 {slug}: 已补占位字段 {', '.join(missing)} (请改成真实内容)"}
    elif not body.strip():
        out.append(_f("skills", "warn", f"技能 {slug}: 正文为空", path=rel))
    else:
        out.append(_f("skills", "ok", f"技能 {slug}: frontmatter 合法", path=rel))
    return out


def _fix_skill_frontmatter(path: Path, meta: Dict[str, Any], missing: List[str]) -> bool:
    """给缺字段的技能 frontmatter 补占位值 (安全可逆: 仅追加行, 不改正文)。"""
    try:
        text = path.read_text(encoding="utf-8")
        m = _FRONT_RE.match(text)
        if not m:
            return False
        lines = m.group(1).splitlines()
        for key in missing:
            placeholder = f"TODO-{key}"
            lines.append(f"{key}: {placeholder}")
        new_fm = "\n".join(lines)
        new_text = text[:m.start(1)] + new_fm + text[m.end(1):]
        path.write_text(new_text, encoding="utf-8")
        return True
    except OSError:
        return False


# ------------------------------------------------------------------ 项目指令检查

def _check_project_docs(workspace: Path) -> List[Dict[str, Any]]:
    """检查 QXT.md / AGENTS.md / CLAUDE.md 可读性 / 体积 / 编码。"""
    findings: List[Dict[str, Any]] = []
    found_any = False
    for name in _PROJECT_DOC_NAMES:
        p = workspace / name
        if not p.exists():
            continue
        found_any = True
        try:
            raw = p.read_bytes()
        except OSError as exc:
            findings.append(_f("project", "error", f"{name}: 无法读取 ({exc})", path=str(p)))
            continue
        size = len(raw)
        # 编码检测: 严格 UTF-8 解码, 失败即警告
        try:
            raw.decode("utf-8")
            enc_ok = True
        except UnicodeDecodeError:
            enc_ok = False
        item = _f("project", "ok", f"{name}: 可读 ({size} 字节)", path=str(p))
        if not enc_ok:
            item = _f("project", "warn", f"{name}: 非 UTF-8 编码",
                      detail="建议转存为 UTF-8 (无 BOM), 否则 Agent 可能误读。", path=str(p))
        elif size > _PROJECT_DOC_MAX:
            item = _f("project", "warn", f"{name}: 体积 {size//1024}KB 超过 32KB 建议上限",
                      detail="过长会占用上下文; 建议拆分或精简。", path=str(p))
        findings.append(item)
    if not found_any:
        findings.append(_f(
            "project", "ok", "未发现 QXT.md / AGENTS.md / CLAUDE.md (可用 /init 生成)",
            path=str(workspace),
        ))
    return findings


# ------------------------------------------------------------------ 环境检查

def _check_env(home: Path, workspace: Path, fix: bool) -> List[Dict[str, Any]]:
    """Python 版本 / git / 工作区可写 / venv 检测。"""
    findings: List[Dict[str, Any]] = []

    # Python 版本 >= 3.10
    v = sys.version_info
    if v >= (3, 10):
        findings.append(_f("env", "ok", f"Python {v.major}.{v.minor}.{v.micro} (≥3.10)"))
    else:
        findings.append(_f(
            "env", "error", f"Python {v.major}.{v.minor} 过低",
            detail="qxt 需要 Python ≥ 3.10, 请升级解释器。",
        ))

    # git 可用性
    import shutil
    git_path = shutil.which("git")
    if git_path:
        findings.append(_f("env", "ok", f"git 可用 ({git_path})"))
    else:
        findings.append(_f(
            "env", "warn", "未检测到 git",
            detail="版本感知 / /diff / /undo 等功能需要 git; 建议安装 Git for Windows。",
        ))

    # 工作区可写
    probe = workspace / ".qxt_write_probe"
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        findings.append(_f("env", "ok", f"工作区可写 ({workspace})"))
    except OSError as exc:
        findings.append(_f("env", "error", f"工作区不可写: {exc}", path=str(workspace)))

    # venv 检测
    in_venv = bool(os.environ.get("VIRTUAL_ENV"))
    if in_venv:
        findings.append(_f("env", "ok", f"运行于虚拟环境 ({os.environ['VIRTUAL_ENV']})"))
    else:
        findings.append(_f("env", "warn", "未检测到虚拟环境 (VIRTUAL_ENV 未设置)",
                           detail="建议在项目 venv 内运行, 避免污染全局解释器。"))

    # --fix: 确保 home 与 skills 目录存在
    if fix:
        created = []
        for d in (home, home / "skills", home / ".agents"):
            if not d.exists():
                try:
                    d.mkdir(parents=True, exist_ok=True)
                    created.append(str(d))
                except OSError:
                    pass
        if created:
            findings.append(_f("env", "ok", f"--fix: 已创建缺失目录 {len(created)} 个",
                               detail="; ".join(created)))
    return findings


# ------------------------------------------------------------------ 缓存自检

def _check_cache(home: Path) -> List[Dict[str, Any]]:
    """system prompt 稳定段哈希 + 记忆存储可读写。"""
    findings: List[Dict[str, Any]] = []

    # system prompt 稳定段哈希: 取 prompts 模块里"稳定前缀"的可导入入口;
    # 若 prompts.py 尚未显式分段 (差距分析 A1), 则退化为对整个 prompts 源码做哈希,
    # 仅证明它可被导入且哈希稳定, 不报错。
    try:
        from ..core import prompts as _prompts  # noqa: PLC0415
        src = getattr(_prompts, "__file__", None)
        if src and Path(src).exists():
            digest = hashlib.sha256(Path(src).read_bytes()).hexdigest()[:12]
            findings.append(_f(
                "cache", "ok", f"system prompt 模块可导入 (sha256:{digest})",
                detail="稳定段缓存边界见 docs/gap_analysis (A1)。",
            ))
        else:
            findings.append(_f("cache", "ok", "system prompt 模块可导入"))
    except Exception as exc:  # noqa: BLE001
        findings.append(_f("cache", "warn", f"system prompt 模块导入失败: {exc}"))

    # 记忆存储可读写: 在 home 下写一个探针文件
    mem_dir = home / "memory"
    probe = mem_dir / ".doctor_probe"
    try:
        mem_dir.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        back = probe.read_text(encoding="utf-8")
        probe.unlink()
        if back == "ok":
            findings.append(_f("cache", "ok", f"记忆存储可读写 ({mem_dir})"))
        else:
            findings.append(_f("cache", "error", "记忆存储读写不一致", path=str(mem_dir)))
    except OSError as exc:
        findings.append(_f("cache", "error", f"记忆存储不可写: {exc}", path=str(mem_dir)))
    return findings


# ------------------------------------------------------------------ 网络检查 (可选)

def _check_network(home: Path) -> List[Dict[str, Any]]:
    """--network: 探测已配置 API endpoint 的可达性。"""
    findings: List[Dict[str, Any]] = []
    cfg_path = home / "config.yaml"
    base_url = ""
    if cfg_path.exists():
        try:
            import yaml
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            model = data.get("model") or {}
            base_url = model.get("base_url") or ""
        except Exception:  # noqa: BLE001
            pass
    if not base_url:
        findings.append(_f("network", "warn", "未配置 model.base_url, 跳过网络探测"))
        return findings
    try:
        import ssl
        import urllib.request
        t0 = time.time()
        req = urllib.request.Request(base_url, method="HEAD")
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=4, context=ctx) as resp:
            resp.read()
        ms = (time.time() - t0) * 1000
        findings.append(_f("network", "ok", f"{base_url} 可达 ({ms:.0f}ms)"))
    except Exception as exc:  # noqa: BLE001
        findings.append(_f("network", "warn", f"{base_url} 不可达: {exc}",
                           detail="检查代理 / --offline / 网络连接。"))
    return findings


# ------------------------------------------------------------------ 主编排

def run_checks(workspace: Optional[Path] = None, *, fix: bool = False,
               network: bool = False, home: Optional[Path] = None) -> List[Dict[str, Any]]:
    """运行全部诊断, 返回结构化 findings (纯函数, 不打印)。"""
    home = Path(home) if home else home_dir()
    workspace = Path(workspace) if workspace else Path.cwd()
    findings: List[Dict[str, Any]] = []
    findings += _check_config(home, fix)
    findings += _check_skills(home, workspace, fix)
    findings += _check_project_docs(workspace)
    findings += _check_env(home, workspace, fix)
    findings += _check_cache(home)
    if network:
        findings += _check_network(home)
    return findings


def _exit_code(findings: List[Dict[str, Any]]) -> int:
    """0=全部通过, 1=有警告, 2=有错误。"""
    if any(f["status"] == "error" for f in findings):
        return 2
    if any(f["status"] == "warn" for f in findings):
        return 1
    return 0


# ------------------------------------------------------------------ 输出渲染

_MARK = {"ok": ("✅", "green"), "warn": ("⚠️", "yellow"), "error": ("❌", "red")}


def _render_rich(findings: List[Dict[str, Any]]) -> None:
    """用 rich 表格 + 颜色标记打印报告。"""
    from rich.console import Console
    from rich.table import Table

    console = Console(highlight=False)
    console.print(f"\n[bold]青小团 doctor 诊断报告[/bold]  (qxt {__version__})")
    table = Table(show_header=True, header_style="bold", expand=True)
    table.add_column("状态", justify="center", width=4)
    table.add_column("分类", width=10)
    table.add_column("说明")
    table.add_column("路径", ratio=1, style="dim")
    for f in findings:
        mark, color = _MARK[f["status"]]
        text = f["message"]
        if f.get("fixed"):
            text += " [bold](已自动修复)[/bold]"
        elif f.get("detail"):
            text += f"\n  └─ {f['detail']}"
        table.add_row(
            f"[{color}]{mark}[/{color}]",
            f["category"],
            text,
            f.get("path", ""),
        )
    console.print(table)
    errs = sum(1 for f in findings if f["status"] == "error")
    warns = sum(1 for f in findings if f["status"] == "warn")
    if errs:
        console.print(f"\n[red]发现 {errs} 个错误, {warns} 个警告[/red]")
    elif warns:
        console.print(f"\n[yellow]发现 {warns} 个警告, 无错误[/yellow]")
    else:
        console.print("\n[green]全部通过 ✅[/green]")


def _render_json(findings: List[Dict[str, Any]]) -> int:
    import json
    payload = {
        "version": __version__,
        "exit_code": _exit_code(findings),
        "summary": {
            "ok": sum(1 for f in findings if f["status"] == "ok"),
            "warn": sum(1 for f in findings if f["status"] == "warn"),
            "error": sum(1 for f in findings if f["status"] == "error"),
        },
        "findings": findings,
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload["exit_code"]


# ------------------------------------------------------------------ CLI 入口

def cmd_doctor(args) -> int:
    """`qxt doctor` 入口: 运行诊断, 按 --json/--fix/--network 分发。"""
    fix = bool(getattr(args, "fix", False))
    as_json = bool(getattr(args, "json", False))
    network = bool(getattr(args, "network", False))
    workspace = getattr(args, "workspace", None) or os.getcwd()

    findings = run_checks(Path(workspace), fix=fix, network=network)
    if as_json:
        return _render_json(findings)
    _render_rich(findings)
    return _exit_code(findings)
