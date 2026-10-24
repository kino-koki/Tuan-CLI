"""文件系统工具插件: 读 / 写 / 改 / 移动 / 删除 / 列目录 / 搜索 / glob。

补充的 Agent 核心能力 (对比原版):
- glob: 按通配符批量定位文件 (Agent 探索仓库的常用入口)。
- move_file / rename: 重命名与移动 (跨文件重构必备)。
- delete_file: 删除单文件 (危险, 需确认; YOLO 下自动批准)。
write_file 本身在 YOLO 下属于高风险写入, 也标记为 dangerous 以便统一管控。
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from ..core.kernel import Kernel, Plugin
from .base import Tool, ToolContext, string_prop
from ..ext.write_scan import scan_content_for_danger, format_matches_for_user, _resolve_path_for_warning

MAX_READ_CHARS = 40000
# read_files 单文件大小上限 (字节)。可经 tools.read_files.max_bytes 覆盖。
DEFAULT_MAX_READ_BYTES = 200 * 1024


def _atomic_write_text(path: Path, content: str) -> None:
    """原子写: 同目录临时文件 + fsync + os.replace, 崩溃不留半截文件。

    保留目标文件的既有权限位 (源码/脚本的可执行位不能被替换掉),
    新文件 (目标不存在) 用默认 0644 & umask。
    """
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            try:
                os.chmod(tmp_name, stat.S_IMODE(path.stat().st_mode))
            except OSError:
                pass
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _resolve(ctx: ToolContext, path: str) -> Path:
    workspace = Path(ctx.workspace).resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve()
    # 1) 工作区内: 原样放行 (既有行为, 缓存友好)
    try:
        resolved.relative_to(workspace)
        return resolved
    except ValueError:
        pass
    # 2) 工作区外: 仅当落在本会话经 /add-dir 显式授权的目录内才放行。
    #    授权为空时这里什么都不做, 行为与改动前完全一致 (越界仍被拦截)。
    for allowed in _extra_allowed_roots(ctx):
        try:
            resolved.relative_to(allowed)
            return resolved
        except ValueError:
            continue
    raise ValueError(
        f"路径必须位于工作区内: {path}"
        " (如需访问工作区外目录, 请先在 REPL 内用 /add-dir <路径> 显式授权)"
    ) from None


def _rel(ctx: ToolContext, p: Path) -> str:
    try:
        return str(p.relative_to(ctx.workspace))
    except ValueError:
        return str(p)


# ------------------------------------------------------------------ 额外目录授权 (/add-dir)
# 对标 Claude Code /add-dir: 把工作区外的目录显式纳入本会话"可读上下文"。
#
# 安全模型 (任一被破坏即视为事故):
#   - 只能由用户在 REPL 内显式 /add-dir 授权; Agent 自身没有 add_dir 工具, 不能自助授权。
#   - 拒绝不存在路径、非目录, 以及系统关键目录 (盘符根 / Windows 目录 / POSIX 系统目录)。
#   - 授权为 per-session 内存态 (挂在 ctx 上), 不落盘、不写入 config, 重启会话即失效,
#     从根本上避免"授权目录列表落盘泄露"。
#   - 授权仅放宽 _resolve 的"必须在工作区内"约束; 写操作 (write/edit/delete/move) 仍走
#     既有 dangerous 确认 + Read-before-Edit 守卫, 不因授权而绕过。

EXTRA_DIRS_ATTR = "extra_allowed_dirs"


def _extra_allowed_roots(ctx: ToolContext) -> list:
    """本会话已授权的额外目录 (resolve 后的绝对路径列表), 惰性读取。"""
    raw = getattr(ctx, EXTRA_DIRS_ATTR, None)
    if not raw:
        return []
    out: list = []
    for d in raw:
        try:
            out.append(Path(d).resolve())
        except OSError:
            continue
    return out


def _system_roots() -> list:
    """跨平台系统关键目录根 (用于拒绝 /add-dir 授权它们)。"""
    roots: list = []
    # POSIX 系统目录
    for p in ("/etc", "/bin", "/sbin", "/usr", "/boot", "/root", "/dev", "/proc", "/sys"):
        try:
            roots.append(Path(p))
        except Exception:  # noqa: BLE001
            pass
    # Windows: SystemRoot (通常 C:\Windows) 与 Program Files
    # (仅限 Windows, 避免在 POSIX 上产生无意义的相对路径)
    if os.name == "nt":
        sysroot = os.environ.get("SystemRoot") or r"C:\Windows"
        try:
            roots.append(Path(sysroot))
        except Exception:  # noqa: BLE001
            pass
        for p in (r"C:\Program Files", r"C:\Program Files (x86)"):
            try:
                roots.append(Path(p))
            except Exception:  # noqa: BLE001
                pass
    return roots


def _is_system_critical(target: Path) -> bool:
    """target 是否为文件系统根 (盘符根 / POSIX /) 或位于某个系统关键目录之内。"""
    try:
        if str(target) == str(target.anchor):
            return True
    except Exception:  # noqa: BLE001
        pass
    for root in _system_roots():
        try:
            target.relative_to(root)  # 不抛 = target == root 或在其下
            return True
        except ValueError:
            continue
    return False


def authorize_extra_dir(ctx: ToolContext, path: str) -> str:
    """把工作区外目录加入本会话可读授权集 (仅用户经 /add-dir 调用)。返回结果消息。"""
    workspace = Path(ctx.workspace).resolve()
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    try:
        target = candidate.resolve()
    except OSError as exc:
        return f"[错误] 无法解析路径 {path}: {exc}"
    if not target.exists():
        return f"[错误] 目录不存在: {target}"
    if not target.is_dir():
        return f"[错误] 不是目录: {target}"
    # 工作区内本就可达, 无需授权 (也避免重复登记)
    try:
        target.relative_to(workspace)
        return f"该目录已在工作区内, 无需授权: {target}"
    except ValueError:
        pass
    if _is_system_critical(target):
        return f"[错误] 拒绝授权系统关键目录 (安全限制): {target}"
    existing = getattr(ctx, EXTRA_DIRS_ATTR, None)
    if existing is None:
        existing = []
        setattr(ctx, EXTRA_DIRS_ATTR, existing)
    norm = str(target)
    if norm in existing:
        return f"已在授权列表中: {target}"
    existing.append(norm)
    return f"已授权目录 (本会话可读): {target}"


def list_extra_dirs(ctx: ToolContext) -> list:
    """当前本会话已授权的额外目录列表 (/add-dir 无参时展示)。"""
    return list(getattr(ctx, EXTRA_DIRS_ATTR, None) or [])


def glob(ctx: ToolContext, pattern: str, path: str = ".") -> str:
    """按 glob 通配符匹配文件 (如 '**/*.py', 'src/**/*.ts')。"""
    root = _resolve(ctx, path)
    if not root.exists():
        return f"[错误] 目录不存在: {root}"
    matches = sorted(p for p in root.glob(pattern) if p.is_file())
    if not matches:
        return f"未匹配到文件: {pattern}"
    lines = []
    for m in matches[:200]:
        lines.append(_rel(ctx, m))
    if len(matches) > 200:
        lines.append(f"...[共 {len(matches)} 个, 截断显示前 200]")
    return "\n".join(lines)


def move_file(ctx: ToolContext, src: str, dst: str) -> str:
    """移动或重命名文件/目录。"""
    s = _resolve(ctx, src)
    d = _resolve(ctx, dst)
    if not s.exists():
        return f"[错误] 源不存在: {s}"
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
    return f"已移动 {_rel(ctx, s)} -> {_rel(ctx, d)}"


def delete_file(ctx: ToolContext, path: str) -> str:
    """删除单个文件 (危险操作, 需确认)。"""
    p = _resolve(ctx, path)
    if not p.exists():
        return f"[错误] 文件不存在: {p}"
    if p.is_dir():
        return f"[错误] {p} 是目录, 请用 delete_dir"
    p.unlink()
    return f"已删除 {_rel(ctx, p)}"


def delete_dir(ctx: ToolContext, path: str) -> str:
    """递归删除整个目录 (极危险, 需确认, YOLO 仍建议保留红名单)。"""
    import shutil as _shutil

    p = _resolve(ctx, path)
    if not p.exists():
        return f"[错误] 目录不存在: {p}"
    if not p.is_dir():
        return f"[错误] {p} 不是目录"
    _shutil.rmtree(str(p))
    return f"已递归删除目录 {_rel(ctx, p)}"


def read_file(ctx: ToolContext, path: str, offset: int = 0, limit: int = 0) -> str:
    p = _resolve(ctx, path)
    if not p.exists():
        return f"[错误] 文件不存在: {p}"
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if offset:
        lines = lines[offset:]
    if limit:
        lines = lines[:limit]
    out = "\n".join(lines)
    if len(out) > MAX_READ_CHARS:
        out = out[:MAX_READ_CHARS] + f"\n...[截断, 全文 {len(text)} 字符]"
    # 记录为本会话已读, 供 Read-before-Edit 守卫放行后续 edit/write
    ctx.mark_read(str(p))
    return f"# {p}\n{out}"


# ------------------------------------------------------------------ 并行批量读 (read_files)
# 对标 Freebuff / Codebuff 的"快速并行读": 一次往返把 N 个文件并行拿回来,
# 省掉 N 次工具往返与 N 份系统提示开销; 单文件失败互不影响, 成功即计入已读。

def _read_one_file(ctx: ToolContext, path: str, offset: int, limit: int,
                   max_bytes: int) -> str:
    """并行读取单个文件, 返回 "=== <path> === ..." 块字符串。

    任何失败 (路径越界 / 不存在 / 超限 / 二进制 / 解码 / IO) 都收敛成该文件块内的
    错误标注, 绝不抛异常 —— 保证一个文件出错不拖垮整批其他文件。
    """
    header = f"=== {path} ==="
    try:
        p = _resolve(ctx, path)
    except Exception as exc:  # noqa: BLE001 - 越界路径等, 都收敛进块内
        return f"{header}\n[错误] 路径解析失败: {exc}"
    if not p.exists() or not p.is_file():
        return f"{header}\n[错误] 文件不存在: {p}"
    try:
        size = p.stat().st_size
    except OSError as exc:
        return f"{header}\n[错误] 无法读取文件状态: {exc}"
    if size > max_bytes:
        return (f"{header}\n[跳过] 文件过大 ({size} 字节 > 上限 {max_bytes} 字节), "
                f"请改用 read_file 配合 offset/limit 分段读取")
    try:
        raw = p.read_bytes()
    except OSError as exc:
        return f"{header}\n[错误] 读取失败: {exc}"
    # 二进制检测: 含 NUL 字节即视为二进制, 不读全文
    if b"\x00" in raw:
        return f"{header}\n[跳过] 二进制文件 (检测到 NUL 字节), 不读取文本内容"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if offset:
        lines = lines[offset:]
    if limit:
        lines = lines[:limit]
    out = "\n".join(lines)
    if len(out) > MAX_READ_CHARS:
        out = out[:MAX_READ_CHARS] + f"\n...[截断, 全文 {len(text)} 字符]"
    # 成功读取即记为已读, 满足后续 edit/write 的 Read-before-Edit 守卫
    ctx.mark_read(str(p))
    return f"{header}\n{out}"


def read_files(ctx: ToolContext, paths: list, offset: int = 0, limit: int = 0,
               max_workers: int = 8) -> str:
    """并行批量读多个文件 (对标 Freebuff/Codebuff 快速并行读)。

    - ThreadPoolExecutor 并行读取, 一次往返拿全文, 省往返、省 token;
    - 单文件大小上限 tools.read_files.max_bytes (默认 200KB), 超限只提示不读全文;
    - 含 NUL 字节的二进制文件跳过;
    - 单文件失败 (不存在/权限/编码) 只在该文件块标注错误, 不中断其他文件;
    - 每个成功读取的文件自动 mark_read, 放行后续 edit;
    - read_only=True, Plan 模式放行。
    """
    if not paths:
        return "[错误] paths 为空: 请提供至少一个文件路径"
    max_bytes = ctx.config("tools.read_files.max_bytes", DEFAULT_MAX_READ_BYTES)
    try:
        max_bytes = int(max_bytes)
    except (TypeError, ValueError):
        max_bytes = DEFAULT_MAX_READ_BYTES
    try:
        workers = max(1, int(max_workers or 8))
    except (TypeError, ValueError):
        workers = 8
    # 提前初始化已读集合, 避免多线程并发惰性建 set 时互相覆盖
    if ctx.read_files is None:
        ctx.read_files = set()
    blocks: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_read_one_file, ctx, path, offset, limit, max_bytes)
                   for path in paths]
        for fut in futures:
            try:
                blocks.append(fut.result())
            except Exception as exc:  # noqa: BLE001 - worker 理论上不抛, 兜底保整批不炸
                blocks.append(f"=== (未知) ===\n[错误] 读取任务异常: {exc}")
    return "\n\n".join(blocks)


# ------------------------------------------------------------------ Read-before-Edit 守卫
# 对标 Kimi Code v0.38.0 "Edit/Write must Read first": 未先 read 就改/覆盖既有文件一律拦截。
# 通过配置 tools.require_read_before_edit: false 关闭 (默认开启)。

def _guard_enabled(ctx: ToolContext) -> bool:
    v = ctx.config("tools.require_read_before_edit", True)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def _read_before_edit_blocked(ctx: ToolContext, p: Path) -> Optional[str]:
    """返回非空错误串表示应拦截; None 表示放行。

    - edit_file 目标必然存在, 一律要求先 read;
    - write_file 仅当文件已存在 (覆盖) 时要求先 read, 新建文件放行。
    """
    if not _guard_enabled(ctx):
        return None
    if ctx.has_read(str(p)):
        return None
    return (f"[错误] 请先 read_file 读取该文件后再编辑: {_rel(ctx, p)}\n"
            "(Read-before-Edit 守卫; 如需关闭可设 tools.require_read_before_edit: false)")


# ------------------------------------------------------------------ diff 预览

def _unified_diff_text(old: str, new: str, p: Path, n: int = 3) -> str:
    """生成 unified diff 文本 (对标 Claude Code /diff 面板), 不写盘。"""
    import difflib
    lines = list(difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=f"a/{p.name}", tofile=f"b/{p.name}", lineterm="", n=n,
    ))
    if not lines:
        return "(无差异)"
    body = lines[:200]
    more = len(lines) - len(body)
    text = "\n".join(body)
    if more > 0:
        text += f"\n...[diff 共 {len(lines)} 行, 截断显示前 {len(body)} 行]"
    return text


def _apply_replacements(text: str, replacements: list) -> tuple:
    """按序应用多组替换。返回 (new_text, errors)。

    任一组 old_string 未找到或不唯一即记错误; 全部成功时 new_text 为替换后全文。
    调用方据此决定是否写盘 —— 任一失败则整体回滚 (不写)。
    """
    working = text
    errors: list[str] = []
    for i, rep in enumerate(replacements):
        old = rep.get("old_string", "") if isinstance(rep, dict) else ""
        new = rep.get("new_string", "") if isinstance(rep, dict) else ""
        if not old:
            errors.append(f"第 {i + 1} 组: old_string 为空")
            continue
        count = working.count(old)
        if count == 0:
            errors.append(f"第 {i + 1} 组: old_string 未找到")
        elif count > 1:
            errors.append(f"第 {i + 1} 组: old_string 出现 {count} 次, 不唯一, 请扩大上下文")
        else:
            working = working.replace(old, new, 1)
    return working, errors


def _normalize_replacements(old_string, new_string, replacements) -> Optional[list]:
    """统一为 replacements 列表; 两种调用方式缺一不可时返回 None (由调用方报错)。"""
    if replacements is not None:
        return list(replacements)
    if old_string is not None and new_string is not None:
        return [{"old_string": old_string, "new_string": new_string}]
    return None


def write_file(ctx: ToolContext, path: str, content: str) -> str:
    p = _resolve(ctx, path)
    # 覆盖既有文件前要求先读; 新建文件放行
    if p.exists():
        blocked = _read_before_edit_blocked(ctx, p)
        if blocked is not None:
            return blocked

    # 写入前扫描: 检测是否包含危险命令
    is_dangerous, matches = scan_content_for_danger(content)
    if is_dangerous:
        warning = format_matches_for_user(matches)
        return f"[已拒绝] 文件 {p} 包含危险内容:\n{warning}"

    _atomic_write_text(p, content)
    return f"已写入 {p} ({len(content)} 字符)"


def edit_file(ctx: ToolContext, path: str, old_string: Optional[str] = None,
              new_string: Optional[str] = None,
              replacements: Optional[list] = None) -> str:
    """精确替换文本 (支持单组与 multi-cut 多组替换)。

    - 单组: edit_file(path, old_string, new_string)
    - 多组: edit_file(path, replacements=[{old_string, new_string}, ...])
    多组按顺序应用; 任一组未找到或不唯一则整体回滚 (不写入)。
    """
    p = _resolve(ctx, path)
    if not p.exists():
        return f"[错误] 文件不存在: {p}"
    blocked = _read_before_edit_blocked(ctx, p)
    if blocked is not None:
        return blocked
    reps = _normalize_replacements(old_string, new_string, replacements)
    if reps is None:
        return "[错误] 需提供 old_string/new_string 或 replacements 之一"
    text = p.read_text(encoding="utf-8")
    new_text, errors = _apply_replacements(text, reps)
    if errors:
        return ("[错误] 多组替换未全部通过, 已整体回滚 (未写入):\n" + "\n".join(errors))

    # 写入前扫描: 检测新内容是否包含危险命令
    is_dangerous, matches = scan_content_for_danger(new_text)
    if is_dangerous:
        warning = format_matches_for_user(matches)
        return f"[已拒绝] 文件 {p} 包含危险内容:\n{warning}"

    _atomic_write_text(p, new_text)
    diff = _unified_diff_text(text, new_text, p)
    n = len(reps)
    header = f"已修改 {p} ({n} 处替换)" if n > 1 else f"已修改 {p}"
    return f"{header}\n已应用变更, diff 如下:\n{diff}"


def diff_preview(ctx: ToolContext, path: str, old_string: Optional[str] = None,
                 new_string: Optional[str] = None,
                 replacements: Optional[list] = None) -> str:
    """预览对文件执行替换后的 unified diff, 不实际修改文件 (对标 Claude Code /diff 面板)。"""
    p = _resolve(ctx, path)
    if not p.exists():
        return f"[错误] 文件不存在: {p}"
    reps = _normalize_replacements(old_string, new_string, replacements)
    if reps is None:
        return "[错误] 需提供 old_string/new_string 或 replacements 之一"
    text = p.read_text(encoding="utf-8")
    new_text, errors = _apply_replacements(text, reps)
    if errors:
        return "[错误] 无法生成预览 (替换无法全部应用, 文件未改动):\n" + "\n".join(errors)
    diff = _unified_diff_text(text, new_text, p)
    return f"diff 预览 (未修改文件 {_rel(ctx, p)}):\n{diff}"


# ------------------------------------------------------------------ 事务性多文件编辑 (edit_files)
# 对标 Freebuff / Codebuff 的"批量事务写": 先把 N 个文件的全部改动在内存里校验完,
# 任何一处不匹配就一个字节都不落盘; 全部通过才逐文件原子写。省多次往返, 且不留半改状态。

def _normalize_edit_item_reps(item) -> tuple:
    """解析 edit_files 的单个编辑项。

    返回 (path, reps, error):
    - reps 统一为 [{"old_string", "new_string"}, ...] (兼容 replacements 项的 old/new 短键
      与 edit_file 的 old_string/new_string 长键);
    - 调用方式缺失 (old/new 与 replacements 都没给) 时 error 非空, 由事务层汇总。
    """
    if not isinstance(item, dict):
        return None, None, "item 不是对象"
    path = item.get("path")
    if not path:
        return None, None, "缺少 path"
    replacements = item.get("replacements")
    if replacements is not None:
        reps = []
        for r in replacements:
            if isinstance(r, dict):
                old = r.get("old", r.get("old_string"))
                new = r.get("new", r.get("new_string"))
            else:
                old = new = None
            reps.append({"old_string": old, "new_string": new})
        return path, reps, None
    old_string = item.get("old_string")
    new_string = item.get("new_string")
    if old_string is not None and new_string is not None:
        return path, [{"old_string": old_string, "new_string": new_string}], None
    return path, None, "需提供 old_string/new_string 或 replacements 之一"


def edit_files(ctx: ToolContext, items: list) -> str:
    """多文件事务性编辑 (对标 Freebuff/Codebuff 批量事务写)。

    items: 每项 {path, old_string?, new_string?, replacements?: [{old,new}]};
           old/new 单组 与 replacements 多组二选一。
    两阶段事务:
      (1) 校验全部 —— 逐文件过 Read-before-Edit 守卫, 且每组 old 在文件中存在且唯一;
          任一失败 → 整体拒绝并列出全部失败点, 不写任何文件;
      (2) 全部通过 —— 逐文件 _atomic_write_text 原子写, 返回每文件 unified diff 摘要。
    """
    if not items:
        return "[错误] items 为空: 请提供至少一个编辑项"

    # ---- 阶段 1: 全部校验 (只在内存里算, 不落盘) ----
    prepared: list[tuple] = []   # (path, p, old_text, new_text, n_reps)
    failures: list[str] = []      # 收集全部失败点, 一次性报出
    for idx, item in enumerate(items):
        tag = f"第 {idx + 1} 项"
        shown = item.get("path") if isinstance(item, dict) else "?"
        path, reps, nerr = _normalize_edit_item_reps(item)
        if nerr is not None:
            failures.append(f"{tag} ({shown}): {nerr}")
            continue
        try:
            p = _resolve(ctx, path)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{tag} ({path}): 路径解析失败: {exc}")
            continue
        if not p.exists() or not p.is_file():
            failures.append(f"{tag} ({path}): 文件不存在: {p}")
            continue
        blocked = _read_before_edit_blocked(ctx, p)
        if blocked is not None:
            failures.append(f"{tag} ({path}): {blocked}")
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            failures.append(f"{tag} ({path}): UTF-8 解码失败: {exc}")
            continue
        except OSError as exc:
            failures.append(f"{tag} ({path}): 读取失败: {exc}")
            continue
        new_text, errors = _apply_replacements(text, reps)
        if errors:
            failures.append(f"{tag} ({path}): " + "; ".join(errors))
            continue
        prepared.append((path, p, text, new_text, len(reps)))

    if failures:
        return ("[错误] edit_files 事务校验未全部通过, 已整体拒绝 (未写入任何文件):\n"
                + "\n".join(f"  - {f}" for f in failures))

    # ---- 阶段 2: 全部通过, 逐文件原子落盘 ----
    results: list[str] = []
    for path, p, old_text, new_text, n in prepared:
        # 写入前扫描: 检测是否包含危险命令
        is_dangerous, matches = scan_content_for_danger(new_text)
        if is_dangerous:
            warning = format_matches_for_user(matches)
            return (f"[已拒绝] 文件 {_rel(ctx, p)} 包含危险内容:\n{warning}\n\n"
                    f"edit_files 事务已整体拒绝 (未写入任何文件)。")

        _atomic_write_text(p, new_text)
        diff = _unified_diff_text(old_text, new_text, p)
        header = f"已修改 {_rel(ctx, p)} ({n} 处替换)" if n > 1 else f"已修改 {_rel(ctx, p)}"
        results.append(f"{header}\n{diff}")
    return f"edit_files 事务成功, 共修改 {len(prepared)} 个文件:\n\n" + "\n\n".join(results)


def list_dir(ctx: ToolContext, path: str = ".", depth: int = 2) -> str:
    root = _resolve(ctx, path)
    if not root.is_dir():
        return f"[错误] 目录不存在: {root}"
    lines: list[str] = []
    max_depth = min(depth, 4)
    for current, dirs, files in os.walk(root):
        rel = Path(current).relative_to(root)
        level = len(rel.parts)
        if level >= max_depth:
            dirs[:] = []
        dirs[:] = [d for d in sorted(dirs) if not d.startswith(".") and d != "__pycache__"]
        indent = "  " * level
        name = "." if str(rel) == "." else rel.name + "/"
        lines.append(f"{indent}{name}")
        for f in sorted(files)[:50]:
            lines.append(f"{indent}  {f}")
        if len(lines) > 400:
            lines.append("...[截断]")
            break
    return "\n".join(lines)


def search_files(ctx: ToolContext, pattern: str, path: str = ".") -> str:
    import re

    root = _resolve(ctx, path)
    if not root.is_dir():
        return f"[错误] 目录不存在: {root}"
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"[错误] 正则表达式无效: {exc}"
    hits: list[str] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__" and d != "node_modules"]
        for fname in files:
            fpath = Path(current) / fname
            try:
                for i, line in enumerate(fpath.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if regex.search(line):
                        hits.append(f"{fpath.relative_to(root)}:{i}: {line.strip()[:160]}")
                        if len(hits) >= 100:
                            return "\n".join(hits) + "\n...[超过 100 条, 截断]"
            except OSError:
                continue
    return "\n".join(hits) if hits else "未找到匹配内容"


class FilesystemPlugin(Plugin):
    name = "tools.filesystem"
    provides = []
    requires = ["tool_registry"]

    def activate(self, kernel: Kernel) -> None:
        registry = kernel.require("tool_registry")
        registry.register(Tool(
            name="read_file",
            description="读文件内容, 大文件用 offset/limit 分段",
            parameters={
                "type": "object",
                "properties": {
                    "path": string_prop("文件路径"),
                    "offset": {"type": "integer", "description": "起始行 (可选)"},
                    "limit": {"type": "integer", "description": "读取行数 (可选)"},
                },
                "required": ["path"],
            },
            handler=read_file, group="filesystem", read_only=True,
        ))
        registry.register(Tool(
            name="read_files",
            description="并行批量读取多个文件, 一次往返拿回全文, 省多次工具往返、省 token "
                        "(对标 Freebuff/Codebuff 快速并行读)。ThreadPoolExecutor 并行; "
                        "单文件超过 tools.read_files.max_bytes(默认 200KB) 只提示不读全文, 请改用 read_file 分段; "
                        "检测到 NUL 字节的二进制文件跳过; 单个文件失败(不存在/权限/编码)只在该块标注错误, "
                        "不中断其他文件; 每个成功读取的文件自动记为已读, 放行后续 edit。",
            parameters={
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "description": "要读取的文件路径列表",
                        "items": string_prop("文件路径"),
                    },
                    "offset": {"type": "integer", "description": "每个文件统一的起始行 (可选)"},
                    "limit": {"type": "integer", "description": "每个文件统一的读取行数 (可选)"},
                    "max_workers": {"type": "integer", "description": "并行线程数, 默认 8"},
                },
                "required": ["paths"],
            },
            handler=read_files, group="filesystem", read_only=True,
        ))
        registry.register(Tool(
            name="write_file",
            description="创建或覆盖文件",
            parameters={
                "type": "object",
                "properties": {
                    "path": string_prop("文件路径"),
                    "content": string_prop("完整内容"),
                },
                "required": ["path", "content"],
            },
            handler=write_file, group="filesystem", dangerous=True,
        ))
        registry.register(Tool(
            name="edit_file",
            description="精确替换文本, old_string 须唯一。两种方式: "
                        "(1) old_string/new_string 单组替换; "
                        "(2) replacements=[{old_string,new_string},...] 多组按序替换, "
                        "任一组未找到或不唯一则整体回滚不写入。覆盖已存在文件前须先 read_file。",
            parameters={
                "type": "object",
                "properties": {
                    "path": string_prop("文件路径"),
                    "old_string": string_prop("被替换原文 (单组方式)"),
                    "new_string": string_prop("新文本 (单组方式)"),
                    "replacements": {
                        "type": "array",
                        "description": "多组替换列表, 每项 {old_string, new_string} (multi-cut)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_string": string_prop("被替换原文"),
                                "new_string": string_prop("新文本"),
                            },
                            "required": ["old_string", "new_string"],
                        },
                    },
                },
                "required": ["path"],
            },
            handler=edit_file, group="filesystem", dangerous=True,
        ))
        registry.register(Tool(
            name="edit_files",
            description="多文件事务性编辑: 全部校验通过才落盘, 任一不匹配整体拒绝 (对标 Freebuff/Codebuff 批量事务写)。"
                        "items 每项 {path, old_string?, new_string?, replacements?: [{old,new}]}; "
                        "old/new 单组 与 replacements 多组二选一。两阶段: (1) 逐文件过 Read-before-Edit 守卫, "
                        "且每组 old 在文件中存在且唯一; 任一失败 → 整体拒绝并列出全部失败点, 不写任何文件; "
                        "(2) 全部通过 → 逐文件原子写, 返回每文件 unified diff 摘要。",
            parameters={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "编辑项列表, 每项 {path, old_string?, new_string?, replacements?}",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": string_prop("文件路径"),
                                "old_string": string_prop("被替换原文 (单组方式)"),
                                "new_string": string_prop("新文本 (单组方式)"),
                                "replacements": {
                                    "type": "array",
                                    "description": "多组替换列表, 每项 {old, new} (亦兼容 {old_string,new_string})",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "old": string_prop("被替换原文"),
                                            "new": string_prop("新文本"),
                                            "old_string": string_prop("被替换原文 (兼容 edit_file 写法)"),
                                            "new_string": string_prop("新文本 (兼容 edit_file 写法)"),
                                        },
                                    },
                                },
                            },
                            "required": ["path"],
                        },
                    },
                },
                "required": ["items"],
            },
            handler=edit_files, group="filesystem",
        ))
        registry.register(Tool(
            name="diff_preview",
            description="预览对文件执行替换后的 unified diff, 不实际修改文件 "
                        "(对标 Claude Code /diff 面板)。支持单组 old_string/new_string "
                        "或 replacements 多组。",
            parameters={
                "type": "object",
                "properties": {
                    "path": string_prop("文件路径"),
                    "old_string": string_prop("被替换原文 (单组方式)"),
                    "new_string": string_prop("新文本 (单组方式)"),
                    "replacements": {
                        "type": "array",
                        "description": "多组替换列表, 每项 {old_string, new_string}",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_string": string_prop("被替换原文"),
                                "new_string": string_prop("新文本"),
                            },
                            "required": ["old_string", "new_string"],
                        },
                    },
                },
                "required": ["path"],
            },
            handler=diff_preview, group="filesystem", read_only=True,
        ))
        registry.register(Tool(
            name="list_dir",
            description="树形列出目录",
            parameters={
                "type": "object",
                "properties": {
                    "path": string_prop("目录, 默认工作区"),
                    "depth": {"type": "integer", "description": "深度, 默认 2"},
                },
                "required": [],
            },
            handler=list_dir, group="filesystem", read_only=True,
        ))
        registry.register(Tool(
            name="search_files",
            description="正则搜索文件内容",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": string_prop("正则"),
                    "path": string_prop("根目录, 默认工作区"),
                },
                "required": ["pattern"],
            },
            handler=search_files, group="filesystem", read_only=True,
        ))
        registry.register(Tool(
            name="glob",
            description="按通配符批量定位文件, 如 '**/*.py'",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": string_prop("glob 模式"),
                    "path": string_prop("根目录, 默认工作区"),
                },
                "required": ["pattern"],
            },
            handler=glob, group="filesystem", read_only=True,
        ))
        registry.register(Tool(
            name="move_file",
            description="移动或重命名文件/目录",
            parameters={
                "type": "object",
                "properties": {
                    "src": string_prop("源路径"),
                    "dst": string_prop("目标路径"),
                },
                "required": ["src", "dst"],
            },
            handler=move_file, group="filesystem", dangerous=True,
        ))
        registry.register(Tool(
            name="delete_file",
            description="删除单个文件 (不可逆, 需确认)",
            parameters={
                "type": "object",
                "properties": {
                    "path": string_prop("文件路径"),
                },
                "required": ["path"],
            },
            handler=delete_file, group="filesystem", dangerous=True,
        ))
        registry.register(Tool(
            name="delete_dir",
            description="递归删除整个目录 (极危险, 需确认)",
            parameters={
                "type": "object",
                "properties": {
                    "path": string_prop("目录路径"),
                },
                "required": ["path"],
            },
            handler=delete_dir, group="filesystem", dangerous=True,
        ))
