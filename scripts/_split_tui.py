#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性脚本: 完成 tui.py QxtTUI 的 mixin 拆分接线 (Task: god-class split)。

背景: layout/state/render 三个 mixin 模块此前已按「逐行原样迁移」创建, 但
QxtTUI 从未继承它们 (class QxtTUI: 无基类), 147 个方法仍全部留在 tui.py ——
三份 mixin 是死代码, 且其中 12 个方法与 tui.py 漂移 (mixin 里的草稿甚至引用了
不存在的 _slogan_stream_started 等方法)。

本脚本以 tui.py 为唯一真源:
  1. 用 tui.py 的当前版本覆写 state/render/layout 中漂移的方法副本;
  2. 把剩余 45 个方法逐字抽到 5 个新 mixin 模块
     (interact/slashmenu/panels/slogan/lifecycle), 并按既有模式生成
     类级属性/跨 mixin 方法声明 (供 mypy 解析);
  3. 从 QxtTUI 删除全部已抽取方法, 类头改为继承全部 8 个 mixin;
  4. 静态校验: 每个新模块引用的模块级名字必须可解析 (common.__all__ /
     builtins / 显式 import), self.* 属性/方法必须有声明或在本模块定义。

纯 stdlib, 只读写本仓库文件; 幂等性不做保证, 请只跑一次。
"""
from __future__ import annotations

import ast
import builtins
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TUI = ROOT / "tuan_cli" / "tui"

# 剩余 45 个方法的目标归属 (module -> (classname, [methods]))
CLUSTERS: dict[str, tuple[str, list[str]]] = {
    "interact.py": ("InteractMixin", [
        "_set_clipboard", "_copy_last_answer", "_copy_last_user", "_build_keys",
        "_handle_enter", "_ask_move", "_wheel_owner", "_mouse_wheel",
    ]),
    "slashmenu.py": ("SlashMenuMixin", [
        "_on_input_changed", "_close_slash_menu", "_record_slash_usage",
        "_arg_completions", "_slash_move", "_slash_clamp_scroll",
        "_accept_slash", "_slash_menu_rows",
    ]),
    "panels.py": ("PanelsMixin", [
        "toggle_audit", "toggle_diff", "_fetch_diff", "_session_picker_open",
        "_task_browser_open", "_open_session_picker", "_sp_move",
        "_sp_toggle_scope", "_sp_accept", "_close_session_picker",
        "_open_task_browser", "_tb_move", "_tb_toggle_filter", "_tb_stop",
        "_tb_accept", "_close_task_browser", "toggle_mcp_status",
        "_help_overlay_rows", "_toggle_help",
    ]),
    "slogan.py": ("SloganMixin", [
        "_phase_of_context", "_slogan_dispatch", "slogan_for", "slogan_trace",
        "slogan_owner", "slogan_errors", "slogan_closed_trace",
        "_release_slogan_owner",
    ]),
    "lifecycle.py": ("LifecycleMixin", [
        "close", "_animate",
    ]),
}

EXISTING_MIXINS = ("state.py", "render.py", "layout.py")

MIXIN_IMPORTS = (
    "from .state import StateMixin\n"
    "from .render import RenderMixin\n"
    "from .layout import LayoutMixin\n"
    "from .interact import InteractMixin\n"
    "from .slashmenu import SlashMenuMixin\n"
    "from .panels import PanelsMixin\n"
    "from .slogan import SloganMixin\n"
    "from .lifecycle import LifecycleMixin\n"
)

MODULE_DOCSTRINGS = {
    "interact.py": "交互域: 键位绑定、剪贴板、Enter 提交、鼠标滚轮、确认/询问按键侧。",
    "slashmenu.py": "slash 命令面板域: 输入联动过滤、高亮滚动、参数补全、面板渲染。",
    "panels.py": "面板/浏览器域: 审计/Diff/MCP 面板开关、会话选择器、任务浏览器、帮助覆盖层。",
    "slogan.py": "运行时标语域: 标语分发、阶段判定、trace/封存快照。",
    "lifecycle.py": "生命周期域: 应用关闭与动画心跳。",
}

# 个别新模块需要的、不在 common.__all__ 里的模块级名字 (与 tui.py 顶部 import 同源)
EXTRA_IMPORTS: dict[str, str] = {
    "slogan.py": "from ..ui.slogans import mapping  # noqa: F401  (tui.py 顶部同名 import)\n",
    "lifecycle.py": "from ..ui.slogans import mapping  # noqa: F401  (tui.py 顶部同名 import)\n",
}


def line_starts(src: str) -> list[int]:
    starts = [0]
    for line in src.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    return starts


def node_span(src: str, starts: list[int], node: ast.AST) -> tuple[int, int]:
    """节点绝对字符区间 (含装饰器)。

    注意: ast 的 col_offset/end_col_offset 是 UTF-8 字节偏移, 而本文件大量
    中文注释/文档串, 必须换算回字符偏移再切片, 否则段会截断在多字节字符上。
    """
    lines = src.splitlines(keepends=True)

    def char_pos(lineno: int, byte_col: int) -> int:
        line = lines[lineno - 1]
        return starts[lineno - 1] + len(line.encode("utf-8")[:byte_col].decode("utf-8", errors="replace"))

    lineno, col = node.lineno, node.col_offset
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        for dec in getattr(node, "decorator_list", []):
            if dec.lineno < lineno or (dec.lineno == lineno and dec.col_offset < col):
                lineno, col = dec.lineno, dec.col_offset
    start = char_pos(lineno, col)
    end = char_pos(node.end_lineno, node.end_col_offset)
    return start, end


def class_methods(src: str, classname: str | None = None) -> dict[str, tuple[ast.AST, str]]:
    """返回 {方法名: (节点, 源码片段)}; 同名取后定义者。"""
    tree = ast.parse(src)
    starts = line_starts(src)
    out: dict[str, tuple[ast.AST, str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if classname is not None and node.name != classname:
            continue
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                s, e = node_span(src, starts, item)
                out[item.name] = (item, src[s:e])
    return out


def replace_in_file(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"{path.name}: 目标片段出现 {text.count(old)} 次, 预期 1 次"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def indent4(text: str) -> str:
    """每行前补 4 空格 (空行保持空), 用于把方法段放进类体/哑类。"""
    return "\n".join(("    " + l) if l.strip() else l for l in text.splitlines())


def parse_method(text: str) -> ast.AST:
    """解析单个类方法片段: 段从 def 关键字开始 (无缩进), 包一层哑类并补 4 空格。"""
    return ast.parse("class _W:\n" + indent4(text))


def parse_annotation(text: str) -> ast.AST:
    """解析类型注解表达式。"""
    return ast.parse(text, mode="eval")


def main() -> None:
    tui_path = TUI / "tui.py"
    src = tui_path.read_text(encoding="utf-8")
    qxt = class_methods(src, "QxtTUI")
    print(f"QxtTUI 方法数: {len(qxt)}")

    # ---- 1) 覆写既有 mixin 中漂移的方法副本 (以 tui.py 为真源; __init__ 除外) ----
    for mod in EXISTING_MIXINS:
        mpath = TUI / mod
        msrc = mpath.read_text(encoding="utf-8")
        mm = class_methods(msrc)
        drifted = [n for n in mm if n in qxt and n != "__init__"
                   and mm[n][1].strip() != qxt[n][1].strip()]
        for name in drifted:
            replace_in_file(mpath, mm[name][1], qxt[name][1])
            print(f"  覆写漂移方法: {mod}::{name}")
        if not drifted:
            print(f"  {mod}: 无漂移")

    # ---- 2) 计算尚未抽取的方法, 校验聚类覆盖 ----
    covered: set[str] = set()
    for mod in EXISTING_MIXINS:
        covered |= set(class_methods((TUI / mod).read_text(encoding="utf-8")))
    cluster_names = [n for _, (_c, names) in CLUSTERS.items() for n in names]
    rest = [n for n in qxt if n not in covered and n != "__init__"]
    missing = sorted(set(rest) - set(cluster_names))
    extra = sorted(set(cluster_names) - set(rest))
    assert not missing, f"未分配聚类的方法: {missing}"
    assert not extra, f"聚类里多出的方法: {extra}"
    print(f"待抽取到新模块的方法: {len(rest)}")

    # __init__ 中 self.X: T 的注解表 (供新模块生成类级属性声明)
    ann_map: dict[str, str] = {}
    init_node, _init_src = qxt["__init__"]
    for node in ast.walk(init_node):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Attribute) \
                and isinstance(node.target.value, ast.Name) and node.target.value.id == "self":
            ann_map[node.target.attr] = ast.unparse(node.annotation)

    # common.__all__ (新模块的命名空间来源)
    common_src = (TUI / "common.py").read_text(encoding="utf-8")
    ctree = ast.parse(common_src)
    common_all: set[str] = set()
    for node in ctree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            common_all = {elt.value for elt in node.value.elts}  # type: ignore[attr-defined]
    allowed = common_all | set(dir(builtins)) | {"annotations", "common"}

    # ---- 3) 生成 5 个新 mixin 模块 ----
    for mod, (clsname, names) in CLUSTERS.items():
        methods_src = [qxt[n][1] for n in names]
        # 收集 self.* 引用, 生成类级声明 (模仿 layout.py 的既有模式)
        attrs: set[str] = set()
        calls: set[str] = set()
        for n in names:
            for node in ast.walk(parse_method(qxt[n][1])):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                        and node.value.id == "self":
                    attrs.add(node.attr)
                    if isinstance(node.ctx, ast.Load):
                        calls.add(node.attr)
        # 方法参数/局部名 (近似): 用于排除 self 以外的自由名检查
        declared = set(names)
        decl_lines: list[str] = []
        for a in sorted(attrs):
            if a in declared:
                continue
            if a in calls:
                decl_lines.append(f"    {a}: Callable[..., Any]")
            else:
                ann = ann_map.get(a, "Any")
                free = {x.id for x in ast.walk(parse_annotation(ann)) if isinstance(x, ast.Name)}
                if not free <= allowed:
                    ann = "Any"
                decl_lines.append(f"    {a}: {ann}")
        residual: set[str] = set()
        for n in names:
            fn = parse_method(qxt[n][1])
            local: set[str] = set()
            for node in ast.walk(fn):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    a = node.args
                    for arg in list(a.args) + list(a.posonlyargs) + list(a.kwonlyargs):
                        local.add(arg.arg)
                    if a.vararg:
                        local.add(a.vararg.arg)
                    if a.kwarg:
                        local.add(a.kwarg.arg)
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    local.add(node.id)
                if isinstance(node, ast.Import):
                    for a in node.names:
                        local.add((a.asname or a.name).split(".")[0])
                if isinstance(node, ast.ImportFrom):
                    for a in node.names:
                        local.add(a.asname or a.name)
                if isinstance(node, ast.ExceptHandler) and node.name:
                    local.add(node.name)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    local.add(node.name)
            for node in ast.walk(fn):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) \
                        and node.id not in local and node.id not in allowed \
                        and not node.id.startswith("self"):
                    residual.add(node.id)
        extra_ok: set[str] = set()
        if mod in EXTRA_IMPORTS:
            for node in ast.parse(EXTRA_IMPORTS[mod]).body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for a in node.names:
                        extra_ok.add(a.asname or a.name)
        if residual - extra_ok:
            raise SystemExit(f"{mod}: 存在无法解析的模块级名字, 请补 import: {sorted(residual - extra_ok)}")

        header = (
            f'"""{MODULE_DOCSTRINGS[mod]}\n'
            "\n"
            "本模块由 tui.py 的 QxtTUI 拆分而来, 方法体逐行原样迁移 (无逻辑改动)。\n"
            "模块级常量/工具/小类集中在 `tuan_cli.tui.common`, 由 `from .common import *`\n"
            "注入到本模块命名空间, 因此方法体内对模块级名字的引用保持不变。\n"
            '"""\n'
            "\n"
            "from __future__ import annotations\n"
            "\n"
            "from .common import *  # noqa: F401,F403\n"
            "\n"
            + EXTRA_IMPORTS.get(mod, "")
            + "\n"
            "\n"
            f"class {clsname}:\n"
            f'    """{MODULE_DOCSTRINGS[mod]}"""\n'
            "\n"
        )
        if decl_lines:
            header += "    # ---- 跨 mixin 共享实例属性/方法 (纯声明, 运行期不赋值) ----\n"
            header += "\n".join(decl_lines) + "\n\n"
        body = "\n\n".join(indent4(m) for m in methods_src)
        (TUI / mod).write_text(header + body + "\n", encoding="utf-8")
        print(f"  生成 {mod}: {clsname} ({len(names)} 方法, {len((header + body).splitlines())} 行)")

    # ---- 4) 改写 tui.py: 删除已抽取方法 + 换类头 + 加 mixin import ----
    starts = line_starts(src)
    spans: list[tuple[int, int]] = []
    for name, (node, _t) in qxt.items():
        if name == "__init__":
            continue
        s, e = node_span(src, starts, node)
        spans.append((s, e))
    spans.sort(reverse=True)
    out = src
    for s, e in spans:
        out = out[:s] + out[e:]
    # 类头: class QxtTUI: -> 继承全部 mixin
    old_head = "class QxtTUI:"
    assert out.count(old_head) == 1
    new_head = ("class QxtTUI(StateMixin, RenderMixin, LayoutMixin, InteractMixin,\n"
                "             SlashMenuMixin, PanelsMixin, SloganMixin, LifecycleMixin):")
    out = out.replace(old_head, new_head, 1)
    # mixin import 插到 runtime_slogans import 之后
    anchor = "from .runtime_slogans import RuntimeSloganEngine\n"
    assert out.count(anchor) == 1
    out = out.replace(anchor, anchor + MIXIN_IMPORTS, 1)
    tui_path.write_text(out, encoding="utf-8")
    print(f"tui.py 重写完成: {len(src.splitlines())} -> {len(out.splitlines())} 行")


if __name__ == "__main__":
    main()
